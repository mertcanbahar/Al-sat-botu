#!/usr/bin/env python3
"""Drawdown halt politikası süpürmesi: eşik + histerezis + kısmi reset.

Neyi ölçüyor
------------
`engine.risk.update_halt_state()` halt'ı kalıcı bir durum olarak yönetir:
`halt_pct` drawdown'da tetiklenir, `release_pct`'ye toparlanınca ya da
nakitte kilitlenmiş bir hesapta kısmi peak reset'iyle bırakır, reset hakkı
bitince kalıcı olarak durur. Bu script aynı simülasyonu
(`backtest/portfolio_backtest.py` -- aynı sinyal motoru, aynı maliyet modeli,
aynı look-ahead'siz T+1 yürütme) farklı `HaltPolicy`'lerle koşup yan yana
karşılaştırır.

Raporlanan iki soru:
  - **Halt işlevsel mi?** tetiklenme sayısı, halt'ta geçen gün oranı,
    engellenen ALIM sinyali sayısı.
  - **Kilitliyor mu / çırpınıyor mu?** pencere sonunda hâlâ halt'ta olan
    hesap sayısı, kalıcı durdurma sayısı, halt->serbest döngü sayısı
    (çok yüksekse eşikler birbirine fazla yakın demektir).

Tek bir rastgele çekilişe bakarak parametre seçilmesin diye her politika
`--seeds` kadar farklı sentetik veri kümesinde koşulur ve medyan raporlanır.

Kullanım:
    python backtest/halt_sweep.py --synthetic --seeds 8 --out-dir /tmp/halt-sweep
    python backtest/halt_sweep.py --years 5 --out-dir backtest/results  # gerçek veri
    python backtest/halt_sweep.py --synthetic --release-pcts none 0.05 0.10 0.15

--synthetic ile üretilen sayılar GERÇEK PİYASA VERİSİ DEĞİLDİR; eşiklerin
göreli davranışını sınamak içindir. Bu yüzden sentetik koşu backtest/results/
altına yazmayı reddeder.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.portfolio_backtest import (  # noqa: E402
    BACKTEST_SYMBOLS,
    STARTING_CAPITAL,
    SimResult,
    compute_curve_metrics,
    generate_synthetic_data,
    load_price_data,
    simulate,
)
from engine.risk import HaltPolicy  # noqa: E402

HALT_REASON_PREFIX = "Drawdown halt"
STOP_REASON_PREFIX = "Bot kalıcı olarak durduruldu"


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
    stopped: bool
    cycles: int          # kaç kez halt'a girdi
    releases: int        # kaç kez toparlanmayla çıktı
    resets: int          # kaç kez kısmi peak reset'iyle çıktı
    blocked_buy_signals: int


def halt_stats(sim: SimResult) -> HaltStats:
    flags = sim.halt_flags
    days = len(flags)
    halt_days = sum(1 for f in flags if f)

    longest = streak = 0
    for f in flags:
        streak = streak + 1 if f else 0
        longest = max(longest, streak)

    transitions = [t for _, t, _ in sim.halt_transitions]
    blocked = sum(
        1
        for r in sim.rejected
        if any(
            reason.startswith(HALT_REASON_PREFIX) or reason.startswith(STOP_REASON_PREFIX)
            for reason in r.reasons
        )
    )

    return HaltStats(
        days=days,
        halt_days=halt_days,
        halt_days_pct=(halt_days / days) if days else None,
        longest_halt_streak=longest,
        halted_at_end=bool(flags and flags[-1]),
        stopped=sim.stopped,
        cycles=transitions.count("halted"),
        releases=transitions.count("released"),
        resets=transitions.count("reset"),
        blocked_buy_signals=blocked,
    )


# --------------------------------------------------------------------------
# Bir politikanın tek bir veri kümesindeki sonucu
# --------------------------------------------------------------------------

def run_policy(
    policy: HaltPolicy,
    price_data: dict[str, list[dict]],
    universe: Sequence[dict],
    include_portfolio: bool = True,
) -> dict:
    result: dict = {}

    if include_portfolio:
        sim = simulate(universe, price_data, STARTING_CAPITAL, halt_policy=policy)
        total, cagr, dd, sharpe = compute_curve_metrics(sim.equity_curve)
        stats = halt_stats(sim)
        result["portfolio"] = {
            "window": {"start": sim.window_start, "end": sim.window_end},
            "total_return_pct": total,
            "cagr_pct": cagr,
            "max_drawdown_pct": dd,
            "sharpe": sharpe,
            "trade_count": len(sim.trades),
            "halt": vars(stats),
        }

    per_symbol_capital = STARTING_CAPITAL / len(BACKTEST_SYMBOLS)
    isolated: dict[str, dict] = {}
    start_sum = final_sum = 0.0
    for entry in universe:
        sim = simulate([entry], price_data, per_symbol_capital, halt_policy=policy)
        total, _, dd, _ = compute_curve_metrics(sim.equity_curve)
        isolated[entry["symbol"]] = {
            "total_return_pct": total,
            "max_drawdown_pct": dd,
            "trade_count": len(sim.trades),
            "halt": vars(halt_stats(sim)),
        }
        if sim.equity_curve:
            start_sum += sim.equity_curve[0][1]
            final_sum += sim.equity_curve[-1][1]

    dds = [r["max_drawdown_pct"] for r in isolated.values() if r["max_drawdown_pct"] is not None]
    halt_pcts = [
        r["halt"]["halt_days_pct"] for r in isolated.values() if r["halt"]["halt_days_pct"] is not None
    ]
    result["isolated"] = {
        "aggregate_total_return_pct": (final_sum / start_sum - 1.0) if start_sum else None,
        "mean_max_drawdown_pct": statistics.fmean(dds) if dds else None,
        "worst_max_drawdown_pct": min(dds) if dds else None,
        "accounts": len(isolated),
        "accounts_locked_at_end": sum(1 for r in isolated.values() if r["halt"]["halted_at_end"]),
        "accounts_stopped": sum(1 for r in isolated.values() if r["halt"]["stopped"]),
        "locked_symbols": sorted(s for s, r in isolated.items() if r["halt"]["halted_at_end"]),
        "total_cycles": sum(r["halt"]["cycles"] for r in isolated.values()),
        "total_releases": sum(r["halt"]["releases"] for r in isolated.values()),
        "total_resets": sum(r["halt"]["resets"] for r in isolated.values()),
        "total_blocked_buy_signals": sum(r["halt"]["blocked_buy_signals"] for r in isolated.values()),
        "total_trades": sum(r["trade_count"] for r in isolated.values()),
        "mean_halt_days_pct": statistics.fmean(halt_pcts) if halt_pcts else None,
        "per_symbol": isolated,
    }
    return result


# --------------------------------------------------------------------------
# Politika ızgarası ve tohumlar arası birleştirme
# --------------------------------------------------------------------------

def policy_label(policy: HaltPolicy) -> str:
    if policy.latching:
        return f"H%{policy.halt_pct * 100:.0f} / mandal"
    return f"H%{policy.halt_pct * 100:.0f} → R%{policy.release_pct * 100:.0f}"


def _median(values: list) -> Optional[float]:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


def aggregate(runs: list[dict], key_path: tuple[str, ...]) -> dict:
    """Aynı politikanın farklı tohumlardaki sonuçlarını medyan + aralık olarak topla."""
    section = key_path[0]
    fields = [k for k in runs[0][section] if isinstance(runs[0][section][k], (int, float, type(None)))]
    out: dict = {}
    for field_name in fields:
        values = [r[section][field_name] for r in runs]
        out[field_name] = {
            "median": _median(values),
            "min": min((v for v in values if v is not None), default=None),
            "max": max((v for v in values if v is not None), default=None),
        }
    return out


# --------------------------------------------------------------------------
# Raporlama
# --------------------------------------------------------------------------

def _pct(v: Optional[float], digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "N/A"


def _num(v: Optional[float], digits: int = 2) -> str:
    return f"{v:.{digits}f}" if v is not None else "N/A"


def _range(stat: dict, fmt=_num) -> str:
    if stat["median"] is None:
        return "N/A"
    if stat["min"] == stat["max"]:
        return fmt(stat["median"])
    return f"{fmt(stat['median'])} ({fmt(stat['min'])}–{fmt(stat['max'])})"


def write_markdown(
    results: list[dict], path: Path, synthetic: bool, years: int, seeds: int, with_portfolio: bool
) -> None:
    lines: list[str] = []
    lines.append("# Drawdown halt politikası: yan yana karşılaştırma")
    lines.append("")
    lines.append(f"Üretim zamanı: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    lines.append("")
    if synthetic:
        lines.append(
            f"> ⚠️ **SENTETİK VERİ, {seeds} tohum.** Gerçek piyasa verisi değil; "
            "ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın "
            "deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, "
            "parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı "
            "okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR."
        )
    else:
        lines.append(
            f"Gerçek Twelve Data günlük verisi, {years} yıl, {len(BACKTEST_SYMBOLS)} sembol."
        )
    lines.append("")

    labels = [r["label"] for r in results]
    header = "| Metrik | " + " | ".join(labels) + " |"
    sep = "|---|" + "---|" * len(labels)

    def table(section: str, rows: list[tuple[str, str, object]]) -> None:
        lines.append(header)
        lines.append(sep)
        for title, field_name, fmt in rows:
            cells = []
            for r in results:
                stat = r[section].get(field_name)
                cells.append(_range(stat, fmt) if stat else "N/A")
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## İzole hesaplar (20 ayrı tek-sembol hesabı)")
    lines.append("")
    lines.append(
        "Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için "
        "halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok."
    )
    lines.append("")
    table(
        "isolated",
        [
            ("Toplam getiri (20 hesap)", "aggregate_total_return_pct", _pct),
            ("Ortalama maks. DD", "mean_max_drawdown_pct", _pct),
            ("En kötü hesap DD", "worst_max_drawdown_pct", _pct),
            ("Toplam işlem", "total_trades", _num),
            ("**Sonda kilitli hesap**", "accounts_locked_at_end", _num),
            ("**Kalıcı durdurulan hesap**", "accounts_stopped", _num),
            ("Halt tetiklenme sayısı", "total_cycles", _num),
            ("Toparlanmayla çıkış", "total_releases", _num),
            ("Kısmi reset ile çıkış", "total_resets", _num),
            ("Engellenen ALIM sinyali", "total_blocked_buy_signals", _num),
            ("Ortalama halt gün oranı", "mean_halt_days_pct", _pct),
        ],
    )

    if with_portfolio:
        lines.append("## Portföy geneli (paylaşılan sermaye)")
        lines.append("")
        table(
            "portfolio",
            [
                ("Toplam getiri", "total_return_pct", _pct),
                ("CAGR", "cagr_pct", _pct),
                ("Maks. DD", "max_drawdown_pct", _pct),
                ("Sharpe", "sharpe", _num),
                ("İşlem sayısı", "trade_count", _num),
            ],
        )
        lines.append(header)
        lines.append(sep)
        for title, field_name, fmt in [
            ("Halt gün oranı", "halt_days_pct", _pct),
            ("Halt tetiklenme sayısı", "cycles", _num),
            ("Toparlanmayla çıkış", "releases", _num),
            ("Kısmi reset ile çıkış", "resets", _num),
            ("Engellenen ALIM sinyali", "blocked_buy_signals", _num),
        ]:
            cells = [_range(r["portfolio_halt"].get(field_name), fmt) for r in results]
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        lines.append("")

    lines.append("## Nasıl okunmalı")
    lines.append("")
    lines.append("- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.")
    lines.append("- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.")
    lines.append(
        "- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler "
        "birbirine fazla yakın, halt çırpınıyor."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--out-dir", default="backtest/results")
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.20])
    parser.add_argument(
        "--release-pcts",
        nargs="+",
        default=["none", "0.05", "0.10", "0.15"],
        help="Serbest bırakma eşikleri; 'none' = histerezis yok (eski mandal davranışı)",
    )
    parser.add_argument("--seeds", type=int, default=1, help="Kaç farklı sentetik veri kümesi")
    parser.add_argument("--no-portfolio", action="store_true", help="Sadece izole hesaplar (hızlı)")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    if args.synthetic and out_dir.resolve() == (Path(__file__).resolve().parent / "results"):
        parser.error(
            "--synthetic sonuçları backtest/results/ altına yazılamaz. Başka bir --out-dir verin."
        )
    if not args.synthetic and args.seeds > 1:
        parser.error("--seeds yalnızca sentetik veriyle anlamlı (gerçek veri tek bir tarihtir).")

    policies = [
        HaltPolicy(halt_pct=h, release_pct=None if r == "none" else float(r))
        for h in args.thresholds
        for r in args.release_pcts
    ]

    seeds = list(range(42, 42 + args.seeds)) if args.synthetic else [None]
    per_policy: dict[str, list[dict]] = {policy_label(p): [] for p in policies}

    for seed in seeds:
        if args.synthetic:
            print(f"\n### Tohum {seed}")
            price_data = generate_synthetic_data(BACKTEST_SYMBOLS, args.years, seed=seed)
        else:
            print(f"Veri yükleniyor (Twelve Data, {args.years}y)...")
            price_data = load_price_data(BACKTEST_SYMBOLS, args.years)
        if not price_data:
            raise SystemExit("Kullanılabilir veri yok.")
        universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in price_data]

        for policy in policies:
            label = policy_label(policy)
            run = run_policy(policy, price_data, universe, include_portfolio=not args.no_portfolio)
            per_policy[label].append(run)
            iso = run["isolated"]
            print(
                f"  {label}: getiri {_pct(iso['aggregate_total_return_pct'])}, "
                f"kilitli {iso['accounts_locked_at_end']}/{iso['accounts']}, "
                f"durdurulan {iso['accounts_stopped']}, "
                f"tetiklenme {iso['total_cycles']}, "
                f"toparlanma {iso['total_releases']}, reset {iso['total_resets']}"
            )

    results = []
    for policy in policies:
        label = policy_label(policy)
        runs = per_policy[label]
        entry = {
            "label": label,
            "policy": {
                "halt_pct": policy.halt_pct,
                "release_pct": policy.release_pct,
                "min_halt_marks": policy.min_halt_marks,
                "reset_after_marks": policy.reset_after_marks,
                "reset_fraction": policy.reset_fraction,
                "max_resets": policy.max_resets,
                "hard_floor_pct": policy.hard_floor_pct,
            },
            "isolated": aggregate(runs, ("isolated",)),
        }
        if not args.no_portfolio:
            entry["portfolio"] = aggregate(runs, ("portfolio",))
            entry["portfolio_halt"] = aggregate(
                [{"halt": r["portfolio"]["halt"]} for r in runs], ("halt",)
            )
        results.append(entry)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "halt_sweep.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "synthetic": args.synthetic,
                "seeds": seeds,
                "years": args.years,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    write_markdown(
        results, out_dir / "halt_sweep.md", args.synthetic, args.years, len(seeds),
        with_portfolio=not args.no_portfolio,
    )
    print(f"\nSonuçlar yazıldı: {out_dir}/halt_sweep.md, {out_dir}/halt_sweep.json")


if __name__ == "__main__":
    main()
