"""Shared HTTP retry/backoff helper for the data clients.

Both `coingecko.py` and `twelvedata.py` hit third-party APIs that rate-limit
(429) or occasionally return 5xx/timeouts under load. Previously a single
failed request bubbled straight up and the caller (`run_portfolio.py`)
simply skipped that symbol for the run. This retries transient failures
with exponential backoff (+ jitter) before giving up.
"""
from __future__ import annotations

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 1.0


def request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    should_retry_response=None,
    **kwargs,
) -> requests.Response:
    """Perform an HTTP request, retrying transient failures with backoff.

    Retries on connection errors/timeouts and on HTTP 429/5xx responses
    (honoring a `Retry-After` header when present), plus any response for
    which `should_retry_response(response)` returns True -- used for APIs
    like Twelve Data that report rate limiting as HTTP 200 with an
    in-body error code rather than a 429 status.

    Raises the last exception, or the last response's `raise_for_status()`
    error, once `max_retries` is exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt == max_retries:
                raise
            delay = _backoff_delay(attempt, backoff_base_seconds)
            logger.warning(
                "%s %s failed (%s); retrying in %.1fs (attempt %d/%d)",
                method, url, exc, delay, attempt + 1, max_retries,
            )
            time.sleep(delay)
            continue

        is_retryable_status = response.status_code in RETRYABLE_STATUS_CODES
        is_retryable_body = bool(should_retry_response and should_retry_response(response))
        if not (is_retryable_status or is_retryable_body):
            response.raise_for_status()
            return response

        if attempt == max_retries:
            response.raise_for_status()
            return response

        delay = _retry_after_delay(response) or _backoff_delay(attempt, backoff_base_seconds)
        logger.warning(
            "%s %s returned %d; retrying in %.1fs (attempt %d/%d)",
            method, url, response.status_code, delay, attempt + 1, max_retries,
        )
        time.sleep(delay)

    if last_exc is not None:  # pragma: no cover - unreachable, loop always returns/raises
        raise last_exc
    raise RuntimeError("request_with_retry: exhausted retries without a response")  # pragma: no cover


def _backoff_delay(attempt: int, base_seconds: float) -> float:
    return base_seconds * (2**attempt) + random.uniform(0, base_seconds)


def _retry_after_delay(response: requests.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None
