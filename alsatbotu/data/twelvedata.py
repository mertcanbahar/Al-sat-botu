"""Twelve Data client for stocks/forex/crypto time series (requires an API key)."""
from __future__ import annotations

import collections
import logging
import time

from .. import config
from .cache import DiskCache
from .retry import request_with_retry

logger = logging.getLogger(__name__)

_cache = DiskCache()

# Kota penceresi. Bir saniyelik pay, bizim saatimizle Twelve Data'nınki
# arasındaki kaymaya karşı.
_RATE_WINDOW_SECONDS = 61.0


class RateLimiter:
    """Kayan pencereli istemci tarafı hız sınırlayıcı.

    Son `period` saniyede `max_calls` istek yapıldıysa en eskisi pencereden
    düşene kadar bekler. Kayan pencere her takvim dakikasını da kapsadığı
    için sağlayıcı kotayı takvim dakikasıyla saysa bile aşılmaz.
    """

    def __init__(self, max_calls: int, period: float, clock=time.monotonic, sleep=time.sleep) -> None:
        self.max_calls = max_calls
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: collections.deque[float] = collections.deque()

    def acquire(self) -> None:
        if self.max_calls <= 0:
            return
        now = self._clock()
        while self._calls and now - self._calls[0] >= self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            wait = self.period - (now - self._calls[0])
            logger.info("Twelve Data dakika kotası dolu; %.1fs bekleniyor", wait)
            self._sleep(wait)
            now = self._clock()
            while self._calls and now - self._calls[0] >= self.period:
                self._calls.popleft()
        self._calls.append(now)


_limiter = RateLimiter(config.TWELVEDATA_REQUESTS_PER_MINUTE, _RATE_WINDOW_SECONDS)


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
        # Her deneme (tekrarlar dahil) kotadan düşer. Yine de 429 gelirse
        # (anahtarı başka bir iş de kullanıyorsa) dakika dolmadan tekrar
        # denemek boşa istek harcar: canlıda 1-4 sn'lik geri çekilmeler
        # WMT/KO/EUR/USD'yi hep 429'la düşürüyordu.
        before_attempt=_limiter.acquire,
        min_retry_delay_seconds=_RATE_WINDOW_SECONDS,
        max_retries=2,
    )
    payload = response.json()
    if payload.get("status") == "error":
        raise TwelveDataError(payload.get("message", "Twelve Data request failed."))

    values = list(reversed(payload["values"]))  # API returns newest first
    _cache.set("twelvedata_time_series", key, values)
    return values
