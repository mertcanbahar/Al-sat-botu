"""Unified price-history provider on top of the CoinGecko and Twelve Data clients."""
from __future__ import annotations

from datetime import datetime, timezone

from . import coingecko, twelvedata

SOURCES = ("coingecko", "twelvedata")


def get_price_history(
    symbol: str,
    source: str = "coingecko",
    vs_currency: str = "usd",
    days: int = 30,
    interval: str = "1day",
) -> list[dict]:
    """Fetch OHLC(V) history for a single symbol.

    Returns a list of dicts sorted oldest-first, each with keys:
    timestamp (UTC datetime), open, high, low, close[, volume].
    """
    if source == "coingecko":
        raw = coingecko.fetch_ohlc(symbol, vs_currency=vs_currency, days=days)
        rows = [
            {
                "timestamp": datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
            }
            for candle in raw
        ]
    elif source == "twelvedata":
        raw = twelvedata.fetch_time_series(symbol, interval=interval, outputsize=days)
        rows = []
        for point in raw:
            row = {
                "timestamp": datetime.fromisoformat(point["datetime"]).replace(
                    tzinfo=timezone.utc
                ),
                "open": float(point["open"]),
                "high": float(point["high"]),
                "low": float(point["low"]),
                "close": float(point["close"]),
            }
            if point.get("volume") is not None:
                row["volume"] = float(point["volume"])
            rows.append(row)
    else:
        raise ValueError(f"Unknown source: {source!r} (expected one of {SOURCES})")

    return sorted(rows, key=lambda row: row["timestamp"])
