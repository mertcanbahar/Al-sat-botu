"""Tests for alsatbotu.signal.evaluate, focused on the volume-confirmation leg.

Twelve Data's forex time_series has no "volume" field (OTC market), so
`get_price_history(..., source="twelvedata")` never sets `row["volume"]`
for forex symbols. Before this fix, `_evaluate_row`'s volume_ok required
`volume > volume_avg`, which is False whenever volume is None -- forex
could satisfy the EMA/RSI legs perfectly and still never get a BUY signal.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from alsatbotu.signal import Decision, Signal, evaluate
from evaluation.strategy import BASELINE_PARAMS, evaluate_versioned


def _uptrend_rows(n: int = 80, with_volume: bool = True) -> list[dict]:
    """A steady, wiggly uptrend: EMA20 > EMA50, RSI settles inside [40, 75].

    A pure monotonic climb pins RSI at 100 (all gains, no losses), which
    trips the RSI_SELL_MAX > 75 leg instead of the BUY band -- the small
    sine wiggle on top of the drift produces occasional down-days so RSI
    settles in the middle of its range, like a real (if unusually clean)
    uptrend would.
    """
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(n):
        if i > 0:
            price *= 1.0015 * (1 + 0.01 * math.sin(i / 3.3))
        row = {
            "timestamp": base + timedelta(days=i),
            "open": price,
            "high": price * 1.001,
            "low": price * 0.999,
            "close": price,
        }
        if with_volume:
            # Rising volume so the last bar's volume clears its own 20-period average.
            row["volume"] = 1_000_000.0 + i * 5_000.0
        rows.append(row)
    return rows


def _assert_buy_setup_is_real(rows: list[dict]) -> None:
    """Sanity check the fixture actually clears the EMA/RSI legs on its own."""
    from alsatbotu.indicators import add_indicators

    last = add_indicators(rows)[-1]
    assert last["ema_fast"] > last["ema_slow"], "fixture does not produce a bullish EMA cross"
    assert 40 <= last["rsi"] <= 75, f"fixture RSI {last['rsi']} outside the BUY band"


def test_buy_fires_with_volume_confirmation_present_and_passing():
    rows = _uptrend_rows(with_volume=True)
    _assert_buy_setup_is_real(rows)
    decision = evaluate(rows)
    assert decision.signal == Signal.BUY
    assert any("Volume" in r and ">" in r for r in decision.reasons)


def test_buy_still_fires_when_volume_data_is_entirely_absent():
    """The forex case: Twelve Data never sets "volume" -- must not block BUY forever."""
    rows = _uptrend_rows(with_volume=False)
    _assert_buy_setup_is_real(rows)
    decision = evaluate(rows)
    assert decision.signal == Signal.BUY
    assert any("unavailable" in r for r in decision.reasons)


def test_versioned_strategy_matches_the_same_volume_semantics():
    rows_with_volume = _uptrend_rows(with_volume=True)
    rows_without_volume = _uptrend_rows(with_volume=False)

    assert evaluate_versioned(rows_with_volume, BASELINE_PARAMS).signal == Signal.BUY
    assert evaluate_versioned(rows_without_volume, BASELINE_PARAMS).signal == Signal.BUY


def test_buy_still_blocked_when_volume_data_exists_but_fails_the_check():
    """Volume present but *below* its own average must still block BUY (no regression)."""
    rows = _uptrend_rows(with_volume=True)
    # Tank the last bar's volume far below the 20-period average computed from the rest.
    rows[-1] = {**rows[-1], "volume": 1.0}
    decision = evaluate(rows)
    assert decision.signal != Signal.BUY
