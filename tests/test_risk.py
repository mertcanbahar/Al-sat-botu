"""Tests for the risk engine's latching drawdown halt (hysteresis + resets)."""
from __future__ import annotations

import pytest

from engine.risk import (
    STOP_REASON_HARD_FLOOR,
    STOP_REASON_MAX_RESETS,
    HaltPolicy,
    evaluate_buy,
    update_halt_state,
)
from portfolio.state import PortfolioState, Position

POLICY = HaltPolicy(
    halt_pct=0.20,
    release_pct=0.10,
    min_halt_marks=2,
    reset_after_marks=5,
    reset_fraction=0.5,
    max_resets=2,
    hard_floor_pct=0.50,
)


def cash_state(cash: float, peak: float = 100_000.0, starting: float = 100_000.0) -> PortfolioState:
    return PortfolioState(cash=cash, starting_capital=starting, peak_equity=peak)


def mark(state: PortfolioState, prices: dict | None = None, policy: HaltPolicy = POLICY):
    return update_halt_state(state, prices or {}, policy)


# -- Tetikleme ve histerezis ------------------------------------------------


def test_halt_triggers_at_threshold_and_not_before():
    state = cash_state(81_000.0)  # %19 drawdown
    assert mark(state).transition is None
    assert state.halted is False

    state.cash = 80_000.0  # %20
    assert mark(state).transition == "halted"
    assert state.halted is True


def test_release_needs_both_recovery_and_minimum_duration():
    state = cash_state(80_000.0)
    mark(state)  # halt

    # Anında toparlansa bile minimum süre dolmadan bırakmaz.
    state.cash = 95_000.0
    assert mark(state).transition is None
    assert state.halted is True

    # Süre dolduktan sonra, drawdown release eşiğinin altındayken bırakır.
    assert mark(state).transition == "released"
    assert state.halted is False


def test_partial_recovery_between_the_two_thresholds_keeps_the_halt_on():
    """Histerezisin amacı: %20 ile %10 arasında dolaşmak halt'ı açmaz."""
    state = cash_state(80_000.0)
    mark(state)
    state.cash = 85_000.0  # %15 drawdown: halt eşiğinin altında ama release'in üstünde
    # reset_after_marks'tan az işaretleme, ki kaçış kapısı değil histerezis sınansın.
    for _ in range(POLICY.reset_after_marks - 1):
        assert mark(state).transition is None
    assert state.halted is True

    # Aynı hesap %10'un altına inince bırakır.
    state.cash = 91_000.0
    assert mark(state).transition == "released"


# -- Kısmi reset (nakitte kilitlenme kaçış kapısı) --------------------------


def test_partial_reset_releases_a_flat_cash_account_and_halves_the_peak():
    state = cash_state(80_000.0)
    mark(state)  # halt, peak 100k
    for _ in range(4):
        mark(state)
    event = mark(state)  # reset_after_marks (5) doldu

    assert event.transition == "reset"
    assert state.halted is False
    assert state.halt_resets == 1
    # Peak tamamen sıfırlanmaz: equity ile eski peak'in ortasına çekilir.
    assert state.peak_equity == pytest.approx(90_000.0)
    # Koruma korunuyor: bir sonraki halt 90k'nın %20 altında, yani 72k'da.
    assert state.stopped is False


def test_reset_does_not_fire_while_positions_are_still_open():
    state = cash_state(0.0)
    state.open_positions["AAPL"] = Position(
        symbol="AAPL", category="tech", quantity=800.0, entry_price=100.0,
        entry_date="2026-01-01", stop_price=90.0,
    )
    prices = {"AAPL": 100.0}  # equity 80k, %20 drawdown
    mark(state, prices)
    for _ in range(10):
        event = mark(state, prices)
        assert event.transition != "reset"
    assert state.halted is True


def test_stops_permanently_after_the_reset_budget_is_spent():
    state = cash_state(80_000.0)
    policy = POLICY

    # Her turda: halt -> 5 işaretleme -> reset. İki reset sonra üçüncüsünde durur.
    for expected_resets in (1, 2):
        mark(state, policy=policy)  # halt (ilk turda zaten halted olabilir)
        for _ in range(policy.reset_after_marks):
            mark(state, policy=policy)
        assert state.halt_resets == expected_resets
        # Yeni peak'in %20 altına in ki tekrar halt tetiklensin.
        state.cash = state.peak_equity * 0.80

    mark(state, policy=policy)
    for _ in range(policy.reset_after_marks):
        event = mark(state, policy=policy)
    assert event.transition == "stopped"
    assert state.stopped is True
    assert state.stop_reason == STOP_REASON_MAX_RESETS


# -- Sert taban -------------------------------------------------------------


def test_hard_floor_stops_immediately_regardless_of_halt_state():
    state = cash_state(49_000.0)  # başlangıç sermayesinin %50'sinin altı
    event = mark(state)
    assert event.transition == "stopped"
    assert state.stop_reason == STOP_REASON_HARD_FLOOR
    assert state.halted is True


def test_a_stopped_bot_never_resumes_on_its_own():
    state = cash_state(49_000.0)
    mark(state)
    state.cash = 200_000.0  # tamamen toparlansa bile
    for _ in range(50):
        assert mark(state).transition is None
    assert state.stopped is True


# -- evaluate_buy bayrağı okur ---------------------------------------------


def test_evaluate_buy_blocks_while_halted_and_allows_after_release():
    state = cash_state(80_000.0)
    mark(state)

    blocked = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert not blocked.approved
    assert any(r.startswith("Drawdown halt") for r in blocked.reasons)

    state.cash = 95_000.0
    mark(state)
    mark(state)  # release
    allowed = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert allowed.approved and allowed.quantity > 0


def test_evaluate_buy_blocks_while_stopped_and_says_approval_is_needed():
    state = cash_state(49_000.0)
    mark(state)
    decision = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert not decision.approved
    assert any("insan onayı" in r for r in decision.reasons)


# -- Eski mandal davranışı (karşılaştırma tabanı) ---------------------------


def test_latching_policy_never_releases():
    latching = HaltPolicy(halt_pct=0.20, release_pct=None)
    state = cash_state(80_000.0)
    update_halt_state(state, {}, latching)
    state.cash = 99_999.0  # neredeyse tam toparlanma
    for _ in range(100):
        update_halt_state(state, {}, latching)
    assert state.halted is True
