"""Risk engine: position sizing and portfolio-level guardrails for paper trading.

Rules:
  - Position size risks at most `RISK_PER_TRADE_PCT` (2%) of current equity,
    sized off the distance between entry price and the ATR stop.
  - The ATR stop uses the same multiplier as the SELL rule in
    `alsatbotu.signal` (entry_price - ATR_STOP_MULTIPLIER * atr), so a
    position's stop is consistent with the rule that would exit it.
  - No single category (see `alsatbotu.config.SYMBOL_CATEGORIES`) may hold
    more than `CATEGORY_EXPOSURE_LIMIT_PCT` (40%) of equity.
  - At most `MAX_OPEN_POSITIONS` (8) positions open at once.
  - A trade whose sized notional falls below `MIN_POSITION_NOTIONAL` is
    rejected outright rather than opened as a dust-sized position.
  - No new BUYs while the portfolio is drawdown-halted; existing positions
    may still be sold. The halt is a latching state with hysteresis, not an
    instantaneous test -- see `HaltPolicy` and `update_halt_state()` below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from alsatbotu.config import (
    CATEGORY_EXPOSURE_LIMIT_PCT,
    DRAWDOWN_RELEASE_PCT,
    HALT_HARD_FLOOR_PCT,
    HALT_RESET_AFTER_MARKS,
    HALT_RESET_FRACTION,
    MAX_DRAWDOWN_PCT,
    MAX_HALT_RESETS,
    MAX_OPEN_POSITIONS,
    MIN_HALT_MARKS,
    MIN_POSITION_NOTIONAL,
    RISK_PER_TRADE_PCT,
)
from alsatbotu.signal import ATR_STOP_MULTIPLIER
from portfolio.state import PortfolioState


def compute_atr_stop(entry_price: float, atr: float) -> float:
    return entry_price - ATR_STOP_MULTIPLIER * atr


def compute_position_size(equity: float, entry_price: float, stop_price: float) -> float:
    """Quantity to buy so that a stop-out risks `RISK_PER_TRADE_PCT` of equity."""
    risk_per_unit = entry_price - stop_price
    if risk_per_unit <= 0:
        return 0.0
    risk_budget = equity * RISK_PER_TRADE_PCT
    return risk_budget / risk_per_unit


@dataclass(frozen=True)
class HaltPolicy:
    """Drawdown halt'ın tüm parametreleri tek yerde.

    Varsayılanı `DEFAULT_HALT_POLICY` (alsatbotu.config'ten okunur). Süpürme
    (backtest/halt_sweep.py) alternatif politikaları buradan geçirir; canlı
    kod hiçbir zaman kendi eşiğini uydurmaz.
    """

    halt_pct: float = MAX_DRAWDOWN_PCT
    # None = histerezis yok (eski tek yönlü mandal davranışı, karşılaştırma için).
    release_pct: Optional[float] = DRAWDOWN_RELEASE_PCT
    min_halt_marks: int = MIN_HALT_MARKS
    reset_after_marks: int = HALT_RESET_AFTER_MARKS
    reset_fraction: float = HALT_RESET_FRACTION
    max_resets: int = MAX_HALT_RESETS
    hard_floor_pct: float = HALT_HARD_FLOOR_PCT

    @property
    def latching(self) -> bool:
        """Serbest bırakma yoksa kural eski tek yönlü mandal gibi davranır."""
        return self.release_pct is None


DEFAULT_HALT_POLICY = HaltPolicy()

# Kalıcı durdurma nedenleri (durum dosyasına yazılır, rapora çıkar).
STOP_REASON_MAX_RESETS = "max_resets"
STOP_REASON_HARD_FLOOR = "hard_floor"


@dataclass
class HaltEvent:
    """Bir equity işaretlemesinde halt durumunda ne değiştiğinin özeti."""

    transition: Optional[str]  # "halted" | "released" | "reset" | "stopped" | None
    equity: float
    peak_equity: float
    drawdown: float
    halted: bool
    stopped: bool
    detail: str = ""


def _drawdown(equity: float, peak: float) -> float:
    return (peak - equity) / peak if peak > 0 else 0.0


def update_halt_state(
    state: PortfolioState,
    current_prices: dict[str, float],
    policy: Optional[HaltPolicy] = None,
    mark_date: Optional[str] = None,
    trend_ok: Optional[bool] = None,
) -> HaltEvent:
    """Equity'yi işaretle, peak'i güncelle ve halt durum makinesini ilerlet.

    Her equity işaretlemesinde tam bir kez çağrılmalı: canlı koşuda
    (scripts/run_portfolio.py) koşu sonunda, backtest'te her simülasyon
    gününde. `evaluate_buy()` bu fonksiyonun bıraktığı bayrağı okur, yani
    bir ALIM her zaman *bir önceki* işaretlemenin durumuna göre karara
    bağlanır -- canlı koşu ile backtest bu konuda birebir aynı davranır.

    Durum geçişleri:
      AKTİF  -> HALT     : drawdown >= halt_pct
      HALT   -> AKTİF    : en az min_halt_marks geçmiş VE (piyasa trendi
                           yukarı döndü VEYA drawdown <= release_pct)
      HALT   -> AKTİF    : reset_after_marks geçmiş VE açık pozisyon yok
                           (peak, equity'ye doğru reset_fraction kadar çekilir)
      HALT   -> DURDU    : reset hakkı bitmiş (max_resets)
      her an -> DURDU    : equity, başlangıç sermayesinin hard_floor_pct'sinin altında

    DURDU kalıcıdır ve yalnızca insan onayıyla kalkar
    (scripts/resume_halt.py); bu fonksiyon onu asla kendiliğinden açmaz.
    """
    policy = policy or DEFAULT_HALT_POLICY

    equity = state.equity(current_prices)
    state.peak_equity = max(state.peak_equity, equity)
    drawdown = _drawdown(equity, state.peak_equity)

    def event(transition: Optional[str], detail: str = "") -> HaltEvent:
        return HaltEvent(
            transition=transition,
            equity=equity,
            peak_equity=state.peak_equity,
            drawdown=drawdown,
            halted=state.halted,
            stopped=state.stopped,
            detail=detail,
        )

    # Kalıcı durdurma her şeyin önünde: insan onayı gelene kadar hiçbir şey değişmez.
    if state.stopped:
        return event(None, "Kalıcı durdurma aktif; insan onayı bekleniyor.")

    # Sert taban: sermayenin yarısı gitmişse eşik/histerezis tartışması biter.
    floor = state.starting_capital * policy.hard_floor_pct
    if state.starting_capital > 0 and equity < floor:
        state.stopped = True
        state.stop_reason = STOP_REASON_HARD_FLOOR
        state.halted = True
        return event(
            "stopped",
            f"Equity {equity:.2f}, sert tabanın ({floor:.2f}) altına düştü. "
            "Bot kalıcı olarak durduruldu; devam için insan onayı gerekiyor.",
        )

    if not state.halted:
        if drawdown >= policy.halt_pct:
            state.halted = True
            state.halted_since = mark_date
            state.halted_marks = 0
            return event(
                "halted",
                f"Drawdown %{drawdown * 100:.2f} >= %{policy.halt_pct * 100:.0f}; "
                "yeni ALIM durduruldu.",
            )
        return event(None)

    # -- Halt aktif --------------------------------------------------------
    state.halted_marks += 1

    # policy.latching iken release_pct None'dur; karşılaştırmayı guard'ın
    # arkasında tut.
    recovered = not policy.latching and drawdown <= policy.release_pct
    if (
        not policy.latching
        and state.halted_marks >= policy.min_halt_marks
        and (recovered or trend_ok)
    ):
        state.halted = False
        state.halted_since = None
        state.halted_marks = 0
        if recovered:
            why = f"Drawdown %{drawdown * 100:.2f} <= %{policy.release_pct * 100:.0f}; toparlanma"
        else:
            # Trend döndü ama equity hâlâ halt bandının içinde. Ölçütü de
            # güncellemezsek kural ertesi işaretlemede yeniden tetiklenir ve
            # halt çırpınır (ölçüldü: tek koşuda 9 döngü). Peak, drawdown tam
            # release_pct olacak seviyeye çekilir: koruma korunur (sonraki
            # halt yeni peak'in halt_pct altında), anında yeniden tetiklenmez.
            old_peak = state.peak_equity
            state.peak_equity = min(old_peak, equity / (1 - policy.release_pct))
            why = (
                "Piyasa trendi yukarı döndü (trend kapısı); peak "
                f"{old_peak:.2f} -> {state.peak_equity:.2f} çekildi"
            )
        return event("released", f"{why} ile halt kalktı.")

    # Nakitteki bir hesabın equity'si sabittir: toparlanma yapısal olarak
    # imkânsız, tek çıkış peak'i aşağı çekmek.
    if (
        not policy.latching
        and state.halted_marks >= policy.reset_after_marks
        and not state.open_positions
    ):
        if state.halt_resets >= policy.max_resets:
            state.stopped = True
            state.stop_reason = STOP_REASON_MAX_RESETS
            return event(
                "stopped",
                f"{state.halt_resets} kısmi reset'ten sonra hâlâ halt'ta ve nakitte. "
                "Bot kalıcı olarak durduruldu; devam için insan onayı gerekiyor.",
            )

        old_peak = state.peak_equity
        state.peak_equity = equity + policy.reset_fraction * (old_peak - equity)
        state.halt_resets += 1
        state.halted = False
        state.halted_since = None
        state.halted_marks = 0
        return event(
            "reset",
            f"{policy.reset_after_marks} işaretlemedir halt'ta ve açık pozisyon yok. "
            f"Peak {old_peak:.2f} -> {state.peak_equity:.2f} çekildi "
            f"({state.halt_resets}/{policy.max_resets} reset), halt kalktı.",
        )

    return event(None)


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    quantity: float = 0.0
    stop_price: float = 0.0
    capped_by: str | None = None


def evaluate_buy(
    state: PortfolioState,
    symbol: str,
    category: str,
    entry_price: float,
    atr: float,
    current_prices: dict[str, float],
) -> RiskDecision:
    """Decide whether to open a new position and, if so, at what size.

    Available cash and the category exposure cap *size down* the position
    rather than veto it: the 2%-risk quantity is what the trade would like
    to be, and the limits are the room it actually has. Only a limit with
    no room left at all (or a blocked portfolio) rejects the trade.

    Halt burada yeniden hesaplanmaz: `update_halt_state()`'in son
    işaretlemede bıraktığı durum okunur. Böylece eşik/histerezis mantığı
    tek bir yerde yaşar ve canlı koşu ile backtest aynı kararı verir.
    """
    equity = state.equity(current_prices)
    reasons: list[str] = []

    if symbol in state.open_positions:
        reasons.append(f"Position already open for {symbol}")

    if state.stopped:
        reasons.append(
            f"Bot kalıcı olarak durduruldu ({state.stop_reason}); "
            "devam için insan onayı gerekiyor"
        )
    elif state.halted:
        reasons.append(
            f"Drawdown halt: equity {equity:.2f}, peak {state.peak_equity:.2f} "
            f"altında (%{_drawdown(equity, state.peak_equity) * 100:.2f}), "
            f"{state.halted_marks} işaretlemedir halt'ta"
        )

    if len(state.open_positions) >= MAX_OPEN_POSITIONS:
        reasons.append(f"Max open positions reached ({MAX_OPEN_POSITIONS})")

    if atr is None or atr <= 0:
        reasons.append("No valid ATR available to size a stop")

    if reasons:
        return RiskDecision(approved=False, reasons=reasons)

    stop_price = compute_atr_stop(entry_price, atr)
    quantity = compute_position_size(equity, entry_price, stop_price)
    if quantity <= 0:
        return RiskDecision(
            approved=False,
            reasons=["Computed position size is zero (stop not below entry)"],
            stop_price=stop_price,
        )

    category_room = (
        equity * CATEGORY_EXPOSURE_LIMIT_PCT - state.category_exposure(category, current_prices)
    )
    limits = {
        "cash": state.cash / entry_price,
        f"category {category!r} {CATEGORY_EXPOSURE_LIMIT_PCT * 100:.0f}% limit": (
            max(category_room, 0.0) / entry_price
        ),
    }

    capped_by = None
    for label, max_quantity in limits.items():
        if max_quantity < quantity:
            quantity = max_quantity
            capped_by = label

    # Sıfır değil, "anlamsız küçük" de kabul edilmez: nakit tükendiğinde
    # cash/entry_price pozitif ama toz mertebesinde bir sayı olur ve eski
    # `quantity <= 0` kontrolünden geçip 0.000000 adetlik kayıt yaratırdı.
    notional = quantity * entry_price
    if quantity <= 0 or notional < MIN_POSITION_NOTIONAL:
        exhausted = capped_by or "position sizing"
        return RiskDecision(
            approved=False,
            reasons=[
                f"No room to open a position: {exhausted} leaves only "
                f"{notional:.2f} of notional (minimum {MIN_POSITION_NOTIONAL:.2f})"
            ],
            stop_price=stop_price,
        )

    return RiskDecision(
        approved=True, quantity=quantity, stop_price=stop_price, capped_by=capped_by
    )
