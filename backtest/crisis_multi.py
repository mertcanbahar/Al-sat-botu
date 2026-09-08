#!/usr/bin/env python3
"""Kriz rejimi koşusu: 3 çöküş şekli x N tohum x 3 kol.

Rastgele yürüyüş verisi halt kuralının var olma sebebini (kuyruk rejimi)
içermiyor. Bu script kasıtlı bir kriz üretir: ortak piyasa faktörü (beta) +
sembole özgü gürültü, ve tanımlı bir çöküş penceresinde güçlü negatif
sürüklenme ile yükselen oynaklık. Kriz sırasında bütün semboller birlikte
düştüğü için portföy çeşitlendirmeyle kaçamaz.

Üç kol aynı veri üzerinde koşulur:
  A. Halt kapalı  B. Mandal %20 (production)  C. Histerezis %20→%10

Kollar doğrudan bu repodaki risk motoruna karşı koşar (trend kapılı halt
production'a alındıktan sonra ayrı bir ağaca gerek kalmadı).

Sonuçlar: backtest/results/synthetic/crisis_<sekil>.json

Kullanım: python3 crisis_multi.py <sekil> <tohum_sayisi>
  sekil: kisa_sert | uzun_yavas | cift_dipli

Her (şekil, tohum) için aynı veri üzerinde üç kol koşulur:
  A. Halt kapalı        B. Mandal %20 (production)      C. Histerezis %20→%10

Ayrıca her halt/reset olayının krizin hangi evresinde olduğu etiketlenir:
  kriz_oncesi | cokus_ici | toparlanma | sonrasi
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.portfolio_backtest import (  # noqa: E402
    BACKTEST_SYMBOLS,
    STARTING_CAPITAL,
    compute_curve_metrics,
    load_price_data,
    market_trend_flags,
    simulate,
)
from engine.risk import HaltPolicy  # noqa: E402

YEARS = 5
TRADING_DAYS = YEARS * 252
CRASH_START = 630
RECOVERY_LEN = 250
NORMAL_DRIFT, NORMAL_VOL = 0.0004, 0.011
MARKET_SHARE = 0.75

# (segment listesi) -- her segment (gun_sayisi, gunluk_suruklenme, oynaklik)
SHAPES = {
    # ~3 ayda sert çöküş
    "kisa_sert": [(60, -0.0070, 0.032)],
    # ~14 ayda yavaş erime
    "uzun_yavas": [(300, -0.0016, 0.014)],
    # düş - yarı toparlan - tekrar düş
    "cift_dipli": [(80, -0.0055, 0.028), (60, +0.0030, 0.016), (80, -0.0055, 0.028)],
}


def build_regimes(shape: str) -> list[tuple[float, float]]:
    """Gün başına (sürüklenme, oynaklık)."""
    regimes = [(NORMAL_DRIFT, NORMAL_VOL)] * TRADING_DAYS
    i = CRASH_START
    for days, drift, vol in SHAPES[shape]:
        for k in range(days):
            if i + k < TRADING_DAYS:
                regimes[i + k] = (drift, vol)
        i += days
    crash_end = i
    for k in range(RECOVERY_LEN):
        if crash_end + k < TRADING_DAYS:
            regimes[crash_end + k] = (0.0011, NORMAL_VOL)
    return regimes, crash_end


def generate(shape: str, seed: int):
    regimes, crash_end = build_regimes(shape)
    mkt = random.Random(seed)
    market, dates = [], []
    d = datetime(2021, 1, 4, tzinfo=timezone.utc)
    for i in range(TRADING_DAYS):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        drift, vol = regimes[i]
        market.append(mkt.gauss(drift, vol))
        dates.append(d)
        d += timedelta(days=1)

    data = {}
    for n, entry in enumerate(BACKTEST_SYMBOLS):
        rng = random.Random(seed * 1000 + n)
        price = rng.uniform(50, 400)
        beta = rng.uniform(0.8, 1.25)
        rows = []
        for i in range(TRADING_DAYS):
            _, vol = regimes[i]
            ret = beta * MARKET_SHARE * market[i] + rng.gauss(0.0, vol * (1 - MARKET_SHARE))
            price = max(1.0, price * (1 + ret))
            high = price * (1 + abs(rng.gauss(0, 0.005)))
            low = price * (1 - abs(rng.gauss(0, 0.005)))
            open_ = low + (high - low) * rng.random()
            rows.append({
                "timestamp": dates[i], "open": open_,
                "high": max(high, open_, price), "low": min(low, open_, price),
                "close": price, "volume": rng.uniform(1_000_000, 5_000_000),
            })
        data[entry["symbol"]] = rows

    phases = {
        "crash_start": dates[CRASH_START].date().isoformat(),
        "crash_end": dates[min(crash_end, TRADING_DAYS - 1)].date().isoformat(),
        "recovery_end": dates[min(crash_end + RECOVERY_LEN, TRADING_DAYS - 1)].date().isoformat(),
    }
    return data, phases


def phase_of(date_str: str, phases: dict) -> str:
    if date_str < phases["crash_start"]:
        return "kriz_oncesi"
    if date_str < phases["crash_end"]:
        return "COKUS_ICI"
    if date_str < phases["recovery_end"]:
        return "toparlanma"
    return "sonrasi"


ARMS = {
    "A_halt_kapali": HaltPolicy(halt_pct=1.01, release_pct=None),
    "B_mandal20": HaltPolicy(halt_pct=0.20, release_pct=None),
    "C_histerezis": HaltPolicy(
        halt_pct=0.20, release_pct=0.10, min_halt_marks=10,
        reset_after_marks=60, reset_fraction=0.5, max_resets=2, hard_floor_pct=0.50,
    ),
    # E: zaman sayacı yerine DURUMA bakan çıkış koşulu. Piyasa proxy'si
    # (20 sembolün eşit ağırlıklı endeksi) kendi SMA50'sinin üstüne çıkınca
    # halt kalkar; drawdown toparlanması beklenmez. Zaman sayacı yalnızca
    # uzun bir emniyet ağı olarak kalır (250 işaretleme), böylece trend hiç
    # dönmezse hesap yine de kilitli kalmaz.
    # Motor tarafı: crisis_trend_release.patch (1fc8e31 üzerine).
    "E_trend_kapisi": HaltPolicy(
        halt_pct=0.20, release_pct=0.10, min_halt_marks=10,
        reset_after_marks=250, reset_fraction=0.5, max_resets=2, hard_floor_pct=0.50,
    ),  # trend bayrakları simulate()'e ayrıca geçilir
    # C ile tek farkı reset penceresi: 60 gün çöküş süresinden kısa kaldığı
    # için mekanizma krizin ortasında geri giriyordu (bkz. reset@COKUS_ICI
    # vakaları). 120 gün bunu kapatıyor mu?
    "D_histerezis_reset120": HaltPolicy(
        halt_pct=0.20, release_pct=0.10, min_halt_marks=10,
        reset_after_marks=120, reset_fraction=0.5, max_resets=2, hard_floor_pct=0.50,
    ),
}

ARMS_ALL = dict(ARMS)

# Alt küme koşmak için: ALSATBOTU_CRISIS_ARMS="D_histerezis_reset120"
_selected = os.environ.get("ALSATBOTU_CRISIS_ARMS", "").strip()
if _selected:
    names = [n.strip() for n in _selected.split(",") if n.strip()]
    unknown = [n for n in names if n not in ARMS]
    if unknown:
        raise SystemExit(f"Bilinmeyen kol(lar): {unknown}. Geçerli: {list(ARMS)}")
    ARMS = {n: ARMS[n] for n in names}
    ARM_SUFFIX = "_" + "+".join(names)
else:
    ARM_SUFFIX = ""


# --------------------------------------------------------------------------
# Gerçek veri modu: sentetik kriz yerine gerçek piyasa geçmişi
# --------------------------------------------------------------------------

# Gerçek veride kriz penceresi uydurulmaz; bilinen stres dönemleri ayrıca
# raporlanır (veri o tarihleri kapsıyorsa).
STRESS_WINDOWS = {
    "2008_GFC": ("2007-10-01", "2009-06-30"),
    "2011_euro": ("2011-05-01", "2011-12-31"),
    "2018_Q4": ("2018-09-01", "2018-12-31"),
    "2020_covid": ("2020-02-01", "2020-06-30"),
    "2022_ayi": ("2022-01-01", "2022-12-31"),
}


def window_metrics(curve: list, start: str, end: str) -> Optional[dict]:
    """Equity eğrisinin bir alt penceresindeki getiri ve maks. drawdown."""
    seg = [(d, v) for d, v in curve if start <= d <= end]
    if len(seg) < 2:
        return None
    values = [v for _, v in seg]
    peak = values[0]
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    return {
        "start": seg[0][0], "end": seg[-1][0], "days": len(seg),
        "total_return_pct": values[-1] / values[0] - 1.0 if values[0] else None,
        "max_drawdown_pct": mdd,
    }


# Simülasyon, evrendeki BÜTÜN semboller warmup'ını doldurunca başlar. Yani
# tek bir geç başlayan sembol (ör. META, 2012 IPO) pencereyi 2012'ye çeker
# ve 2008 dışarıda kalır. 2008'i kapsamak istiyorsak o sembolleri evrenden
# çıkarmak gerekir; hangileri çıktığı raporlanır.
HISTORY_CUTOFF = "2007-01-01"


def run_real(years: int, cutoff: str = HISTORY_CUTOFF) -> None:
    """Gerçek Twelve Data geçmişiyle A (halt kapalı) ve E (trend kapısı) kolları."""
    print(f"Gerçek veri yükleniyor (Twelve Data, {years} yıl, {len(BACKTEST_SYMBOLS)} sembol)...")
    data = load_price_data(BACKTEST_SYMBOLS, years)
    if not data:
        raise SystemExit("Hiçbir sembol için veri alınamadı (API anahtarı / kota?).")

    too_short = {
        s: rows[0]["timestamp"].date().isoformat()
        for s, rows in data.items()
        if rows[0]["timestamp"].date().isoformat() > cutoff
    }
    if too_short:
        print(
            f"\n{cutoff} sonrası başlayan {len(too_short)} sembol evrenden çıkarıldı "
            "(yoksa pencere en geç başlayana göre kısalır ve 2008 dışarıda kalır):"
        )
        for s, d in sorted(too_short.items()):
            print(f"  {s}: ilk mum {d}")
        for s in too_short:
            data.pop(s)
    if not data:
        raise SystemExit("Kesme tarihinden sonra evrende sembol kalmadı.")

    universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in data]
    n = min(len(rows) for rows in data.values())
    earliest = min(rows[0]["timestamp"].date().isoformat() for rows in data.values())
    latest = max(rows[-1]["timestamp"].date().isoformat() for rows in data.values())
    print(f"\n{len(universe)} sembol, en kısa seri {n} mum, veri {earliest} → {latest}.")

    trend_flags = market_trend_flags(data)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "synthetic": False,
        "years_requested": years,
        "symbols": [e["symbol"] for e in universe],
        "excluded_symbols": [e["symbol"] for e in BACKTEST_SYMBOLS if e["symbol"] not in data],
        "excluded_for_short_history": too_short,
        "history_cutoff": cutoff,
        "arms": {},
    }

    for name in ("A_halt_kapali", "E_trend_kapisi"):
        policy = ARMS_ALL[name]
        flags = trend_flags if name == "E_trend_kapisi" else None
        sim = simulate(universe, data, STARTING_CAPITAL, halt_policy=policy, trend_ok_by_date=flags)
        total, cagr, dd, sharpe = compute_curve_metrics(sim.equity_curve)
        stress = {
            label: window_metrics(sim.equity_curve, a, b)
            for label, (a, b) in STRESS_WINDOWS.items()
        }
        out["arms"][name] = {
            "window": {"start": sim.window_start, "end": sim.window_end},
            "total_return_pct": total, "cagr_pct": cagr,
            "max_drawdown_pct": dd, "sharpe": sharpe,
            "trade_count": len(sim.trades),
            "halt_days": sum(1 for f in sim.halt_flags if f),
            "halt_days_pct": sum(1 for f in sim.halt_flags if f) / max(len(sim.halt_flags), 1),
            "halted_at_end": bool(sim.halt_flags and sim.halt_flags[-1]),
            "stopped": sim.stopped,
            "events": [{"date": d, "kind": t, "detail": det} for d, t, det in sim.halt_transitions],
            "stress_windows": {k: v for k, v in stress.items() if v},
        }
        a = out["arms"][name]
        print(f"\n{name}: {a['window']['start']} → {a['window']['end']}")
        print(f"  getiri {total*100:+.2f}%  CAGR {cagr*100:+.2f}%  Sharpe {sharpe:.2f}  maksDD {dd*100:.2f}%  işlem {len(sim.trades)}")
        print(f"  halt {a['halt_days']} gün ({a['halt_days_pct']*100:.1f}%), sonda kilitli: {a['halted_at_end']}")
        for e in a["events"]:
            print(f"    [{e['date']}] {e['kind']}: {e['detail']}")
        for label, m in a["stress_windows"].items():
            print(f"    {label}: getiri {m['total_return_pct']*100:+.2f}%, maksDD {m['max_drawdown_pct']*100:.2f}% ({m['start']}→{m['end']})")

    dest = Path(__file__).resolve().parent / "results" / "crisis_real.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nSonuç: {dest}")


def main() -> None:
    if sys.argv[1] == "--real":
        run_real(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        return
    shape = sys.argv[1]
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    results = []
    for seed in range(11, 11 + n_seeds):
        data, phases = generate(shape, seed)
        bh = [sum(r[i]["close"] / r[0]["close"] for r in data.values()) / len(data)
              for i in range(TRADING_DAYS)]
        peak = 0.0
        bh_dd = 0.0
        for v in bh:
            peak = max(peak, v)
            bh_dd = min(bh_dd, (v - peak) / peak)

        row = {"seed": seed, "phases": phases, "bh_total": bh[-1] / bh[0] - 1.0, "bh_dd": bh_dd, "arms": {}}
        trend_flags = market_trend_flags(data)
        for name, policy in ARMS.items():
            flags = trend_flags if name == "E_trend_kapisi" else None
            sim = simulate(
                BACKTEST_SYMBOLS, data, STARTING_CAPITAL,
                halt_policy=policy, trend_ok_by_date=flags,
            )
            total, cagr, dd, sharpe = compute_curve_metrics(sim.equity_curve)
            events = [
                {"date": d, "kind": t, "phase": phase_of(d, phases)}
                for d, t, _ in sim.halt_transitions
            ]
            row["arms"][name] = {
                "total_return_pct": total, "sharpe": sharpe, "max_drawdown_pct": dd,
                "trade_count": len(sim.trades),
                "halt_days": sum(1 for f in sim.halt_flags if f),
                "halt_days_pct": sum(1 for f in sim.halt_flags if f) / max(len(sim.halt_flags), 1),
                "halted_at_end": bool(sim.halt_flags and sim.halt_flags[-1]),
                "stopped": sim.stopped,
                "events": events,
            }
        results.append(row)
        # Özet satırı hangi kolların koşulduğuna göre kurulur (alt küme
        # koşularında A/B/C mevcut olmayabilir).
        parts = []
        for name, arm in row["arms"].items():
            ev = "".join(
                f" {e['kind']}@{e['phase']}" for e in arm["events"]
            ) or " olay-yok"
            parts.append(
                f"{name} {arm['total_return_pct']*100:+.1f}%"
                f"{'/kilit' if arm['halted_at_end'] else ''}"
                f"{'/DURDU' if arm['stopped'] else ''}"
                f" [{ev.strip()}]"
            )
        print(f"[{shape}] tohum {seed}: B&H {row['bh_total']*100:+.1f}%/DD {bh_dd*100:.1f}% | "
              + " | ".join(parts), flush=True)

    out = (
        Path(__file__).resolve().parent / "results" / "synthetic"
        / f"crisis_{shape}{ARM_SUFFIX}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"shape": shape, "runs": results}, indent=2), encoding="utf-8"
    )
    print(f"[{shape}] bitti")


if __name__ == "__main__":
    main()
