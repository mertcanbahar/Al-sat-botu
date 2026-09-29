"""Saf hesaplar (I/O yok): göreli hacim, spread, değişim, split faktörü.

Canlı (Aşama 3+) ve backtest aynı fonksiyonları kullanır.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

from intraday.zaman import Seans


def kumulatif_hacim_profili(
    barlar: Iterable[dict], seans: Seans, carpan: float = 1.0
) -> list[float]:
    """Seans açılışından itibaren her dakika sonu için kümülatif hacim.

    Sonuç uzunluğu = seans.dakika_sayisi. Eleman k, [acilis, acilis+k+1dk)
    aralığındaki toplam hacimdir. Bar olmayan dakikada (IEX'te sık) değer
    bir öncekiyle aynı kalır. Seans dışı barlar yok sayılır.
    `carpan`: split düzeltmesi (bkz. split_carpani).
    """
    n = seans.dakika_sayisi
    dakikalik = [0.0] * n
    for b in barlar:
        t: datetime = b["t"]
        if not seans.iceriyor(t):
            continue
        dakikalik[seans.acilistan_dakika(t)] += float(b["v"]) * carpan
    kum = []
    toplam = 0.0
    for v in dakikalik:
        toplam += v
        kum.append(toplam)
    return kum


def ortalama_profil(profiller: Sequence[Sequence[float]], uzunluk: int) -> list[float | None]:
    """Aynı dakika ofsetindeki kümülatif hacimlerin ortalaması.

    Kısa (yarım gün) profiller, kendi uzunluklarının ötesinde katkı vermez;
    o ofset için yalnızca o dakikaya ulaşan günlerin ortalaması alınır.
    """
    sonuc: list[float | None] = []
    for k in range(uzunluk):
        degerler = [p[k] for p in profiller if k < len(p)]
        sonuc.append(sum(degerler) / len(degerler) if degerler else None)
    return sonuc


def goreli_hacim(bugun_kumulatif: float, taban_kumulatif: float | None) -> float | None:
    """Bugün şu dakikaya kadarki hacim / geçmiş günlerde aynı dakikaya kadarki ortalama."""
    if taban_kumulatif is None or taban_kumulatif <= 0:
        return None
    return bugun_kumulatif / taban_kumulatif


def spread_pct(bid: float | None, ask: float | None) -> float | None:
    """(ask - bid) / orta fiyat * 100. Tek taraflı/ters/boş quote -> None."""
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    orta = (bid + ask) / 2.0
    return (ask - bid) / orta * 100.0


def degisim_pct(fiyat: float, onceki_kapanis: float) -> float | None:
    if not onceki_kapanis or onceki_kapanis <= 0:
        return None
    return (fiyat / onceki_kapanis - 1.0) * 100.0


def degisim_gecti(degisim: float | None, esik: float, yon: str) -> bool:
    if degisim is None:
        return False
    if yon == "yukari":
        return degisim >= esik
    if yon == "iki_yonlu":
        return abs(degisim) >= esik
    raise ValueError(f"bilinmeyen degisim_yonu: {yon}")


def split_carpani(ham_kapanis: float, duzeltilmis_kapanis: float) -> float | None:
    """Ham / split-düzeltmeli kapanış = o günden bugüne kümülatif split faktörü.

    Geçmiş gün d'nin hacmini hedef gün D cinsine çevirmek için:
    hacim_d * f(d) / f(D). Örn. d ile D arasında 1:10 ters split varsa
    f(d)=0.1, f(D)=1 -> 1000 lot eski hisse = 100 lot yeni hisse.
    """
    if not ham_kapanis or not duzeltilmis_kapanis:
        return None
    return ham_kapanis / duzeltilmis_kapanis


def fiyat_dilimi(fiyat: float, sinirlar: Sequence[float]) -> str | None:
    """[2,4,6,8,10] -> '2-4', ... ; son dilim üst sınırı kapsar."""
    for i in range(len(sinirlar) - 1):
        alt, ust = sinirlar[i], sinirlar[i + 1]
        son = i == len(sinirlar) - 2
        if alt <= fiyat < ust or (son and fiyat == ust):
            return f"{alt:g}-{ust:g}"
    return None
