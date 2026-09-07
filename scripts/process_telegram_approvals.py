#!/usr/bin/env python3
"""Poll Telegram for approve/reject taps on candidate strategy versions.

This is the only place a strategy version's `active` flag is ever
flipped by the improvement loop's output. `scripts/run_improvement_loop.py`
only ever creates `status="candidate"` rows and posts them to Telegram
with inline buttons -- this script is what turns a button tap into
`activate_version()` / `reject_version()` (evaluation/strategy.py).

Short-poll only (`getUpdates` with `timeout=0`): meant to run frequently
from cron (see .github/workflows/eval-process-approvals.yml), not as a
long-running bot process. The last processed update_id is persisted in
the `telegram_offset` table so re-running this script never reprocesses
a button press.

A candidate that is rejected, or never answered at all, simply stays
`status="candidate"`/`"rejected"` with `active` untouched -- whatever
version was active before the loop ran stays active.

Usage:
    python scripts/process_telegram_approvals.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.db import connect
from evaluation.strategy import activate_version, get_version, reject_version
from notify.telegram import answer_callback_query, edit_message_text, get_updates

logger = logging.getLogger(__name__)


def _get_offset(conn) -> int:
    row = conn.execute("SELECT last_update_id FROM telegram_offset WHERE id = 1").fetchone()
    return row["last_update_id"] if row else 0


def _set_offset(conn, last_update_id: int) -> None:
    conn.execute(
        """
        INSERT INTO telegram_offset (id, last_update_id) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET last_update_id = excluded.last_update_id
        """,
        (last_update_id,),
    )
    conn.commit()


def process_updates(conn) -> int:
    """Process every pending callback_query update. Returns the number handled."""
    offset = _get_offset(conn)
    updates = get_updates(offset=offset)
    handled = 0

    for update in updates:
        # Advance the offset past every update we see, whether or not it's
        # a callback_query we act on -- an update Telegram delivered once
        # should never come back just because it wasn't one we cared about.
        offset = max(offset, update["update_id"] + 1)

        callback = update.get("callback_query")
        if not callback:
            continue

        data = callback.get("data", "")
        callback_id = callback["id"]
        if ":" not in data:
            answer_callback_query(callback_id)
            continue

        action, version = data.split(":", 1)
        row = get_version(version, conn=conn)
        message = callback.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if row is None or row["status"] != "candidate":
            answer_callback_query(callback_id, "Bu aday artık bekleyen bir onay değil.")
            continue

        if action == "approve":
            activate_version(version, conn=conn)
            answer_callback_query(callback_id, f"{version} aktif edildi.")
            if chat_id is not None and message_id is not None:
                edit_message_text(
                    chat_id, message_id, f"{message.get('text', '')}\n\n✅ Kabul edildi ve aktif edildi."
                )
            logger.info("Activated strategy version %s (approved via Telegram).", version)
            handled += 1
        elif action == "reject":
            reject_version(version, conn=conn)
            answer_callback_query(callback_id, f"{version} reddedildi.")
            if chat_id is not None and message_id is not None:
                edit_message_text(
                    chat_id, message_id, f"{message.get('text', '')}\n\n❌ Reddedildi."
                )
            logger.info("Rejected strategy version %s (rejected via Telegram).", version)
            handled += 1
        else:
            answer_callback_query(callback_id)

    _set_offset(conn, offset)
    return handled


def main() -> None:
    conn = connect()
    handled = process_updates(conn)
    conn.close()
    print(f"Processed {handled} approval decision(s).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
