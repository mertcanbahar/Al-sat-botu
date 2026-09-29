"""Tarayıcı raporu: backtest/results/intraday/scanner_report.md (+ takılma CSV)."""
from __future__ import annotations

import csv
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from intraday.hesap import fiyat_dilimi
from intraday.indir import IndirmeSonucu
from intraday.tarayici import FILTRELER, SembolGunOzet
from intraday.zaman import UTC, et_saat, tr_saat


def _yuzde(a: float, b: float) -> str:
    return f"%{100.0 * a / b:.1f}" if b else "—"


def _yuzdelik(degerler: list[float], p: float) -> Optional[float]:
    if not degerler:
        return None
    s = sorted(degerler)
    k = (len(s) - 1) * p
    alt = int(k)
    ust = min(alt + 1, len(s) - 1)
    return s[alt] + (s[ust] - s[alt]) * (k - alt)


def _f(x: Optional[float], fmt: str = "{:.2f}") -> str:
    return fmt.format(x) if x is not None else "—"


def gunluk_istatistik(sayilar: list[int]) -> dict:
    if not sayilar:
        return {"ort": None, "medyan": None, "min": None, "maks": None}
    return {
        "ort": statistics.fmean(sayilar),
        "medyan": statistics.median(sayilar),
        "min": min(sayilar),
        "maks": max(sayilar),
    }


def rapor_uret(
    ind: IndirmeSonucu,
    ozetler: list[SembolGunOzet],
    cfg: dict,
    rapor_yolu: Path,
    erisimsiz_quote_feedleri: set[str],
    olusturma: datetime | None = None,
) -> str:
    tcfg, vcfg, rcfg = cfg["tarayici"], cfg["veri"], cfg["rapor"]
    tf = vcfg["tarama_feed"]
    kf = ind.karsilastirma_feed if ind.karsilastirma_feed != tf else None
    if kf in erisimsiz_quote_feedleri:
        kf_quote = None
    else:
        kf_quote = kf
    dilimler = rcfg["fiyat_dilimleri"]
    olusturma = olusturma or datetime.now(UTC)
    L: list[str] = []
    a = L.append

    seanslar = ind.tarama_seanslari
    a("# Gün içi tarayıcı raporu (Aşama 1)\n")
    a(f"- Oluşturma: {olusturma:%Y-%m-%d %H:%M} UTC / "
      f"{tr_saat(olusturma):%Y-%m-%d %H:%M} TR")
    if seanslar:
        a(f"- Dönem: {seanslar[0].gun} → {seanslar[-1].gun} "
          f"({len(seanslar)} seans, {sum(s.yarim_gun for s in seanslar)} yarım gün)")
    a(f"- Tarama akışı: **{tf.upper()}** | günlük/toplam hacim akışı: "
      f"**{ind.gunluk_feed.upper()}** | karşılaştırma akışı: **{(kf or 'yok').upper()}**")
    istenen = (vcfg.get("karsilastirma_feed") or "").lower()
    if istenen and istenen != tf:
        durum = lambda ok: "**VAR**" if ok else "**YOK**"
        a(f"- Geçmiş {istenen.upper()} erişimi (bu plan): günlük bar "
          f"{durum(ind.gunluk_feed == istenen)}, dakikalık bar "
          f"{durum(ind.karsilastirma_feed == istenen)}, quote "
          f"{durum(ind.karsilastirma_feed == istenen and istenen not in erisimsiz_quote_feedleri)}")
    a(f"- API istek sayısı (bu koşu): {ind.istek_sayisi}")
    a("- Eşikler (`intraday/config.yaml`): " + ", ".join(
        f"{k}={tcfg[k]}" for k in ("fiyat_min", "fiyat_max", "min_gunluk_hacim",
                                   "min_goreli_hacim", "min_gun_ici_degisim_pct",
                                   "degisim_yonu", "max_spread_pct")))
    if ind.uyarilar:
        a("\n> **UYARILAR**")
        for u in ind.uyarilar:
            a(f"> - {u}")
    a("")

    # 1. evren ve huni -------------------------------------------------
    ev = ind.evren
    a("## 1. Evren ve filtre hunisi\n")
    a(f"Alpaca assets (exchange={tcfg['borsa']}, status=active, us_equity): "
      f"**{ev.toplam}** varlık → eleme sonrası **{len(ev.kalan)}** hisse "
      f"(evren tarihi {ev.tarih}).\n")
    a("| Eleme kuralı | Elenen | Örnekler |\n|---|---:|---|")
    for kural, liste in ev.elenen.items():
        a(f"| `{kural}` | {len(liste)} | {', '.join(liste[:8])} |")
    a("\nKurallar sırayla uygulanır, bir varlık ilk eşleşen kurala yazılır: "
      "(1) exchange/status/tradable, (2) sembolde `.`/`/` vb. özel karakter, "
      "(3) isim regex'leri (etf, warrant, right, unit, preferred), "
      "(4) 5 harfli Nasdaq sembollerinde 5. harf W/U/R/P. "
      "Regex'ler `intraday/config.yaml` → `evren`.\n")

    on = ind.on
    a(f"**Günlük ön filtre** (sembol-gün; {len(ev.kalan)} hisse × {len(seanslar)} seans "
      f"= {on.toplam_sembol_gun}):\n")
    a("| Adım (sıralı) | Elenen | Kalan |\n|---|---:|---:|")
    kalan = on.toplam_sembol_gun
    etiket = {
        "veri_yok": "O gün günlük bar yok (işlem yok/listelenmemiş)",
        "onceki_kapanis_yok": "Önceki seans kapanışı yok",
        "gecmis_yetersiz": f"Geçmiş < {tcfg['goreli_hacim_min_gun']} seans",
        "ort_hacim": f"Önceki {tcfg['goreli_hacim_gun']} seans ort. hacim < {tcfg['min_gunluk_hacim']:,}",
        "fiyat_araligi": f"Gün aralığı {tcfg['fiyat_min']}–{tcfg['fiyat_max']} USD'ye hiç girmiyor",
        "degisim": f"Gün içi hiçbir an %{tcfg['min_gun_ici_degisim_pct']} değişime ulaşmıyor",
    }
    for k, v in on.huni.items():
        kalan -= v
        a(f"| {etiket.get(k, k)} | {v:,} | {kalan:,} |")
    aday = sum(len(v) for v in on.adaylar.values())
    a(f"\n→ Dakikalık veriyle taranan aday sembol-gün: **{aday:,}**\n")

    taranan = [o for o in ozetler if o.durum == "tarandi"]
    durumlar = Counter(o.durum for o in ozetler)
    a("**Dakika seviyesi huni** (aday sembol-günler; \"geçti\" = gün içinde en az bir dakikada):\n")
    a("| Durum | Sembol-gün |\n|---|---:|")
    for d, n in durumlar.most_common():
        a(f"| {d} | {n:,} |")
    a("")
    a("| Filtre | Sıralı (öncekilerle birlikte) | Tek başına |\n|---|---:|---:|")
    for ad in FILTRELER:
        a(f"| {ad} | {sum(o.sirali.get(ad, False) for o in taranan):,} | "
          f"{sum(o.tek_basina.get(ad, False) for o in taranan):,} |")
    for f in [tf] + ([kf_quote] if kf_quote else []):
        a(f"| spread ≤ %{tcfg['max_spread_pct']} ({f.upper()} quote) | "
          f"{sum(o.takilma.get(f) is not None for o in taranan):,} | (hesaplanmadı*) |")
    a("\n\\* Spread yalnızca diğer filtreleri geçen dakikalarda sorgulanır (API bütçesi); "
      "tek başına spread oranı bu yüzden yok.\n")

    # 2. günlük takılma ------------------------------------------------
    def gunluk_sayilar(feed: Optional[str]) -> list[int]:
        c = Counter()
        for o in taranan:
            if feed is None:
                if o.on_gecen_dakika > 0:
                    c[o.gun] += 1
            elif o.takilma.get(feed) is not None:
                c[o.gun] += 1
        return [c.get(s.gun, 0) for s in seanslar]

    a("## 2. Günde tarayıcıya takılan hisse sayısı\n")
    a("Takılma = sembolün o gün TÜM filtreleri ilk kez geçtiği dakika (sembol başına günde 1). "
      "Takılmasız günler 0 olarak dahildir.\n")
    a("| Varyant | Ortalama | Medyan | Min | Maks |\n|---|---:|---:|---:|---:|")
    varyantlar = [(f"Tüm filtreler, spread {tf.upper()} (canlıya en yakın)", tf)]
    if kf_quote:
        varyantlar.append((f"Tüm filtreler, spread {kf_quote.upper()} (NBBO)", kf_quote))
    varyantlar.append(("Spread filtresi hariç", None))
    for ad, f in varyantlar:
        st = gunluk_istatistik(gunluk_sayilar(f))
        a(f"| {ad} | {_f(st['ort'])} | {_f(st['medyan'], '{:g}')} | "
          f"{_f(st['min'], '{:g}')} | {_f(st['maks'], '{:g}')} |")
    a("")

    ana = [o.takilma[tf] for o in taranan if o.takilma.get(tf)]

    # 3. saat dağılımı -------------------------------------------------
    a("## 3. Saatlere göre dağılım\n")
    a(f"İlk takılma anı (bar kapanışı), spread {tf.upper()} varyantı, n={len(ana)}. "
      "Not: TR (UTC+3, yaz saati yok) ile ET arasındaki fark ABD yaz/kış saatine göre "
      "7 ya da 8 saat; bu yüzden seans açılışı TR'de yazın 16:30, kışın 17:30.\n")
    tr_c = Counter(tr_saat(h.karar_ani).hour for h in ana)
    a("| TR saati | Takılma | Pay |\n|---|---:|---:|")
    for saat in sorted(tr_c):
        a(f"| {saat:02d}:00–{saat:02d}:59 | {tr_c[saat]} | {_yuzde(tr_c[saat], len(ana))} |")
    a("\nSeans açılışına göre (ET, 30 dk dilim):\n")
    et_c = Counter()
    for h in ana:
        e = et_saat(h.karar_ani)
        dk = (e.hour * 60 + e.minute) // 30 * 30
        et_c[dk] += 1
    a("| ET dilimi | Takılma | Pay |\n|---|---:|---:|")
    for dk in sorted(et_c):
        a(f"| {dk // 60:02d}:{dk % 60:02d} | {et_c[dk]} | {_yuzde(et_c[dk], len(ana))} |")
    a("")

    # 4. fiyat dilimleri ----------------------------------------------
    a("## 4. Fiyat dilimlerine göre dağılım\n")
    fd = Counter(fiyat_dilimi(h.fiyat, dilimler) for h in ana)
    a("| Fiyat (USD, takılma anı) | Takılma | Pay |\n|---|---:|---:|")
    for i in range(len(dilimler) - 1):
        k = f"{dilimler[i]:g}-{dilimler[i + 1]:g}"
        a(f"| {k} | {fd.get(k, 0)} | {_yuzde(fd.get(k, 0), len(ana))} |")
    a("")

    # 5. IEX yeterliliği ----------------------------------------------
    a(f"## 5. {tf.upper()} verisinin yeterliliği\n")
    oranlar, kapsama = [], []
    dilim_oran: dict[str, list[float]] = {}
    for o in taranan:
        if o.karsilastirma_hacmi:
            r = o.tarama_hacmi / o.karsilastirma_hacmi
            oranlar.append(r)
            pc = ind.on.onceki_kapanis.get((o.sembol, o.gun))
            if pc is not None:
                dilim_oran.setdefault(fiyat_dilimi(pc, dilimler) or "aralık dışı", []).append(r)
        if o.karsilastirma_bar_sayisi:
            kapsama.append(o.bar_sayisi / o.karsilastirma_bar_sayisi)
    if oranlar:
        a(f"**Hacim oranı** {tf.upper()} / {kf.upper()} (seans içi dakikalık toplam, "
          f"n={len(oranlar)} sembol-gün): medyan {_yuzde(_yuzdelik(oranlar, .5), 1)}, "
          f"p10 {_yuzde(_yuzdelik(oranlar, .1), 1)}, p90 {_yuzde(_yuzdelik(oranlar, .9), 1)}.\n")
        a("| Fiyat dilimi (önceki kapanış) | n | Medyan oran |\n|---|---:|---:|")
        for k in sorted(dilim_oran):
            a(f"| {k} | {len(dilim_oran[k])} | {_yuzde(_yuzdelik(dilim_oran[k], .5), 1)} |")
        a(f"\n**Dakika kapsaması**: {tf.upper()}'te bar olan dakika / {kf.upper()}'te bar olan "
          f"dakika — medyan {_yuzde(_yuzdelik(kapsama, .5), 1)}, "
          f"p10 {_yuzde(_yuzdelik(kapsama, .1), 1)}.\n")
    else:
        a("Karşılaştırma akışı olmadığı için hacim oranı hesaplanamadı.\n")

    a("| Quote akışı | Sorgulanan dakika | Quote yok / tek taraflı | Medyan spread | p90 spread |")
    a("|---|---:|---:|---:|---:|")
    for f in [tf] + ([kf_quote] if kf_quote else []):
        sorgu = sum(o.quote_sorgu.get(f, 0) for o in taranan)
        yok = sum(o.quote_yok.get(f, 0) for o in taranan)
        sp = [x for o in taranan for x in o.spread_ornek.get(f, [])]
        a(f"| {f.upper()} | {sorgu:,} | {yok:,} ({_yuzde(yok, sorgu)}) | "
          f"{_f(_yuzdelik(sp, .5), '%{:.2f}')} | {_f(_yuzdelik(sp, .9), '%{:.2f}')} |")
    dogrulanamadi = sum(o.spread_dogrulanamadi.get(tf, False) for o in taranan)
    a(f"\nSpread'i {tcfg['max_quote_sorgu_sembol_gun']} sorguda doğrulanamayan "
      f"(takılmadan kalan) sembol-gün: {dogrulanamadi}.")
    if erisimsiz_quote_feedleri:
        a(f"\nQuote erişimi olmayan akış(lar): {', '.join(sorted(erisimsiz_quote_feedleri))}.")

    a("\n**Değerlendirme:**\n")
    for satir in iex_degerlendirme(oranlar, taranan, tf, rcfg):
        a(f"- {satir}")
    a("")

    # 6. en sık 20 --------------------------------------------------
    n = int(rcfg["en_sik_n"])
    a(f"## 6. En sık takılan {n} sembol\n")
    sc = Counter(h.sembol for h in ana)
    a("| # | Sembol | İsim | Takıldığı gün |\n|---:|---|---|---:|")
    for i, (s, c) in enumerate(sc.most_common(n), 1):
        a(f"| {i} | {s} | {ev.isimler.get(s, '')} | {c} |")
    if ana:
        pay = sum(c for _, c in sc.most_common(n)) / len(ana)
        a(f"\nİlk {n} sembol tüm takılmaların {_yuzde(pay, 1)}'ini oluşturuyor.")
    a("")

    # 7. varsayımlar -------------------------------------------------
    a("## 7. Varsayımlar, bilinen eksikler, riskler\n")
    for v in varsayimlar(tcfg):
        a(f"- {v}")
    a("")

    metin = "\n".join(L) + "\n"
    rapor_yolu.parent.mkdir(parents=True, exist_ok=True)
    rapor_yolu.write_text(metin, encoding="utf-8")
    takilma_csv_yaz(rapor_yolu.with_name("scanner_hits.csv"), taranan)
    return metin


def iex_degerlendirme(oranlar: list[float], taranan: list[SembolGunOzet], tf: str, rcfg: dict) -> list[str]:
    """Veriden türetilen, eşikleri config'de olan açık hüküm cümleleri."""
    sonuc: list[str] = []
    esik_hacim = float(rcfg["iex_uyari_hacim_orani"])
    esik_quote = float(rcfg["iex_uyari_quote_yok_pct"])
    if oranlar:
        med = _yuzdelik(oranlar, .5)
        if med < esik_hacim:
            sonuc.append(
                f"**{tf.upper()} hacmi toplam hacmin medyan %{100 * med:.1f}'i — %{100 * esik_hacim:.0f} "
                f"eşiğinin altında. Küçük hisselerde {tf.upper()} barları seyrek; fiyat ve "
                "özellikle göreli hacim YANILTICI olabilir.** Göreli hacim oran olarak "
                f"{tf.upper()}'in kendi geçmişiyle kıyaslandığı için ölçek hatası büyük ölçüde "
                "sadeleşir, ama gürültü çok yüksektir.")
        else:
            sonuc.append(f"{tf.upper()} hacim payı medyan %{100 * med:.1f} (eşik %{100 * esik_hacim:.0f}).")
    sorgu = sum(o.quote_sorgu.get(tf, 0) for o in taranan)
    yok = sum(o.quote_yok.get(tf, 0) for o in taranan)
    if sorgu:
        oran = 100.0 * yok / sorgu
        if oran > esik_quote:
            sonuc.append(
                f"**Sorgulanan dakikaların %{oran:.1f}'inde {tf.upper()} quote'u yok ya da tek taraflı "
                f"(eşik %{esik_quote:.0f}). {tf.upper()} quote'u yalnızca {tf.upper()}'in kendi "
                "defterinin en iyi alış/satışıdır, NBBO değildir: küçük hisselerde spread'i "
                "olduğundan geniş gösterir ya da hiç göstermez. Canlıda spread filtresi bu akışla "
                "güvenilir değil.**")
        else:
            sonuc.append(f"{tf.upper()} quote yokluğu %{oran:.1f} (eşik %{esik_quote:.0f}).")
    if not sonuc:
        sonuc.append("Yeterlilik değerlendirmesi için veri yok.")
    return sonuc


def takilma_csv_yaz(yol: Path, taranan: list[SembolGunOzet]) -> None:
    with open(yol, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["gun", "sembol", "spread_feed", "karar_ani_utc", "karar_ani_tr",
                    "fiyat", "degisim_pct", "goreli_hacim", "spread_pct"])
        for o in taranan:
            for feed, h in o.takilma.items():
                if h is None:
                    continue
                w.writerow([h.gun, h.sembol, feed, h.karar_ani.strftime("%Y-%m-%d %H:%M"),
                            tr_saat(h.karar_ani).strftime("%Y-%m-%d %H:%M"),
                            f"{h.fiyat:.4f}", f"{h.degisim:.2f}", f"{h.goreli_hacim:.2f}",
                            f"{h.spread:.3f}"])


def varsayimlar(tcfg: dict) -> list[str]:
    n, mn = tcfg["goreli_hacim_gun"], tcfg["goreli_hacim_min_gun"]
    return [
        "**Hayatta kalma yanlılığı:** evren BUGÜNKÜ aktif Nasdaq listesidir; son 6 ayda "
        "listeden çıkan / iflas eden / sembol değiştiren hisseler yok. 2–10 USD aralığında "
        "bu etki küçük değildir, takılma sayısı olduğundan az görünebilir.",
        f"**min_gunluk_hacim** = önceki {n} seansın ortalama günlük hacmi (toplam/SIP, split "
        "düzeltmeli). Bugünkü kümülatif hacim DEĞİL. Seans başında bilindiği için lookahead yok.",
        f"**Göreli hacim** = bugün açılıştan bu dakikaya kadarki hacim / önceki {n} seansta aynı "
        "dakikaya kadarki hacmin ortalaması (tarama akışıyla, split düzeltmeli). Yarım günler "
        f"tabandan çıkarılır. En az {mn} geçmiş seans yoksa hesaplanmaz.",
        "**Gün içi değişim** = son dakika kapanışı / önceki seans kapanışı − 1 (varsayılan yalnızca "
        "yukarı). Önceki kapanış Alpaca günlük barının `c` alanıdır; bu alanın uzatılmış seans "
        "işlemlerini içerip içermediği doğrulanmadı.",
        f"**Spread** = (ask − bid) / orta fiyat, karar anından en fazla {tcfg['quote_penceresi_sn']} sn önceki son quote. "
        f"Sembol-gün başına en fazla {tcfg['max_quote_sorgu_sembol_gun']} dakikada sorgulanır; tek taraflı quote \"quote yok\" sayılır.",
        "**Günlük ön filtre kayıpsızdır** (fiyat aralığı ve değişim için aynı günün high/low'u "
        "yalnızca hangi dakikalık verinin indirileceğine karar verir). Günlük bar uzatılmış seansı "
        "içeriyorsa aralık daha geniştir → yine kayıp olmaz, sadece fazla indirme olur.",
        "**SIP geçmiş verisinin ücretsiz planda erişilebilir olduğu** (son 15 dk hariç) varsayıldı. "
        "Erişilemezse rapor başındaki uyarıya bakın.",
        "Seans saatleri ve tatil/yarım günler Alpaca calendar endpoint'inden; iç zamanlar UTC.",
        "**Aşama 2 riski — ORB ve IEX:** açılış aralığı (ilk 5/15 dk) IEX'te çok az bar ile "
        "oluşabilir; kırılma seviyesi ve VWAP IEX'te toplam piyasadan farklı olur. Backtest'i "
        "hem IEX hem SIP barlarıyla koşup farkı ölçmek gerekir.",
        "**Aşama 2 riski — maliyet:** 2–10 USD hisselerde spread görece geniş olabilir (bölüm 5 "
        "tablosu); spread/2 + kayma, R başına beklentinin önemli kısmını yiyebilir.",
        "**Aşama 3 riski — canlı IEX:** canlı akış IEX olacaksa göreli hacim tabanı da IEX "
        "geçmişinden hesaplanmalı (bu rapor öyle yapıyor); SIP'e geçilirse eşikler yeniden kalibre edilmeli.",
        "**Halt'lar (LULD):** bu fiyat aralığında sık; tarayıcı halt'ı ayrıca tespit etmiyor.",
    ]
