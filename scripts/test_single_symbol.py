#!/usr/bin/env python3
"""Smoke test: verify the data layer + rule engine work for a single symbol.

Fetches real OHLC data for one CoinGecko coin (bitcoin by default; no API
key required) and confirms the rule engine produces a decision.

Usage:
    python scripts/test_single_symbol.py [coin_id] [days]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.data import get_price_history
from alsatbotu.indicators import add_indicators
from alsatbotu.signal import Signal, evaluate

INDICATOR_KEYS = (
    "ema_20",
    "ema_50",
    "rsi",
    "atr",
    "volume_sma_20",
)


def _format(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "N/A"


def test_single_symbol(coin_id: str = "bitcoin", days: int = 30) -> None:
    rows = get_price_history(coin_id, source="coingecko", days=days)
    assert rows, f"No price data returned for {coin_id!r}"
    assert {"timestamp", "open", "high", "low", "close"}.issubset(rows[0].keys())
    assert len(rows) >= 2, "Need at least 2 candles to evaluate the rule engine"

    decision = evaluate(rows)
    assert decision.signal in Signal

    latest = add_indicators(rows)[-1]

    print(f"Symbol: {coin_id}")
    print(f"Candles fetched: {len(rows)}")
    print(f"Latest close: {latest['close']}")
    print(f"Latest volume: {_format(latest.get('volume'))}")
    print("Indicators (latest candle, raw values):")
    for key in INDICATOR_KEYS:
        print(f"  {key}: {_format(latest[key])}")
    print(f"Signal: {decision.signal.value}")
    for reason in decision.reasons:
        print(f"  - {reason}")
    print("OK: data layer and rule engine work for a single symbol.")


if __name__ == "__main__":
    coin_id = sys.argv[1] if len(sys.argv) > 1 else "bitcoin"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    test_single_symbol(coin_id, days)
