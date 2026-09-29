# Kırılma (Breakout) Mimarisi — Backtest Karşılaştırması

> ⚠️ **SENTETİK VERİ.** Bu dosya kodun uçtan uca çalıştığını gösteren bir duman testidir; rastgele yürüyüş fiyatları gerçek piyasa değildir. Sonuçlardan strateji hakkında hüküm çıkarılmaz.

Üretim zamanı: 2026-09-29T05:10:38.194903Z  
Pencere: 2021-03-29 → 2030-08-30  
Semboller (26): AAPL, MSFT, GOOGL, AMZN, NVDA, META, JPM, XOM, WMT, KO, EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/TRY, JNJ, UNH, CAT, HON, NEE, APD, DIS, PLD, BAC, PG

Canlı sisteme bağlı değil: production kodu değişmedi, yalnızca `backtest/breakout_backtest.py` içinde simüle edildi.

## 1. C kolu ATR×3 stop uyguluyor mu?

**Backtest'teki C (`portfolio_backtest.simulate`) uygulamıyor.** `evaluate_buy` pozisyona Entry − 3×ATR stop'unu yazıyor ve boyutlandırmayı buna göre yapıyor, ama simülasyon bu stop'u hiç kontrol etmiyor; pozisyon yalnızca kural motorunun SELL sinyaliyle kapanıyor (SELL'in "ATR stop" bacağı `close < önceki close − 3×önceki ATR` — tek günlük çöküş filtresi, girişe bağlı stop değil).

**Canlı sistem uyguluyor:** `scripts/run_portfolio.py::_enforce_stop` her koşuda fiyat ≤ pozisyonun stop'u ise SELL sinyali beklemeden kapatıyor. Yani backtest'teki C canlıyı birebir temsil etmiyordu.

**C-stop** bu farkı kapatır: C ile aynı kod (bu modüldeki kopya; stop kapalıyken `simulate` ile birebir aynı sonucu verdiği her koşuda doğrulanır) + her kapanışta `close ≤ stop` ise ertesi açılışta satış. Stop, canlıdaki gibi kural motorundan önce gelir.

- **C çıkış nedenleri:** SELL sinyali: 321
- **C-stop çıkış nedenleri:** SELL sinyali: 241, stop_loss (ATR×3): 160

## 2. Komisyon / kayma varsayımı

Varsayım **var** ve tüm tablolardaki sonuçlar bu maliyetler düşülmüş (net) hâlidir: komisyon işlem tutarının %0.05'i, kayma %0.05, her ikisi de her tarafta (gidiş-dönüş ≈ %0.20). Açılış ve stop dolumları kayma öder; A/B'de gün içi TP limit fiyattan dolar. Maliyet varsayımı olduğu için 0.05R / 0.1R ile yeniden koşu yapılmadı; mevcut varsayımın R cinsinden karşılığı:

| | A | B | C | C-stop |
|---|---|---|---|---|
| Ort. işlem maliyeti (% giriş tutarı) | 0.200% | 0.194% | 0.201% | 0.201% |
| Ort. işlem maliyeti (R) | 0.070 | 0.068 | 0.035 | 0.035 |

R: A/B'de Entry − 1.5×ATR; C/C-stop'ta `evaluate_buy`'ın boyutlandırdığı Entry − 3×ATR.

## Karşılaştırma (portföy geneli, aynı veri ve pencere)

| Metrik | A: %100, TP yok, iz süren stop | B: %50 TP1 + %50 iz süren stop | C: mevcut sistem (backtest, stop yok) | C-stop: mevcut sistem + canlıdaki ATR×3 stop | Al-ve-tut (eşit ağırlık) |
|---|---|---|---|---|---|
| CAGR | -4.52% | -1.29% | 2.07% | 3.81% | 8.25% |
| Toplam getiri | -35.34% | -11.51% | 21.32% | 42.21% | 111.04% |
| Maks. drawdown | -37.83% | -19.25% | -20.15% | -14.65% | -10.79% |
| Sharpe | -0.78 | -0.24 | 0.26 | 0.42 | 1.26 |
| Ort. exposure (pozisyon / equity) | 22.1% | 18.1% | 74.5% | 76.1% | 100.0% |
| Piyasada gün oranı (≥1 pozisyon) | 77.7% | 75.7% | 100.0% | 100.0% | 100.0% |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | -20.45% | -7.12% | 2.78% | 5.01% | 8.25% |
| Profit factor | 0.69 | 0.92 | 1.08 | 1.16 | — |
| Expectancy ($/işlem) | $-74 | $-24 | $48 | $92 | — |
| Expectancy (%/işlem) | -0.59% | -0.15% | 0.50% | 0.57% | — |
| Expectancy (R) | -0.21 | -0.05 | 0.08 | 0.10 | — |
| Ort. kazanan / ort. kaybeden | 1.47 | 1.28 | 1.84 | 2.22 | — |
| İşlem sayısı (kapanan) | 480 | 483 | 321 | 401 | — |
| Ort. tutma süresi (işlem günü) | 7.4 | 7.1 | 37.3 | 30.1 | — |
| İsabet oranı | 32.5% | 42.0% | 38.0% | 34.4% | — |
| Dönem sonunda açık pozisyon | 0 | 0 | 5 | 5 | — |
| Reddedilen sinyal (risk motoru) | 19 | 8 | 9735 | 9566 | — |

## 3. Exposure

- **Ort. exposure:** her gün kapanışta açık pozisyonların piyasa değeri / equity; günlerin ortalaması. Al-ve-tut her zaman %100.
- **Piyasada gün oranı:** en az bir pozisyonun açık olduğu günlerin oranı.
- **Exposure'a göre düzeltilmiş CAGR** = CAGR / ort. exposure: sermayenin yalnızca yatırılan kısmının yıllık getirisi (kaldıraçla %100 exposure'a ölçeklemenin kabaca karşılığı; nakit getirisi ve kaldıraç maliyeti yok sayılır).

## 4. En büyük 3 kazananın toplam kâra katkısı

| | A | B | C | C-stop |
|---|---|---|---|---|
| Top-3 net kâr | $6,476 | $3,612 | $27,332 | $31,329 |
| Toplam net kâr (kapanan işlemler) | $-35,340 | $-11,512 | $15,353 | $37,077 |
| Top-3 / toplam net kâr | N/A | N/A | 178.0% | 84.5% |
| Top-3 / brüt kâr (kazananların toplamı) | 8.1% | 2.9% | 13.0% | 11.4% |

- **A:** AUD/USD 2026-08-05→2026-09-08 $2,375, MSFT 2022-01-06→2022-02-07 $2,149, PG 2024-08-28→2024-10-08 $1,952
- **B:** JNJ 2023-05-04→2023-05-16 $1,257, APD 2027-08-23→2027-08-30 $1,188, UNH 2029-04-17→2029-05-16 $1,168
- **C:** USD/CHF 2029-10-09→2030-05-31 $13,514, JPM 2029-05-16→2029-12-21 $7,298, NVDA 2022-05-20→2022-11-22 $6,521
- **C-stop:** USD/CHF 2029-10-09→2030-05-31 $14,868, JPM 2029-06-21→2029-12-21 $8,834, GOOGL 2029-03-05→2029-08-15 $7,627

Top-3 / toplam net kâr: toplam ≤ 0 ise tanımsız (N/A); %100'ün üstü geri kalan işlemlerin toplamda zarar ettiğini gösterir.

## 5. Alt dönemler

Tek sürekli koşunun dilimleri: her dönem kendi başlangıç equity'sine göre ölçülür, portföy durumu (açık pozisyonlar, halt) dönem sınırında sıfırlanmaz. İşlemler çıkış tarihine göre dönemlere atanır.

### 2013–2019 (bu pencerede veri yok)

| Metrik | A | B | C | C-stop | Al-ve-tut |
|---|---|---|---|---|---|
| CAGR | N/A | N/A | N/A | N/A | N/A |
| Toplam getiri | N/A | N/A | N/A | N/A | N/A |
| Maks. drawdown | N/A | N/A | N/A | N/A | N/A |
| Sharpe | N/A | N/A | N/A | N/A | N/A |
| Ort. exposure (pozisyon / equity) | N/A | N/A | N/A | N/A | N/A |
| Piyasada gün oranı (≥1 pozisyon) | N/A | N/A | N/A | N/A | N/A |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | N/A | N/A | N/A | N/A | N/A |
| Profit factor | N/A | N/A | N/A | N/A | — |
| Expectancy ($/işlem) | N/A | N/A | N/A | N/A | — |
| Expectancy (%/işlem) | N/A | N/A | N/A | N/A | — |
| Expectancy (R) | N/A | N/A | N/A | N/A | — |
| Ort. kazanan / ort. kaybeden | N/A | N/A | N/A | N/A | — |
| İşlem sayısı (kapanan) | 0 | 0 | 0 | 0 | — |
| Ort. tutma süresi (işlem günü) | N/A | N/A | N/A | N/A | — |
| İsabet oranı | N/A | N/A | N/A | N/A | — |

### 2020–2026 (2021-03-30 → 2030-08-30)

| Metrik | A | B | C | C-stop | Al-ve-tut |
|---|---|---|---|---|---|
| CAGR | -4.52% | -1.29% | 2.07% | 3.81% | 8.25% |
| Toplam getiri | -35.34% | -11.51% | 21.32% | 42.21% | 111.04% |
| Maks. drawdown | -37.83% | -19.25% | -20.15% | -14.65% | -10.79% |
| Sharpe | -0.78 | -0.24 | 0.26 | 0.42 | 1.26 |
| Ort. exposure (pozisyon / equity) | 22.1% | 18.1% | 74.5% | 76.1% | 100.0% |
| Piyasada gün oranı (≥1 pozisyon) | 77.7% | 75.7% | 100.0% | 100.0% | 100.0% |
| Exposure'a göre düzeltilmiş CAGR (CAGR / ort. exposure) | -20.45% | -7.12% | 2.78% | 5.01% | 8.25% |
| Profit factor | 0.69 | 0.92 | 1.08 | 1.16 | — |
| Expectancy ($/işlem) | $-74 | $-24 | $48 | $92 | — |
| Expectancy (%/işlem) | -0.59% | -0.15% | 0.50% | 0.57% | — |
| Expectancy (R) | -0.21 | -0.05 | 0.08 | 0.10 | — |
| Ort. kazanan / ort. kaybeden | 1.47 | 1.28 | 1.84 | 2.22 | — |
| İşlem sayısı (kapanan) | 480 | 483 | 321 | 401 | — |
| Ort. tutma süresi (işlem günü) | 7.4 | 7.1 | 37.3 | 30.1 | — |
| İsabet oranı | 32.5% | 42.0% | 38.0% | 34.4% | — |

## 6. Al-ve-tut (bağlam)

Eşit ağırlıklı, aynı evren, aynı pencere; giriş komisyonu ve kaymasını öder, yeniden dengeleme yok.

| | Tüm pencere | 2013–2019 | 2020–2026 |
|---|---|---|---|
| Sharpe | 1.26 | N/A | 1.26 |
| Maks. drawdown | -10.79% | N/A | -10.79% |
| CAGR | 8.25% | N/A | 8.25% |

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
| Aday → kırılma | 15.2% | 15.1% | 15.2% | 15.1% |
| Kırılma → kârlı işlem | 32.0% | 41.8% | 32.5% | 42.0% |
| Aday kaydı | 3282 | 3258 | 3292 | 3262 |
| Kırılma | 498 | 492 | 500 | 492 |
| Süresi doldu | 802 | 796 | 803 | 798 |
| Filtre bozuldu | 1974 | 1962 | 1981 | 1964 |
| Gerçekleşen giriş | 497 | 491 | 480 | 483 |
| Risk motoru reddi | 0 | 0 | 19 | 8 |
| Ertesi gün bar yok | 0 | 0 | 0 | 0 |

Sinyal çalışması: her sembol kendi hesabında, halt kapalı (portföy kısıtları huniyi bozmaz).

## Lookahead doğrulaması

Veri 2025-12-15 tarihinde kesildi; kesik ve tam veriyle yapılan koşular kesim tarihine kadar karşılaştırıldı. **Sonuç: GEÇTİ ✅**

| Kol | Equity eğrisi | Kapanan işlemler | Aday olayları | Karşılaştırılan işlem |
|---|---|---|---|---|
| A | ✅ | ✅ | ✅ | 245 |
| B | ✅ | ✅ | ✅ | 240 |
| C | ✅ | ✅ | — | 156 |
| C-stop | ✅ | ✅ | — | 193 |

C kopyası (`simulate_current`, stop kapalı) ile `portfolio_backtest.simulate` birebir aynı: ✅

## Sınırlamalar

- Survivorship bias: evren bugünün hâlâ işlem gören büyük şirketleri (bkz. `portfolio_backtest.py`).
- Günlük bar: gün içi sıra bilinmediği için stop/TP çakışmaları kötümser çözüldü.
- C-stop: canlı stop'u gün içi fiyatla kontrol eder; backtest günlük kapanışla kontrol edip ertesi açılışta satar (backtest'in genel yürütme kuralı). Gün içi delinip kapanışta geri dönen stoplar burada tetiklenmez.
- Kategori kırpması (`plan_category_trims`) hiçbir kolda simüle edilmiyor (mevcut `simulate` ile tutarlı).
- Dönem sonunda açık pozisyonlar işlem metriklerine girmez, equity eğrisine piyasa değeriyle girer.

