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


def evaluate_buy(
    state: PortfolioState,
    symbol: str,
    category: str,
    entry_price: float,
    atr: float,
    current_prices: dict[str, float],
) -> RiskDecision:
    """Decide whether to open a new position and, if so, at what size."""
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
        return RiskDecision(approved=False, reasons=reasons)

    stop_price = compute_atr_stop(entry_price, atr)
    quantity = compute_position_size(equity, entry_price, stop_price)

    if quantity <= 0:
        reasons.append("Computed position size is zero (stop not below entry)")

    cost = quantity * entry_price
    if cost > state.cash:
        reasons.append(f"Insufficient cash: need {cost:.2f}, have {state.cash:.2f}")

    category_exposure = state.category_exposure(category, current_prices) + cost
    category_limit = equity * CATEGORY_EXPOSURE_LIMIT_PCT
    if category_exposure > category_limit:
        reasons.append(
            f"Category {category!r} exposure {category_exposure:.2f} would exceed "
            f"{CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f}% limit ({category_limit:.2f})"
        )

    if reasons:
        return RiskDecision(approved=False, reasons=reasons, quantity=quantity, stop_price=stop_price)

    return RiskDecision(approved=True, quantity=quantity, stop_price=stop_price)
