"""Fiyatı gelmeyen açık pozisyon ve Twelve Data hız limiti.

Canlıda KO açık pozisyonken fiyatı çoğu koşuda gelmedi: 16 sembol art arda
çekiliyor, Twelve Data ücretsiz planı dakikada 8 istek kabul ediyor ve
listenin kuyruğu (WMT, KO, forex) HTTP 429 alıyordu. Fiyat gelmeyince stop
kontrolü de hiçbir iz bırakmadan atlanıyordu.
"""
from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import pytest
import requests

from alsatbotu.data import retry
from alsatbotu.data.twelvedata import RateLimiter
from portfolio.state import PortfolioState, Position


# -- RateLimiter -------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_limiter_lets_the_quota_through_without_waiting():
    clock = FakeClock()
    limiter = RateLimiter(8, 61.0, clock=clock, sleep=clock.sleep)
    for _ in range(8):
        limiter.acquire()
    assert clock.sleeps == []


def test_rate_limiter_waits_for_the_oldest_call_to_leave_the_window():
    clock = FakeClock()
    limiter = RateLimiter(8, 61.0, clock=clock, sleep=clock.sleep)
    for _ in range(8):
        limiter.acquire()
        clock.now += 1.0
    # 9. istek t=8'de: ilk istek (t=0) t=61'de pencereden düşer.
    limiter.acquire()
    assert clock.sleeps == [pytest.approx(53.0)]


def test_rate_limiter_never_exceeds_the_quota_in_any_window():
    clock = FakeClock()
    limiter = RateLimiter(8, 61.0, clock=clock, sleep=clock.sleep)
    calls = []
    for _ in range(16):  # canlı izleme listesinin boyu
        limiter.acquire()
        calls.append(clock.now)
    for start in calls:
        assert sum(1 for t in calls if start <= t < start + 60.0) <= 8


# -- retry: before_attempt ve gecikme tabanı ----------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_retry_calls_before_attempt_on_every_attempt_and_honours_the_delay_floor():
    attempts = []
    responses = [FakeResponse(429), FakeResponse(200, {"ok": True})]
    with patch("requests.request", side_effect=responses), patch.object(retry.time, "sleep") as sleep:
        retry.request_with_retry(
            "GET",
            "https://example.test",
            before_attempt=lambda: attempts.append(1),
            min_retry_delay_seconds=61.0,
        )
    assert len(attempts) == 2
    assert sleep.call_args.args[0] >= 61.0


# -- run_portfolio: sıralama ve fiyatsız pozisyon uyarısı ----------------------


@pytest.fixture()
def runner():
    return importlib.import_module("scripts.run_portfolio")


def test_held_symbols_are_fetched_first(runner):
    watchlist = [{"symbol": s} for s in ("AAPL", "MSFT", "WMT", "KO", "EUR/USD")]
    ordered = [e["symbol"] for e in runner._order_for_fetch(watchlist, {"KO", "MSFT"})]
    assert ordered == ["MSFT", "KO", "AAPL", "WMT", "EUR/USD"]


def _rate_limited_error() -> requests.HTTPError:
    response = FakeResponse(429)
    return requests.HTTPError(
        "429 Client Error: Too Many Requests for url: https://api.twelvedata.com/time_series?symbol=KO&apikey=SECRET",
        response=response,
    )


def test_unpriced_open_position_is_reported_not_skipped(runner, tmp_path, monkeypatch):
    state = PortfolioState(cash=1_000.0, starting_capital=10_000.0, peak_equity=10_000.0)
    state.open_positions["KO"] = Position(
        symbol="KO", category="consumer", quantity=32.55,
        entry_price=88.07, entry_date="2026-09-04", stop_price=85.18,
    )
    fetched: list[str] = []
    sent: list[str] = []

    def fake_history(symbol, source, days):
        fetched.append(symbol)
        raise _rate_limited_error()

    monkeypatch.setattr(runner, "WATCHLIST", [
        {"symbol": "AAPL", "category": "tech", "source": "twelvedata"},
        {"symbol": "KO", "category": "consumer", "source": "twelvedata"},
    ])
    monkeypatch.setattr(runner, "load_state", lambda: state)
    monkeypatch.setattr(runner, "save_state", lambda s: None)
    monkeypatch.setattr(runner, "last_decisions", lambda: {})
    monkeypatch.setattr(runner, "get_price_history", fake_history)
    monkeypatch.setattr(runner, "send_message", lambda text: sent.append(text) or True)
    monkeypatch.setattr(runner, "telegram_is_configured", lambda: True)
    monkeypatch.setattr(runner, "HEALTH_PATH", tmp_path / "health.json")
    monkeypatch.setattr(runner, "EQUITY_LEDGER_PATH", tmp_path / "equity.jsonl")

    runner.run(days=60)

    assert fetched[0] == "KO"
    assert "KO" in state.open_positions  # fiyat yokken stop'la kapatılmaz

    assert len(sent) == 1
    assert "KO" in sent[0] and "Stop kontrolü yapılamadı" in sent[0]
    assert "HTTP 429" in sent[0]
    assert "SECRET" not in sent[0]

    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    stop = next(m for m in health["modules"] if m["name"] == "stop")
    assert stop["status"] == "warn"
    assert stop["code"] == "W-STOP"
    assert "KO" in stop["detail"]


def test_stop_module_is_ok_when_every_position_is_priced(runner):
    assert runner._stop_module({})["status"] == "ok"


# -- daily_report ------------------------------------------------------------


def test_daily_report_flags_an_unpriced_position():
    from scripts.daily_report import build_report

    state = PortfolioState(cash=1_000.0, starting_capital=10_000.0, peak_equity=10_000.0)
    state.open_positions["KO"] = Position(
        symbol="KO", category="consumer", quantity=10.0,
        entry_price=88.07, entry_date="2026-09-04", stop_price=85.18,
    )
    report = build_report(state, current_prices={})
    assert "KO fiyatı alınamadı — stop (85.1800) kontrol edilemedi" in report
    assert "fiyat alınamadı" in report.split("Kategori dağılımı")[0]
