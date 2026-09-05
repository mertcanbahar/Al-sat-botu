#!/usr/bin/env python3
"""Run one paper-trading pass over the watchlist and update the portfolio.

For each symbol in `alsatbotu.config.WATCHLIST`:
  1. Fetch price history and evaluate the rule engine (alsatbotu.rules).
  2. Append the signal to the ledger (portfolio/ledger.py), regardless of
     whether it results in a trade.
  3. On BUY: ask the risk engine (engine/risk.py) whether to open a
     position and at what size; open it if approved.
  4. On SELL: close the open position for that symbol, if any.

Portfolio state (data/portfolio.json) is saved once at the end. This
script does not touch Telegram, the AI layer, or cron -- it is meant to be
run manually (see .github/workflows/manual-portfolio.yml) or from a
scheduler that already exists elsewhere.

Usage:
    python scripts/run_portfolio.py [days]
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import WATCHLIST
from alsatbotu.data import get_price_history
from alsatbotu.indicators import add_indicators
from alsatbotu.rules import Signal, evaluate
from engine.risk import evaluate_buy
from portfolio.ledger import log_signal
from portfolio.state import close_position, load_state, open_position, save_state, update_peak_equity


def run(days: int = 60) -> None:
    state = load_state()
    current_prices: dict[str, float] = {}
    latest_by_symbol: dict[str, dict] = {}

    for entry in WATCHLIST:
        symbol = entry["symbol"]
        category = entry["category"]
        source = entry.get("source", "coingecko")

        try:
            rows = get_price_history(symbol, source=source, days=days)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the run
            print(f"{symbol}: failed to fetch price history ({exc})")
            continue

        if len(rows) < 2:
            print(f"{symbol}: not enough candles to evaluate ({len(rows)})")
            continue

        decision = evaluate(rows)
        latest = add_indicators(rows)[-1]
        price = latest["close"]
        current_prices[symbol] = price
        latest_by_symbol[symbol] = latest

        log_signal(symbol, decision, price, latest)

        if decision.signal == Signal.BUY:
            risk_decision = evaluate_buy(
                state, symbol, category, price, latest["atr"], current_prices
            )
            if risk_decision.approved:
                open_position(
                    state,
                    symbol=symbol,
                    category=category,
                    quantity=risk_decision.quantity,
                    entry_price=price,
                    entry_date=latest["timestamp"].isoformat(),
                    stop_price=risk_decision.stop_price,
                )
                print(f"{symbol}: BUY {risk_decision.quantity:.6f} @ {price:.4f}")
            else:
                print(f"{symbol}: BUY signal rejected by risk engine: {'; '.join(risk_decision.reasons)}")
        elif decision.signal == Signal.SELL:
            trade = close_position(
                state,
                symbol=symbol,
                exit_price=price,
                exit_date=latest["timestamp"].isoformat(),
                reason="; ".join(decision.reasons) or "SELL signal",
            )
            if trade is not None:
                print(f"{symbol}: SELL {trade.quantity:.6f} @ {price:.4f} (pnl {trade.pnl_pct * 100:.2f}%)")
        else:
            print(f"{symbol}: HOLD @ {price:.4f}")

    equity = update_peak_equity(state, current_prices)
    save_state(state)

    print()
    print(f"Cash: {state.cash:.2f}")
    print(f"Equity: {equity:.2f} (peak {state.peak_equity:.2f})")
    print(f"Open positions: {len(state.open_positions)}")
    for symbol, position in state.open_positions.items():
        print(
            f"  {symbol}: {position.quantity:.6f} @ {position.entry_price:.4f} "
            f"(stop {position.stop_price:.4f}, category {position.category})"
        )
    print(f"Closed trades: {len(state.closed_trades)}")


def _parse_days(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return int(argv[0]) if argv else 60


if __name__ == "__main__":
    run(_parse_days())
