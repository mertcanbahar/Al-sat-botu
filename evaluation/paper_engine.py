"""Paper portfolio (task part B): 10,000 virtual TL, long-only.

Rules (see `alsatbotu.config`):
  - 1% of current equity notional per trade (`PAPER_RISK_PER_TRADE_PCT`).
  - 0.15% commission + 0.05% slippage, charged on both entry and exit.
  - Stop-loss at entry - 1.5*ATR, take-profit at entry + 2.5*ATR.
  - At most 100 new trades opened per calendar day (UTC).

This is a separate ledger from `portfolio/state.py` (the JSON-based live
paper portfolio with 2%-risk ATR-stop sizing) -- it exists purely to feed
the evaluation loop's daily report and weekly improvement loop, and lives
entirely in `paper_trades` (evaluation/db.py). Long-only, one open trade
per symbol at a time, matching the rule engine's own BUY/SELL/HOLD shape.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from alsatbotu.config import (
    PAPER_ATR_STOP_MULTIPLIER,
    PAPER_ATR_TARGET_MULTIPLIER,
    PAPER_COMMISSION_PCT,
    PAPER_MAX_TRADES_PER_DAY,
    PAPER_RISK_PER_TRADE_PCT,
    PAPER_SLIPPAGE_PCT,
    PAPER_STARTING_CAPITAL,
)


def buy_fill_price(raw_price: float) -> float:
    return raw_price * (1 + PAPER_SLIPPAGE_PCT)


def sell_fill_price(raw_price: float) -> float:
    return raw_price * (1 - PAPER_SLIPPAGE_PCT)


def commission_for(notional: float) -> float:
    return abs(notional) * PAPER_COMMISSION_PCT


def compute_cash(conn: sqlite3.Connection) -> float:
    cash = PAPER_STARTING_CAPITAL
    for row in conn.execute("SELECT entry_price, size, exit_price, fee FROM paper_trades"):
        cash -= row["entry_price"] * row["size"]
        cash -= row["fee"]
        if row["exit_price"] is not None:
            cash += row["exit_price"] * row["size"]
    return cash


def open_positions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pt.*, s.symbol
        FROM paper_trades pt
        JOIN signals s ON s.id = pt.signal_id
        WHERE pt.exit_ts IS NULL
        """
    ).fetchall()


def get_open_trade(conn: sqlite3.Connection, symbol: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pt.* FROM paper_trades pt
        JOIN signals s ON s.id = pt.signal_id
        WHERE s.symbol = ? AND pt.exit_ts IS NULL
        """,
        (symbol,),
    ).fetchone()


def equity(conn: sqlite3.Connection, current_prices: dict[str, float]) -> float:
    cash = compute_cash(conn)
    position_value = sum(
        pos["size"] * current_prices.get(pos["symbol"], pos["entry_price"])
        for pos in open_positions(conn)
    )
    return cash + position_value


def trades_opened_on(conn: sqlite3.Connection, day: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM paper_trades WHERE substr(entry_ts, 1, 10) = ?", (day,)
    ).fetchone()
    return row["n"]


@dataclass
class OpenResult:
    opened: bool
    reason: str
    trade_id: Optional[int] = None


def open_trade(
    conn: sqlite3.Connection,
    signal_id: int,
    symbol: str,
    raw_price: float,
    atr: Optional[float],
    current_prices: dict[str, float],
    strategy_version: str,
    now: Optional[datetime] = None,
) -> OpenResult:
    """Open a long paper position sized to 1% of equity, if room allows."""
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()

    if get_open_trade(conn, symbol) is not None:
        return OpenResult(False, f"Position already open for {symbol}")
    if trades_opened_on(conn, day) >= PAPER_MAX_TRADES_PER_DAY:
        return OpenResult(False, f"Daily trade cap reached ({PAPER_MAX_TRADES_PER_DAY})")
    if atr is None or atr <= 0:
        return OpenResult(False, "No valid ATR available to size stop/target")

    eq = equity(conn, current_prices)
    notional = eq * PAPER_RISK_PER_TRADE_PCT
    fill_price = buy_fill_price(raw_price)
    size = notional / fill_price
    if size <= 0:
        return OpenResult(False, "Computed position size is zero")

    fee = commission_for(size * fill_price)
    slippage_cost = (fill_price - raw_price) * size

    cur = conn.execute(
        """
        INSERT INTO paper_trades
            (signal_id, side, entry_price, size, fee, slippage, entry_ts, strategy_version)
        VALUES (?, 'long', ?, ?, ?, ?, ?, ?)
        """,
        (signal_id, fill_price, size, fee, slippage_cost, now.isoformat(), strategy_version),
    )
    conn.commit()
    return OpenResult(True, "opened", cur.lastrowid)


def close_trade(
    conn: sqlite3.Connection,
    trade_id: int,
    raw_price: float,
    reason: str,
    now: Optional[datetime] = None,
) -> float:
    """Close an open trade at `raw_price` (slippage/commission applied on exit). Returns net pnl."""
    now = now or datetime.now(timezone.utc)
    trade = conn.execute("SELECT * FROM paper_trades WHERE id = ?", (trade_id,)).fetchone()

    fill_price = sell_fill_price(raw_price)
    exit_fee = commission_for(trade["size"] * fill_price)
    exit_slippage_cost = (raw_price - fill_price) * trade["size"]

    total_fee = trade["fee"] + exit_fee
    total_slippage = trade["slippage"] + exit_slippage_cost
    pnl = (fill_price - trade["entry_price"]) * trade["size"] - total_fee

    conn.execute(
        """
        UPDATE paper_trades
        SET exit_price = ?, exit_reason = ?, fee = ?, slippage = ?, pnl = ?, exit_ts = ?
        WHERE id = ?
        """,
        (fill_price, reason, total_fee, total_slippage, pnl, now.isoformat(), trade_id),
    )
    conn.commit()
    return pnl


def check_exits(
    conn: sqlite3.Connection,
    symbol: str,
    raw_price: float,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Close the open trade for `symbol` if `raw_price` has crossed its stop or target.

    ATR-derived stop/target are computed from the ATR recorded on the
    signal that opened the trade (looked up via signals.indicators_json),
    so they stay fixed for the life of the trade rather than trailing.
    Returns the exit reason if closed, else None.
    """
    trade = get_open_trade(conn, symbol)
    if trade is None:
        return None

    signal = conn.execute(
        "SELECT indicators_json FROM signals WHERE id = ?", (trade["signal_id"],)
    ).fetchone()
    atr = json.loads(signal["indicators_json"]).get("atr") if signal else None
    if atr is None or atr <= 0:
        return None

    entry_price = trade["entry_price"]
    stop_price = entry_price - PAPER_ATR_STOP_MULTIPLIER * atr
    target_price = entry_price + PAPER_ATR_TARGET_MULTIPLIER * atr

    if raw_price <= stop_price:
        close_trade(conn, trade["id"], raw_price, "stop_loss", now)
        return "stop_loss"
    if raw_price >= target_price:
        close_trade(conn, trade["id"], raw_price, "take_profit", now)
        return "take_profit"
    return None
