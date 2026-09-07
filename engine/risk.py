"""Risk engine: position sizing and portfolio-level guardrails for paper trading.

Rules:
  - Position size risks at most `RISK_PER_TRADE_PCT` (2%) of current equity,
    sized off the distance between entry price and the ATR stop.
  - The ATR stop uses the same multiplier as the SELL rule in
    `alsatbotu.signal` (entry_price - ATR_STOP_MULTIPLIER * atr), so a
    position's stop is consistent with the rule that would exit it.
  - No single category (see `alsatbotu.config.SYMBOL_CATEGORIES`) may hold
    more than `CATEGORY_EXPOSURE_LIMIT_PCT` (40%) of equity.
  - At most `MAX_OPEN_POSITIONS` (8) positions open at once.
  - Drawdown from the equity high-water mark limits how much of the
    risk-sized position may actually be taken. Two mechanisms exist:

      * Legacy (default): a single latch at `MAX_DRAWDOWN_PCT` (20%). No new
        BUYs past it; existing positions may still be sold.
      * Graduated (`policy=`): the four-state machine in `engine/halt.py`,
        which scales the position down (100/75/50%) before it stops buying
        and can release itself again. Opt-in per call, so the live runner
        keeps the legacy behaviour until it is switched over deliberately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from alsatbotu.config import (
    CATEGORY_EXPOSURE_LIMIT_PCT,
    MAX_DRAWDOWN_PCT,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
)
from alsatbotu.signal import ATR_STOP_MULTIPLIER
from engine.halt import DateLike, HaltAssessment, HaltPolicy, assess, state_from_name
from portfolio.state import PortfolioState


def compute_atr_stop(entry_price: float, atr: float) -> float:
    return entry_price - ATR_STOP_MULTIPLIER * atr


def compute_position_size(equity: float, entry_price: float, stop_price: float) -> float:
    """Quantity to buy so that a stop-out risks `RISK_PER_TRADE_PCT` of equity."""
    risk_per_unit = entry_price - stop_price
    if risk_per_unit <= 0:
        return 0.0
    risk_budget = equity * RISK_PER_TRADE_PCT
    return risk_budget / risk_per_unit


def is_drawdown_halted(
    current_equity: float, peak_equity: float, max_drawdown_pct: float | None = None
) -> bool:
    """True when equity is `max_drawdown_pct` or more below its peak.

    `max_drawdown_pct` defaults to the live `MAX_DRAWDOWN_PCT`; callers pass
    it explicitly only to test alternative thresholds (backtest/halt_sweep.py).
    """
    if peak_equity <= 0:
        return False
    threshold = MAX_DRAWDOWN_PCT if max_drawdown_pct is None else max_drawdown_pct
    drawdown = (peak_equity - current_equity) / peak_equity
    return drawdown >= threshold


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    quantity: float = 0.0
    stop_price: float = 0.0
    capped_by: str | None = None
    # Only set when `evaluate_buy` ran with a graduated `policy`.
    halt: Optional[HaltAssessment] = None


def assess_halt(
    state: PortfolioState,
    equity: float,
    policy: HaltPolicy,
    today: Optional[DateLike] = None,
) -> HaltAssessment:
    """Run the state machine against live equity and the recorded posture.

    Deliberately re-derived rather than read straight off `state.halt_state`:
    a deepening drawdown then takes effect on the mark it happens, not on the
    next time someone remembers to call `update_halt_state()`. The recorded
    state still matters -- it carries the hysteresis and the HALT clock.
    """
    return assess(
        equity=equity,
        high_water_mark=state.peak_equity,
        previous_state=state_from_name(state.halt_state),
        halt_since=state.halt_since,
        today=today,
        policy=policy,
        halt_entry_drawdown=state.halt_entry_drawdown,
        previously_below_floor=state.below_floor,
    )


def evaluate_buy(
    state: PortfolioState,
    symbol: str,
    category: str,
    entry_price: float,
    atr: float,
    current_prices: dict[str, float],
    max_drawdown_pct: float | None = None,
    policy: Optional[HaltPolicy] = None,
    today: Optional[DateLike] = None,
) -> RiskDecision:
    """Decide whether to open a new position and, if so, at what size.

    Available cash, the category exposure cap and -- with a graduated
    `policy` -- the drawdown state's capacity *size down* the position rather
    than veto it: the 2%-risk quantity is what the trade would like to be,
    and the limits are the room it actually has. Only a limit with no room
    left at all (or a blocked portfolio) rejects the trade.

    `policy` selects the drawdown mechanism. Left as None the legacy latch at
    `max_drawdown_pct` (default `MAX_DRAWDOWN_PCT`) applies, unchanged. Given
    a `HaltPolicy`, the four-state machine applies instead and
    `max_drawdown_pct` is ignored -- the two are alternatives, not layers.
    """
    equity = state.equity(current_prices)
    reasons: list[str] = []
    halt: Optional[HaltAssessment] = None

    if symbol in state.open_positions:
        reasons.append(f"Position already open for {symbol}")

    if policy is None:
        halt_threshold = MAX_DRAWDOWN_PCT if max_drawdown_pct is None else max_drawdown_pct
        if is_drawdown_halted(equity, state.peak_equity, halt_threshold):
            reasons.append(
                f"Drawdown halt: equity {equity:.2f} is more than "
                f"{halt_threshold * 100:.0f}% below peak {state.peak_equity:.2f}"
            )
    else:
        halt = assess_halt(state, equity, policy, today)
        if halt.blocks_new_buys:
            # The "Drawdown halt" prefix is load-bearing: backtest/halt_sweep.py
            # counts blocked BUY signals by matching it.
            reasons.append(f"Drawdown halt: {halt.reason}")

    if len(state.open_positions) >= MAX_OPEN_POSITIONS:
        reasons.append(f"Max open positions reached ({MAX_OPEN_POSITIONS})")

    if atr is None or atr <= 0:
        reasons.append("No valid ATR available to size a stop")

    if reasons:
        return RiskDecision(approved=False, reasons=reasons, halt=halt)

    stop_price = compute_atr_stop(entry_price, atr)
    quantity = compute_position_size(equity, entry_price, stop_price)
    if quantity <= 0:
        return RiskDecision(
            approved=False,
            reasons=["Computed position size is zero (stop not below entry)"],
            stop_price=stop_price,
            halt=halt,
        )

    category_room = (
        equity * CATEGORY_EXPOSURE_LIMIT_PCT - state.category_exposure(category, current_prices)
    )
    limits = {
        "cash": state.cash / entry_price,
        f"category {category!r} {CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f}% limit": (
            max(category_room, 0.0) / entry_price
        ),
    }
    if halt is not None and halt.capacity < 1.0:
        # A capacity cut scales the risk-sized quantity itself, so it reads as
        # "half a normal position", independent of price or available cash.
        limits[f"drawdown state {halt.state.name} ({halt.capacity * 100:.0f}% capacity)"] = (
            quantity * halt.capacity
        )

    capped_by = None
    for label, max_quantity in limits.items():
        if max_quantity < quantity:
            quantity = max_quantity
            capped_by = label

    if quantity <= 0:
        return RiskDecision(
            approved=False,
            reasons=[f"No room to open a position: {capped_by} is exhausted"],
            stop_price=stop_price,
            halt=halt,
        )

    return RiskDecision(
        approved=True,
        quantity=quantity,
        stop_price=stop_price,
        capped_by=capped_by,
        halt=halt,
    )
