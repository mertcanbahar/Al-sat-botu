#!/usr/bin/env python3
"""Run one paper-trading pass over the watchlist and update the portfolio.

For each symbol in `alsatbotu.config.WATCHLIST`:
  1. Fetch price history and evaluate the rule engine (alsatbotu.rules).
  2. Append the signal to the ledger (portfolio/ledger.py), regardless of
     whether it results in a trade.
  3. On BUY: ask the risk engine (engine/risk.py) whether to open a
     position and at what size; open it if approved.
  4. On SELL: close the open position for that symbol, if any.
  5. Send a Telegram message for BUY/SELL signals that are *new* -- i.e.
     the symbol's previously recorded decision was something else. HOLD is
     never notified, and a decision that simply persists across runs is
     not re-sent.

Portfolio state (data/portfolio.json) is saved once at the end. This
script does not touch Telegram, the AI layer, or cron -- it is meant to be
run manually (see .github/workflows/manual-portfolio.yml) or from a
scheduler that already exists elsewhere.

Usage:
    python scripts/run_portfolio.py [days]
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import WATCHLIST
from alsatbotu.data import get_price_history
from alsatbotu.indicators import add_indicators
from alsatbotu.rules import Decision, Signal, evaluate
from engine.risk import evaluate_buy
from notify.telegram import send_message
from portfolio.ledger import last_decisions, log_signal
from portfolio.state import close_position, load_state, open_position, save_state, update_peak_equity

SIGNAL_LABELS = {Signal.BUY: "🟢 AL", Signal.SELL: "🔴 SAT"}


def _notify_signal(symbol: str, decision: Decision, price: float, action: str) -> None:
    lines = [
        f"{SIGNAL_LABELS[decision.signal]} sinyali — {symbol}",
        f"Fiyat: {price:.4f}",
    ]
    if decision.reasons:
        lines.append("Tetikleyen kural:")
        lines.extend(f"  • {reason}" for reason in decision.reasons)
    lines.append(f"İşlem: {action}")
    send_message("\n".join(lines))


def run(days: int = 60) -> None:
    state = load_state()
    # Read before any new signal is appended, so it reflects the previous run.
    previous_decisions = last_decisions()
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
        is_new_signal = previous_decisions.get(symbol) != decision.signal.value

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
                action = (
                    f"{risk_decision.quantity:.6f} adet alındı "
                    f"(stop {risk_decision.stop_price:.4f})"
                )
                if risk_decision.capped_by:
                    action += f" — boyut sınırlandı: {risk_decision.capped_by}"
                print(f"{symbol}: BUY {risk_decision.quantity:.6f} @ {price:.4f}")
            else:
                action = f"risk motoru reddetti — {'; '.join(risk_decision.reasons)}"
                print(f"{symbol}: BUY signal rejected by risk engine: {'; '.join(risk_decision.reasons)}")
            if is_new_signal:
                _notify_signal(symbol, decision, price, action)
        elif decision.signal == Signal.SELL:
            trade = close_position(
                state,
                symbol=symbol,
                exit_price=price,
                exit_date=latest["timestamp"].isoformat(),
                reason="; ".join(decision.reasons) or "SELL signal",
            )
            if trade is not None:
                action = (
                    f"{trade.quantity:.6f} adet satıldı, "
                    f"P&L {trade.pnl:+.2f} ({trade.pnl_pct * 100:+.2f}%)"
                )
                print(f"{symbol}: SELL {trade.quantity:.6f} @ {price:.4f} (pnl {trade.pnl_pct * 100:.2f}%)")
            else:
                action = "açık pozisyon yok, işlem yapılmadı"
                print(f"{symbol}: SELL signal, no open position")
            if is_new_signal:
                _notify_signal(symbol, decision, price, action)
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(_parse_days())
