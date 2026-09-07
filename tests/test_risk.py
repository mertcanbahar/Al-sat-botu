"""Tests for the risk engine's drawdown halt, including threshold overrides."""
from __future__ import annotations

import pytest

from alsatbotu.config import MAX_DRAWDOWN_PCT
from engine.risk import evaluate_buy, is_drawdown_halted
from portfolio.state import PortfolioState


def test_halt_uses_live_threshold_by_default():
    # 25% below peak: over the live 20% limit, under a 30% one.
    assert is_drawdown_halted(75.0, 100.0) is (0.25 >= MAX_DRAWDOWN_PCT)


@pytest.mark.parametrize(
    "threshold, expected",
    [(0.20, True), (0.25, True), (0.30, False), (0.35, False)],
)
def test_halt_threshold_can_be_overridden(threshold, expected):
    assert is_drawdown_halted(75.0, 100.0, threshold) is expected


def test_halt_triggers_exactly_at_the_threshold():
    assert is_drawdown_halted(70.0, 100.0, 0.30) is True
    assert is_drawdown_halted(70.01, 100.0, 0.30) is False


def test_no_peak_means_no_halt():
    assert is_drawdown_halted(0.0, 0.0, 0.20) is False


def _state_at_drawdown(drawdown: float) -> PortfolioState:
    """Cash-only portfolio sitting `drawdown` below a 100k peak."""
    peak = 100_000.0
    return PortfolioState(
        cash=peak * (1 - drawdown), starting_capital=peak, peak_equity=peak
    )


def test_evaluate_buy_blocks_under_tight_threshold_and_allows_under_loose_one():
    state = _state_at_drawdown(0.25)

    blocked = evaluate_buy(
        state, "AAPL", "tech", entry_price=100.0, atr=2.0, current_prices={}, max_drawdown_pct=0.20
    )
    assert not blocked.approved
    assert any(r.startswith("Drawdown halt") for r in blocked.reasons)

    allowed = evaluate_buy(
        state, "AAPL", "tech", entry_price=100.0, atr=2.0, current_prices={}, max_drawdown_pct=0.30
    )
    assert allowed.approved
    assert allowed.quantity > 0
