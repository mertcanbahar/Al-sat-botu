"""Risk engine: position sizing and portfolio-level guardrails for paper trading.

Rules:
  - Position size risks at most `RISK_PER_TRADE_PCT` (2%) of current equity,
    sized off the distance between entry price and the ATR stop.
  - The ATR stop uses the same multiplier as the SELL rule in
    `alsatbotu.rules` (entry_price - ATR_STOP_MULTIPLIER * atr), so a
    position's stop is consistent with the rule that would exit it.
  - No single category (see `alsatbotu.config.SYMBOL_CATEGORIES`) may hold
    more than `CATEGORY_EXPOSURE_LIMIT_PCT` (40%) of equity.
  - At most `MAX_OPEN_POSITIONS` (8) positions open at once.
  - No new BUYs once equity has drawn down more than `MAX_DRAWDOWN_PCT`
    (20%) from its peak; existing positions may still be sold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from alsatbotu.config import (
    CATEGORY_EXPOSURE_LIMIT_PCT,
    MAX_DRAWDOWN_PCT,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
)
from alsatbotu.rules import ATR_STOP_MULTIPLIER
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


def is_drawdown_halted(current_equity: float, peak_equity: float) -> bool:
    if peak_equity <= 0:
        return False
    drawdown = (peak_equity - current_equity) / peak_equity
    return drawdown >= MAX_DRAWDOWN_PCT


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    quantity: float = 0.0
    stop_price: float = 0.0
    capped_by: str | None = None


def evaluate_buy(
    state: PortfolioState,
    symbol: str,
    category: str,
    entry_price: float,
    atr: float,
    current_prices: dict[str, float],
) -> RiskDecision:
    """Decide whether to open a new position and, if so, at what size.

    Available cash and the category exposure cap *size down* the position
    rather than veto it: the 2%-risk quantity is what the trade would like
    to be, and the limits are the room it actually has. Only a limit with
    no room left at all (or a blocked portfolio) rejects the trade.
    """
    equity = state.equity(current_prices)
    reasons: list[str] = []

    if symbol in state.open_positions:
        reasons.append(f"Position already open for {symbol}")

    if is_drawdown_halted(equity, state.peak_equity):
        reasons.append(
            f"Drawdown halt: equity {equity:.2f} is more than "
            f"{MAX_DRAWDOWN_PCT * 100:.0f}% below peak {state.peak_equity:.2f}"
        )

    if len(state.open_positions) >= MAX_OPEN_POSITIONS:
        reasons.append(f"Max open positions reached ({MAX_OPEN_POSITIONS})")

    if atr is None or atr <= 0:
        reasons.append("No valid ATR available to size a stop")

    if reasons:
        return RiskDecision(approved=False, reasons=reasons)

    stop_price = compute_atr_stop(entry_price, atr)
    quantity = compute_position_size(equity, entry_price, stop_price)
    if quantity <= 0:
        return RiskDecision(
            approved=False,
            reasons=["Computed position size is zero (stop not below entry)"],
            stop_price=stop_price,
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
        )

    return RiskDecision(
        approved=True, quantity=quantity, stop_price=stop_price, capped_by=capped_by
    )
