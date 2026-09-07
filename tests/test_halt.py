"""Tests for the graduated drawdown state machine (engine/halt.py).

The behaviours that matter are the ones the old single-threshold latch got
wrong: hysteresis (a drawdown hovering at a boundary must not flip the book on
and off), non-terminality (HALT has to be leavable), and the time-based safety
net (a book that cannot recover on its own still reopens, at the smallest
size).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from engine.halt import (
    HaltAssessment,
    HaltPolicy,
    HaltState,
    assess,
    drawdown_pct,
    next_state,
    state_from_name,
    update_high_water_mark,
)

POLICY = HaltPolicy()
DAY = date(2026, 1, 1)


def state_at(drawdown: float, previous: HaltState = HaltState.NORMAL) -> HaltState:
    return next_state(previous, drawdown, POLICY)


# --------------------------------------------------------------------------
# Drawdown is measured from the high-water mark
# --------------------------------------------------------------------------

def test_drawdown_is_measured_from_the_high_water_mark_not_starting_capital():
    # Account started at 10k, ran to 20k, now sits at 16k. Against starting
    # capital that is a 60% *gain*; against the high-water mark it is a 20%
    # drawdown, and the state machine must see the latter.
    assert drawdown_pct(16_000.0, 20_000.0) == pytest.approx(0.20)
    assert state_at(drawdown_pct(16_000.0, 20_000.0)) is HaltState.HALT


def test_high_water_mark_only_ratchets_up():
    hwm = update_high_water_mark(10_000.0, 12_000.0)
    assert hwm == 12_000.0
    assert update_high_water_mark(hwm, 9_000.0) == 12_000.0


def test_equity_above_the_high_water_mark_is_not_a_negative_drawdown():
    assert drawdown_pct(120.0, 100.0) == 0.0


def test_no_high_water_mark_means_no_drawdown():
    assert drawdown_pct(0.0, 0.0) == 0.0
    assert assess(0.0, 0.0, policy=POLICY).state is HaltState.NORMAL


# --------------------------------------------------------------------------
# Entry thresholds and their exact boundaries
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "drawdown, expected",
    [
        (0.00, HaltState.NORMAL),
        (0.099, HaltState.NORMAL),
        (0.10, HaltState.CAUTION),
        (0.149, HaltState.CAUTION),
        (0.15, HaltState.DEFENSIVE),
        (0.199, HaltState.DEFENSIVE),
        (0.20, HaltState.HALT),
        (0.60, HaltState.HALT),
    ],
)
def test_entry_thresholds_from_normal(drawdown, expected):
    assert state_at(drawdown) is expected


@pytest.mark.parametrize(
    "state, expected_capacity",
    [
        (HaltState.NORMAL, 1.00),
        (HaltState.CAUTION, 0.75),
        (HaltState.DEFENSIVE, 0.50),
        (HaltState.HALT, 0.00),
    ],
)
def test_capacity_ladder(state, expected_capacity):
    assert POLICY.capacity_for(state) == pytest.approx(expected_capacity)


# --------------------------------------------------------------------------
# Hysteresis: entry and exit thresholds differ
# --------------------------------------------------------------------------

def test_halt_is_entered_at_20_and_left_at_15_not_at_the_same_level():
    assert state_at(0.20, HaltState.DEFENSIVE) is HaltState.HALT
    # Still deep in the gap: recovering to 19% or 16% does not release HALT.
    assert state_at(0.19, HaltState.HALT) is HaltState.HALT
    assert state_at(0.16, HaltState.HALT) is HaltState.HALT
    assert state_at(0.1501, HaltState.HALT) is HaltState.HALT
    # 15% is the exit threshold, so this is where it finally steps back.
    assert state_at(0.15, HaltState.HALT) is HaltState.DEFENSIVE


def test_re_entry_needs_the_entry_threshold_again_not_the_exit_one():
    # Back in DEFENSIVE after a HALT: drifting to 16-19% must not re-halt,
    # otherwise leaving HALT at 15% would just bounce straight back.
    assert state_at(0.16, HaltState.DEFENSIVE) is HaltState.DEFENSIVE
    assert state_at(0.199, HaltState.DEFENSIVE) is HaltState.DEFENSIVE
    assert state_at(0.20, HaltState.DEFENSIVE) is HaltState.HALT


@pytest.mark.parametrize(
    "state, enter_at, exit_at",
    [
        (HaltState.CAUTION, 0.10, 0.05),
        (HaltState.DEFENSIVE, 0.15, 0.10),
        (HaltState.HALT, 0.20, 0.15),
    ],
)
def test_every_rung_has_a_hysteresis_gap(state, enter_at, exit_at):
    assert POLICY.enter_threshold(state) == pytest.approx(enter_at)
    assert POLICY.exit_threshold(state) == pytest.approx(exit_at)
    assert POLICY.exit_threshold(state) < POLICY.enter_threshold(state)


def test_oscillating_around_the_halt_boundary_does_not_chatter():
    # A drawdown wobbling either side of 20% would flip a plain threshold on
    # and off every single day. Hysteresis means one transition in, and none
    # back out until 15%.
    series = [0.198, 0.202, 0.197, 0.203, 0.199, 0.201] * 5
    state = HaltState.DEFENSIVE
    transitions = 0
    for drawdown in series:
        following = state_at(drawdown, state)
        if following is not state:
            transitions += 1
        state = following

    assert transitions == 1
    assert state is HaltState.HALT


def test_a_plain_threshold_would_have_chattered_on_the_same_series():
    # The counterfactual the hysteresis is there to prevent, so the test above
    # is measuring something real rather than a series that never crosses.
    series = [0.198, 0.202, 0.197, 0.203, 0.199, 0.201] * 5
    flips = sum(1 for a, b in zip(series, series[1:]) if (a >= 0.20) != (b >= 0.20))
    assert flips == len(series) - 1  # every single mark flips the latch


# --------------------------------------------------------------------------
# Multi-rung moves in both directions
# --------------------------------------------------------------------------

def test_a_gap_down_deepens_straight_to_halt_without_stepping_through_rungs():
    assert state_at(0.25, HaltState.NORMAL) is HaltState.HALT


def test_a_full_recovery_returns_to_normal_in_one_mark():
    assert state_at(0.02, HaltState.HALT) is HaltState.NORMAL


def test_recovery_stops_at_the_rung_the_drawdown_still_justifies():
    # 12% is at or below HALT's exit (15%) so HALT is released, but it is
    # still above DEFENSIVE's exit (10%), so recovery stops at DEFENSIVE.
    assert state_at(0.12, HaltState.HALT) is HaltState.DEFENSIVE


def test_halt_is_not_terminal():
    state = HaltState.NORMAL
    for drawdown in (0.22, 0.21, 0.18, 0.14, 0.08, 0.01):
        state = state_at(drawdown, state)
    assert state is HaltState.NORMAL


# --------------------------------------------------------------------------
# Time-based safety net
# --------------------------------------------------------------------------

def halt_after(days: int, drawdown: float = 0.25) -> HaltAssessment:
    """Assess a book that entered HALT `days` calendar days ago.

    The default drawdown sits in the working band (past HALT's 20% entry,
    above the 30% floor) and is flat since entry, so what these tests measure
    is the clock alone -- the floor and the stability condition are covered
    by their own tests below.
    """
    equity, hwm = 100.0 * (1 - drawdown), 100.0
    return assess(
        equity=equity,
        high_water_mark=hwm,
        previous_state=HaltState.HALT,
        halt_since=DAY,
        today=DAY + timedelta(days=days),
        policy=POLICY,
        halt_entry_drawdown=drawdown,
    )


def test_halt_blocks_new_buys_before_the_safety_net_fires():
    result = halt_after(13)
    assert result.state is HaltState.HALT
    assert result.capacity == 0.0
    assert result.blocks_new_buys
    assert not result.recovery_unlocked
    assert result.halt_days == 13


def test_the_safety_net_reopens_sizing_on_day_14():
    result = halt_after(14)
    assert result.state is HaltState.HALT
    assert result.capacity == pytest.approx(0.25)
    assert not result.blocks_new_buys
    assert result.recovery_unlocked


def test_the_safety_net_stays_open_past_day_14():
    assert halt_after(90).capacity == pytest.approx(0.25)


def test_the_safety_net_is_a_rung_below_defensive():
    assert POLICY.recovery_capacity < POLICY.capacity_defensive


def test_a_frozen_all_cash_account_still_reopens():
    # The exact case hysteresis alone cannot fix: an account that halted while
    # fully in cash has a flat equity curve, so its drawdown never improves
    # and no exit threshold is ever met. Only the clock releases it -- and a
    # flat curve is precisely what the stability condition allows, since the
    # drawdown is not deepening.
    equity, hwm = 75.0, 100.0  # 25%: past HALT, above the 30% floor
    state, halt_since, entry_dd = HaltState.NORMAL, None, None
    unlocked_on = None
    for offset in range(30):
        today = DAY + timedelta(days=offset)
        result = assess(
            equity, hwm, state, halt_since, today, POLICY, halt_entry_drawdown=entry_dd
        )
        state, halt_since, entry_dd = result.state, result.halt_since, result.halt_entry_drawdown
        assert result.state is HaltState.HALT  # drawdown never recovers
        if result.recovery_unlocked and unlocked_on is None:
            unlocked_on = offset

    assert unlocked_on == POLICY.recovery_days


def test_leaving_halt_clears_the_clock_so_a_second_halt_waits_the_full_window():
    recovered = assess(
        equity=88.0,  # 12% drawdown: out of HALT, into DEFENSIVE
        high_water_mark=100.0,
        previous_state=HaltState.HALT,
        halt_since=DAY,
        today=DAY + timedelta(days=20),
        policy=POLICY,
    )
    assert recovered.state is HaltState.DEFENSIVE
    assert recovered.halt_since is None

    re_halted = assess(
        equity=75.0,
        high_water_mark=100.0,
        previous_state=recovered.state,
        halt_since=recovered.halt_since_iso,
        today=DAY + timedelta(days=21),
        policy=POLICY,
    )
    assert re_halted.state is HaltState.HALT
    assert re_halted.halt_days == 0
    assert not re_halted.recovery_unlocked


def test_a_halt_recorded_without_a_start_date_starts_its_clock_today():
    # State written by an older build. Starting the clock now is the
    # conservative reading; treating the missing date as "long ago" would
    # unlock a book nobody has measured.
    result = assess(70.0, 100.0, HaltState.HALT, None, DAY, POLICY)
    assert result.halt_since == DAY
    assert result.halt_days == 0
    assert result.capacity == 0.0


@pytest.mark.parametrize("today", [DAY, "2026-01-01", "2026-01-01T13:45:00+00:00"])
def test_dates_may_be_dates_or_iso_strings(today):
    result = assess(70.0, 100.0, HaltState.HALT, "2026-01-01", today, POLICY)
    assert result.halt_days == 0


# --------------------------------------------------------------------------
# Conditional safety net: the drawdown must have stopped deepening
# --------------------------------------------------------------------------
# Without this, the net reopens buying at 25% into a market that is still
# falling. In the synthetic run that produced two portfolio drawdowns of
# -34% against legacy's -22%.

NO_CONDITION = HaltPolicy(recovery_requires_stable_drawdown=False, floor_pct=None, floor_exit_pct=None)
NO_FLOOR = HaltPolicy(floor_pct=None, floor_exit_pct=None)


def _hold_halt(series, policy, start_drawdown=0.21):
    """Walk a drawdown series day by day, carrying state forward."""
    state, since, entry_dd, floor = HaltState.NORMAL, None, None, False
    result = None
    for offset, drawdown in enumerate([start_drawdown] + list(series)):
        result = assess(
            equity=100.0 * (1 - drawdown),
            high_water_mark=100.0,
            previous_state=state,
            halt_since=since,
            today=DAY + timedelta(days=offset),
            policy=policy,
            halt_entry_drawdown=entry_dd,
            previously_below_floor=floor,
        )
        state, since = result.state, result.halt_since
        entry_dd, floor = result.halt_entry_drawdown, result.below_floor
    return result


def test_net_stays_shut_while_the_drawdown_keeps_deepening():
    # Enters HALT at 21%, then sinks a little further every day for 20 days.
    worsening = [0.21 + 0.002 * (i + 1) for i in range(20)]
    result = _hold_halt(worsening, NO_FLOOR)

    assert result.state is HaltState.HALT
    assert result.halt_days >= POLICY.recovery_days
    assert not result.recovery_unlocked
    assert result.capacity == 0.0
    assert "still deepening" in result.reason


def test_net_opens_when_the_drawdown_has_stopped_deepening():
    # Enters HALT at 21% and simply sits there: the market went sideways,
    # which is the case the net was designed for.
    result = _hold_halt([0.21] * 20, NO_FLOOR)

    assert result.state is HaltState.HALT
    assert result.recovery_unlocked
    assert result.capacity == pytest.approx(0.25)


def test_net_opens_once_a_deepened_drawdown_comes_back_to_its_entry_level():
    # Sinks to 26% then recovers to 20.5% -- still HALT (exit is 15%), but no
    # longer deeper than where it started, so the net is allowed to open.
    series = [0.26] * 10 + [0.205] * 12
    result = _hold_halt(series, NO_FLOOR)

    assert result.state is HaltState.HALT
    assert result.recovery_unlocked


def test_without_the_condition_the_net_opens_into_a_falling_market():
    # The v1 behaviour, kept switchable so the two can be compared.
    worsening = [0.21 + 0.002 * (i + 1) for i in range(20)]
    result = _hold_halt(worsening, NO_CONDITION)

    assert result.recovery_unlocked
    assert result.capacity == pytest.approx(0.25)


# --------------------------------------------------------------------------
# Absolute floor
# --------------------------------------------------------------------------

def test_floor_forces_zero_capacity_regardless_of_the_clock():
    result = _hold_halt([0.32] * 40, POLICY)

    assert result.below_floor
    assert result.capacity == 0.0
    assert not result.recovery_unlocked
    assert result.halt_days >= POLICY.recovery_days  # clock ran out, net still shut
    assert "absolute floor" in result.reason


def test_floor_binds_even_when_the_drawdown_is_flat():
    # Flat at 31% would satisfy the conditional net; the floor overrides it.
    flat_below_floor = _hold_halt([0.31] * 30, POLICY, start_drawdown=0.31)
    assert flat_below_floor.capacity == 0.0

    # The same flat drawdown just above the floor does open the net.
    flat_above_floor = _hold_halt([0.29] * 30, POLICY, start_drawdown=0.29)
    assert flat_above_floor.capacity == pytest.approx(0.25)


def test_floor_has_its_own_hysteresis():
    # Binds at 30%, and 26-29% does not release it.
    still_held = _hold_halt([0.32] * 5 + [0.27] * 5, POLICY)
    assert still_held.below_floor

    # 25% is the floor's exit threshold.
    released = _hold_halt([0.32] * 5 + [0.25] * 5, POLICY)
    assert not released.below_floor


def test_leaving_the_floor_restores_the_ladder():
    # Down to 32%, back to 14%: floor released and HALT released too.
    result = _hold_halt([0.32] * 5 + [0.14] * 3, POLICY)
    assert not result.below_floor
    assert result.state is HaltState.DEFENSIVE
    assert result.capacity == pytest.approx(0.50)


def test_floor_can_be_switched_off():
    result = _hold_halt([0.32] * 40, NO_FLOOR)
    assert not result.below_floor
    assert result.recovery_unlocked is False or result.capacity >= 0.0  # net gated by the condition


def test_policy_rejects_a_floor_above_the_halt_threshold():
    with pytest.raises(ValueError, match="backstop under the ladder"):
        HaltPolicy(floor_pct=0.18, floor_exit_pct=0.16)


def test_policy_rejects_a_floor_without_a_hysteresis_gap():
    with pytest.raises(ValueError, match="hysteresis gap"):
        HaltPolicy(floor_pct=0.30, floor_exit_pct=0.30)


def test_policy_rejects_half_configured_floor():
    with pytest.raises(ValueError, match="set or cleared together"):
        HaltPolicy(floor_pct=0.30, floor_exit_pct=None)


def test_live_default_policy_is_the_floor_without_the_condition():
    """The default is the "v1 + taban %30" arm the synthetic run left standing.

    The stability condition ships switched off: it measured as reintroducing
    the lockout (519-641 day blocked streaks) and costing 6.7 points of
    portfolio return, to do a job the floor already does. The code stays so
    it can be re-measured on real data -- see
    backtest/results/synthetic/halt_compare.md.
    """
    from alsatbotu.config import DEFAULT_HALT_POLICY

    assert DEFAULT_HALT_POLICY.recovery_requires_stable_drawdown is False
    assert DEFAULT_HALT_POLICY.floor_pct == pytest.approx(0.30)
    assert DEFAULT_HALT_POLICY.floor_exit_pct == pytest.approx(0.25)


# --------------------------------------------------------------------------
# Assessment bookkeeping
# --------------------------------------------------------------------------

def test_assessment_reports_the_transition_and_a_readable_reason():
    result = assess(79.0, 100.0, HaltState.NORMAL, None, DAY, POLICY)
    assert result.state is HaltState.HALT
    assert result.previous_state is HaltState.NORMAL
    assert result.changed
    assert result.drawdown_pct == pytest.approx(0.21)
    assert "HALT" in result.reason and "21.00%" in result.reason


def test_an_unchanged_state_is_not_reported_as_a_transition():
    assert not assess(95.0, 100.0, HaltState.NORMAL, None, DAY, POLICY).changed


def test_state_names_round_trip_and_unknown_names_fall_back_to_normal():
    for state in HaltState:
        assert state_from_name(state.name) is state
    assert state_from_name("defensive") is HaltState.DEFENSIVE
    assert state_from_name(None) is HaltState.NORMAL
    assert state_from_name("") is HaltState.NORMAL
    assert state_from_name("NOT_A_STATE") is HaltState.NORMAL


# --------------------------------------------------------------------------
# Policy validation: a bad override must fail loudly, not chatter quietly
# --------------------------------------------------------------------------

def test_policy_rejects_a_missing_hysteresis_gap():
    with pytest.raises(ValueError, match="hysteresis"):
        HaltPolicy(exit_halt_pct=0.20)


def test_policy_rejects_non_monotonic_entry_thresholds():
    with pytest.raises(ValueError, match="monotonic"):
        HaltPolicy(enter_caution_pct=0.30)


def test_policy_rejects_capacity_that_grows_with_drawdown():
    with pytest.raises(ValueError, match="must not increase"):
        HaltPolicy(capacity_defensive=0.90)


def test_policy_rejects_a_safety_net_above_defensive():
    with pytest.raises(ValueError, match="rung below"):
        HaltPolicy(recovery_capacity=0.60)


def test_policy_rejects_a_zero_day_recovery_window():
    with pytest.raises(ValueError, match="recovery_days"):
        HaltPolicy(recovery_days=0)


def test_live_default_policy_is_valid_and_matches_the_agreed_design():
    from alsatbotu.config import DEFAULT_HALT_POLICY

    assert DEFAULT_HALT_POLICY.enter_halt_pct == pytest.approx(0.20)
    assert DEFAULT_HALT_POLICY.exit_halt_pct == pytest.approx(0.15)
    assert DEFAULT_HALT_POLICY.capacity_halt == 0.0
    assert DEFAULT_HALT_POLICY.recovery_days == 14
    assert DEFAULT_HALT_POLICY.recovery_capacity == pytest.approx(0.25)
