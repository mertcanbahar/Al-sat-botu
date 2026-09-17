#!/usr/bin/env python3
"""Long-polling companion to `scripts/process_telegram_controls.py`.

The GitHub Actions cron (`.github/workflows/telegram-control.yml`) short-polls
every 5 minutes -- reliable, but Telegram's `answerCallbackQuery` only accepts
an answer within a few seconds of the tap, so by the time the cron job gets to
it the callback query has always expired ("query is too old"). The button's
own loading spinner sticks as a result, even though the action underneath
(pause/resume/halt-clear) is applied correctly.

This script is the fix for *that* -- not a replacement for the cron job, an
addition to it. Run it locally (on the phone, in Termux) while you want fast
button feedback; the GitHub Actions cron keeps working as the always-on
fallback for whenever this isn't running (phone off, Termux closed, no
network). Both share the same offset file
(`alsatbotu.config.TELEGRAM_CONTROL_OFFSET_PATH`) and the same
`scripts.process_telegram_controls.process_updates()` logic, so an update
handled by one is never re-delivered to the other -- whichever gets to
Telegram first wins, the other's next poll just sees nothing new.

This process does NOT commit or push `data/portfolio.json` -- that's the
GitHub Actions job's responsibility (it runs in CI with its own git identity
and a controlled retry/rebase loop for the shared-state race). Running this
daemon updates the *local* state file only. If you want the phone's actions
to reach GitHub without waiting for the next cron tick, commit and push
`data/portfolio.json` (and the offset file) yourself -- deliberately not
automated here: an unattended `git push` from a long-running loop is a
second, less-controlled writer to the same file the CI job also writes to,
and the failure mode (silently losing a push, or racing CI's own commit) is
worse than a few minutes of extra lag before the next cron sync.

Usage:
    python scripts/telegram_control_daemon.py
    # or, to survive the terminal closing:
    nohup python3 scripts/telegram_control_daemon.py > logs/daemon.log 2>&1 &

See README.md for the short "nasıl başlatılır" note.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.process_telegram_controls import process_updates

logger = logging.getLogger(__name__)

# Telegram long-poll duration per call. Kept under Telegram's own ~50s cap
# and under `notify.telegram.get_updates`'s HTTP-timeout padding.
POLL_TIMEOUT_SECONDS = 25
# Pause between polls after a network/API error, so a persistent outage
# doesn't spin the loop hot.
ERROR_BACKOFF_SECONDS = 5


def run_forever() -> None:
    logger.info("Telegram control daemon started (long-poll timeout=%ss).", POLL_TIMEOUT_SECONDS)
    while True:
        try:
            handled = process_updates(timeout=POLL_TIMEOUT_SECONDS)
            if handled:
                logger.info("Applied %d control action(s).", handled)
        except Exception:  # noqa: BLE001 - a bad update must never kill the daemon
            logger.exception("Unhandled error in control-panel poll; backing off and retrying.")
            time.sleep(ERROR_BACKOFF_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        run_forever()
    except KeyboardInterrupt:
        logger.info("Telegram control daemon stopped.")
