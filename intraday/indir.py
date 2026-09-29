"""Geçmiş veri indirme: takvim -> evren -> günlük barlar -> ön filtre ->
yalnızca gereken günler için dakikalık barlar.

API bütçesi:
  * Günlük barlar tüm evren için ucuzdur (sembol başına ~150 bar).
  * Dakikalık bar yalnızca (a) günlük ön filtreyi geçen aday sembol-günler ve
    (b) o aday günün göreli hacim tabanı için gereken önceki N seans
    için çekilir. (b) olmadan "aynı saate kadarki hacim" hesaplanamaz.
  * Karşılaştırma akışı (SIP) dakikalık barları yalnızca aday günler için
    çekilir (IEX/SIP hacim oranı için).

Günlük ön filtre KAYIPSIZDIR: dakika seviyesinde geçebilecek hiçbir
sembol-günü elemez (bkz. `on_filtre`). Aynı günün günlük barı yalnızca
"hangi veriyi indireyim" kararında kullanılır, tarayıcı kararında asla.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from intraday import depo as depo_mod
from intraday.alpaca import AlpacaIstemci, ErisimYok
from intraday.depo import Depo
from intraday.evren import EvrenSonucu, evren_kaydet, evren_olustur, evren_yukle
from intraday.hesap import split_carpani
from intraday.zaman import ET, UTC, Seans, et_saat, takvimden_seanslar, utc_parse

logger = logging.getLogger(__name__)


# -- yardımcılar ----------------------------------------------------------


def _alpaca_bar(b: dict) -> dict:
    return {"t": utc_parse(b["t"]), "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}


def gunluk_sozluk(barlar: dict[str, list[dict]]) -> dict[str, dict[date, dict]]:
    """{sembol: [bar]} -> {sembol: {ET tarihi: bar}}"""
    return {s: {et_saat(b["t"]).date(): b for b in liste} for s, liste in barlar.items()}


def ay_once(gun: date, ay: int) -> date:
    y, m = divmod(gun.year * 12 + gun.month - 1 - ay, 12)
    return date(y, m + 1, min(gun.day, calendar.monthrange(y, m + 1)[1]))


@dataclass
class OnFiltreSonucu:
    adaylar: dict[date, set[str]] = field(default_factory=dict)
    # sıralı huni: her adımda elenen sembol-gün sayısı
    huni: dict[str, int] = field(default_factory=dict)
    toplam_sembol_gun: int = 0
    ort_hacim: dict[tuple[str, date], float] = field(default_factory=dict)
    onceki_kapanis: dict[tuple[str, date], float] = field(default_factory=dict)


def split_faktorleri(
    ham: dict[str, dict[date, dict]], duz: dict[str, dict[date, dict]]
) -> dict[str, dict[date, float]]:
    sonuc: dict[str, dict[date, float]] = {}
    for s, gunler in ham.items():
        d = duz.get(s, {})
        sonuc[s] = {}
        for g, b in gunler.items():
            f = split_carpani(b["c"], d[g]["c"]) if g in d else None
            sonuc[s][g] = f if f else 1.0
    return sonuc


def on_filtre(
    semboller: list[str],
    tarama_seanslari: list[Seans],
    tum_seanslar: list[Seans],
    gunluk_ham: dict[str, dict[date, dict]],
    faktor: dict[str, dict[date, float]],
    tcfg: dict,
) -> OnFiltreSonucu:
    """Kayıpsız günlük ön filtre.

    Bir (sembol, D) aday olur ancak ve ancak:
      1. D'de SIP günlük barı var ve önceki seans kapanışı biliniyor,
      2. D'den ÖNCEKİ N seansın ortalama günlük hacmi (split düzeltmeli)
         >= min_gunluk_hacim  (seans başında bilinir -> lookahead yok),
      3. D'nin [low, high] aralığı [fiyat_min, fiyat_max] ile kesişiyor
         (gün içinde hiç aralığa girmeyen hisse hiçbir dakikada geçemez),
      4. D'nin high'ı (iki yönlüde low'u da) değişim eşiğine ulaşıyor.
    3 ve 4 aynı günün verisini kullanır ama yalnızca indirme kararı içindir:
    geçemeyeceği kesin olanı atar, geçebilecek olanı atmaz.
    """
    sonuc = OnFiltreSonucu()
    for ad in ("veri_yok", "onceki_kapanis_yok", "gecmis_yetersiz", "ort_hacim",
               "fiyat_araligi", "degisim"):
        sonuc.huni[ad] = 0
    indeks = {s.gun: i for i, s in enumerate(tum_seanslar)}
    n = int(tcfg["goreli_hacim_gun"])
    min_gun = int(tcfg["goreli_hacim_min_gun"])
    esik = float(tcfg["min_gun_ici_degisim_pct"]) / 100.0

    for seans in tarama_seanslari:
        D = seans.gun
        i = indeks[D]
        onceki_gunler = [s.gun for s in tum_seanslar[max(0, i - n) : i]]
        for sembol in semboller:
            sonuc.toplam_sembol_gun += 1
            gunler = gunluk_ham.get(sembol, {})
            bar = gunler.get(D)
            if bar is None:
                sonuc.huni["veri_yok"] += 1
                continue
            onceki = tum_seanslar[i - 1].gun if i > 0 else None
            if onceki is None or onceki not in gunler:
                sonuc.huni["onceki_kapanis_yok"] += 1
                continue
            fD = faktor[sembol].get(D, 1.0)
            # D günü split olduysa önceki kapanışı D cinsine çevir
            # (fiyat için ters oran: hacim * f(d)/f(D), fiyat * f(D)/f(d))
            pc = gunler[onceki]["c"] * fD / faktor[sembol].get(onceki, 1.0)
            hacimler = [
                gunler[g]["v"] * faktor[sembol].get(g, 1.0) / fD
                for g in onceki_gunler
                if g in gunler
            ]
            if len(hacimler) < min_gun:
                sonuc.huni["gecmis_yetersiz"] += 1
                continue
            ort = sum(hacimler) / len(hacimler)
            if ort < float(tcfg["min_gunluk_hacim"]):
                sonuc.huni["ort_hacim"] += 1
                continue
            if bar["h"] < float(tcfg["fiyat_min"]) or bar["l"] > float(tcfg["fiyat_max"]):
                sonuc.huni["fiyat_araligi"] += 1
                continue
            yukari = bar["h"] / pc - 1.0 >= esik
            asagi = tcfg["degisim_yonu"] == "iki_yonlu" and (1.0 - bar["l"] / pc) >= esik
            if not (yukari or asagi):
                sonuc.huni["degisim"] += 1
                continue
            sonuc.adaylar.setdefault(D, set()).add(sembol)
            sonuc.ort_hacim[(sembol, D)] = ort
            sonuc.onceki_kapanis[(sembol, D)] = pc
    return sonuc


def taban_gunleri(
    sembol: str,
    D: date,
    tum_seanslar: list[Seans],
    gunluk_ham: dict[str, dict[date, dict]],
    tcfg: dict,
) -> list[Seans]:
    """D için göreli hacim tabanına girecek önceki seanslar (en yeni N tanesi).

    Sembolün SIP günlük barı olmayan günler (listelenmemiş/işlem görmemiş)
    ve istenirse yarım günler atlanır.
    """
    n = int(tcfg["goreli_hacim_gun"])
    yarim_disla = bool(tcfg["goreli_hacim_yarim_gunleri_dislama"])
    gunler = gunluk_ham.get(sembol, {})
    sonuc: list[Seans] = []
    for s in reversed(tum_seanslar):
        if s.gun >= D:
            continue
        if yarim_disla and s.yarim_gun:
            continue
        if s.gun not in gunler:
            continue
        sonuc.append(s)
        if len(sonuc) == n:
            break
    return list(reversed(sonuc))


# -- ana indirme akışı -----------------------------------------------------


@dataclass
class IndirmeSonucu:
    evren: EvrenSonucu
    tum_seanslar: list[Seans]
    tarama_seanslari: list[Seans]
    gunluk_ham: dict[str, dict[date, dict]]
    faktor: dict[str, dict[date, float]]
    on: OnFiltreSonucu
    gunluk_feed: str
    karsilastirma_feed: str | None
    uyarilar: list[str]
    istek_sayisi: int = 0


class Indirici:
    def __init__(self, istemci: AlpacaIstemci, depo: Depo, cfg: dict):
        self.api = istemci
        self.depo = depo
        self.cfg = cfg
        self.uyarilar: list[str] = []

    def takvim(self, bas: date, bit: date) -> list[Seans]:
        yol = self.depo.takvim_yolu(bas.isoformat(), bit.isoformat())
        veri = depo_mod.json_oku(yol, None)
        if veri is None:
            veri = self.api.takvim(bas.isoformat(), bit.isoformat())
            depo_mod.json_yaz(yol, veri)
        return takvimden_seanslar(veri)

    def evren(self, bugun: date) -> EvrenSonucu:
        dizin = self.depo.evren_dizini()
        mevcut = evren_yukle(dizin, bugun)
        if mevcut is not None:
            logger.info("Evren bugün zaten güncellenmiş: %d hisse", len(mevcut.kalan))
            return mevcut
        borsa = self.cfg["tarayici"]["borsa"]
        sonuc = evren_olustur(self.api.varliklar(borsa), borsa, self.cfg["evren"], bugun)
        evren_kaydet(sonuc, dizin)
        logger.info("Evren: %d varlık, %d hisse kaldı", sonuc.toplam, len(sonuc.kalan))
        return sonuc

    def gunluk(self, semboller: list[str], bas: date, bit: date, feed: str, adj: str):
        yol = self.depo.gunluk_yolu(feed, adj, bas.isoformat(), bit.isoformat())
        eksik = sorted(set(semboller) - depo_mod.manifest_oku(yol))
        mevcut = depo_mod.barlari_oku(yol)
        if eksik:
            logger.info("Günlük bar (%s/%s): %d sembol indiriliyor", feed, adj, len(eksik))
            yeni = self.api.barlar(
                eksik, "1Day",
                datetime.combine(bas, time(0), tzinfo=ET).astimezone(UTC),
                datetime.combine(bit, time(23, 59), tzinfo=ET).astimezone(UTC),
                feed=feed, adjustment=adj,
            )
            for s, liste in yeni.items():
                mevcut[s] = [_alpaca_bar(b) for b in liste]
            depo_mod.barlari_yaz(yol, mevcut)
            depo_mod.manifest_yaz(yol, depo_mod.manifest_oku(yol) | set(eksik))
        return gunluk_sozluk(mevcut)

    def dakika(self, seans: Seans, semboller: set[str], feed: str) -> None:
        yol = self.depo.dakika_yolu(feed, seans.gun.isoformat())
        eksik = semboller - depo_mod.manifest_oku(yol)
        if not eksik:
            return
        mevcut = depo_mod.barlari_oku(yol)
        yeni = self.api.barlar(
            eksik, "1Min", seans.acilis, seans.kapanis - timedelta(minutes=1),
            feed=feed, adjustment="raw",
        )
        for s, liste in yeni.items():
            # yalnızca düzenli seans
            mevcut[s] = [b for b in map(_alpaca_bar, liste) if seans.iceriyor(b["t"])]
        depo_mod.barlari_yaz(yol, mevcut)
        depo_mod.manifest_yaz(yol, depo_mod.manifest_oku(yol) | eksik)

    def calistir(self, bugun: date) -> IndirmeSonucu:
        vcfg, tcfg = self.cfg["veri"], self.cfg["tarayici"]
        # SIP'in son 15 dakikası ücretsiz planda kısıtlı: dünü bitiş al.
        bitis = bugun - timedelta(days=1)
        baslangic = ay_once(bitis, int(vcfg["gecmis_ay"]))
        # göreli hacim tabanı için baştan ~N seans + tampon
        takvim_bas = baslangic - timedelta(days=int(tcfg["goreli_hacim_gun"]) * 2 + 10)
        tum = self.takvim(takvim_bas, bitis)
        tarama = [s for s in tum if baslangic <= s.gun <= bitis]
        evren = self.evren(bugun)

        gunluk_feed = vcfg.get("karsilastirma_feed") or vcfg["tarama_feed"]
        karsi = vcfg.get("karsilastirma_feed") or None
        try:
            ham = self.gunluk(evren.kalan, takvim_bas, bitis, gunluk_feed, "raw")
            duz = self.gunluk(evren.kalan, takvim_bas, bitis, gunluk_feed, "split")
        except ErisimYok as exc:
            if gunluk_feed == vcfg["tarama_feed"]:
                raise
            self.uyarilar.append(
                f"{gunluk_feed.upper()} günlük veriye erişilemedi ({exc}); günlük hacim "
                f"{vcfg['tarama_feed'].upper()} ile hesaplandı -> 'min_gunluk_hacim' "
                "ve IEX/toplam hacim oranı ANLAMSIZ."
            )
            gunluk_feed, karsi = vcfg["tarama_feed"], None
            ham = self.gunluk(evren.kalan, takvim_bas, bitis, gunluk_feed, "raw")
            duz = self.gunluk(evren.kalan, takvim_bas, bitis, gunluk_feed, "split")
        faktor = split_faktorleri(ham, duz)

        on = on_filtre(evren.kalan, tarama, tum, ham, faktor, tcfg)
        logger.info("Ön filtre: %d aday sembol-gün",
                    sum(len(v) for v in on.adaylar.values()))

        # dakikalık ihtiyaç: aday gün + taban günleri
        ihtiyac: dict[date, set[str]] = {}
        for D, semboller in on.adaylar.items():
            for s in semboller:
                ihtiyac.setdefault(D, set()).add(s)
                for tg in taban_gunleri(s, D, tum, ham, tcfg):
                    ihtiyac.setdefault(tg.gun, set()).add(s)
        seans_map = {s.gun: s for s in tum}
        for g in sorted(ihtiyac):
            logger.info("Dakikalık %s: %d sembol (%s)", g, len(ihtiyac[g]), vcfg["tarama_feed"])
            self.dakika(seans_map[g], ihtiyac[g], vcfg["tarama_feed"])
        if karsi and karsi != vcfg["tarama_feed"]:
            for D in sorted(on.adaylar):
                try:
                    self.dakika(seans_map[D], on.adaylar[D], karsi)
                except ErisimYok as exc:
                    self.uyarilar.append(
                        f"{karsi.upper()} dakikalık veriye erişilemedi ({exc}); "
                        "IEX/SIP dakika karşılaştırması yapılmadı."
                    )
                    karsi = None
                    break

        return IndirmeSonucu(
            evren=evren, tum_seanslar=tum, tarama_seanslari=tarama, gunluk_ham=ham,
            faktor=faktor, on=on, gunluk_feed=gunluk_feed, karsilastirma_feed=karsi,
            uyarilar=self.uyarilar, istek_sayisi=self.api.istek_sayisi,
        )
