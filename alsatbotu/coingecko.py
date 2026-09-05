"""CoinGecko client for cryptocurrency OHLC data (no API key required)."""
from __future__ import annotations

import requests

from . import config
from .cache import DiskCache

_cache = DiskCache()


def fetch_ohlc(coin_id: str, vs_currency: str = "usd", days: int = 30) -> list[list[float]]:
    """Return raw CoinGecko OHLC candles: [[timestamp_ms, open, high, low, close], ...]."""
    key = {"coin_id": coin_id, "vs_currency": vs_currency, "days": days}
    cached = _cache.get("coingecko_ohlc", key)
    if cached is not None:
        return cached

    url = f"{config.COINGECKO_BASE_URL}/coins/{coin_id}/ohlc"
    response = requests.get(
        url,
        params={"vs_currency": vs_currency, "days": days},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    _cache.set("coingecko_ohlc", key, data)
    return data


def fetch_total_volumes(coin_id: str, vs_currency: str = "usd", days: int = 30) -> list[list[float]]:
    """Return CoinGecko's `total_volumes` series from the market_chart endpoint.

    Each point is `[timestamp_ms, volume]`. Note: this is NOT a per-candle
    traded volume — CoinGecko's public market_chart endpoint reports a
    rolling 24h trading volume sampled at each timestamp, not the volume
    traded within a single OHLC candle's interval (the public API does not
    expose true per-candle volume for OHLC data). See data.py for how this
    is matched to OHLC candles and read its docstring before relying on the
    resulting "volume" field for anything beyond a relative/trend signal.
    """
    key = {"coin_id": coin_id, "vs_currency": vs_currency, "days": days}
    cached = _cache.get("coingecko_total_volumes", key)
    if cached is not None:
        return cached

    url = f"{config.COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
    response = requests.get(
        url,
        params={"vs_currency": vs_currency, "days": days},
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("total_volumes", [])
    _cache.set("coingecko_total_volumes", key, data)
    return data
