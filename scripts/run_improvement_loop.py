#!/usr/bin/env python3
"""Weekly self-improvement loop entry point (task part D).

See evaluation/improve.py for the algorithm: find one loss pattern from
the last 7 days of paper trades, change one strategy parameter, backtest
old vs. new on the same historical data, and keep only the winner.

Meant to run once a week (see .github/workflows/eval-weekly-improvement.yml).

Usage:
    python scripts/run_improvement_loop.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.improve import run_weekly_improvement
from notify.telegram import send_message


def _format_message(result: dict) -> str:
    status = result["status"]
    if status in ("no_pattern", "no_data"):
        return f"🔧 Haftalık iyileştirme döngüsü: atlandı — {result['reason']}"

    bt = result["backtest"]
    lines = [
        "🔧 Haftalık iyileştirme döngüsü",
        "",
        f"Hipotez: {result['hypothesis']}",
        "",
        f"Backtest ({bt['old_version']} vs {bt['new_version']}, son {180} gün):",
        f"  • {bt['old_version']}: getiri %{bt['old_total_return_pct'] * 100:+.2f}, "
        f"{bt['old_trade_count']} işlem",
        f"  • {bt['new_version']}: getiri %{bt['new_total_return_pct'] * 100:+.2f}, "
        f"{bt['new_trade_count']} işlem",
        "",
    ]
    if status == "accepted":
        lines.append(f"✅ {bt['new_version']} kabul edildi ve aktif hale getirildi.")
    else:
        lines.append(f"❌ {bt['new_version']} eskisini geçemedi, {bt['old_version']} aktif kalıyor.")
    return "\n".join(lines)


def main() -> None:
    result = run_weekly_improvement()
    message = _format_message(result)
    print(message)
    send_message(message)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
