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
