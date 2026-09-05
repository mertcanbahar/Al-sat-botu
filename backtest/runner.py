#!/usr/bin/env python3
"""Backtest runner: replays alsatbotu.rules.evaluate() over historical candles.

This does not change the rule engine in any way -- it calls the exact same
`rules.evaluate()` used live, one bar at a time on an expanding window (no
lookahead: bar i only ever sees rows[0:i+1]), and simulates a simple
long-only strategy on top of its BUY/SELL/HOLD output: enter on BUY when
flat, exit on SELL when in a position, do nothing on HOLD.

Reports: total return, win rate, max drawdown, trade count, and average
holding period.

Usage:
    python backtest/runner.py [symbol] [days] [source]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.data import get_price_history
from alsatbotu.rules import Signal, evaluate


@dataclass
class Trade:
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    return_pct: float
    holding_period: timedelta


@dataclass
class OpenPosition:
    entry_time: datetime
    entry_price: float
    unrealized_return_pct: float


@dataclass
class BacktestResult:
    trades: list[Trade]
    total_return_pct: float
    win_rate: Optional[float]
    max_drawdown_pct: float
    trade_count: int
    avg_holding_period: Optional[timedelta]
    open_position: Optional[OpenPosition]


def run_backtest(rows: Sequence[dict]) -> BacktestResult:
    """Simulate a long-only BUY/SELL/HOLD strategy over `rows` using rules.evaluate().

    Total return and max drawdown are computed on a bar-by-bar mark-to-market
    equity curve (an open position at the end still counts toward both), so
    they reflect the full path, not just realized trade P&L. Win rate,
    trade count, and average holding period only consider *closed* trades.
    """
    if len(rows) < 2:
        raise ValueError("Need at least 2 rows to backtest (rules.evaluate() requires 2).")

    trades: list[Trade] = []
    position: Optional[dict] = None
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    current_equity = equity

    for i in range(1, len(rows)):
        window = rows[: i + 1]
        decision = evaluate(window)
        price = rows[i]["close"]
        timestamp = rows[i]["timestamp"]

        if position is not None:
            current_equity = position["equity_at_entry"] * (price / position["entry_price"])
        else:
            current_equity = equity

        peak = max(peak, current_equity)
        if peak:
            max_drawdown = min(max_drawdown, (current_equity - peak) / peak)

        if position is None and decision.signal == Signal.BUY:
            position = {
                "entry_time": timestamp,
                "entry_price": price,
                "equity_at_entry": equity,
            }
        elif position is not None and decision.signal == Signal.SELL:
            equity = position["equity_at_entry"] * (price / position["entry_price"])
            trades.append(
                Trade(
                    entry_time=position["entry_time"],
                    exit_time=timestamp,
                    entry_price=position["entry_price"],
                    exit_price=price,
                    return_pct=price / position["entry_price"] - 1.0,
                    holding_period=timestamp - position["entry_time"],
                )
            )
            position = None

    open_position = None
    if position is not None:
        last_price = rows[-1]["close"]
        open_position = OpenPosition(
            entry_time=position["entry_time"],
            entry_price=position["entry_price"],
            unrealized_return_pct=last_price / position["entry_price"] - 1.0,
        )

    win_rate = (sum(1 for t in trades if t.return_pct > 0) / len(trades)) if trades else None
    avg_holding_period = (
        sum((t.holding_period for t in trades), timedelta()) / len(trades) if trades else None
    )

    return BacktestResult(
        trades=trades,
        total_return_pct=current_equity - 1.0,
        win_rate=win_rate,
        max_drawdown_pct=max_drawdown,
        trade_count=len(trades),
        avg_holding_period=avg_holding_period,
        open_position=open_position,
    )


def _format_pct(value: Optional[float]) -> str:
    return f"{value * 100:.2f}%" if value is not None else "N/A"


def print_report(symbol: str, rows: Sequence[dict], result: BacktestResult) -> None:
    print(f"Symbol: {symbol}")
    print(f"Candles: {len(rows)} ({rows[0]['timestamp']} -> {rows[-1]['timestamp']})")
    print(f"Total return: {_format_pct(result.total_return_pct)}")
    print(f"Win rate: {_format_pct(result.win_rate)}")
    print(f"Max drawdown: {_format_pct(result.max_drawdown_pct)}")
    print(f"Trade count: {result.trade_count}")
    avg_hold = result.avg_holding_period
    print(f"Avg holding period: {avg_hold if avg_hold is not None else 'N/A'}")
    if result.open_position is not None:
        op = result.open_position
        print(
            f"Open position at end: entered {op.entry_time} at {op.entry_price:.4f}, "
            f"unrealized return {_format_pct(op.unrealized_return_pct)}"
        )

    if result.trades:
        print()
        print("Trades:")
        for i, trade in enumerate(result.trades, start=1):
            print(
                f"  {i}. {trade.entry_time} @ {trade.entry_price:.4f} -> "
                f"{trade.exit_time} @ {trade.exit_price:.4f} "
                f"({_format_pct(trade.return_pct)}, held {trade.holding_period})"
            )


def main(symbol: str = "bitcoin", days: int = 180, source: str = "coingecko") -> None:
    rows = get_price_history(symbol, source=source, days=days)
    result = run_backtest(rows)
    print_report(symbol, rows, result)


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "bitcoin"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    source = sys.argv[3] if len(sys.argv) > 3 else "coingecko"
    main(symbol, days, source)
