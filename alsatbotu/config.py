"""Central configuration for the data layer and rule engine."""
from __future__ import annotations

import os
from pathlib import Path

from engine.halt import HaltPolicy

CACHE_DIR = Path(
    os.environ.get("ALSATBOTU_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache")
)
CACHE_TTL_SECONDS = int(os.environ.get("ALSATBOTU_CACHE_TTL_SECONDS", "300"))

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
TWELVEDATA_BASE_URL = "https://api.twelvedata.com"
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "")

REQUEST_TIMEOUT_SECONDS = 10

TELEGRAM_BASE_URL = "https://api.telegram.org"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# -- Paper portfolio / risk engine --------------------------------------

DATA_DIR = Path(os.environ.get("ALSATBOTU_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
PORTFOLIO_STATE_PATH = DATA_DIR / "portfolio.json"
SIGNALS_LEDGER_PATH = DATA_DIR / "signals.jsonl"

STARTING_CAPITAL = float(os.environ.get("ALSATBOTU_STARTING_CAPITAL", "10000"))

RISK_PER_TRADE_PCT = 0.02
CATEGORY_EXPOSURE_LIMIT_PCT = 0.40
MAX_OPEN_POSITIONS = 8

# -- Drawdown state machine (engine/halt.py) ----------------------------
# Kademeli duruş: equity high-water mark'ından ne kadar düşüldüğüne göre
# pozisyon kapasitesi %100 → %75 → %50 → %0'a iner. Giriş ve çıkış eşikleri
# farklıdır (histerezis): HALT'a %20'de girilir, %15'e dönünce çıkılır.
# Hepsi ortam değişkeniyle ezilebilir ki parametre süpürmesi
# (bkz. backtest/halt_sweep.py) canlı varsayılanları değiştirmeden koşabilsin.
HALT_ENTER_CAUTION_PCT = float(os.environ.get("ALSATBOTU_HALT_ENTER_CAUTION_PCT", "0.10"))
HALT_ENTER_DEFENSIVE_PCT = float(os.environ.get("ALSATBOTU_HALT_ENTER_DEFENSIVE_PCT", "0.15"))
# Eski `ALSATBOTU_MAX_DRAWDOWN_PCT` bu eşiğin adıydı; süpürme script'leri ve
# workflow'lar hâlâ onu geçebilsin diye fallback olarak okunuyor.
HALT_ENTER_HALT_PCT = float(
    os.environ.get(
        "ALSATBOTU_HALT_ENTER_HALT_PCT",
        os.environ.get("ALSATBOTU_MAX_DRAWDOWN_PCT", "0.20"),
    )
)

HALT_EXIT_CAUTION_PCT = float(os.environ.get("ALSATBOTU_HALT_EXIT_CAUTION_PCT", "0.05"))
HALT_EXIT_DEFENSIVE_PCT = float(os.environ.get("ALSATBOTU_HALT_EXIT_DEFENSIVE_PCT", "0.10"))
HALT_EXIT_HALT_PCT = float(os.environ.get("ALSATBOTU_HALT_EXIT_HALT_PCT", "0.15"))

HALT_CAPACITY_NORMAL = float(os.environ.get("ALSATBOTU_HALT_CAPACITY_NORMAL", "1.00"))
HALT_CAPACITY_CAUTION = float(os.environ.get("ALSATBOTU_HALT_CAPACITY_CAUTION", "0.75"))
HALT_CAPACITY_DEFENSIVE = float(os.environ.get("ALSATBOTU_HALT_CAPACITY_DEFENSIVE", "0.50"))
HALT_CAPACITY_HALT = float(os.environ.get("ALSATBOTU_HALT_CAPACITY_HALT", "0.00"))

# Zaman bazlı güvenlik ağı: HALT bu kadar takvim günü sürerse hesap tamamen
# kilitli kalmak yerine en küçük kademeyle (DEFENSIVE'in bir altı) yeniden
# denemeye başlar.
HALT_RECOVERY_DAYS = int(os.environ.get("ALSATBOTU_HALT_RECOVERY_DAYS", "14"))
HALT_RECOVERY_CAPACITY = float(os.environ.get("ALSATBOTU_HALT_RECOVERY_CAPACITY", "0.25"))
# Ağ yalnızca drawdown HALT'a girildiği günden beri derinleşmediyse açılır.
# VARSAYILAN KAPALI: sentetik ölçüm bu koşulun kilitlenmeyi geri getirdiğini
# gösterdi (bloke seriler 519-641 gün) ve portföy getirisini 6.7 puan
# düşürdü, karşılığında tabanın zaten yaptığı işi yaptı. Kod duruyor ki
# gerçek veride yeniden ölçülebilsin; açmak için env'i "1" yapın.
# Bkz. backtest/results/synthetic/halt_compare.md
HALT_RECOVERY_REQUIRES_STABLE_DRAWDOWN = (
    os.environ.get("ALSATBOTU_HALT_RECOVERY_REQUIRES_STABLE_DD", "0") not in ("0", "false", "False")
)

# Mutlak taban: bu drawdown'ın altında güvenlik ağı hiç açılmaz, kapasite
# koşulsuz sıfırdır. Kendi histerezisi var (taban %30'da bağlar, %25'te
# bırakır). Boş string = taban yok.
def _optional_pct(name: str, default: str) -> float | None:
    raw = os.environ.get(name, default).strip()
    return float(raw) if raw else None


HALT_FLOOR_PCT = _optional_pct("ALSATBOTU_HALT_FLOOR_PCT", "0.30")
HALT_FLOOR_EXIT_PCT = _optional_pct("ALSATBOTU_HALT_FLOOR_EXIT_PCT", "0.25")

DEFAULT_HALT_POLICY = HaltPolicy(
    enter_caution_pct=HALT_ENTER_CAUTION_PCT,
    enter_defensive_pct=HALT_ENTER_DEFENSIVE_PCT,
    enter_halt_pct=HALT_ENTER_HALT_PCT,
    exit_caution_pct=HALT_EXIT_CAUTION_PCT,
    exit_defensive_pct=HALT_EXIT_DEFENSIVE_PCT,
    exit_halt_pct=HALT_EXIT_HALT_PCT,
    capacity_normal=HALT_CAPACITY_NORMAL,
    capacity_caution=HALT_CAPACITY_CAUTION,
    capacity_defensive=HALT_CAPACITY_DEFENSIVE,
    capacity_halt=HALT_CAPACITY_HALT,
    recovery_days=HALT_RECOVERY_DAYS,
    recovery_capacity=HALT_RECOVERY_CAPACITY,
    recovery_requires_stable_drawdown=HALT_RECOVERY_REQUIRES_STABLE_DRAWDOWN,
    floor_pct=HALT_FLOOR_PCT,
    floor_exit_pct=HALT_FLOOR_EXIT_PCT,
)

# Geriye dönük uyumluluk: eski tek-eşikli mandalın adı, artık state
# machine'in HALT giriş eşiğinin alias'ı. `scripts/daily_report.py`,
# `backtest/` ve mevcut testler bunu kullanmaya devam ediyor; state
# machine devreye alınana kadar canlı davranış birebir aynı.
MAX_DRAWDOWN_PCT = HALT_ENTER_HALT_PCT

# Symbol -> category, used by the risk engine's category exposure cap.
# "other" is the fallback category for any symbol not listed here.
SYMBOL_CATEGORIES: dict[str, str] = {
    "AAPL": "tech",
    "MSFT": "tech",
    "GOOGL": "tech",
    "AMZN": "tech",
    "NVDA": "tech",
    "META": "tech",
    "JPM": "financials",
    "XOM": "energy",
    "WMT": "consumer",
    "KO": "consumer",
}

# The default watchlist the portfolio runner evaluates each time it runs.
WATCHLIST: list[dict] = [
    {"symbol": symbol, "category": category, "source": "twelvedata"}
    for symbol, category in SYMBOL_CATEGORIES.items()
]

# Symbol -> data source, derived from the watchlist above.
SYMBOL_SOURCES: dict[str, str] = {entry["symbol"]: entry["source"] for entry in WATCHLIST}


def category_for(symbol: str) -> str:
    return SYMBOL_CATEGORIES.get(symbol, "other")


def source_for(symbol: str, default: str = "coingecko") -> str:
    return SYMBOL_SOURCES.get(symbol, default)


def asset_type_for(source: str) -> str:
    return "crypto" if source == "coingecko" else "stock"


# -- Evaluation / paper-trading loop ------------------------------------
# See evaluation/ package: SQLite signal+outcome log, a paper portfolio run
# alongside (not instead of) the JSON-based one above, a daily Telegram
# report, and a weekly self-improvement loop over strategy parameters.

EVAL_DB_PATH = Path(os.environ.get("ALSATBOTU_EVAL_DB_PATH", DATA_DIR / "evaluation.db"))

PAPER_STARTING_CAPITAL = float(os.environ.get("ALSATBOTU_PAPER_STARTING_CAPITAL", "10000"))
PAPER_RISK_PER_TRADE_PCT = 0.01  # 1% of current equity notional per trade
PAPER_COMMISSION_PCT = 0.0015    # 0.15% commission, charged on entry and exit
PAPER_SLIPPAGE_PCT = 0.0005      # 0.05% slippage, charged on entry and exit
PAPER_ATR_STOP_MULTIPLIER = 1.5
PAPER_ATR_TARGET_MULTIPLIER = 2.5
PAPER_MAX_TRADES_PER_DAY = 100

OUTCOME_HORIZONS_HOURS = {"price_1h": 1, "price_24h": 24, "price_7d": 24 * 7}
