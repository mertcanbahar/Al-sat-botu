"""Evaluation & self-improvement loop for the rule engine.

Everything here is additive: it reads the same price data, indicators, and
rule engine (`alsatbotu.rules`) the live JSON-based portfolio
(`portfolio/`, `engine/risk.py`, `scripts/run_portfolio.py`) already uses,
and logs to its own SQLite database (`alsatbotu.config.EVAL_DB_PATH`)
rather than touching `data/portfolio.json` or `data/signals.jsonl`.

Modules:
  db.py         -- SQLite connection + schema (signals, outcomes,
                   paper_trades, strategy_versions).
  strategy.py   -- versioned, tunable strategy parameters and a
                   parameterized re-implementation of the BUY/SELL rules.
  logger.py     -- writes one `signals` row per evaluated symbol.
  outcomes.py   -- hourly job: fills price_1h/24h/7d for signals old enough
                   to have them, and derives hit/pnl_pct_24h.
  paper_engine.py -- the paper portfolio described in the task: 10,000
                   starting capital, 1% of equity per trade, 0.15%
                   commission + 0.05% slippage per side, 1.5*ATR stop /
                   2.5*ATR target, capped at 100 new trades/day.
  report.py     -- builds the daily Telegram report (trade count, hit
                   rate, avg win/loss, PnL gross/net, worst 3 trades,
                   buy-and-hold comparison).
  improve.py    -- weekly loop: mines last week's losing paper trades for
                   one common pattern, proposes exactly one parameter
                   change, backtests old vs. new version side by side, and
                   keeps only the version that wins.
"""
