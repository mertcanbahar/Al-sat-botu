#!/usr/bin/env python3
"""Drawdown-halt eşiği süpürmesi: %20 / %25 / %30 / %35 yan yana.

Neyi ölçüyor
------------
`engine.risk.evaluate_buy()` içindeki drawdown halt kuralı, equity zirvesinden
`MAX_DRAWDOWN_PCT` kadar düşünce yeni ALIM'ları durdurur (mevcut pozisyonlar
satılmaya devam eder). Eşik çok sıkı olursa hesap bir kez halt'a girer ve
bir daha asla alım yapamaz -- "sistem kilitlenir", çünkü equity'yi zirveye
geri taşıyacak tek mekanizma yeni alımlardır. Çok gevşek olursa kural hiç
tetiklenmez, yani hiçbir koruma sağlamaz.

Bu script, `backtest/portfolio_backtest.py` içindeki simülasyonun *aynısını*
(aynı sinyal motoru, aynı risk motoru, aynı maliyet modeli, aynı
look-ahead'siz yürütme) her eşik için ayrı ayrı koşar ve şunları raporlar:

  - Getiri tarafı: toplam getiri, CAGR, gerçekleşen maks. drawdown, Sharpe,
    işlem sayısı.
  - Halt'ın işlevselliği: halt'ın aktif olduğu gün sayısı/oranı, en uzun
    kesintisiz halt serisi, halt yüzünden reddedilen ALIM sinyali sayısı.
  - Kilitlenme: pencere sonunda hâlâ halt'ta olan hesap sayısı ("locked"),
    yani bir daha hiç alım yapamamış olanlar.

Böylece "halt bir işe yarıyor mu (hiç tetikleniyor mu)" ile "halt sistemi
kilitliyor mu" sorularının ikisi de aynı tabloda görünür.

Kullanım:
    python backtest/halt_sweep.py --synthetic --out-dir /tmp/halt-sweep
    python backtest/halt_sweep.py --years 5 --out-dir backtest/results  # gerçek veri, TWELVEDATA_API_KEY ister
    python backtest/halt_sweep.py --thresholds 0.20 0.25 0.30 0.35

--synthetic ile üretilen sayılar GERÇEK PİYASA VERİSİ DEĞİLDİR; sadece kodu
ve eşiklerin göreli davranışını sınamak içindir. Bu yüzden sentetik koşu,
backtest/results/ altına yazmayı reddeder.
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
    compute_trade_metrics,
    generate_synthetic_data,
    load_price_data,
    simulate,
)

DEFAULT_THRESHOLDS = [0.20, 0.25, 0.30, 0.35]
HALT_REASON_PREFIX = "Drawdown halt"


# --------------------------------------------------------------------------
# Tek bir hesabın (portföy ya da izole sembol) halt istatistikleri
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


def halt_stats(sim: SimResult) -> HaltStats:
    flags = sim.halt_flags
    days = len(flags)
    halt_days = sum(1 for f in flags if f)

    longest = streak = 0
    for f in flags:
        streak = streak + 1 if f else 0
        longest = max(longest, streak)

    first_halt_date = None
    for (d, _), f in zip(sim.equity_curve, flags):
        if f:
            first_halt_date = d
            break

    blocked = sum(
        1
        for r in sim.rejected
        if any(reason.startswith(HALT_REASON_PREFIX) for reason in r.reasons)
    )

    return HaltStats(
        days=days,
        halt_days=halt_days,
        halt_days_pct=(halt_days / days) if days else None,
        longest_halt_streak=longest,
        halted_at_end=bool(flags and flags[-1]),
        blocked_buy_signals=blocked,
        first_halt_date=first_halt_date,
    )


# --------------------------------------------------------------------------
# Bir eşik için tam koşu (portföy geneli + 20 izole hesap)
# --------------------------------------------------------------------------

def run_threshold(
    threshold: float, price_data: dict[str, list[dict]], universe: Sequence[dict]
) -> dict:
    port_sim = simulate(universe, price_data, STARTING_CAPITAL, max_drawdown_pct=threshold)
    port_total, port_cagr, port_dd, port_sharpe = compute_curve_metrics(port_sim.equity_curve)
    port_trades, port_hit, _ = compute_trade_metrics(port_sim.trades)
    port_halt = halt_stats(port_sim)

    per_symbol_capital = STARTING_CAPITAL / len(BACKTEST_SYMBOLS)
    isolated: dict[str, dict] = {}
    final_equity_sum = 0.0
    start_equity_sum = 0.0
    for entry in universe:
        symbol = entry["symbol"]
        sim = simulate([entry], price_data, per_symbol_capital, max_drawdown_pct=threshold)
        total, _, dd, _ = compute_curve_metrics(sim.equity_curve)
        stats = halt_stats(sim)
        isolated[symbol] = {
            "total_return_pct": total,
            "max_drawdown_pct": dd,
            "trade_count": len(sim.trades),
            "halt": vars(stats),
        }
        if sim.equity_curve:
            start_equity_sum += sim.equity_curve[0][1]
            final_equity_sum += sim.equity_curve[-1][1]

    locked = [s for s, r in isolated.items() if r["halt"]["halted_at_end"]]
    ever_halted = [s for s, r in isolated.items() if r["halt"]["halt_days"] > 0]
    halt_pcts = [
        r["halt"]["halt_days_pct"] for r in isolated.values() if r["halt"]["halt_days_pct"] is not None
    ]

    return {
        "threshold": threshold,
        "portfolio": {
            "window": {"start": port_sim.window_start, "end": port_sim.window_end},
            "total_return_pct": port_total,
            "cagr_pct": port_cagr,
            "max_drawdown_pct": port_dd,
            "sharpe": port_sharpe,
            "trade_count": port_trades,
            "hit_rate_pct": port_hit,
            "rejected_signals": len(port_sim.rejected),
            "halt": vars(port_halt),
        },
        "isolated": {
            "aggregate_total_return_pct": (
                final_equity_sum / start_equity_sum - 1.0 if start_equity_sum else None
            ),
            "accounts": len(isolated),
            "accounts_ever_halted": len(ever_halted),
            "accounts_locked_at_end": len(locked),
            "locked_symbols": sorted(locked),
            "mean_halt_days_pct": statistics.fmean(halt_pcts) if halt_pcts else None,
            "total_blocked_buy_signals": sum(
                r["halt"]["blocked_buy_signals"] for r in isolated.values()
            ),
            "total_trades": sum(r["trade_count"] for r in isolated.values()),
            "per_symbol": isolated,
        },
    }


# --------------------------------------------------------------------------
# Raporlama
# --------------------------------------------------------------------------

def _pct(v: Optional[float], digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "N/A"


def _num(v: Optional[float], digits: int = 2) -> str:
    return f"{v:.{digits}f}" if v is not None else "N/A"


def write_markdown(runs: list[dict], path: Path, synthetic: bool, years: int) -> None:
    lines: list[str] = []
    lines.append("# Drawdown halt eşiği: yan yana karşılaştırma")
    lines.append("")
    lines.append(f"Üretim zamanı: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    lines.append("")
    if synthetic:
        lines.append(
            "> ⚠️ **SENTETİK VERİ.** Bu tablo gerçek piyasa verisiyle değil, "
            "`generate_synthetic_data()`'nın deterministik rastgele yürüyüşüyle "
            "üretildi (ağ/API anahtarı olmadan koşabilmek için). Eşiklerin göreli "
            "davranışı (hangisi kilitliyor, hangisi hiç tetiklenmiyor) okunabilir; "
            "getiri rakamları gerçek performans tahmini DEĞİLDİR."
        )
    else:
        lines.append(
            f"Gerçek Twelve Data günlük verisi, {years} yıl, "
            f"{len(BACKTEST_SYMBOLS)} sembol. Sinyal/risk motoru, maliyet modeli ve "
            "T+1 açılış yürütmesi `backtest/portfolio_backtest.py` ile birebir aynı; "
            "eşik dışında hiçbir parametre değişmiyor."
        )
    lines.append("")

    window = runs[0]["portfolio"]["window"] if runs else {"start": "", "end": ""}
    lines.append(f"Pencere: {window['start']} → {window['end']}")
    lines.append("")

    lines.append("## 1) Portföy geneli (paylaşılan sermaye, tüm risk kısıtları aktif)")
    lines.append("")
    header = "| Metrik | " + " | ".join(f"%{r['threshold'] * 100:.0f}" for r in runs) + " |"
    sep = "|---|" + "---|" * len(runs)
    lines.append(header)
    lines.append(sep)

    def row(label: str, fn) -> None:
        lines.append(f"| {label} | " + " | ".join(fn(r) for r in runs) + " |")

    row("Toplam getiri", lambda r: _pct(r["portfolio"]["total_return_pct"]))
    row("CAGR", lambda r: _pct(r["portfolio"]["cagr_pct"]))
    row("Gerçekleşen maks. DD", lambda r: _pct(r["portfolio"]["max_drawdown_pct"]))
    row("Sharpe", lambda r: _num(r["portfolio"]["sharpe"]))
    row("İşlem sayısı", lambda r: str(r["portfolio"]["trade_count"]))
    row(
        "İsabet oranı",
        lambda r: _pct(r["portfolio"]["hit_rate_pct"], 1)
        if r["portfolio"]["hit_rate_pct"] is not None
        else "N/A",
    )
    row("**Halt aktif gün**", lambda r: str(r["portfolio"]["halt"]["halt_days"]))
    row("**Halt aktif gün oranı**", lambda r: _pct(r["portfolio"]["halt"]["halt_days_pct"], 1))
    row("En uzun kesintisiz halt (gün)", lambda r: str(r["portfolio"]["halt"]["longest_halt_streak"]))
    row("İlk halt tarihi", lambda r: r["portfolio"]["halt"]["first_halt_date"] or "—")
    row("Halt'ın engellediği ALIM sinyali", lambda r: str(r["portfolio"]["halt"]["blocked_buy_signals"]))
    row(
        "**Pencere sonunda kilitli mi?**",
        lambda r: "🔒 EVET" if r["portfolio"]["halt"]["halted_at_end"] else "hayır",
    )
    lines.append("")

    lines.append("## 2) İzole hesaplar (20 ayrı tek-sembol hesabı)")
    lines.append("")
    lines.append(
        "Portföy kısıtları paylaşılmadığı için halt'ın kilitleme etkisi burada en "
        "net görünür: bir alt hesap halt'a girip zirvesine dönemezse bir daha hiç "
        "alım yapamaz."
    )
    lines.append("")
    lines.append(header)
    lines.append(sep)
    row("Toplam getiri (20 hesap toplamı)", lambda r: _pct(r["isolated"]["aggregate_total_return_pct"]))
    row("Toplam işlem sayısı", lambda r: str(r["isolated"]["total_trades"]))
    row("Halt'a hiç girmiş hesap", lambda r: f"{r['isolated']['accounts_ever_halted']}/{r['isolated']['accounts']}")
    row(
        "**Sonda kilitli kalan hesap**",
        lambda r: f"{r['isolated']['accounts_locked_at_end']}/{r['isolated']['accounts']}",
    )
    row("Ortalama halt gün oranı", lambda r: _pct(r["isolated"]["mean_halt_days_pct"], 1))
    row("Halt'ın engellediği ALIM sinyali", lambda r: str(r["isolated"]["total_blocked_buy_signals"]))
    lines.append("")

    for r in runs:
        locked = r["isolated"]["locked_symbols"]
        lines.append(
            f"- %{r['threshold'] * 100:.0f} → kilitli kalan semboller: "
            + (", ".join(locked) if locked else "yok")
        )
    lines.append("")

    lines.append("## Nasıl okunmalı")
    lines.append("")
    lines.append(
        "- **Halt aktif gün oranı = 0** ise kural hiç tetiklenmemiştir: koruma "
        "sağlamaz, parametre sınanmamış demektir."
    )
    lines.append(
        "- **Sonda kilitli hesap sayısı yüksek** ise kural bir kez tetiklenip bir "
        "daha bırakmamış, yani stratejiyi kalıcı olarak durdurmuştur."
    )
    lines.append(
        "- Aranan orta nokta: halt'ın ölçülebilir biçimde tetiklendiği ama hesapların "
        "büyük kısmının pencere sonunda kilitli kalmadığı eşik."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--out-dir", default="backtest/results")
    parser.add_argument("--thresholds", type=float, nargs="+", default=DEFAULT_THRESHOLDS)
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Sentetik veri kullan (ağ yok, gerçek sonuç değil)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    if args.synthetic and out_dir.resolve() == (Path(__file__).resolve().parent / "results"):
        parser.error(
            "--synthetic sonuçları backtest/results/ altına yazılamaz "
            "(gerçek backtest sonuçlarıyla karışmasın diye). Başka bir --out-dir verin."
        )

    print(f"Veri yükleniyor ({'sentetik' if args.synthetic else 'Twelve Data'}, {args.years}y)...")
    if args.synthetic:
        price_data = generate_synthetic_data(BACKTEST_SYMBOLS, args.years)
    else:
        price_data = load_price_data(BACKTEST_SYMBOLS, args.years)
    if not price_data:
        raise SystemExit("Hiçbir sembol için kullanılabilir veri yok; süpürme yapılamıyor.")

    universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in price_data]

    runs = []
    for threshold in args.thresholds:
        print(f"\n=== Eşik %{threshold * 100:.0f} ===")
        result = run_threshold(threshold, price_data, universe)
        p, iso = result["portfolio"], result["isolated"]
        print(
            f"  portföy: getiri {_pct(p['total_return_pct'])}, "
            f"halt {p['halt']['halt_days']} gün ({_pct(p['halt']['halt_days_pct'], 1)}), "
            f"sonda kilitli: {p['halt']['halted_at_end']}"
        )
        print(
            f"  izole:   getiri {_pct(iso['aggregate_total_return_pct'])}, "
            f"kilitli hesap {iso['accounts_locked_at_end']}/{iso['accounts']}, "
            f"halt'a giren {iso['accounts_ever_halted']}/{iso['accounts']}"
        )
        runs.append(result)

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "synthetic": args.synthetic,
        "years": args.years,
        "symbols": [e["symbol"] for e in universe],
        "excluded_symbols": [e["symbol"] for e in BACKTEST_SYMBOLS if e["symbol"] not in price_data],
        "runs": runs,
    }
    (out_dir / "halt_sweep.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(runs, out_dir / "halt_sweep.md", args.synthetic, args.years)
    print(f"\nSonuçlar yazıldı: {out_dir}/halt_sweep.md, {out_dir}/halt_sweep.json")


if __name__ == "__main__":
    main()
