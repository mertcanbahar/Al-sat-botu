"""Twelve Data client for stocks/forex/crypto time series (requires an API key)."""
from __future__ import annotations

from .. import config
from .cache import DiskCache
from .retry import request_with_retry

_cache = DiskCache()


class TwelveDataError(RuntimeError):
    pass


def _is_rate_limited_body(response) -> bool:
    try:
        payload = response.json()
    except ValueError:
        return False
    return payload.get("status") == "error" and payload.get("code") == 429


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
    response = request_with_retry(
        "GET",
        url,
        params={
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": config.TWELVEDATA_API_KEY,
        },
        timeout=config.REQUEST_TIMEOUT_SECONDS,
        # Twelve Data reports rate limiting as HTTP 200 with an in-body
        # {"code": 429, "status": "error"} payload rather than a 429 status.
        should_retry_response=_is_rate_limited_body,
    )
    payload = response.json()
    if payload.get("status") == "error":
        raise TwelveDataError(payload.get("message", "Twelve Data request failed."))

    values = list(reversed(payload["values"]))  # API returns newest first
    _cache.set("twelvedata_time_series", key, values)
    return values
