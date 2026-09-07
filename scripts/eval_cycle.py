#!/usr/bin/env python3
"""Run one evaluation-loop pass: log signals + drive the paper portfolio.

For each symbol in `alsatbotu.config.WATCHLIST`:
  1. Fetch price history and evaluate the *active* strategy version
     (evaluation.strategy.evaluate_versioned -- same rules as
     alsatbotu.signal.evaluate, but with tunable thresholds).
  2. Log the signal (evaluation/logger.py -> `signals` table).
  3. Check the symbol's open paper trade (if any) against its ATR
     stop-loss / take-profit.
  4. On BUY: open a new paper trade if none is open and the daily cap
     allows it.
  5. On SELL: close the open paper trade for that symbol, if any.

This is independent of `scripts/run_portfolio.py` (the JSON-based live
portfolio) -- it only writes to the SQLite evaluation database. Meant to
run on the same cadence as the live portfolio (see
.github/workflows/eval-cycle.yml).

Usage:
    python scripts/eval_cycle.py [days]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import WATCHLIST, asset_type_for
from alsatbotu.data import get_price_history
from alsatbotu.indicators import add_indicators
from evaluation.db import connect
from evaluation.logger import log_signal
from evaluation.paper_engine import check_exits, close_trade, get_open_trade, open_trade
from evaluation.strategy import evaluate_versioned, get_active_params
from alsatbotu.signal import Signal


def run(days: int = 60) -> None:
    conn = connect()
    params = get_active_params(conn)
    current_prices: dict[str, float] = {}

    for entry in WATCHLIST:
        symbol = entry["symbol"]
        source = entry.get("source", "coingecko")
        asset_type = asset_type_for(source)

        try:
            rows = get_price_history(symbol, source=source, days=days)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the run
            print(f"{symbol}: failed to fetch price history ({exc})")
            continue
        if len(rows) < 2:
            print(f"{symbol}: not enough candles to evaluate ({len(rows)})")
            continue

        decision = evaluate_versioned(rows, params)
        latest = add_indicators(rows)[-1]
        price = latest["close"]
        current_prices[symbol] = price

        signal_id = log_signal(conn, symbol, asset_type, price, latest, decision, params)

        exit_reason = check_exits(conn, symbol, price)
        if exit_reason:
            print(f"{symbol}: paper trade closed ({exit_reason}) @ {price:.4f}")

        if decision.signal == Signal.BUY:
            result = open_trade(
                conn, signal_id, symbol, price, latest.get("atr"), current_prices, params.version
            )
            print(f"{symbol}: BUY -> {'opened' if result.opened else result.reason}")
        elif decision.signal == Signal.SELL:
            trade = get_open_trade(conn, symbol)
            if trade is not None:
                pnl = close_trade(conn, trade["id"], price, "signal")
                print(f"{symbol}: SELL -> closed, pnl {pnl:+.2f}")
            else:
                print(f"{symbol}: SELL -> no open paper trade")
        else:
            print(f"{symbol}: HOLD @ {price:.4f}")

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
