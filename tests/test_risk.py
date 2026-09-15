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


def test_evaluate_buy_blocks_while_manually_paused():
    state = cash_state(100_000.0)
    state.paused = True
    state.paused_reason = "Telegram"

    decision = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert not decision.approved
    assert any("duraklatıldı" in r for r in decision.reasons)


def test_evaluate_buy_allows_after_manual_resume():
    state = cash_state(100_000.0)
    state.paused = True
    state.paused = False
    state.paused_reason = None

    decision = evaluate_buy(state, "AAPL", "tech", 100.0, 2.0, {})
    assert decision.approved and decision.quantity > 0


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


# -- VADE profili -----------------------------------------------------------


# İlgili config değerlerinin anlık kopyası. Modülün kendisini döndürmek
# işe yaramaz: yardımcı, ortamı eski haline getirmek için config'i tekrar
# yüklüyor ve modül nesnesi tek olduğu için çağıran taraf geri yüklenmiş
# değerleri okuyordu.
_VADE_FIELDS = (
    "VADE", "EMA_FAST_PERIOD", "EMA_SLOW_PERIOD", "ATR_STOP_MULTIPLIER",
    "MAX_OPEN_POSITIONS", "MAX_POSITION_ALLOCATION_PCT",
    "PAPER_ATR_STOP_MULTIPLIER", "PAPER_ATR_TARGET_MULTIPLIER",
)


def _reload_config_with(vade_value):
    """ALSATBOTU_VADE verilen değerdeyken config'i yükleyip değerlerini döndürür."""
    import importlib
    import os
    from types import SimpleNamespace

    import alsatbotu.config as config

    previous = os.environ.get("ALSATBOTU_VADE")
    try:
        if vade_value is None:
            os.environ.pop("ALSATBOTU_VADE", None)
        else:
            os.environ["ALSATBOTU_VADE"] = vade_value
        reloaded = importlib.reload(config)
        return SimpleNamespace(**{f: getattr(reloaded, f) for f in _VADE_FIELDS})
    finally:
        if previous is None:
            os.environ.pop("ALSATBOTU_VADE", None)
        else:
            os.environ["ALSATBOTU_VADE"] = previous
        importlib.reload(config)


def test_vade_defaults_to_uzun_when_unset():
    config = _reload_config_with(None)
    assert config.VADE == "uzun"
    assert (config.EMA_FAST_PERIOD, config.EMA_SLOW_PERIOD) == (20, 50)
    assert config.MAX_OPEN_POSITIONS == 5


def test_vade_profiles_carry_the_documented_values():
    kisa = _reload_config_with("kisa")
    assert (kisa.EMA_FAST_PERIOD, kisa.EMA_SLOW_PERIOD) == (10, 30)
    assert kisa.ATR_STOP_MULTIPLIER == 1.5
    assert kisa.MAX_OPEN_POSITIONS == 10
    assert kisa.MAX_POSITION_ALLOCATION_PCT == 0.08

    uzun = _reload_config_with("uzun")
    assert (uzun.EMA_FAST_PERIOD, uzun.EMA_SLOW_PERIOD) == (20, 50)
    assert uzun.ATR_STOP_MULTIPLIER == 3.0
    assert uzun.MAX_OPEN_POSITIONS == 5
    assert uzun.MAX_POSITION_ALLOCATION_PCT == 0.15


def test_blank_vade_is_treated_as_unset():
    """Tanımlanmamış bir GitHub Actions repository variable boş string gelir.

    Bunu geçersiz sayıp hata fırlatmak, değişkeni unutan bir koşuda botu
    çökertirdi; boş/boşluklu değer varsayılana düşer.
    """
    for blank in ("", "   "):
        config = _reload_config_with(blank)
        assert config.VADE == "uzun"


def test_vade_is_case_and_space_insensitive():
    assert _reload_config_with(" KISA ").VADE == "kisa"


def test_invalid_vade_fails_loudly():
    with pytest.raises(ValueError, match="ALSATBOTU_VADE"):
        _reload_config_with("orta")


def test_both_engines_share_one_stop_multiplier():
    """Değerlendirme motoru ile JSON portföyü aynı stop çarpanını kullanmalı.

    Eskiden PAPER_ATR_STOP_MULTIPLIER sabit 1.5'ti; vade "uzun" iken JSON
    tarafı 3.0 kullanıyordu ve aynı pozisyon bir raporda stop'la kapanmış,
    diğerinde açık görünüyordu.
    """
    for vade in ("kisa", "uzun"):
        config = _reload_config_with(vade)
        assert config.PAPER_ATR_STOP_MULTIPLIER == config.ATR_STOP_MULTIPLIER
        # Hedef, stop'a göre ölçeklenir (eski 1.5/2.5 oranı korunur).
        assert config.PAPER_ATR_TARGET_MULTIPLIER == pytest.approx(
            config.ATR_STOP_MULTIPLIER * (2.5 / 1.5)
        )


# -- Toz pozisyon süzgeci ---------------------------------------------------


def _dust_state():
    from alsatbotu.config import MIN_POSITION_NOTIONAL

    state = PortfolioState(cash=100.0, starting_capital=10_000.0, peak_equity=10_000.0)
    state.open_positions["META"] = Position(
        symbol="META", category="tech", quantity=7.412586648491189e-16,
        entry_price=613.48, entry_date="2026-09-08", stop_price=600.0,
    )
    state.open_positions["KO"] = Position(
        symbol="KO", category="consumer", quantity=40.0,
        entry_price=70.0, entry_date="2026-09-01", stop_price=65.0,
    )
    assert MIN_POSITION_NOTIONAL == 10.0
    return state


def test_dust_positions_are_dropped_and_real_ones_kept():
    from portfolio.state import drop_dust_positions

    state = _dust_state()
    dropped = drop_dust_positions(state, where="test")
    assert dropped == ["META"]
    assert set(state.open_positions) == {"KO"}


def test_dropping_dust_returns_its_entry_cost_to_cash():
    from portfolio.state import drop_dust_positions

    state = _dust_state()
    state.open_positions["META"].quantity = 0.01  # 6.13 -> asgari 10'un altında
    cash_before = state.cash
    drop_dust_positions(state, where="test")
    assert state.cash == pytest.approx(cash_before + 0.01 * 613.48)


def test_load_and_save_state_filter_dust():
    import json
    import tempfile
    from pathlib import Path

    from portfolio.state import load_state, save_state

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "portfolio.json"
        save_state(_dust_state(), path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert set(raw["open_positions"]) == {"KO"}  # save_state hiç yazmaz

        # Süzgeçten önce yazılmış bir dosya okunurken de temizlenir.
        raw["open_positions"]["META"] = {
            "symbol": "META", "category": "tech", "quantity": 7.4e-16,
            "entry_price": 613.48, "entry_date": "2026-09-08", "stop_price": 600.0,
        }
        path.write_text(json.dumps(raw), encoding="utf-8")
        assert set(load_state(path).open_positions) == {"KO"}


# -- Stop'a uyulması --------------------------------------------------------


def _stop_state():
    state = PortfolioState(cash=0.0, starting_capital=10_000.0, peak_equity=10_000.0)
    state.open_positions["NVDA"] = Position(
        symbol="NVDA", category="tech", quantity=10.0,
        entry_price=230.36, entry_date="2026-09-05", stop_price=218.60,
    )
    return state


def _enforce_stop(state, symbol, price):
    import importlib
    module = importlib.import_module("scripts.run_portfolio")
    return module._enforce_stop(state, symbol, price, when="2026-09-11T16:00:00")


def test_stop_closes_the_position_without_a_sell_signal():
    state = _stop_state()
    assert _enforce_stop(state, "NVDA", 218.36) is True
    assert "NVDA" not in state.open_positions
    trade = state.closed_trades[-1]
    assert trade.reason == "stop_loss"
    assert trade.exit_price == 218.36
    assert state.cash == pytest.approx(2183.6)


def test_stop_triggers_exactly_at_the_stop_price():
    state = _stop_state()
    assert _enforce_stop(state, "NVDA", 218.61) is False
    assert "NVDA" in state.open_positions
    assert _enforce_stop(state, "NVDA", 218.60) is True


def test_stop_is_a_no_op_without_an_open_position():
    state = _stop_state()
    assert _enforce_stop(state, "AAPL", 1.0) is False
    assert state.closed_trades == []


# -- Kategori tolerans bandı ------------------------------------------------


def _category_state(xom_price: float):
    """Enerji kategorisi tek isimde; fiyat verilen seviyeye gelmiş portföy."""
    state = PortfolioState(cash=4_000.0, starting_capital=10_000.0, peak_equity=10_000.0)
    state.open_positions["XOM"] = Position(
        symbol="XOM", category="energy", quantity=40.0,
        entry_price=100.0, entry_date="2026-09-01", stop_price=90.0,
    )
    state.open_positions["KO"] = Position(
        symbol="KO", category="consumer", quantity=20.0,
        entry_price=100.0, entry_date="2026-09-01", stop_price=90.0,
    )
    return state, {"XOM": xom_price, "KO": 100.0}


def test_no_trim_inside_the_tolerance_band():
    from engine.risk import plan_category_trims

    # XOM 4.000 -> 4.400: equity 10.400, enerji %42.3 (>%40, <%45).
    state, prices = _category_state(110.0)
    assert plan_category_trims(state, prices) == []


def test_trim_fires_above_the_hard_limit_and_targets_the_entry_limit():
    from alsatbotu.config import CATEGORY_EXPOSURE_LIMIT_PCT
    from engine.risk import plan_category_trims
    from portfolio.state import reduce_position

    # XOM 4.000 -> 6.000: equity 12.000, enerji %50.
    state, prices = _category_state(150.0)
    trims = plan_category_trims(state, prices)
    assert [trim.symbol for trim in trims] == ["XOM"]
    assert trims[0].share_before == pytest.approx(0.50)

    for trim in trims:
        reduce_position(
            state, trim.symbol, trim.quantity, trim.price, "2026-09-11", "category_trim"
        )

    equity = state.equity(prices)
    share = state.category_exposure("energy", prices) / equity
    assert share == pytest.approx(CATEGORY_EXPOSURE_LIMIT_PCT)
    # Satış equity'yi değiştirmez (komisyon bu motorda modellenmiyor).
    assert equity == pytest.approx(12_000.0)
    # Tek koşuda tek kırpma: sonuç bandın içinde, tekrar tetiklenmez.
    assert plan_category_trims(state, prices) == []


def test_trim_takes_from_the_largest_holding_first():
    from engine.risk import plan_category_trims

    state, prices = _category_state(150.0)
    state.open_positions["CVX"] = Position(
        symbol="CVX", category="energy", quantity=5.0,
        entry_price=100.0, entry_date="2026-09-01", stop_price=90.0,
    )
    state.cash -= 500.0
    prices["CVX"] = 100.0
    trims = plan_category_trims(state, prices)
    assert trims[0].symbol == "XOM"


def test_reduce_position_keeps_the_remainder_open():
    from portfolio.state import reduce_position

    state, prices = _category_state(150.0)
    trade = reduce_position(state, "XOM", 10.0, 150.0, "2026-09-11", "category_trim")
    assert trade is not None and trade.quantity == 10.0
    assert trade.pnl == pytest.approx(10.0 * 50.0)
    position = state.open_positions["XOM"]
    assert position.quantity == pytest.approx(30.0)
    assert position.entry_price == 100.0  # giriş fiyatı ve stop'u değişmez
    assert state.cash == pytest.approx(4_000.0 + 1_500.0)


def test_reduce_position_closes_it_when_the_remainder_would_be_dust():
    from portfolio.state import reduce_position

    state, prices = _category_state(150.0)
    trade = reduce_position(state, "XOM", 39.95, 150.0, "2026-09-11", "category_trim")
    assert trade is not None
    assert "XOM" not in state.open_positions  # kalan 5 birim < asgari 10
    assert trade.quantity == pytest.approx(40.0)
