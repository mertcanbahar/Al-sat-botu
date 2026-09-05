"""Twelve Data client for stocks/forex/crypto time series (requires an API key)."""
from __future__ import annotations

import requests

from . import config
from .cache import DiskCache

_cache = DiskCache()


class TwelveDataError(RuntimeError):
    pass


def fetch_time_series(symbol: str, interval: str = "1day", outputsize: int = 30) -> list[dict]:
    """Return Twelve Data time series values, oldest first."""
    key = {"symbol": symbol, "interval": interval, "outputsize": outputsize}
    cached = _cache.get("twelvedata_time_series", key)
    if cached is not None:
        return cached

    if not config.TWELVEDATA_API_KEY:
        raise TwelveDataError(
            "TWELVEDATA_API_KEY is not set; export it before fetching Twelve Data."
        )

    url = f"{config.TWELVEDATA_BASE_URL}/time_series"
    response = requests.get(
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": config.TWELVEDATA_API_KEY,
        },
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "error":
        raise TwelveDataError(payload.get("message", "Twelve Data request failed."))

    values = list(reversed(payload["values"]))  # API returns newest first
    _cache.set("twelvedata_time_series", key, values)
    return values
