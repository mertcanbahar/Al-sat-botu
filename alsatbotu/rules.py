"""Rule engine turning indicator values into a BUY/SELL/HOLD signal."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from .indicators import add_indicators

RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Decision:
    signal: Signal
    score: int
    reasons: list[str] = field(default_factory=list)


def _evaluate_row(prev: dict, last: dict) -> Decision:
    score = 0
    reasons: list[str] = []

    if last["rsi"] is not None:
        if last["rsi"] < RSI_OVERSOLD:
            score += 1
            reasons.append(f"RSI {last['rsi']:.1f} < {RSI_OVERSOLD} (oversold)")
        elif last["rsi"] > RSI_OVERBOUGHT:
            score -= 1
            reasons.append(f"RSI {last['rsi']:.1f} > {RSI_OVERBOUGHT} (overbought)")

    if None not in (prev["sma_fast"], prev["sma_slow"], last["sma_fast"], last["sma_slow"]):
        crossed_up = prev["sma_fast"] <= prev["sma_slow"] and last["sma_fast"] > last["sma_slow"]
        crossed_down = prev["sma_fast"] >= prev["sma_slow"] and last["sma_fast"] < last["sma_slow"]
        if crossed_up:
            score += 1
            reasons.append("SMA fast crossed above SMA slow (golden cross)")
        elif crossed_down:
            score -= 1
            reasons.append("SMA fast crossed below SMA slow (death cross)")

    if None not in (prev["macd"], prev["macd_signal"], last["macd"], last["macd_signal"]):
        crossed_up = prev["macd"] <= prev["macd_signal"] and last["macd"] > last["macd_signal"]
        crossed_down = prev["macd"] >= prev["macd_signal"] and last["macd"] < last["macd_signal"]
        if crossed_up:
            score += 1
            reasons.append("MACD crossed above signal line")
        elif crossed_down:
            score -= 1
            reasons.append("MACD crossed below signal line")

    if last["bb_lower"] is not None and last["close"] < last["bb_lower"]:
        score += 1
        reasons.append("Price below lower Bollinger band")
    elif last["bb_upper"] is not None and last["close"] > last["bb_upper"]:
        score -= 1
        reasons.append("Price above upper Bollinger band")

    if score > 0:
        signal = Signal.BUY
    elif score < 0:
        signal = Signal.SELL
    else:
        signal = Signal.HOLD

    return Decision(signal=signal, score=score, reasons=reasons)


def evaluate(rows: Sequence[dict]) -> Decision:
    """Evaluate the rule engine on the latest two rows of price/indicator data."""
    if len(rows) < 2:
        raise ValueError("Need at least 2 rows of data to evaluate rules.")

    enriched = add_indicators(rows)
    prev, last = enriched[-2], enriched[-1]
    return _evaluate_row(prev, last)
