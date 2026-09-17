"""Tests for scripts/telegram_control_daemon.py's loop behavior.

No real Telegram calls here (no token in this environment, and none should
be needed): `process_updates` is monkeypatched to a scripted sequence, so
these only verify the daemon's *loop* contract -- it keeps calling
`process_updates` with the long-poll timeout, survives an exception from one
iteration without crashing, and backs off (briefly) after an error rather
than spinning hot.
"""
from __future__ import annotations

import pytest

import scripts.telegram_control_daemon as daemon


def test_run_forever_passes_the_long_poll_timeout_each_call(monkeypatch):
    calls = []

    def fake_process_updates(timeout: int = 0) -> int:
        calls.append(timeout)
        if len(calls) >= 3:
            raise KeyboardInterrupt
        return 0

    monkeypatch.setattr(daemon, "process_updates", fake_process_updates)
    monkeypatch.setattr(daemon.time, "sleep", lambda _seconds: None)

    with pytest.raises(KeyboardInterrupt):
        daemon.run_forever()

    assert calls == [daemon.POLL_TIMEOUT_SECONDS] * 3


def test_run_forever_survives_an_exception_and_backs_off(monkeypatch):
    calls = []
    slept = []

    def fake_process_updates(timeout: int = 0) -> int:
        calls.append(timeout)
        if len(calls) == 1:
            raise RuntimeError("boom: simulated network failure")
        raise KeyboardInterrupt  # stop the loop on the second call

    monkeypatch.setattr(daemon, "process_updates", fake_process_updates)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: slept.append(seconds))

    with pytest.raises(KeyboardInterrupt):
        daemon.run_forever()

    # First call raised and was swallowed; the loop backed off once, then
    # called process_updates a second time (which stopped it).
    assert len(calls) == 2
    assert slept == [daemon.ERROR_BACKOFF_SECONDS]
