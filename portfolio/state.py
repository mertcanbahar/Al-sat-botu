"""Paper portfolio state: cash, open positions, and closed trades.

Persisted as a single JSON file (`data/portfolio.json` by default -- see
`alsatbotu.config.PORTFOLIO_STATE_PATH`). Starting capital comes from
`alsatbotu.config.STARTING_CAPITAL` and is only used the first time a
portfolio is created; once a state file exists it is the source of truth.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from alsatbotu.config import DEFAULT_HALT_POLICY, PORTFOLIO_STATE_PATH, STARTING_CAPITAL
from engine.halt import (
    DateLike,
    HaltAssessment,
    HaltPolicy,
    HaltState,
    assess,
    state_from_name,
    update_high_water_mark,
)


@dataclass
class Position:
    symbol: str
    category: str
    quantity: float
    entry_price: float
    entry_date: str
    stop_price: float


@dataclass
class ClosedTrade:
    symbol: str
    category: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class PortfolioState:
    cash: float
    starting_capital: float
    # Highest equity ever marked (the high-water mark). Kept under its
    # original name because `docs/index.html` reads `peak_equity` straight
    # out of the saved JSON; `high_water_mark` below is the same number under
    # the name the drawdown formula uses.
    peak_equity: float
    open_positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    # Drawdown state machine (engine/halt.py). Persisted as a plain name and
    # ISO date so state files stay readable and older files, which have
    # neither key, load as a book that has never been in trouble.
    halt_state: str = HaltState.NORMAL.name
    halt_since: Optional[str] = None

    @property
    def high_water_mark(self) -> float:
        return self.peak_equity

    def position_value(self, current_prices: dict[str, float]) -> float:
        return sum(
            position.quantity * current_prices.get(symbol, position.entry_price)
            for symbol, position in self.open_positions.items()
        )

    def equity(self, current_prices: dict[str, float]) -> float:
        return self.cash + self.position_value(current_prices)

    def category_exposure(self, category: str, current_prices: dict[str, float]) -> float:
        return sum(
            position.quantity * current_prices.get(symbol, position.entry_price)
            for symbol, position in self.open_positions.items()
            if position.category == category
        )


def _new_state() -> PortfolioState:
    return PortfolioState(
        cash=STARTING_CAPITAL,
        starting_capital=STARTING_CAPITAL,
        peak_equity=STARTING_CAPITAL,
    )


def load_state(path: Path = PORTFOLIO_STATE_PATH) -> PortfolioState:
    """Load portfolio state from `path`, creating a fresh one if it doesn't exist."""
    if not os.path.exists(path):
        return _new_state()

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return PortfolioState(
        cash=raw["cash"],
        starting_capital=raw["starting_capital"],
        peak_equity=raw["peak_equity"],
        open_positions={
            symbol: Position(**data) for symbol, data in raw.get("open_positions", {}).items()
        },
        closed_trades=[ClosedTrade(**data) for data in raw.get("closed_trades", [])],
        # Absent in every state file written before the state machine existed.
        halt_state=raw.get("halt_state", HaltState.NORMAL.name),
        halt_since=raw.get("halt_since"),
    )


def save_state(state: PortfolioState, path: Path = PORTFOLIO_STATE_PATH) -> None:
    """Write `state` to `path` atomically (write to a temp file, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "cash": state.cash,
        "starting_capital": state.starting_capital,
        "peak_equity": state.peak_equity,
        "open_positions": {
            symbol: asdict(position) for symbol, position in state.open_positions.items()
        },
        "closed_trades": [asdict(trade) for trade in state.closed_trades],
        "halt_state": state.halt_state,
        "halt_since": state.halt_since,
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def update_peak_equity(state: PortfolioState, current_prices: dict[str, float]) -> float:
    """Update and return `state.peak_equity` given the latest equity mark."""
    equity = state.equity(current_prices)
    state.peak_equity = update_high_water_mark(state.peak_equity, equity)
    return equity


def update_halt_state(
    state: PortfolioState,
    equity: float,
    today: Optional[DateLike] = None,
    policy: Optional[HaltPolicy] = None,
) -> HaltAssessment:
    """Advance the drawdown state machine one mark and record the result.

    Call this once per equity mark, right after `update_peak_equity()`, so the
    HALT clock advances on calendar days and the recorded state reflects the
    latest close. `engine.risk.evaluate_buy()` re-derives the state from live
    equity rather than trusting this field, so a caller that skips this step
    still gets correct sizing -- it just loses the persisted clock, which is
    what the time-based safety net runs on.
    """
    assessment = assess(
        equity=equity,
        high_water_mark=state.peak_equity,
        previous_state=state_from_name(state.halt_state),
        halt_since=state.halt_since,
        today=today,
        policy=policy or DEFAULT_HALT_POLICY,
    )
    state.halt_state = assessment.state.name
    state.halt_since = assessment.halt_since_iso
    return assessment


def open_position(
    state: PortfolioState,
    symbol: str,
    category: str,
    quantity: float,
    entry_price: float,
    entry_date: str,
    stop_price: float,
) -> Position:
    if symbol in state.open_positions:
        raise ValueError(f"Position already open for {symbol!r}")

    position = Position(
        symbol=symbol,
        category=category,
        quantity=quantity,
        entry_price=entry_price,
        entry_date=entry_date,
        stop_price=stop_price,
    )
    state.cash -= quantity * entry_price
    state.open_positions[symbol] = position
    return position


def close_position(
    state: PortfolioState,
    symbol: str,
    exit_price: float,
    exit_date: str,
    reason: str,
) -> Optional[ClosedTrade]:
    position = state.open_positions.pop(symbol, None)
    if position is None:
        return None

    proceeds = position.quantity * exit_price
    cost = position.quantity * position.entry_price
    state.cash += proceeds

    trade = ClosedTrade(
        symbol=position.symbol,
        category=position.category,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_date=position.entry_date,
        exit_date=exit_date,
        pnl=proceeds - cost,
        pnl_pct=(exit_price / position.entry_price - 1.0) if position.entry_price else 0.0,
        reason=reason,
    )
    state.closed_trades.append(trade)
    return trade
