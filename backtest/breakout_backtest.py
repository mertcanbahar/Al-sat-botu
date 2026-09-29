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
from alsatbotu.indicators import ema, rsi
from alsatbotu.signal import ATR_STOP_MULTIPLIER
from backtest.portfolio_backtest import (
    BACKTEST_SYMBOLS,
    COMMISSION_PCT,
    SLIPPAGE_PCT,
    STARTING_CAPITAL,
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
ARM_CURRENT = "C"     # mevcut sistem (referans)

ARM_LABELS = {
    ARM_TRAIL_ONLY: "A: %100, TP yok, iz süren stop",
    ARM_TP_SPLIT: "B: %50 TP1 + %50 iz süren stop",
    ARM_CURRENT: "C: mevcut sistem (referans)",
}

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


def process_bar(t: OpenTrade, o: float, h: float, l: float) -> list[ExitOrder]:
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

    stop_reason = "initial_stop" if not t.tp1_done else (
        "trail_stop" if stop > t.entry_price + 1e-12 and stop > t.initial_stop else "breakeven_stop"
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
        t.fills.append(
            {"date": d, "quantity": closed.quantity, "price": price, "reason": order.reason, "fee": fee}
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
            open_trades[symbol] = t
            funnel.entries_executed += 1

        # 2) Gün içi stop/TP (giriş barı dahil: giriş açılışta, barın geri kalanı sonrasında).
        for symbol, t in list(open_trades.items()):
            if symbol not in today:
                continue
            row = rows_by_symbol[symbol][today[symbol]]
            for order in process_bar(t, row["open"], row["high"], row["low"]):
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
    )


# --------------------------------------------------------------------------
# Metrikler (üç kol için ortak)
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
    open_at_end: int


def trade_stats_from_breakout(trades: Sequence[BreakoutTrade]) -> list[TradeStat]:
    return [
        TradeStat(t.symbol, t.entry_date, t.exit_date, t.net_pnl, t.net_pnl_pct, t.bars_held, t.r_multiple)
        for t in trades
    ]


def trade_stats_from_current(trades: Sequence, sim_dates: Sequence[str]) -> list[TradeStat]:
    """C kolunun NetTrade kayıtları; tutma süresi aynı işlem günü ekseninde."""
    pos = {d: k for k, d in enumerate(sim_dates)}
    out = []
    for t in trades:
        entry = t.entry_date[:10]
        exit_ = t.exit_date[:10]
        out.append(
            TradeStat(t.symbol, entry, exit_, t.net_pnl, t.net_pnl_pct, pos.get(exit_, 0) - pos.get(entry, 0))
        )
    return out


def compute_arm_metrics(
    arm: str, equity_curve: list[tuple[str, float]], stats: Sequence[TradeStat], open_at_end: int
) -> ArmMetrics:
    total_return, cagr, max_dd, sharpe = compute_curve_metrics(equity_curve)
    n = len(stats)
    wins = [t for t in stats if t.net_pnl > 0]
    losses = [t for t in stats if t.net_pnl <= 0]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    net_total = gross_profit - gross_loss

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    ratio = None
    if wins and losses:
        avg_loss = statistics.fmean(t.net_pnl_pct for t in losses)
        if avg_loss:
            ratio = statistics.fmean(t.net_pnl_pct for t in wins) / abs(avg_loss)
    rs = [t.r_multiple for t in stats if t.r_multiple is not None]

    top3 = sorted((t.net_pnl for t in stats), reverse=True)[:3]
    top3_sum = sum(top3)
    top3_positive = sum(p for p in top3 if p > 0)

    return ArmMetrics(
        arm=arm,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_dd,
        sharpe=sharpe,
        trade_count=n,
        hit_rate=len(wins) / n if n else None,
        profit_factor=profit_factor,
        expectancy_usd=net_total / n if n else None,
        expectancy_pct=statistics.fmean(t.net_pnl_pct for t in stats) if n else None,
        expectancy_r=statistics.fmean(rs) if rs else None,
        avg_win_loss_ratio=ratio,
        avg_bars_held=statistics.fmean(t.bars_held for t in stats) if n else None,
        net_pnl_total=net_total,
        top3_net_pnl=top3_sum,
        top3_share_of_net=top3_sum / net_total if net_total > 0 else None,
        top3_share_of_gross_profit=top3_positive / gross_profit if gross_profit > 0 else None,
        open_at_end=open_at_end,
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


def exit_reason_breakdown(trades: Sequence[BreakoutTrade]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in trades:
        out[t.exit_reason] = out.get(t.exit_reason, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# --------------------------------------------------------------------------
# Lookahead kontrolü (gerçek veri üzerinde de koşar)
# --------------------------------------------------------------------------

def truncate_data(price_data: dict[str, list[dict]], cutoff: str) -> dict[str, list[dict]]:
    return {
        s: [r for r in rows if r["timestamp"].date().isoformat() <= cutoff]
        for s, rows in price_data.items()
    }


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
            [(t.symbol, t.entry_date, t.exit_date, round(t.net_pnl, 6)) for t in full.trades if t.exit_date <= cutoff],
            [(t.symbol, t.entry_date, t.exit_date, round(t.net_pnl, 6)) for t in part.trades],
            [e for e in full.events if e[0] <= cutoff],
            part.events,
            cutoff,
        )
    full_c = simulate(universe, price_data, capital, trend_ok_by_date=flags_full)
    part_c = simulate(universe, cut, capital, trend_ok_by_date=flags_cut)
    result["arms"][ARM_CURRENT] = _compare_runs(
        full_c.equity_curve, part_c.equity_curve,
        [(t.symbol, t.entry_date, t.exit_date, round(t.net_pnl, 6)) for t in full_c.trades if t.exit_date[:10] <= cutoff],
        [(t.symbol, t.entry_date, t.exit_date, round(t.net_pnl, 6)) for t in part_c.trades],
        [], [], cutoff,
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

    print("Arm C (current system)...")
    sim_c = simulate(universe, price_data, STARTING_CAPITAL, trend_ok_by_date=trend_flags)
    c_dates = [d for d, _ in sim_c.equity_curve]
    print("Arm A / B (breakout)...")
    sims = {
        arm: simulate_breakout(universe, price_data, STARTING_CAPITAL, arm, params, trend_ok_by_date=trend_flags)
        for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT)
    }
    for arm, sim in sims.items():
        if [d for d, _ in sim.equity_curve] != c_dates:
            raise RuntimeError(f"Kol {arm} penceresi C ile aynı değil; karşılaştırma geçersiz olur.")

    metrics = {
        ARM_CURRENT: compute_arm_metrics(
            ARM_CURRENT, sim_c.equity_curve, trade_stats_from_current(sim_c.trades, c_dates),
            len(sim_c.open_positions_at_end),
        )
    }
    for arm, sim in sims.items():
        metrics[arm] = compute_arm_metrics(
            arm, sim.equity_curve, trade_stats_from_breakout(sim.trades), len(sim.open_trades_at_end)
        )

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
        stats = trade_stats_from_breakout(trades)
        wins = [t for t in stats if t.net_pnl > 0]
        losses = [t for t in stats if t.net_pnl <= 0]
        gp, gl = sum(t.net_pnl for t in wins), -sum(t.net_pnl for t in losses)
        isolated[arm] = {
            "funnel": asdict(funnel),
            "rates": funnel_rates(funnel, trades),
            "trade_count": len(trades),
            "hit_rate": len(wins) / len(trades) if trades else None,
            "profit_factor": gp / gl if gl > 0 else None,
            "expectancy_r": statistics.fmean(t.r_multiple for t in stats if t.r_multiple is not None) if stats else None,
            "avg_bars_held": statistics.fmean(t.bars_held for t in stats) if stats else None,
            "exit_reasons": exit_reason_breakdown(trades),
            "tp1_hit_rate": (sum(t.tp1_hit for t in trades) / len(trades)) if trades and arm == ARM_TP_SPLIT else None,
            "ambiguous_bars": sum(t.ambiguous_bars for t in trades),
        }

    print("Lookahead check (truncate at mid-window, compare)...")
    la = lookahead_check(universe, price_data, STARTING_CAPITAL)
    print(f"  passed={la['passed']}")

    bh_curve, _, _ = buy_and_hold(universe, price_data, STARTING_CAPITAL)
    bh = compute_curve_metrics(bh_curve)

    return {
        "synthetic": synthetic,
        "params": asdict(params),
        "window": {"start": c_dates[0] if c_dates else "", "end": c_dates[-1] if c_dates else ""},
        "symbols": [e["symbol"] for e in universe],
        "excluded_symbols": [e["symbol"] for e in BACKTEST_SYMBOLS if e["symbol"] not in price_data],
        "volume_data": {s: prepare_series(price_data[s][:2], params).has_volume for s in price_data},
        "metrics": {k: asdict(v) for k, v in metrics.items()},
        "buy_and_hold": dict(zip(("total_return", "cagr", "max_drawdown", "sharpe"), bh)),
        "portfolio_funnel": {
            arm: {"funnel": asdict(sim.funnel), "rates": funnel_rates(sim.funnel, sim.trades)}
            for arm, sim in sims.items()
        },
        "exit_reasons": {arm: exit_reason_breakdown(sim.trades) for arm, sim in sims.items()},
        "ambiguous_bars": {arm: sum(t.ambiguous_bars for t in sim.trades) for arm, sim in sims.items()},
        "tp1_hit_rate_portfolio": (
            sum(t.tp1_hit for t in sims[ARM_TP_SPLIT].trades) / len(sims[ARM_TP_SPLIT].trades)
            if sims[ARM_TP_SPLIT].trades else None
        ),
        "rejected_signals": {arm: len(sim.rejected) for arm, sim in sims.items()} | {ARM_CURRENT: len(sim_c.rejected)},
        "top3_trades": {
            arm: [asdict(t) for t in sorted(sim.trades, key=lambda t: t.net_pnl, reverse=True)[:3]]
            for arm, sim in sims.items()
        } | {
            ARM_CURRENT: [vars(t) for t in sorted(sim_c.trades, key=lambda t: t.net_pnl, reverse=True)[:3]]
        },
        "open_trades_at_end": {arm: sim.open_trades_at_end for arm, sim in sims.items()},
        "isolated_signal_study": isolated,
        "lookahead_check": la,
        "trades": {arm: [asdict(t) for t in sim.trades] for arm, sim in sims.items()},
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


def write_markdown(results: dict, path: Path) -> None:
    m = results["metrics"]
    arms = [ARM_TRAIL_ONLY, ARM_TP_SPLIT, ARM_CURRENT]
    p = results["params"]
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

    L.append("## Kurallar")
    L.append("")
    L.append(f"- **Aday:** EMA{p['ema_fast']} > EMA{p['ema_slow']} ve RSI14 ∈ [{p['rsi_min']:.0f}, {p['rsi_max']:.0f}]")
    L.append(f"- **Kırılma seviyesi:** önceki {p['lookback']} tamamlanmış barın en yüksek high'ı (bugünkü bar hariç)")
    L.append(f"- **Teyit:** Close > seviye + marj; marj {p['margin_atr_with_volume']}×ATR (hacim varsa) / "
             f"{p['margin_atr_without_volume']}×ATR (hacim yoksa); hacim varsa Volume > {p['volume_mult']}× önceki {p['volume_window']} günün ortalaması")
    L.append(f"- **Aday ömrü:** {p['candidate_ttl']} işlem günü; filtre bozulursa süreden bağımsız düşer. "
             "Kırılma barında filtre aranmaz (kırılma kontrolü o günün filtre kontrolünden önce yapılır). "
             "Süresi dolan aday, filtre bir kez bozulup yeniden kurulmadan tekrar aday olamaz.")
    L.append("- **Giriş:** kırılma T kapanışında teyit, T+1 açılışında alım")
    L.append(f"- **Pozisyon:** Stop = Entry − {p['stop_atr']}×ATR; 1R = Entry − Stop; TP1 = +{p['tp1_r']}R; TP2 = +{p['tp2_r']}R. "
             "Boyut: production `evaluate_buy` (%2 risk, %15 tahsis tavanı, kategori %40, max açık pozisyon, halt)")
    L.append(f"- **B:** TP1'de %{p['tp1_fraction'] * 100:.0f} satış, stop → Entry + {p['breakeven_atr']}×ATR; "
             f"kalan için iz süren stop = en yüksek kapanış − {p['trail_atr']}×ATR; TP2'de kalanın tamamı")
    L.append(f"- **A:** %100 pozisyon, TP yok; stop = max(initial, en yüksek kapanış − {p['trail_atr']}×ATR)")
    L.append("- **C:** mevcut sistem (`alsatbotu.signal.evaluate` + `engine.risk.evaluate_buy`), `portfolio_backtest.simulate` ile birebir")
    L.append(f"- **Maliyet:** komisyon %{COMMISSION_PCT * 100:.2f}, slipaj %{SLIPPAGE_PCT * 100:.2f} (her taraf); "
             "stop ve açılış (gap) dolumları slipajlı, gün içi TP limit fiyattan")
    L.append("")

    L.append("## Aynı barda hem stop hem TP tetiklenirse")
    L.append("")
    L.append("Günlük OHLC barından gün içi sıra bilinemez; kural **kötümser**:")
    L.append("")
    L.append("1. Açılış sırası bilinen tek fiyattır: açılış stop'un altındaysa tüm pozisyon açılıştan, hedefin üstündeyse hedef açılıştan dolar.")
    L.append("2. Açılıştan sonra aynı bar hem `low ≤ stop` hem `high ≥ TP` ise **önce stop tetiklenmiş sayılır**; pozisyonun tamamı stop'tan kapanır, TP gerçekleşmemiş sayılır.")
    L.append("3. TP1 gün içinde dolarsa yeni stop (Entry + 0.2×ATR) ve iz süren stop **ertesi bardan** itibaren geçerlidir (low'un TP1'den önce mi sonra mı oluştuğu bilinemez).")
    L.append("4. TP1 ile aynı barda `high ≥ TP2` ise kalan TP2'den satılır (TP2'ye ancak TP1 geçildikten sonra ulaşılabilir).")
    L.append("5. İz süren stop yalnızca kapanışta güncellenir, ertesi bardan geçerlidir.")
    L.append("")
    amb = results["ambiguous_bars"]
    L.append(f"Portföy koşusunda belirsiz (stop+TP aynı bar) bar sayısı: A = {amb.get(ARM_TRAIL_ONLY, 0)}, B = {amb.get(ARM_TP_SPLIT, 0)}.")
    L.append("")

    L.append("## Karşılaştırma (portföy geneli, aynı veri ve pencere)")
    L.append("")
    L.append("| Metrik | " + " | ".join(ARM_LABELS[a] for a in arms) + " | Al-ve-tut (bağlam) |")
    L.append("|---|" + "---|" * (len(arms) + 1))
    bh = results["buy_and_hold"]
    rows = [
        ("CAGR", lambda x: _pct(x["cagr"]), _pct(bh["cagr"])),
        ("Toplam getiri", lambda x: _pct(x["total_return"]), _pct(bh["total_return"])),
        ("Maks. drawdown", lambda x: _pct(x["max_drawdown"]), _pct(bh["max_drawdown"])),
        ("Sharpe", lambda x: _num(x["sharpe"]), _num(bh["sharpe"])),
        ("Profit factor", lambda x: _num(x["profit_factor"]), "—"),
        ("Expectancy ($/işlem)", lambda x: _usd(x["expectancy_usd"]), "—"),
        ("Expectancy (%/işlem)", lambda x: _pct(x["expectancy_pct"]), "—"),
        ("Expectancy (R)", lambda x: _num(x["expectancy_r"]), "—"),
        ("Ort. kazanan / ort. kaybeden", lambda x: _num(x["avg_win_loss_ratio"]), "—"),
        ("İşlem sayısı (kapanan)", lambda x: str(x["trade_count"]), "—"),
        ("Ort. tutma süresi (işlem günü)", lambda x: _num(x["avg_bars_held"], 1), "—"),
        ("İsabet oranı", lambda x: _pct(x["hit_rate"], 1), "—"),
        ("Dönem sonunda açık pozisyon", lambda x: str(x["open_at_end"]), "—"),
    ]
    for label, fn, bh_val in rows:
        L.append(f"| {label} | " + " | ".join(fn(m[a]) for a in arms) + f" | {bh_val} |")
    rej = results["rejected_signals"]
    L.append("| Reddedilen sinyal (risk motoru) | " + " | ".join(str(rej.get(a, 0)) for a in arms) + " | — |")
    L.append("")
    L.append("Expectancy (R) C kolu için tanımsız: mevcut sistem sabit bir 1R ile çalışmıyor. "
             "Ort. kazanan/kaybeden oranı işlem başı yüzde getiriler üzerinden (mevcut raporla aynı tanım).")
    L.append("")

    L.append("## İstenen üç oran")
    L.append("")
    iso = results["isolated_signal_study"]
    pf = results["portfolio_funnel"]
    L.append("**Sinyal çalışması** (her sembol kendi hesabında, halt kapalı — her kırılma işleme dönüşür, portföy kısıtları huniyi bozmaz) "
             "ve **portföy koşusu** (kısıtlar bağlıyken) ayrı ayrı:")
    L.append("")
    L.append("| Oran | A — sinyal çalışması | B — sinyal çalışması | A — portföy | B — portföy |")
    L.append("|---|---|---|---|---|")

    def fr(block, key):
        return _pct(block["rates"][key], 1)

    L.append(f"| 1. Aday → kırılma dönüşümü | {fr(iso['A'], 'candidate_to_breakout')} | {fr(iso['B'], 'candidate_to_breakout')} | "
             f"{fr(pf['A'], 'candidate_to_breakout')} | {fr(pf['B'], 'candidate_to_breakout')} |")
    L.append(f"| 2. Kırılma → kârlı işlem (kapanan işlemler içinde) | {fr(iso['A'], 'breakout_to_profitable_trade')} | "
             f"{fr(iso['B'], 'breakout_to_profitable_trade')} | {fr(pf['A'], 'breakout_to_profitable_trade')} | "
             f"{fr(pf['B'], 'breakout_to_profitable_trade')} |")
    L.append(f"| 2b. Kârlı işlem / tüm kırılma sinyalleri | {fr(iso['A'], 'breakout_to_profitable_over_all_signals')} | "
             f"{fr(iso['B'], 'breakout_to_profitable_over_all_signals')} | {fr(pf['A'], 'breakout_to_profitable_over_all_signals')} | "
             f"{fr(pf['B'], 'breakout_to_profitable_over_all_signals')} |")
    L.append("")
    L.append("| 3. En büyük 3 kazananın katkısı (portföy) | A | B | C |")
    L.append("|---|---|---|---|")
    L.append("| Top-3 net kâr | " + " | ".join(_usd(m[a]["top3_net_pnl"]) for a in arms) + " |")
    L.append("| Toplam net kâr (kapanan işlemler) | " + " | ".join(_usd(m[a]["net_pnl_total"]) for a in arms) + " |")
    L.append("| Top-3 / toplam net kâr | " + " | ".join(_pct(m[a]["top3_share_of_net"], 1) for a in arms) + " |")
    L.append("| Top-3 / brüt kâr (kazananların toplamı) | " + " | ".join(_pct(m[a]["top3_share_of_gross_profit"], 1) for a in arms) + " |")
    L.append("")
    L.append("Top-3 / toplam net kâr: toplam net kâr ≤ 0 ise tanımsız (N/A). %100'ün üstü, geri kalan işlemlerin toplamda zarar ettiği anlamına gelir.")
    L.append("")

    L.append("### Huni ayrıntısı")
    L.append("")
    L.append("| | A — sinyal | B — sinyal | A — portföy | B — portföy |")
    L.append("|---|---|---|---|---|")
    for key, label in [
        ("candidates", "Aday kaydı"),
        ("breakouts", "Kırılma"),
        ("expired", "Süresi doldu (7 gün)"),
        ("filter_broken", "Filtre bozuldu"),
        ("candidates_open_at_end", "Dönem sonunda açık aday"),
        ("entries_executed", "Gerçekleşen giriş"),
        ("entries_rejected", "Risk motoru reddi"),
        ("entries_no_bar", "Ertesi gün bar yok"),
    ]:
        L.append(f"| {label} | {iso['A']['funnel'][key]} | {iso['B']['funnel'][key]} | {pf['A']['funnel'][key]} | {pf['B']['funnel'][key]} |")
    L.append("")

    L.append("### Çıkış nedenleri (portföy)")
    L.append("")
    for arm in (ARM_TRAIL_ONLY, ARM_TP_SPLIT):
        reasons = ", ".join(f"{k}: {v}" for k, v in results["exit_reasons"][arm].items()) or "—"
        L.append(f"- **{arm}:** {reasons}")
    L.append(f"- **B TP1'e ulaşma oranı:** {_pct(results['tp1_hit_rate_portfolio'], 1)}")
    L.append("")

    la = results["lookahead_check"]
    L.append("## Lookahead doğrulaması")
    L.append("")
    if la.get("passed") is None:
        L.append(f"Koşulamadı: {la.get('reason')}")
    else:
        L.append(f"Veri {la['cutoff']} tarihinde kesildi; kesik veriyle ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. "
                 f"**Sonuç: {'GEÇTİ ✅' if la['passed'] else 'BAŞARISIZ ❌'}**")
        L.append("")
        L.append("| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |")
        L.append("|---|---|---|---|---|")
        for arm, r in la["arms"].items():
            ev = "—" if arm == ARM_CURRENT else ("✅" if r["candidate_events_identical"] else "❌")
            L.append(f"| {arm} | {'✅' if r['equity_curve_identical'] else '❌'} | {'✅' if r['closed_trades_identical'] else '❌'} | {ev} | {r['closed_trades_compared']} |")
    L.append("")
    L.append("Ayrıca birim testleri (`tests/test_breakout_backtest.py`): göstergelerin kesik seri üzerinde aynı değeri vermesi, "
             "kırılma seviyesinin bugünkü barı içermemesi, gelecekteki barların bozulmasının geçmiş kararları değiştirmemesi.")
    L.append("")

    L.append("## Sınırlamalar")
    L.append("")
    L.append("- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).")
    L.append("- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü; gerçek sonuç bundan iyi olabilir, kötü olamaz (bu varsayım altında).")
    L.append("- Kategori kırpması (`plan_category_trims`) üç kolda da simüle edilmiyor (mevcut `simulate` ile tutarlı).")
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
    parser = argparse.ArgumentParser(description="Breakout architecture backtest (A/B/C arms).")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--out-dir", default="backtest/results/breakout")
    parser.add_argument("--synthetic", action="store_true", help="Sentetik veri (kod duman testi, ağ yok)")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(main(args.years, args.out_dir, args.synthetic))
