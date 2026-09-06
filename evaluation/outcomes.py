"""Hourly job: fills price_1h/24h/7d for signals old enough to have them.

For every signal missing a given horizon's price whose age has reached
that horizon, fetch the current price for its symbol and record it. Once
`price_24h` is filled, `pnl_pct_24h` and `hit` are derived: `hit` is True
when the 24h move agrees with the signal's direction (price rose after a
BUY, or fell after a SELL); HOLD signals have no direction to score, so
their `hit` stays NULL.

Idempotent and safe to run every hour via cron: a horizon already filled
is never re-fetched, and a signal not yet old enough is simply skipped
until a later run.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from alsatbotu.config import OUTCOME_HORIZONS_HOURS
from alsatbotu.data import get_price_history
from evaluation.db import connect

logger = logging.getLogger(__name__)


def _current_price(symbol: str, asset_type: str) -> float | None:
    source = "coingecko" if asset_type == "crypto" else "twelvedata"
    try:
        rows = get_price_history(symbol, source=source, days=7)
    except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the job
        logger.warning("outcomes: failed to fetch %s (%s)", symbol, exc)
        return None
    return rows[-1]["close"] if rows else None


def _ensure_outcome_row(conn: sqlite3.Connection, signal_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO outcomes (signal_id) VALUES (?)", (signal_id,))


def _due_signals(conn: sqlite3.Connection, column: str, hours: int, now: datetime) -> list[sqlite3.Row]:
    cutoff = (now - timedelta(hours=hours)).isoformat()
    return conn.execute(
        f"""
        SELECT s.id, s.symbol, s.asset_type, s.price, s.decision
        FROM signals s
        LEFT JOIN outcomes o ON o.signal_id = s.id
        WHERE s.ts <= ? AND (o.signal_id IS NULL OR o.{column} IS NULL)
        """,
        (cutoff,),
    ).fetchall()


def fill_due_outcomes(conn: sqlite3.Connection | None = None, now: datetime | None = None) -> int:
    """Fill every outcome horizon that is now due. Returns the number of prices filled."""
    owns_conn = conn is None
    conn = conn or connect()
    now = now or datetime.now(timezone.utc)
    filled = 0
    try:
        for column, hours in OUTCOME_HORIZONS_HOURS.items():
            for row in _due_signals(conn, column, hours, now):
                price = _current_price(row["symbol"], row["asset_type"])
                if price is None:
                    continue
                _ensure_outcome_row(conn, row["id"])
                conn.execute(
                    f"UPDATE outcomes SET {column} = ? WHERE signal_id = ?",
                    (price, row["id"]),
                )
                filled += 1
                if column == "price_24h":
                    pnl_pct = price / row["price"] - 1.0 if row["price"] else None
                    hit = None
                    if pnl_pct is not None and row["decision"] in ("BUY", "SELL"):
                        moved_up = pnl_pct > 0
                        hit = int(moved_up if row["decision"] == "BUY" else not moved_up)
                    conn.execute(
                        "UPDATE outcomes SET pnl_pct_24h = ?, hit = ? WHERE signal_id = ?",
                        (pnl_pct, hit, row["id"]),
                    )
                conn.commit()
    finally:
        if owns_conn:
            conn.close()
    return filled


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    count = fill_due_outcomes()
    print(f"Filled {count} outcome price(s).")
