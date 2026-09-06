"""Writes one `signals` row (schema A) per evaluated symbol."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from alsatbotu.rules import Decision
from evaluation.strategy import StrategyParams, confidence_for

PROMPT_VERSION = "rule-engine-v1"  # no LLM prompt yet; bumped if/when one is added


def log_signal(
    conn: sqlite3.Connection,
    symbol: str,
    asset_type: str,
    price: float,
    indicators: dict,
    decision: Decision,
    params: StrategyParams,
    ts: Optional[datetime] = None,
) -> int:
    """Insert one signal row and return its id."""
    indicators_json = json.dumps(
        {
            "ema_20": indicators.get("ema_20"),
            "ema_50": indicators.get("ema_50"),
            "rsi": indicators.get("rsi"),
            "atr": indicators.get("atr"),
            "volume": indicators.get("volume"),
            "volume_sma_20": indicators.get("volume_sma_20"),
        }
    )
    cur = conn.execute(
        """
        INSERT INTO signals
            (ts, symbol, asset_type, price, indicators_json, decision,
             confidence, reasoning, prompt_version, strategy_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (ts or datetime.now(timezone.utc)).isoformat(),
            symbol,
            asset_type,
            price,
            indicators_json,
            decision.signal.value,
            confidence_for(decision, indicators, params),
            "; ".join(decision.reasons) or None,
            PROMPT_VERSION,
            params.version,
        ),
    )
    conn.commit()
    return cur.lastrowid
