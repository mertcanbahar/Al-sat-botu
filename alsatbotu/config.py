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
# Twelve Data ücretsiz planı dakikada 8 istek kabul ediyor; fazlası HTTP 429
# döner. İzleme listesi 16 sembol olduğu için istemci tarafında bu hıza
# uyulmazsa listenin kuyruğu (WMT, KO, forex) her koşuda fiyatsız kalıyordu.
TWELVEDATA_REQUESTS_PER_MINUTE = int(os.environ.get("ALSATBOTU_TWELVEDATA_RPM", "8"))

REQUEST_TIMEOUT_SECONDS = 10

TELEGRAM_BASE_URL = "https://api.telegram.org"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# -- Paper portfolio / risk engine --------------------------------------

DATA_DIR = Path(os.environ.get("ALSATBOTU_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
PORTFOLIO_STATE_PATH = DATA_DIR / "portfolio.json"
SIGNALS_LEDGER_PATH = DATA_DIR / "signals.jsonl"
# scripts/process_telegram_controls.py'nin kendi getUpdates offset'i --
# evaluation.db'deki telegram_offset tablosundan (strateji onay akışı)
# bilerek ayrı: iki bağımsız kısa-poll tüketicisi, her biri kendi high-water
# mark'ını tutar, callback_data önekine göre ilgilenmediği güncellemeleri
# atlar ama yine de offset'ini onların da ötesine taşır.
TELEGRAM_CONTROL_OFFSET_PATH = DATA_DIR / "telegram_control_offset.json"

# -- Sermaye ve vade ----------------------------------------------------
# SERMAYE: paper portföyün başlangıç sermayesi. Bir state dosyası varsa o
# dosya kaynaktır; bu değer yalnızca portföy ilk kez yaratılırken kullanılır.
SERMAYE = float(
    os.environ.get("ALSATBOTU_SERMAYE", os.environ.get("ALSATBOTU_STARTING_CAPITAL", "10000"))
)
STARTING_CAPITAL = SERMAYE  # eski ad, kod tabanının geri kalanı bunu kullanıyor

# VADE: "kisa" ya da "uzun". Tek bir anahtar, birbirine bağlı dört ayarı
# birlikte değiştirir -- ayrı ayrı kurcalanınca tutarsız kombinasyonlar
# çıkıyordu (ör. uzun EMA + sıkı stop = trend daha başlamadan stop olmak).
#
#   kisa: hızlı dönen sinyal, gürültüye yakın stop, çok sayıda küçük pozisyon.
#         EMA 10/30 (~2 hafta / ~6 hafta), ATR stop x1.5, 10 pozisyon, %8 tahsis.
#   uzun: mevcut canlı davranışın devamı. EMA 20/50 (~1 ay / ~2.5 ay), stop
#         normal dalgalanmayı yutacak kadar geniş (ATR x3), 5 pozisyon, %15.
#
# Tahsis oranları toplamda yatırımlı kalma seviyesini de belirler:
# 10 x %8 = %80, 5 x %15 = %75. İkisi de nakit tamponu bırakır.
# Boş değer "tanımsız" demektir: GitHub Actions'ta tanımlanmamış bir
# repository variable ifadesi boş string olarak gelir ve bunu geçersiz sayıp
# hata fırlatmak, değişkeni unutan bir koşuda botu çökertirdi.
VADE = (os.environ.get("ALSATBOTU_VADE") or "").strip().lower() or "uzun"

VADE_PROFILLERI: dict[str, dict] = {
    "kisa": {
        "ema_fast": 10,
        "ema_slow": 30,
        "atr_stop_multiplier": 1.5,
        "max_open_positions": 10,
        "max_position_allocation_pct": 0.08,
    },
    "uzun": {
        "ema_fast": 20,
        "ema_slow": 50,
        "atr_stop_multiplier": 3.0,
        "max_open_positions": 5,
        "max_position_allocation_pct": 0.15,
    },
}

if VADE not in VADE_PROFILLERI:
    raise ValueError(
        f"ALSATBOTU_VADE={VADE!r} geçersiz; geçerli değerler: {sorted(VADE_PROFILLERI)}"
    )

_VADE_PROFILI = VADE_PROFILLERI[VADE]

# Tek bir pozisyonun equity'nin bu oranından fazlasını tutmasına asla izin
# verilmez. Vade profili bunun altında bir değer önerebilir ama üstüne
# çıkamaz: nakdin tek bir isme akıp sonraki sinyallerin "nakit yok" diye
# reddedilmesi tam olarak bu tavanın engellediği şey.
POSITION_ALLOCATION_HARD_CAP = 0.15

RISK_PER_TRADE_PCT = 0.02
MAX_POSITION_ALLOCATION_PCT = min(
    float(
        os.environ.get(
            "ALSATBOTU_MAX_POSITION_ALLOCATION_PCT",
            _VADE_PROFILI["max_position_allocation_pct"],
        )
    ),
    POSITION_ALLOCATION_HARD_CAP,
)
EMA_FAST_PERIOD = int(os.environ.get("ALSATBOTU_EMA_FAST", _VADE_PROFILI["ema_fast"]))
EMA_SLOW_PERIOD = int(os.environ.get("ALSATBOTU_EMA_SLOW", _VADE_PROFILI["ema_slow"]))
ATR_STOP_MULTIPLIER = float(
    os.environ.get("ALSATBOTU_ATR_STOP_MULTIPLIER", _VADE_PROFILI["atr_stop_multiplier"])
)
# Anlamsız küçüklükteki pozisyonlar hiç açılmasın. Nakit tükendiğinde
# cash/entry_price sıfır değil, ~1e-9 gibi pozitif bir float çıkıyor; eski
# "quantity <= 0" kontrolü bunu geçiriyor ve raporda 0.000000 adetlik
# pozisyon olarak görünüyordu.
MIN_POSITION_NOTIONAL = float(os.environ.get("ALSATBOTU_MIN_POSITION_NOTIONAL", "10"))

# -- Kategori yoğunlaşması: tolerans bandı -------------------------------
# İki eşik, tek bir eşiğin iki kusurunu birden çözüyor:
#   CATEGORY_EXPOSURE_LIMIT_PCT (%40) giriş limitidir -- yeni bir pozisyon
#   bir kategoriyi bu oranın üstüne çıkaramaz (boyutu kırpılır).
#   CATEGORY_TRIM_PCT (%45) sert kırpma sınırıdır -- fiyat hareketiyle bir
#   kategori bunun üstüne çıkarsa fazlası satılarak %40'a geri çekilir.
# Aradaki 5 puanlık band tolerans: giriş tam limitte yapıldıysa %1'lik bir
# fiyat hareketi kırpma tetiklemesin, aksi halde her gün birkaç kuruşluk
# satış yapıp komisyon yakardık.
CATEGORY_EXPOSURE_LIMIT_PCT = 0.40
CATEGORY_TRIM_PCT = 0.45
MAX_OPEN_POSITIONS = int(
    os.environ.get("ALSATBOTU_MAX_OPEN_POSITIONS", _VADE_PROFILI["max_open_positions"])
)
# -- Drawdown halt (histerezisli) ---------------------------------------
# Equity peak'inden MAX_DRAWDOWN_PCT kadar düşülünce yeni ALIM durur (mevcut
# pozisyonlar satılmaya devam eder). Halt anlık bir hesap değil, kalıcı bir
# durumdur: ancak aşağıdaki koşullardan biriyle kalkar.
#
#   1. Trend kapısı: piyasa proxy'si (izlenen sembollerin eşit ağırlıklı
#      endeksi) kendi TREND_SMA_WINDOW ortalamasının üstüne çıkarsa. Gerçek
#      veride (2007-2026) halt'ı bırakan mekanizma pratikte budur.
#   1b. Toparlanma (histerezis): drawdown DRAWDOWN_RELEASE_PCT'ye inerse.
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
# Zamanlı reset artık yalnızca emniyet ağı: trend hiç dönmezse ve hesap
# nakitteyse devreye girer. Sabit gün sayısı çöküş süresini bilemediği için
# (kısa/uzun/çift dipli senaryolarda ters yönlü davranıyordu) uzun tutuluyor.
HALT_RESET_AFTER_MARKS = int(os.environ.get("ALSATBOTU_HALT_RESET_AFTER_MARKS", "250"))
# Trend kapısı: eşit ağırlıklı piyasa endeksinin karşılaştırıldığı SMA penceresi.
TREND_SMA_WINDOW = int(os.environ.get("ALSATBOTU_TREND_SMA_WINDOW", "50"))
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

# Forex çiftleri: "forex" kategorisi altında toplanır, böylece risk motorunun
# CATEGORY_EXPOSURE_LIMIT_PCT'i bunları hisse senedi kategorilerinden bağımsız
# kendi başına bir grup olarak sınırlar. TwelveData bu sembolleri "EUR/USD"
# formatında destekliyor (alsatbotu/data/twelvedata.py zaten kaynak-agnostik).
# Şimdilik yalnızca paper trading -- gerçek bir forex broker/lot/pip/kaldıraç
# mantığı yok, mevcut cash-based pozisyon boyutlandırması (fiyat*miktar)
# hisse senedi sembolleriyle aynı şekilde uygulanıyor.
FOREX_SYMBOLS: dict[str, str] = {
    "EUR/USD": "forex",
    "GBP/USD": "forex",
    "USD/JPY": "forex",
    "USD/CHF": "forex",
    "AUD/USD": "forex",
    "USD/TRY": "forex",
}

SYMBOL_CATEGORIES.update(FOREX_SYMBOLS)

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


def asset_type_for(source: str, category: str | None = None) -> str:
    """"stock"/"crypto"/"forex" sınıflandırması.

    Kaynak "coingecko" ise sonuç tartışmasız "crypto" (bu kaynak yalnızca
    kripto için kullanılıyor). Aksi halde kaynak "twelvedata" hem hisse hem
    forex için kullanıldığından ikisini ayırt edemez -- kategori bilgisi
    (WATCHLIST entry'sindeki "category") burada devreye girer.
    """
    if source == "coingecko":
        return "crypto"
    return "forex" if category == "forex" else "stock"


# -- Evaluation / paper-trading loop ------------------------------------
# See evaluation/ package: SQLite signal+outcome log, a paper portfolio run
# alongside (not instead of) the JSON-based one above, a daily Telegram
# report, and a weekly self-improvement loop over strategy parameters.

EVAL_DB_PATH = Path(os.environ.get("ALSATBOTU_EVAL_DB_PATH", DATA_DIR / "evaluation.db"))

PAPER_STARTING_CAPITAL = float(os.environ.get("ALSATBOTU_PAPER_STARTING_CAPITAL", "10000"))
PAPER_RISK_PER_TRADE_PCT = 0.01  # 1% of current equity notional per trade
PAPER_COMMISSION_PCT = 0.0015    # 0.15% commission, charged on entry and exit
PAPER_SLIPPAGE_PCT = 0.0005      # 0.05% slippage, charged on entry and exit
# Stop çarpanı iki motorda da aynı olmalı. Eskiden burası sabit 1.5'ti,
# JSON portföyü ise vade profilinden gelen ATR_STOP_MULTIPLIER'ı (uzun: 3.0)
# kullanıyordu; aynı pozisyon SQLite motorunda stop'la kapanırken JSON
# tarafında açık kalıyordu ve iki günlük rapor birbiriyle çelişiyordu
# (ör. NVDA 10 Eylül). Artık tek kaynak ATR_STOP_MULTIPLIER.
PAPER_ATR_STOP_MULTIPLIER = float(
    os.environ.get("ALSATBOTU_PAPER_ATR_STOP_MULTIPLIER", ATR_STOP_MULTIPLIER)
)
# Hedef, stop'a göre ölçeklenir: eski 1.5/2.5 çifti 1:1.67 risk/ödül
# oranıydı, stop genişleyince hedef de aynı oranda genişlemezse pozisyonlar
# hedefe stop'tan çok daha erken çarpar.
PAPER_ATR_TARGET_MULTIPLIER = PAPER_ATR_STOP_MULTIPLIER * (2.5 / 1.5)
PAPER_MAX_TRADES_PER_DAY = 100

OUTCOME_HORIZONS_HOURS = {"price_1h": 1, "price_24h": 24, "price_7d": 24 * 7}
