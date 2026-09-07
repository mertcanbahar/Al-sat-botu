"""Telegram notifications and the human-approval callback plumbing.

Reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from the environment (via
`alsatbotu.config`) and talks to the Bot API over plain HTTP (`requests`) --
there is no bot framework and no long-running process here, only
short-lived calls made from cron-triggered scripts.

Notification is never critical path: every function here swallows
failures -- missing credentials, network errors, API errors -- logs them,
and returns a falsy/empty result, so a broken or unconfigured Telegram
setup can never stop a portfolio run.

`send_message` is the original one-way notifier (BUY/SELL alerts, daily
reports). `send_message_with_keyboard`, `answer_callback_query`,
`edit_message_text`, and `get_updates` exist for exactly one purpose: the
weekly improvement loop's human-approval flow (see
`evaluation/improve.py` and `scripts/process_telegram_approvals.py`) --
posting a candidate strategy version with inline "Kabul et"/"Reddet"
buttons, and a separate polling script picking up the resulting
callback_query via `getUpdates`. This is polling, not a webhook or a
persistent bot process: nothing here listens continuously.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from alsatbotu import config

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID)


def _redact(text: str) -> str:
    """Strip the bot token out of text before logging it.

    The token is part of the Bot API URL, and requests' error messages
    (connection errors, HTTP errors) echo that URL back verbatim.
    """
    if config.TELEGRAM_TOKEN:
        return text.replace(config.TELEGRAM_TOKEN, "<TELEGRAM_TOKEN>")
    return text


def _call(method: str, payload: dict) -> Optional[dict]:
    """POST to the Bot API. Returns the parsed `result` field, or None on any failure."""
    if not is_configured():
        logger.warning(
            "Telegram is not configured (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing); "
            "skipping %s.",
            method,
        )
        return None

    url = f"{config.TELEGRAM_BASE_URL}/bot{config.TELEGRAM_TOKEN}/{method}"
    try:
        response = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("Telegram %s failed: %s", method, _redact(str(exc)))
        return None

    if response.status_code != 200:
        logger.error(
            "Telegram %s rejected (HTTP %s): %s",
            method,
            response.status_code,
            _redact(response.text[:300]),
        )
        return None

    return response.json().get("result")


def send_message(text: str, parse_mode: str | None = None) -> bool:
    """Send `text` to the configured chat. Returns True on success.

    Logs and returns False instead of raising on any failure.
    """
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    result = _call("sendMessage", payload)
    if result is None:
        return False
    logger.info("Telegram message sent (%d chars).", len(text))
    return True


def send_message_with_keyboard(text: str, keyboard: list[list[dict]]) -> Optional[dict]:
    """Send `text` with an inline keyboard (list of rows of {"text", "callback_data"}).

    Returns the sent message as a dict (with "message_id", "chat", ...) on
    success, or None on any failure -- callers that need to remember the
    message for later editing should check for None.
    """
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "reply_markup": {"inline_keyboard": keyboard},
    }
    result = _call("sendMessage", payload)
    if result is None:
        return None
    logger.info("Telegram message with keyboard sent (%d chars).", len(text))
    return result


def edit_message_text(chat_id, message_id, text: str, remove_keyboard: bool = True) -> bool:
    """Edit a previously sent message's text (e.g. to show a decision was made)."""
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if remove_keyboard:
        payload["reply_markup"] = {"inline_keyboard": []}
    return _call("editMessageText", payload) is not None


def answer_callback_query(callback_query_id: str, text: str | None = None) -> bool:
    """Acknowledge an inline-keyboard button press (clears the client's loading spinner)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _call("answerCallbackQuery", payload) is not None


def get_updates(offset: Optional[int] = None, timeout: int = 0) -> list[dict]:
    """Fetch pending updates (short poll -- meant to be called from a cron job, not a daemon).

    `offset` should be the last-processed update_id + 1, so Telegram
    doesn't redeliver updates the caller already handled. Returns an
    empty list on any failure or when unconfigured.
    """
    payload: dict = {"timeout": timeout, "allowed_updates": ["callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    result = _call("getUpdates", payload)
    return result if result is not None else []
