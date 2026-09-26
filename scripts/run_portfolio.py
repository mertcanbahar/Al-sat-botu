#!/usr/bin/env python3
"""Run one paper-trading pass over the watchlist and update the portfolio.

For each symbol in `alsatbotu.config.WATCHLIST`:
  1. Fetch price history and evaluate the rule engine (alsatbotu.signal).
  2. Append the signal to the ledger (portfolio/ledger.py), regardless of
     whether it results in a trade.
  3. On BUY: ask the risk engine (engine/risk.py) whether to open a
     position and at what size; open it if approved.
  4. On SELL: close the open position for that symbol, if any.
  5. Send a Telegram message for BUY/SELL signals that are *new* -- i.e.
     the symbol's previously recorded decision was something else. HOLD is
     never notified, and a decision that simply persists across runs is
     not re-sent.

Portfolio state (data/portfolio.json) is saved once at the end. This
script does not touch Telegram, the AI layer, or cron -- it is meant to be
run manually (see .github/workflows/manual-portfolio.yml) or from a
scheduler that already exists elsewhere.

Usage:
    python scripts/run_portfolio.py [days]
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import (
    CATEGORY_EXPOSURE_LIMIT_PCT,
    CATEGORY_TRIM_PCT,
    DATA_DIR,
    MAX_HALT_RESETS,
    TREND_SMA_WINDOW,
    WATCHLIST,
)
from alsatbotu.data import get_price_history
from alsatbotu.indicators import add_indicators
from alsatbotu.signal import Decision, Signal, evaluate
from engine.risk import evaluate_buy, plan_category_trims, update_halt_state
from notify.telegram import is_configured as telegram_is_configured, send_message
from portfolio.ledger import last_decisions, log_signal
from portfolio.state import (
    close_position,
    load_state,
    open_position,
    reduce_position,
    save_state,
)

SIGNAL_LABELS = {Signal.BUY: "🟢 AL", Signal.SELL: "🔴 SAT"}

HEALTH_PATH = DATA_DIR / "health.json"
EQUITY_LEDGER_PATH = DATA_DIR / "equity.jsonl"


def _notify_signal(symbol: str, decision: Decision, price: float, action: str) -> bool:
    lines = [
        f"{SIGNAL_LABELS[decision.signal]} sinyali — {symbol}",
        f"Fiyat: {price:.4f}",
    ]
    if decision.reasons:
        lines.append("Tetikleyen kural:")
        lines.extend(f"  • {reason}" for reason in decision.reasons)
    lines.append(f"İşlem: {action}")
    return send_message("\n".join(lines))


def _module_status(ok_count: int, total: int) -> str:
    if total <= 0 or ok_count >= total:
        return "ok"
    if ok_count > 0:
        return "warn"
    return "error"


def _write_health(
    path: Path,
    total_symbols: int,
    fetch_ok: int,
    volume_ok: int,
    signal_count: int,
    open_positions: int,
    telegram_attempts: int,
    telegram_successes: int,
    unpriced_positions: Optional[dict[str, str]] = None,
) -> None:
    fetch_status = _module_status(fetch_ok, total_symbols)
    volume_status = _module_status(volume_ok, fetch_ok)

    if not telegram_is_configured():
        telegram_status, telegram_detail, telegram_code = "warn", "yapılandırılmadı", "W-TG"
    elif telegram_attempts == 0:
        telegram_status, telegram_detail, telegram_code = "ok", "bekleniyor", None
    elif telegram_successes == telegram_attempts:
        telegram_status, telegram_detail, telegram_code = "ok", "gonderildi", None
    elif telegram_successes > 0:
        telegram_status, telegram_detail, telegram_code = "warn", "kismen gonderildi", "W-TG"
    else:
        telegram_status, telegram_detail, telegram_code = "error", "gonderilemedi", "E-TG"

    def _module(name: str, status: str, detail: str, code: Optional[str] = None) -> dict:
        module = {"name": name, "status": status, "detail": detail}
        if code:
            module["code"] = code
        return module

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "modules": [
            _module(
                "twelvedata",
                fetch_status,
                f"{fetch_ok}/{total_symbols} sembol",
                None if fetch_status == "ok" else ("W-FETCH" if fetch_status == "warn" else "E-FETCH"),
            ),
            _module("indikator", _module_status(fetch_ok, total_symbols), f"{fetch_ok} sembol"),
            _module(
                "hacim",
                volume_status,
                f"{volume_ok}/{fetch_ok}",
                None if volume_status == "ok" else ("W-VOL" if volume_status == "warn" else "E-VOL"),
            ),
            _module("kural", "ok", f"{signal_count} sinyal"),
            _module("portfoy", "ok", f"{open_positions} pozisyon"),
            _stop_module(unpriced_positions or {}),
            _module("telegram", telegram_status, telegram_detail, telegram_code),
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def _stop_module(unpriced_positions: dict[str, str]) -> dict:
    """Stop kontrolünün kapsamı: fiyatı gelmeyen açık pozisyon var mı?"""
    if not unpriced_positions:
        return {"name": "stop", "status": "ok", "detail": "tüm açık pozisyonlar kontrol edildi"}
    return {
        "name": "stop",
        "status": "warn",
        "detail": f"kontrol edilemedi: {', '.join(unpriced_positions)}",
        "code": "W-STOP",
    }


def _order_for_fetch(watchlist: list[dict], held: set[str]) -> list[dict]:
    """Açık pozisyonu olan semboller önce çekilir.

    API kotası koşunun ortasında biterse fiyatsız kalan, stop'u izlenmeyen
    bir pozisyon değil, yalnızca yeni sinyal bakılamayan bir sembol olsun.
    Sıralama kararlı: grupların kendi içindeki sırası izleme listesindeki gibi.
    """
    return sorted(watchlist, key=lambda entry: entry["symbol"] not in held)


def _unpriced_warning(unpriced_positions: dict[str, str], state) -> str:
    lines = ["⚠️ Stop kontrolü yapılamadı — açık pozisyonun fiyatı alınamadı"]
    for symbol, reason in unpriced_positions.items():
        position = state.open_positions[symbol]
        lines.append(
            f"  • {symbol} (stop {position.stop_price:.4f}, giriş {position.entry_price:.4f}): {reason}"
        )
    lines.append(
        "Bu koşuda bu pozisyonlar stop'la kapatılamaz; değerleme giriş fiyatıyla yapıldı."
    )
    return "\n".join(lines)


def _append_equity(path: Path, equity: float, timestamp: Optional[str] = None) -> None:
    record = {"date": timestamp or datetime.now(timezone.utc).isoformat(), "value": equity}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")


def _short_error(exc: Exception) -> str:
    """Telegram/panel için kısa hata metni; API anahtarını içeren URL'yi atar."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return "API hız limiti (HTTP 429)"
    text = str(exc).split(" for url:")[0]
    return text[:160]


def _market_trend_ok(history: dict[str, list[dict]], window: int = TREND_SMA_WINDOW) -> Optional[bool]:
    """Piyasa proxy'si kendi SMA<window>'unun üstünde mi? (halt'ın trend kapısı)

    İzlenen sembollerin eşit ağırlıklı endeksi: her sembol kendi ilk
    kapanışına normalize edilir, her gün yalnızca o gün verisi olan
    semboller ortalamaya girer. Backtest'teki
    `backtest.portfolio_backtest.market_trend_flags` ile aynı formül.

    Yeterli geçmiş yoksa None döner: trend bilinmiyor demektir, halt'ı
    trend gerekçesiyle açmayız.
    """
    by_date: dict[str, list[float]] = {}
    for rows in history.values():
        if not rows or not rows[0].get("close"):
            continue
        base = rows[0]["close"]
        for row in rows:
            if row.get("close") is None:
                continue
            by_date.setdefault(row["timestamp"].date().isoformat(), []).append(row["close"] / base)

    dates = sorted(by_date)
    if len(dates) < window:
        return None
    index = [sum(by_date[d]) / len(by_date[d]) for d in dates]
    return index[-1] > sum(index[-window:]) / window


def _enforce_stop(state, symbol: str, price: float, when: str) -> bool:
    """Fiyat stop'un altındaysa pozisyonu SELL sinyali beklemeden kapat.

    Stop fiyatı şimdiye kadar yalnızca pozisyon boyutlandırmasında ve günlük
    raporun bir uyarı satırında kullanılıyordu; kapatma kararını tek başına
    kural motorunun SELL sinyali veriyordu. Kural HOLD derken stop delinmiş
    olabiliyor (canlıda NVDA: değerlendirme motoru stop'la kapattı, JSON
    portföyü pozisyonu açık gösterdi) -- artık stop'a uyulur.
    """
    position = state.open_positions.get(symbol)
    if position is None or price > position.stop_price:
        return False

    trade = close_position(
        state, symbol=symbol, exit_price=price, exit_date=when, reason="stop_loss"
    )
    if trade is None:
        return False
    print(
        f"{symbol}: STOP {trade.quantity:.6f} @ {price:.4f} "
        f"(stop {position.stop_price:.4f}, pnl {trade.pnl_pct * 100:.2f}%)"
    )
    return True


def _apply_category_trims(state, current_prices: dict[str, float], when: str) -> None:
    """Sert sınırı (%45) aşan kategorileri giriş limitine (%40) geri çek."""
    for trim in plan_category_trims(state, current_prices):
        trade = reduce_position(
            state,
            symbol=trim.symbol,
            quantity=trim.quantity,
            exit_price=trim.price,
            exit_date=when,
            reason="category_trim",
        )
        if trade is None:
            continue
        print(
            f"{trim.symbol}: TRIM {trade.quantity:.6f} @ {trim.price:.4f} — "
            f"{trim.category} kategorisi %{trim.share_before * 100:.1f} ile "
            f"%{CATEGORY_TRIM_PCT * 100:.0f} sert sınırını aştı, "
            f"%{CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f}'a çekiliyor"
        )


def run(days: int = 60) -> None:
    state = load_state()
    # Read before any new signal is appended, so it reflects the previous run.
    previous_decisions = last_decisions()
    current_prices: dict[str, float] = {}
    latest_by_symbol: dict[str, dict] = {}
    history_by_symbol: dict[str, list[dict]] = {}

    fetch_errors: dict[str, str] = {}

    fetch_ok = 0
    volume_ok = 0
    signal_count = 0
    telegram_attempts = 0
    telegram_successes = 0

    for entry in _order_for_fetch(WATCHLIST, set(state.open_positions)):
        symbol = entry["symbol"]
        category = entry["category"]
        source = entry.get("source", "coingecko")

        try:
            rows = get_price_history(symbol, source=source, days=days)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't stop the run
            print(f"{symbol}: failed to fetch price history ({exc})")
            fetch_errors[symbol] = _short_error(exc)
            continue

        if len(rows) < 2:
            print(f"{symbol}: not enough candles to evaluate ({len(rows)})")
            fetch_errors[symbol] = f"yetersiz mum ({len(rows)})"
            continue

        history_by_symbol[symbol] = rows
        decision = evaluate(rows)
        latest = add_indicators(rows)[-1]
        price = latest["close"]
        current_prices[symbol] = price
        latest_by_symbol[symbol] = latest

        fetch_ok += 1
        if latest.get("volume") is not None:
            volume_ok += 1
        if decision.signal != Signal.HOLD:
            signal_count += 1

        log_signal(symbol, decision, price, latest)
        is_new_signal = previous_decisions.get(symbol) != decision.signal.value

        # Stop, kural motorundan önce gelir. Aynı koşuda stop'la çıkıp
        # tekrar girmemek için sembolün geri kalan işlemleri atlanır.
        if _enforce_stop(state, symbol, price, latest["timestamp"].isoformat()):
            continue

        if decision.signal == Signal.BUY:
            risk_decision = evaluate_buy(
                state, symbol, category, price, latest["atr"], current_prices
            )
            if risk_decision.approved:
                open_position(
                    state,
                    symbol=symbol,
                    category=category,
                    quantity=risk_decision.quantity,
                    entry_price=price,
                    entry_date=latest["timestamp"].isoformat(),
                    stop_price=risk_decision.stop_price,
                )
                action = (
                    f"{risk_decision.quantity:.6f} adet alındı "
                    f"(stop {risk_decision.stop_price:.4f})"
                )
                if risk_decision.capped_by:
                    action += f" — boyut sınırlandı: {risk_decision.capped_by}"
                print(f"{symbol}: BUY {risk_decision.quantity:.6f} @ {price:.4f}")
            else:
                action = f"risk motoru reddetti — {'; '.join(risk_decision.reasons)}"
                print(f"{symbol}: BUY signal rejected by risk engine: {'; '.join(risk_decision.reasons)}")
            if is_new_signal:
                telegram_attempts += 1
                if _notify_signal(symbol, decision, price, action):
                    telegram_successes += 1
        elif decision.signal == Signal.SELL:
            trade = close_position(
                state,
                symbol=symbol,
                exit_price=price,
                exit_date=latest["timestamp"].isoformat(),
                reason="; ".join(decision.reasons) or "SELL signal",
            )
            if trade is not None:
                action = (
                    f"{trade.quantity:.6f} adet satıldı, "
                    f"P&L {trade.pnl:+.2f} ({trade.pnl_pct * 100:+.2f}%)"
                )
                print(f"{symbol}: SELL {trade.quantity:.6f} @ {price:.4f} (pnl {trade.pnl_pct * 100:.2f}%)")
            else:
                action = "açık pozisyon yok, işlem yapılmadı"
                print(f"{symbol}: SELL signal, no open position")
            if is_new_signal:
                telegram_attempts += 1
                if _notify_signal(symbol, decision, price, action):
                    telegram_successes += 1
        else:
            print(f"{symbol}: HOLD @ {price:.4f}")

    # Fiyatı gelmeyen açık pozisyonun stop'u bu koşuda kontrol edilemedi.
    # Bu sessizce geçilmez: konsola, health.json'a ve Telegram'a yazılır.
    # İzleme listesinden çıkarılmış ama hâlâ açık bir pozisyon da buraya düşer.
    unpriced_positions = {
        symbol: fetch_errors.get(symbol, "izleme listesinde değil, fiyatı çekilmedi")
        for symbol in state.open_positions
        if symbol not in current_prices
    }
    if unpriced_positions:
        warning = _unpriced_warning(unpriced_positions, state)
        print(warning)
        telegram_attempts += 1
        if send_message(warning):
            telegram_successes += 1

    # Kategori kırpması alım/satımlardan sonra, equity işaretlemesinden önce:
    # halt bu koşunun nihai portföyünü görsün.
    _apply_category_trims(state, current_prices, datetime.now(timezone.utc).isoformat())

    # Halt durum makinesini bu koşunun equity işaretlemesiyle ilerlet.
    # Bir sonraki koşudaki ALIM'lar buradan çıkan duruma bakar (backtest'te
    # de aynı sıra geçerli: işaretle, sonra ertesi gün işlem yap).
    trend_ok = _market_trend_ok(history_by_symbol)
    halt_event = update_halt_state(
        state,
        current_prices,
        mark_date=datetime.now(timezone.utc).isoformat(),
        trend_ok=trend_ok,
    )
    equity = halt_event.equity
    print(f"Piyasa trendi (SMA{TREND_SMA_WINDOW}): " + {True: "yukarı", False: "aşağı", None: "bilinmiyor (yetersiz geçmiş)"}[trend_ok])
    if halt_event.transition:
        print(f"HALT [{halt_event.transition}]: {halt_event.detail}")
    save_state(state)

    _write_health(
        HEALTH_PATH,
        total_symbols=len(WATCHLIST),
        fetch_ok=fetch_ok,
        volume_ok=volume_ok,
        signal_count=signal_count,
        open_positions=len(state.open_positions),
        telegram_attempts=telegram_attempts,
        telegram_successes=telegram_successes,
        unpriced_positions=unpriced_positions,
    )
    _append_equity(EQUITY_LEDGER_PATH, equity)

    print()
    print(f"Cash: {state.cash:.2f}")
    print(f"Equity: {equity:.2f} (peak {state.peak_equity:.2f})")
    if state.stopped:
        print(f"DURUM: bot kalıcı olarak durduruldu ({state.stop_reason}). "
              "Devam için: python scripts/resume_halt.py --onayla")
    elif state.halted:
        print(f"DURUM: drawdown halt aktif ({state.halted_marks} işaretlemedir), "
              f"yeni ALIM yok. Reset hakkı: {state.halt_resets}/{MAX_HALT_RESETS}")
    if state.paused:
        print(f"DURUM: bot Telegram'dan manuel duraklatıldı ({state.paused_reason}), yeni ALIM yok.")
    print(f"Open positions: {len(state.open_positions)}")
    for symbol, position in state.open_positions.items():
        print(
            f"  {symbol}: {position.quantity:.6f} @ {position.entry_price:.4f} "
            f"(stop {position.stop_price:.4f}, category {position.category})"
        )
    print(f"Closed trades: {len(state.closed_trades)}")


def _parse_days(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return int(argv[0]) if argv else 60


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(_parse_days())
