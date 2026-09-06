"""Mocked tests for the data layer: HTTP clients, retry/backoff, and cache.

No real network calls are made -- `requests.request` is patched everywhere.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from alsatbotu.data import coingecko, twelvedata
from alsatbotu.data.cache import DiskCache
from alsatbotu.data.retry import request_with_retry
from alsatbotu.data.twelvedata import TwelveDataError


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("alsatbotu.data.retry.time.sleep"):
        yield


@pytest.fixture()
def isolated_cache(tmp_path, monkeypatch):
    cache = DiskCache(cache_dir=tmp_path, ttl_seconds=300)
    monkeypatch.setattr(coingecko, "_cache", cache)
    monkeypatch.setattr(twelvedata, "_cache", cache)
    return cache


# -- retry helper ------------------------------------------------------


def test_request_with_retry_succeeds_first_try():
    with patch("requests.request", return_value=FakeResponse(200, {"ok": True})) as mock_req:
        response = request_with_retry("GET", "https://example.test")
    assert response.json() == {"ok": True}
    assert mock_req.call_count == 1


def test_request_with_retry_recovers_after_429():
    responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200, {"ok": True})]
    with patch("requests.request", side_effect=responses) as mock_req:
        response = request_with_retry("GET", "https://example.test", max_retries=3)
    assert response.json() == {"ok": True}
    assert mock_req.call_count == 3


def test_request_with_retry_gives_up_after_max_retries():
    with patch("requests.request", return_value=FakeResponse(500)) as mock_req:
        with pytest.raises(requests.HTTPError):
            request_with_retry("GET", "https://example.test", max_retries=2)
    assert mock_req.call_count == 3  # initial attempt + 2 retries


def test_request_with_retry_retries_on_connection_error_then_succeeds():
    side_effect = [requests.ConnectionError("boom"), FakeResponse(200, {"ok": True})]
    with patch("requests.request", side_effect=side_effect) as mock_req:
        response = request_with_retry("GET", "https://example.test", max_retries=2)
    assert response.json() == {"ok": True}
    assert mock_req.call_count == 2


def test_request_with_retry_raises_after_repeated_timeouts():
    with patch("requests.request", side_effect=requests.Timeout("slow")) as mock_req:
        with pytest.raises(requests.Timeout):
            request_with_retry("GET", "https://example.test", max_retries=2)
    assert mock_req.call_count == 3


def test_request_with_retry_does_not_retry_client_errors():
    with patch("requests.request", return_value=FakeResponse(404)) as mock_req:
        with pytest.raises(requests.HTTPError):
            request_with_retry("GET", "https://example.test", max_retries=3)
    assert mock_req.call_count == 1


# -- coingecko -----------------------------------------------------------


def test_coingecko_fetch_ohlc_success(isolated_cache):
    candles = [[1, 2, 3, 1, 2]]
    with patch("requests.request", return_value=FakeResponse(200, candles)) as mock_req:
        result = coingecko.fetch_ohlc("bitcoin", days=7)
    assert result == candles
    assert mock_req.call_count == 1


def test_coingecko_fetch_ohlc_uses_cache_on_second_call(isolated_cache):
    candles = [[1, 2, 3, 1, 2]]
    with patch("requests.request", return_value=FakeResponse(200, candles)) as mock_req:
        coingecko.fetch_ohlc("bitcoin", days=7)
        coingecko.fetch_ohlc("bitcoin", days=7)
    assert mock_req.call_count == 1


def test_coingecko_fetch_ohlc_retries_on_rate_limit(isolated_cache):
    responses = [FakeResponse(429), FakeResponse(200, [[1, 2, 3, 1, 2]])]
    with patch("requests.request", side_effect=responses) as mock_req:
        result = coingecko.fetch_ohlc("bitcoin", days=7)
    assert result == [[1, 2, 3, 1, 2]]
    assert mock_req.call_count == 2


# -- twelvedata ------------------------------------------------------------


def test_twelvedata_requires_api_key(monkeypatch, isolated_cache):
    monkeypatch.setattr("alsatbotu.data.twelvedata.config.TWELVEDATA_API_KEY", "")
    with pytest.raises(TwelveDataError):
        twelvedata.fetch_time_series("AAPL")


def test_twelvedata_fetch_time_series_success(monkeypatch, isolated_cache):
    monkeypatch.setattr("alsatbotu.data.twelvedata.config.TWELVEDATA_API_KEY", "key")
    payload = {
        "status": "ok",
        "values": [
            {"datetime": "2024-01-02", "open": "2", "high": "3", "low": "1", "close": "2"},
            {"datetime": "2024-01-01", "open": "1", "high": "2", "low": "0", "close": "1"},
        ],
    }
    with patch("requests.request", return_value=FakeResponse(200, payload)) as mock_req:
        result = twelvedata.fetch_time_series("AAPL")
    assert mock_req.call_count == 1
    # Oldest first (API returns newest first).
    assert [v["datetime"] for v in result] == ["2024-01-01", "2024-01-02"]


def test_twelvedata_raises_on_error_status(monkeypatch, isolated_cache):
    monkeypatch.setattr("alsatbotu.data.twelvedata.config.TWELVEDATA_API_KEY", "key")
    payload = {"status": "error", "code": 400, "message": "bad symbol"}
    with patch("requests.request", return_value=FakeResponse(200, payload)) as mock_req:
        with pytest.raises(TwelveDataError, match="bad symbol"):
            twelvedata.fetch_time_series("NOPE")
    assert mock_req.call_count == 1  # a 400-style body error isn't retried


def test_twelvedata_retries_in_body_rate_limit(monkeypatch, isolated_cache):
    monkeypatch.setattr("alsatbotu.data.twelvedata.config.TWELVEDATA_API_KEY", "key")
    rate_limited = FakeResponse(200, {"status": "error", "code": 429, "message": "limit"})
    ok = FakeResponse(200, {"status": "ok", "values": []})
    with patch("requests.request", side_effect=[rate_limited, ok]) as mock_req:
        result = twelvedata.fetch_time_series("AAPL")
    assert result == []
    assert mock_req.call_count == 2
