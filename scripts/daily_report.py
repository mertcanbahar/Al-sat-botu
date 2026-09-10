#!/usr/bin/env python3
"""Send the daily risk report for the paper portfolio to Telegram.

Reads the saved portfolio state (data/portfolio.json), marks it to market
with the latest close per held symbol, and reports portfolio value, open
positions, category exposure, drawdown, hit rate, and any risk warnings.

This script only reads the portfolio -- it never opens or closes a
position, and it never writes portfolio.json. Run it manually or from
.github/workflows/daily-report.yml.

Usage:
    python scripts/daily_report.py [days]
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import (
    CATEGORY_EXPOSURE_LIMIT_PCT,
    DRAWDOWN_RELEASE_PCT,
    MAX_DRAWDOWN_PCT,
    MAX_HALT_RESETS,
    MAX_OPEN_POSITIONS,
    source_for,
)
from alsatbotu.data import get_price_history
from notify.telegram import send_message
from portfolio.state import PortfolioState, load_state

# Warn before a limit is actually breached, at this fraction of it.
WARN_THRESHOLD = 0.9


def fetch_current_prices(state: PortfolioState, days: int = 7) -> dict[str, float]:
    """Latest close per held symbol; symbols that fail to fetch are left out.

    Each symbol is fetched from the same source it was opened against (see
    `alsatbotu.config.source_for`) -- stock tickers like AAPL don't exist as
    CoinGecko coin ids, so hardcoding one source here would silently fail
    to re-price every stock position and understate drawdown/stop warnings.

    A missing symbol falls back to its entry price in PortfolioState's
    valuation helpers, so a failed fetch understates movement rather than
    crashing the report.
    """
    prices: dict[str, float] = {}
    for symbol in state.open_positions:
        try:
            rows = get_price_history(symbol, source=source_for(symbol), days=days)
        except Exception as exc:  # noqa: BLE001 - report must survive a bad symbol
            print(f"{symbol}: failed to fetch current price ({exc})")
            continue
        if rows:
            prices[symbol] = rows[-1]["close"]
    return prices


def _hit_rate(state: PortfolioState) -> Optional[float]:
    if not state.closed_trades:
        return None
    wins = sum(1 for trade in state.closed_trades if trade.pnl > 0)
    return wins / len(state.closed_trades)


def halt_status_line(state: PortfolioState, equity: float) -> str:
    """Halt durumunun her gün görünen tek satırlık özeti.

    Uyarı bölümü yalnızca sorun varken konuşur; bu satır halt kapalıyken de
    yazılır, çünkü mekanizmayı canlıda izlerken "bugün ne durumdaydı"
    sorusunun cevabı raporda olmalı.
    """
    if state.stopped:
        return (
            f"Halt: 🛑 KALICI DURDURMA ({state.stop_reason}) — yeni ALIM yok, "
            "insan onayı bekleniyor"
        )

    drawdown = (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0
    resets = f"reset {state.halt_resets}/{MAX_HALT_RESETS}"
    if state.halted:
        release_equity = state.peak_equity * (1 - DRAWDOWN_RELEASE_PCT)
        since = f", {state.halted_marks} koşudur" if state.halted_marks else ""
        return (
            f"Halt: 🔴 AKTİF{since} — yeni ALIM yok. Çıkış: piyasa trendi yukarı dönerse "
            f"ya da equity {release_equity:,.2f} üstüne çıkarsa ({resets})"
        )

    headroom = state.peak_equity * (1 - MAX_DRAWDOWN_PCT)
    return (
        f"Halt: 🟢 yok — drawdown %{drawdown * 100:.2f}, "
        f"tetiklenme eşiği %{MAX_DRAWDOWN_PCT * 100:.0f} (equity {headroom:,.2f} altına inerse) "
        f"({resets})"
    )


def _warnings(state: PortfolioState, current_prices: dict[str, float], equity: float) -> list[str]:
    warnings: list[str] = []

    drawdown = (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0
    if state.stopped:
        warnings.append(
            f"🛑 BOT KALICI OLARAK DURDURULDU ({state.stop_reason}) — yeni ALIM yok. "
            "Devam etmesi için insan onayı gerekiyor: "
            "python scripts/resume_halt.py --onayla"
        )
    elif state.halted:
        # Halt'tan çıkış için gereken equity'yi rakamla söyle: "ne olursa açılır"
        # sorusunun cevabı raporda görünsün.
        release_equity = state.peak_equity * (1 - DRAWDOWN_RELEASE_PCT)
        warnings.append(
            f"Drawdown %{drawdown * 100:.2f} — yeni AL sinyalleri durduruldu "
            f"(limit %{MAX_DRAWDOWN_PCT * 100:.0f}, {state.halted_marks} koşudur halt'ta). "
            f"Halt, piyasa trendi yukarı dönünce ya da equity {release_equity:,.2f} "
            f"üstüne çıkınca (drawdown %{DRAWDOWN_RELEASE_PCT * 100:.0f}) kalkar; "
            f"kullanılan reset: {state.halt_resets}/{MAX_HALT_RESETS}"
        )
    elif drawdown >= MAX_DRAWDOWN_PCT * WARN_THRESHOLD:
        warnings.append(
            f"Drawdown %{drawdown * 100:.2f} — %{MAX_DRAWDOWN_PCT * 100:.0f} limitine yaklaşıyor"
        )

    if len(state.open_positions) >= MAX_OPEN_POSITIONS:
        warnings.append(
            f"Açık pozisyon limiti dolu ({len(state.open_positions)}/{MAX_OPEN_POSITIONS}) "
            "— yeni pozisyon açılamaz"
        )

    if equity > 0:
        categories = {position.category for position in state.open_positions.values()}
        for category in sorted(categories):
            share = state.category_exposure(category, current_prices) / equity
            if share > CATEGORY_EXPOSURE_LIMIT_PCT:
                warnings.append(
                    f"{category} kategorisi %{share * 100:.1f} ile "
                    f"%{CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f} limitini aştı"
                )
            elif share >= CATEGORY_EXPOSURE_LIMIT_PCT * WARN_THRESHOLD:
                warnings.append(
                    f"{category} kategorisi %{share * 100:.1f} ile "
                    f"%{CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f} limitine yaklaşıyor"
                )

    for symbol, position in state.open_positions.items():
        price = current_prices.get(symbol)
        if price is not None and price <= position.stop_price:
            warnings.append(
                f"{symbol} fiyatı {price:.4f}, stop seviyesi {position.stop_price:.4f} altında"
            )

    if state.cash <= 0:
        warnings.append("Nakit tükendi — yeni pozisyon açılamaz")

    return warnings


def build_report(
    state: PortfolioState,
    current_prices: dict[str, float],
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    equity = state.equity(current_prices)
    position_value = state.position_value(current_prices)
    total_return = (
        equity / state.starting_capital - 1.0 if state.starting_capital else 0.0
    )
    drawdown = (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0

    lines = [
        f"📊 Günlük Risk Raporu — {now:%Y-%m-%d}",
        "",
        f"Portföy değeri: {equity:,.2f} (başlangıca göre %{total_return * 100:+.2f})",
        f"  Nakit: {state.cash:,.2f}",
        f"  Pozisyonlar: {position_value:,.2f}",
        "",
        f"Açık pozisyonlar ({len(state.open_positions)}/{MAX_OPEN_POSITIONS}):",
    ]

    if state.open_positions:
        for symbol, position in state.open_positions.items():
            price = current_prices.get(symbol, position.entry_price)
            change = (price / position.entry_price - 1.0) if position.entry_price else 0.0
            lines.append(
                f"  • {symbol} ({position.category}): {position.quantity:.6f} adet, "
                f"giriş {position.entry_price:.4f} → {price:.4f} "
                f"(%{change * 100:+.2f}), stop {position.stop_price:.4f}"
            )
    else:
        lines.append("  • yok")

    lines.extend(["", "Kategori dağılımı:"])
    categories = {position.category for position in state.open_positions.values()}
    if categories and equity > 0:
        for category in sorted(categories):
            value = state.category_exposure(category, current_prices)
            lines.append(
                f"  • {category}: {value:,.2f} (%{value / equity * 100:.1f} / "
                f"limit %{CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f})"
            )
    else:
        lines.append("  • yok")

    hit_rate = _hit_rate(state)
    wins = sum(1 for trade in state.closed_trades if trade.pnl > 0)
    hit_rate_text = (
        f"%{hit_rate * 100:.1f} ({wins}/{len(state.closed_trades)} kapanmış işlem)"
        if hit_rate is not None
        else "henüz kapanmış işlem yok"
    )

    lines.extend(
        [
            "",
            f"Drawdown: %{drawdown * 100:.2f} (tepe {state.peak_equity:,.2f})",
            halt_status_line(state, equity),
            f"İsabet oranı: {hit_rate_text}",
            "",
            "⚠️ Uyarılar:",
        ]
    )

    warnings = _warnings(state, current_prices, equity)
    if warnings:
        lines.extend(f"  • {warning}" for warning in warnings)
    else:
        lines.append("  • yok")

    return "\n".join(lines)


def main(days: int = 7) -> None:
    state = load_state()
    current_prices = fetch_current_prices(state, days=days)
    report = build_report(state, current_prices)

    print(report)
    send_message(report)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
