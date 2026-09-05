"""Unified price-history provider on top of the CoinGecko and Twelve Data clients."""
from __future__ import annotations

import bisect
from datetime import datetime, timezone

from . import coingecko, twelvedata

SOURCES = ("coingecko", "twelvedata")


def _attach_nearest_volume(rows: list[dict], volume_points: list[list[float]]) -> list[dict]:
    """Attach the nearest-in-time `total_volumes` sample to each row as "volume".

    CoinGecko's public API has no endpoint for true per-candle traded
    volume alongside OHLC data: `/coins/{id}/ohlc` returns no volume at
    all, and `/coins/{id}/market_chart`'s `total_volumes` is a rolling 24h
    volume sampled on its own grid, which usually runs at a different
    granularity than the OHLC candles (e.g. 4h OHLC candles vs. hourly
    market_chart samples for a 3-30 day window). There is no bucket to sum
    within, since each sample already aggregates a trailing 24h window
    rather than the interval since the previous sample.

    So each candle gets the single closest volume sample by timestamp, on
    the same best-effort basis as reading "the 24h volume was approximately
    X around the time this candle closed". That is enough for a rule that
    only compares a value against its own moving average (rising vs.
    falling trading activity), which is the only use `rules.py` makes of
    it, but it is an approximation, not the candle's own traded volume.
    """
    if not volume_points:
        return rows

    sorted_points = sorted(volume_points, key=lambda point: point[0])
    timestamps = [point[0] for point in sorted_points]

    merged = []
    for row in rows:
        target_ms = row["timestamp"].timestamp() * 1000
        idx = bisect.bisect_left(timestamps, target_ms)
        candidates = [i for i in (idx - 1, idx) if 0 <= i < len(timestamps)]
        best_idx = min(candidates, key=lambda i: abs(timestamps[i] - target_ms))

        new_row = dict(row)
        new_row["volume"] = float(sorted_points[best_idx][1])
        merged.append(new_row)
    return merged


def get_price_history(
    symbol: str,
    source: str = "coingecko",
    vs_currency: str = "usd",
    days: int = 30,
    interval: str = "1day",
) -> list[dict]:
    """Fetch OHLC(V) history for a single symbol.

    Returns a list of dicts sorted oldest-first, each with keys:
    timestamp (UTC datetime), open, high, low, close, volume.

    For source="coingecko", "volume" comes from a separate market_chart
    call matched to each OHLC candle by nearest timestamp -- see
    `_attach_nearest_volume` and `coingecko.fetch_total_volumes` for why
    this is an approximation (a rolling 24h volume snapshot) rather than
    the candle's own traded volume.
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
        volume_points = coingecko.fetch_total_volumes(symbol, vs_currency=vs_currency, days=days)
        rows = _attach_nearest_volume(rows, volume_points)
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
