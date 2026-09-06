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
MAX_DRAWDOWN_PCT = 0.20

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


def category_for(symbol: str) -> str:
    return SYMBOL_CATEGORIES.get(symbol, "other")
