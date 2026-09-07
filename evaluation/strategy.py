"""Versioned, tunable strategy parameters.

`alsatbotu/rules.py` stays untouched -- it's the live rule engine and this
project's other tooling (portfolio, backtest) depends on its exact,
fixed thresholds. This module is a parallel, parameterized
re-implementation of the *same* three-condition BUY / three-reason SELL
logic, used only by the evaluation loop (signal logging, the paper
portfolio, and the weekly improvement loop), so that loop can vary one
threshold at a time without editing source and redeploying.

`strategy_versions` (see db.py) is the durable registry: each row is one
named version's parameter set, its lifecycle `status`
('candidate' / 'active' / 'rejected'), and whether it's the live one.
Exactly one version is ever `active` at a time; `get_active_params()` is
what everything else in this package should call. A version only reaches
`status='active'` through `activate_version()`, which nothing in this
codebase calls automatically -- see `evaluation/improve.py` and
`scripts/process_telegram_approvals.py` for the human-approval flow that
does.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Optional, Sequence

from alsatbotu.indicators import add_indicators
from alsatbotu.signal import Decision, Signal
from evaluation.db import connect

BASELINE_VERSION = "v1"


@dataclass(frozen=True)
class StrategyParams:
    version: str
    rsi_buy_min: float = 40.0
    rsi_buy_max: float = 65.0
    rsi_sell_max: float = 75.0
    atr_stop_multiplier: float = 2.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(version: str, blob: str) -> "StrategyParams":
        data = json.loads(blob)
        data["version"] = version
        return StrategyParams(**data)


BASELINE_PARAMS = StrategyParams(version=BASELINE_VERSION)


def evaluate_versioned(rows: Sequence[dict], params: StrategyParams) -> Decision:
    """Same shape as `alsatbotu.signal.evaluate`, but reads thresholds from `params`."""
    if len(rows) < 2:
        raise ValueError("Need at least 2 rows of data to evaluate rules.")

    enriched = add_indicators(rows)
    prev, last = enriched[-2], enriched[-1]

    ema_20 = last["ema_20"]
    ema_50 = last["ema_50"]
    rsi_value = last["rsi"]
    close = last["close"]
    volume = last.get("volume")
    volume_avg = last["volume_sma_20"]

    sell_reasons: list[str] = []
    if prev["close"] is not None and prev["atr"] is not None:
        stop_level = prev["close"] - params.atr_stop_multiplier * prev["atr"]
        if close < stop_level:
            sell_reasons.append(f"Price {close:.4f} below ATR stop level {stop_level:.4f}")

    if ema_20 is not None and ema_50 is not None and ema_20 < ema_50:
        sell_reasons.append(f"EMA20 {ema_20:.4f} < EMA50 {ema_50:.4f}")

    if rsi_value is not None and rsi_value > params.rsi_sell_max:
        sell_reasons.append(f"RSI {rsi_value:.1f} > {params.rsi_sell_max}")

    if sell_reasons:
        return Decision(signal=Signal.SELL, reasons=sell_reasons)

    trend_ok = ema_20 is not None and ema_50 is not None and ema_20 > ema_50
    rsi_ok = rsi_value is not None and params.rsi_buy_min <= rsi_value <= params.rsi_buy_max
    volume_ok = volume is not None and volume_avg is not None and volume > volume_avg

    if trend_ok and rsi_ok and volume_ok:
        return Decision(
            signal=Signal.BUY,
            reasons=[
                f"EMA20 {ema_20:.4f} > EMA50 {ema_50:.4f}",
                f"RSI {rsi_value:.1f} in [{params.rsi_buy_min}, {params.rsi_buy_max}]",
                f"Volume {volume:.4f} > 20-period average {volume_avg:.4f}",
            ],
        )

    return Decision(signal=Signal.HOLD)


def confidence_for(decision: Decision, indicators: dict, params: StrategyParams) -> float:
    """Heuristic 0..1 confidence, until a scored/LLM decision layer replaces the rule engine.

    HOLD is a non-decision (0.5, "no opinion"). For BUY/SELL, each of the
    up-to-three triggering conditions counts equally toward confidence, so
    a BUY on all three confirming conditions (the only way BUY fires) is
    always 1.0, while a SELL on one weak reason (e.g. only RSI > threshold)
    scores lower than a SELL on all three.
    """
    if decision.signal == Signal.HOLD:
        return 0.5
    total_possible = 3
    return min(1.0, len(decision.reasons) / total_possible)


def _row(conn, version: str):
    return conn.execute(
        "SELECT * FROM strategy_versions WHERE version = ?", (version,)
    ).fetchone()


def save_version(
    params: StrategyParams,
    parent_version: Optional[str] = None,
    hypothesis: Optional[str] = None,
    status: str = "candidate",
    backtest: Optional[dict] = None,
    conn=None,
) -> None:
    """Insert (or update) a strategy version row.

    `status="active"` is only ever passed for the baseline version
    (`get_active_params` seeding an empty database) or by the migration
    backfill in `evaluation/db.py`. Every version the weekly improvement
    loop proposes is saved with `status="candidate"` and `active=0` --
    activation is a separate, explicit step (`activate_version`) that only
    `scripts/process_telegram_approvals.py` calls, after a human approves
    it. Nothing here activates a version on backtest results alone.
    """
    owns_conn = conn is None
    conn = conn or connect()
    try:
        active = status == "active"
        conn.execute(
            """
            INSERT INTO strategy_versions
                (version, parent_version, params_json, hypothesis, created_at,
                 active, backtest_json, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(version) DO UPDATE SET
                active = excluded.active,
                backtest_json = excluded.backtest_json,
                status = excluded.status
            """,
            (
                params.version,
                parent_version,
                params.to_json(),
                hypothesis,
                datetime.now(timezone.utc).isoformat(),
                int(active),
                json.dumps(backtest) if backtest is not None else None,
                status,
            ),
        )
        if active:
            conn.execute(
                "UPDATE strategy_versions SET active = 0 WHERE version != ?", (params.version,)
            )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def record_telegram_message(version: str, chat_id, message_id: int, conn=None) -> None:
    """Remember which Telegram message carries a candidate's approval buttons."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "UPDATE strategy_versions SET telegram_chat_id = ?, telegram_message_id = ? WHERE version = ?",
            (str(chat_id), message_id, version),
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_version(version: str, conn=None) -> Optional[sqlite3.Row]:
    owns_conn = conn is None
    conn = conn or connect()
    try:
        return conn.execute(
            "SELECT * FROM strategy_versions WHERE version = ?", (version,)
        ).fetchone()
    finally:
        if owns_conn:
            conn.close()


def pending_candidates(conn=None) -> list[sqlite3.Row]:
    owns_conn = conn is None
    conn = conn or connect()
    try:
        return conn.execute(
            "SELECT * FROM strategy_versions WHERE status = 'candidate' ORDER BY created_at"
        ).fetchall()
    finally:
        if owns_conn:
            conn.close()


def activate_version(version: str, conn=None) -> None:
    """Human-approval path: make `version` the live one. Never called automatically."""
    owns_conn = conn is None
    conn = conn or connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE strategy_versions SET active = 0")
        conn.execute(
            "UPDATE strategy_versions SET active = 1, status = 'active', decided_at = ? WHERE version = ?",
            (now, version),
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def reject_version(version: str, conn=None) -> None:
    """Human-rejection path (or a no-response candidate left as-is forever): mark it rejected.

    Never touches `active` -- whatever version was live stays live.
    """
    owns_conn = conn is None
    conn = conn or connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE strategy_versions SET status = 'rejected', decided_at = ? WHERE version = ?",
            (now, version),
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_active_params(conn=None) -> StrategyParams:
    owns_conn = conn is None
    conn = conn or connect()
    try:
        row = conn.execute(
            "SELECT version, params_json FROM strategy_versions WHERE active = 1"
        ).fetchone()
        if row is None:
            save_version(BASELINE_PARAMS, status="active", conn=conn)
            return BASELINE_PARAMS
        return StrategyParams.from_json(row["version"], row["params_json"])
    finally:
        if owns_conn:
            conn.close()


def next_version_id(conn) -> str:
    rows = conn.execute("SELECT version FROM strategy_versions").fetchall()
    numbers = []
    for r in rows:
        v = r["version"]
        if v.startswith("v") and v[1:].isdigit():
            numbers.append(int(v[1:]))
    return f"v{max(numbers, default=0) + 1}"


def with_change(base: StrategyParams, version: str, **changes) -> StrategyParams:
    return replace(base, version=version, **changes)
