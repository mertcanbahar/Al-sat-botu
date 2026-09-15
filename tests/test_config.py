"""Tests for the watchlist/category/asset-type helpers in alsatbotu.config."""
from __future__ import annotations

from alsatbotu import config


def test_forex_symbols_are_in_the_watchlist_under_the_forex_category():
    forex_entries = [w for w in config.WATCHLIST if w["category"] == "forex"]
    assert forex_entries, "forex sembolleri WATCHLIST'e eklenmemiş"
    for entry in forex_entries:
        assert entry["symbol"] in config.FOREX_SYMBOLS
        assert entry["source"] == "twelvedata"


def test_category_for_forex_symbol_is_forex():
    for symbol in config.FOREX_SYMBOLS:
        assert config.category_for(symbol) == "forex"


def test_asset_type_for_distinguishes_forex_from_stock_even_though_both_use_twelvedata():
    assert config.asset_type_for("twelvedata", "forex") == "forex"
    assert config.asset_type_for("twelvedata", "tech") == "stock"
    assert config.asset_type_for("twelvedata", None) == "stock"


def test_asset_type_for_crypto_is_unaffected_by_category():
    assert config.asset_type_for("coingecko", "forex") == "crypto"
    assert config.asset_type_for("coingecko", None) == "crypto"
