"""Gün içi tarayıcı.

`SembolGunTarayici` akış (streaming) mantığıyla çalışır: barlar sırayla
verilir, her bar yalnızca o ana kadarki veriyi görür. Aynı sınıf Aşama 3'te
canlı websocket barlarıyla beslenecek -> backtest ve canlı aynı kod yolu.

Karar anı = bar kapanışı (bar başlangıcı + 1 dk). Spread için kullanılan
quote o andan SONRA olamaz.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Protocol

from intraday import depo as depo_mod
from intraday.alpaca import ErisimYok
from intraday.depo import Depo
from intraday.hesap import (
    degisim_gecti,
    degisim_pct,
    goreli_hacim,
    kumulatif_hacim_profili,
    ortalama_profil,
    spread_pct,
)
from intraday.indir import IndirmeSonucu, taban_gunleri
from intraday.zaman import Seans, dakika_sonu

logger = logging.getLogger(__name__)

FILTRELER = ("fiyat", "degisim", "goreli_hacim")


@dataclass
class DakikaDurumu:
    t: datetime  # bar başlangıcı (UTC)
    karar_ani: datetime
    fiyat: float
    kumulatif_hacim: float
    degisim: Optional[float]
    goreli_hacim: Optional[float]
    gecti: dict[str, bool]

    @property
    def on_filtreler_gecti(self) -> bool:
        return all(self.gecti.values())


class SembolGunTarayici:
    """Tek sembol, tek seans. Spread hariç filtreleri bar bar değerlendirir."""

    def __init__(
        self,
        sembol: str,
        seans: Seans,
        onceki_kapanis: float,
        taban_profil: list[Optional[float]],
        tcfg: dict,
    ):
        self.sembol = sembol
        self.seans = seans
        self.onceki_kapanis = onceki_kapanis
        self.taban = taban_profil
        self.cfg = tcfg
        self._kum = 0.0
        self._son_t: Optional[datetime] = None

    def bar_isle(self, bar: dict) -> Optional[DakikaDurumu]:
        t = bar["t"]
        if not self.seans.iceriyor(t):
            return None
        if self._son_t is not None and t <= self._son_t:
            raise ValueError("barlar zaman sırasıyla verilmeli")
        self._son_t = t
        self._kum += float(bar["v"])
        k = self.seans.acilistan_dakika(t)
        fiyat = float(bar["c"])
        deg = degisim_pct(fiyat, self.onceki_kapanis)
        rv = goreli_hacim(self._kum, self.taban[k] if k < len(self.taban) else None)
        c = self.cfg
        gecti = {
            "fiyat": float(c["fiyat_min"]) <= fiyat <= float(c["fiyat_max"]),
            "degisim": degisim_gecti(deg, float(c["min_gun_ici_degisim_pct"]), c["degisim_yonu"]),
            "goreli_hacim": rv is not None and rv >= float(c["min_goreli_hacim"]),
        }
        return DakikaDurumu(t, dakika_sonu(t), fiyat, self._kum, deg, rv, gecti)

    def spread_gecti(self, quote: Optional[dict]) -> tuple[Optional[float], bool]:
        if quote is None:
            return None, False
        sp = spread_pct(quote.get("bp"), quote.get("ap"))
        return sp, sp is not None and sp <= float(self.cfg["max_spread_pct"])


# -- quote kaynağı (backtest: REST + önbellek; canlı: websocket) ----------


class QuoteKaynagi(Protocol):
    def __call__(self, sembol: str, an: datetime, feed: str) -> Optional[dict]: ...


class OnbellekliQuote:
    """Alpaca REST'ten `an` öncesi son quote; gün/feed başına JSON önbellek."""

    def __init__(self, istemci, depo: Depo, pencere_sn: int):
        self.api = istemci
        self.depo = depo
        self.pencere = timedelta(seconds=pencere_sn)
        self._cache: dict[tuple[str, str], dict] = {}
        self._kirli: set[tuple[str, str]] = set()
        self.erisimsiz: set[str] = set()  # 401/403 veren akışlar (ör. planda SIP yok)

    def _tablo(self, feed: str, gun: str) -> dict:
        k = (feed, gun)
        if k not in self._cache:
            self._cache[k] = depo_mod.json_oku(self.depo.quote_yolu(feed, gun), {})
        return self._cache[k]

    def __call__(self, sembol: str, an: datetime, feed: str) -> Optional[dict]:
        gun = an.date().isoformat()  # UTC tarihi; yalnızca dosya adı için
        tablo = self._tablo(feed, gun)
        anahtar = f"{sembol}|{int(an.timestamp())}"
        if anahtar not in tablo:
            if feed in self.erisimsiz:
                return None
            try:
                q = self.api.son_quote(sembol, an - self.pencere, an, feed)
            except ErisimYok:
                self.erisimsiz.add(feed)
                return None
            tablo[anahtar] = {"bp": q.get("bp"), "ap": q.get("ap"), "t": q.get("t")} if q else None
            self._kirli.add((feed, gun))
        return tablo[anahtar]

    def kaydet(self) -> None:
        for feed, gun in self._kirli:
            depo_mod.json_yaz(self.depo.quote_yolu(feed, gun), self._cache[(feed, gun)])
        self._kirli.clear()


# -- geçmiş veri sürücüsü ------------------------------------------------


@dataclass
class Takilma:
    sembol: str
    gun: date
    t: datetime
    karar_ani: datetime
    fiyat: float
    degisim: float
    goreli_hacim: float
    spread: float
    feed: str  # spread'in hangi akıştan geldiği


@dataclass
class SembolGunOzet:
    sembol: str
    gun: date
    durum: str  # "tarandi" | "taban_yetersiz" | "dakika_verisi_yok"
    bar_sayisi: int = 0
    tek_basina: dict[str, bool] = field(default_factory=dict)  # filtre -> herhangi dakikada geçti mi
    sirali: dict[str, bool] = field(default_factory=dict)      # kümülatif huni
    on_gecen_dakika: int = 0
    quote_sorgu: dict[str, int] = field(default_factory=dict)
    quote_yok: dict[str, int] = field(default_factory=dict)
    spread_ornek: dict[str, list[float]] = field(default_factory=dict)
    spread_dogrulanamadi: dict[str, bool] = field(default_factory=dict)
    takilma: dict[str, Optional[Takilma]] = field(default_factory=dict)
    tarama_hacmi: float = 0.0
    karsilastirma_hacmi: Optional[float] = None
    karsilastirma_bar_sayisi: Optional[int] = None


def _sirali_huni(durumlar: list[DakikaDurumu]) -> dict[str, bool]:
    sonuc = {}
    for i, ad in enumerate(FILTRELER):
        gerekli = FILTRELER[: i + 1]
        sonuc[ad] = any(all(d.gecti[g] for g in gerekli) for d in durumlar)
    return sonuc


def sembol_gun_tara(
    sembol: str,
    seans: Seans,
    onceki_kapanis: float,
    bugun_barlar: list[dict],
    taban_barlari: list[tuple[Seans, list[dict], float]],
    tcfg: dict,
    quote: Callable[[str, datetime, str], Optional[dict]],
    spread_feedleri: list[str],
) -> SembolGunOzet:
    """Bir aday sembol-günü baştan sona, dakika dakika tarar.

    taban_barlari: [(seans, barlar, hacim_carpani)] -- D'den önceki günler.
    """
    oz = SembolGunOzet(sembol, seans.gun, "tarandi", bar_sayisi=len(bugun_barlar))
    if len(taban_barlari) < int(tcfg["goreli_hacim_min_gun"]):
        oz.durum = "taban_yetersiz"
        return oz
    if not bugun_barlar:
        oz.durum = "dakika_verisi_yok"
        return oz
    profiller = [kumulatif_hacim_profili(b, s, c) for s, b, c in taban_barlari]
    taban = ortalama_profil(profiller, seans.dakika_sayisi)
    tar = SembolGunTarayici(sembol, seans, onceki_kapanis, taban, tcfg)

    max_sorgu = int(tcfg["max_quote_sorgu_sembol_gun"])
    for f in spread_feedleri:
        oz.quote_sorgu[f] = 0
        oz.quote_yok[f] = 0
        oz.spread_ornek[f] = []
        oz.spread_dogrulanamadi[f] = False
        oz.takilma[f] = None

    durumlar: list[DakikaDurumu] = []
    for bar in bugun_barlar:
        d = tar.bar_isle(bar)
        if d is None:
            continue
        durumlar.append(d)
        oz.tarama_hacmi = d.kumulatif_hacim
        if not d.on_filtreler_gecti:
            continue
        oz.on_gecen_dakika += 1
        for f in spread_feedleri:
            if oz.takilma[f] is not None:
                continue
            if oz.quote_sorgu[f] >= max_sorgu:
                oz.spread_dogrulanamadi[f] = True
                continue
            q = quote(sembol, d.karar_ani, f)
            oz.quote_sorgu[f] += 1
            sp, ok = tar.spread_gecti(q)
            if q is None or sp is None:
                oz.quote_yok[f] += 1
            else:
                oz.spread_ornek[f].append(sp)
            if ok:
                oz.takilma[f] = Takilma(sembol, seans.gun, d.t, d.karar_ani, d.fiyat,
                                        d.degisim, d.goreli_hacim, sp, f)
                oz.spread_dogrulanamadi[f] = False

    oz.tek_basina = {ad: any(d.gecti[ad] for d in durumlar) for ad in FILTRELER}
    oz.sirali = _sirali_huni(durumlar)
    return oz


def gecmisi_tara(
    ind: IndirmeSonucu,
    depo: Depo,
    cfg: dict,
    quote: Callable[[str, datetime, str], Optional[dict]],
) -> list[SembolGunOzet]:
    tcfg, vcfg = cfg["tarayici"], cfg["veri"]
    tarama_feed = vcfg["tarama_feed"]
    spread_feedleri = [tarama_feed] + (
        [ind.karsilastirma_feed]
        if ind.karsilastirma_feed and ind.karsilastirma_feed != tarama_feed
        else []
    )
    seans_map = {s.gun: s for s in ind.tum_seanslar}
    dakika_cache: dict[tuple[str, date], dict[str, list[dict]]] = {}

    def dakika(feed: str, g: date) -> dict[str, list[dict]]:
        k = (feed, g)
        if k not in dakika_cache:
            if len(dakika_cache) > 64:
                dakika_cache.clear()
            dakika_cache[k] = depo_mod.barlari_oku(depo.dakika_yolu(feed, g.isoformat()))
        return dakika_cache[k]

    ozetler: list[SembolGunOzet] = []
    for D in sorted(ind.on.adaylar):
        seans = seans_map[D]
        for s in sorted(ind.on.adaylar[D]):
            fD = ind.faktor[s].get(D, 1.0)
            taban = [
                (tg, dakika(tarama_feed, tg.gun).get(s, []), ind.faktor[s].get(tg.gun, 1.0) / fD)
                for tg in taban_gunleri(s, D, ind.tum_seanslar, ind.gunluk_ham, tcfg)
            ]
            oz = sembol_gun_tara(
                s, seans, ind.on.onceki_kapanis[(s, D)],
                dakika(tarama_feed, D).get(s, []), taban, tcfg, quote, spread_feedleri,
            )
            if ind.karsilastirma_feed:
                kb = dakika(ind.karsilastirma_feed, D).get(s, [])
                oz.karsilastirma_hacmi = sum(float(b["v"]) for b in kb)
                oz.karsilastirma_bar_sayisi = len(kb)
            ozetler.append(oz)
        if hasattr(quote, "kaydet"):
            quote.kaydet()
    return ozetler
