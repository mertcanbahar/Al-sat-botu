"""Known input/output tests for alsatbotu.indicators (pure functions)."""
from __future__ import annotations

import math

from alsatbotu.indicators import add_indicators, atr, ema, rsi, sma


def _approx(a: float | None, b: float, tol: float = 1e-9) -> bool:
    return a is not None and math.isclose(a, b, rel_tol=0, abs_tol=tol)


def test_sma_basic():
    values = [1, 2, 3, 4, 5]
    result = sma(values, window=3)
    assert result == [None, None, 2.0, 3.0, 4.0]


def test_sma_window_larger_than_values_is_all_none():
    assert sma([1.0, 2.0], window=5) == [None, None]


def test_sma_empty_input():
    assert sma([], window=3) == []


def test_ema_known_values():
    # alpha = 2 / (3 + 1) = 0.5
    values = [1, 2, 3, 4, 5]
    result = ema(values, span=3)
    assert result[0] is None
    assert result[1] is None
    assert _approx(result[2], 2.25)
    assert _approx(result[3], 3.125)
    assert _approx(result[4], 4.0625)


def test_ema_span_one_returns_input_series():
    values = [5.0, 6.0, 7.0]
    result = ema(values, span=1)
    assert result == [5.0, 6.0, 7.0]


def test_ema_empty_input():
    assert ema([], span=5) == []


def test_rsi_all_gains_is_100():
    # Strictly increasing closes: every delta is a gain, avg_loss stays 0.
    values = list(range(1, 21))  # 20 points -> 19 deltas
    result = rsi(values, period=14)
    assert result[:14] == [None] * 14
    assert all(_approx(v, 100.0) for v in result[14:])


def test_rsi_all_losses_is_0():
    values = list(range(20, 0, -1))
    result = rsi(values, period=14)
    assert result[:14] == [None] * 14
    assert all(_approx(v, 0.0) for v in result[14:])


def test_rsi_not_enough_values_is_all_none():
    assert rsi([1.0, 2.0, 3.0], period=14) == [None, None, None]


def test_atr_zero_when_flat():
    highs = [10.0] * 20
    lows = [10.0] * 20
    closes = [10.0] * 20
    result = atr(highs, lows, closes, period=14)
    assert result[:14] == [None] * 14
    assert all(_approx(v, 0.0) for v in result[14:])


def test_atr_not_enough_values_is_all_none():
    result = atr([1.0, 2.0], [1.0, 2.0], [1.0, 2.0], period=14)
    assert result == [None, None]


def test_add_indicators_attaches_expected_keys():
    rows = [
        {"close": float(i), "high": float(i) + 1, "low": float(i) - 1, "volume": 100.0}
        for i in range(1, 25)
    ]
    enriched = add_indicators(rows)
    assert len(enriched) == len(rows)
    for key in ("ema_20", "ema_50", "rsi", "atr", "volume_sma_20"):
        assert key in enriched[-1]
    # Original row data is preserved.
    assert enriched[0]["close"] == rows[0]["close"]


def test_add_indicators_missing_volume_yields_none_volume_sma():
    rows = [{"close": float(i), "high": float(i) + 1, "low": float(i) - 1} for i in range(1, 25)]
    enriched = add_indicators(rows)
    assert all(row["volume_sma_20"] is None for row in enriched)
