# Kırılma (Breakout) Mimarisi — Backtest Karşılaştırması

Üretim zamanı: 2026-09-29T03:02:01.199307Z  
Pencere: 2013-07-10 → 2026-09-29  
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
| CAGR | 1.24% | 2.56% | 5.48% | 29.87% |
| Toplam getiri | 17.66% | 39.71% | 102.55% | 3067.67% |
| Maks. drawdown | -14.02% | -7.25% | -19.16% | -42.95% |
| Sharpe | 0.24 | 0.54 | 0.59 | 1.10 |
| Profit factor | 1.14 | 1.26 | 1.34 | — |
| Expectancy ($/işlem) | $31 | $70 | $202 | — |
| Expectancy (%/işlem) | 0.20% | 0.40% | 1.17% | — |
| Expectancy (R) | 0.05 | 0.11 | N/A | — |
| Ort. kazanan / ort. kaybeden | 2.01 | 1.50 | 1.78 | — |
| İşlem sayısı (kapanan) | 574 | 571 | 500 | — |
| Ort. tutma süresi (işlem günü) | 12.7 | 12.4 | 34.8 | — |
| İsabet oranı | 36.1% | 45.5% | 45.4% | — |
| Dönem sonunda açık pozisyon | 0 | 1 | 4 | — |
| Reddedilen sinyal (risk motoru) | 53 | 42 | 15313 | — |

Expectancy (R) C kolu için tanımsız: mevcut sistem sabit bir 1R ile çalışmıyor. Ort. kazanan/kaybeden oranı işlem başı yüzde getiriler üzerinden (mevcut raporla aynı tanım).

## İstenen üç oran

**Sinyal çalışması** (her sembol kendi hesabında, halt kapalı — her kırılma işleme dönüşür, portföy kısıtları huniyi bozmaz) ve **portföy koşusu** (kısıtlar bağlıyken) ayrı ayrı:

| Oran | A — sinyal çalışması | B — sinyal çalışması | A — portföy | B — portföy |
|---|---|---|---|---|
| 1. Aday → kırılma dönüşümü | 13.2% | 13.0% | 13.4% | 13.2% |
| 2. Kırılma → kârlı işlem (kapanan işlemler içinde) | 36.3% | 46.3% | 36.1% | 45.5% |
| 2b. Kârlı işlem / tüm kırılma sinyalleri | 36.3% | 46.2% | 32.0% | 41.1% |

| 3. En büyük 3 kazananın katkısı (portföy) | A | B | C |
|---|---|---|---|
| Top-3 net kâr | $13,043 | $8,492 | $44,609 |
| Toplam net kâr (kapanan işlemler) | $17,665 | $40,183 | $101,143 |
| Top-3 / toplam net kâr | 73.8% | 21.1% | 44.1% |
| Top-3 / brüt kâr (kazananların toplamı) | 8.8% | 4.4% | 11.2% |

Top-3 / toplam net kâr: toplam net kâr ≤ 0 ise tanımsız (N/A). %100'ün üstü, geri kalan işlemlerin toplamda zarar ettiği anlamına gelir.

### Huni ayrıntısı

| | A — sinyal | B — sinyal | A — portföy | B — portföy |
|---|---|---|---|---|
| Aday kaydı | 5087 | 5052 | 4829 | 4782 |
| Kırılma | 673 | 658 | 646 | 632 |
| Süresi doldu (7 gün) | 1431 | 1410 | 1360 | 1333 |
| Filtre bozuldu | 2979 | 2981 | 2819 | 2814 |
| Dönem sonunda açık aday | 4 | 3 | 4 | 3 |
| Gerçekleşen giriş | 673 | 658 | 574 | 572 |
| Risk motoru reddi | 0 | 0 | 53 | 42 |
| Ertesi gün bar yok | 0 | 0 | 19 | 18 |

### Çıkış nedenleri (portföy)

- **A:** trail_stop: 319, initial_stop: 183, stop_gap: 72
- **B:** initial_stop: 274, trail_stop: 104, tp2: 88, stop_gap: 56, breakeven_stop: 26, tp2_gap: 23
- **B TP1'e ulaşma oranı:** 45.5%

## Lookahead doğrulaması

Veri 2020-06-03 tarihinde kesildi; kesik veriyle ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. **Sonuç: GEÇTİ ✅**

| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |
|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | 308 |
| B | ✅ | ✅ | ✅ | 311 |
| C | ✅ | ✅ | — | 257 |

Ayrıca birim testleri (`tests/test_breakout_backtest.py`): göstergelerin kesik seri üzerinde aynı değeri vermesi, kırılma seviyesinin bugünkü barı içermemesi, gelecekteki barların bozulmasının geçmiş kararları değiştirmemesi.

## Sınırlamalar

- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).
- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü; gerçek sonuç bundan iyi olabilir, kötü olamaz (bu varsayım altında).
- Kategori kırpması (`plan_category_trims`) üç kolda da simüle edilmiyor (mevcut `simulate` ile tutarlı).
- Dönem sonunda açık pozisyonlar işlem metriklerine girmez, equity eğrisine piyasa değeriyle girer.

