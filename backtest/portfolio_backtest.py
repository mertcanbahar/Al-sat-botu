#!/usr/bin/env python3
"""Does the live rule engine beat equal-weight buy-and-hold?

Runs two separate simulations, both driven by the exact same production
code -- `alsatbotu.signal.evaluate()` for signals and `engine.risk.evaluate_buy()`
for position sizing / portfolio guardrails. Neither is modified or
reimplemented here.

1. Per-symbol (isolated): each of the 20 backtest symbols gets its own
   dedicated sub-account (starting capital / 20) and its own
   `PortfolioState`, so portfolio-wide caps (max positions, category
   exposure) never bind across symbols -- only the per-trade risk sizing
   and the drawdown halt (`engine.risk.HaltPolicy`, overridable per run
   via `simulate(..., halt_policy=...)`) apply, exactly as they would
   for a single-symbol account. This answers "does the rule engine beat
   buy-and-hold for this specific stock?"

2. Portfolio-wide (shared): all 20 symbols trade against one shared
   `PortfolioState` and one starting capital, so `MAX_OPEN_POSITIONS`,
   `CATEGORY_EXPOSURE_LIMIT_PCT`, and 2%-risk sizing all bind exactly as
   they do in `scripts/run_portfolio.py`. This answers "does the whole
   system beat an equal-weight buy-and-hold portfolio of the same 20
   stocks?"

Realism:
  - Signals are computed on day T's close (using only rows[0:T+1], no
    lookahead) and executed at day T+1's open.
  - Every fill pays slippage (adverse move off the quoted open) and a
    commission, both flat percentages -- see COMMISSION_PCT / SLIPPAGE_PCT
    below for the exact assumption.
  - Buy-and-hold benchmarks pay the same entry slippage + commission as
    the strategy, so the comparison isn't tilted by only costing one side.

Survivorship bias: the 20-symbol universe (see BACKTEST_SYMBOLS) is
today's list of large, decades-old, still-listed companies -- it is not a
reconstruction of any index's actual historical constituents. Over a
5-year window this is a mild rather than severe bias (none of these
names were meaningfully at risk of delisting or bankruptcy across
2021-2026), but it still means the sample skews toward known survivors
rather than a point-in-time-correct universe, and the resulting numbers
should be read as "how would this rule set have performed on today's
blue chips," not as an unbiased estimate of a strategy applied to the
market as a whole. This is disclosed, not corrected -- correcting it
would require a historical index-constituent dataset this project does
not have.

Usage:
    python backtest/portfolio_backtest.py [--years 5] [--out-dir backtest/results]
    python backtest/portfolio_backtest.py --synthetic --out-dir /tmp/bt-smoke  # code smoke test, no network
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import SYMBOL_CATEGORIES
from alsatbotu.indicators import add_indicators
from alsatbotu.signal import Signal, evaluate
from engine.risk import HaltPolicy, evaluate_buy, update_halt_state
from portfolio.state import PortfolioState, close_position, open_position

# --------------------------------------------------------------------------
# Backtest universe
# --------------------------------------------------------------------------
# The 10 symbols already live in alsatbotu.config.SYMBOL_CATEGORIES, plus 10
# more chosen for sector spread. Categories not already used by the live
# config (healthcare, industrials, utilities, materials, communication,
# real_estate) are introduced here, backtest-only -- alsatbotu/config.py and
# the live WATCHLIST it feeds to scripts/run_portfolio.py are untouched, so
# this analysis has no effect on live paper trading.
#
# Tech count stays at 6 (AAPL, MSFT, GOOGL, AMZN, NVDA, META) out of 20 = 30%,
# under the 50% cap the task set.
NEW_SYMBOL_CATEGORIES: dict[str, str] = {
    "JNJ": "healthcare",   # Johnson & Johnson
    "UNH": "healthcare",   # UnitedHealth Group
    "CAT": "industrials",  # Caterpillar
    "HON": "industrials",  # Honeywell
    "NEE": "utilities",    # NextEra Energy
    "APD": "materials",    # Air Products and Chemicals
    "DIS": "communication",  # Walt Disney
    "PLD": "real_estate",  # Prologis
    "BAC": "financials",   # Bank of America
    "PG": "consumer",      # Procter & Gamble
}

BACKTEST_CATEGORIES: dict[str, str] = {**SYMBOL_CATEGORIES, **NEW_SYMBOL_CATEGORIES}
BACKTEST_SYMBOLS: list[dict] = [
    {"symbol": symbol, "category": category, "source": "twelvedata"}
    for symbol, category in BACKTEST_CATEGORIES.items()
]

TECH_COUNT = sum(1 for c in BACKTEST_CATEGORIES.values() if c == "tech")
assert TECH_COUNT / len(BACKTEST_CATEGORIES) <= 0.5, "Tech weight must stay at or below 50%."

# --------------------------------------------------------------------------
# Assumptions (declared up front, not buried in code)
# --------------------------------------------------------------------------
STARTING_CAPITAL = 100_000.0
COMMISSION_PCT = 0.0005   # 5 bps of trade notional, each side (discount-broker level)
SLIPPAGE_PCT = 0.0005     # 5 bps adverse fill vs. the quoted open, each side
RATE_LIMIT_SLEEP_SECONDS = 8.0  # Twelve Data free tier: 8 requests/minute
INDICATOR_LOOKBACK_BARS = 400   # rolling window fed to evaluate(); EMA20/50, RSI14, ATR14 all
                                 # converge to the full-history value well within 400 bars, and
                                 # this keeps evaluate()'s own O(window) indicator recompute from
                                 # becoming O(n^2) over a 5-year, 20-symbol run. It does not
                                 # affect the no-lookahead guarantee: only past bars are ever used.
WARMUP_BARS = 60  # >50 so EMA50 has real data, not just its seed value


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_price_data(
    symbols: Sequence[dict], years: int, sleep_seconds: float = RATE_LIMIT_SLEEP_SECONDS
) -> dict[str, list[dict]]:
    """Fetch daily OHLCV history for each symbol from Twelve Data.

    Sequential with a fixed sleep between calls to stay under the free
    tier's 8 requests/minute. A symbol that fails to fetch (bad ticker,
    rate limit, no data) is skipped with a printed warning rather than
    aborting the whole run -- the report says which symbols made it in.
    """
    from alsatbotu.data import get_price_history

    calendar_days = 365 * years + 10  # pad for weekends/holidays
    data: dict[str, list[dict]] = {}
    for i, entry in enumerate(symbols):
        symbol = entry["symbol"]
        try:
            rows = get_price_history(symbol, source="twelvedata", days=calendar_days)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the run
            print(f"  {symbol}: FAILED to fetch ({exc}) -- excluded from results")
            continue
        if len(rows) < WARMUP_BARS + 20:
            print(f"  {symbol}: only {len(rows)} candles returned -- excluded (need warmup + room to trade)")
            continue
        print(f"  {symbol}: {len(rows)} candles, {rows[0]['timestamp'].date()} -> {rows[-1]['timestamp'].date()}")
        data[symbol] = rows
        if i < len(symbols) - 1:
            time.sleep(sleep_seconds)
    return data


def generate_synthetic_data(symbols: Sequence[dict], years: int, seed: int = 42) -> dict[str, list[dict]]:
    """Deterministic fake OHLCV data, for exercising the simulation code with no network.

    NOT real market data. Only ever written to an --out-dir the caller
    explicitly points away from backtest/results/, so a code smoke test can
    never be mistaken for a real backtest result.
    """
    rng = random.Random(seed)
    n = years * 252
    start = datetime(2021, 1, 4, tzinfo=timezone.utc)
    data: dict[str, list[dict]] = {}
    for entry in symbols:
        symbol = entry["symbol"]
        price = rng.uniform(50, 400)
        rows = []
        d = start
        # NOT hash(): Python string hash'i süreç başına rastgelelenir
        # (PYTHONHASHSEED), bu da "deterministik" veriyi süreçler arasında
        # yeniden üretilemez hale getiriyordu. crc32 sabit.
        sym_rng = random.Random(seed ^ zlib.crc32(symbol.encode("utf-8")))
        for _ in range(n):
            while d.weekday() >= 5:
                d += timedelta(days=1)
            drift = sym_rng.gauss(0.0004, 0.018)
            price = max(1.0, price * (1 + drift))
            high = price * (1 + abs(sym_rng.gauss(0, 0.006)))
            low = price * (1 - abs(sym_rng.gauss(0, 0.006)))
            open_ = low + (high - low) * sym_rng.random()
            volume = sym_rng.uniform(1_000_000, 5_000_000)
            rows.append(
                {
                    "timestamp": d,
                    "open": open_,
                    "high": max(high, open_, price),
                    "low": min(low, open_, price),
                    "close": price,
                    "volume": volume,
                }
            )
            d += timedelta(days=1)
        data[symbol] = rows
    return data


# --------------------------------------------------------------------------
# Cost model helpers
# --------------------------------------------------------------------------

def buy_fill_price(open_price: float) -> float:
    return open_price * (1 + SLIPPAGE_PCT)


def sell_fill_price(open_price: float) -> float:
    return open_price * (1 - SLIPPAGE_PCT)


def commission_for(notional: float) -> float:
    return abs(notional) * COMMISSION_PCT


# --------------------------------------------------------------------------
# Trade-tracking record (wraps portfolio.state.ClosedTrade with net-of-cost P&L)
# --------------------------------------------------------------------------

@dataclass
class NetTrade:
    symbol: str
    category: str
    entry_date: str
    exit_date: str
    entry_price: float  # fill price, i.e. after slippage
    exit_price: float
    quantity: float
    gross_pnl: float
    commission_paid: float
    net_pnl: float
    net_pnl_pct: float
    reason: str


@dataclass
class RejectedSignal:
    symbol: str
    date: str
    signal: str
    reasons: list[str]


@dataclass
class SimResult:
    equity_curve: list[tuple[str, float]]
    trades: list[NetTrade]
    rejected: list[RejectedSignal]
    open_positions_at_end: dict[str, dict]
    days_in_position: dict[str, int]
    window_start: str
    window_end: str
    # Simülasyon günlerinin her biri için "bugün drawdown halt aktif mi?"
    # (True = o gün yeni ALIM yasak). halt_sweep.py bunu kilitlenme
    # ölçümü için kullanır.
    halt_flags: list[bool] = field(default_factory=list)
    # (tarih, geçiş, açıklama) -- "halted" / "released" / "reset" / "stopped".
    halt_transitions: list[tuple[str, str, str]] = field(default_factory=list)
    halt_resets: int = 0
    stopped: bool = False
    stop_reason: Optional[str] = None


# --------------------------------------------------------------------------
# Core simulation: shared for the isolated per-symbol runs and the
# portfolio-wide run. `universe` controls which symbols share the state.
# --------------------------------------------------------------------------

def simulate(
    universe: Sequence[dict],
    price_data: dict[str, list[dict]],
    starting_capital: float,
    halt_policy: Optional[HaltPolicy] = None,
) -> SimResult:
    symbols = [e["symbol"] for e in universe if e["symbol"] in price_data]
    categories = {e["symbol"]: e["category"] for e in universe}
    rows_by_symbol = {s: price_data[s] for s in symbols}
    index_by_date: dict[str, dict[str, int]] = {}
    for s, rows in rows_by_symbol.items():
        for i, row in enumerate(rows):
            key = row["timestamp"].date().isoformat()
            index_by_date.setdefault(key, {})[s] = i

    all_dates = sorted(index_by_date.keys())
    # Only start once every symbol in the universe has its warmup history.
    first_ready: dict[str, str] = {}
    for s, rows in rows_by_symbol.items():
        if len(rows) > WARMUP_BARS:
            first_ready[s] = rows[WARMUP_BARS]["timestamp"].date().isoformat()
    if not first_ready:
        return SimResult([], [], [], {}, {}, "", "")
    start_date = max(first_ready.values())
    sim_dates = [d for d in all_dates if d >= start_date]
    if not sim_dates:
        return SimResult([], [], [], {}, {}, "", "")

    state = PortfolioState(cash=starting_capital, starting_capital=starting_capital, peak_equity=starting_capital)
    entry_commission: dict[str, float] = {}
    pending: dict[str, tuple[Signal, dict]] = {}  # symbol -> (signal, indicators at decision time)
    current_prices: dict[str, float] = {}
    trades: list[NetTrade] = []
    rejected: list[RejectedSignal] = []
    equity_curve: list[tuple[str, float]] = []
    halt_flags: list[bool] = []
    halt_transitions: list[tuple[str, str, str]] = []
    days_in_position: dict[str, int] = {s: 0 for s in symbols}

    for d in sim_dates:
        today_idx = index_by_date.get(d, {})

        # 1) Execute yesterday's decisions at today's open.
        for symbol, (signal, indicators) in list(pending.items()):
            if symbol not in today_idx:
                continue  # no bar today for this symbol; drop the stale order
            row = rows_by_symbol[symbol][today_idx[symbol]]
            open_price = row["open"]
            category = categories[symbol]

            if signal == Signal.BUY:
                if symbol in state.open_positions:
                    pending.pop(symbol, None)
                    continue
                fill = buy_fill_price(open_price)
                atr = indicators.get("atr")
                decision = evaluate_buy(state, symbol, category, fill, atr, current_prices)
                if not decision.approved:
                    rejected.append(RejectedSignal(symbol, d, "BUY", decision.reasons))
                else:
                    open_position(
                        state,
                        symbol=symbol,
                        category=category,
                        quantity=decision.quantity,
                        entry_price=fill,
                        entry_date=row["timestamp"].isoformat(),
                        stop_price=decision.stop_price,
                    )
                    fee = commission_for(decision.quantity * fill)
                    state.cash -= fee
                    entry_commission[symbol] = fee
            elif signal == Signal.SELL:
                if symbol not in state.open_positions:
                    pending.pop(symbol, None)
                    continue
                fill = sell_fill_price(open_price)
                position_qty = state.open_positions[symbol].quantity
                closed = close_position(
                    state,
                    symbol=symbol,
                    exit_price=fill,
                    exit_date=row["timestamp"].isoformat(),
                    reason="; ".join(indicators.get("reasons", [])) or "SELL signal",
                )
                if closed is not None:
                    fee = commission_for(position_qty * fill)
                    state.cash -= fee
                    total_fees = entry_commission.pop(symbol, 0.0) + fee
                    net_pnl = closed.pnl - total_fees
                    net_pct = net_pnl / (closed.entry_price * closed.quantity) if closed.entry_price else 0.0
                    trades.append(
                        NetTrade(
                            symbol=symbol,
                            category=category,
                            entry_date=closed.entry_date,
                            exit_date=closed.exit_date,
                            entry_price=closed.entry_price,
                            exit_price=closed.exit_price,
                            quantity=closed.quantity,
                            gross_pnl=closed.pnl,
                            commission_paid=total_fees,
                            net_pnl=net_pnl,
                            net_pnl_pct=net_pct,
                            reason=closed.reason,
                        )
                    )
            pending.pop(symbol, None)

        # 2) Mark prices, refresh equity/peak.
        for symbol, idx in today_idx.items():
            current_prices[symbol] = rows_by_symbol[symbol][idx]["close"]
        for symbol in state.open_positions:
            days_in_position[symbol] = days_in_position.get(symbol, 0) + 1
        # update_halt_state() peak'i de günceller ve halt durum makinesini
        # ilerletir; yarınki ALIM'lar bu işaretlemenin bıraktığı duruma bakar.
        halt_event = update_halt_state(state, current_prices, halt_policy, mark_date=d)
        equity = halt_event.equity
        equity_curve.append((d, equity))
        halt_flags.append(state.halted or state.stopped)
        if halt_event.transition:
            halt_transitions.append((d, halt_event.transition, halt_event.detail))

        # 3) Compute tomorrow's decisions from today's close (no lookahead:
        #    only rows up to and including index `idx` are ever passed in).
        for symbol, idx in today_idx.items():
            if idx + 1 < WARMUP_BARS:
                continue
            window_start_i = max(0, idx + 1 - INDICATOR_LOOKBACK_BARS)
            window = rows_by_symbol[symbol][window_start_i : idx + 1]
            if len(window) < 2:
                continue
            decision = evaluate(window)
            if decision.signal == Signal.HOLD:
                continue
            latest = add_indicators(window)[-1]
            pending[symbol] = (decision.signal, {"atr": latest.get("atr"), "reasons": decision.reasons})

    return SimResult(
        equity_curve=equity_curve,
        trades=trades,
        rejected=rejected,
        open_positions_at_end={s: vars(p) for s, p in state.open_positions.items()},
        days_in_position=days_in_position,
        window_start=sim_dates[0],
        window_end=sim_dates[-1],
        halt_flags=halt_flags,
        halt_transitions=halt_transitions,
        halt_resets=state.halt_resets,
        stopped=state.stopped,
        stop_reason=state.stop_reason,
    )


# --------------------------------------------------------------------------
# Buy-and-hold benchmarks (same cost model on entry, no rebalancing)
# --------------------------------------------------------------------------

def buy_and_hold(
    universe: Sequence[dict], price_data: dict[str, list[dict]], starting_capital: float
) -> tuple[list[tuple[str, float]], str, str]:
    symbols = [e["symbol"] for e in universe if e["symbol"] in price_data]
    if not symbols:
        return [], "", ""

    index_by_date: dict[str, dict[str, int]] = {}
    for s in symbols:
        for i, row in enumerate(price_data[s]):
            index_by_date.setdefault(row["timestamp"].date().isoformat(), {})[s] = i
    all_dates = sorted(index_by_date.keys())

    first_ready = {s: price_data[s][WARMUP_BARS]["timestamp"].date().isoformat() for s in symbols if len(price_data[s]) > WARMUP_BARS}
    if not first_ready:
        return [], "", ""
    start_date = max(first_ready.values())
    sim_dates = [d for d in all_dates if d >= start_date]
    if not sim_dates:
        return [], "", ""

    per_symbol_capital = starting_capital / len(symbols)
    shares: dict[str, float] = {}
    cash = 0.0
    entered = False
    curve: list[tuple[str, float]] = []

    for d in sim_dates:
        today_idx = index_by_date.get(d, {})
        if not entered:
            for s in symbols:
                if s not in today_idx:
                    continue
                open_price = price_data[s][today_idx[s]]["open"]
                fill = buy_fill_price(open_price)
                qty = per_symbol_capital / fill
                fee = commission_for(qty * fill)
                qty -= fee / fill  # fee eats into the position, no external cash injected
                shares[s] = qty
            entered = True
        value = 0.0
        for s in symbols:
            if s in today_idx:
                last_close = price_data[s][today_idx[s]]["close"]
            else:
                last_close = None
            if s in shares:
                px = last_close if last_close is not None else _last_known_close(price_data[s], d)
                value += shares[s] * (px or 0.0)
        curve.append((d, value + cash))

    return curve, sim_dates[0], sim_dates[-1]


def _last_known_close(rows: list[dict], on_or_before: str) -> Optional[float]:
    result = None
    for row in rows:
        key = row["timestamp"].date().isoformat()
        if key > on_or_before:
            break
        result = row["close"]
    return result


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

@dataclass
class Metrics:
    total_return_pct: Optional[float]
    cagr_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    sharpe: Optional[float]
    trade_count: int = 0
    hit_rate_pct: Optional[float] = None
    avg_win_loss_ratio: Optional[float] = None
    time_in_market_pct: Optional[float] = None


def compute_curve_metrics(curve: list[tuple[str, float]]) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if len(curve) < 2:
        return None, None, None, None
    values = [v for _, v in curve]
    total_return = values[-1] / values[0] - 1.0 if values[0] else None

    start = date.fromisoformat(curve[0][0])
    end = date.fromisoformat(curve[-1][0])
    years = max((end - start).days / 365.25, 1 / 365.25)
    cagr = (values[-1] / values[0]) ** (1 / years) - 1.0 if values[0] and values[-1] > 0 else None

    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            max_dd = min(max_dd, (v - peak) / peak)

    daily_returns = [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1]]
    if len(daily_returns) >= 2 and statistics.pstdev(daily_returns) > 0:
        sharpe = statistics.fmean(daily_returns) / statistics.pstdev(daily_returns) * (252 ** 0.5)
    else:
        sharpe = None

    return total_return, cagr, max_dd, sharpe


def compute_trade_metrics(trades: list[NetTrade]) -> tuple[int, Optional[float], Optional[float]]:
    if not trades:
        return 0, None, None
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    hit_rate = len(wins) / len(trades)
    if wins and losses:
        avg_win = statistics.fmean(t.net_pnl_pct for t in wins)
        avg_loss = statistics.fmean(t.net_pnl_pct for t in losses)
        ratio = avg_win / abs(avg_loss) if avg_loss else None
    else:
        ratio = None
    return len(trades), hit_rate, ratio


def strategy_metrics(sim: SimResult, symbols_in_window: int, total_days: int) -> Metrics:
    total_return, cagr, max_dd, sharpe = compute_curve_metrics(sim.equity_curve)
    trade_count, hit_rate, ratio = compute_trade_metrics(sim.trades)
    days_held = sum(sim.days_in_position.values())
    time_in_market = (days_held / (total_days * max(symbols_in_window, 1))) if total_days else None
    return Metrics(total_return, cagr, max_dd, sharpe, trade_count, hit_rate, ratio, time_in_market)


def bench_metrics(curve: list[tuple[str, float]]) -> Metrics:
    total_return, cagr, max_dd, sharpe = compute_curve_metrics(curve)
    return Metrics(total_return, cagr, max_dd, sharpe, trade_count=1, hit_rate_pct=None, avg_win_loss_ratio=None, time_in_market_pct=1.0 if curve else None)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def run(years: int, out_dir: Path, synthetic: bool = False) -> dict:
    print(f"Loading {len(BACKTEST_SYMBOLS)} symbols ({'synthetic' if synthetic else 'Twelve Data'}, {years}y)...")
    if synthetic:
        price_data = generate_synthetic_data(BACKTEST_SYMBOLS, years)
    else:
        price_data = load_price_data(BACKTEST_SYMBOLS, years)

    if not price_data:
        raise RuntimeError("No symbols returned usable data; nothing to backtest.")

    universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in price_data]
    per_symbol_capital = STARTING_CAPITAL / len(BACKTEST_SYMBOLS)

    print("\nRunning isolated per-symbol simulations...")
    per_symbol_results = {}
    for entry in universe:
        symbol = entry["symbol"]
        sim = simulate([entry], price_data, per_symbol_capital)
        bh_curve, bh_start, bh_end = buy_and_hold([entry], price_data, per_symbol_capital)
        total_days = len(sim.equity_curve)
        per_symbol_results[symbol] = {
            "category": entry["category"],
            "window": {"start": sim.window_start, "end": sim.window_end},
            "strategy": strategy_metrics(sim, 1, total_days),
            "buy_and_hold": bench_metrics(bh_curve),
            "strategy_equity_curve": sim.equity_curve,
            "buy_and_hold_equity_curve": bh_curve,
            "trades": sim.trades,
            "rejected_signals": sim.rejected,
        }
        print(f"  {symbol}: {len(sim.trades)} trades")

    print("\nRunning portfolio-wide (shared-cash, risk-engine-constrained) simulation...")
    portfolio_sim = simulate(universe, price_data, STARTING_CAPITAL)
    portfolio_bh_curve, _, _ = buy_and_hold(universe, price_data, STARTING_CAPITAL)
    portfolio_results = {
        "window": {"start": portfolio_sim.window_start, "end": portfolio_sim.window_end},
        "strategy": strategy_metrics(portfolio_sim, len(universe), len(portfolio_sim.equity_curve)),
        "buy_and_hold": bench_metrics(portfolio_bh_curve),
        "strategy_equity_curve": portfolio_sim.equity_curve,
        "buy_and_hold_equity_curve": portfolio_bh_curve,
        "trades": portfolio_sim.trades,
        "rejected_signals": portfolio_sim.rejected,
    }
    print(f"  Portfolio: {len(portfolio_sim.trades)} trades, {len(portfolio_sim.rejected)} rejected signals")

    return {
        "per_symbol": per_symbol_results,
        "portfolio": portfolio_results,
        "excluded_symbols": [e["symbol"] for e in BACKTEST_SYMBOLS if e["symbol"] not in price_data],
    }


# --------------------------------------------------------------------------
# Output writers
# --------------------------------------------------------------------------

def _metrics_dict(m: Metrics) -> dict:
    return {
        "total_return_pct": m.total_return_pct,
        "cagr_pct": m.cagr_pct,
        "max_drawdown_pct": m.max_drawdown_pct,
        "sharpe": m.sharpe,
        "trade_count": m.trade_count,
        "hit_rate_pct": m.hit_rate_pct,
        "avg_win_loss_ratio": m.avg_win_loss_ratio,
        "time_in_market_pct": m.time_in_market_pct,
    }


def write_json(results: dict, path: Path) -> None:
    def default(obj):
        if isinstance(obj, Metrics):
            return _metrics_dict(obj)
        if isinstance(obj, (NetTrade, RejectedSignal)):
            return vars(obj)
        raise TypeError(f"Not JSON serializable: {type(obj)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "assumptions": {
                    "starting_capital": STARTING_CAPITAL,
                    "commission_pct_per_side": COMMISSION_PCT,
                    "slippage_pct_per_side": SLIPPAGE_PCT,
                    "execution": "signal on day T close, filled at day T+1 open",
                    "indicator_lookback_bars": INDICATOR_LOOKBACK_BARS,
                    "survivorship_bias_note": (
                        "Universe is today's still-listed large caps, not a point-in-time "
                        "index reconstruction; see module docstring."
                    ),
                },
                **results,
            },
            f,
            default=default,
            indent=2,
        )
        f.write("\n")


def write_csv(results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol", "category",
                "strategy_total_return_pct", "strategy_cagr_pct", "strategy_max_drawdown_pct", "strategy_sharpe",
                "strategy_trade_count", "strategy_hit_rate_pct", "strategy_avg_win_loss_ratio", "strategy_time_in_market_pct",
                "bh_total_return_pct", "bh_cagr_pct", "bh_max_drawdown_pct", "bh_sharpe",
                "beat_buy_and_hold",
            ]
        )
        for symbol, r in results["per_symbol"].items():
            s, b = r["strategy"], r["buy_and_hold"]
            beat = (
                s.total_return_pct is not None
                and b.total_return_pct is not None
                and s.total_return_pct > b.total_return_pct
            )
            writer.writerow(
                [
                    symbol, r["category"],
                    s.total_return_pct, s.cagr_pct, s.max_drawdown_pct, s.sharpe,
                    s.trade_count, s.hit_rate_pct, s.avg_win_loss_ratio, s.time_in_market_pct,
                    b.total_return_pct, b.cagr_pct, b.max_drawdown_pct, b.sharpe,
                    beat,
                ]
            )


def _pct(v: Optional[float], digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "N/A"


def _num(v: Optional[float], digits: int = 2) -> str:
    return f"{v:.{digits}f}" if v is not None else "N/A"


def write_markdown(results: dict, path: Path) -> None:
    lines: list[str] = []
    lines.append("# Backtest: Kural Motoru vs. Al-ve-Tut")
    lines.append("")
    lines.append(f"Üretim zamanı: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    lines.append("")
    lines.append("## Varsayımlar")
    lines.append("")
    lines.append(f"- Başlangıç sermayesi: ${STARTING_CAPITAL:,.0f} (portföy genelinde), ${STARTING_CAPITAL / len(BACKTEST_SYMBOLS):,.0f} (izole sembol başına)")
    lines.append(f"- Komisyon: işlem tutarının %{COMMISSION_PCT * 100:.2f}'i, her taraf için (giriş ve çıkışta ayrı ayrı)")
    lines.append(f"- Slipaj: kotalanan açılış fiyatına göre %{SLIPPAGE_PCT * 100:.2f} aleyhte kayma, her taraf için")
    lines.append("- Yürütme: sinyal T günü kapanışıyla hesaplanır, T+1 günü açılışında işleme girilir (look-ahead yok)")
    lines.append("- Al-ve-tut karşılaştırması da aynı giriş komisyonu/slipajını öder (adil karşılaştırma)")
    lines.append("")
    lines.append("## Survivorship bias uyarısı")
    lines.append("")
    lines.append(
        "20 sembolün tamamı bugün hâlâ işlem gören, onlarca yıldır listede olan büyük "
        "şirketler. Bu, herhangi bir tarihe ait gerçek endeks bileşen listesinin yeniden "
        "inşası değil. 5 yıllık pencerede bu hafif bir önyargıdır (bu isimlerden hiçbiri "
        "2021-2026 arasında delisting/iflas riski taşımıyordu), ama sonuçlar \"piyasanın "
        "tamamına uygulanan tarafsız bir tahmin\" değil, \"bugünün mavi çipleri üzerinde bu "
        "kural setinin nasıl performans gösterdiği\" olarak okunmalı."
    )
    lines.append("")
    if results["excluded_symbols"]:
        lines.append(f"**Veri alınamayan/yetersiz semboller (analiz dışı):** {', '.join(results['excluded_symbols'])}")
        lines.append("")

    port = results["portfolio"]
    s, b = port["strategy"], port["buy_and_hold"]
    verdict = "EVET, yeniyor" if (s.total_return_pct or 0) > (b.total_return_pct or 0) else "HAYIR, yenmiyor"
    lines.append("## Sonuç: Strateji al-ve-tut'u yeniyor mu?")
    lines.append("")
    lines.append(f"**Portföy genelinde: {verdict}.**")
    lines.append(
        f"Strateji toplam getiri {_pct(s.total_return_pct)} (CAGR {_pct(s.cagr_pct)}, Sharpe {_num(s.sharpe)}) "
        f"vs. eşit ağırlıklı al-ve-tut {_pct(b.total_return_pct)} (CAGR {_pct(b.cagr_pct)}, Sharpe {_num(b.sharpe)})."
    )
    lines.append("")

    lines.append("## Portföy Genelinde (paylaşılan sermaye, risk motoru kısıtlarıyla)")
    lines.append("")
    lines.append(f"Pencere: {port['window']['start']} → {port['window']['end']}")
    lines.append("")
    lines.append("| Metrik | Strateji | Al-ve-Tut |")
    lines.append("|---|---|---|")
    lines.append(f"| Toplam Getiri | {_pct(s.total_return_pct)} | {_pct(b.total_return_pct)} |")
    lines.append(f"| CAGR | {_pct(s.cagr_pct)} | {_pct(b.cagr_pct)} |")
    lines.append(f"| Maks. Drawdown | {_pct(s.max_drawdown_pct)} | {_pct(b.max_drawdown_pct)} |")
    lines.append(f"| Sharpe | {_num(s.sharpe)} | {_num(b.sharpe)} |")
    lines.append(f"| İşlem Sayısı | {s.trade_count} | {b.trade_count} |")
    lines.append(f"| İsabet Oranı | {_pct(s.hit_rate_pct, 1) if s.hit_rate_pct is not None else 'N/A'} | — |")
    lines.append(f"| Ort. Kazanç/Kayıp Oranı | {_num(s.avg_win_loss_ratio)} | — |")
    lines.append(f"| Piyasada Kalma Oranı | {_pct(s.time_in_market_pct, 1) if s.time_in_market_pct is not None else 'N/A'} | {_pct(b.time_in_market_pct, 1)} |")
    lines.append(f"| Reddedilen Sinyal Sayısı (kısıtlar nedeniyle) | {len(port['rejected_signals'])} | — |")
    lines.append("")

    lines.append("## Sembol Başına (izole hesap, portföy kısıtları paylaşılmıyor)")
    lines.append("")
    lines.append("| Sembol | Kategori | Strat. Getiri | B&H Getiri | Strat. CAGR | B&H CAGR | Strat. DD | B&H DD | Strat. Sharpe | B&H Sharpe | İşlem | İsabet | Yener mi? |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for symbol, r in sorted(results["per_symbol"].items()):
        ss, sb = r["strategy"], r["buy_and_hold"]
        beats = ss.total_return_pct is not None and sb.total_return_pct is not None and ss.total_return_pct > sb.total_return_pct
        lines.append(
            f"| {symbol} | {r['category']} | {_pct(ss.total_return_pct)} | {_pct(sb.total_return_pct)} | "
            f"{_pct(ss.cagr_pct)} | {_pct(sb.cagr_pct)} | {_pct(ss.max_drawdown_pct)} | {_pct(sb.max_drawdown_pct)} | "
            f"{_num(ss.sharpe)} | {_num(sb.sharpe)} | {ss.trade_count} | "
            f"{_pct(ss.hit_rate_pct, 1) if ss.hit_rate_pct is not None else 'N/A'} | {'✅' if beats else '❌'} |"
        )
    lines.append("")

    beat_count = sum(
        1
        for r in results["per_symbol"].values()
        if r["strategy"].total_return_pct is not None
        and r["buy_and_hold"].total_return_pct is not None
        and r["strategy"].total_return_pct > r["buy_and_hold"].total_return_pct
    )
    lines.append(f"Al-ve-tut'u yenen sembol sayısı: {beat_count} / {len(results['per_symbol'])}")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_dashboard_json(results: dict, path: Path) -> None:
    """Panel-friendly shape: dense metrics + {date,value} equity curves, no dataclasses."""

    def curve_points(curve: list[tuple[str, float]]) -> list[dict]:
        return [{"date": d, "value": v} for d, v in curve]

    def trade_dicts(trades: list[NetTrade]) -> list[dict]:
        return [vars(t) for t in trades]

    port = results["portfolio"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "assumptions": {
            "starting_capital": STARTING_CAPITAL,
            "commission_pct_per_side": COMMISSION_PCT,
            "slippage_pct_per_side": SLIPPAGE_PCT,
        },
        "excluded_symbols": results["excluded_symbols"],
        "portfolio": {
            "window": port["window"],
            "strategy": {**_metrics_dict(port["strategy"]), "equity_curve": curve_points(port["strategy_equity_curve"])},
            "buy_and_hold": {**_metrics_dict(port["buy_and_hold"]), "equity_curve": curve_points(port["buy_and_hold_equity_curve"])},
            "rejected_signal_count": len(port["rejected_signals"]),
        },
        "symbols": {
            symbol: {
                "category": r["category"],
                "window": r["window"],
                "strategy": {**_metrics_dict(r["strategy"]), "equity_curve": curve_points(r["strategy_equity_curve"])},
                "buy_and_hold": {**_metrics_dict(r["buy_and_hold"]), "equity_curve": curve_points(r["buy_and_hold_equity_curve"])},
                "trades": trade_dicts(r["trades"]),
            }
            for symbol, r in results["per_symbol"].items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def main(years: int, out_dir: str, synthetic: bool) -> None:
    out = Path(out_dir)
    results = run(years, out, synthetic=synthetic)
    write_json(results, out / "results.json")
    write_csv(results, out / "results.csv")
    write_markdown(results, out / "summary.md")
    write_dashboard_json(results, out / "dashboard.json")
    print(f"\nWrote results to {out}/ (results.json, results.csv, summary.md, dashboard.json)")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--out-dir", default="backtest/results")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data instead of Twelve Data (code smoke test only)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    main(args.years, args.out_dir, args.synthetic)
