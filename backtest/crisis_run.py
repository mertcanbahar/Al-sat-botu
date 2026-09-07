#!/usr/bin/env python3
"""Kriz dönemi koşusu: 2008 + 2020 çöküşlerinde drawdown halt kolları.

Soru
----
Önceki süpürmeler (bkz. `backtest/halt_threshold_findings.md`) sakin,
birbirinden bağımsız rastgele yürüyüşler üzerinde koşuldu. Orada portföy
düzeyinde halt neredeyse hiç tetiklenmedi -- yani ölçülen şey kuralın
krizdeki davranışı değil, verinin sakinliğiydi. Bu koşu tam olarak o
boşluğu kapatır: veri, ortak bir piyasa faktörüyle 2008 (GFC, ~-55%) ve
2020 (COVID, 23 işlem gününde ~-34%) çöküşlerini içerecek şekilde
üretilir (`backtest/crisis_data.py`), böylece halt'ın tetiklenmemesi
mümkün değildir.

Karşılaştırılan üç kol
----------------------
1. **legacy %20** -- bugünkü canlı davranış: her gün anlık hesap,
   `engine.risk.is_drawdown_halted()`, kalıcı durum yok.
2. **v1** -- geri alınmış histerezisli durum makinesi (H%20 → R%10,
   60 işaretleme sonra kısmi peak reset'i × 0.5, en fazla 2 reset,
   sert taban %50).
3. **v1 taban%30** -- aynı v1, sert tabanı %50 yerine %30: bot çöküşün
   daha derinine kadar çalışır, kalıcı durdurma daha geç gelir.

Her kol hem portföy geneli (paylaşılan sermaye) hem de 20 izole tek-sembol
hesabı için koşulur ve birden çok tohumda tekrarlanır (medyan + aralık).
Durum makinesinin her geçişi tarih/equity/peak/drawdown ile loglanır.

Kullanım:
    python backtest/crisis_run.py                       # sentetik kriz senaryosu
    python backtest/crisis_run.py --seeds 1 2 7 42 101
    python backtest/crisis_run.py --real --years 17     # TWELVEDATA_API_KEY ister

Sentetik çıktı `backtest/results/` köküne yazılmaz (gerçek backtest
sonuçlarıyla karışmasın diye); varsayılan hedef `results/synthetic/crisis/`.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.crisis_data import (  # noqa: E402
    CRISIS_REGIMES,
    CRISIS_WINDOWS,
    equal_weight_index,
    generate_crisis_data,
    window_drawdown,
)
from backtest.halt_policy import (  # noqa: E402
    V1,
    V1_FLOOR30,
    HaltController,
    HaltPolicy,
)
from backtest.portfolio_backtest import (  # noqa: E402
    BACKTEST_SYMBOLS,
    STARTING_CAPITAL,
    SimResult,
    compute_curve_metrics,
    compute_trade_metrics,
    load_price_data,
    simulate,
)

HALT_REASON_PREFIX = "Drawdown halt"
DEFAULT_SEEDS = [1, 2, 7, 42, 101]

# Kollar: (etiket, görünen ad, politika ya da None=canlı mandal, eşik)
ARMS: list[tuple[str, str, Optional[HaltPolicy], Optional[float]]] = [
    ("legacy20", "legacy %20", None, 0.20),
    ("v1", "v1", V1, None),
    ("v1_floor30", "v1 taban%30", V1_FLOOR30, None),
]
ARM_LABELS = {key: label for key, label, _, _ in ARMS}


# --------------------------------------------------------------------------
# Tek bir hesabın halt istatistikleri
# --------------------------------------------------------------------------

@dataclass
class HaltStats:
    days: int
    halt_days: int
    halt_days_pct: Optional[float]
    longest_halt_streak: int
    halted_at_end: bool
    blocked_buy_signals: int
    first_halt_date: Optional[str]
    transitions: dict[str, int]
    stopped: bool
    stop_reason: Optional[str]
    # Kriz penceresi başına: o pencerede kaç gün halt aktifti, equity ne kadar düştü.
    per_crisis: dict[str, dict]


def _transitions_from_flags(sim: SimResult, starting_capital: float) -> list[dict]:
    """Canlı mandal kolunda geçiş logu: halt bayrağının gün gün değişimi.

    legacy kolunda durum makinesi yok (her gün anlık hesap), ama "halt
    başladı / kalktı" olayları equity eğrisinden birebir okunabilir. Peak,
    `portfolio.state.update_peak_equity()` ile aynı şekilde yeniden
    kurulur: başlangıç sermayesinden başlayan koşan maksimum.
    """
    events: list[dict] = []
    previous = False
    peak = starting_capital
    for (day, equity), flag in zip(sim.equity_curve, sim.halt_flags):
        peak = max(peak, equity)
        if flag != previous:
            events.append(
                {
                    "transition": "halted" if flag else "released",
                    "date": day,
                    "equity": equity,
                    "peak_equity": peak,
                    "drawdown": (peak - equity) / peak if peak > 0 else 0.0,
                    "halted": flag,
                    "stopped": False,
                    "detail": (
                        "Drawdown eşiği aşıldı; yeni ALIM durduruldu."
                        if flag
                        else "Equity eşiğin üstüne döndü; halt kendiliğinden kalktı."
                    ),
                }
            )
            previous = flag
    return events


def _crisis_slice(sim: SimResult, start: date, end: date) -> tuple[list[bool], list[tuple[str, float]]]:
    lo, hi = start.isoformat(), end.isoformat()
    flags, curve = [], []
    for (day, equity), flag in zip(sim.equity_curve, sim.halt_flags):
        if lo <= day <= hi:
            flags.append(flag)
            curve.append((day, equity))
    return flags, curve


def halt_stats(
    sim: SimResult, controller: Optional[HaltController], starting_capital: float
) -> HaltStats:
    flags = sim.halt_flags
    days = len(flags)
    halt_days = sum(1 for f in flags if f)

    longest = streak = 0
    for f in flags:
        streak = streak + 1 if f else 0
        longest = max(longest, streak)

    first_halt_date = None
    for (day, _), f in zip(sim.equity_curve, flags):
        if f:
            first_halt_date = day
            break

    blocked = sum(
        1
        for r in sim.rejected
        if any(reason.startswith(HALT_REASON_PREFIX) for reason in r.reasons)
    )

    if controller is not None:
        raw_events = [asdict(e) for e in sim.halt_events]
    else:
        raw_events = _transitions_from_flags(sim, starting_capital)

    counts: dict[str, int] = {}
    for event in raw_events:
        counts[event["transition"]] = counts.get(event["transition"], 0) + 1

    per_crisis: dict[str, dict] = {}
    for label, (start, end) in CRISIS_WINDOWS.items():
        crisis_flags, crisis_curve = _crisis_slice(sim, start, end)
        first_in_window = None
        for (day, _), f in zip(crisis_curve, crisis_flags):
            if f:
                first_in_window = day
                break
        per_crisis[label] = {
            "days": len(crisis_flags),
            "halt_days": sum(1 for f in crisis_flags if f),
            "first_halt_date": first_in_window,
            "equity_drawdown_pct": window_drawdown(crisis_curve, start, end),
        }

    return HaltStats(
        days=days,
        halt_days=halt_days,
        halt_days_pct=(halt_days / days) if days else None,
        longest_halt_streak=longest,
        halted_at_end=bool(flags and flags[-1]),
        blocked_buy_signals=blocked,
        first_halt_date=first_halt_date,
        transitions=counts,
        stopped=bool(controller.stopped) if controller else False,
        stop_reason=controller.stop_reason if controller else None,
        per_crisis=per_crisis,
    )


# --------------------------------------------------------------------------
# Bir (tohum, kol) görevinin tam koşusu
# --------------------------------------------------------------------------

def _make_controller(policy: Optional[HaltPolicy]) -> Optional[HaltController]:
    return HaltController(policy=policy) if policy is not None else None


def run_arm(
    arm_key: str,
    seed: int,
    price_data: dict[str, list[dict]],
    universe: Sequence[dict],
) -> dict:
    _, label, policy, threshold = next(a for a in ARMS if a[0] == arm_key)

    controller = _make_controller(policy)
    port_sim = simulate(
        universe, price_data, STARTING_CAPITAL,
        max_drawdown_pct=threshold, halt_controller=controller,
    )
    port_total, port_cagr, port_dd, port_sharpe = compute_curve_metrics(port_sim.equity_curve)
    port_trades, port_hit, _ = compute_trade_metrics(port_sim.trades)
    port_halt = halt_stats(port_sim, controller, STARTING_CAPITAL)
    port_events = (
        [asdict(e) for e in port_sim.halt_events]
        if controller is not None
        else _transitions_from_flags(port_sim, STARTING_CAPITAL)
    )

    per_symbol_capital = STARTING_CAPITAL / len(BACKTEST_SYMBOLS)
    isolated: dict[str, dict] = {}
    isolated_events: dict[str, list[dict]] = {}
    start_equity_sum = final_equity_sum = 0.0
    for entry in universe:
        symbol = entry["symbol"]
        sym_controller = _make_controller(policy)
        sim = simulate(
            [entry], price_data, per_symbol_capital,
            max_drawdown_pct=threshold, halt_controller=sym_controller,
        )
        total, _, dd, _ = compute_curve_metrics(sim.equity_curve)
        stats = halt_stats(sim, sym_controller, per_symbol_capital)
        isolated[symbol] = {
            "total_return_pct": total,
            "max_drawdown_pct": dd,
            "trade_count": len(sim.trades),
            "halt": asdict(stats),
        }
        isolated_events[symbol] = (
            [asdict(e) for e in sim.halt_events]
            if sym_controller is not None
            else _transitions_from_flags(sim, per_symbol_capital)
        )
        if sim.equity_curve:
            start_equity_sum += sim.equity_curve[0][1]
            final_equity_sum += sim.equity_curve[-1][1]

    locked = [s for s, r in isolated.items() if r["halt"]["halted_at_end"]]
    stopped = [s for s, r in isolated.items() if r["halt"]["stopped"]]
    ever_halted = [s for s, r in isolated.items() if r["halt"]["halt_days"] > 0]
    halt_pcts = [
        r["halt"]["halt_days_pct"] for r in isolated.values()
        if r["halt"]["halt_days_pct"] is not None
    ]
    worst_dd = min(
        (r["max_drawdown_pct"] for r in isolated.values() if r["max_drawdown_pct"] is not None),
        default=None,
    )
    mean_dd = statistics.fmean(
        [r["max_drawdown_pct"] for r in isolated.values() if r["max_drawdown_pct"] is not None]
    ) if isolated else None

    return {
        "arm": arm_key,
        "label": label,
        "seed": seed,
        "portfolio": {
            "window": {"start": port_sim.window_start, "end": port_sim.window_end},
            "total_return_pct": port_total,
            "cagr_pct": port_cagr,
            "max_drawdown_pct": port_dd,
            "sharpe": port_sharpe,
            "trade_count": port_trades,
            "hit_rate_pct": port_hit,
            "rejected_signals": len(port_sim.rejected),
            "halt": asdict(port_halt),
            "transitions": port_events,
        },
        "isolated": {
            "aggregate_total_return_pct": (
                final_equity_sum / start_equity_sum - 1.0 if start_equity_sum else None
            ),
            "accounts": len(isolated),
            "accounts_ever_halted": len(ever_halted),
            "accounts_locked_at_end": len(locked),
            "accounts_stopped": len(stopped),
            "locked_symbols": sorted(locked),
            "stopped_symbols": sorted(stopped),
            "mean_halt_days_pct": statistics.fmean(halt_pcts) if halt_pcts else None,
            "total_blocked_buy_signals": sum(
                r["halt"]["blocked_buy_signals"] for r in isolated.values()
            ),
            "total_trades": sum(r["trade_count"] for r in isolated.values()),
            "worst_account_dd_pct": worst_dd,
            "mean_account_dd_pct": mean_dd,
            "per_symbol": isolated,
            "transitions": isolated_events,
        },
    }


def _run_on(arm_key: str, seed: int, price_data: dict[str, list[dict]]) -> dict:
    universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in price_data]
    result = run_arm(arm_key, seed, price_data, universe)

    index = equal_weight_index(price_data)
    result["scenario"] = {
        "index_total_return_pct": (index[-1][1] / index[0][1] - 1.0) if len(index) > 1 else None,
        "crisis_drawdowns": {
            label: window_drawdown(index, start, end)
            for label, (start, end) in CRISIS_WINDOWS.items()
        },
    }
    return result


def _task(args: tuple[str, int]) -> dict:
    """Worker girişi: veriyi tohumdan yeniden üretip tek bir kolu koşar.

    Veri süreçler arası taşınmak yerine tohumdan yeniden üretilir (üretim
    ~2 sn, veri ise onlarca MB). Yalnızca sentetik yol buradan geçer;
    gerçek veri ağ çağrısı gerektirdiği için `main()` içinde bir kez
    çekilip bütün kollarda paylaşılır.
    """
    arm_key, seed = args
    return _run_on(arm_key, seed, generate_crisis_data(BACKTEST_SYMBOLS, seed=seed))


# --------------------------------------------------------------------------
# Tohumlar arası özet (medyan + aralık), bulgu raporuyla aynı biçim
# --------------------------------------------------------------------------

def _median_range(values: list[Optional[float]]) -> Optional[dict]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return {"median": statistics.median(clean), "min": min(clean), "max": max(clean)}


def summarize(runs: list[dict]) -> dict[str, dict]:
    """Kol -> metrik -> {median, min, max}."""
    summary: dict[str, dict] = {}
    for arm_key, label, _, _ in ARMS:
        arm_runs = [r for r in runs if r["arm"] == arm_key]
        if not arm_runs:
            continue

        def port(path: list, runs_=arm_runs):
            out = []
            for r in runs_:
                node = r["portfolio"]
                for key in path:
                    node = node[key] if node is not None else None
                out.append(node)
            return out

        def iso(key: str, runs_=arm_runs):
            return [r["isolated"][key] for r in runs_]

        def transition_count(kind: str, runs_=arm_runs):
            return [r["portfolio"]["halt"]["transitions"].get(kind, 0) for r in runs_]

        crisis: dict[str, dict] = {}
        for crisis_label in CRISIS_WINDOWS:
            crisis[crisis_label] = {
                "halt_days": _median_range(
                    [r["portfolio"]["halt"]["per_crisis"][crisis_label]["halt_days"] for r in arm_runs]
                ),
                "equity_drawdown_pct": _median_range(
                    [
                        r["portfolio"]["halt"]["per_crisis"][crisis_label]["equity_drawdown_pct"]
                        for r in arm_runs
                    ]
                ),
                "first_halt_dates": [
                    r["portfolio"]["halt"]["per_crisis"][crisis_label]["first_halt_date"]
                    for r in arm_runs
                ],
            }

        summary[arm_key] = {
            "label": label,
            "seeds": [r["seed"] for r in arm_runs],
            "portfolio": {
                "total_return_pct": _median_range(port(["total_return_pct"])),
                "cagr_pct": _median_range(port(["cagr_pct"])),
                "max_drawdown_pct": _median_range(port(["max_drawdown_pct"])),
                "sharpe": _median_range(port(["sharpe"])),
                "trade_count": _median_range(port(["trade_count"])),
                "hit_rate_pct": _median_range(port(["hit_rate_pct"])),
                "halt_days": _median_range(port(["halt", "halt_days"])),
                "halt_days_pct": _median_range(port(["halt", "halt_days_pct"])),
                "longest_halt_streak": _median_range(port(["halt", "longest_halt_streak"])),
                "blocked_buy_signals": _median_range(port(["halt", "blocked_buy_signals"])),
                "halted_at_end_count": sum(1 for v in port(["halt", "halted_at_end"]) if v),
                "stopped_count": sum(1 for v in port(["halt", "stopped"]) if v),
                "first_halt_dates": port(["halt", "first_halt_date"]),
                "stop_reasons": sorted(
                    {r for r in port(["halt", "stop_reason"]) if r is not None}
                ),
                "transitions": {
                    kind: _median_range(transition_count(kind))
                    for kind in ("halted", "released", "reset", "stopped")
                },
                "crisis": crisis,
            },
            "isolated": {
                "aggregate_total_return_pct": _median_range(iso("aggregate_total_return_pct")),
                "accounts_ever_halted": _median_range(iso("accounts_ever_halted")),
                "accounts_locked_at_end": _median_range(iso("accounts_locked_at_end")),
                "accounts_stopped": _median_range(iso("accounts_stopped")),
                "mean_halt_days_pct": _median_range(iso("mean_halt_days_pct")),
                "total_blocked_buy_signals": _median_range(iso("total_blocked_buy_signals")),
                "total_trades": _median_range(iso("total_trades")),
                "worst_account_dd_pct": _median_range(iso("worst_account_dd_pct")),
                "mean_account_dd_pct": _median_range(iso("mean_account_dd_pct")),
            },
        }
    return summary


# --------------------------------------------------------------------------
# Raporlama
# --------------------------------------------------------------------------

def _pct(v: Optional[float], digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "N/A"


def _mr_pct(mr: Optional[dict], digits: int = 2) -> str:
    if mr is None:
        return "N/A"
    body = _pct(mr["median"], digits)
    if abs(mr["max"] - mr["min"]) < 1e-12:
        return body
    return f"{body} ({_pct(mr['min'], digits)}–{_pct(mr['max'], digits)})"


def _mr_num(mr: Optional[dict], digits: int = 0) -> str:
    if mr is None:
        return "N/A"
    body = f"{mr['median']:.{digits}f}"
    if abs(mr["max"] - mr["min"]) < 1e-12:
        return body
    return f"{body} ({mr['min']:.{digits}f}–{mr['max']:.{digits}f})"


def write_markdown(
    summary: dict[str, dict],
    runs: list[dict],
    path: Path,
    synthetic: bool,
    seeds: list[int],
) -> None:
    arms = [k for k, _, _, _ in ARMS if k in summary]
    lines: list[str] = []
    lines.append("# Kriz dönemi koşusu: 2008 + 2020 çöküşlerinde drawdown halt")
    lines.append("")
    lines.append(f"Üretim zamanı: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    lines.append("")

    if synthetic:
        lines.append(
            "> ⚠️ **SENTETİK KRİZ SENARYOSU — GERÇEK PİYASA VERİSİ DEĞİL.** Bu ortamda "
            "`TWELVEDATA_API_KEY` yok ve dış ağ kapalı, yani gerçek 2008/2020 fiyatları "
            "çekilemedi. Veri `backtest/crisis_data.py` ile üretildi: ortak bir piyasa "
            "faktörü + rejim takvimi, GFC'de ~-55%, COVID'de 23 işlem gününde ~-34% "
            "hedefiyle. **Getiri seviyeleri gerçek performans tahmini değildir.** "
            "Okunabilir olan: böyle bir çöküşte halt kuralının ne yaptığı ve üç kolun "
            "birbirine göre davranışı. Anahtar/ağ olan bir ortamda aynı koşu "
            "`--real` ile gerçek veriyle tekrarlanabilir."
        )
    else:
        lines.append("Gerçek Twelve Data günlük verisi.")
    lines.append("")

    window = runs[0]["portfolio"]["window"] if runs else {"start": "", "end": ""}
    symbol_count = runs[0]["isolated"]["accounts"] if runs else 0
    lines.append(
        f"Pencere: **{window['start']} → {window['end']}** · "
        f"Tohumlar: {', '.join(str(s) for s in seeds)} · "
        f"{symbol_count} sembol · ${STARTING_CAPITAL:,.0f} portföy sermayesi. "
        "Tablolar tohumlar arası **medyan (min–maks)**."
    )
    lines.append("")

    # -- Senaryo doğrulaması -------------------------------------------
    lines.append("## 0) Senaryo gerçekten kriz içeriyor mu?")
    lines.append("")
    lines.append(
        "Eşit ağırlıklı (günlük dengelenen) endeks üzerinden ölçülen kriz derinlikleri — "
        "halt'ın tetiklenmemesi için bir mazeret kalmadığını göstermek için:"
    )
    lines.append("")
    lines.append("| Tohum | " + " | ".join(CRISIS_WINDOWS) + " | 17y toplam |")
    lines.append("|---|" + "---|" * (len(CRISIS_WINDOWS) + 1))
    seen: set[int] = set()
    for r in runs:
        if r["seed"] in seen:
            continue
        seen.add(r["seed"])
        cells = [_pct(r["scenario"]["crisis_drawdowns"][c], 1) for c in CRISIS_WINDOWS]
        lines.append(
            f"| {r['seed']} | " + " | ".join(cells)
            + f" | {_pct(r['scenario']['index_total_return_pct'], 0)} |"
        )
    lines.append("")
    lines.append("Rejim takvimi:")
    lines.append("")
    lines.append("| Rejim | Başlangıç | Hedef hareket | Günlük oynaklık |")
    lines.append("|---|---|---|---|")
    for regime in CRISIS_REGIMES:
        lines.append(
            f"| {regime.name} | {regime.start.isoformat()} | "
            f"{regime.target_return * 100:+.0f}% | {regime.vol * 100:.2f}% |"
        )
    lines.append("")

    header = "| Metrik | " + " | ".join(summary[a]["label"] for a in arms) + " |"
    sep = "|---|" + "---|" * len(arms)

    def row(label: str, fn) -> None:
        lines.append(f"| {label} | " + " | ".join(fn(summary[a]) for a in arms) + " |")

    # -- Portföy -------------------------------------------------------
    lines.append("## 1) Portföy geneli (paylaşılan sermaye, tüm risk kısıtları aktif)")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    row("Toplam getiri", lambda s: _mr_pct(s["portfolio"]["total_return_pct"], 1))
    row("CAGR", lambda s: _mr_pct(s["portfolio"]["cagr_pct"], 2))
    row("Gerçekleşen maks. DD", lambda s: _mr_pct(s["portfolio"]["max_drawdown_pct"], 1))
    row("Sharpe", lambda s: _mr_num(s["portfolio"]["sharpe"], 2))
    row("İşlem sayısı", lambda s: _mr_num(s["portfolio"]["trade_count"]))
    row("İsabet oranı", lambda s: _mr_pct(s["portfolio"]["hit_rate_pct"], 1))
    lines.append("| | | | |")
    row("**Halt aktif gün**", lambda s: _mr_num(s["portfolio"]["halt_days"]))
    row("**Halt aktif gün oranı**", lambda s: _mr_pct(s["portfolio"]["halt_days_pct"], 1))
    row("En uzun kesintisiz halt (gün)", lambda s: _mr_num(s["portfolio"]["longest_halt_streak"]))
    row("Halt'ın engellediği ALIM sinyali", lambda s: _mr_num(s["portfolio"]["blocked_buy_signals"]))
    row(
        "İlk halt tarihi (tohum başına)",
        lambda s: ", ".join(d or "—" for d in s["portfolio"]["first_halt_dates"]),
    )
    lines.append("| | | | |")
    row("Geçiş: halt'a giriş", lambda s: _mr_num(s["portfolio"]["transitions"]["halted"]))
    row("Geçiş: toparlanmayla çıkış", lambda s: _mr_num(s["portfolio"]["transitions"]["released"]))
    row("Geçiş: kısmi reset ile çıkış", lambda s: _mr_num(s["portfolio"]["transitions"]["reset"]))
    row("Geçiş: kalıcı durdurma", lambda s: _mr_num(s["portfolio"]["transitions"]["stopped"]))
    row(
        "**Pencere sonunda halt'ta**",
        lambda s: f"{s['portfolio']['halted_at_end_count']}/{len(s['seeds'])} tohum",
    )
    row(
        "**Pencere sonunda kalıcı durdurulmuş**",
        lambda s: f"{s['portfolio']['stopped_count']}/{len(s['seeds'])} tohum",
    )
    row(
        "Durdurma nedeni",
        lambda s: ", ".join(f"`{r}`" for r in s["portfolio"]["stop_reasons"]) or "—",
    )
    lines.append("")

    # -- Kriz pencereleri ----------------------------------------------
    lines.append("## 2) Krizlerin içinde ne oldu")
    lines.append("")
    for crisis_label, (start, end) in CRISIS_WINDOWS.items():
        lines.append(f"### {crisis_label} — {start.isoformat()} → {end.isoformat()}")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        row(
            "Halt aktif gün (pencere içinde)",
            lambda s, c=crisis_label: _mr_num(s["portfolio"]["crisis"][c]["halt_days"]),
        )
        row(
            "Portföy equity düşüşü",
            lambda s, c=crisis_label: _mr_pct(s["portfolio"]["crisis"][c]["equity_drawdown_pct"], 1),
        )
        row(
            "Halt'ın devreye girdiği gün",
            lambda s, c=crisis_label: ", ".join(
                d or "—" for d in s["portfolio"]["crisis"][c]["first_halt_dates"]
            ),
        )
        lines.append("")

    # -- İzole hesaplar -------------------------------------------------
    lines.append("## 3) İzole hesaplar (20 ayrı tek-sembol hesabı)")
    lines.append("")
    lines.append(
        "Portföy kısıtları paylaşılmadığı için halt'ın kilitleme etkisi burada en net "
        "görünür: bir alt hesap halt'a girip zirvesine dönemezse bir daha hiç alım yapamaz."
    )
    lines.append("")
    lines.append(header)
    lines.append(sep)
    row("Toplam getiri (20 hesap toplamı)", lambda s: _mr_pct(s["isolated"]["aggregate_total_return_pct"], 1))
    row("Toplam işlem sayısı", lambda s: _mr_num(s["isolated"]["total_trades"]))
    row("Halt'a hiç girmiş hesap", lambda s: _mr_num(s["isolated"]["accounts_ever_halted"], 1) + "/20")
    row("**Sonda kilitli kalan hesap**", lambda s: _mr_num(s["isolated"]["accounts_locked_at_end"], 1) + "/20")
    row("**Kalıcı durdurulan hesap**", lambda s: _mr_num(s["isolated"]["accounts_stopped"], 1) + "/20")
    row("Ortalama halt gün oranı", lambda s: _mr_pct(s["isolated"]["mean_halt_days_pct"], 1))
    row("Halt'ın engellediği ALIM sinyali", lambda s: _mr_num(s["isolated"]["total_blocked_buy_signals"]))
    row("Ortalama hesap maks. DD", lambda s: _mr_pct(s["isolated"]["mean_account_dd_pct"], 1))
    row("**En kötü hesap maks. DD**", lambda s: _mr_pct(s["isolated"]["worst_account_dd_pct"], 1))
    lines.append("")

    # -- Geçiş logları ---------------------------------------------------
    lines.append("## 4) Durum makinesi geçiş logları (portföy geneli)")
    lines.append("")
    lines.append(
        "Her kolun ilk tohumundaki portföy hesabının tam geçiş dizisi. "
        "`halted` = yeni ALIM durdu, `released` = toparlanmayla kalktı, "
        "`reset` = kısmi peak reset'iyle kalktı, `stopped` = kalıcı durdurma."
    )
    lines.append("")
    first_seed = seeds[0]
    for arm_key in arms:
        run = next((r for r in runs if r["arm"] == arm_key and r["seed"] == first_seed), None)
        if run is None:
            continue
        events = run["portfolio"]["transitions"]
        lines.append(f"### {ARM_LABELS[arm_key]} (tohum {first_seed}) — {len(events)} geçiş")
        lines.append("")
        if not events:
            lines.append("_Hiç geçiş yok: halt bu kolda hiç tetiklenmedi._")
            lines.append("")
            continue
        lines.append("| # | Tarih | Geçiş | Equity | Peak | Drawdown | Ayrıntı |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, event in enumerate(events, 1):
            lines.append(
                f"| {i} | {event['date']} | `{event['transition']}` | "
                f"{event['equity']:,.0f} | "
                f"{event.get('peak_equity', float('nan')):,.0f} | "
                f"{_pct(event.get('drawdown'), 1)} | {event.get('detail', '')} |"
            )
        lines.append("")

    lines.append(
        "Bütün kolların, bütün tohumların ve 20 izole hesabın geçişleri "
        "`crisis_transitions.jsonl` dosyasında."
    )
    lines.append("")

    lines.append("## Nasıl okunmalı")
    lines.append("")
    lines.append(
        "- **Halt aktif gün oranı = 0** ise kural bu krizde bile hiç tetiklenmemiştir; "
        "koruma iddiası ölçülmemiş demektir."
    )
    lines.append(
        "- **Pencere sonunda halt'ta / kilitli hesap sayısı yüksek** ise kural bir kez "
        "tetiklenip bırakmamıştır: strateji kalıcı olarak durmuştur."
    )
    lines.append(
        "- **Kalıcı durdurma (`stopped`) nedeni** iki v1 kolunu ayıran tek şeydir. "
        "Neden `hard_floor` ise taban değeri bağlamıştır ve taban%50 ile taban%30 "
        "farklı davranır. Neden `max_resets` ise taban hiç devreye girmemiştir: "
        "hesap reset hakkını tüketerek durmuştur, tabanın nerede olduğu sonucu "
        "değiştirmez ve iki kol birebir aynı çıkar."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_transitions_jsonl(runs: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for run in runs:
            for event in run["portfolio"]["transitions"]:
                f.write(json.dumps(
                    {"arm": run["arm"], "seed": run["seed"], "account": "PORTFOLIO", **event},
                    ensure_ascii=False,
                ) + "\n")
            for symbol, events in run["isolated"]["transitions"].items():
                for event in events:
                    f.write(json.dumps(
                        {"arm": run["arm"], "seed": run["seed"], "account": symbol, **event},
                        ensure_ascii=False,
                    ) + "\n")


# --------------------------------------------------------------------------
# Giriş
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    parser.add_argument("--out-dir", default="backtest/results/synthetic/crisis")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--real",
        action="store_true",
        help="Sentetik kriz senaryosu yerine Twelve Data (TWELVEDATA_API_KEY ister)",
    )
    parser.add_argument("--years", type=int, default=17, help="--real ile çekilecek geçmiş")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not args.real and out_dir.resolve() == (Path(__file__).resolve().parent / "results"):
        parser.error(
            "Sentetik sonuçlar backtest/results/ köküne yazılamaz "
            "(gerçek backtest sonuçlarıyla karışmasın diye). Başka bir --out-dir verin."
        )

    seeds = [0] if args.real else list(args.seeds)
    tasks = [(arm_key, seed) for seed in seeds for arm_key, *_ in ARMS]
    print(
        f"{len(tasks)} görev ({len(ARMS)} kol × {len(seeds)} tohum), "
        f"{args.workers} işçi, {'gerçek veri' if args.real else 'sentetik kriz senaryosu'}"
    )

    runs: list[dict] = []
    if args.real:
        # Ağ çağrısı pahalı ve kotalı: veri bir kez çekilip üç kolda paylaşılır.
        print(f"Twelve Data'dan {args.years} yıl çekiliyor...")
        price_data = load_price_data(BACKTEST_SYMBOLS, args.years)
        if not price_data:
            raise SystemExit("Hiçbir sembol için kullanılabilir veri yok; koşu yapılamıyor.")
        for arm_key, seed in tasks:
            print(f"  koşuyor: {arm_key}")
            runs.append(_run_on(arm_key, seed, price_data))
    elif args.workers <= 1:
        for task in tasks:
            print(f"  koşuyor: {task[0]} / tohum {task[1]}")
            runs.append(_task(task))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(_task, tasks):
                port = result["portfolio"]
                print(
                    f"  {result['arm']:<12} tohum {result['seed']:>3}: "
                    f"getiri {_pct(port['total_return_pct'], 1):>9}, "
                    f"maksDD {_pct(port['max_drawdown_pct'], 1):>8}, "
                    f"halt {port['halt']['halt_days']:>5} gün, "
                    f"geçiş {len(port['transitions'])}, "
                    f"durduruldu={port['halt']['stopped']}"
                )
                runs.append(result)

    runs.sort(key=lambda r: ([a[0] for a in ARMS].index(r["arm"]), r["seed"]))
    summary = summarize(runs)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "synthetic": not args.real,
        "seeds": seeds,
        "arms": {k: {"label": lbl, "policy": (asdict(p) if p else None), "threshold": t}
                 for k, lbl, p, t in ARMS},
        "summary": summary,
        "runs": runs,
    }
    (out_dir / "crisis_run.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_transitions_jsonl(runs, out_dir / "crisis_transitions.jsonl")
    write_markdown(summary, runs, out_dir / "crisis_run.md", not args.real, seeds)
    print(f"\nSonuçlar yazıldı: {out_dir}/crisis_run.md, crisis_run.json, crisis_transitions.jsonl")


if __name__ == "__main__":
    main()
