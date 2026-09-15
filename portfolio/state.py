"""Paper portfolio state: cash, open positions, and closed trades.

Persisted as a single JSON file (`data/portfolio.json` by default -- see
`alsatbotu.config.PORTFOLIO_STATE_PATH`). Starting capital comes from
`alsatbotu.config.STARTING_CAPITAL` and is only used the first time a
portfolio is created; once a state file exists it is the source of truth.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from alsatbotu.config import (
    MIN_POSITION_NOTIONAL,
    PORTFOLIO_STATE_PATH,
    STARTING_CAPITAL,
)

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    category: str
    quantity: float
    entry_price: float
    entry_date: str
    stop_price: float


@dataclass
class ClosedTrade:
    symbol: str
    category: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_date: str
    exit_date: str
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class PortfolioState:
    cash: float
    starting_capital: float
    peak_equity: float
    open_positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)

    # -- Drawdown halt durumu (engine.risk.update_halt_state sahibidir) ----
    # Halt artık anlık bir hesap değil, kalıcı bir durum: bir kez tetiklenince
    # ancak toparlanma (histerezis) ya da kısmi peak reset'i onu bırakır.
    halted: bool = False
    halted_since: Optional[str] = None
    # Halt başladığından (ya da son reset'ten) beri kaç kez equity işaretlendi.
    halted_marks: int = 0
    halt_resets: int = 0
    # Kalıcı durdurma: yalnızca insan onayıyla kalkar (scripts/resume_halt.py).
    stopped: bool = False
    stop_reason: Optional[str] = None

    # Manuel duraklatma: Telegram'daki "⏸ Duraklat" butonuyla açılır, "▶️ Devam
    # Et" ile kapanır (scripts/process_telegram_controls.py). `halted`/`stopped`
    # ile bağımsızdır -- risk motorunun kendi kararı değil, insanın anlık
    # tercihidir. Açıkken de mevcut pozisyonların SATIŞI çalışmaya devam eder,
    # yalnızca yeni ALIM durur (bkz. engine/risk.py evaluate_buy).
    paused: bool = False
    paused_reason: Optional[str] = None

    def position_value(self, current_prices: dict[str, float]) -> float:
        return sum(
            position.quantity * current_prices.get(symbol, position.entry_price)
            for symbol, position in self.open_positions.items()
        )

    def equity(self, current_prices: dict[str, float]) -> float:
        return self.cash + self.position_value(current_prices)

    def category_exposure(self, category: str, current_prices: dict[str, float]) -> float:
        return sum(
            position.quantity * current_prices.get(symbol, position.entry_price)
            for symbol, position in self.open_positions.items()
            if position.category == category
        )


def drop_dust_positions(
    state: PortfolioState, where: str, min_notional: float = MIN_POSITION_NOTIONAL
) -> list[str]:
    """Toz büyüklüğündeki pozisyonları state'ten düş; düşülen sembolleri döndür.

    Risk motoru artık `MIN_POSITION_NOTIONAL` altındaki bir alımı hiç
    onaylamıyor, ama daha önce yazılmış state dosyalarında bu kayıtlar
    duruyor (canlıda META, 7.4e-16 adet) ve raporda "0.000000 adet, %+5.04"
    gibi anlamsız bir satır üretiyorlar. Süzgeç hem okurken hem yazarken
    çalışır: eski dosya temizlenerek yüklenir, yeni dosyaya hiç girmez.

    Giriş maliyeti nakde geri verilir -- düşürme, hiç açılmaması gereken bir
    pozisyonun açılışını geri almaktır; tanımı gereği `min_notional`'dan
    küçük bir tutardır.
    """
    dropped: list[str] = []
    for symbol, position in list(state.open_positions.items()):
        notional = position.quantity * position.entry_price
        if notional >= min_notional:
            continue
        del state.open_positions[symbol]
        state.cash += notional
        dropped.append(symbol)
        logger.warning(
            "%s: toz pozisyon state'ten düşürüldü (%s) — %.12g adet, %.6g tutar "
            "(asgari %.2f); giriş maliyeti nakde iade edildi",
            symbol,
            where,
            position.quantity,
            notional,
            min_notional,
        )
    return dropped


def _new_state() -> PortfolioState:
    return PortfolioState(
        cash=STARTING_CAPITAL,
        starting_capital=STARTING_CAPITAL,
        peak_equity=STARTING_CAPITAL,
    )


def load_state(path: Path = PORTFOLIO_STATE_PATH) -> PortfolioState:
    """Load portfolio state from `path`, creating a fresh one if it doesn't exist."""
    if not os.path.exists(path):
        return _new_state()

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    state = PortfolioState(
        cash=raw["cash"],
        starting_capital=raw["starting_capital"],
        peak_equity=raw["peak_equity"],
        open_positions={
            symbol: Position(**data) for symbol, data in raw.get("open_positions", {}).items()
        },
        closed_trades=[ClosedTrade(**data) for data in raw.get("closed_trades", [])],
        # Halt alanları sonradan eklendi: eski state dosyalarında yoklar,
        # varsayılanları "hiç halt olmamış" anlamına gelir.
        halted=raw.get("halted", False),
        halted_since=raw.get("halted_since"),
        halted_marks=raw.get("halted_marks", 0),
        halt_resets=raw.get("halt_resets", 0),
        stopped=raw.get("stopped", False),
        stop_reason=raw.get("stop_reason"),
        paused=raw.get("paused", False),
        paused_reason=raw.get("paused_reason"),
    )
    drop_dust_positions(state, where="load_state")
    return state


def save_state(state: PortfolioState, path: Path = PORTFOLIO_STATE_PATH) -> None:
    """Write `state` to `path` atomically (write to a temp file, then rename)."""
    drop_dust_positions(state, where="save_state")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "cash": state.cash,
        "starting_capital": state.starting_capital,
        "peak_equity": state.peak_equity,
        "open_positions": {
            symbol: asdict(position) for symbol, position in state.open_positions.items()
        },
        "closed_trades": [asdict(trade) for trade in state.closed_trades],
        "halted": state.halted,
        "halted_since": state.halted_since,
        "halted_marks": state.halted_marks,
        "halt_resets": state.halt_resets,
        "stopped": state.stopped,
        "stop_reason": state.stop_reason,
        "paused": state.paused,
        "paused_reason": state.paused_reason,
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def update_peak_equity(state: PortfolioState, current_prices: dict[str, float]) -> float:
    """Update and return `state.peak_equity` given the latest equity mark."""
    equity = state.equity(current_prices)
    state.peak_equity = max(state.peak_equity, equity)
    return equity


def open_position(
    state: PortfolioState,
    symbol: str,
    category: str,
    quantity: float,
    entry_price: float,
    entry_date: str,
    stop_price: float,
) -> Position:
    if symbol in state.open_positions:
        raise ValueError(f"Position already open for {symbol!r}")

    position = Position(
        symbol=symbol,
        category=category,
        quantity=quantity,
        entry_price=entry_price,
        entry_date=entry_date,
        stop_price=stop_price,
    )
    state.cash -= quantity * entry_price
    state.open_positions[symbol] = position
    return position


def reduce_position(
    state: PortfolioState,
    symbol: str,
    quantity: float,
    exit_price: float,
    exit_date: str,
    reason: str,
) -> Optional[ClosedTrade]:
    """Bir pozisyonun `quantity` kadarını sat, kalanı açık bırak.

    Kategori kırpması için var: fazlalık satılır, pozisyonun geri kalanı
    (ve giriş fiyatı, stop'u) olduğu gibi kalır. Kalan kısım
    `MIN_POSITION_NOTIONAL` altına düşecekse pozisyon tamamen kapatılır --
    aksi halde süzgecin temizlediği toz kayıtları bu kez kırpma üretirdi.
    """
    position = state.open_positions.get(symbol)
    if position is None or quantity <= 0:
        return None

    remaining = position.quantity - quantity
    if remaining * position.entry_price < MIN_POSITION_NOTIONAL:
        return close_position(state, symbol, exit_price, exit_date, reason)

    position.quantity = remaining
    state.cash += quantity * exit_price

    trade = ClosedTrade(
        symbol=position.symbol,
        category=position.category,
        quantity=quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_date=position.entry_date,
        exit_date=exit_date,
        pnl=quantity * (exit_price - position.entry_price),
        pnl_pct=(exit_price / position.entry_price - 1.0) if position.entry_price else 0.0,
        reason=reason,
    )
    state.closed_trades.append(trade)
    return trade


def close_position(
    state: PortfolioState,
    symbol: str,
    exit_price: float,
    exit_date: str,
    reason: str,
) -> Optional[ClosedTrade]:
    position = state.open_positions.pop(symbol, None)
    if position is None:
        return None

    proceeds = position.quantity * exit_price
    cost = position.quantity * position.entry_price
    state.cash += proceeds

    trade = ClosedTrade(
        symbol=position.symbol,
        category=position.category,
        quantity=position.quantity,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_date=position.entry_date,
        exit_date=exit_date,
        pnl=proceeds - cost,
        pnl_pct=(exit_price / position.entry_price - 1.0) if position.entry_price else 0.0,
        reason=reason,
    )
    state.closed_trades.append(trade)
    return trade
