"""Tests for the backtest-only breakout architecture (backtest/breakout_backtest.py)."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from alsatbotu.indicators import atr, ema, rsi
from backtest.breakout_backtest import (
    ARM_TP_SPLIT,
    ARM_TRAIL_ONLY,
    DEFAULT_PARAMS,
    EVENT_BREAKOUT,
    EVENT_EXPIRED,
    EVENT_FILTER_BROKEN,
    EVENT_REGISTERED,
    NO_HALT_POLICY,
    CandidateTracker,
    TradeStat,
    compute_arm_metrics,
    copy_matches_original,
    period_metrics,
    simulate_current,
    slice_curve,
    breakout_margin,
    breakout_ok,
    end_of_bar_update,
    new_trade,
    prepare_series,
    prior_window_max,
    prior_window_mean,
    process_bar,
    simulate_breakout,
    truncate_data,
)
from backtest.portfolio_backtest import generate_synthetic_data, simulate

P = DEFAULT_PARAMS


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# --------------------------------------------------------------------------
# Lookahead: kırılma seviyesi, hacim ortalaması, göstergeler
# --------------------------------------------------------------------------

def test_prior_window_max_excludes_current_bar():
    highs = [1, 2, 3, 4, 100]
    out = prior_window_max(highs, 3)
    assert out[:3] == [None, None, None]
    assert out[3] == 3          # max(1,2,3), 4 dahil değil
    assert out[4] == 4          # max(2,3,4), bugünkü 100 dahil değil


def test_prior_window_mean_excludes_current_bar():
    vols = [10, 20, 30, 1000]
    assert prior_window_mean(vols, 3)[3] == 20


def _rows(n: int, seed: int = 1, volume: bool = True) -> list[dict]:
    rng = random.Random(seed)
    price = 100.0
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        price *= 1 + rng.gauss(0.0005, 0.015)
        hi = price * (1 + abs(rng.gauss(0, 0.005)))
        lo = price * (1 - abs(rng.gauss(0, 0.005)))
        row = {"timestamp": t0 + timedelta(days=i), "open": (hi + lo) / 2, "high": hi, "low": lo, "close": price}
        if volume:
            row["volume"] = rng.uniform(1e6, 2e6)
        rows.append(row)
    return rows


def test_indicators_are_causal_truncation_invariant():
    """Tüm seride bir kez hesaplanan gösterge, kesik seride hesaplananla aynı olmalı."""
    rows = _rows(200)
    full = prepare_series(rows)
    for cut in (60, 99, 150):
        part = prepare_series(rows[: cut + 1])
        for name in ("ema_fast", "ema_slow", "rsi", "atr", "prior_high", "prior_volume_avg"):
            a, b = getattr(full, name)[cut], getattr(part, name)[cut]
            assert a is not None and b is not None and close(a, b), (name, cut, a, b)


def test_breakout_level_ignores_todays_high():
    rows = _rows(80)
    base = prepare_series(rows)
    rows2 = [dict(r) for r in rows]
    rows2[70]["high"] = 10_000.0
    changed = prepare_series(rows2)
    assert changed.prior_high[70] == base.prior_high[70]
    assert changed.prior_high[71] == 10_000.0  # ertesi gün "önceki 20 bar"a girer


def _series_with_breakout(volume: bool, today_volume: float = 5e6):
    rows = _rows(80, volume=volume)
    s = prepare_series(rows)
    i = 79
    level = s.prior_high[i]
    rows[i]["close"] = level + 0.2 * s.atr[i]  # 0.1 ATR ile 0.3 ATR marjı arasında
    rows[i]["high"] = max(rows[i]["high"], rows[i]["close"])
    if volume:
        rows[i]["volume"] = today_volume
    s = prepare_series(rows)
    return s, i


def test_margin_depends_on_volume_availability():
    s_vol, i = _series_with_breakout(volume=True)
    s_novol, j = _series_with_breakout(volume=False)
    assert close(breakout_margin(s_vol, i), 0.1 * s_vol.atr[i])
    assert close(breakout_margin(s_novol, j), 0.3 * s_novol.atr[j])
    # Close = seviye + 0.2 ATR: hacimli sembolde geçer, hacimsizde geçmez.
    assert breakout_ok(s_vol, i) is True
    assert breakout_ok(s_novol, j) is False


def test_volume_confirmation_required_when_volume_exists():
    s, i = _series_with_breakout(volume=True, today_volume=1.0)
    assert breakout_ok(s, i) is False
    avg = s.prior_volume_avg[i]
    s2, _ = _series_with_breakout(volume=True, today_volume=1.21 * avg)
    assert breakout_ok(s2, i) is True


# --------------------------------------------------------------------------
# Aday durum makinesi
# --------------------------------------------------------------------------

def test_candidate_cannot_break_out_on_registration_bar():
    tr = CandidateTracker(ttl=7)
    assert tr.on_close(0, "d0", True, True, False) == EVENT_REGISTERED
    assert tr.on_close(1, "d1", True, True, False) == EVENT_BREAKOUT


def test_candidate_expires_after_seven_trading_days():
    tr = CandidateTracker(ttl=7)
    assert tr.on_close(10, "d", True, False, False) == EVENT_REGISTERED
    for i in range(11, 17):
        assert tr.on_close(i, "d", True, False, False) is None
    assert tr.on_close(17, "d", True, False, False) == EVENT_EXPIRED
    # Filtre hâlâ tutuyor ama sıfırlanmadan yeniden aday olamaz.
    assert tr.on_close(18, "d", True, False, False) is None
    assert tr.on_close(19, "d", False, False, False) is None
    assert tr.on_close(20, "d", True, False, False) == EVENT_REGISTERED


def test_breakout_on_seventh_day_still_counts():
    tr = CandidateTracker(ttl=7)
    tr.on_close(0, "d", True, False, False)
    for i in range(1, 7):
        tr.on_close(i, "d", True, False, False)
    assert tr.on_close(7, "d", True, True, False) == EVENT_BREAKOUT


def test_filter_break_drops_candidate_regardless_of_age():
    tr = CandidateTracker(ttl=7)
    tr.on_close(0, "d", True, False, False)
    assert tr.on_close(1, "d", False, False, False) == EVENT_FILTER_BROKEN
    assert tr.on_close(2, "d", True, False, False) == EVENT_REGISTERED  # hemen yeniden aday olabilir


def test_breakout_is_checked_before_filter_on_same_bar():
    """Kırılma günü RSI 70'i aşsa bile (filtre False) kırılma sayılır."""
    tr = CandidateTracker(ttl=7)
    tr.on_close(0, "d", True, False, False)
    assert tr.on_close(1, "d", False, True, False) == EVENT_BREAKOUT


def test_blocked_symbol_is_not_tracked():
    tr = CandidateTracker(ttl=7)
    assert tr.on_close(0, "d", True, True, True) is None
    assert not tr.active
    assert tr.counts[EVENT_REGISTERED] == 0


# --------------------------------------------------------------------------
# Gün içi çıkışlar ve stop/TP sıralaması
# --------------------------------------------------------------------------

def _trade(arm: str = ARM_TP_SPLIT):
    # Entry 100, ATR 2 -> stop 97, R 3, TP1 104.5, TP2 109
    return new_trade("X", "tech", arm, "d0", "d1", 100.0, 10.0, 2.0)


def test_position_levels():
    t = _trade()
    assert close(t.initial_stop, 97.0)
    assert close(t.r_per_share, 3.0)
    assert close(t.tp1, 104.5)
    assert close(t.tp2, 109.0)


def test_same_bar_stop_and_tp1_assumes_stop_first():
    t = _trade()
    orders = process_bar(t, o=100.0, h=105.0, l=96.0)
    assert len(orders) == 1
    assert orders[0].portion == "rest" and close(orders[0].price, 97.0) and orders[0].market
    assert orders[0].reason == "initial_stop_ambiguous"
    assert t.ambiguous_bars == 1 and not t.tp1_done


def test_tp1_intrabar_sells_half_and_new_stop_waits_for_next_bar():
    t = _trade()
    # Low 99 < Entry+0.2ATR (100.4) ama yeni stop bu barda henüz aktif değil.
    orders = process_bar(t, o=100.0, h=105.0, l=99.0)
    assert [(o.portion, o.price, o.market) for o in orders] == [("tp1", 104.5, False)]
    assert t.tp1_done and close(t.stop, 97.0)
    end_of_bar_update(t, close=104.0, atr_now=2.0)
    assert close(t.stop, 100.4)  # max(entry+0.2ATR, 104-4=100)
    orders = process_bar(t, o=101.0, h=101.5, l=100.0)
    assert [(o.portion, round(o.price, 6), o.reason) for o in orders] == [("rest", 100.4, "breakeven_stop")]


def test_tp1_and_tp2_same_bar():
    t = _trade()
    orders = process_bar(t, o=100.0, h=110.0, l=99.0)
    assert [(o.portion, o.price) for o in orders] == [("tp1", 104.5), ("rest", 109.0)]


def test_gap_down_below_stop_fills_at_open():
    t = _trade()
    orders = process_bar(t, o=95.0, h=96.0, l=94.0)
    assert [(o.portion, o.price, o.reason) for o in orders] == [("rest", 95.0, "stop_gap")]


def test_gap_up_above_tp1_fills_at_open():
    t = _trade()
    orders = process_bar(t, o=106.0, h=107.0, l=96.0)  # low stop'un altında olsa bile açılış önce
    assert [(o.portion, o.price, o.reason) for o in orders] == [("tp1", 106.0, "tp1_gap")]


def test_post_tp1_same_bar_stop_and_tp2_assumes_stop():
    t = _trade()
    process_bar(t, o=100.0, h=105.0, l=99.0)
    end_of_bar_update(t, close=104.0, atr_now=2.0)
    orders = process_bar(t, o=104.0, h=110.0, l=100.0)
    assert len(orders) == 1 and close(orders[0].price, t.stop) and orders[0].reason.endswith("_ambiguous")


def test_trailing_stop_never_decreases_and_follows_highest_close():
    t = _trade(ARM_TRAIL_ONLY)
    end_of_bar_update(t, close=100.0, atr_now=2.0)
    assert close(t.stop, 97.0)  # 100-4=96 < initial 97
    end_of_bar_update(t, close=110.0, atr_now=2.0)
    assert close(t.stop, 106.0)
    end_of_bar_update(t, close=105.0, atr_now=5.0)  # ATR genişlese de stop inmez
    assert close(t.stop, 106.0)


def test_arm_b_has_no_trailing_before_tp1():
    t = _trade()
    end_of_bar_update(t, close=104.0, atr_now=0.5)
    assert close(t.stop, 97.0)


def test_arm_a_never_takes_profit():
    t = _trade(ARM_TRAIL_ONLY)
    assert process_bar(t, o=100.0, h=200.0, l=99.0) == []


# --------------------------------------------------------------------------
# Portföy simülasyonu
# --------------------------------------------------------------------------

UNIVERSE = [
    {"symbol": "AAPL", "category": "tech"},
    {"symbol": "JPM", "category": "financials"},
    {"symbol": "XOM", "category": "energy"},
    {"symbol": "KO", "category": "consumer"},
]


def _data():
    return generate_synthetic_data(UNIVERSE, years=4, seed=7)


def test_simulation_produces_trades_with_correct_sizing_and_partial_exits():
    data = _data()
    for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        sim = simulate_breakout(UNIVERSE, data, 100_000.0, arm)
        assert sim.trades, arm
        for t in sim.trades:
            assert close(t.entry_price - t.initial_stop, 1.5 * t.atr_entry)
            equity_at_entry = dict(sim.equity_curve).get(t.entry_date, max(v for _, v in sim.equity_curve))
            # %15 tahsis tavanı: giriş, önceki kapanış equity'si üzerinden boyutlanır.
            assert t.entry_price * t.quantity <= 0.15 * max(v for _, v in sim.equity_curve) + 1e-6, equity_at_entry
            assert close(sum(f["quantity"] for f in t.fills), t.quantity)
            assert t.entry_date > t.signal_date
            if arm == ARM_TRAIL_ONLY:
                assert not t.tp1_hit and len(t.fills) == 1
        f = sim.funnel
        assert f.candidates == f.breakouts + f.expired + f.filter_broken + f.candidates_open_at_end
        # Son gün kapanışındaki kırılmalar ertesi gün olmadığı için bekleyen emir olarak kalır.
        pending_at_end = sum(1 for d, _, e in sim.events if e == EVENT_BREAKOUT and d == sim.window_end)
        assert f.breakouts == f.entries_executed + f.entries_rejected + f.entries_no_bar + pending_at_end


def test_tp1_partial_exit_sells_half():
    data = _data()
    sim = simulate_breakout(UNIVERSE, data, 100_000.0, ARM_TP_SPLIT)
    tp1_trades = [t for t in sim.trades if t.tp1_hit]
    assert tp1_trades
    for t in tp1_trades:
        first = t.fills[0]
        assert first["reason"].startswith("tp1")
        assert close(first["quantity"], 0.5 * t.quantity)


def test_future_bars_do_not_change_past_decisions():
    """Kesim tarihinden sonraki barları boz; kesime kadar her şey aynı kalmalı."""
    data = _data()
    dates = sorted({r["timestamp"].date().isoformat() for rows in data.values() for r in rows})
    cutoff = dates[len(dates) * 2 // 3]
    rng = random.Random(99)
    garbled = {}
    for s, rows in data.items():
        out = []
        for r in rows:
            r = dict(r)
            if r["timestamp"].date().isoformat() > cutoff:
                k = rng.uniform(0.3, 3.0)
                for key in ("open", "high", "low", "close"):
                    r[key] *= k
                r["volume"] *= rng.uniform(0.1, 10)
            out.append(r)
        garbled[s] = out
    for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        a = simulate_breakout(UNIVERSE, data, 100_000.0, arm)
        b = simulate_breakout(UNIVERSE, garbled, 100_000.0, arm)
        assert [x for x in a.equity_curve if x[0] <= cutoff] == [x for x in b.equity_curve if x[0] <= cutoff]
        assert [e for e in a.events if e[0] <= cutoff] == [e for e in b.events if e[0] <= cutoff]
        key = lambda t: (t.symbol, t.entry_date, t.exit_date, t.net_pnl)
        assert [key(t) for t in a.trades if t.exit_date <= cutoff] == [key(t) for t in b.trades if t.exit_date <= cutoff]


def test_truncated_run_matches_full_run_up_to_cutoff():
    data = _data()
    dates = sorted({r["timestamp"].date().isoformat() for rows in data.values() for r in rows})
    cutoff = dates[len(dates) // 2]
    full = simulate_breakout(UNIVERSE, data, 100_000.0, ARM_TP_SPLIT)
    part = simulate_breakout(UNIVERSE, truncate_data(data, cutoff), 100_000.0, ARM_TP_SPLIT)
    assert [x for x in full.equity_curve if x[0] <= cutoff] == part.equity_curve


def test_no_halt_policy_never_halts():
    data = _data()
    sim = simulate_breakout(UNIVERSE[:1], data, 5_000.0, ARM_TP_SPLIT, halt_policy=NO_HALT_POLICY)
    assert all("halt" not in " ".join(r.reasons).lower() for r in sim.rejected)


# --------------------------------------------------------------------------
# C / C-stop
# --------------------------------------------------------------------------

def test_current_copy_matches_portfolio_backtest_simulate():
    """Stop kapalıyken kopya, portfolio_backtest.simulate ile birebir aynı."""
    data = _data()
    original = simulate(UNIVERSE, data, 100_000.0)
    copy = simulate_current(UNIVERSE, data, 100_000.0, enforce_stop=False)
    assert original.trades
    assert copy_matches_original(original, copy)


def test_current_stop_exits_when_close_below_entry_stop():
    data = _data()
    sim = simulate_current(UNIVERSE, data, 100_000.0, enforce_stop=True)
    stops = [t for t in sim.trades if t.reason.startswith("stop_loss")]
    assert stops
    for t in sim.trades:
        assert t.risk_usd > 0 and t.stop_price < t.entry_price
    rows = {s: {r["timestamp"].date().isoformat(): r for r in rs} for s, rs in data.items()}
    for t in stops:
        dates = sorted(d for d in rows[t.symbol] if d < t.exit_date[:10])
        # Karar günü (çıkıştan önceki bar) kapanışı stop'un altında; dolum ertesi açılışta.
        assert rows[t.symbol][dates[-1]]["close"] <= t.stop_price
        assert close(t.exit_price, rows[t.symbol][t.exit_date[:10]]["open"] * (1 - 0.0005))


def test_stopless_c_never_honours_entry_stop():
    """Belgelenen bulgu: C, kapanış stop'un altındayken bile SELL sinyali gelmedikçe tutar."""
    data = _data()
    sim = simulate_current(UNIVERSE, data, 100_000.0, enforce_stop=False)
    assert not any(t.reason.startswith("stop_loss") for t in sim.trades)


# --------------------------------------------------------------------------
# Exposure ve dönem dilimleri
# --------------------------------------------------------------------------

def test_exposure_metrics():
    curve = [("2020-01-01", 100.0), ("2020-01-02", 110.0), ("2020-01-03", 121.0)]
    exposure = [("2020-01-01", 0.0), ("2020-01-02", 0.5), ("2020-01-03", 1.0)]
    m = compute_arm_metrics("X", curve, [], None, exposure)
    assert close(m.avg_exposure, 0.5)
    assert close(m.days_in_market, 2 / 3)
    assert close(m.exposure_adj_cagr, m.cagr / 0.5)


def test_exposure_recorded_for_all_sims_and_bounded():
    data = _data()
    sims = [
        simulate_breakout(UNIVERSE, data, 100_000.0, ARM_TP_SPLIT),
        simulate_current(UNIVERSE, data, 100_000.0, enforce_stop=True),
    ]
    for sim in sims:
        assert len(sim.exposure) == len(sim.equity_curve)
        assert all(0.0 <= v <= 1.0 + 1e-9 for _, v in sim.exposure)
        assert any(v > 0 for _, v in sim.exposure)


def test_slice_curve_uses_previous_close_as_base():
    curve = [("2019-12-30", 100.0), ("2019-12-31", 100.0), ("2020-01-02", 110.0), ("2020-01-03", 121.0)]
    assert slice_curve(curve, "2020-01-01", "9999-12-31") == [("2019-12-31", 100.0), ("2020-01-02", 110.0), ("2020-01-03", 121.0)]
    assert slice_curve(curve, "0000-00-00", "2019-12-31") == curve[:2]


def test_period_metrics_assign_trades_by_exit_date():
    curve = [("2019-12-31", 100.0), ("2020-01-02", 110.0)]
    stats = [
        TradeStat("X", "2019-12-01", "2019-12-20", 5.0, 0.05, 10),
        TradeStat("Y", "2019-12-15", "2020-01-02", -2.0, -0.02, 5),
    ]
    early = period_metrics("A", curve, None, stats, "0000-00-00", "2019-12-31")
    late = period_metrics("A", curve, None, stats, "2020-01-01", "9999-12-31")
    assert early.trade_count == 1 and early.net_pnl_total == 5.0
    assert late.trade_count == 1 and late.net_pnl_total == -2.0
    assert close(late.total_return, 0.10)


def test_breakout_trade_cost_in_r_is_positive_and_consistent():
    data = _data()
    sim = simulate_breakout(UNIVERSE, data, 100_000.0, ARM_TP_SPLIT)
    for t in sim.trades:
        assert t.risk_usd > 0
        assert t.slippage_paid > 0  # giriş her zaman açılışta, kayma öder
        assert close(t.risk_usd, (t.entry_price - t.initial_stop) * t.quantity)
