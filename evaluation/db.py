"""SQLite schema and connection helper for the evaluation loop.

Four tables:
  signals           -- one row per symbol per evaluation cycle (A).
  outcomes          -- forward-looking price marks for each signal (A).
  paper_trades      -- the 10k-TL paper portfolio's fills (B).
  strategy_versions -- the parameter-version registry the weekly
                        improvement loop (D) reads and writes.

`connect()` opens (creating if needed) `alsatbotu.config.EVAL_DB_PATH` with
the schema applied; every script in this package calls it rather than
managing its own sqlite3.Connection.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alsatbotu.config import EVAL_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    price REAL NOT NULL,
    indicators_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL,
    reasoning TEXT,
    prompt_version TEXT NOT NULL,
    strategy_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);

CREATE TABLE IF NOT EXISTS outcomes (
    signal_id INTEGER PRIMARY KEY REFERENCES signals(id),
    price_1h REAL,
    price_24h REAL,
    price_7d REAL,
    pnl_pct_24h REAL,
    hit INTEGER
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    exit_price REAL,
    exit_reason TEXT,
    fee REAL NOT NULL,
    slippage REAL NOT NULL,
    pnl REAL,
    entry_ts TEXT NOT NULL,
    exit_ts TEXT,
    strategy_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_entry_ts ON paper_trades(entry_ts);
CREATE INDEX IF NOT EXISTS idx_paper_trades_open ON paper_trades(exit_ts);

CREATE TABLE IF NOT EXISTS strategy_versions (
    version TEXT PRIMARY KEY,
    parent_version TEXT,
    params_json TEXT NOT NULL,
    hypothesis TEXT,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    backtest_json TEXT
);
"""


def connect(path: Path = EVAL_DB_PATH) -> sqlite3.Connection:
    """Open the evaluation database, creating the schema if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
