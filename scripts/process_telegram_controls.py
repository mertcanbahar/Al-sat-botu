#!/usr/bin/env python3
"""Poll Telegram for the button-based bot control panel.

Two kinds of updates are handled, both only from `TELEGRAM_CHAT_ID` (any
other chat's taps/messages are ignored, but still consumed so they don't
come back):

  - A plain text message -> replies with the control panel (inline
    keyboard: "Durum", "Duraklat", "Devam Et", "Halt Kaldır"). This is the
    only free-text interaction in the whole flow; everything after the
    panel is shown is a button tap, per the "tuşlu sistem" requirement.
  - A callback_query with `ctrl:<action>` data -> applies the action to
    `data/portfolio.json` (the JSON-based live portfolio's `PortfolioState`)
    and edits the message to show the result.

Short-poll only (`getUpdates` with `timeout=0`): meant to run frequently
from cron (see .github/workflows/telegram-control.yml), not as a
long-running bot process. This script's offset is tracked separately from
`scripts/process_telegram_approvals.py`'s (see
`alsatbotu.config.TELEGRAM_CONTROL_OFFSET_PATH`) -- two independent
short-poll consumers, each with their own high-water mark, each ignoring
(but still advancing past) updates meant for the other.

`pause`/`resume` here are independent of the drawdown-halt machinery
(`state.halted`/`state.stopped`, owned by `engine.risk.update_halt_state()`):
it's a manual, always-reversible human toggle, not a risk decision. Existing
positions are still sold while paused; only new BUYs stop (see
`engine.risk.evaluate_buy`). "Halt Kaldır" is the one control-panel action
that touches the risk-owned `stopped` state, and it delegates to
`scripts.resume_halt.attempt_resume()` so the safety checks (hard floor,
drawdown) live in exactly one place.

Usage:
    python scripts/process_telegram_controls.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import TELEGRAM_CHAT_ID, TELEGRAM_CONTROL_OFFSET_PATH, source_for
from alsatbotu.data import get_price_history
from notify.telegram import answer_callback_query, edit_message_text, get_updates, send_message_with_keyboard
from portfolio.state import load_state, save_state
from scripts.resume_halt import attempt_resume, current_prices, describe

logger = logging.getLogger(__name__)

CONTROL_KEYBOARD = [
    [{"text": "📊 Durum", "callback_data": "ctrl:status"}],
    [
        {"text": "⏸ Duraklat", "callback_data": "ctrl:pause"},
        {"text": "▶️ Devam Et", "callback_data": "ctrl:resume"},
    ],
    [{"text": "🔓 Halt Kaldır", "callback_data": "ctrl:clear_halt"}],
]


def _get_offset() -> int:
    if not os.path.exists(TELEGRAM_CONTROL_OFFSET_PATH):
        return 0
    with open(TELEGRAM_CONTROL_OFFSET_PATH, "r", encoding="utf-8") as f:
        return json.load(f).get("last_update_id", 0)


def _set_offset(last_update_id: int) -> None:
    TELEGRAM_CONTROL_OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TELEGRAM_CONTROL_OFFSET_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"last_update_id": last_update_id}, f)
    os.replace(tmp_path, TELEGRAM_CONTROL_OFFSET_PATH)


def _is_authorized_chat(chat_id) -> bool:
    # TELEGRAM_CHAT_ID gelir string; Telegram chat.id'yi sayı olarak yollar.
    return TELEGRAM_CHAT_ID != "" and str(chat_id) == str(TELEGRAM_CHAT_ID)


def _status_text() -> str:
    state = load_state()
    prices = current_prices(state)
    equity = state.equity(prices)
    lines = [describe(state, equity)]
    lines.append(f"Duraklatıldı     : {'EVET (' + str(state.paused_reason) + ')' if state.paused else 'hayır'}")
    return "\n".join(lines)


def _handle_pause(pause: bool) -> str:
    state = load_state()
    state.paused = pause
    state.paused_reason = "Telegram" if pause else None
    save_state(state)
    return "⏸ Bot duraklatıldı. Mevcut pozisyonlar yönetilmeye devam eder, yeni ALIM yapılmaz." if pause \
        else "▶️ Bot devam ediyor."


def _handle_clear_halt() -> str:
    state = load_state()
    prices = current_prices(state)
    equity = state.equity(prices)
    result = attempt_resume(state, equity)
    if result.applied:
        save_state(state)
        text = "🔓 Kalıcı durdurma kaldırıldı."
        if result.messages:
            text += "\n\n" + "\n".join(result.messages)
        return text
    return "\n".join(result.messages) or "Yapılacak bir şey yok."


def _handle_callback(callback: dict) -> bool:
    """Returns True iff this was one of ours (`ctrl:*`) and got acted on."""
    callback_id = callback["id"]
    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    data = callback.get("data", "")

    if not data.startswith("ctrl:"):
        return False  # başka bir akışın (ör. strateji onayı) butonu, bize ait değil

    if not _is_authorized_chat(chat_id):
        answer_callback_query(callback_id)
        return False

    action = data.split(":", 1)[1]
    if action == "status":
        answer_callback_query(callback_id)
        if chat_id is not None:
            send_message_with_keyboard(_status_text(), CONTROL_KEYBOARD)
        return True
    elif action == "pause":
        text = _handle_pause(True)
    elif action == "resume":
        text = _handle_pause(False)
    elif action == "clear_halt":
        text = _handle_clear_halt()
    else:
        answer_callback_query(callback_id)
        return False

    answer_callback_query(callback_id, text[:200])
    if chat_id is not None and message_id is not None:
        edit_message_text(chat_id, message_id, text)
    logger.info("Telegram control action %r applied.", action)
    return True


def _handle_message(message: dict) -> None:
    chat_id = message.get("chat", {}).get("id")
    if not _is_authorized_chat(chat_id) or not message.get("text"):
        return
    send_message_with_keyboard("🎛 Kontrol paneli:\n\n" + _status_text(), CONTROL_KEYBOARD)


def process_updates() -> int:
    """Process every pending update. Returns the number of control actions applied."""
    offset = _get_offset()
    updates = get_updates(offset=offset, allowed_updates=["callback_query", "message"])
    handled = 0

    for update in updates:
        offset = max(offset, update["update_id"] + 1)

        callback = update.get("callback_query")
        if callback:
            if _handle_callback(callback):
                handled += 1
            continue

        message = update.get("message")
        if message:
            _handle_message(message)

    _set_offset(offset)
    return handled


def main() -> None:
    handled = process_updates()
    print(f"Processed {handled} control update(s).")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
