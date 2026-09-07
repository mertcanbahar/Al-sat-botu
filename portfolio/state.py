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

from alsatbotu.config import PORTFOLIO_STATE_PATH, STARTING_CAPITAL


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
    peak_equity: float
    open_positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)

    # -- Drawdown halt durumu (engine.risk.update_halt_state sahibidir) ----
    # Halt artık anlık bir hesap değil, kalıcı bir durum: bir kez tetiklenince
    # ancak toparlanma (histerezis) ya da kısmi peak reset'i onu bırakır.
    halted: bool = False
    halted_since: Optional[str] = None
    # Halt başladığından (ya da son reset'ten) beri kaç kez equity işaretlendi.
    halted_marks: int = 0
    halt_resets: int = 0
    # Kalıcı durdurma: yalnızca insan onayıyla kalkar (scripts/resume_halt.py).
    stopped: bool = False
    stop_reason: Optional[str] = None

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
        # Halt alanları sonradan eklendi: eski state dosyalarında yoklar,
        # varsayılanları "hiç halt olmamış" anlamına gelir.
        halted=raw.get("halted", False),
        halted_since=raw.get("halted_since"),
        halted_marks=raw.get("halted_marks", 0),
        halt_resets=raw.get("halt_resets", 0),
        stopped=raw.get("stopped", False),
        stop_reason=raw.get("stop_reason"),
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
        "halted": state.halted,
        "halted_since": state.halted_since,
        "halted_marks": state.halted_marks,
        "halt_resets": state.halt_resets,
        "stopped": state.stopped,
        "stop_reason": state.stop_reason,
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def update_peak_equity(state: PortfolioState, current_prices: dict[str, float]) -> float:
    """Update and return `state.peak_equity` given the latest equity mark."""
    equity = state.equity(current_prices)
    state.peak_equity = max(state.peak_equity, equity)
    return equity


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
