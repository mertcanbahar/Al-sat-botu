"""Tests for the risk engine's latching drawdown halt (hysteresis + resets)."""
from __future__ import annotations

import pytest

from engine.risk import (
    STOP_REASON_HARD_FLOOR,
    STOP_REASON_MAX_RESETS,
    HaltPolicy,
    evaluate_buy,
    update_halt_state,
)
from portfolio.state import PortfolioState, Position, open_position

POLICY = HaltPolicy(
    halt_pct=0.20,
    release_pct=0.10,
    min_halt_marks=2,
    reset_after_marks=5,
    reset_fraction=0.5,
    max_resets=2,
    hard_floor_pct=0.50,
)


def cash_state(cash: float, peak: float = 100_000.0, starting: float = 100_000.0) -> PortfolioState:
    return PortfolioState(cash=cash, starting_capital=starting, peak_equity=peak)


def mark(state: PortfolioState, prices: dict | None = None, policy: HaltPolicy = POLICY):
    return update_halt_state(state, prices or {}, policy)


# -- Tetikleme ve histerezis ------------------------------------------------


def test_halt_triggers_at_threshold_and_not_before():
    state = cash_state(81_000.0)  # %19 drawdown
    assert mark(state).transition is None
    assert state.halted is False

    state.cash = 80_000.0  # %20
    assert mark(state).transition == "halted"
    assert state.halted is True


def test_release_needs_both_recovery_and_minimum_duration():
    state = cash_state(80_000.0)
    mark(state)  # halt

    # Anında toparlansa bile minimum süre dolmadan bırakmaz.
    state.cash = 95_000.0
    assert mark(state).transition is None
    assert state.halted is True

    # Süre dolduktan sonra, drawdown release eşiğinin altındayken bırakır.
    assert mark(state).transition == "released"
    assert state.halted is False


def test_partial_recovery_between_the_two_thresholds_keeps_the_halt_on():
    """Histerezisin amacı: %20 ile %10 arasında dolaşmak halt'ı açmaz."""
    state = cash_state(80_000.0)
    mark(state)
    state.cash = 85_000.0  # %15 drawdown: halt eşiğinin altında ama release'in üstünde
    # reset_after_marks'tan az işaretleme, ki kaçış kapısı değil histerezis sınansın.
    for _ in range(POLICY.reset_after_marks - 1):
        assert mark(state).transition is None
    assert state.halted is True

    # Aynı hesap %10'un altına inince bırakır.
    state.cash = 91_000.0
    assert mark(state).transition == "released"


# -- Kısmi reset (nakitte kilitlenme kaçış kapısı) --------------------------


def test_partial_reset_releases_a_flat_cash_account_and_halves_the_peak():
    state = cash_state(80_000.0)
    mark(state)  # halt, peak 100k
    for _ in range(4):
        mark(state)
    event = mark(state)  # reset_after_marks (5) doldu

    assert event.transition == "reset"
    assert state.halted is False
    assert state.halt_resets == 1
    # Peak tamamen sıfırlanmaz: equity ile eski peak'in ortasına çekilir.
    assert state.peak_equity == pytest.approx(90_000.0)
    # Koruma korunuyor: bir sonraki halt 90k'nın %20 altında, yani 72k'da.
    assert state.stopped is False


def test_reset_does_not_fire_while_positions_are_still_open():
    state = cash_state(0.0)
    state.open_positions["AAPL"] = Position(
        symbol="AAPL", category="tech", quantity=800.0, entry_price=100.0,
        entry_date="2026-01-01", stop_price=90.0,
    )
    prices = {"AAPL": 100.0}  # equity 80k, %20 drawdown
    mark(state, prices)
    for _ in range(10):
        event = mark(state, prices)
        assert event.transition != "reset"
    assert state.halted is True


def test_stops_permanently_after_the_reset_budget_is_spent():
    state = cash_state(80_000.0)
    policy = POLICY

    # Her turda: halt -> 5 işaretleme -> reset. İki reset sonra üçüncüsünde durur.
    for expected_resets in (1, 2):
        mark(state, policy=policy)  # halt (ilk turda zaten halted olabilir)
        for _ in range(policy.reset_after_marks):
            mark(state, policy=policy)
        assert state.halt_resets == expected_resets
        # Yeni peak'in %20 altına in ki tekrar halt tetiklensin.
        state.cash = state.peak_equity * 0.80

    mark(state, policy=policy)
    for _ in range(policy.reset_after_marks):
        event = mark(state, policy=policy)
    assert event.transition == "stopped"
    assert state.stopped is True
    assert state.stop_reason == STOP_REASON_MAX_RESETS


# -- Sert taban -------------------------------------------------------------


def test_hard_floor_stops_immediately_regardless_of_halt_state():
    state = cash_state(49_000.0)  # başlangıç sermayesinin %50'sinin altı
    event = mark(state)
    assert event.transition == "stopped"
    assert state.stop_reason == STOP_REASON_HARD_FLOOR
    assert state.halted is True


def test_a_stopped_bot_never_resumes_on_its_own():
    state = cash_state(49_000.0)
    mark(state)
    state.cash = 200_000.0  # tamamen toparlansa bile
    for _ in range(50):
        assert mark(state).transition is None
    assert state.stopped is True


# -- evaluate_buy bayrağı okur ---------------------------------------------


def test_evaluate_buy_blocks_while_halted_and_allows_after_release():
    state = cash_state(80_000.0)
    mark(state)

    blocked = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert not blocked.approved
    assert any(r.startswith("Drawdown halt") for r in blocked.reasons)

    state.cash = 95_000.0
    mark(state)
    mark(state)  # release
    allowed = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert allowed.approved and allowed.quantity > 0


def test_evaluate_buy_blocks_while_stopped_and_says_approval_is_needed():
    state = cash_state(49_000.0)
    mark(state)
    decision = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert not decision.approved
    assert any("insan onayı" in r for r in decision.reasons)


# -- Trend kapısı -----------------------------------------------------------


def test_trend_release_needs_minimum_duration_too():
    state = cash_state(80_000.0)
    mark(state)  # halt
    # Trend hemen dönse bile minimum süre dolmadan bırakmaz.
    assert update_halt_state(state, {}, POLICY, trend_ok=True).transition is None
    assert state.halted is True


def test_trend_release_pulls_peak_into_the_release_band():
    """Trendle çıkarken ölçüt de güncellenmezse halt ertesi gün yeniden tetiklenir."""
    state = cash_state(80_000.0)
    for _ in range(POLICY.min_halt_marks + 1):
        update_halt_state(state, {}, POLICY)
    event = update_halt_state(state, {}, POLICY, trend_ok=True)

    assert event.transition == "released"
    assert "trend" in event.detail.lower()
    # Peak, drawdown tam release_pct (%10) olacak seviyeye çekilir.
    assert state.peak_equity == pytest.approx(80_000.0 / 0.9)
    # Ve bir sonraki işaretlemede kural yeniden tetiklenmez.
    assert update_halt_state(state, {}, POLICY, trend_ok=False).transition is None
    assert state.halted is False


def test_trend_release_does_not_lower_the_peak_when_already_recovered():
    state = cash_state(80_000.0)
    for _ in range(POLICY.min_halt_marks + 1):
        update_halt_state(state, {}, POLICY)
    state.cash = 95_000.0  # drawdown %5, zaten release bandının içinde
    event = update_halt_state(state, {}, POLICY, trend_ok=True)
    assert event.transition == "released"
    assert "toparlanma" in event.detail
    assert state.peak_equity == pytest.approx(100_000.0)  # peak'e dokunulmaz


def test_trend_unknown_does_not_release():
    """Trend bilinmiyorsa (yetersiz geçmiş) halt trend gerekçesiyle açılmaz.

    Kaçış kapısının (nakitte zamanlı reset) karışmaması için
    reset_after_marks'tan az işaretleme yapılır.
    """
    state = cash_state(80_000.0)
    for _ in range(POLICY.reset_after_marks - 1):
        update_halt_state(state, {}, POLICY, trend_ok=None)
    assert state.halted is True


# -- Eski mandal davranışı (karşılaştırma tabanı) ---------------------------


def test_latching_policy_never_releases():
    latching = HaltPolicy(halt_pct=0.20, release_pct=None)
    state = cash_state(80_000.0)
    update_halt_state(state, {}, latching)
    state.cash = 99_999.0  # neredeyse tam toparlanma
    for _ in range(100):
        update_halt_state(state, {}, latching)
    assert state.halted is True


# -- Günlük raporun halt satırı (canlı izleme) ------------------------------


def test_daily_report_halt_line_covers_all_three_states():
    """Halt durumu raporda her gün görünmeli, yalnızca sorun varken değil."""
    from scripts.daily_report import halt_status_line

    calm = PortfolioState(cash=95_000.0, starting_capital=100_000.0, peak_equity=100_000.0)
    line = halt_status_line(calm, 95_000.0)
    assert "yok" in line and "%5.00" in line  # drawdown ve eşiğe kalan mesafe görünür

    halted = PortfolioState(cash=80_000.0, starting_capital=100_000.0, peak_equity=100_000.0)
    for _ in range(3):
        update_halt_state(halted, {})
    line = halt_status_line(halted, 80_000.0)
    assert "AKTİF" in line and "trend" in line  # çıkış koşulu yazılı

    stopped = PortfolioState(cash=40_000.0, starting_capital=100_000.0, peak_equity=100_000.0)
    update_halt_state(stopped, {})
    line = halt_status_line(stopped, 40_000.0)
    assert "KALICI DURDURMA" in line and "insan onayı" in line


# -- Toz pozisyon koruması --------------------------------------------------


def test_dust_sized_buy_is_rejected_instead_of_opened():
    """Nakit tükendiğinde cash/entry_price pozitif ama toz mertebesinde çıkar.

    Eski `quantity <= 0` kontrolü bunu geçiriyor ve günlük raporda 0.000000
    adetlik pozisyon olarak görünüyordu.
    """
    state = PortfolioState(cash=1e-7, starting_capital=10_000.0, peak_equity=10_000.0)
    decision = evaluate_buy(state, "META", "tech", 500.0, 10.0, {})

    assert not decision.approved
    assert decision.quantity == 0.0
    assert any("minimum" in r for r in decision.reasons)


def test_buy_below_minimum_notional_is_rejected():
    from alsatbotu.config import MIN_POSITION_NOTIONAL

    # Kategori odası (equity * %40) minimum notional'ın altında kalacak kadar
    # küçük bir hesap: 20 TL equity -> 8 TL oda -> 10 TL eşiğinin altında.
    equity = MIN_POSITION_NOTIONAL * 2
    state = PortfolioState(cash=equity, starting_capital=equity, peak_equity=equity)
    decision = evaluate_buy(state, "META", "tech", 500.0, 10.0, {})

    assert not decision.approved
    assert any("minimum" in r for r in decision.reasons)


def test_normal_sized_buy_still_goes_through():
    state = PortfolioState(cash=10_000.0, starting_capital=10_000.0, peak_equity=10_000.0)
    decision = evaluate_buy(state, "META", "tech", 500.0, 10.0, {})
    assert decision.approved
    assert decision.quantity * 500.0 >= 10.0


# -- Pozisyon başına tahsis tavanı ------------------------------------------


def test_single_position_never_exceeds_the_allocation_cap():
    from alsatbotu.config import MAX_POSITION_ALLOCATION_PCT

    equity = 10_000.0
    state = PortfolioState(cash=equity, starting_capital=equity, peak_equity=equity)
    # Stop çok yakın olduğu için 2%-risk boyutlaması tek başına çok büyük bir
    # pozisyon isterdi; tavanın bunu kırpması gerekir.
    decision = evaluate_buy(state, "AAPL", "tech", 100.0, 0.2, {})

    assert decision.approved
    assert decision.quantity * 100.0 == pytest.approx(equity * MAX_POSITION_ALLOCATION_PCT)
    assert "allocation cap" in (decision.capped_by or "")


def test_allocation_cap_leaves_cash_for_later_signals():
    """Eski davranışta tek pozisyon nakdi bitirip sonraki sinyalleri reddettiriyordu."""
    from alsatbotu.config import MAX_POSITION_ALLOCATION_PCT

    equity = 10_000.0
    state = PortfolioState(cash=equity, starting_capital=equity, peak_equity=equity)
    prices: dict[str, float] = {}

    opened = 0
    for symbol, price in [("AAPL", 100.0), ("MSFT", 200.0), ("JPM", 50.0)]:
        category = "tech" if symbol in ("AAPL", "MSFT") else "financials"
        decision = evaluate_buy(state, symbol, category, price, price * 0.02, prices)
        assert decision.approved, decision.reasons
        open_position(
            state, symbol=symbol, category=category, quantity=decision.quantity,
            entry_price=price, entry_date="2026-01-01", stop_price=decision.stop_price,
        )
        prices[symbol] = price
        opened += 1

    assert opened == 3
    # Üç pozisyon sonrası hâlâ nakit var: 1 - 3 * tahsis oranı kadar.
    assert state.cash == pytest.approx(equity * (1 - 3 * MAX_POSITION_ALLOCATION_PCT))
    assert state.cash > 0


def test_allocation_cap_never_exceeds_the_hard_cap(monkeypatch=None):
    from alsatbotu.config import MAX_POSITION_ALLOCATION_PCT, POSITION_ALLOCATION_HARD_CAP

    assert MAX_POSITION_ALLOCATION_PCT <= POSITION_ALLOCATION_HARD_CAP
