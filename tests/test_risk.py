"""Tests for the risk engine's drawdown halt, including threshold overrides.

The first half covers the legacy single-threshold latch, which the live
runner still uses and which must keep behaving exactly as it did. The second
half covers the graduated state machine that `policy=` opts into.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from alsatbotu.config import MAX_DRAWDOWN_PCT
from engine.halt import HaltPolicy, HaltState
from engine.risk import evaluate_buy, is_drawdown_halted
from portfolio.state import (
    Position,
    PortfolioState,
    load_state,
    save_state,
    update_halt_state,
)


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


def test_legacy_path_reports_no_halt_assessment():
    """`policy=None` must stay exactly the old code path, state machine unused."""
    decision = evaluate_buy(
        _state_at_drawdown(0.0), "AAPL", "tech", entry_price=100.0, atr=2.0, current_prices={}
    )
    assert decision.approved
    assert decision.halt is None


# --------------------------------------------------------------------------
# Graduated state machine (opt-in via policy=)
# --------------------------------------------------------------------------

POLICY = HaltPolicy()
DAY = date(2026, 1, 1)


def _buy(state: PortfolioState, today=DAY, policy: HaltPolicy = POLICY):
    # A wide ATR relative to the entry price on purpose: it keeps the
    # risk-sized quantity below the cash and category-exposure caps, so what
    # these tests measure is the capacity cut and nothing else. (At atr=2 the
    # 40% category cap binds first and hides it.)
    return evaluate_buy(
        state,
        "AAPL",
        "tech",
        entry_price=100.0,
        atr=4.0,
        current_prices={},
        policy=policy,
        today=today,
    )


def _flat_book(equity: float) -> PortfolioState:
    """Same equity, but no drawdown history: the unscaled comparison."""
    return PortfolioState(cash=equity, starting_capital=equity, peak_equity=equity)


@pytest.mark.parametrize(
    "drawdown, expected_state, expected_fraction",
    [
        (0.00, HaltState.NORMAL, 1.00),
        (0.05, HaltState.NORMAL, 1.00),
        (0.12, HaltState.CAUTION, 0.75),
        (0.17, HaltState.DEFENSIVE, 0.50),
    ],
)
def test_capacity_scales_the_position_instead_of_vetoing_it(
    drawdown, expected_state, expected_fraction
):
    state = _state_at_drawdown(drawdown)
    decision = _buy(state)

    assert decision.approved
    assert decision.halt.state is expected_state
    # Equity falls with the drawdown too, so the comparison has to hold equity
    # fixed: what would this same equity have bought with no drawdown behind it?
    unscaled = _buy(_flat_book(state.cash)).quantity
    assert decision.quantity == pytest.approx(unscaled * expected_fraction)


def test_capped_by_names_the_drawdown_state():
    decision = _buy(_state_at_drawdown(0.17))
    assert decision.capped_by is not None
    assert "DEFENSIVE" in decision.capped_by
    assert "50% capacity" in decision.capped_by


def test_a_tighter_limit_than_capacity_still_wins_the_cap():
    # 17% down (DEFENSIVE, 50% capacity) but nearly all of the equity is tied
    # up in an open position, so the cash limit binds harder than the capacity
    # cut and must be the one reported.
    state = PortfolioState(cash=8_000.0, starting_capital=100_000.0, peak_equity=100_000.0)
    state.open_positions["XOM"] = Position(
        symbol="XOM",
        category="energy",
        quantity=500.0,
        entry_price=150.0,
        entry_date=DAY.isoformat(),
        stop_price=140.0,
    )

    decision = _buy(state)

    assert decision.halt.state is HaltState.DEFENSIVE
    assert decision.capped_by == "cash"
    assert decision.quantity == pytest.approx(80.0)  # 8k of cash at 100/share


def test_halt_blocks_buys_and_keeps_the_prefix_the_sweep_matches_on():
    decision = _buy(_state_at_drawdown(0.25))

    assert not decision.approved
    assert decision.halt.state is HaltState.HALT
    assert any(r.startswith("Drawdown halt") for r in decision.reasons)


def test_the_safety_net_reopens_buying_at_the_smallest_size():
    state = _state_at_drawdown(0.25)
    state.halt_state = HaltState.HALT.name
    state.halt_since = DAY.isoformat()

    blocked = _buy(state, today=DAY + timedelta(days=13))
    assert not blocked.approved

    reopened = _buy(state, today=DAY + timedelta(days=14))
    assert reopened.approved
    assert reopened.halt.recovery_unlocked
    assert "25% capacity" in reopened.capped_by


def test_hysteresis_survives_a_round_trip_through_evaluate_buy():
    state = _state_at_drawdown(0.21)
    assert not _buy(state).approved  # into HALT

    # Recording the state is what carries the hysteresis across marks.
    update_halt_state(state, state.cash, today=DAY, policy=POLICY)
    assert state.halt_state == HaltState.HALT.name

    # Recovering to 17% would be DEFENSIVE from scratch, but a book already in
    # HALT stays there until 15%.
    recovered = PortfolioState(
        cash=83_000.0,
        starting_capital=100_000.0,
        peak_equity=100_000.0,
        halt_state=state.halt_state,
        halt_since=state.halt_since,
    )
    assert not _buy(recovered).approved
    assert _buy(recovered).halt.state is HaltState.HALT


def test_deepening_applies_on_the_mark_it_happens_even_if_state_is_stale():
    # Recorded as NORMAL, but equity has already fallen 25%. The trade must be
    # blocked now, not on whatever run next calls update_halt_state().
    state = _state_at_drawdown(0.25)
    assert state.halt_state == HaltState.NORMAL.name
    assert not _buy(state).approved


# --------------------------------------------------------------------------
# Persistence and backward compatibility
# --------------------------------------------------------------------------

def test_state_files_written_before_the_state_machine_still_load(tmp_path):
    legacy = {
        "cash": 2867.03,
        "starting_capital": 10_000.0,
        "peak_equity": 10_000.0,
        "open_positions": {},
        "closed_trades": [],
    }
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    state = load_state(path)
    assert state.halt_state == HaltState.NORMAL.name
    assert state.halt_since is None
    assert state.high_water_mark == state.peak_equity == 10_000.0


def test_halt_state_round_trips_through_save_and_load(tmp_path):
    state = _state_at_drawdown(0.25)
    update_halt_state(state, state.cash, today=DAY, policy=POLICY)

    path = tmp_path / "portfolio.json"
    save_state(state, path)
    reloaded = load_state(path)

    assert reloaded.halt_state == HaltState.HALT.name
    assert reloaded.halt_since == DAY.isoformat()


def test_update_halt_state_clears_the_clock_when_the_book_recovers(tmp_path):
    state = _state_at_drawdown(0.25)
    update_halt_state(state, state.cash, today=DAY, policy=POLICY)
    assert state.halt_since == DAY.isoformat()

    # Equity back to a 12% drawdown: out of HALT, clock cleared.
    update_halt_state(state, 88_000.0, today=DAY + timedelta(days=5), policy=POLICY)
    assert state.halt_state == HaltState.DEFENSIVE.name
    assert state.halt_since is None
