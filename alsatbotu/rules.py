"""Rule engine turning indicator values into a BUY/SELL/HOLD signal.

Uses EMA(20), EMA(50), RSI(14), ATR(14) and a 20-period volume average:

AL (BUY)  -- all of: EMA20 > EMA50, RSI in [40, 65], last volume > 20-period
             volume average.
SAT (SELL) -- any of: price below the ATR stop level, EMA20 < EMA50,
             RSI > 75.

The ATR stop level is a simple trailing stop computed from the *previous*
bar: stop = prev_close - ATR_STOP_MULTIPLIER * prev_atr. Using the previous
bar (rather than the same bar being evaluated) avoids a tautology, since a
bar's own close can never fall below a level derived from itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from .indicators import add_indicators

RSI_BUY_MIN = 40
RSI_BUY_MAX = 65
RSI_SELL_MAX = 75
ATR_STOP_MULTIPLIER = 2.0


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Decision:
    signal: Signal
    reasons: list[str] = field(default_factory=list)


def _evaluate_row(prev: dict, last: dict) -> Decision:
    ema_20 = last["ema_20"]
    ema_50 = last["ema_50"]
    rsi_value = last["rsi"]
    close = last["close"]
    volume = last.get("volume")
    volume_avg = last["volume_sma_20"]

    sell_reasons: list[str] = []

    stop_level = None
    if prev["close"] is not None and prev["atr"] is not None:
        stop_level = prev["close"] - ATR_STOP_MULTIPLIER * prev["atr"]
        if close < stop_level:
            sell_reasons.append(f"Price {close:.4f} below ATR stop level {stop_level:.4f}")

    if ema_20 is not None and ema_50 is not None and ema_20 < ema_50:
        sell_reasons.append(f"EMA20 {ema_20:.4f} < EMA50 {ema_50:.4f}")

    if rsi_value is not None and rsi_value > RSI_SELL_MAX:
        sell_reasons.append(f"RSI {rsi_value:.1f} > {RSI_SELL_MAX}")

    if sell_reasons:
        return Decision(signal=Signal.SELL, reasons=sell_reasons)

    trend_ok = ema_20 is not None and ema_50 is not None and ema_20 > ema_50
    rsi_ok = rsi_value is not None and RSI_BUY_MIN <= rsi_value <= RSI_BUY_MAX
    volume_ok = volume is not None and volume_avg is not None and volume > volume_avg

    if trend_ok and rsi_ok and volume_ok:
        return Decision(
            signal=Signal.BUY,
            reasons=[
                f"EMA20 {ema_20:.4f} > EMA50 {ema_50:.4f}",
                f"RSI {rsi_value:.1f} in [{RSI_BUY_MIN}, {RSI_BUY_MAX}]",
                f"Volume {volume:.4f} > 20-period average {volume_avg:.4f}",
            ],
        )

    return Decision(signal=Signal.HOLD)


def evaluate(rows: Sequence[dict]) -> Decision:
    """Evaluate the rule engine on the latest two rows of price/indicator data."""
    if len(rows) < 2:
        raise ValueError("Need at least 2 rows of data to evaluate rules.")

    enriched = add_indicators(rows)
    prev, last = enriched[-2], enriched[-1]
    return _evaluate_row(prev, last)
