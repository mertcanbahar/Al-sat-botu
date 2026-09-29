# Kırılma (Breakout) Mimarisi — Backtest Karşılaştırması

> ⚠️ **SENTETİK VERİ.** Bu dosya kodun uçtan uca çalıştığını gösteren bir duman testidir; rastgele yürüyüş fiyatları gerçek piyasa değildir. Sonuçlardan strateji hakkında hüküm çıkarılmaz.

Üretim zamanı: 2026-09-29T02:52:29.185982Z  
Pencere: 2021-03-29 → 2030-08-30  
Semboller (26): AAPL, MSFT, GOOGL, AMZN, NVDA, META, JPM, XOM, WMT, KO, EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/TRY, JNJ, UNH, CAT, HON, NEE, APD, DIS, PLD, BAC, PG

Canlı sisteme bağlı değil: production kodu değişmedi, yalnızca `backtest/breakout_backtest.py` içinde simüle edildi.

## Kurallar

- **Aday:** EMA20 > EMA50 ve RSI14 ∈ [50, 70]
- **Kırılma seviyesi:** önceki 20 tamamlanmış barın en yüksek high'ı (bugünkü bar hariç)
- **Teyit:** Close > seviye + marj; marj 0.1×ATR (hacim varsa) / 0.3×ATR (hacim yoksa); hacim varsa Volume > 1.2× önceki 20 günün ortalaması
- **Aday ömrü:** 7 işlem günü; filtre bozulursa süreden bağımsız düşer. Kırılma barında filtre aranmaz (kırılma kontrolü o günün filtre kontrolünden önce yapılır). Süresi dolan aday, filtre bir kez bozulup yeniden kurulmadan tekrar aday olamaz.
- **Giriş:** kırılma T kapanışında teyit, T+1 açılışında alım
- **Pozisyon:** Stop = Entry − 1.5×ATR; 1R = Entry − Stop; TP1 = +1.5R; TP2 = +3.0R. Boyut: production `evaluate_buy` (%2 risk, %15 tahsis tavanı, kategori %40, max açık pozisyon, halt)
- **B:** TP1'de %50 satış, stop → Entry + 0.2×ATR; kalan için iz süren stop = en yüksek kapanış − 2.0×ATR; TP2'de kalanın tamamı
- **A:** %100 pozisyon, TP yok; stop = max(initial, en yüksek kapanış − 2.0×ATR)
- **C:** mevcut sistem (`alsatbotu.signal.evaluate` + `engine.risk.evaluate_buy`), `portfolio_backtest.simulate` ile birebir
- **Maliyet:** komisyon %0.05, slipaj %0.05 (her taraf); stop ve açılış (gap) dolumları slipajlı, gün içi TP limit fiyattan

## Aynı barda hem stop hem TP tetiklenirse

Günlük OHLC barından gün içi sıra bilinemez; kural **kötümser**:

1. Açılış sırası bilinen tek fiyattır: açılış stop'un altındaysa tüm pozisyon açılıştan, hedefin üstündeyse hedef açılıştan dolar.
2. Açılıştan sonra aynı bar hem `low ≤ stop` hem `high ≥ TP` ise **önce stop tetiklenmiş sayılır**; pozisyonun tamamı stop'tan kapanır, TP gerçekleşmemiş sayılır.
3. TP1 gün içinde dolarsa yeni stop (Entry + 0.2×ATR) ve iz süren stop **ertesi bardan** itibaren geçerlidir (low'un TP1'den önce mi sonra mı oluştuğu bilinemez).
4. TP1 ile aynı barda `high ≥ TP2` ise kalan TP2'den satılır (TP2'ye ancak TP1 geçildikten sonra ulaşılabilir).
5. İz süren stop yalnızca kapanışta güncellenir, ertesi bardan geçerlidir.

Portföy koşusunda belirsiz (stop+TP aynı bar) bar sayısı: A = 0, B = 0.

## Karşılaştırma (portföy geneli, aynı veri ve pencere)

| Metrik | A: %100, TP yok, iz süren stop | B: %50 TP1 + %50 iz süren stop | C: mevcut sistem (referans) | Al-ve-tut (bağlam) |
|---|---|---|---|---|
| CAGR | -4.52% | -1.29% | 2.07% | 8.25% |
| Toplam getiri | -35.34% | -11.51% | 21.32% | 111.04% |
| Maks. drawdown | -37.83% | -19.25% | -20.15% | -10.79% |
| Sharpe | -0.78 | -0.24 | 0.26 | 1.26 |
| Profit factor | 0.69 | 0.92 | 1.08 | — |
| Expectancy ($/işlem) | $-74 | $-24 | $48 | — |
| Expectancy (%/işlem) | -0.59% | -0.15% | 0.50% | — |
| Expectancy (R) | -0.21 | -0.05 | N/A | — |
| Ort. kazanan / ort. kaybeden | 1.47 | 1.28 | 1.84 | — |
| İşlem sayısı (kapanan) | 480 | 483 | 321 | — |
| Ort. tutma süresi (işlem günü) | 7.4 | 7.1 | 37.3 | — |
| İsabet oranı | 32.5% | 42.0% | 38.0% | — |
| Dönem sonunda açık pozisyon | 0 | 0 | 5 | — |
| Reddedilen sinyal (risk motoru) | 19 | 8 | 9735 | — |

Expectancy (R) C kolu için tanımsız: mevcut sistem sabit bir 1R ile çalışmıyor. Ort. kazanan/kaybeden oranı işlem başı yüzde getiriler üzerinden (mevcut raporla aynı tanım).

## İstenen üç oran

**Sinyal çalışması** (her sembol kendi hesabında, halt kapalı — her kırılma işleme dönüşür, portföy kısıtları huniyi bozmaz) ve **portföy koşusu** (kısıtlar bağlıyken) ayrı ayrı:

| Oran | A — sinyal çalışması | B — sinyal çalışması | A — portföy | B — portföy |
|---|---|---|---|---|
| 1. Aday → kırılma dönüşümü | 15.2% | 15.1% | 15.2% | 15.1% |
| 2. Kırılma → kârlı işlem (kapanan işlemler içinde) | 32.0% | 41.8% | 32.5% | 42.0% |
| 2b. Kârlı işlem / tüm kırılma sinyalleri | 31.9% | 41.7% | 31.2% | 41.3% |

| 3. En büyük 3 kazananın katkısı (portföy) | A | B | C |
|---|---|---|---|
| Top-3 net kâr | $6,476 | $3,612 | $27,332 |
| Toplam net kâr (kapanan işlemler) | $-35,340 | $-11,512 | $15,353 |
| Top-3 / toplam net kâr | N/A | N/A | 178.0% |
| Top-3 / brüt kâr (kazananların toplamı) | 8.1% | 2.9% | 13.0% |

Top-3 / toplam net kâr: toplam net kâr ≤ 0 ise tanımsız (N/A). %100'ün üstü, geri kalan işlemlerin toplamda zarar ettiği anlamına gelir.

### Huni ayrıntısı

| | A — sinyal | B — sinyal | A — portföy | B — portföy |
|---|---|---|---|---|
| Aday kaydı | 3282 | 3258 | 3292 | 3262 |
| Kırılma | 498 | 492 | 500 | 492 |
| Süresi doldu (7 gün) | 802 | 796 | 803 | 798 |
| Filtre bozuldu | 1974 | 1962 | 1981 | 1964 |
| Dönem sonunda açık aday | 8 | 8 | 8 | 8 |
| Gerçekleşen giriş | 497 | 491 | 480 | 483 |
| Risk motoru reddi | 0 | 0 | 19 | 8 |
| Ertesi gün bar yok | 0 | 0 | 0 | 0 |

### Çıkış nedenleri (portföy)

- **A:** stop_gap: 341, trail_stop: 83, initial_stop: 56
- **B:** stop_gap: 264, initial_stop: 92, tp2_gap: 59, trail_stop: 37, tp2: 31
- **B TP1'e ulaşma oranı:** 42.0%

## Lookahead doğrulaması

Veri 2025-12-15 tarihinde kesildi; kesik veriyle ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. **Sonuç: GEÇTİ ✅**

| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |
|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | 245 |
| B | ✅ | ✅ | ✅ | 240 |
| C | ✅ | ✅ | — | 156 |

Ayrıca birim testleri (`tests/test_breakout_backtest.py`): göstergelerin kesik seri üzerinde aynı değeri vermesi, kırılma seviyesinin bugünkü barı içermemesi, gelecekteki barların bozulmasının geçmiş kararları değiştirmemesi.

## Sınırlamalar

- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).
- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü; gerçek sonuç bundan iyi olabilir, kötü olamaz (bu varsayım altında).
- Kategori kırpması (`plan_category_trims`) üç kolda da simüle edilmiyor (mevcut `simulate` ile tutarlı).
- Dönem sonunda açık pozisyonlar işlem metriklerine girmez, equity eğrisine piyasa değeriyle girer.

