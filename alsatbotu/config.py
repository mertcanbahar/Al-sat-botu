"""Central configuration for the data layer and rule engine."""
from __future__ import annotations

import os
from pathlib import Path

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
# -- Drawdown halt (histerezisli) ---------------------------------------
# Equity peak'inden MAX_DRAWDOWN_PCT kadar düşülünce yeni ALIM durur (mevcut
# pozisyonlar satılmaya devam eder). Halt anlık bir hesap değil, kalıcı bir
# durumdur: ancak aşağıdaki koşullardan biriyle kalkar.
#
#   1. Toparlanma (histerezis): drawdown DRAWDOWN_RELEASE_PCT'ye inerse.
#   2. Kısmi peak reset'i: halt HALT_RESET_AFTER_MARKS işaretleme boyunca
#      sürmüş VE hesapta açık pozisyon kalmamışsa. Nakitteki bir hesabın
#      equity'si sabittir, yani (1) yapısal olarak imkânsızdır -- peak,
#      equity'ye doğru HALT_RESET_FRACTION kadar çekilerek halt bırakılır.
#      Koruma tamamen sıfırlanmaz, kademeli olarak gevşer.
#   3. Hiçbiri: MAX_HALT_RESETS reset'ten sonra ya da equity başlangıç
#      sermayesinin HALT_HARD_FLOOR_PCT altına düşerse bot KALICI olarak
#      durur ve yalnızca insan onayıyla (scripts/resume_halt.py) devam eder.
#
# Süpürme (backtest/halt_sweep.py) canlı varsayılanları değiştirmeden
# koşabilsin diye hepsi ortam değişkeniyle ezilebilir.
MAX_DRAWDOWN_PCT = float(os.environ.get("ALSATBOTU_MAX_DRAWDOWN_PCT", "0.20"))
DRAWDOWN_RELEASE_PCT = float(os.environ.get("ALSATBOTU_DRAWDOWN_RELEASE_PCT", "0.10"))
# Çırpınma freni: halt en az bu kadar işaretleme sürmeden toparlanmayla kalkmaz.
MIN_HALT_MARKS = int(os.environ.get("ALSATBOTU_MIN_HALT_MARKS", "10"))
HALT_RESET_AFTER_MARKS = int(os.environ.get("ALSATBOTU_HALT_RESET_AFTER_MARKS", "60"))
HALT_RESET_FRACTION = float(os.environ.get("ALSATBOTU_HALT_RESET_FRACTION", "0.5"))
MAX_HALT_RESETS = int(os.environ.get("ALSATBOTU_MAX_HALT_RESETS", "2"))
HALT_HARD_FLOOR_PCT = float(os.environ.get("ALSATBOTU_HALT_HARD_FLOOR_PCT", "0.50"))

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
