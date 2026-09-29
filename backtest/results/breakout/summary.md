# Kırılma (Breakout) Mimarisi — Backtest Karşılaştırması

Üretim zamanı: 2026-09-29T05:25:33.726977Z  
Pencere: 2013-07-10 → 2026-09-29  
Semboller (26): AAPL, MSFT, GOOGL, AMZN, NVDA, META, JPM, XOM, WMT, KO, EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/TRY, JNJ, UNH, CAT, HON, NEE, APD, DIS, PLD, BAC, PG

Canlı sisteme bağlı değil: production kodu değişmedi, yalnızca `backtest/breakout_backtest.py` içinde simüle edildi.

## 1. C kolu ATR×3 stop uyguluyor mu?

**Backtest'teki C (`portfolio_backtest.simulate`) uygulamıyor.** `evaluate_buy` pozisyona Entry − 3×ATR stop'unu yazıyor ve boyutlandırmayı buna göre yapıyor, ama simülasyon bu stop'u hiç kontrol etmiyor; pozisyon yalnızca kural motorunun SELL sinyaliyle kapanıyor (SELL'in "ATR stop" bacağı `close < önceki close − 3×önceki ATR` — tek günlük çöküş filtresi, girişe bağlı stop değil).

**Canlı sistem uyguluyor:** `scripts/run_portfolio.py::_enforce_stop` her koşuda fiyat ≤ pozisyonun stop'u ise SELL sinyali beklemeden kapatıyor. Yani backtest'teki C canlıyı birebir temsil etmiyordu.

**C-stop** bu farkı kapatır: C ile aynı kod (bu modüldeki kopya; stop kapalıyken `simulate` ile birebir aynı sonucu verdiği her koşuda doğrulanır) + her kapanışta `close ≤ stop` ise ertesi açılışta satış. Stop, canlıdaki gibi kural motorundan önce gelir.

- **C çıkış nedenleri:** SELL sinyali: 500
- **C-stop çıkış nedenleri:** SELL sinyali: 414, stop_loss (ATR×3): 141

## 2. Komisyon / kayma varsayımı

Varsayım **var** ve tüm tablolardaki sonuçlar bu maliyetler düşülmüş (net) hâlidir: komisyon işlem tutarının %0.05'i, kayma %0.05, her ikisi de her tarafta (gidiş-dönüş ≈ %0.20). Açılış ve stop dolumları kayma öder; A/B'de gün içi TP limit fiyattan dolar. Maliyet varsayımı olduğu için 0.05R / 0.1R ile yeniden koşu yapılmadı; mevcut varsayımın R cinsinden karşılığı:

| | A | B | C | C-stop |
|---|---|---|---|---|
| Ort. işlem maliyeti (% giriş tutarı) | 0.200% | 0.186% | 0.201% | 0.201% |
| Ort. işlem maliyeti (R) | 0.094 | 0.088 | 0.054 | 0.053 |

R: A/B'de Entry − 1.5×ATR; C/C-stop'ta `evaluate_buy`'ın boyutlandırdığı Entry − 3×ATR.

## Karşılaştırma (portföy geneli, aynı veri ve pencere)

| Metrik | A: %100, TP yok, iz süren stop | B: %50 TP1 + %50 iz süren stop | C: mevcut sistem (backtest, stop yok) | C-stop: mevcut sistem + canlıdaki ATR×3 stop | Al-ve-tut (eşit ağırlık) |
|---|---|---|---|---|---|
| CAGR | 1.24% | 2.56% | 5.48% | 4.09% | 29.87% |
| Toplam getiri | 17.66% | 39.71% | 102.55% | 69.89% | 3067.67% |
| Maks. drawdown | -14.02% | -7.25% | -19.16% | -24.26% | -42.95% |
| Sharpe | 0.24 | 0.54 | 0.59 | 0.45 | 1.10 |
| Ort. exposure (pozisyon / equity) | 30.6% | 25.3% | 72.5% | 72.8% | 100.0% |
| Piyasada gün oranı (≥1 pozisyon) | 79.5% | 79.3% | 99.9% | 99.9% | 100.0% |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | 4.05% | 10.12% | 7.56% | 5.62% | 29.87% |
| Profit factor | 1.14 | 1.26 | 1.34 | 1.24 | — |
| Expectancy ($/işlem) | $31 | $70 | $202 | $120 | — |
| Expectancy (%/işlem) | 0.20% | 0.40% | 1.17% | 0.83% | — |
| Expectancy (R) | 0.05 | 0.11 | 0.16 | 0.09 | — |
| Ort. kazanan / ort. kaybeden | 2.01 | 1.50 | 1.78 | 1.78 | — |
| İşlem sayısı (kapanan) | 574 | 571 | 500 | 555 | — |
| Ort. tutma süresi (işlem günü) | 12.7 | 12.4 | 34.8 | 31.2 | — |
| İsabet oranı | 36.1% | 45.5% | 45.4% | 42.9% | — |
| Dönem sonunda açık pozisyon | 0 | 1 | 4 | 4 | — |
| Reddedilen sinyal (risk motoru) | 53 | 42 | 15313 | 15322 | — |

## 3. Exposure

- **Ort. exposure:** her gün kapanışta açık pozisyonların piyasa değeri / equity; günlerin ortalaması. Al-ve-tut her zaman %100.
- **Piyasada gün oranı:** en az bir pozisyonun açık olduğu günlerin oranı.
- **Exposure'a göre düzeltilmiş CAGR** = CAGR / ort. exposure: sermayenin yalnızca yatırılan kısmının yıllık getirisi (kaldıraçla %100 exposure'a ölçeklemenin kabaca karşılığı; nakit getirisi ve kaldıraç maliyeti yok sayılır). Exposure çok düşükken bu oran küçük getiri farklarını büyütür; tek başına değil, ham CAGR ve drawdown ile birlikte okunmalı.

## 4. En büyük 3 kazananın toplam kâra katkısı

| | A | B | C | C-stop |
|---|---|---|---|---|
| Top-3 net kâr | $13,043 | $8,492 | $44,609 | $25,964 |
| Toplam net kâr (kapanan işlemler) | $17,665 | $40,183 | $101,143 | $66,340 |
| Top-3 / toplam net kâr | 73.8% | 21.1% | 44.1% | 39.1% |
| Top-3 / brüt kâr (kazananların toplamı) | 8.8% | 4.4% | 11.2% | 7.7% |

- **A:** NVDA 2024-01-09→2024-02-20 $4,770, USD/TRY 2018-07-12→2018-08-14 $4,534, META 2024-01-22→2024-03-11 $3,738
- **B:** META 2024-01-22→2024-02-02 $3,202, HON 2020-11-04→2020-11-09 $2,661, NVDA 2023-01-18→2023-02-01 $2,628
- **C:** NVDA 2023-01-27→2023-05-26 $24,711, NVDA 2020-04-08→2020-08-18 $11,049, NVDA 2019-08-22→2019-12-20 $8,850
- **C-stop:** NVDA 2020-04-08→2020-08-18 $9,407, CAT 2026-03-09→2026-05-01 $8,812, NVDA 2016-09-12→2016-11-14 $7,745

Top-3 / toplam net kâr: toplam ≤ 0 ise tanımsız (N/A); %100'ün üstü geri kalan işlemlerin toplamda zarar ettiğini gösterir.

## 5. Alt dönemler

Tek sürekli koşunun dilimleri: her dönem kendi başlangıç equity'sine göre ölçülür, portföy durumu (açık pozisyonlar, halt) dönem sınırında sıfırlanmaz. İşlemler çıkış tarihine göre dönemlere atanır.

### 2013–2019 (2013-07-11 → 2019-12-31)

| Metrik | A | B | C | C-stop | Al-ve-tut |
|---|---|---|---|---|---|
| CAGR | -0.53% | 0.91% | 8.73% | 5.69% | 19.30% |
| Toplam getiri | -3.36% | 6.07% | 71.92% | 43.10% | 213.55% |
| Maks. drawdown | -14.02% | -7.25% | -9.57% | -13.24% | -28.17% |
| Sharpe | -0.09 | 0.24 | 1.00 | 0.67 | 1.28 |
| Ort. exposure (pozisyon / equity) | 31.0% | 27.7% | 73.9% | 74.1% | 100.0% |
| Piyasada gün oranı (≥1 pozisyon) | 79.9% | 82.7% | 99.9% | 99.9% | 100.0% |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | -1.69% | 3.30% | 11.81% | 7.68% | 19.30% |
| Profit factor | 0.90 | 1.09 | 1.81 | 1.38 | — |
| Expectancy ($/işlem) | $-20 | $20 | $287 | $142 | — |
| Expectancy (%/işlem) | -0.14% | 0.15% | 1.59% | 0.93% | — |
| Expectancy (R) | -0.03 | 0.06 | 0.28 | 0.15 | — |
| Ort. kazanan / ort. kaybeden | 1.76 | 1.41 | 1.96 | 1.82 | — |
| İşlem sayısı (kapanan) | 292 | 294 | 227 | 241 | — |
| Ort. tutma süresi (işlem günü) | 11.6 | 11.9 | 35.1 | 32.6 | — |
| İsabet oranı | 33.9% | 43.9% | 48.0% | 44.0% | — |

### 2020–2026 (2020-01-01 → 2026-09-29)

| Metrik | A | B | C | C-stop | Al-ve-tut |
|---|---|---|---|---|---|
| CAGR | 2.96% | 4.17% | 2.46% | 2.58% | 40.89% |
| Toplam getiri | 21.75% | 31.72% | 17.82% | 18.72% | 910.26% |
| Maks. drawdown | -9.36% | -6.14% | -19.16% | -24.26% | -42.95% |
| Sharpe | 0.45 | 0.77 | 0.27 | 0.28 | 1.13 |
| Ort. exposure (pozisyon / equity) | 30.2% | 23.2% | 71.3% | 71.6% | 100.0% |
| Piyasada gün oranı (≥1 pozisyon) | 79.1% | 76.3% | 99.9% | 99.8% | 100.0% |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | 9.80% | 18.00% | 3.45% | 3.60% | 40.89% |
| Profit factor | 1.34 | 1.40 | 1.17 | 1.18 | — |
| Expectancy ($/işlem) | $83 | $123 | $132 | $102 | — |
| Expectancy (%/işlem) | 0.55% | 0.66% | 0.83% | 0.75% | — |
| Expectancy (R) | 0.13 | 0.17 | 0.06 | 0.05 | — |
| Ort. kazanan / ort. kaybeden | 2.16 | 1.54 | 1.69 | 1.77 | — |
| İşlem sayısı (kapanan) | 282 | 277 | 273 | 314 | — |
| Ort. tutma süresi (işlem günü) | 13.9 | 12.9 | 34.5 | 30.1 | — |
| İsabet oranı | 38.3% | 47.3% | 43.2% | 42.0% | — |

## 6. Al-ve-tut (bağlam)

Eşit ağırlıklı, aynı evren, aynı pencere; giriş komisyonu ve kaymasını öder, yeniden dengeleme yok.

| | Tüm pencere | 2013–2019 | 2020–2026 |
|---|---|---|---|
| Sharpe | 1.10 | 1.28 | 1.13 |
| Maks. drawdown | -42.95% | -28.17% | -42.95% |
| CAGR | 29.87% | 19.30% | 40.89% |

## Kurallar (A/B)

- **Aday:** EMA20 > EMA50 ve RSI14 ∈ [50, 70]
- **Kırılma seviyesi:** önceki 20 tamamlanmış barın en yüksek high'ı (bugünkü bar hariç)
- **Teyit:** Close > seviye + marj; marj 0.1×ATR (hacim varsa) / 0.3×ATR (hacim yoksa); hacim varsa Volume > 1.2× önceki 20 günün ortalaması
- **Aday ömrü:** 7 işlem günü; filtre bozulursa süreden bağımsız düşer. Kırılma barında filtre aranmaz. Süresi dolan aday, filtre bir kez bozulup yeniden kurulmadan tekrar aday olamaz.
- **Giriş:** kırılma T kapanışında teyit, T+1 açılışında alım
- **Pozisyon:** Stop = Entry − 1.5×ATR; TP1 = +1.5R; TP2 = +3.0R. Boyut: production `evaluate_buy` (%2 risk, %15 tahsis tavanı, kategori %40, max açık pozisyon, halt)
- **B:** TP1'de %50 satış, stop → Entry + 0.2×ATR; kalan için iz süren stop = en yüksek kapanış − 2.0×ATR; TP2'de kalanın tamamı
- **A:** %100 pozisyon, TP yok; stop = max(initial, en yüksek kapanış − 2.0×ATR)

### Aynı barda hem stop hem TP

Kötümser: açılış önce işlenir (gap); açılıştan sonra aynı barda `low ≤ stop` ve `high ≥ TP` ise önce stop tetiklenmiş sayılır ve pozisyonun tamamı stop'tan kapanır. TP1 gün içinde dolarsa yeni stop ertesi bardan geçerlidir; TP1 ile aynı barda `high ≥ TP2` ise kalan TP2'den satılır. İz süren stop yalnızca kapanışta güncellenir.
Belirsiz bar sayısı: A = 0, B = 0.

## Huni (A/B)

| | A — sinyal | B — sinyal | A — portföy | B — portföy |
|---|---|---|---|---|
| Aday → kırılma | 13.2% | 13.0% | 13.4% | 13.2% |
| Kırılma → kârlı işlem | 36.3% | 46.3% | 36.1% | 45.5% |
| Aday kaydı | 5087 | 5052 | 4829 | 4782 |
| Kırılma | 673 | 658 | 646 | 632 |
| Süresi doldu | 1431 | 1410 | 1360 | 1333 |
| Filtre bozuldu | 2979 | 2981 | 2819 | 2814 |
| Gerçekleşen giriş | 673 | 658 | 574 | 572 |
| Risk motoru reddi | 0 | 0 | 53 | 42 |
| Ertesi gün bar yok | 0 | 0 | 19 | 18 |

Sinyal çalışması: her sembol kendi hesabında, halt kapalı (portföy kısıtları huniyi bozmaz).

## Lookahead doğrulaması

Veri 2020-06-03 tarihinde kesildi; kesik ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. **Sonuç: GEÇTİ ✅**

| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |
|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | 308 |
| B | ✅ | ✅ | ✅ | 311 |
| C | ✅ | ✅ | — | 257 |
| C-stop | ✅ | ✅ | — | 276 |

C kopyası (`simulate_current`, stop kapalı) ile `portfolio_backtest.simulate` birebir aynı: ✅

## Sınırlamalar

- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).
- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü.
- C-stop: canlı stop'u gün içi fiyatla kontrol eder; backtest günlük kapanışla kontrol edip ertesi açılışta satar (backtest'in genel yürütme kuralı). Gün içi delinip kapanışta geri dönen stoplar burada tetiklenmez.
- Kategori kırpması (`plan_category_trims`) hiçbir kolda simüle edilmiyor (mevcut `simulate` ile tutarlı).
- Dönem sonunda açık pozisyonlar işlem metriklerine girmez, equity eğrisine piyasa değeriyle girer.

