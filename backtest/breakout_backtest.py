#!/usr/bin/env python3
"""Kırılma (breakout) mimarisi -- yalnızca backtest, canlıya bağlı DEĞİL.

Bu modül production koduna dokunmaz: `alsatbotu.signal`, `engine.risk`,
`portfolio.state` ve `scripts/run_portfolio.py` olduğu gibi kalır. Buradaki
kurallar yalnızca bu dosyanın simülasyonunda yaşar; canlı davranış değişmez.
Production fonksiyonları (göstergeler, `evaluate_buy`, `update_halt_state`,
`open_position`/`reduce_position`/`close_position`) salt okunur şekilde
yeniden kullanılır, böylece risk motorunun kısıtları (tek pozisyon %15
tahsis tavanı, kategori %40 limiti, en fazla açık pozisyon, drawdown halt)
C kolu (mevcut sistem) ile birebir aynı şekilde bağlar.

AKIŞ (her gün T kapanışında, yalnızca rows[0..T] kullanılarak):

  ADAY      EMA20 > EMA50 ve 50 <= RSI14 <= 70 ise sembol aday listesine girer.
  SEVİYE    kırılma_seviyesi = T'den ÖNCEKİ 20 tamamlanmış barın en yüksek
            high'ı (high[T-20 .. T-1]); T barının kendisi dahil değil.
  TEYİT     close_T > seviye + marj
              marj = 0.1 x ATR14  (hacim verisi varsa)
                     0.3 x ATR14  (hacim verisi yoksa, ör. forex)
            hacim verisi varsa ayrıca: volume_T > 1.2 x (önceki 20 barın
            ortalama hacmi, T hariç).
  ÖMÜR      Aday T0 kapanışında listeye girer; T0+1 .. T0+7 (7 işlem günü)
            kapanışlarında kırılma aranır. Kırılma olmazsa aday düşer
            ("expired"). EMA/RSI filtresi herhangi bir kapanışta bozulursa
            süreden bağımsız düşer ("filter_broken").
  GİRİŞ     Kırılma T kapanışında teyit edilir, T+1 açılışında (slipajlı)
            alınır. Stop/R için ATR, T kapanışındaki ATR'dir.

Karar noktaları (spesifikasyonun açık bıraktığı yerler, burada sabitlendi):

  * Kırılma barında filtre şartı aranmaz. Aday, T-1 kapanışına kadar
    filtreyi her gün geçmiş olmalıdır; kırılmanın kendisi RSI'ı 70'in üstüne
    itebilir ve bu "filtre bozuldu" sayılmaz -- aksi halde en güçlü
    kırılmalar sistematik olarak elenirdi. Kırılma kontrolü o günün filtre
    kontrolünden ÖNCE yapılır.
  * Aynı bar hem aday kaydı hem kırılma olamaz: aday T0'da kaydolur,
    kırılma en erken T0+1'de aranır.
  * Süresi dolan ("expired") bir aday, filtre en az bir kapanışta bozulup
    yeniden kurulmadan tekrar aday olamaz. Aksi halde trend sürdükçe aday
    her gün yeniden doğar ve 7 günlük ömür anlamını yitirirdi. Filtre
    bozulmasıyla düşen, kırılan ya da pozisyonu kapanan sembol ise filtre
    tuttuğu ilk kapanışta yeniden aday olabilir.
  * Açık pozisyonu ya da bekleyen emri olan sembol aday takibine girmez.
  * Hacim ortalaması (önceki 20 bar) T barını içermez; production'daki
    `volume_sma_20` T'yi içerir. Burada "hacim, alışılmışın 1.2 katı mı"
    sorusu soruluyor ve T'yi kendi ortalamasına katmak eşiği yumuşatırdı.

POZİSYON (A ve B kolları):

  Initial Stop = Entry - 1.5 x ATR, 1R = Entry - Initial Stop
  TP1 = Entry + 1.5R, TP2 = Entry + 3R
  Boyut: production `engine.risk.evaluate_buy` (equity'nin %2'si risk,
  %15 tahsis tavanı, nakit, kategori %40 limiti, max açık pozisyon, halt).
  `evaluate_buy` stop'u kendi çarpanıyla (ATR_STOP_MULTIPLIER) kurduğu için
  ona ATR x (1.5 / ATR_STOP_MULTIPLIER) verilir: böylece hesapladığı stop
  tam olarak Entry - 1.5 x ATR olur ve boyutlandırma 1R'ye göre yapılır.
  Production fonksiyonu değiştirilmez.

  B (%50 TP1 + %50 iz süren stop):
    TP1'de pozisyonun %50'si satılır; stop Entry + 0.2 x ATR'ye çekilir.
    Sonrasında kalan için iz süren stop = en yüksek kapanış - 2 x ATR
    (stop asla aşağı inmez, Entry + 0.2 x ATR tabanının altına düşmez).
    TP2'ye ulaşılırsa kalan tamamen satılır.
  A (%100, TP yok): stop = max(initial stop, en yüksek kapanış - 2 x ATR),
    girişten itibaren iz sürer.
  C (mevcut sistem): `backtest.portfolio_backtest.simulate` birebir -- yani
    production `alsatbotu.signal.evaluate` + `engine.risk.evaluate_buy`.
    Bu simülasyon pozisyonun Entry - 3 x ATR stop'unu KONTROL ETMEZ.
  C-stop: C + canlıdaki `scripts/run_portfolio.py::_enforce_stop` davranışı
    (kapanış <= stop ise ertesi açılışta satış). Bkz. `simulate_current`.

GÜN İÇİ SIRALAMA -- AYNI BARDA HEM STOP HEM TP (açık kural):

  Günlük OHLC barından fiyatın gün içindeki yolu bilinemez. Kural:
  1. Açılış ilk fiyattır, sırası bilinir. Açılış stop'un altındaysa tüm
     pozisyon açılıştan (slipajlı) çıkar; açılış hedefin üstündeyse hedef
     açılıştan (slipajlı) gerçekleşir.
  2. Açılıştan sonra aynı bar hem stop'a (low <= stop) hem hedefe
     (high >= TP) değdiyse KÖTÜMSER varsayım: önce STOP tetiklenmiştir;
     pozisyonun tamamı stop'tan kapanır, TP hiç gerçekleşmemiş sayılır. Bu
     durumlar sayılır ve raporda "belirsiz bar" olarak verilir.
  3. TP1 gün içinde gerçekleştiyse yeni stop (Entry + 0.2 x ATR) ve iz süren
     stop ANCAK ERTESİ BARDAN itibaren geçerlidir: TP1 dolduktan sonra
     fiyatın aynı gün geri dönüp dönmediği bilinemez; bar low'u TP1'den
     önce de oluşmuş olabilir (giriş barında low <= open < Entry + 0.2 ATR
     her zaman doğrudur, yani aksi kural giriş gününde TP1 alan her
     pozisyonun kalanını otomatik olarak başabaştan kapatırdı).
  4. TP1 ile aynı barda high >= TP2 ise kalan TP2'den satılır (fiyat TP2'ye
     ancak TP1'i geçtikten sonra ulaşabilir).
  5. İz süren stop yalnızca kapanışta (o günün kapanışı ve ATR'si ile)
     güncellenir ve ertesi bardan itibaren geçerlidir.

  Dolum fiyatları: stop ve açılış (gap) dolumları "piyasa" emridir, aleyhte
  slipaj öder. Gün içi TP dolumu limit emirdir, tam hedef fiyattan dolar.
  Her dolum komisyon öder. Oranlar `portfolio_backtest` ile aynıdır.

LOOKAHEAD GÜVENCESİ:

  * EMA/RSI/ATR/SMA production'daki nedensel (yalnızca geçmişe bakan)
    fonksiyonlardır; tüm seri üzerinde bir kez hesaplanmaları, her gün
    rows[0..T] üzerinde yeniden hesaplanmalarıyla aynı sonucu verir
    (testte doğrulanır).
  * Kırılma seviyesi ve hacim ortalaması T barını içermez.
  * T kapanışındaki karar T+1 açılışında uygulanır; gün içi çıkışlar
    yalnızca o barın OHLC'sini, iz süren stop yalnızca o güne kadarki
    kapanışları kullanır.
  * `lookahead_check()` gerçek veri üzerinde de koşar: veriyi pencerenin
    ortasında keser, kesik ve tam veriyle koşuların kesim tarihine kadar
    birebir aynı olduğunu (equity eğrisi, girişler, kapanan işlemler)
    doğrular. Sonuç raporda yazılır.

Kullanım:
    python backtest/breakout_backtest.py [--years 10] [--out-dir backtest/results/breakout]
    python backtest/breakout_backtest.py --synthetic --out-dir backtest/results/breakout/synthetic
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alsatbotu.indicators import atr as atr_series
from alsatbotu.indicators import add_indicators, ema, rsi
from alsatbotu.signal import ATR_STOP_MULTIPLIER, Signal, evaluate
from backtest.portfolio_backtest import (
    BACKTEST_SYMBOLS,
    COMMISSION_PCT,
    SLIPPAGE_PCT,
    STARTING_CAPITAL,
    INDICATOR_LOOKBACK_BARS,
    WARMUP_BARS,
    RejectedSignal,
    buy_and_hold,
    buy_fill_price,
    commission_for,
    compute_curve_metrics,
    generate_synthetic_data,
    load_price_data,
    market_trend_flags,
    sell_fill_price,
    simulate,
)
from engine.risk import HaltPolicy, evaluate_buy, update_halt_state
from portfolio.state import PortfolioState, close_position, open_position, reduce_position

ARM_TRAIL_ONLY = "A"  # %100 pozisyon, TP yok, yalnızca iz süren stop
ARM_TP_SPLIT = "B"    # %50 TP1 + %50 iz süren stop
ARM_CURRENT = "C"     # mevcut sistem, portfolio_backtest.simulate ile birebir (stop uygulanmaz)
ARM_CURRENT_STOP = "C-stop"  # C + canlıdaki Entry - 3xATR stop'u (scripts/run_portfolio.py::_enforce_stop)

ARM_LABELS = {
    ARM_TRAIL_ONLY: "A: %100, TP yok, iz süren stop",
    ARM_TP_SPLIT: "B: %50 TP1 + %50 iz süren stop",
    ARM_CURRENT: "C: mevcut sistem (backtest, stop yok)",
    ARM_CURRENT_STOP: "C-stop: mevcut sistem + canlıdaki ATR×3 stop",
}
ALL_ARMS = [ARM_TRAIL_ONLY, ARM_TP_SPLIT, ARM_CURRENT, ARM_CURRENT_STOP]

# Alt dönemler (tek sürekli koşunun dilimleri; her dilim kendi başlangıç
# equity'sine normalize edilir, portföy durumu dönem sınırında sıfırlanmaz).
PERIODS = [("2013–2019", "0000-00-00", "2019-12-31"), ("2020–2026", "2020-01-01", "9999-12-31")]

# Halt'ı tamamen kapatan politika: sinyal kalitesi çalışmasında (izole,
# sembol başına) portföy korumasının sonuçları bozmasını istemiyoruz.
NO_HALT_POLICY = HaltPolicy(halt_pct=float("inf"), hard_floor_pct=0.0)


@dataclass(frozen=True)
class BreakoutParams:
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    lookback: int = 20
    candidate_ttl: int = 7
    margin_atr_with_volume: float = 0.1
    margin_atr_without_volume: float = 0.3
    volume_mult: float = 1.2
    volume_window: int = 20
    stop_atr: float = 1.5
    tp1_r: float = 1.5
    tp2_r: float = 3.0
    tp1_fraction: float = 0.5
    breakeven_atr: float = 0.2
    trail_atr: float = 2.0


DEFAULT_PARAMS = BreakoutParams()


# --------------------------------------------------------------------------
# Göstergeler (nedensel, bir kez hesaplanır)
# --------------------------------------------------------------------------

@dataclass
class SymbolSeries:
    rows: list[dict]
    ema_fast: list[Optional[float]]
    ema_slow: list[Optional[float]]
    rsi: list[Optional[float]]
    atr: list[Optional[float]]
    prior_high: list[Optional[float]]      # max(high[i-lookback .. i-1])
    prior_volume_avg: list[Optional[float]]  # mean(volume[i-window .. i-1])
    has_volume: bool


def prior_window_max(values: Sequence[float], window: int) -> list[Optional[float]]:
    """out[i] = max(values[i-window .. i-1]); i. eleman DAHİL DEĞİL."""
    out: list[Optional[float]] = [None] * len(values)
    for i in range(window, len(values)):
        out[i] = max(values[i - window : i])
    return out


def prior_window_mean(values: Sequence[float], window: int) -> list[Optional[float]]:
    """out[i] = mean(values[i-window .. i-1]); i. eleman DAHİL DEĞİL."""
    out: list[Optional[float]] = [None] * len(values)
    for i in range(window, len(values)):
        out[i] = sum(values[i - window : i]) / window
    return out


def prepare_series(rows: Sequence[dict], params: BreakoutParams = DEFAULT_PARAMS) -> SymbolSeries:
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    volumes = [r.get("volume") for r in rows]
    # production add_indicators ile aynı ölçüt: tek bir satırda bile hacim
    # yoksa sembolün hacim verisi "yok" sayılır.
    has_volume = bool(volumes) and all(v is not None for v in volumes)
    return SymbolSeries(
        rows=list(rows),
        ema_fast=ema(closes, params.ema_fast),
        ema_slow=ema(closes, params.ema_slow),
        rsi=rsi(closes, 14),
        atr=atr_series(highs, lows, closes, 14),
        prior_high=prior_window_max(highs, params.lookback),
        prior_volume_avg=(
            prior_window_mean(volumes, params.volume_window) if has_volume else [None] * len(rows)
        ),
        has_volume=has_volume,
    )


def filter_ok(s: SymbolSeries, i: int, params: BreakoutParams = DEFAULT_PARAMS) -> bool:
    f, sl, r = s.ema_fast[i], s.ema_slow[i], s.rsi[i]
    if f is None or sl is None or r is None:
        return False
    return f > sl and params.rsi_min <= r <= params.rsi_max


def breakout_level(s: SymbolSeries, i: int) -> Optional[float]:
    return s.prior_high[i]


def breakout_margin(s: SymbolSeries, i: int, params: BreakoutParams = DEFAULT_PARAMS) -> Optional[float]:
    a = s.atr[i]
    if a is None:
        return None
    mult = params.margin_atr_with_volume if s.has_volume else params.margin_atr_without_volume
    return mult * a


def breakout_ok(s: SymbolSeries, i: int, params: BreakoutParams = DEFAULT_PARAMS) -> bool:
    level = breakout_level(s, i)
    margin = breakout_margin(s, i, params)
    if level is None or margin is None:
        return False
    if not s.rows[i]["close"] > level + margin:
        return False
    if s.has_volume:
        avg = s.prior_volume_avg[i]
        if avg is None:
            return False
        return s.rows[i]["volume"] > params.volume_mult * avg
    return True


# --------------------------------------------------------------------------
# Aday listesi durum makinesi (sembol başına)
# --------------------------------------------------------------------------

EVENT_REGISTERED = "registered"
EVENT_BREAKOUT = "breakout"
EVENT_EXPIRED = "expired"
EVENT_FILTER_BROKEN = "filter_broken"


@dataclass
class CandidateTracker:
    ttl: int = DEFAULT_PARAMS.candidate_ttl
    start_index: Optional[int] = None
    start_date: Optional[str] = None
    needs_reset: bool = False
    counts: dict[str, int] = field(
        default_factory=lambda: {
            EVENT_REGISTERED: 0,
            EVENT_BREAKOUT: 0,
            EVENT_EXPIRED: 0,
            EVENT_FILTER_BROKEN: 0,
        }
    )

    @property
    def active(self) -> bool:
        return self.start_index is not None

    def _drop(self, event: str) -> str:
        self.counts[event] += 1
        self.start_index = None
        self.start_date = None
        return event

    def on_close(
        self, i: int, date: str, filter_passes: bool, breakout_passes: bool, blocked: bool
    ) -> Optional[str]:
        """Bir kapanışı işle; olay adını (ya da None) döndür.

        `i` sembolün kendi bar indeksidir (yaş işlem günü olarak sayılır).
        `blocked`: açık pozisyon ya da bekleyen emir var -- takip yok.
        """
        if blocked:
            return None

        if self.active:
            # Kırılma, bugünün filtre kontrolünden ÖNCE (bkz. modül docstring'i).
            if breakout_passes:
                self.needs_reset = False
                return self._drop(EVENT_BREAKOUT)
            if not filter_passes:
                self.needs_reset = False
                return self._drop(EVENT_FILTER_BROKEN)
            if i - self.start_index >= self.ttl:
                self.needs_reset = True
                return self._drop(EVENT_EXPIRED)
            return None

        if not filter_passes:
            self.needs_reset = False
            return None
        if self.needs_reset:
            return None
        self.start_index = i
        self.start_date = date
        self.counts[EVENT_REGISTERED] += 1
        return EVENT_REGISTERED


# --------------------------------------------------------------------------
# Pozisyon ve gün içi çıkış mantığı
# --------------------------------------------------------------------------

@dataclass
class ExitOrder:
    portion: str   # "tp1" (başlangıç miktarının tp1_fraction'ı) | "rest" (kalanın tamamı)
    price: float   # slipaj öncesi fiyat
    market: bool   # True: stop/gap (slipaj öder), False: limit TP (tam fiyat)
    reason: str


@dataclass
class OpenTrade:
    symbol: str
    category: str
    arm: str
    signal_date: str
    entry_date: str
    entry_price: float
    quantity_initial: float
    atr_entry: float
    initial_stop: float
    stop: float
    tp1: float
    tp2: float
    entry_fee: float = 0.0
    entry_slippage: float = 0.0
    tp1_done: bool = False
    highest_close: float = 0.0
    ambiguous_bars: int = 0
    fills: list[dict] = field(default_factory=list)

    @property
    def r_per_share(self) -> float:
        return self.entry_price - self.initial_stop


def new_trade(
    symbol: str,
    category: str,
    arm: str,
    signal_date: str,
    entry_date: str,
    entry_price: float,
    quantity: float,
    atr_value: float,
    params: BreakoutParams = DEFAULT_PARAMS,
) -> OpenTrade:
    initial_stop = entry_price - params.stop_atr * atr_value
    r = entry_price - initial_stop
    return OpenTrade(
        symbol=symbol,
        category=category,
        arm=arm,
        signal_date=signal_date,
        entry_date=entry_date,
        entry_price=entry_price,
        quantity_initial=quantity,
        atr_entry=atr_value,
        initial_stop=initial_stop,
        stop=initial_stop,
        tp1=entry_price + params.tp1_r * r,
        tp2=entry_price + params.tp2_r * r,
        highest_close=entry_price,
    )


def process_bar(
    t: OpenTrade, o: float, h: float, l: float, params: BreakoutParams = DEFAULT_PARAMS
) -> list[ExitOrder]:
    """Bir barın gün içi çıkışlarını belirle (sıralama kuralı modül docstring'inde).

    `t.stop` ve `t.tp1_done` o barın BAŞINDAKİ durumdur; TP1 bu barda
    dolarsa `t.tp1_done` True olur ama stop değişmez -- yeni stop
    `end_of_bar_update` ile kapanışta kurulur ve ertesi bardan geçerlidir.
    """
    stop = t.stop

    if t.arm == ARM_TRAIL_ONLY:
        if o <= stop:
            return [ExitOrder("rest", o, True, "stop_gap")]
        if l <= stop:
            return [ExitOrder("rest", stop, True, "trail_stop" if stop > t.initial_stop else "initial_stop")]
        return []

    if t.arm != ARM_TP_SPLIT:
        raise ValueError(f"Bilinmeyen kol: {t.arm!r}")

    breakeven = t.entry_price + params.breakeven_atr * t.atr_entry
    stop_reason = "initial_stop" if not t.tp1_done else (
        "trail_stop" if stop > breakeven + 1e-9 else "breakeven_stop"
    )

    if not t.tp1_done:
        # 1) Açılış: sırası bilinen tek fiyat.
        if o <= stop:
            return [ExitOrder("rest", o, True, "stop_gap")]
        if o >= t.tp1:
            orders = [ExitOrder("tp1", o, True, "tp1_gap")]
            t.tp1_done = True
            if o >= t.tp2:
                orders.append(ExitOrder("rest", o, True, "tp2_gap"))
            elif h >= t.tp2:
                orders.append(ExitOrder("rest", t.tp2, False, "tp2"))
            return orders
        # 2) Gün içi: ikisi birden -> kötümser, önce stop.
        hit_stop = l <= stop
        hit_tp1 = h >= t.tp1
        if hit_stop and hit_tp1:
            t.ambiguous_bars += 1
            return [ExitOrder("rest", stop, True, "initial_stop_ambiguous")]
        if hit_stop:
            return [ExitOrder("rest", stop, True, stop_reason)]
        if hit_tp1:
            t.tp1_done = True
            orders = [ExitOrder("tp1", t.tp1, False, "tp1")]
            if h >= t.tp2:
                orders.append(ExitOrder("rest", t.tp2, False, "tp2"))
            return orders
        return []

    # TP1 sonrası: kalan için stop (başabaş/iz süren) ve TP2.
    if o <= stop:
        return [ExitOrder("rest", o, True, "stop_gap")]
    if o >= t.tp2:
        return [ExitOrder("rest", o, True, "tp2_gap")]
    hit_stop = l <= stop
    hit_tp2 = h >= t.tp2
    if hit_stop and hit_tp2:
        t.ambiguous_bars += 1
        return [ExitOrder("rest", stop, True, f"{stop_reason}_ambiguous")]
    if hit_stop:
        return [ExitOrder("rest", stop, True, stop_reason)]
    if hit_tp2:
        return [ExitOrder("rest", t.tp2, False, "tp2")]
    return []


def end_of_bar_update(
    t: OpenTrade, close: float, atr_now: Optional[float], params: BreakoutParams = DEFAULT_PARAMS
) -> None:
    """Kapanışta stop'u güncelle; yeni stop ertesi bardan itibaren geçerli. Stop asla inmez."""
    t.highest_close = max(t.highest_close, close)
    if t.arm == ARM_TP_SPLIT and not t.tp1_done:
        return  # TP1 öncesi stop sabit: initial stop
    floor = t.stop
    if t.arm == ARM_TP_SPLIT:
        floor = max(floor, t.entry_price + params.breakeven_atr * t.atr_entry)
    trail = t.highest_close - params.trail_atr * atr_now if atr_now is not None else floor
    t.stop = max(floor, trail)


# --------------------------------------------------------------------------
# Sonuç kayıtları
# --------------------------------------------------------------------------

@dataclass
class BreakoutTrade:
    symbol: str
    category: str
    arm: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    quantity: float
    initial_stop: float
    atr_entry: float
    tp1: float
    tp2: float
    tp1_hit: bool
    exit_reason: str
    fills: list[dict]
    gross_pnl: float
    commission_paid: float
    net_pnl: float
    net_pnl_pct: float
    r_multiple: Optional[float]
    bars_held: int
    ambiguous_bars: int
    risk_usd: float = 0.0        # 1R x başlangıç miktarı
    slippage_paid: float = 0.0   # tüm dolumlarda aleyhte kaymanın dolar karşılığı


@dataclass
class Funnel:
    candidates: int = 0
    breakouts: int = 0
    expired: int = 0
    filter_broken: int = 0
    candidates_open_at_end: int = 0
    entries_executed: int = 0
    entries_rejected: int = 0
    entries_no_bar: int = 0

    def add(self, other: "Funnel") -> None:
        for k in vars(self):
            setattr(self, k, getattr(self, k) + getattr(other, k))


@dataclass
class BreakoutSimResult:
    arm: str
    equity_curve: list[tuple[str, float]]
    trades: list[BreakoutTrade]
    rejected: list[RejectedSignal]
    open_trades_at_end: list[dict]
    funnel: Funnel
    events: list[tuple[str, str, str]]  # (tarih, sembol, olay)
    window_start: str
    window_end: str
    exposure: list[tuple[str, float]] = field(default_factory=list)  # (tarih, pozisyon değeri / equity)


# --------------------------------------------------------------------------
# Portföy simülasyonu (A ve B)
# --------------------------------------------------------------------------

def _sim_dates(rows_by_symbol: dict[str, list[dict]]) -> tuple[list[str], dict[str, dict[str, int]]]:
    """`portfolio_backtest.simulate` ile aynı pencere: tüm semboller ısındıktan sonra."""
    index_by_date: dict[str, dict[str, int]] = {}
    for s, rows in rows_by_symbol.items():
        for i, row in enumerate(rows):
            index_by_date.setdefault(row["timestamp"].date().isoformat(), {})[s] = i
    first_ready = [
        rows[WARMUP_BARS]["timestamp"].date().isoformat()
        for rows in rows_by_symbol.values()
        if len(rows) > WARMUP_BARS
    ]
    if not first_ready:
        return [], index_by_date
    start = max(first_ready)
    return [d for d in sorted(index_by_date) if d >= start], index_by_date


def simulate_breakout(
    universe: Sequence[dict],
    price_data: dict[str, list[dict]],
    starting_capital: float,
    arm: str,
    params: BreakoutParams = DEFAULT_PARAMS,
    halt_policy: Optional[HaltPolicy] = None,
    trend_ok_by_date: Optional[dict[str, bool]] = None,
) -> BreakoutSimResult:
    if arm not in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        raise ValueError(f"simulate_breakout yalnızca A/B kollarını koşar, verilen: {arm!r}")

    symbols = [e["symbol"] for e in universe if e["symbol"] in price_data]
    categories = {e["symbol"]: e["category"] for e in universe}
    rows_by_symbol = {s: price_data[s] for s in symbols}
    series = {s: prepare_series(rows_by_symbol[s], params) for s in symbols}
    sim_dates, index_by_date = _sim_dates(rows_by_symbol)
    funnel = Funnel()
    if not sim_dates:
        return BreakoutSimResult(arm, [], [], [], [], funnel, [], "", "")
    date_pos = {d: k for k, d in enumerate(sim_dates)}

    state = PortfolioState(cash=starting_capital, starting_capital=starting_capital, peak_equity=starting_capital)
    trackers = {s: CandidateTracker(ttl=params.candidate_ttl) for s in symbols}
    pending: dict[str, dict] = {}
    open_trades: dict[str, OpenTrade] = {}
    current_prices: dict[str, float] = {}
    trades: list[BreakoutTrade] = []
    rejected: list[RejectedSignal] = []
    events: list[tuple[str, str, str]] = []
    equity_curve: list[tuple[str, float]] = []
    exposure: list[tuple[str, float]] = []

    def apply_exit(t: OpenTrade, order: ExitOrder, d: str) -> None:
        position = state.open_positions.get(t.symbol)
        if position is None:
            return
        price = sell_fill_price(order.price) if order.market else order.price
        if order.portion == "tp1":
            qty = min(position.quantity, t.quantity_initial * params.tp1_fraction)
        else:
            qty = position.quantity
        if qty >= position.quantity - 1e-12:
            closed = close_position(state, t.symbol, price, d, order.reason)
        else:
            closed = reduce_position(state, t.symbol, qty, price, d, order.reason)
        if closed is None:
            return
        fee = commission_for(closed.quantity * price)
        state.cash -= fee
        slip = closed.quantity * price * SLIPPAGE_PCT / (1 - SLIPPAGE_PCT) if order.market else 0.0
        t.fills.append(
            {"date": d, "quantity": closed.quantity, "price": price, "reason": order.reason, "fee": fee,
             "slippage": slip}
        )
        if t.symbol not in state.open_positions:
            finalize(t, d)

    def finalize(t: OpenTrade, d: str) -> None:
        open_trades.pop(t.symbol, None)
        gross = sum(f["quantity"] * (f["price"] - t.entry_price) for f in t.fills)
        fees = t.entry_fee + sum(f["fee"] for f in t.fills)
        net = gross - fees
        notional = t.entry_price * t.quantity_initial
        risk = t.r_per_share * t.quantity_initial
        trades.append(
            BreakoutTrade(
                symbol=t.symbol,
                category=t.category,
                arm=t.arm,
                signal_date=t.signal_date,
                entry_date=t.entry_date,
                exit_date=d,
                entry_price=t.entry_price,
                quantity=t.quantity_initial,
                initial_stop=t.initial_stop,
                atr_entry=t.atr_entry,
                tp1=t.tp1,
                tp2=t.tp2,
                tp1_hit=any(f["reason"].startswith("tp1") for f in t.fills),
                exit_reason=t.fills[-1]["reason"],
                fills=list(t.fills),
                gross_pnl=gross,
                commission_paid=fees,
                net_pnl=net,
                net_pnl_pct=net / notional if notional else 0.0,
                r_multiple=net / risk if risk > 0 else None,
                bars_held=date_pos[d] - date_pos[t.entry_date],
                ambiguous_bars=t.ambiguous_bars,
                risk_usd=risk,
                slippage_paid=t.entry_slippage + sum(f["slippage"] for f in t.fills),
            )
        )

    for d in sim_dates:
        today = index_by_date.get(d, {})

        # 1) Dünkü kırılma sinyalleri bugünün açılışında.
        for symbol, sig in list(pending.items()):
            pending.pop(symbol)
            if symbol not in today:
                funnel.entries_no_bar += 1
                continue
            row = rows_by_symbol[symbol][today[symbol]]
            fill = buy_fill_price(row["open"])
            category = categories[symbol]
            sized_atr = params.stop_atr * sig["atr"] / ATR_STOP_MULTIPLIER
            decision = evaluate_buy(state, symbol, category, fill, sized_atr, current_prices)
            if not decision.approved:
                funnel.entries_rejected += 1
                rejected.append(RejectedSignal(symbol, d, "BUY", decision.reasons))
                continue
            open_position(
                state,
                symbol=symbol,
                category=category,
                quantity=decision.quantity,
                entry_price=fill,
                entry_date=d,
                stop_price=decision.stop_price,
            )
            fee = commission_for(decision.quantity * fill)
            state.cash -= fee
            t = new_trade(symbol, category, arm, sig["date"], d, fill, decision.quantity, sig["atr"], params)
            t.entry_fee = fee
            t.entry_slippage = decision.quantity * fill * SLIPPAGE_PCT / (1 + SLIPPAGE_PCT)
            open_trades[symbol] = t
            funnel.entries_executed += 1

        # 2) Gün içi stop/TP (giriş barı dahil: giriş açılışta, barın geri kalanı sonrasında).
        for symbol, t in list(open_trades.items()):
            if symbol not in today:
                continue
            row = rows_by_symbol[symbol][today[symbol]]
            for order in process_bar(t, row["open"], row["high"], row["low"], params):
                apply_exit(t, order, d)

        # 3) Kapanışta işaretle, halt durum makinesini ilerlet.
        for symbol, idx in today.items():
            current_prices[symbol] = rows_by_symbol[symbol][idx]["close"]
        halt_event = update_halt_state(
            state,
            current_prices,
            halt_policy,
            mark_date=d,
            trend_ok=None if trend_ok_by_date is None else trend_ok_by_date.get(d, False),
        )
        equity_curve.append((d, halt_event.equity))
        exposure.append((d, _exposure(state, current_prices, halt_event.equity)))

        # 4) Kapanış: stop güncellemesi, aday listesi, yarının emirleri.
        for symbol, t in open_trades.items():
            if symbol not in today:
                continue
            i = today[symbol]
            end_of_bar_update(t, rows_by_symbol[symbol][i]["close"], series[symbol].atr[i], params)
            state.open_positions[symbol].stop_price = t.stop

        for symbol, i in today.items():
            s = series[symbol]
            blocked = symbol in open_trades or symbol in pending
            event = trackers[symbol].on_close(
                i, d, filter_ok(s, i, params), breakout_ok(s, i, params), blocked
            )
            if event is None:
                continue
            events.append((d, symbol, event))
            if event == EVENT_BREAKOUT:
                pending[symbol] = {"date": d, "atr": s.atr[i]}

    for tr in trackers.values():
        funnel.candidates += tr.counts[EVENT_REGISTERED]
        funnel.breakouts += tr.counts[EVENT_BREAKOUT]
        funnel.expired += tr.counts[EVENT_EXPIRED]
        funnel.filter_broken += tr.counts[EVENT_FILTER_BROKEN]
        funnel.candidates_open_at_end += int(tr.active)

    open_at_end = []
    for symbol, t in open_trades.items():
        position = state.open_positions[symbol]
        price = current_prices.get(symbol, t.entry_price)
        open_at_end.append(
            {
                "symbol": symbol,
                "entry_date": t.entry_date,
                "entry_price": t.entry_price,
                "quantity_open": position.quantity,
                "last_close": price,
                "stop": t.stop,
                "tp1_hit": t.tp1_done,
                "unrealized_pnl": position.quantity * (price - t.entry_price)
                + sum(f["quantity"] * (f["price"] - t.entry_price) for f in t.fills),
            }
        )

    return BreakoutSimResult(
        arm=arm,
        equity_curve=equity_curve,
        trades=trades,
        rejected=rejected,
        open_trades_at_end=open_at_end,
        funnel=funnel,
        events=events,
        window_start=sim_dates[0],
        window_end=sim_dates[-1],
        exposure=exposure,
    )


def _exposure(state: PortfolioState, prices: dict[str, float], equity: float) -> float:
    return state.position_value(prices) / equity if equity > 0 else 0.0


# --------------------------------------------------------------------------
# C ve C-stop: mevcut sistem
# --------------------------------------------------------------------------
# `portfolio_backtest.simulate`'in bu modüldeki kopyası. İki farkı var, ikisi de
# ek ölçüm/opsiyon; varsayılan (enforce_stop=False) davranış birebir aynıdır
# (testte ve her koşuda `simulate` ile karşılaştırılarak doğrulanır):
#   * Günlük exposure ve işlem başı 1R / kayma maliyeti kaydedilir.
#   * enforce_stop=True: canlıdaki `scripts/run_portfolio.py::_enforce_stop`
#     davranışı. Pozisyonun giriş anındaki stop'u (Entry - ATR_STOP_MULTIPLIER x
#     ATR, `evaluate_buy`'ın kurduğu) her kapanışta kontrol edilir; kapanış
#     stop'un altındaysa SELL sinyali beklenmeden ertesi açılışta satılır
#     (backtest'in "T kapanışında karar, T+1 açılışında dolum" kuralı). Canlıda
#     da stop, kural motorundan önce gelir.
# `portfolio_backtest.py` değiştirilmedi.

@dataclass
class CurrentTrade:
    symbol: str
    category: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: float
    stop_price: float
    gross_pnl: float
    commission_paid: float
    slippage_paid: float
    net_pnl: float
    net_pnl_pct: float
    risk_usd: float
    reason: str


@dataclass
class CurrentSimResult:
    equity_curve: list[tuple[str, float]]
    trades: list[CurrentTrade]
    rejected: list[RejectedSignal]
    open_positions_at_end: dict[str, dict]
    exposure: list[tuple[str, float]]


def simulate_current(
    universe: Sequence[dict],
    price_data: dict[str, list[dict]],
    starting_capital: float,
    enforce_stop: bool = False,
    halt_policy: Optional[HaltPolicy] = None,
    trend_ok_by_date: Optional[dict[str, bool]] = None,
) -> CurrentSimResult:
    symbols = [e["symbol"] for e in universe if e["symbol"] in price_data]
    categories = {e["symbol"]: e["category"] for e in universe}
    rows_by_symbol = {s: price_data[s] for s in symbols}
    sim_dates, index_by_date = _sim_dates(rows_by_symbol)
    if not sim_dates:
        return CurrentSimResult([], [], [], {}, [])

    state = PortfolioState(cash=starting_capital, starting_capital=starting_capital, peak_equity=starting_capital)
    entry_commission: dict[str, float] = {}
    entry_slippage: dict[str, float] = {}
    pending: dict[str, tuple[Signal, dict]] = {}
    current_prices: dict[str, float] = {}
    trades: list[CurrentTrade] = []
    rejected: list[RejectedSignal] = []
    equity_curve: list[tuple[str, float]] = []
    exposure: list[tuple[str, float]] = []

    for d in sim_dates:
        today_idx = index_by_date.get(d, {})

        for symbol, (signal, info) in list(pending.items()):
            if symbol not in today_idx:
                continue
            row = rows_by_symbol[symbol][today_idx[symbol]]
            open_price = row["open"]
            category = categories[symbol]
            if signal == Signal.BUY:
                if symbol in state.open_positions:
                    pending.pop(symbol, None)
                    continue
                fill = buy_fill_price(open_price)
                decision = evaluate_buy(state, symbol, category, fill, info.get("atr"), current_prices)
                if not decision.approved:
                    rejected.append(RejectedSignal(symbol, d, "BUY", decision.reasons))
                else:
                    open_position(
                        state, symbol=symbol, category=category, quantity=decision.quantity,
                        entry_price=fill, entry_date=row["timestamp"].isoformat(),
                        stop_price=decision.stop_price,
                    )
                    fee = commission_for(decision.quantity * fill)
                    state.cash -= fee
                    entry_commission[symbol] = fee
                    entry_slippage[symbol] = decision.quantity * fill * SLIPPAGE_PCT / (1 + SLIPPAGE_PCT)
            elif signal == Signal.SELL:
                if symbol not in state.open_positions:
                    pending.pop(symbol, None)
                    continue
                fill = sell_fill_price(open_price)
                position = state.open_positions[symbol]
                qty, stop_price = position.quantity, position.stop_price
                closed = close_position(
                    state, symbol=symbol, exit_price=fill, exit_date=row["timestamp"].isoformat(),
                    reason="; ".join(info.get("reasons", [])) or "SELL signal",
                )
                if closed is not None:
                    fee = commission_for(qty * fill)
                    state.cash -= fee
                    fees = entry_commission.pop(symbol, 0.0) + fee
                    slip = entry_slippage.pop(symbol, 0.0) + qty * fill * SLIPPAGE_PCT / (1 - SLIPPAGE_PCT)
                    net = closed.pnl - fees
                    trades.append(
                        CurrentTrade(
                            symbol=symbol, category=category, entry_date=closed.entry_date,
                            exit_date=closed.exit_date, entry_price=closed.entry_price,
                            exit_price=closed.exit_price, quantity=closed.quantity, stop_price=stop_price,
                            gross_pnl=closed.pnl, commission_paid=fees, slippage_paid=slip, net_pnl=net,
                            net_pnl_pct=net / (closed.entry_price * closed.quantity) if closed.entry_price else 0.0,
                            risk_usd=(closed.entry_price - stop_price) * closed.quantity,
                            reason=closed.reason,
                        )
                    )
            pending.pop(symbol, None)

        for symbol, idx in today_idx.items():
            current_prices[symbol] = rows_by_symbol[symbol][idx]["close"]
        halt_event = update_halt_state(
            state, current_prices, halt_policy, mark_date=d,
            trend_ok=None if trend_ok_by_date is None else trend_ok_by_date.get(d, False),
        )
        equity_curve.append((d, halt_event.equity))
        exposure.append((d, _exposure(state, current_prices, halt_event.equity)))

        for symbol, idx in today_idx.items():
            if idx + 1 < WARMUP_BARS:
                continue
            # Canlıdaki gibi: stop kural motorundan önce gelir.
            position = state.open_positions.get(symbol)
            if enforce_stop and position is not None and current_prices[symbol] <= position.stop_price:
                pending[symbol] = (
                    Signal.SELL,
                    {"reasons": [f"stop_loss (close {current_prices[symbol]:.4f} <= stop {position.stop_price:.4f})"]},
                )
                continue
            window = rows_by_symbol[symbol][max(0, idx + 1 - INDICATOR_LOOKBACK_BARS) : idx + 1]
            if len(window) < 2:
                continue
            decision = evaluate(window)
            if decision.signal == Signal.HOLD:
                continue
            latest = add_indicators(window)[-1]
            pending[symbol] = (decision.signal, {"atr": latest.get("atr"), "reasons": decision.reasons})

    return CurrentSimResult(
        equity_curve=equity_curve,
        trades=trades,
        rejected=rejected,
        open_positions_at_end={s: vars(p) for s, p in state.open_positions.items()},
        exposure=exposure,
    )


# --------------------------------------------------------------------------
# Metrikler (tüm kollar için ortak)
# --------------------------------------------------------------------------

@dataclass
class TradeStat:
    symbol: str
    entry_date: str
    exit_date: str
    net_pnl: float
    net_pnl_pct: float
    bars_held: int
    r_multiple: Optional[float] = None
    cost_usd: float = 0.0            # komisyon + kayma
    cost_pct: float = 0.0            # maliyet / giriş tutarı
    cost_r: Optional[float] = None   # maliyet / 1R


@dataclass
class ArmMetrics:
    arm: str
    total_return: Optional[float]
    cagr: Optional[float]
    max_drawdown: Optional[float]
    sharpe: Optional[float]
    trade_count: int
    hit_rate: Optional[float]
    profit_factor: Optional[float]
    expectancy_usd: Optional[float]
    expectancy_pct: Optional[float]
    expectancy_r: Optional[float]
    avg_win_loss_ratio: Optional[float]
    avg_bars_held: Optional[float]
    net_pnl_total: float
    top3_net_pnl: float
    top3_share_of_net: Optional[float]
    top3_share_of_gross_profit: Optional[float]
    open_at_end: Optional[int]
    avg_exposure: Optional[float] = None         # ortalama (pozisyon değeri / equity)
    days_in_market: Optional[float] = None       # en az bir pozisyonun açık olduğu günlerin oranı
    exposure_adj_cagr: Optional[float] = None    # CAGR / ortalama exposure
    avg_cost_pct: Optional[float] = None
    avg_cost_r: Optional[float] = None


def trade_stats_from_breakout(trades: Sequence[BreakoutTrade]) -> list[TradeStat]:
    out = []
    for t in trades:
        cost = t.commission_paid + t.slippage_paid
        notional = t.entry_price * t.quantity
        out.append(
            TradeStat(
                t.symbol, t.entry_date, t.exit_date, t.net_pnl, t.net_pnl_pct, t.bars_held, t.r_multiple,
                cost, cost / notional if notional else 0.0, cost / t.risk_usd if t.risk_usd > 0 else None,
            )
        )
    return out


def trade_stats_from_current(trades: Sequence[CurrentTrade], sim_dates: Sequence[str]) -> list[TradeStat]:
    """C / C-stop işlemleri; tutma süresi aynı işlem günü ekseninde, 1R = Entry - stop (ATR x3)."""
    pos = {d: k for k, d in enumerate(sim_dates)}
    out = []
    for t in trades:
        entry, exit_ = t.entry_date[:10], t.exit_date[:10]
        cost = t.commission_paid + t.slippage_paid
        notional = t.entry_price * t.quantity
        out.append(
            TradeStat(
                t.symbol, entry, exit_, t.net_pnl, t.net_pnl_pct, pos.get(exit_, 0) - pos.get(entry, 0),
                t.net_pnl / t.risk_usd if t.risk_usd > 0 else None,
                cost, cost / notional if notional else 0.0, cost / t.risk_usd if t.risk_usd > 0 else None,
            )
        )
    return out


def _mean(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def compute_arm_metrics(
    arm: str,
    equity_curve: list[tuple[str, float]],
    stats: Sequence[TradeStat],
    open_at_end: Optional[int],
    exposure: Optional[list[tuple[str, float]]] = None,
) -> ArmMetrics:
    total_return, cagr, max_dd, sharpe = compute_curve_metrics(equity_curve)
    n = len(stats)
    wins = [t for t in stats if t.net_pnl > 0]
    losses = [t for t in stats if t.net_pnl <= 0]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    net_total = gross_profit - gross_loss

    ratio = None
    if wins and losses:
        avg_loss = statistics.fmean(t.net_pnl_pct for t in losses)
        if avg_loss:
            ratio = statistics.fmean(t.net_pnl_pct for t in wins) / abs(avg_loss)

    top3 = sorted((t.net_pnl for t in stats), reverse=True)[:3]
    top3_sum = sum(top3)
    top3_positive = sum(p for p in top3 if p > 0)

    avg_exp = _mean(v for _, v in exposure) if exposure else None
    in_market = (sum(1 for _, v in exposure if v > 0) / len(exposure)) if exposure else None

    return ArmMetrics(
        arm=arm,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=sharpe,
        trade_count=n,
        hit_rate=len(wins) / n if n else None,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        expectancy_usd=net_total / n if n else None,
        expectancy_pct=_mean(t.net_pnl_pct for t in stats),
        expectancy_r=_mean(t.r_multiple for t in stats),
        avg_win_loss_ratio=ratio,
        avg_bars_held=_mean(t.bars_held for t in stats),
        net_pnl_total=net_total,
        top3_net_pnl=top3_sum,
        top3_share_of_net=top3_sum / net_total if net_total > 0 else None,
        top3_share_of_gross_profit=top3_positive / gross_profit if gross_profit > 0 else None,
        open_at_end=open_at_end,
        avg_exposure=avg_exp,
        days_in_market=in_market,
        exposure_adj_cagr=cagr / avg_exp if cagr is not None and avg_exp else None,
        avg_cost_pct=_mean(t.cost_pct for t in stats),
        avg_cost_r=_mean(t.cost_r for t in stats),
    )


def slice_curve(curve: list[tuple[str, float]], start: str, end: str) -> list[tuple[str, float]]:
    """[start, end] aralığı; dönemin ilk gününün getirisi kaybolmasın diye önceki günün değeri taban olarak eklenir."""
    inside = [(d, v) for d, v in curve if start <= d <= end]
    before = [(d, v) for d, v in curve if d < start]
    return ([before[-1]] if before and inside else []) + inside


def period_metrics(
    arm: str,
    curve: list[tuple[str, float]],
    exposure: Optional[list[tuple[str, float]]],
    stats: Sequence[TradeStat],
    start: str,
    end: str,
) -> ArmMetrics:
    """Tek sürekli koşunun bir dilimi. İşlemler çıkış tarihine göre dönemlere atanır."""
    return compute_arm_metrics(
        arm,
        slice_curve(curve, start, end),
        [t for t in stats if start <= t.exit_date[:10] <= end],
        None,
        [(d, v) for d, v in exposure if start <= d <= end] if exposure is not None else None,
    )


def funnel_rates(funnel: Funnel, trades: Sequence) -> dict:
    resolved = funnel.candidates - funnel.candidates_open_at_end
    profitable = sum(1 for t in trades if t.net_pnl > 0)
    return {
        "candidate_to_breakout": funnel.breakouts / resolved if resolved else None,
        "breakout_to_profitable_trade": profitable / len(trades) if trades else None,
        "breakout_to_profitable_over_all_signals": profitable / funnel.breakouts if funnel.breakouts else None,
        "profitable_trades": profitable,
        "closed_trades": len(trades),
        "resolved_candidates": resolved,
    }


def exit_reason_breakdown(trades: Sequence) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in trades:
        reason = getattr(t, "exit_reason", None) or getattr(t, "reason", "")
        if reason.startswith("stop_loss"):
            reason = "stop_loss (ATR×3)"
        elif not isinstance(t, BreakoutTrade):
            reason = "SELL sinyali"
        out[reason] = out.get(reason, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# --------------------------------------------------------------------------
# Lookahead kontrolü (gerçek veri üzerinde de koşar)
# --------------------------------------------------------------------------

def truncate_data(price_data: dict[str, list[dict]], cutoff: str) -> dict[str, list[dict]]:
    return {
        s: [r for r in rows if r["timestamp"].date().isoformat() <= cutoff]
        for s, rows in price_data.items()
    }


def _trade_keys(trades, cutoff: Optional[str] = None) -> list[tuple]:
    return [
        (t.symbol, t.entry_date, t.exit_date, round(t.net_pnl, 6))
        for t in trades
        if cutoff is None or t.exit_date[:10] <= cutoff
    ]


def lookahead_check(universe: Sequence[dict], price_data: dict[str, list[dict]], capital: float) -> dict:
    """Veriyi pencerenin ortasında kes; kesim tarihine kadar her şey aynı olmalı.

    Kesik koşu gelecekteki barları hiç görmez. Eğer tam koşunun kesim
    tarihine kadarki herhangi bir kararı (girişler, kapanan işlemler, equity)
    gelecekteki bir bara bakıyorsa iki koşu ayrışır.
    """
    full_dates, _ = _sim_dates({e["symbol"]: price_data[e["symbol"]] for e in universe if e["symbol"] in price_data})
    if len(full_dates) < 10:
        return {"passed": None, "reason": "pencere çok kısa"}
    cutoff = full_dates[len(full_dates) // 2]
    cut = truncate_data(price_data, cutoff)
    flags_full = market_trend_flags(price_data)
    flags_cut = market_trend_flags(cut)

    result: dict = {"cutoff": cutoff, "arms": {}}
    for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        full = simulate_breakout(universe, price_data, capital, arm, trend_ok_by_date=flags_full)
        part = simulate_breakout(universe, cut, capital, arm, trend_ok_by_date=flags_cut)
        result["arms"][arm] = _compare_runs(
            full.equity_curve, part.equity_curve,
            _trade_keys(full.trades, cutoff), _trade_keys(part.trades),
            [e for e in full.events if e[0] <= cutoff], part.events, cutoff,
        )
    full_c = simulate(universe, price_data, capital, trend_ok_by_date=flags_full)
    part_c = simulate(universe, cut, capital, trend_ok_by_date=flags_cut)
    result["arms"][ARM_CURRENT] = _compare_runs(
        full_c.equity_curve, part_c.equity_curve,
        _trade_keys(full_c.trades, cutoff), _trade_keys(part_c.trades), [], [], cutoff,
    )
    full_cs = simulate_current(universe, price_data, capital, enforce_stop=True, trend_ok_by_date=flags_full)
    part_cs = simulate_current(universe, cut, capital, enforce_stop=True, trend_ok_by_date=flags_cut)
    result["arms"][ARM_CURRENT_STOP] = _compare_runs(
        full_cs.equity_curve, part_cs.equity_curve,
        _trade_keys(full_cs.trades, cutoff), _trade_keys(part_cs.trades), [], [], cutoff,
    )
    result["passed"] = all(v["passed"] for v in result["arms"].values())
    return result


def _compare_runs(eq_full, eq_part, tr_full, tr_part, ev_full, ev_part, cutoff) -> dict:
    eq_full_cut = [(d, round(v, 6)) for d, v in eq_full if d <= cutoff]
    eq_part_r = [(d, round(v, 6)) for d, v in eq_part]
    checks = {
        "equity_curve_identical": eq_full_cut == eq_part_r,
        "closed_trades_identical": tr_full == tr_part,
        "candidate_events_identical": ev_full == ev_part,
    }
    return {"passed": all(checks.values()), **checks, "closed_trades_compared": len(tr_part)}


def copy_matches_original(original, copy: CurrentSimResult) -> bool:
    """`simulate_current(enforce_stop=False)` ile `portfolio_backtest.simulate` birebir aynı mı?"""
    return (
        [(d, round(v, 6)) for d, v in original.equity_curve] == [(d, round(v, 6)) for d, v in copy.equity_curve]
        and _trade_keys(original.trades) == _trade_keys(copy.trades)
        and len(original.rejected) == len(copy.rejected)
    )


# --------------------------------------------------------------------------
# Orkestrasyon
# --------------------------------------------------------------------------

def run(years: int, synthetic: bool = False, params: BreakoutParams = DEFAULT_PARAMS) -> dict:
    print(f"Loading {len(BACKTEST_SYMBOLS)} symbols ({'synthetic' if synthetic else 'Twelve Data'}, {years}y)...")
    price_data = generate_synthetic_data(BACKTEST_SYMBOLS, years) if synthetic else load_price_data(BACKTEST_SYMBOLS, years)
    if not price_data:
        raise RuntimeError("No symbols returned usable data; nothing to backtest.")
    return run_on_data(price_data, synthetic=synthetic, params=params)


def run_on_data(price_data: dict[str, list[dict]], synthetic: bool, params: BreakoutParams = DEFAULT_PARAMS) -> dict:
    universe = [e for e in BACKTEST_SYMBOLS if e["symbol"] in price_data]
    trend_flags = market_trend_flags(price_data)

    print("Arm C (portfolio_backtest.simulate, reference) + copy check...")
    sim_c_original = simulate(universe, price_data, STARTING_CAPITAL, trend_ok_by_date=trend_flags)
    sim_c = simulate_current(universe, price_data, STARTING_CAPITAL, enforce_stop=False, trend_ok_by_date=trend_flags)
    if not copy_matches_original(sim_c_original, sim_c):
        raise RuntimeError("simulate_current(enforce_stop=False), portfolio_backtest.simulate ile aynı değil.")
    print("Arm C-stop (current system + live ATR x3 stop)...")
    sim_cs = simulate_current(universe, price_data, STARTING_CAPITAL, enforce_stop=True, trend_ok_by_date=trend_flags)
    dates = [d for d, _ in sim_c.equity_curve]

    print("Arm A / B (breakout)...")
    sims = {
        arm: simulate_breakout(universe, price_data, STARTING_CAPITAL, arm, params, trend_ok_by_date=trend_flags)
        for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT)
    }
    for arm, sim in sims.items():
        if [d for d, _ in sim.equity_curve] != dates:
            raise RuntimeError(f"Kol {arm} penceresi C ile aynı değil; karşılaştırma geçersiz olur.")

    curves = {arm: sims[arm].equity_curve for arm in sims} | {
        ARM_CURRENT: sim_c.equity_curve, ARM_CURRENT_STOP: sim_cs.equity_curve,
    }
    exposures = {arm: sims[arm].exposure for arm in sims} | {
        ARM_CURRENT: sim_c.exposure, ARM_CURRENT_STOP: sim_cs.exposure,
    }
    stats = {arm: trade_stats_from_breakout(sims[arm].trades) for arm in sims} | {
        ARM_CURRENT: trade_stats_from_current(sim_c.trades, dates),
        ARM_CURRENT_STOP: trade_stats_from_current(sim_cs.trades, dates),
    }
    open_at_end = {arm: len(sims[arm].open_trades_at_end) for arm in sims} | {
        ARM_CURRENT: len(sim_c.open_positions_at_end), ARM_CURRENT_STOP: len(sim_cs.open_positions_at_end),
    }
    metrics = {arm: compute_arm_metrics(arm, curves[arm], stats[arm], open_at_end[arm], exposures[arm]) for arm in ALL_ARMS}

    bh_curve, _, _ = buy_and_hold(universe, price_data, STARTING_CAPITAL)
    bh_exposure = [(d, 1.0) for d, _ in bh_curve]
    bh = compute_arm_metrics("B&H", bh_curve, [], None, bh_exposure)

    periods = {}
    for label, start, end in PERIODS:
        periods[label] = {
            arm: asdict(period_metrics(arm, curves[arm], exposures[arm], stats[arm], start, end)) for arm in ALL_ARMS
        } | {"B&H": asdict(period_metrics("B&H", bh_curve, bh_exposure, [], start, end))}
        sliced = slice_curve(bh_curve, start, end)
        periods[label]["_window"] = {"start": sliced[1][0] if len(sliced) > 1 else None, "end": sliced[-1][0] if sliced else None}

    # İzole sinyal çalışması: her sembol kendi hesabında, halt kapalı -- her
    # kırılma işleme dönüşür, portföy kısıtları huniyi bozmaz.
    print("Isolated per-symbol signal study (no portfolio constraints, halt off)...")
    per_symbol_capital = STARTING_CAPITAL / len(BACKTEST_SYMBOLS)
    isolated: dict[str, dict] = {}
    for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        funnel = Funnel()
        trades: list[BreakoutTrade] = []
        for entry in universe:
            r = simulate_breakout([entry], price_data, per_symbol_capital, arm, params, halt_policy=NO_HALT_POLICY)
            funnel.add(r.funnel)
            trades.extend(r.trades)
        iso_stats = trade_stats_from_breakout(trades)
        wins = [t for t in iso_stats if t.net_pnl > 0]
        losses = [t for t in iso_stats if t.net_pnl <= 0]
        gp, gl = sum(t.net_pnl for t in wins), -sum(t.net_pnl for t in losses)
        isolated[arm] = {
            "funnel": asdict(funnel),
            "rates": funnel_rates(funnel, trades),
            "trade_count": len(trades),
            "hit_rate": len(wins) / len(trades) if trades else None,
            "profit_factor": gp / gl if gl > 0 else None,
            "expectancy_r": _mean(t.r_multiple for t in iso_stats),
            "avg_bars_held": _mean(t.bars_held for t in iso_stats),
            "exit_reasons": exit_reason_breakdown(trades),
            "tp1_hit_rate": (sum(t.tp1_hit for t in trades) / len(trades)) if trades and arm == ARM_TP_SPLIT else None,
            "ambiguous_bars": sum(t.ambiguous_bars for t in trades),
        }

    print("Lookahead check (truncate at mid-window, compare)...")
    la = lookahead_check(universe, price_data, STARTING_CAPITAL)
    print(f"  passed={la['passed']}")

    def top3(trades):
        return [
            {"symbol": t.symbol, "entry_date": t.entry_date[:10], "exit_date": t.exit_date[:10], "net_pnl": t.net_pnl}
            for t in sorted(trades, key=lambda t: t.net_pnl, reverse=True)[:3]
        ]

    return {
        "synthetic": synthetic,
        "params": asdict(params),
        "costs": {
            "commission_pct_per_side": COMMISSION_PCT,
            "slippage_pct_per_side": SLIPPAGE_PCT,
            "avg_cost_pct_per_trade": {arm: metrics[arm].avg_cost_pct for arm in ALL_ARMS},
            "avg_cost_r_per_trade": {arm: metrics[arm].avg_cost_r for arm in ALL_ARMS},
        },
        "window": {"start": dates[0] if dates else "", "end": dates[-1] if dates else ""},
        "symbols": [e["symbol"] for e in universe],
        "excluded_symbols": [e["symbol"] for e in BACKTEST_SYMBOLS if e["symbol"] not in price_data],
        "volume_data": {s: prepare_series(price_data[s][:2], params).has_volume for s in price_data},
        "c_copy_matches_original": True,
        "metrics": {k: asdict(v) for k, v in metrics.items()},
        "buy_and_hold": asdict(bh),
        "periods": periods,
        "portfolio_funnel": {
            arm: {"funnel": asdict(sim.funnel), "rates": funnel_rates(sim.funnel, sim.trades)}
            for arm, sim in sims.items()
        },
        "exit_reasons": {arm: exit_reason_breakdown(sim.trades) for arm, sim in sims.items()}
        | {ARM_CURRENT: exit_reason_breakdown(sim_c.trades), ARM_CURRENT_STOP: exit_reason_breakdown(sim_cs.trades)},
        "ambiguous_bars": {arm: sum(t.ambiguous_bars for t in sim.trades) for arm, sim in sims.items()},
        "tp1_hit_rate_portfolio": (
            sum(t.tp1_hit for t in sims[ARM_TP_SPLIT].trades) / len(sims[ARM_TP_SPLIT].trades)
            if sims[ARM_TP_SPLIT].trades else None
        ),
        "rejected_signals": {arm: len(sim.rejected) for arm, sim in sims.items()}
        | {ARM_CURRENT: len(sim_c.rejected), ARM_CURRENT_STOP: len(sim_cs.rejected)},
        "top3_trades": {arm: top3(sim.trades) for arm, sim in sims.items()}
        | {ARM_CURRENT: top3(sim_c.trades), ARM_CURRENT_STOP: top3(sim_cs.trades)},
        "open_trades_at_end": {arm: sim.open_trades_at_end for arm, sim in sims.items()},
        "isolated_signal_study": isolated,
        "lookahead_check": la,
        "trades": {arm: [asdict(t) for t in sim.trades] for arm, sim in sims.items()}
        | {ARM_CURRENT: [asdict(t) for t in sim_c.trades], ARM_CURRENT_STOP: [asdict(t) for t in sim_cs.trades]},
    }


# --------------------------------------------------------------------------
# Rapor
# --------------------------------------------------------------------------

def _pct(v: Optional[float], digits: int = 2) -> str:
    return f"{v * 100:.{digits}f}%" if v is not None else "N/A"


def _num(v: Optional[float], digits: int = 2) -> str:
    return f"{v:.{digits}f}" if v is not None else "N/A"


def _usd(v: Optional[float]) -> str:
    return f"${v:,.0f}" if v is not None else "N/A"


METRIC_ROWS = [
    ("CAGR", lambda x: _pct(x["cagr"])),
    ("Toplam getiri", lambda x: _pct(x["total_return"])),
    ("Maks. drawdown", lambda x: _pct(x["max_drawdown"])),
    ("Sharpe", lambda x: _num(x["sharpe"])),
    ("Ort. exposure (pozisyon / equity)", lambda x: _pct(x["avg_exposure"], 1)),
    ("Piyasada gün oranı (≥1 pozisyon)", lambda x: _pct(x["days_in_market"], 1)),
    ("Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure)", lambda x: _pct(x["exposure_adj_cagr"])),
    ("Profit factor", lambda x: _num(x["profit_factor"])),
    ("Expectancy ($/işlem)", lambda x: _usd(x["expectancy_usd"])),
    ("Expectancy (%/işlem)", lambda x: _pct(x["expectancy_pct"])),
    ("Expectancy (R)", lambda x: _num(x["expectancy_r"])),
    ("Ort. kazanan / ort. kaybeden", lambda x: _num(x["avg_win_loss_ratio"])),
    ("İşlem sayısı (kapanan)", lambda x: str(x["trade_count"])),
    ("Ort. tutma süresi (işlem günü)", lambda x: _num(x["avg_bars_held"], 1)),
    ("İsabet oranı", lambda x: _pct(x["hit_rate"], 1)),
]


def _metric_table(L: list[str], cols: list[tuple[str, dict]], rows=METRIC_ROWS) -> None:
    L.append("| Metrik | " + " | ".join(label for label, _ in cols) + " |")
    L.append("|---|" + "---|" * len(cols))
    for label, fn in rows:
        cells = []
        for _, m in cols:
            try:
                cells.append(fn(m) if m.get("arm") != "B&H" or label in _BH_ROWS else "—")
            except (KeyError, TypeError):
                cells.append("—")
        L.append(f"| {label} | " + " | ".join(cells) + " |")


_BH_ROWS = {
    "CAGR", "Toplam getiri", "Maks. drawdown", "Sharpe", "Ort. exposure (pozisyon / equity)",
    "Piyasada gün oranı (≥1 pozisyon)", "Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure)",
}


def write_markdown(results: dict, path: Path) -> None:
    m = results["metrics"]
    p = results["params"]
    bh = results["buy_and_hold"]
    L: list[str] = []
    L.append("# Kırılma (Breakout) Mimarisi — Backtest Karşılaştırması")
    L.append("")
    if results["synthetic"]:
        L.append("> ⚠️ **SENTETİK VERİ.** Bu dosya kodun uçtan uca çalıştığını gösteren bir duman testidir; "
                 "rastgele yürüyüş fiyatları gerçek piyasa değildir. Sonuçlardan strateji hakkında hüküm çıkarılmaz.")
        L.append("")
    L.append(f"Üretim zamanı: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}  ")
    L.append(f"Pencere: {results['window']['start']} → {results['window']['end']}  ")
    L.append(f"Semboller ({len(results['symbols'])}): {', '.join(results['symbols'])}")
    if results["excluded_symbols"]:
        L.append(f"  \nVeri alınamayan (analiz dışı): {', '.join(results['excluded_symbols'])}")
    L.append("")
    L.append("Canlı sisteme bağlı değil: production kodu değişmedi, yalnızca `backtest/breakout_backtest.py` içinde simüle edildi.")
    L.append("")

    # 1) C ve stop
    L.append("## 1. C kolu ATR×3 stop uyguluyor mu?")
    L.append("")
    L.append("**Backtest'teki C (`portfolio_backtest.simulate`) uygulamıyor.** `evaluate_buy` pozisyona "
             f"Entry − {ATR_STOP_MULTIPLIER:g}×ATR stop'unu yazıyor ve boyutlandırmayı buna göre yapıyor, ama simülasyon "
             "bu stop'u hiç kontrol etmiyor; pozisyon yalnızca kural motorunun SELL sinyaliyle kapanıyor "
             f"(SELL'in \"ATR stop\" bacağı `close < önceki close − {ATR_STOP_MULTIPLIER:g}×önceki ATR` — tek günlük çöküş filtresi, girişe bağlı stop değil).")
    L.append("")
    L.append("**Canlı sistem uyguluyor:** `scripts/run_portfolio.py::_enforce_stop` her koşuda fiyat ≤ pozisyonun stop'u ise "
             "SELL sinyali beklemeden kapatıyor. Yani backtest'teki C canlıyı birebir temsil etmiyordu.")
    L.append("")
    L.append("**C-stop** bu farkı kapatır: C ile aynı kod (bu modüldeki kopya; stop kapalıyken `simulate` ile birebir aynı sonucu "
             "verdiği her koşuda doğrulanır) + her kapanışta `close ≤ stop` ise ertesi açılışta satış. Stop, canlıdaki gibi "
             "kural motorundan önce gelir.")
    L.append("")
    er = results["exit_reasons"]
    for arm in (ARM_CURRENT, ARM_CURRENT_STOP):
        L.append(f"- **{arm} çıkış nedenleri:** " + (", ".join(f"{k}: {v}" for k, v in er[arm].items()) or "—"))
    L.append("")

    # 2) Maliyet
    c = results["costs"]
    L.append("## 2. Komisyon / kayma varsayımı")
    L.append("")
    L.append(f"Varsayım **var** ve tüm tablolardaki sonuçlar bu maliyetler düşülmüş (net) hâlidir: komisyon işlem tutarının "
             f"%{c['commission_pct_per_side'] * 100:.2f}'i, kayma %{c['slippage_pct_per_side'] * 100:.2f}, her ikisi de her tarafta "
             f"(gidiş-dönüş ≈ %{(c['commission_pct_per_side'] + c['slippage_pct_per_side']) * 200:.2f}). "
             "Açılış ve stop dolumları kayma öder; A/B'de gün içi TP limit fiyattan dolar. "
             "Maliyet varsayımı olduğu için 0.05R / 0.1R ile yeniden koşu yapılmadı; mevcut varsayımın R cinsinden karşılığı:")
    L.append("")
    L.append("| | " + " | ".join(ALL_ARMS) + " |")
    L.append("|---|" + "---|" * len(ALL_ARMS))
    L.append("| Ort. işlem maliyeti (% giriş tutarı) | " + " | ".join(_pct(c["avg_cost_pct_per_trade"][a], 3) for a in ALL_ARMS) + " |")
    L.append("| Ort. işlem maliyeti (R) | " + " | ".join(_num(c["avg_cost_r_per_trade"][a], 3) for a in ALL_ARMS) + " |")
    L.append("")
    L.append(f"R: A/B'de Entry − {p['stop_atr']}×ATR; C/C-stop'ta `evaluate_buy`'ın boyutlandırdığı Entry − {ATR_STOP_MULTIPLIER:g}×ATR.")
    L.append("")

    # Ana tablo
    L.append("## Karşılaştırma (portföy geneli, aynı veri ve pencere)")
    L.append("")
    cols = [(ARM_LABELS[a], m[a]) for a in ALL_ARMS] + [("Al-ve-tut (eşit ağırlık)", bh)]
    _metric_table(L, cols)
    rej = results["rejected_signals"]
    L.append("| Dönem sonunda açık pozisyon | " + " | ".join(str(m[a]["open_at_end"]) for a in ALL_ARMS) + " | — |")
    L.append("| Reddedilen sinyal (risk motoru) | " + " | ".join(str(rej.get(a, 0)) for a in ALL_ARMS) + " | — |")
    L.append("")

    # 3) Exposure
    L.append("## 3. Exposure")
    L.append("")
    L.append("- **Ort. exposure:** her gün kapanışta açık pozisyonların piyasa değeri / equity; günlerin ortalaması. Al-ve-tut her zaman %100.")
    L.append("- **Piyasada gün oranı:** en az bir pozisyonun açık olduğu günlerin oranı.")
    L.append("- **Exposure'a göre düzeltilmiş CAGR** = CAGR / ort. exposure: sermayenin yalnızca yatırılan kısmının yıllık getirisi "
             "(kaldıraçla %100 exposure'a ölçeklemenin kabaca karşılığı; nakit getirisi ve kaldıraç maliyeti yok sayılır).")
    L.append("")

    # 4) Top-3
    L.append("## 4. En büyük 3 kazananın toplam kâra katkısı")
    L.append("")
    L.append("| | " + " | ".join(ALL_ARMS) + " |")
    L.append("|---|" + "---|" * len(ALL_ARMS))
    L.append("| Top-3 net kâr | " + " | ".join(_usd(m[a]["top3_net_pnl"]) for a in ALL_ARMS) + " |")
    L.append("| Toplam net kâr (kapanan işlemler) | " + " | ".join(_usd(m[a]["net_pnl_total"]) for a in ALL_ARMS) + " |")
    L.append("| Top-3 / toplam net kâr | " + " | ".join(_pct(m[a]["top3_share_of_net"], 1) for a in ALL_ARMS) + " |")
    L.append("| Top-3 / brüt kâr (kazananların toplamı) | " + " | ".join(_pct(m[a]["top3_share_of_gross_profit"], 1) for a in ALL_ARMS) + " |")
    L.append("")
    for a in ALL_ARMS:
        L.append(f"- **{a}:** " + ", ".join(
            f"{t['symbol']} {t['entry_date']}→{t['exit_date']} {_usd(t['net_pnl'])}" for t in results["top3_trades"][a]
        ))
    L.append("")
    L.append("Top-3 / toplam net kâr: toplam ≤ 0 ise tanımsız (N/A); %100'ün üstü geri kalan işlemlerin toplamda zarar ettiğini gösterir.")
    L.append("")

    # 5) Dönemler
    L.append("## 5. Alt dönemler")
    L.append("")
    L.append("Tek sürekli koşunun dilimleri: her dönem kendi başlangıç equity'sine göre ölçülür, portföy durumu (açık pozisyonlar, "
             "halt) dönem sınırında sıfırlanmaz. İşlemler çıkış tarihine göre dönemlere atanır.")
    L.append("")
    for label, block in results["periods"].items():
        w = block["_window"]
        L.append(f"### {label} ({w['start']} → {w['end']})")
        L.append("")
        cols = [(a, block[a]) for a in ALL_ARMS] + [("Al-ve-tut", block["B&H"])]
        _metric_table(L, cols)
        L.append("")

    # 6) B&H
    L.append("## 6. Al-ve-tut (bağlam)")
    L.append("")
    L.append("Eşit ağırlıklı, aynı evren, aynı pencere; giriş komisyonu ve kaymasını öder, yeniden dengeleme yok.")
    L.append("")
    L.append("| | Tüm pencere | " + " | ".join(results["periods"]) + " |")
    L.append("|---|---|" + "---|" * len(results["periods"]))
    for label, key, fn in [("Sharpe", "sharpe", _num), ("Maks. drawdown", "max_drawdown", _pct), ("CAGR", "cagr", _pct)]:
        L.append(f"| {label} | {fn(bh[key])} | " + " | ".join(fn(b['B&H'][key]) for b in results["periods"].values()) + " |")
    L.append("")

    # Kurallar
    L.append("## Kurallar (A/B)")
    L.append("")
    L.append(f"- **Aday:** EMA{p['ema_fast']} > EMA{p['ema_slow']} ve RSI14 ∈ [{p['rsi_min']:.0f}, {p['rsi_max']:.0f}]")
    L.append(f"- **Kırılma seviyesi:** önceki {p['lookback']} tamamlanmış barın en yüksek high'ı (bugünkü bar hariç)")
    L.append(f"- **Teyit:** Close > seviye + marj; marj {p['margin_atr_with_volume']}×ATR (hacim varsa) / "
             f"{p['margin_atr_without_volume']}×ATR (hacim yoksa); hacim varsa Volume > {p['volume_mult']}× önceki {p['volume_window']} günün ortalaması")
    L.append(f"- **Aday ömrü:** {p['candidate_ttl']} işlem günü; filtre bozulursa süreden bağımsız düşer. "
             "Kırılma barında filtre aranmaz. Süresi dolan aday, filtre bir kez bozulup yeniden kurulmadan tekrar aday olamaz.")
    L.append("- **Giriş:** kırılma T kapanışında teyit, T+1 açılışında alım")
    L.append(f"- **Pozisyon:** Stop = Entry − {p['stop_atr']}×ATR; TP1 = +{p['tp1_r']}R; TP2 = +{p['tp2_r']}R. "
             "Boyut: production `evaluate_buy` (%2 risk, %15 tahsis tavanı, kategori %40, max açık pozisyon, halt)")
    L.append(f"- **B:** TP1'de %{p['tp1_fraction'] * 100:.0f} satış, stop → Entry + {p['breakeven_atr']}×ATR; "
             f"kalan için iz süren stop = en yüksek kapanış − {p['trail_atr']}×ATR; TP2'de kalanın tamamı")
    L.append(f"- **A:** %100 pozisyon, TP yok; stop = max(initial, en yüksek kapanış − {p['trail_atr']}×ATR)")
    L.append("")
    L.append("### Aynı barda hem stop hem TP")
    L.append("")
    L.append("Kötümser: açılış önce işlenir (gap); açılıştan sonra aynı barda `low ≤ stop` ve `high ≥ TP` ise önce stop tetiklenmiş sayılır "
             "ve pozisyonun tamamı stop'tan kapanır. TP1 gün içinde dolarsa yeni stop ertesi bardan geçerlidir; TP1 ile aynı barda "
             "`high ≥ TP2` ise kalan TP2'den satılır. İz süren stop yalnızca kapanışta güncellenir.")
    amb = results["ambiguous_bars"]
    L.append(f"Belirsiz bar sayısı: A = {amb.get(ARM_TRAIL_ONLY, 0)}, B = {amb.get(ARM_TP_SPLIT, 0)}.")
    L.append("")

    # Huni
    iso = results["isolated_signal_study"]
    pf = results["portfolio_funnel"]
    L.append("## Huni (A/B)")
    L.append("")
    L.append("| | A — sinyal | B — sinyal | A — portföy | B — portföy |")
    L.append("|---|---|---|---|---|")

    def fr(block, key):
        return _pct(block["rates"][key], 1)

    L.append(f"| Aday → kırılma | {fr(iso['A'], 'candidate_to_breakout')} | {fr(iso['B'], 'candidate_to_breakout')} | "
             f"{fr(pf['A'], 'candidate_to_breakout')} | {fr(pf['B'], 'candidate_to_breakout')} |")
    L.append(f"| Kırılma → kârlı işlem | {fr(iso['A'], 'breakout_to_profitable_trade')} | {fr(iso['B'], 'breakout_to_profitable_trade')} | "
             f"{fr(pf['A'], 'breakout_to_profitable_trade')} | {fr(pf['B'], 'breakout_to_profitable_trade')} |")
    for key, label in [
        ("candidates", "Aday kaydı"), ("breakouts", "Kırılma"), ("expired", "Süresi doldu"),
        ("filter_broken", "Filtre bozuldu"), ("entries_executed", "Gerçekleşen giriş"),
        ("entries_rejected", "Risk motoru reddi"), ("entries_no_bar", "Ertesi gün bar yok"),
    ]:
        L.append(f"| {label} | {iso['A']['funnel'][key]} | {iso['B']['funnel'][key]} | {pf['A']['funnel'][key]} | {pf['B']['funnel'][key]} |")
    L.append("")
    L.append("Sinyal çalışması: her sembol kendi hesabında, halt kapalı (portföy kısıtları huniyi bozmaz).")
    L.append("")

    # Lookahead
    la = results["lookahead_check"]
    L.append("## Lookahead doğrulaması")
    L.append("")
    if la.get("passed") is None:
        L.append(f"Koşulamadı: {la.get('reason')}")
    else:
        L.append(f"Veri {la['cutoff']} tarihinde kesildi; kesik ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. "
                 f"**Sonuç: {'GEÇTİ ✅' if la['passed'] else 'BAŞARISIZ ❌'}**")
        L.append("")
        L.append("| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |")
        L.append("|---|---|---|---|---|")
        for arm, r in la["arms"].items():
            ev = "—" if arm in (ARM_CURRENT, ARM_CURRENT_STOP) else ("✅" if r["candidate_events_identical"] else "❌")
            L.append(f"| {arm} | {'✅' if r['equity_curve_identical'] else '❌'} | {'✅' if r['closed_trades_identical'] else '❌'} | {ev} | {r['closed_trades_compared']} |")
    L.append("")
    L.append(f"C kopyası (`simulate_current`, stop kapalı) ile `portfolio_backtest.simulate` birebir aynı: "
             f"{'✅' if results.get('c_copy_matches_original') else '❌'}")
    L.append("")

    L.append("## Sınırlamalar")
    L.append("")
    L.append("- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).")
    L.append("- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü.")
    L.append("- C-stop: canlı stop'u gün içi fiyatla kontrol eder; backtest günlük kapanışla kontrol edip ertesi açılışta satar "
             "(backtest'in genel yürütme kuralı). Gün içi delinip kapanışta geri dönen stoplar burada tetiklenmez.")
    L.append("- Kategori kırpması (`plan_category_trims`) hiçbir kolda simüle edilmiyor (mevcut `simulate` ile tutarlı).")
    L.append("- Dönem sonunda açık pozisyonlar işlem metriklerine girmez, equity eğrisine piyasa değeriyle girer.")
    L.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_json(results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **results}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
        f.write("\n")


def main(years: int, out_dir: str, synthetic: bool) -> int:
    results = run(years, synthetic=synthetic)
    out = Path(out_dir)
    write_json(results, out / "results.json")
    write_markdown(results, out / "summary.md")
    print(f"\nWrote {out}/summary.md and {out}/results.json")
    if results["lookahead_check"].get("passed") is False:
        print("::error::Lookahead kontrolü başarısız.")
        return 1
    return 0


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Breakout architecture backtest (A/B/C/C-stop arms).")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--out-dir", default="backtest/results/breakout")
    parser.add_argument("--synthetic", action="store_true", help="Sentetik veri (kod duman testi, ağ yok)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(main(args.years, args.out_dir, args.synthetic))
