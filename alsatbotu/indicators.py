"""Technical indicators used by the rule engine (pure Python, no external deps)."""
from __future__ import annotations

from typing import Optional, Sequence


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


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, list[Optional[float]]]:
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    macd_line: list[Optional[float]] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]

    signal_line: list[Optional[float]] = [None] * len(values)
    hist: list[Optional[float]] = [None] * len(values)

    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if first_valid is not None:
        signal_tail = ema(macd_line[first_valid:], signal)
        for offset, value in enumerate(signal_tail):
            signal_line[first_valid + offset] = value
        for i in range(len(values)):
            if macd_line[i] is not None and signal_line[i] is not None:
                hist[i] = macd_line[i] - signal_line[i]

    return {"macd": macd_line, "signal": signal_line, "hist": hist}


def bollinger_bands(
    values: Sequence[float], window: int = 20, num_std: float = 2.0
) -> dict[str, list[Optional[float]]]:
    mid = sma(values, window)
    upper: list[Optional[float]] = [None] * len(values)
    lower: list[Optional[float]] = [None] * len(values)

    for i in range(window - 1, len(values)):
        window_slice = values[i - window + 1 : i + 1]
        mean = mid[i]
        variance = sum((x - mean) ** 2 for x in window_slice) / window
        std = variance**0.5
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std

    return {"mid": mid, "upper": upper, "lower": lower}


def add_indicators(rows: Sequence[dict], price_key: str = "close") -> list[dict]:
    """Return copies of `rows` with SMA/EMA/RSI/MACD/Bollinger columns attached."""
    closes = [row[price_key] for row in rows]

    sma_fast = sma(closes, 10)
    sma_slow = sma(closes, 30)
    ema_fast = ema(closes, 12)
    ema_slow = ema(closes, 26)
    rsi_values = rsi(closes, 14)
    macd_values = macd(closes)
    bb_values = bollinger_bands(closes)

    out = []
    for i, row in enumerate(rows):
        enriched = dict(row)
        enriched["sma_fast"] = sma_fast[i]
        enriched["sma_slow"] = sma_slow[i]
        enriched["ema_fast"] = ema_fast[i]
        enriched["ema_slow"] = ema_slow[i]
        enriched["rsi"] = rsi_values[i]
        enriched["macd"] = macd_values["macd"][i]
        enriched["macd_signal"] = macd_values["signal"][i]
        enriched["macd_hist"] = macd_values["hist"][i]
        enriched["bb_mid"] = bb_values["mid"][i]
        enriched["bb_upper"] = bb_values["upper"][i]
        enriched["bb_lower"] = bb_values["lower"][i]
        out.append(enriched)
    return out
