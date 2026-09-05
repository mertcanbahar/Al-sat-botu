"""Append-only signal ledger.

Every signal the rule engine produces is recorded to
`data/signals.jsonl` (one JSON object per line -- see
`alsatbotu.config.SIGNALS_LEDGER_PATH`). The file is only ever opened in
append mode: existing lines are never rewritten or removed, so it stays a
full audit trail of every decision the bot ever made.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alsatbotu.config import SIGNALS_LEDGER_PATH
from alsatbotu.rules import Decision


def log_signal(
    symbol: str,
    decision: Decision,
    price: float,
    indicators: dict,
    timestamp: datetime | None = None,
    path: Path = SIGNALS_LEDGER_PATH,
) -> dict:
    """Append one signal record to the ledger and return the record written."""
    record = {
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "symbol": symbol,
        "decision": decision.signal.value,
        "price": price,
        "triggering_rule": list(decision.reasons),
        "indicators": {
            "ema_20": indicators.get("ema_20"),
            "ema_50": indicators.get("ema_50"),
            "rsi": indicators.get("rsi"),
            "atr": indicators.get("atr"),
            "volume_sma_20": indicators.get("volume_sma_20"),
        },
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")

    return record


def read_signals(path: Path = SIGNALS_LEDGER_PATH) -> list[dict]:
    """Read all recorded signals from the ledger, oldest first."""
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
