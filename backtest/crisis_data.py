#!/usr/bin/env python3
"""Kriz dönemi fiyat serisi üreteci: 2008 (GFC) ve 2020 (COVID) çöküşleri dahil.

Neden ayrı bir üreteç
---------------------
`portfolio_backtest.generate_synthetic_data()` her sembolü *bağımsız* bir
rastgele yürüyüş olarak üretir. 20 bağımsız yürüyüşün aynı anda çökme
olasılığı düşük olduğu için portföy equity'si hiçbir zaman ciddi bir
drawdown görmez -- drawdown halt kuralı da bu yüzden portföy düzeyinde
neredeyse hiç tetiklenmez. Yani o veriyle "halt çalışıyor mu" sorusu
sorulamaz: ölçülen şey kuralın kendisi değil, verinin sakinliğidir.

Bu üreteç iki şeyi değiştirir:

  1. **Ortak piyasa faktörü.** Her sembolün günlük getirisi
     `beta_i * piyasa + idiyosenkratik` olarak kurulur, yani hepsi aynı
     anda düşer. Kriz dönemlerinde portföy çeşitlendirmesi işe yaramaz --
     gerçek 2008 ve 2020'de olduğu gibi.
  2. **Rejim takvimi.** Piyasa faktörünün sürüklenmesi ve oynaklığı
     `CRISIS_REGIMES` tablosundaki tarihlere göre değişir: 2005-2007
     boğası, 2007-2009 GFC çöküşü (~-55%), 2009-2020 arası boğa (araya
     2011 / 2015-16 / 2018Q4 düzeltmeleri serpiştirilmiş), 2020 Şubat-Mart
     COVID çöküşü (23 işlem gününde ~-34%) ve ardından toparlanma.

Ne DEĞİLDİR
-----------
Bu **gerçek piyasa verisi değildir.** S&P 500'ün ya da herhangi bir hissenin
gerçek 2008/2020 fiyatları değil; o dönemlerin *biçimini* (süre, derinlik,
oynaklık, korelasyon) taklit eden sentetik bir stres senaryosudur. Getiri
seviyeleri gerçek performans tahmini olarak okunamaz. Okunabilir olan:
halt kuralının böyle bir çöküşte ne yaptığı ve politikaların birbirine
göre davranışı.

Gerçek veri bu ortamda çekilemiyor (TWELVEDATA_API_KEY yok ve dış ağ
kapalı); anahtar/ağ olan bir ortamda `crisis_run.py --real` aynı koşuyu
Twelve Data ile yapar.
"""
from __future__ import annotations

import math
import random
import sys
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


WINDOW_START = date(2005, 1, 3)
WINDOW_END = date(2021, 12, 31)

# Idiyosenkratik oynaklığın "sakin rejim" referansı: rejim oynaklığı bunun
# kaç katıysa sembole özgü gürültü de o kadar büyür (krizde her şey oynak).
BASE_VOL = 0.009


@dataclass(frozen=True)
class Regime:
    """Piyasa faktörünün bir dönemdeki hedef hareketi ve oynaklığı.

    `target_return` o rejim boyunca piyasa faktörünün *tam olarak* yapacağı
    kümülatif harekettir: üretilen günlük gürültü rejim içinde ortalaması
    sıfıra çekilip üstüne hedefin günlük log payı eklenir. Böylece her
    tohumda yol farklı ama kriz derinliği aynı olur -- amaç kriz
    derinliğini rastgeleliğe bırakmak değil, o derinlikte halt kuralının
    ne yaptığını ölçmek.
    """

    name: str
    start: date
    target_return: float  # rejim boyunca kümülatif basit getiri
    vol: float            # günlük log-getiri standart sapması
    note: str = ""


# Rejim tablosu. `start` dahil, bir sonraki rejimin `start`'ı hariç.
# Zincirin tamamı 17 yılda ~+300% (yıllık ~%8.5) verir.
CRISIS_REGIMES: list[Regime] = [
    Regime("Boğa 2005-2007", date(2005, 1, 3), 0.28, 0.0075, "kriz öncesi sakin yükseliş"),
    Regime("GFC çöküşü", date(2007, 10, 10), -0.55, 0.0240, "2008 krizi: ~17 ayda -55%"),
    Regime("GFC toparlanması", date(2009, 3, 10), 0.95, 0.0130, "dipten +95%"),
    Regime("2011 düzeltmesi", date(2011, 5, 2), -0.19, 0.0170, "-19%"),
    Regime("Boğa 2011-2015", date(2011, 10, 4), 1.00, 0.0090, "+100%"),
    Regime("2015-16 düzeltmesi", date(2015, 5, 21), -0.14, 0.0150, "-14%"),
    Regime("Boğa 2016-2018", date(2016, 2, 12), 0.60, 0.0080, "+60%"),
    Regime("2018Q4 düzeltmesi", date(2018, 9, 21), -0.20, 0.0180, "-20%"),
    Regime("Boğa 2019", date(2018, 12, 26), 0.45, 0.0100, "+45%"),
    Regime("COVID çöküşü", date(2020, 2, 20), -0.34, 0.0420, "23 işlem gününde -34%"),
    Regime("COVID toparlanması", date(2020, 3, 24), 1.10, 0.0160, "+110%"),
]

# Rapor metinlerinde "asıl olay" olarak anılan iki kriz penceresi.
CRISIS_WINDOWS: dict[str, tuple[date, date]] = {
    "GFC (2008)": (date(2007, 10, 10), date(2009, 3, 9)),
    "COVID (2020)": (date(2020, 2, 20), date(2020, 3, 23)),
}


def trading_days(start: Optional[date] = None, end: Optional[date] = None) -> list[date]:
    """Hafta içi günler. Resmî tatiller modellenmiyor (halt davranışını etkilemez).

    Sınırlar çağrı anında modül değişkenlerinden okunur (varsayılan argümana
    bağlanmaz), böylece testler `WINDOW_START`/`WINDOW_END`'i geçici olarak
    daraltıp kısa bir pencerede koşabilir.
    """
    start = WINDOW_START if start is None else start
    end = WINDOW_END if end is None else end
    days: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _regime_for(day: date) -> Regime:
    current = CRISIS_REGIMES[0]
    for regime in CRISIS_REGIMES:
        if day >= regime.start:
            current = regime
        else:
            break
    return current


def market_path(seed: int = 42) -> list[tuple[date, float]]:
    """Ortak piyasa faktörünün günlük **log**-getirisi (tüm semboller bunu paylaşır).

    Rejim içindeki gürültünün ortalaması sıfıra çekilir ve hedefin günlük
    log payı eklenir, yani her rejimin kümülatif hareketi hedefine tam
    oturur. (Ham gauss sürüklenmesiyle üretmek oynaklık sürüklenmesi
    yüzünden GFC'yi -55% yerine -90%'a indiriyordu.)
    """
    rng = random.Random(seed ^ 0x5EED)
    days = trading_days()

    by_regime: dict[str, list[int]] = {}
    for i, day in enumerate(days):
        by_regime.setdefault(_regime_for(day).name, []).append(i)

    returns = [0.0] * len(days)
    for regime in CRISIS_REGIMES:
        idx = by_regime.get(regime.name, [])
        if not idx:
            continue
        noise = [rng.gauss(0.0, regime.vol) for _ in idx]
        mean = sum(noise) / len(noise)
        per_day = math.log1p(regime.target_return) / len(idx)
        for i, n in zip(idx, noise):
            returns[i] = per_day + (n - mean)

    return list(zip(days, returns))


def generate_crisis_data(
    symbols: Sequence[dict], seed: int = 42
) -> dict[str, list[dict]]:
    """2005-2021 aralığı için sembol başına günlük OHLCV üretir.

    Her sembol ortak piyasa faktörüne `beta` ile bağlıdır; üstüne sembole
    özgü sürüklenme ve gürültü eklenir. `seed` hem piyasa yolunu hem de
    sembol parametrelerini belirler, yani aynı tohum aynı veriyi verir
    (sembol tohumu `crc32`'den gelir -- `hash()` süreç başına rastgelelenir).
    """
    market = market_path(seed)
    days = [day for day, _ in market]
    regime_index: dict[str, list[int]] = {}
    for i, day in enumerate(days):
        regime_index.setdefault(_regime_for(day).name, []).append(i)

    data: dict[str, list[dict]] = {}

    for entry in symbols:
        symbol = entry["symbol"]
        sym_rng = random.Random(seed ^ zlib.crc32(symbol.encode("utf-8")))
        beta = sym_rng.uniform(0.65, 1.45)
        alpha = sym_rng.gauss(0.0, 0.00012)      # sembole özgü kalıcı sürüklenme
        idio_vol = sym_rng.uniform(0.008, 0.016)  # sakin rejimdeki sembol gürültüsü
        price = sym_rng.uniform(30, 250)

        # Sembol gürültüsü de rejim içinde ortalaması sıfıra çekilir: aksi
        # halde 4435 günlük birikmiş gürültü sembolün kriz derinliğini
        # tohumdan tohuma -34%/-68% gibi savuruyor ve ölçülen şey halt
        # kuralı değil çekilişin şansı oluyordu. Yol rastgele kalır,
        # rejim boyunca varılan yer beta ve alpha ile belirlenir.
        idio = [0.0] * len(days)
        for regime in CRISIS_REGIMES:
            idx = regime_index.get(regime.name, [])
            if not idx:
                continue
            stress = regime.vol / BASE_VOL
            noise = [sym_rng.gauss(0.0, idio_vol * stress) for _ in idx]
            mean = sum(noise) / len(noise)
            for i, n in zip(idx, noise):
                idio[i] = alpha + (n - mean)

        rows: list[dict] = []
        for i, (day, market_return) in enumerate(market):
            stress = _regime_for(day).vol / BASE_VOL
            # Log uzayında toplanır: oynaklık sürüklenmesi rejim hedefini
            # bozmasın diye fiyat exp() ile ilerletilir.
            price = max(0.5, price * math.exp(beta * market_return + idio[i]))

            high = price * (1 + abs(sym_rng.gauss(0, 0.006 * stress)))
            low = price * (1 - abs(sym_rng.gauss(0, 0.006 * stress)))
            open_ = low + (high - low) * sym_rng.random()
            rows.append(
                {
                    "timestamp": datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                    "open": open_,
                    "high": max(high, open_, price),
                    "low": min(low, open_, price),
                    "close": price,
                    "volume": sym_rng.uniform(1_000_000, 5_000_000),
                }
            )
        data[symbol] = rows

    return data


def equal_weight_index(price_data: dict[str, list[dict]]) -> list[tuple[str, float]]:
    """Günlük yeniden dengelenen eşit ağırlıklı endeks (rapordaki kriz derinliği için).

    Normalleştirilmiş fiyatların ortalaması yerine *günlük getirilerin*
    kesitsel ortalaması alınır; aksi halde 17 yılda en çok büyüyen bir iki
    sembol ortalamayı ele geçirir ve endeks portföyün gördüğü krizi değil
    o sembollerin yolunu gösterir.
    """
    symbols = [s for s, rows in price_data.items() if rows]
    if not symbols:
        return []
    length = min(len(price_data[s]) for s in symbols)

    value = 100.0
    curve = [(price_data[symbols[0]][0]["timestamp"].date().isoformat(), value)]
    for i in range(1, length):
        daily = [
            price_data[s][i]["close"] / price_data[s][i - 1]["close"] - 1.0
            for s in symbols
            if price_data[s][i - 1]["close"]
        ]
        value *= 1.0 + (sum(daily) / len(daily) if daily else 0.0)
        curve.append((price_data[symbols[0]][i]["timestamp"].date().isoformat(), value))
    return curve


def window_drawdown(curve: list[tuple[str, float]], start: date, end: date) -> float:
    """Verilen tarih aralığındaki tepe-dip düşüşü (rapordaki "kriz gerçekten oldu mu" kontrolü)."""
    values = [v for d, v in curve if start.isoformat() <= d <= end.isoformat()]
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1.0)
    return worst


if __name__ == "__main__":  # elle bakmak için: kriz derinlikleri doğru mu?
    from backtest.portfolio_backtest import BACKTEST_SYMBOLS

    data = generate_crisis_data(BACKTEST_SYMBOLS, seed=42)
    index = equal_weight_index(data)
    print(f"{len(index)} işlem günü, {index[0][0]} → {index[-1][0]}")
    for label, (start, end) in CRISIS_WINDOWS.items():
        print(f"  {label}: {window_drawdown(index, start, end) * 100:.1f}%")
