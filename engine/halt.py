"""Graduated drawdown state machine: how much new risk the book may take on.

The old rule was a single latch: once equity sat `MAX_DRAWDOWN_PCT` below its
peak, `evaluate_buy()` refused every BUY. That rule cannot release itself --
new buys are the only mechanism that can carry equity back toward its peak, so
an account that halts while fully in cash has a frozen equity curve and a
drawdown that can never improve. `backtest/halt_threshold_findings.md` measured
this: at 20%, 6 of 20 isolated accounts halted and never traded again.

This module replaces the latch with four graduated states. Each state caps how
much of the risk-sized position the book may actually take, so the account
scales down instead of switching off:

    NORMAL     drawdown 0-10%    100% of the risk-sized position
    CAUTION    drawdown 10-15%    75%
    DEFENSIVE  drawdown 15-20%    50%
    HALT       drawdown 20%+       0%, escalating to 25% after `recovery_days`

Three properties make it non-terminal:

  * Graduated capacity. CAUTION and DEFENSIVE keep the account trading at a
    reduced size, so equity keeps moving and the drawdown can actually recover.
    This, not the hysteresis, is what breaks the deadlock.
  * Hysteresis. Entering a state and leaving it use different thresholds (enter
    HALT at 20%, leave at 15%), so a drawdown oscillating around a boundary
    does not flip the book on and off day after day.
  * A time-based safety net. If HALT persists for `recovery_days` calendar days
    the account reopens at `recovery_capacity` -- a rung below DEFENSIVE --
    rather than staying locked forever waiting for a recovery it cannot fund.

Everything here is pure: no I/O, no portfolio, no config import. Callers supply
equity, the high-water mark, the previously recorded state, and today's date;
`alsatbotu.config.DEFAULT_HALT_POLICY` holds the live tuning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional, Union

DateLike = Union[date, datetime, str]


class HaltState(Enum):
    """Risk postures, ordered shallow (0) to deep (3)."""

    NORMAL = 0
    CAUTION = 1
    DEFENSIVE = 2
    HALT = 3


# Deepest-first is the order thresholds are checked in; NORMAL has no entry
# threshold of its own (it is where you land when no other state applies).
_DEEPENING_ORDER = (HaltState.CAUTION, HaltState.DEFENSIVE, HaltState.HALT)


def state_from_name(name: Optional[str]) -> HaltState:
    """Parse a persisted state name, falling back to NORMAL.

    Portfolio JSON written before this module existed has no state field at
    all, and an unrecognised name is more likely a typo in an env override
    than a real posture -- both resolve to NORMAL, the same posture those
    accounts effectively had.
    """
    if not name:
        return HaltState.NORMAL
    try:
        return HaltState[name.strip().upper()]
    except KeyError:
        return HaltState.NORMAL


@dataclass(frozen=True)
class HaltPolicy:
    """Thresholds and capacities for the state machine.

    Entry thresholds must deepen monotonically, and each state's exit
    threshold must sit strictly below its entry threshold -- that gap *is* the
    hysteresis. `__post_init__` enforces both, so a bad env override fails at
    import time instead of silently producing a machine that chatters.
    """

    enter_caution_pct: float = 0.10
    enter_defensive_pct: float = 0.15
    enter_halt_pct: float = 0.20

    exit_caution_pct: float = 0.05
    exit_defensive_pct: float = 0.10
    exit_halt_pct: float = 0.15

    capacity_normal: float = 1.00
    capacity_caution: float = 0.75
    capacity_defensive: float = 0.50
    capacity_halt: float = 0.00

    recovery_days: int = 14
    recovery_capacity: float = 0.25

    def __post_init__(self) -> None:
        enters = [self.enter_caution_pct, self.enter_defensive_pct, self.enter_halt_pct]
        if not all(0.0 < value < 1.0 for value in enters):
            raise ValueError(f"Halt entry thresholds must be between 0 and 1: {enters}")
        if not enters[0] < enters[1] < enters[2]:
            raise ValueError(
                "Halt entry thresholds must deepen monotonically "
                f"(caution < defensive < halt): {enters}"
            )

        for state in _DEEPENING_ORDER:
            enter, leave = self.enter_threshold(state), self.exit_threshold(state)
            if not 0.0 <= leave < enter:
                raise ValueError(
                    f"{state.name} exit threshold ({leave}) must be >= 0 and strictly "
                    f"below its entry threshold ({enter}) to give hysteresis a gap"
                )

        capacities = [
            self.capacity_normal,
            self.capacity_caution,
            self.capacity_defensive,
            self.capacity_halt,
        ]
        if not all(0.0 <= value <= 1.0 for value in capacities):
            raise ValueError(f"Capacities must be between 0 and 1: {capacities}")
        if any(a < b for a, b in zip(capacities, capacities[1:])):
            raise ValueError(f"Capacity must not increase as drawdown deepens: {capacities}")

        if self.recovery_days < 1:
            raise ValueError(f"recovery_days must be at least 1: {self.recovery_days}")
        if not 0.0 <= self.recovery_capacity <= 1.0:
            raise ValueError(f"recovery_capacity must be between 0 and 1: {self.recovery_capacity}")
        if self.recovery_capacity > self.capacity_defensive:
            raise ValueError(
                f"recovery_capacity ({self.recovery_capacity}) must not exceed DEFENSIVE "
                f"capacity ({self.capacity_defensive}) -- the safety net is a rung below "
                "DEFENSIVE, not a promotion"
            )

    def enter_threshold(self, state: HaltState) -> float:
        return {
            HaltState.NORMAL: 0.0,
            HaltState.CAUTION: self.enter_caution_pct,
            HaltState.DEFENSIVE: self.enter_defensive_pct,
            HaltState.HALT: self.enter_halt_pct,
        }[state]

    def exit_threshold(self, state: HaltState) -> float:
        return {
            HaltState.NORMAL: 0.0,
            HaltState.CAUTION: self.exit_caution_pct,
            HaltState.DEFENSIVE: self.exit_defensive_pct,
            HaltState.HALT: self.exit_halt_pct,
        }[state]

    def capacity_for(self, state: HaltState) -> float:
        return {
            HaltState.NORMAL: self.capacity_normal,
            HaltState.CAUTION: self.capacity_caution,
            HaltState.DEFENSIVE: self.capacity_defensive,
            HaltState.HALT: self.capacity_halt,
        }[state]


@dataclass(frozen=True)
class HaltAssessment:
    """What the state machine concluded for one equity mark."""

    state: HaltState
    previous_state: HaltState
    capacity: float
    drawdown_pct: float
    high_water_mark: float
    halt_since: Optional[date]
    halt_days: int
    recovery_unlocked: bool
    reason: str

    @property
    def changed(self) -> bool:
        return self.state is not self.previous_state

    @property
    def blocks_new_buys(self) -> bool:
        return self.capacity <= 0.0

    @property
    def halt_since_iso(self) -> Optional[str]:
        return self.halt_since.isoformat() if self.halt_since else None


def drawdown_pct(equity: float, high_water_mark: float) -> float:
    """Drawdown below the high-water mark, as a positive magnitude.

    The high-water mark is the highest equity ever marked, so this is
    `(high_water_mark - equity) / high_water_mark`. Sign convention: this
    module and the rest of the codebase (`scripts/daily_report.py`,
    `engine.risk.is_drawdown_halted`) carry drawdown as a positive number --
    0.20 means "20% below the peak" -- rather than the signed -0.20.

    A non-positive high-water mark (a fresh or wiped-out account) reports no
    drawdown: there is no peak to measure against, and the old rule guarded
    the same case the same way.
    """
    if high_water_mark <= 0:
        return 0.0
    return max(0.0, (high_water_mark - equity) / high_water_mark)


def update_high_water_mark(high_water_mark: float, equity: float) -> float:
    """`high_water_mark = max(high_water_mark, equity)`, named for what it is."""
    return max(high_water_mark, equity)


def _as_date(value: Optional[DateLike]) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # ISO strings appear both as bare dates ("2026-09-07", from the backtest)
    # and as full timestamps (from portfolio state files).
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _today(value: Optional[DateLike]) -> date:
    return _as_date(value) or datetime.now(timezone.utc).date()


def next_state(previous: HaltState, drawdown: float, policy: HaltPolicy) -> HaltState:
    """The state `drawdown` implies, given where the book already was.

    Deepening is immediate and may skip rungs: a drawdown that gaps from 0% to
    25% in one mark goes straight to HALT rather than stepping down over three
    days. Recovering is gated by the exit thresholds -- the book leaves a state
    only once drawdown falls to that state's exit level -- but it, too, may
    cross several rungs at once when equity recovers in one move.
    """
    deepest = HaltState.NORMAL
    for state in _DEEPENING_ORDER:
        if drawdown >= policy.enter_threshold(state):
            deepest = state
    if deepest.value > previous.value:
        return deepest

    current = previous
    while current is not HaltState.NORMAL and drawdown <= policy.exit_threshold(current):
        current = HaltState(current.value - 1)
    return current


def assess(
    equity: float,
    high_water_mark: float,
    previous_state: HaltState = HaltState.NORMAL,
    halt_since: Optional[DateLike] = None,
    today: Optional[DateLike] = None,
    policy: Optional[HaltPolicy] = None,
) -> HaltAssessment:
    """Evaluate one equity mark against the state machine.

    Pure: nothing is mutated and nothing is read from disk. `previous_state`
    and `halt_since` are whatever the caller last persisted (see
    `portfolio.state.update_halt_state`); passing the defaults evaluates the
    book as if it had never been in trouble.

    The HALT clock starts the day HALT is entered and is cleared the moment the
    book leaves HALT, so a second HALT is a full `recovery_days` wait rather
    than an instant reopen. A book recorded as HALT with no recorded start date
    (state written by an older build) starts its clock today -- the
    conservative reading, since the alternative would unlock it immediately.
    """
    policy = policy or HaltPolicy()
    today_date = _today(today)
    drawdown = drawdown_pct(equity, high_water_mark)
    state = next_state(previous_state, drawdown, policy)

    if state is HaltState.HALT:
        started = _as_date(halt_since) if previous_state is HaltState.HALT else None
        started = started or today_date
        halt_days = max(0, (today_date - started).days)
    else:
        started = None
        halt_days = 0

    capacity = policy.capacity_for(state)
    recovery_unlocked = state is HaltState.HALT and halt_days >= policy.recovery_days
    if recovery_unlocked:
        capacity = max(capacity, policy.recovery_capacity)

    return HaltAssessment(
        state=state,
        previous_state=previous_state,
        capacity=capacity,
        drawdown_pct=drawdown,
        high_water_mark=high_water_mark,
        halt_since=started,
        halt_days=halt_days,
        recovery_unlocked=recovery_unlocked,
        reason=_describe(state, drawdown, capacity, halt_days, recovery_unlocked, policy),
    )


def _describe(
    state: HaltState,
    drawdown: float,
    capacity: float,
    halt_days: int,
    recovery_unlocked: bool,
    policy: HaltPolicy,
) -> str:
    head = (
        f"{state.name}: drawdown {drawdown * 100:.2f}% from the high-water mark, "
        f"position capacity {capacity * 100:.0f}%"
    )
    if state is not HaltState.HALT:
        return head
    if recovery_unlocked:
        return (
            f"{head} (HALT for {halt_days} days, past the {policy.recovery_days}-day "
            "safety net, so sizing reopens at the smallest rung)"
        )
    return (
        f"{head} (HALT for {halt_days} of the {policy.recovery_days} days before the "
        "safety net reopens sizing)"
    )
