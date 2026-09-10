"""Technical indicators used by the rule engine (pure Python, no external deps)."""
from __future__ import annotations

from typing import Optional, Sequence

from alsatbotu.config import EMA_FAST_PERIOD, EMA_SLOW_PERIOD


def sma(values: Sequence[float], window: int) -> list[Optional[float]]:
    """Simple moving average; None until `window` values are available."""
    out: list[Optional[float]] = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def ema(values: Sequence[float], span: int) -> list[Optional[float]]:
    """Exponential moving average; None until `span` values are available."""
    out: list[Optional[float]] = [None] * len(values)
    if not values:
        return out

    alpha = 2 / (span + 1)
    current = values[0]
    if span == 1:
        out[0] = current
    for i in range(1, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        if i >= span - 1:
            out[i] = current
    return out


def _rsi_from_avg(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi(values: Sequence[float], period: int = 14) -> list[Optional[float]]:
    """Wilder's RSI; None until `period` price changes are available."""
    out: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return out

    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from_avg(avg_gain, avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi_from_avg(avg_gain, avg_loss)

    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[Optional[float]]:
    """Wilder's Average True Range; None until `period` true ranges are available."""
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n <= period:
        return out

    true_ranges = [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, n)
    ]

    avg_tr = sum(true_ranges[:period]) / period
    out[period] = avg_tr

    for i in range(period, len(true_ranges)):
        avg_tr = (avg_tr * (period - 1) + true_ranges[i]) / period
        out[i + 1] = avg_tr

    return out


def add_indicators(rows: Sequence[dict], price_key: str = "close") -> list[dict]:
    """Return copies of `rows` with EMA(20)/EMA(50)/RSI(14)/ATR(14)/volume SMA(20) attached.

    Volume-derived fields are None throughout when any row is missing a
    "volume" key (e.g. CoinGecko's OHLC endpoint does not provide one).
    """
    closes = [row[price_key] for row in rows]
    highs = [row["high"] for row in rows]
    lows = [row["low"] for row in rows]
    volumes = [row.get("volume") for row in rows]

    ema_20 = ema(closes, 20)
    ema_50 = ema(closes, 50)
    # Vade profiline göre değişen çift. VADE="uzun" iken 20/50 olduğu için
    # ema_fast/ema_slow ile ema_20/ema_50 aynı seriyi taşır; VADE="kisa" iken
    # ayrışırlar. Eski anahtarlar (rapor, dashboard, defter) hep 20/50 kalır ki
    # adı ile içeriği tutsun.
    ema_fast = ema_20 if EMA_FAST_PERIOD == 20 else ema(closes, EMA_FAST_PERIOD)
    ema_slow = ema_50 if EMA_SLOW_PERIOD == 50 else ema(closes, EMA_SLOW_PERIOD)
    rsi_14 = rsi(closes, 14)
    atr_14 = atr(highs, lows, closes, 14)

    has_volume = bool(volumes) and all(v is not None for v in volumes)
    volume_sma_20 = sma(volumes, 20) if has_volume else [None] * len(rows)

    out = []
    for i, row in enumerate(rows):
        enriched = dict(row)
        enriched["ema_20"] = ema_20[i]
        enriched["ema_50"] = ema_50[i]
        enriched["ema_fast"] = ema_fast[i]
        enriched["ema_slow"] = ema_slow[i]
        enriched["rsi"] = rsi_14[i]
        enriched["atr"] = atr_14[i]
        enriched["volume_sma_20"] = volume_sma_20[i]
        out.append(enriched)
    return out
