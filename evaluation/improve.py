"""Weekly self-improvement loop (task part D).

Once a week:
  1. Read last 7 days' losing paper trades.
  2. Look for one common pattern across a small, fixed set of dimensions
     (which entry indicator was extreme, which exit reason dominated,
     which asset type lost most) -- picking the single dimension whose
     loss rate deviates most from the week's overall loss rate.
  3. Map that one pattern to exactly one strategy-parameter change (never
     more than one field of `StrategyParams`), producing a new version.
  4. Backtest the old and new versions side by side over the *same*
     historical window and compare one metric (aggregate net return).
  5. Keep the new version only if it strictly beats the old one;
     otherwise the old version stays active and the new one is recorded
     as rejected.

This never touches an LLM prompt (none exists yet -- see
`evaluation/logger.py`'s PROMPT_VERSION) so "change the prompt" from the
task spec is a no-op path here: every accepted change is a
`StrategyParams` field.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from alsatbotu.config import WATCHLIST, asset_type_for
from alsatbotu.data import get_price_history
from alsatbotu.signal import Signal
from evaluation.db import connect
from evaluation.paper_engine import buy_fill_price, commission_for, sell_fill_price
from evaluation.strategy import StrategyParams, get_active_params, next_version_id, save_version

BACKTEST_DAYS = 180
MIN_SAMPLE = 3


@dataclass
class Pattern:
    dimension: str
    detail: str
    loss_rate_in_bucket: float
    overall_loss_rate: float
    sample_size: int


def _losing_and_all_trades(conn: sqlite3.Connection, since: datetime) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    rows = conn.execute(
        """
        SELECT pt.*, s.symbol, s.asset_type, s.indicators_json
        FROM paper_trades pt
        JOIN signals s ON s.id = pt.signal_id
        WHERE pt.exit_ts IS NOT NULL AND pt.exit_ts >= ?
        """,
        (since.isoformat(),),
    ).fetchall()
    losers = [r for r in rows if r["pnl"] is not None and r["pnl"] <= 0]
    return losers, rows


def find_pattern(losers: Sequence[sqlite3.Row], all_trades: Sequence[sqlite3.Row]) -> Optional[Pattern]:
    """Pick the single dimension/bucket whose loss rate deviates most from the week's average."""
    if len(all_trades) < MIN_SAMPLE or not losers:
        return None

    overall_loss_rate = len(losers) / len(all_trades)
    candidates: list[Pattern] = []

    def bucket_loss_rate(key_fn) -> dict:
        buckets: dict = {}
        for t in all_trades:
            buckets.setdefault(key_fn(t), [0, 0])[1] += 1
        for t in losers:
            buckets[key_fn(t)][0] += 1
        return buckets

    # 1) exit reason
    for key, (loss_n, total_n) in bucket_loss_rate(lambda t: t["exit_reason"]).items():
        if total_n >= MIN_SAMPLE:
            candidates.append(Pattern("exit_reason", key, loss_n / total_n, overall_loss_rate, total_n))

    # 2) asset type
    for key, (loss_n, total_n) in bucket_loss_rate(lambda t: t["asset_type"]).items():
        if total_n >= MIN_SAMPLE:
            candidates.append(Pattern("asset_type", key, loss_n / total_n, overall_loss_rate, total_n))

    # 3) hour of day (entry), bucketed into 4 six-hour windows
    def hour_bucket(t) -> str:
        hour = datetime.fromisoformat(t["entry_ts"]).hour
        window = (hour // 6) * 6
        return f"{window:02d}-{window + 6:02d}"

    for key, (loss_n, total_n) in bucket_loss_rate(hour_bucket).items():
        if total_n >= MIN_SAMPLE:
            candidates.append(Pattern("entry_hour", key, loss_n / total_n, overall_loss_rate, total_n))

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.loss_rate_in_bucket - p.overall_loss_rate)


def hypothesis_and_change(pattern: Pattern, base: StrategyParams, new_version: str) -> tuple[str, StrategyParams]:
    """Map exactly one pattern to exactly one StrategyParams field change."""
    if pattern.dimension == "exit_reason" and pattern.detail == "stop_loss":
        new_params = StrategyParams(
            version=new_version,
            rsi_buy_min=base.rsi_buy_min,
            rsi_buy_max=base.rsi_buy_max,
            rsi_sell_max=base.rsi_sell_max,
            atr_stop_multiplier=base.atr_stop_multiplier + 0.25,
        )
        hypothesis = (
            f"Kayıpların %{pattern.loss_rate_in_bucket * 100:.0f}'i stop-loss ile kapandı "
            f"(genel kayıp oranı %{pattern.overall_loss_rate * 100:.0f}) -- stop çok sıkı. "
            f"Hipotez: ATR stop çarpanını {base.atr_stop_multiplier} -> {new_params.atr_stop_multiplier} "
            "yaparak erken çıkışları azaltmak isabet oranını artırır."
        )
        return hypothesis, new_params

    if pattern.dimension == "asset_type":
        new_params = StrategyParams(
            version=new_version,
            rsi_buy_min=base.rsi_buy_min,
            rsi_buy_max=base.rsi_buy_max,
            rsi_sell_max=base.rsi_sell_max,
            atr_stop_multiplier=max(1.0, base.atr_stop_multiplier - 0.25),
        )
        hypothesis = (
            f"{pattern.detail} türündeki varlıklarda kayıp oranı %{pattern.loss_rate_in_bucket * 100:.0f} "
            f"(genel %{pattern.overall_loss_rate * 100:.0f}). Hipotez: ATR stop çarpanını "
            f"{base.atr_stop_multiplier} -> {new_params.atr_stop_multiplier} yaparak bu varlık "
            "türündeki büyük hareketlerden daha erken çıkmak kayıpları sınırlar."
        )
        return hypothesis, new_params

    # entry_hour, or anything else: no direct time-of-day lever exists, so
    # tighten the RSI entry band (demand a stronger, more central momentum
    # reading) as the one available, always-applicable change.
    new_params = StrategyParams(
        version=new_version,
        rsi_buy_min=base.rsi_buy_min + 2,
        rsi_buy_max=base.rsi_buy_max - 2,
        rsi_sell_max=base.rsi_sell_max,
        atr_stop_multiplier=base.atr_stop_multiplier,
    )
    hypothesis = (
        f"{pattern.detail} saat aralığında açılan işlemlerde kayıp oranı "
        f"%{pattern.loss_rate_in_bucket * 100:.0f} (genel %{pattern.overall_loss_rate * 100:.0f}). "
        f"Hipotez: RSI AL bandını [{base.rsi_buy_min}, {base.rsi_buy_max}] -> "
        f"[{new_params.rsi_buy_min}, {new_params.rsi_buy_max}] daraltarak zayıf momentum "
        "sinyallerini elemek kayıpları azaltır."
    )
    return hypothesis, new_params


@dataclass
class BacktestMetrics:
    total_return_pct: float
    trade_count: int
    hit_rate: Optional[float]


def _run_versioned_backtest(rows: Sequence[dict], params: StrategyParams) -> tuple[float, int, int]:
    """Long-only, no-lookahead simulation of `evaluate_versioned` with paper-engine costs.

    Returns (total_return_pct, trade_count, win_count) for one symbol.
    """
    from evaluation.strategy import evaluate_versioned

    equity = 1.0
    position: Optional[dict] = None
    trade_count = 0
    win_count = 0

    for i in range(1, len(rows)):
        window = rows[: i + 1]
        decision = evaluate_versioned(window, params)
        price = rows[i]["close"]

        if position is None and decision.signal == Signal.BUY:
            fill = buy_fill_price(price)
            position = {"entry": fill}
        elif position is not None and decision.signal == Signal.SELL:
            fill = sell_fill_price(price)
            gross_return = fill / position["entry"] - 1.0
            fee_pct = commission_for(1.0) * 2  # entry + exit, as a fraction of notional
            net_return = gross_return - fee_pct
            equity *= 1.0 + net_return
            trade_count += 1
            win_count += int(net_return > 0)
            position = None

    return equity - 1.0, trade_count, win_count


def backtest_params(params: StrategyParams, price_data: dict[str, list[dict]]) -> BacktestMetrics:
    returns = []
    total_trades = 0
    total_wins = 0
    for rows in price_data.values():
        if len(rows) < 60:
            continue
        ret, trades, wins = _run_versioned_backtest(rows, params)
        returns.append(ret)
        total_trades += trades
        total_wins += wins

    return BacktestMetrics(
        total_return_pct=statistics.fmean(returns) if returns else 0.0,
        trade_count=total_trades,
        hit_rate=(total_wins / total_trades) if total_trades else None,
    )


def _load_backtest_data(days: int = BACKTEST_DAYS) -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for entry in WATCHLIST:
        symbol = entry["symbol"]
        try:
            data[symbol] = get_price_history(symbol, source=entry.get("source", "coingecko"), days=days)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the loop
            print(f"{symbol}: failed to fetch backtest data ({exc})")
    return data


def run_weekly_improvement(conn: Optional[sqlite3.Connection] = None, now: Optional[datetime] = None) -> dict:
    """Run the full weekly loop once. Returns a summary dict for logging/printing."""
    owns_conn = conn is None
    conn = conn or connect()
    now = now or datetime.now(timezone.utc)
    try:
        since = now - timedelta(days=7)
        losers, all_trades = _losing_and_all_trades(conn, since)
        pattern = find_pattern(losers, all_trades)
        if pattern is None:
            return {
                "status": "no_pattern",
                "reason": f"Not enough closed trades in the last 7 days ({len(all_trades)}) "
                f"or no losses to analyze ({len(losers)}).",
            }

        base = get_active_params(conn)
        new_version = next_version_id(conn)
        hypothesis, new_params = hypothesis_and_change(pattern, base, new_version)

        price_data = _load_backtest_data()
        if not price_data:
            return {"status": "no_data", "reason": "No historical price data available to backtest."}

        old_metrics = backtest_params(base, price_data)
        new_metrics = backtest_params(new_params, price_data)

        accepted = new_metrics.total_return_pct > old_metrics.total_return_pct
        backtest_summary = {
            "old_version": base.version,
            "new_version": new_version,
            "old_total_return_pct": old_metrics.total_return_pct,
            "new_total_return_pct": new_metrics.total_return_pct,
            "old_trade_count": old_metrics.trade_count,
            "new_trade_count": new_metrics.trade_count,
            "old_hit_rate": old_metrics.hit_rate,
            "new_hit_rate": new_metrics.hit_rate,
        }

        save_version(
            new_params,
            parent_version=base.version,
            hypothesis=hypothesis,
            active=accepted,
            backtest=backtest_summary,
            conn=conn,
        )

        return {
            "status": "accepted" if accepted else "rejected",
            "pattern": vars(pattern),
            "hypothesis": hypothesis,
            "backtest": backtest_summary,
        }
    finally:
        if owns_conn:
            conn.close()
