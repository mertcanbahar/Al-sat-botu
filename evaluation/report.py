"""Daily Telegram report (task part C): today's paper-trading results.

Reports trade count, hit rate, average win/loss ratio, total PnL both net
of costs (commission + slippage) and gross of them, the three worst
trades, and a "if I had just held instead" comparison: an equal-weight
buy-and-hold of every symbol ever signaled, entered at that symbol's
first-ever recorded price and marked at its latest, against the paper
portfolio's actual equity today.
"""
from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timezone
from typing import Optional

from alsatbotu.config import PAPER_STARTING_CAPITAL
from evaluation.paper_engine import equity as paper_equity


def _trades_closed_on(conn: sqlite3.Connection, day: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pt.*, s.symbol
        FROM paper_trades pt
        JOIN signals s ON s.id = pt.signal_id
        WHERE pt.exit_ts IS NOT NULL AND substr(pt.exit_ts, 1, 10) = ?
        ORDER BY pt.exit_ts
        """,
        (day,),
    ).fetchall()


def _gross_pnl(trade: sqlite3.Row) -> float:
    return trade["pnl"] + trade["fee"] + trade["slippage"]


def _pnl_pct(trade: sqlite3.Row) -> float:
    basis = trade["entry_price"] * trade["size"]
    return trade["pnl"] / basis if basis else 0.0


def buy_and_hold_comparison(conn: sqlite3.Connection) -> tuple[Optional[float], Optional[float]]:
    """(buy_and_hold_equity, strategy_equity) since the first-ever logged signal.

    Symbols are equal-weighted from PAPER_STARTING_CAPITAL, entered at each
    symbol's earliest recorded price and marked at its latest -- an
    approximation of "never traded, just bought and held everything on the
    watchlist" using only data this database already has.
    """
    symbols = [r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM signals")]
    if not symbols:
        return None, None

    per_symbol_capital = PAPER_STARTING_CAPITAL / len(symbols)
    current_prices: dict[str, float] = {}
    bh_equity = 0.0
    for symbol in symbols:
        first = conn.execute(
            "SELECT price FROM signals WHERE symbol = ? ORDER BY ts ASC LIMIT 1", (symbol,)
        ).fetchone()
        last = conn.execute(
            "SELECT price FROM signals WHERE symbol = ? ORDER BY ts DESC LIMIT 1", (symbol,)
        ).fetchone()
        if not first or not last or not first["price"]:
            bh_equity += per_symbol_capital
            continue
        current_prices[symbol] = last["price"]
        bh_equity += per_symbol_capital * (last["price"] / first["price"])

    return bh_equity, paper_equity(conn, current_prices)


def build_daily_report(conn: sqlite3.Connection, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()
    trades = _trades_closed_on(conn, day)

    lines = [f"📈 Günlük Değerlendirme Raporu — {day}", ""]

    if not trades:
        lines.append("Bugün kapanan işlem yok.")
    else:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        hit_rate = len(wins) / len(trades)
        net_total = sum(t["pnl"] for t in trades)
        gross_total = sum(_gross_pnl(t) for t in trades)

        lines.append(f"İşlem sayısı: {len(trades)}")
        lines.append(f"İsabet oranı: %{hit_rate * 100:.1f} ({len(wins)}/{len(trades)})")

        if wins and losses:
            avg_win = statistics.fmean(_pnl_pct(t) for t in wins)
            avg_loss = statistics.fmean(_pnl_pct(t) for t in losses)
            ratio = avg_win / abs(avg_loss) if avg_loss else None
            lines.append(
                f"Ort. kazanç/kayıp oranı: {ratio:.2f} "
                f"(ort. kazanç %{avg_win * 100:.2f}, ort. kayıp %{avg_loss * 100:.2f})"
            )
        else:
            lines.append("Ort. kazanç/kayıp oranı: N/A (tek yönlü sonuç)")

        lines.append(f"Toplam PnL (maliyetler dahil): {net_total:+.2f} TL")
        lines.append(f"Toplam PnL (maliyetler hariç): {gross_total:+.2f} TL")
        lines.append(f"Toplam maliyet (komisyon+slipaj): {gross_total - net_total:.2f} TL")

        worst = sorted(trades, key=lambda t: t["pnl"])[:3]
        lines.append("")
        lines.append("En kötü 3 işlem:")
        for t in worst:
            lines.append(
                f"  • {t['symbol']}: {t['pnl']:+.2f} TL (%{_pnl_pct(t) * 100:+.2f}), "
                f"neden: {t['exit_reason']}"
            )

    bh_equity, strat_equity = buy_and_hold_comparison(conn)
    lines.append("")
    if bh_equity is not None and strat_equity is not None:
        diff = strat_equity - bh_equity
        verdict = "strateji önde" if diff > 0 else ("al-ve-tut önde" if diff < 0 else "eşit")
        lines.append("Al-ve-tut karşılaştırması (hiç işlem yapmayıp elde tutsaydım):")
        lines.append(f"  • Strateji (paper) portföy değeri: {strat_equity:,.2f} TL")
        lines.append(f"  • Al-ve-tut portföy değeri: {bh_equity:,.2f} TL")
        lines.append(f"  • Fark: {diff:+,.2f} TL ({verdict})")
    else:
        lines.append("Al-ve-tut karşılaştırması: henüz yeterli veri yok.")

    return "\n".join(lines)
