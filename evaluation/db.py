"""SQLite schema and connection helper for the evaluation loop.

Five tables:
  signals           -- one row per symbol per evaluation cycle (A).
  outcomes          -- forward-looking price marks for each signal (A).
  paper_trades      -- the 10k-TL paper portfolio's fills (B).
  strategy_versions -- the parameter-version registry the weekly
                        improvement loop (D) reads and writes. A new
                        version is written with status='candidate' and
                        active=0 -- only a human approving it via Telegram
                        (see evaluation/strategy.py:activate_version and
                        scripts/process_telegram_approvals.py) flips it to
                        status='active'/active=1. Nothing in this codebase
                        activates a version on its own.
  telegram_offset   -- single-row cursor into Telegram's getUpdates, so
                        the approval-polling job never reprocesses a
                        button press it already handled.

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
    backtest_json TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    telegram_chat_id TEXT,
    telegram_message_id INTEGER,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS telegram_offset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_update_id INTEGER NOT NULL DEFAULT 0
);
"""

# Columns added after the initial release, for databases created before
# this migration existed. ALTER TABLE ADD COLUMN is idempotent-guarded by
# catching sqlite3's "duplicate column" error rather than checking
# PRAGMA table_info first, since that's what every existing evaluation.db
# in git history needs applied exactly once.
_MIGRATIONS = [
    "ALTER TABLE strategy_versions ADD COLUMN status TEXT NOT NULL DEFAULT 'candidate'",
    "ALTER TABLE strategy_versions ADD COLUMN telegram_chat_id TEXT",
    "ALTER TABLE strategy_versions ADD COLUMN telegram_message_id INTEGER",
    "ALTER TABLE strategy_versions ADD COLUMN decided_at TEXT",
]


def _migrate(conn: sqlite3.Connection) -> None:
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
    # A version created before `status` existed was, by definition, the
    # one already live -- backfill it to 'active' rather than leaving it
    # at the new default of 'candidate'.
    conn.execute("UPDATE strategy_versions SET status = 'active' WHERE active = 1")
    conn.commit()


def connect(path: Path = EVAL_DB_PATH) -> sqlite3.Connection:
    """Open the evaluation database, creating the schema if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn
