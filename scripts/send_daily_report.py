#!/usr/bin/env python3
"""Send the daily evaluation-loop report to Telegram (task part C).

Meant to run once a day at 23:00 local (Europe/Istanbul) -- see
.github/workflows/eval-daily-report.yml. Read-only: never touches
paper_trades or signals, only reports on them.

Usage:
    python scripts/send_daily_report.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.db import connect
from evaluation.report import build_daily_report
from notify.telegram import send_message


def main() -> None:
    conn = connect()
    report = build_daily_report(conn)
    conn.close()

    print(report)
    send_message(report)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
