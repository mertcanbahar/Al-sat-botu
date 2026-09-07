#!/usr/bin/env python3
"""Weekly self-improvement loop entry point (task part D).

See evaluation/improve.py for the algorithm: find one loss pattern from
the last 7 days of paper trades, change one strategy parameter, backtest
old vs. new on the *previous, non-overlapping* 30 days, and post the
result to Telegram as a candidate awaiting human approval.

This script never activates a version. It only ever:
  - saves a new `status="candidate"` row (done inside run_weekly_improvement), and
  - posts it to Telegram with "✅ Kabul et" / "❌ Reddet" buttons.

Activation happens exclusively in scripts/process_telegram_approvals.py,
in response to a human tapping one of those buttons.

Meant to run once a week (see .github/workflows/eval-weekly-improvement.yml).

Usage:
    python scripts/run_improvement_loop.py
"""
from __future__ import annotations

import logging
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.db import connect
from evaluation.improve import run_weekly_improvement
from evaluation.strategy import record_telegram_message
from notify.telegram import send_message, send_message_with_keyboard


def _param_diff(base_params, new_params) -> list[str]:
    lines = []
    for f in fields(base_params):
        if f.name == "version":
            continue
        old_value = getattr(base_params, f.name)
        new_value = getattr(new_params, f.name)
        if old_value != new_value:
            lines.append(f"  • {f.name}: {old_value} → {new_value}")
    return lines


def _format_message(result: dict) -> str:
    bt = result["backtest"]
    diff_lines = _param_diff(result["base_params"], result["new_params"])
    verdict = "yeni sürüm önde" if bt["new_wins_backtest"] else "eski sürüm önde"

    lines = [
        "🔧 Yeni aday strateji sürümü — onay bekliyor",
        "",
        f"Hipotez: {result['hypothesis']}",
        "",
        "Parametre farkı:",
        *diff_lines,
        "",
        f"Backtest penceresi: {bt['window_start']} → {bt['window_end']} "
        "(hipotezin çıkarıldığı son 7 günle çakışmıyor)",
        f"  • {bt['old_version']} (mevcut aktif): getiri %{bt['old_total_return_pct'] * 100:+.2f}, "
        f"{bt['old_trade_count']} işlem, isabet "
        f"{'%' + format(bt['old_hit_rate'] * 100, '.1f') if bt['old_hit_rate'] is not None else 'N/A'}",
        f"  • {bt['new_version']} (aday): getiri %{bt['new_total_return_pct'] * 100:+.2f}, "
        f"{bt['new_trade_count']} işlem, isabet "
        f"{'%' + format(bt['new_hit_rate'] * 100, '.1f') if bt['new_hit_rate'] is not None else 'N/A'}",
        f"  • Backtest sonucu: {verdict}",
        "",
        "Bu sürümü aktif etmek insan onayı gerektirir. Cevap verilmezse veya "
        "reddedilirse mevcut aktif sürüm değişmeden kalır.",
    ]
    return "\n".join(lines)


def main() -> None:
    conn = connect()
    result = run_weekly_improvement(conn)

    if result["status"] in ("no_pattern", "no_data"):
        message = f"🔧 Haftalık iyileştirme döngüsü: atlandı — {result['reason']}"
        print(message)
        send_message(message)
        conn.close()
        return

    message = _format_message(result)
    print(message)

    new_version = result["backtest"]["new_version"]
    keyboard = [
        [
            {"text": "✅ Kabul et", "callback_data": f"approve:{new_version}"},
            {"text": "❌ Reddet", "callback_data": f"reject:{new_version}"},
        ]
    ]
    sent = send_message_with_keyboard(message, keyboard)
    if sent is not None:
        record_telegram_message(new_version, sent["chat"]["id"], sent["message_id"], conn=conn)
    else:
        print("Telegram gönderimi başarısız oldu (yapılandırılmamış olabilir); aday DB'de duruyor.")

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
