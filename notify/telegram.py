"""Telegram notifications.

Reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from the environment (via
`alsatbotu.config`) and sends messages through the Bot API.

Notification is never critical path: `send_message` swallows every
failure -- missing credentials, network errors, API errors -- logs it, and
returns False, so a broken or unconfigured Telegram setup can never stop a
portfolio run.
"""
from __future__ import annotations

import logging

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


def send_message(text: str, parse_mode: str | None = None) -> bool:
    """Send `text` to the configured chat. Returns True on success.

    Logs and returns False instead of raising on any failure.
    """
    if not is_configured():
        logger.warning(
            "Telegram is not configured (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID missing); "
            "skipping message."
        )
        return False

    url = f"{config.TELEGRAM_BASE_URL}/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        response = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("Telegram message failed: %s", _redact(str(exc)))
        return False

    if response.status_code != 200:
        logger.error(
            "Telegram message rejected (HTTP %s): %s",
            response.status_code,
            _redact(response.text[:300]),
        )
        return False

    logger.info("Telegram message sent (%d chars).", len(text))
    return True
