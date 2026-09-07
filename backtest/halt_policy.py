#!/usr/bin/env python3
"""Halt politikaları: canlıdaki mandal ve geri alınmış "v1" durum makinesi.

Bu modül **yalnızca backtest içindir.** Canlı davranış `engine/risk.py`
içindeki sabit %20 mandalıdır ve bu dosya onu değiştirmez -- `6254c93`
ile alınan geri alma kararı yürürlükte. Buradaki v1 durum makinesi,
`1fc8e31` commit'indeki `engine.risk.update_halt_state()`'in birebir
portudur; tek fark, `portfolio.state.PortfolioState`'e alan eklemek
yerine halt durumunu ayrı bir `HaltController` nesnesinde tutmasıdır
(canlı durum dosyasının şeması değişmesin diye).

Politika kolları
----------------
`LEGACY_20`  : durum makinesi *değil*, karşılaştırma etiketidir. Bu kolda
               simülasyon canlı kodu (`engine.risk.is_drawdown_halted`)
               olduğu gibi çağırır: her gün anlık yeniden hesap, kalıcı
               durum yok.
`V1`         : histerezis + kısmi peak reset'i + sert taban %50.
`V1_FLOOR30` : aynısı, sert taban %30 -- yani bot çöküşün daha derinine
               kadar çalışmaya devam eder, kalıcı durdurma daha geç gelir.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio.state import PortfolioState  # noqa: E402

# Kalıcı durdurma nedenleri (1fc8e31 ile aynı isimler).
STOP_REASON_MAX_RESETS = "max_resets"
STOP_REASON_HARD_FLOOR = "hard_floor"

# `evaluate_buy()` halt'ı kendi başına hesaplamasın diye geçilen eşik:
# drawdown tanım gereği 1.0'ı aşamaz, yani bu eşik hiçbir zaman tetiklenmez.
# Halt kararını bu modüldeki durum makinesi verir.
HALT_DELEGATED_TO_POLICY = 2.0

# `halt_sweep.halt_stats()` engellenen sinyalleri bu önekle sayar; v1'in
# ürettiği red gerekçeleri de aynı önekle başlar ki iki kol aynı ölçülsün.
HALT_REASON_PREFIX = "Drawdown halt"


@dataclass(frozen=True)
class HaltPolicy:
    """Drawdown halt'ın tüm parametreleri tek yerde."""

    name: str
    halt_pct: float = 0.20
    # None = histerezis yok (tek yönlü mandal).
    release_pct: Optional[float] = 0.10
    min_halt_marks: int = 10
    reset_after_marks: int = 60
    reset_fraction: float = 0.5
    max_resets: int = 2
    hard_floor_pct: float = 0.50

    @property
    def latching(self) -> bool:
        """Serbest bırakma yoksa kural eski tek yönlü mandal gibi davranır."""
        return self.release_pct is None


# Bulgu raporunun (backtest/halt_threshold_findings.md) önerdiği v1 parametreleri:
# H %20, R %10, reset 60 işaretleme x 0.5, en fazla 2 reset, sert taban %50.
V1 = HaltPolicy(name="v1")
V1_FLOOR30 = HaltPolicy(name="v1_taban30", hard_floor_pct=0.30)


@dataclass
class HaltEvent:
    """Bir equity işaretlemesinde halt durumunda ne değiştiğinin özeti."""

    transition: Optional[str]  # "halted" | "released" | "reset" | "stopped" | None
    date: Optional[str]
    equity: float
    peak_equity: float
    drawdown: float
    halted: bool
    stopped: bool
    detail: str = ""


def _drawdown(equity: float, peak: float) -> float:
    return (peak - equity) / peak if peak > 0 else 0.0


@dataclass
class HaltController:
    """v1 durum makinesinin çalışan durumu (canlıda PortfolioState'te yaşardı).

    Geçişler:
      AKTİF  -> HALT     : drawdown >= halt_pct
      HALT   -> AKTİF    : en az min_halt_marks geçmiş VE drawdown <= release_pct
      HALT   -> AKTİF    : reset_after_marks geçmiş VE açık pozisyon yok
                           (peak, equity'ye doğru reset_fraction kadar çekilir)
      HALT   -> DURDU    : reset hakkı bitmiş (max_resets)
      her an -> DURDU    : equity, başlangıç sermayesinin hard_floor_pct'sinin altında

    DURDU kalıcıdır; bu sınıf onu asla kendiliğinden temizlemez (canlıda
    yalnızca insan onayıyla kalkıyordu).
    """

    policy: HaltPolicy
    halted: bool = False
    halted_since: Optional[str] = None
    halted_marks: int = 0
    halt_resets: int = 0
    stopped: bool = False
    stop_reason: Optional[str] = None
    events: list[HaltEvent] = field(default_factory=list)

    def mark(
        self,
        state: PortfolioState,
        current_prices: dict[str, float],
        mark_date: Optional[str] = None,
    ) -> HaltEvent:
        """Equity'yi işaretle, peak'i güncelle ve durum makinesini bir adım ilerlet.

        Her equity işaretlemesinde tam bir kez çağrılmalı. `evaluate_buy()`
        bu fonksiyonun bıraktığı bayrağı okur, yani bir ALIM her zaman
        *bir önceki* işaretlemenin durumuna göre karara bağlanır.
        """
        policy = self.policy
        equity = state.equity(current_prices)
        state.peak_equity = max(state.peak_equity, equity)
        drawdown = _drawdown(equity, state.peak_equity)

        def event(transition: Optional[str], detail: str = "") -> HaltEvent:
            ev = HaltEvent(
                transition=transition,
                date=mark_date,
                equity=equity,
                peak_equity=state.peak_equity,
                drawdown=drawdown,
                halted=self.halted,
                stopped=self.stopped,
                detail=detail,
            )
            if transition is not None:
                self.events.append(ev)
            return ev

        # Kalıcı durdurma her şeyin önünde.
        if self.stopped:
            return event(None)

        # Sert taban: sermayenin belirli bir oranı gitmişse eşik tartışması biter.
        floor = state.starting_capital * policy.hard_floor_pct
        if state.starting_capital > 0 and equity < floor:
            self.stopped = True
            self.stop_reason = STOP_REASON_HARD_FLOOR
            self.halted = True
            return event(
                "stopped",
                f"Equity {equity:.2f}, sert tabanın ({floor:.2f}) altına düştü. "
                "Bot kalıcı olarak durduruldu.",
            )

        if not self.halted:
            if drawdown >= policy.halt_pct:
                self.halted = True
                self.halted_since = mark_date
                self.halted_marks = 0
                return event(
                    "halted",
                    f"Drawdown %{drawdown * 100:.2f} >= %{policy.halt_pct * 100:.0f}; "
                    "yeni ALIM durduruldu.",
                )
            return event(None)

        # -- Halt aktif ----------------------------------------------------
        self.halted_marks += 1

        if (
            not policy.latching
            and self.halted_marks >= policy.min_halt_marks
            and drawdown <= policy.release_pct
        ):
            self.halted = False
            self.halted_since = None
            self.halted_marks = 0
            return event(
                "released",
                f"Drawdown %{drawdown * 100:.2f} <= %{policy.release_pct * 100:.0f}; "
                "toparlanma ile halt kalktı.",
            )

        # Nakitteki bir hesabın equity'si sabittir: toparlanma yapısal olarak
        # imkânsız, tek çıkış peak'i aşağı çekmek.
        if (
            not policy.latching
            and self.halted_marks >= policy.reset_after_marks
            and not state.open_positions
        ):
            if self.halt_resets >= policy.max_resets:
                self.stopped = True
                self.stop_reason = STOP_REASON_MAX_RESETS
                return event(
                    "stopped",
                    f"{self.halt_resets} kısmi reset'ten sonra hâlâ halt'ta ve nakitte. "
                    "Bot kalıcı olarak durduruldu.",
                )

            old_peak = state.peak_equity
            state.peak_equity = equity + policy.reset_fraction * (old_peak - equity)
            self.halt_resets += 1
            self.halted = False
            self.halted_since = None
            self.halted_marks = 0
            return event(
                "reset",
                f"{policy.reset_after_marks} işaretlemedir halt'ta ve açık pozisyon yok. "
                f"Peak {old_peak:.2f} -> {state.peak_equity:.2f} çekildi "
                f"({self.halt_resets}/{policy.max_resets} reset), halt kalktı.",
            )

        return event(None)

    # -- evaluate_buy() öncesi okunan bayraklar ----------------------------

    def blocks_buys(self) -> bool:
        return self.stopped or self.halted

    def block_reason(self, state: PortfolioState, current_prices: dict[str, float]) -> str:
        equity = state.equity(current_prices)
        if self.stopped:
            # Önek aynı: kalıcı durdurma da halt kaynaklı bir engellemedir,
            # ayrıntısı `stop_reason` alanında.
            return (
                f"{HALT_REASON_PREFIX}: bot kalıcı olarak durduruldu "
                f"({self.stop_reason})"
            )
        return (
            f"{HALT_REASON_PREFIX}: equity {equity:.2f}, peak {state.peak_equity:.2f} "
            f"altında (%{_drawdown(equity, state.peak_equity) * 100:.2f}), "
            f"{self.halted_marks} işaretlemedir halt'ta"
        )
