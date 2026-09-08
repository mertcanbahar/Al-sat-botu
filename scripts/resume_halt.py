#!/usr/bin/env python3
"""Kalıcı olarak durdurulmuş botu insan onayıyla yeniden başlatır.

`engine.risk.update_halt_state()` iki durumda botu KALICI olarak durdurur
(`state.stopped = True`):

  - `max_resets`: izin verilen kısmi peak reset'leri tükendi, hesap hâlâ
    halt'ta ve nakitte.
  - `hard_floor`: equity, başlangıç sermayesinin `HALT_HARD_FLOOR_PCT`
    katının altına indi.

Durdurma yalnızca buradan kalkar. Otomasyonun hiçbir parçası -- ne koşucu,
ne iyileştirme döngüsü, ne de risk motoru -- `stopped` bayrağını kendiliğinden
temizlemez; bu, "onay beklerken sistem ne yapsın?" sorusunun kasıtlı cevabıdır:
**durur ve bekler.** Mevcut pozisyonların SATIŞI çalışmaya devam eder, sadece
yeni ALIM yapılmaz.

Kullanım:
    python scripts/resume_halt.py                 # durumu göster, hiçbir şey değiştirme
    python scripts/resume_halt.py --onayla        # durdurmayı kaldır, peak'i koru
    python scripts/resume_halt.py --onayla --peak-sifirla
        # durdurmayı kaldır ve peak'i güncel equity'ye çek (drawdown sayacı sıfırlanır)
    python scripts/resume_halt.py --onayla --sermaye-sifirla --peak-sifirla
        # sert taban yüzünden durmuşsa: sermaye tabanını da güncel equity'ye çek

`--peak-sifirla` ve `--sermaye-sifirla` bilinçli kararlardır: ikisi de bota
yeniden düşme alanı açar. Onaysız asla yapılmaz. Durduran koşul hâlâ
geçerliyse script bunu söyler ve gerekli bayrak verilmeden değişiklik yapmaz,
çünkü aksi halde bot bir sonraki koşuda sessizce yeniden dururdu.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.config import (
    HALT_HARD_FLOOR_PCT,
    MAX_DRAWDOWN_PCT,
    MAX_HALT_RESETS,
    source_for,
)
from alsatbotu.data import get_price_history
from portfolio.state import PortfolioState, load_state, save_state


def current_prices(state: PortfolioState, days: int = 7) -> dict[str, float]:
    """Açık pozisyonların son kapanışları; çekilemeyen sembol atlanır."""
    prices: dict[str, float] = {}
    for symbol in state.open_positions:
        try:
            rows = get_price_history(symbol, source=source_for(symbol), days=days)
        except Exception as exc:  # noqa: BLE001 - fiyat çekilemezse giriş fiyatı kullanılır
            print(f"  {symbol}: fiyat çekilemedi ({exc}), giriş fiyatı varsayılacak")
            continue
        if rows:
            prices[symbol] = rows[-1]["close"]
    return prices


def describe(state: PortfolioState, equity: float) -> str:
    drawdown = (
        (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0
    )
    lines = [
        f"Equity          : {equity:,.2f}",
        f"Peak            : {state.peak_equity:,.2f}",
        f"Drawdown        : %{drawdown * 100:.2f} (halt limiti %{MAX_DRAWDOWN_PCT * 100:.0f})",
        f"Açık pozisyon   : {len(state.open_positions)}",
        f"Kullanılan reset: {state.halt_resets}/{MAX_HALT_RESETS}",
        f"Halt            : {'AKTİF' if state.halted else 'yok'}",
        f"Kalıcı durdurma : {state.stop_reason if state.stopped else 'yok'}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onayla",
        action="store_true",
        help="Kalıcı durdurmayı kaldır (insan onayı). Verilmezse hiçbir şey değişmez.",
    )
    parser.add_argument(
        "--peak-sifirla",
        action="store_true",
        help="Durdurmayı kaldırırken peak'i güncel equity'ye çek (drawdown sıfırlanır).",
    )
    parser.add_argument(
        "--sermaye-sifirla",
        action="store_true",
        help=(
            "Başlangıç sermayesini güncel equity'ye çek. Sert taban (hard_floor) "
            "bu değere göre hesaplandığı için, taban yüzünden durmuş bir botu "
            "yeniden başlatmanın TEK yolu budur."
        ),
    )
    args = parser.parse_args(argv)

    state = load_state()
    prices = current_prices(state)
    equity = state.equity(prices)

    print(describe(state, equity))
    print()

    if not state.stopped:
        print("Bot kalıcı olarak durdurulmuş değil; yapılacak bir şey yok.")
        return 0

    if not args.onayla:
        print(
            "Bot kalıcı olarak durdurulmuş durumda ve öyle kalacak.\n"
            "Devam ettirmek için bu komutu --onayla ile tekrar çalıştırın."
        )
        return 0

    # Onay verilmiş olsa bile, durduran koşul hâlâ geçerliyse bot bir sonraki
    # koşuda anında yeniden durur. Sessizce olmasın.
    floor = state.starting_capital * HALT_HARD_FLOOR_PCT
    if equity < floor and not args.sermaye_sifirla:
        print(
            f"UYARI: equity {equity:,.2f} hâlâ sert tabanın ({floor:,.2f}) altında. "
            "Durdurma kaldırılsa da bot bir sonraki koşuda yeniden duracak.\n"
            "       Gerçekten devam etmesini istiyorsanız --sermaye-sifirla ekleyin "
            "(başlangıç sermayesi güncel equity'ye çekilir).\n"
            "       Hiçbir şey değiştirilmedi."
        )
        return 1

    drawdown = (state.peak_equity - equity) / state.peak_equity if state.peak_equity > 0 else 0.0
    if drawdown >= MAX_DRAWDOWN_PCT and not args.peak_sifirla:
        print(
            f"UYARI: drawdown hâlâ %{drawdown * 100:.2f} (halt limiti "
            f"%{MAX_DRAWDOWN_PCT * 100:.0f}). Kalıcı durdurma kalkar ama bot bir "
            "sonraki koşuda doğrudan normal halt'a girer.\n"
            "       Sıfırdan başlamasını istiyorsanız --peak-sifirla ekleyin."
        )

    state.stopped = False
    state.stop_reason = None
    state.halted = False
    state.halted_since = None
    state.halted_marks = 0
    state.halt_resets = 0
    if args.sermaye_sifirla:
        state.starting_capital = equity
    if args.peak_sifirla:
        state.peak_equity = equity
    save_state(state)

    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"[{stamp}] Kalıcı durdurma insan onayıyla kaldırıldı.")
    print(f"  Peak: {state.peak_equity:,.2f}" + (" (equity'ye çekildi)" if args.peak_sifirla else " (korundu)"))
    print(
        f"  Başlangıç sermayesi: {state.starting_capital:,.2f}"
        + (" (equity'ye çekildi)" if args.sermaye_sifirla else " (korundu)")
    )
    print("  Reset sayacı sıfırlandı; bot bir sonraki koşuda yeniden ALIM yapabilir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
