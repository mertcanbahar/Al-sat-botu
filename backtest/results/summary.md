# Backtest: Kural Motoru vs. Al-ve-Tut

Üretim zamanı: 2026-09-07T08:17:19.573596Z

## Varsayımlar

- Başlangıç sermayesi: $100,000 (portföy genelinde), $5,000 (izole sembol başına)
- Komisyon: işlem tutarının %0.05'i, her taraf için (giriş ve çıkışta ayrı ayrı)
- Slipaj: kotalanan açılış fiyatına göre %0.05 aleyhte kayma, her taraf için
- Yürütme: sinyal T günü kapanışıyla hesaplanır, T+1 günü açılışında işleme girilir (look-ahead yok)
- Al-ve-tut karşılaştırması da aynı giriş komisyonu/slipajını öder (adil karşılaştırma)

## Survivorship bias uyarısı

20 sembolün tamamı bugün hâlâ işlem gören, onlarca yıldır listede olan büyük şirketler. Bu, herhangi bir tarihe ait gerçek endeks bileşen listesinin yeniden inşası değil. 5 yıllık pencerede bu hafif bir önyargıdır (bu isimlerden hiçbiri 2021-2026 arasında delisting/iflas riski taşımıyordu), ama sonuçlar "piyasanın tamamına uygulanan tarafsız bir tahmin" değil, "bugünün mavi çipleri üzerinde bu kural setinin nasıl performans gösterdiği" olarak okunmalı.

## Sonuç: Strateji al-ve-tut'u yeniyor mu?

**Portföy genelinde: HAYIR, yenmiyor.**
Strateji toplam getiri -9.43% (CAGR -1.39%, Sharpe -0.19) vs. eşit ağırlıklı al-ve-tut 475.83% (CAGR 28.15%, Sharpe 1.12).

## Portföy Genelinde (paylaşılan sermaye, risk motoru kısıtlarıyla)

Pencere: 2019-08-14 → 2026-09-04

| Metrik | Strateji | Al-ve-Tut |
|---|---|---|
| Toplam Getiri | -9.43% | 475.83% |
| CAGR | -1.39% | 28.15% |
| Maks. Drawdown | -26.53% | -32.02% |
| Sharpe | -0.19 | 1.12 |
| İşlem Sayısı | 38 | 1 |
| İsabet Oranı | 42.1% | — |
| Ort. Kazanç/Kayıp Oranı | 1.05 | — |
| Piyasada Kalma Oranı | 2.3% | 100.0% |
| Reddedilen Sinyal Sayısı (kısıtlar nedeniyle) | 6725 | — |

## Sembol Başına (izole hesap, portföy kısıtları paylaşılmıyor)

| Sembol | Kategori | Strat. Getiri | B&H Getiri | Strat. CAGR | B&H CAGR | Strat. DD | B&H DD | Strat. Sharpe | B&H Sharpe | İşlem | İsabet | Yener mi? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | tech | 79.39% | 531.26% | 8.63% | 29.83% | -9.25% | -33.43% | 1.15 | 1.00 | 42 | 54.8% | ❌ |
| AMZN | tech | 1.13% | 193.27% | 0.16% | 16.47% | -20.46% | -56.15% | 0.06 | 0.61 | 32 | 37.5% | ❌ |
| APD | materials | -8.22% | 35.35% | -1.21% | 4.38% | -17.25% | -33.78% | -0.15 | 0.29 | 36 | 41.7% | ❌ |
| BAC | financials | 12.46% | 137.24% | 1.68% | 13.02% | -17.32% | -49.27% | 0.27 | 0.54 | 34 | 50.0% | ❌ |
| CAT | industrials | -4.92% | 606.48% | -0.71% | 31.92% | -20.71% | -38.98% | -0.08 | 1.01 | 30 | 46.7% | ❌ |
| DIS | communication | -1.08% | -20.73% | -0.15% | -3.24% | -18.09% | -60.72% | 0.01 | 0.06 | 22 | 50.0% | ✅ |
| GOOGL | tech | 81.41% | 481.42% | 8.80% | 28.33% | -11.00% | -44.32% | 1.03 | 0.94 | 35 | 48.6% | ❌ |
| HON | industrials | -10.89% | 35.57% | -1.62% | 4.41% | -20.35% | -43.32% | -0.24 | 0.30 | 36 | 33.3% | ❌ |
| JNJ | healthcare | 10.15% | 111.29% | 1.38% | 11.18% | -12.68% | -27.83% | 0.30 | 0.64 | 36 | 47.2% | ❌ |
| JPM | financials | 28.89% | 242.21% | 3.66% | 19.04% | -13.97% | -43.99% | 0.53 | 0.73 | 34 | 52.9% | ❌ |
| KO | consumer | 1.15% | 66.20% | 0.16% | 7.46% | -10.68% | -37.54% | 0.06 | 0.46 | 37 | 54.1% | ❌ |
| META | tech | 79.36% | 243.20% | 8.63% | 19.09% | -10.50% | -76.74% | 0.99 | 0.63 | 27 | 63.0% | ❌ |
| MSFT | tech | 25.62% | 272.97% | 3.28% | 20.50% | -12.71% | -37.56% | 0.48 | 0.78 | 39 | 56.4% | ❌ |
| NEE | utilities | -15.34% | 55.25% | -2.33% | 6.43% | -22.05% | -47.17% | -0.41 | 0.36 | 20 | 40.0% | ❌ |
| NVDA | tech | 112.75% | 6040.07% | 11.29% | 79.20% | -12.11% | -66.36% | 1.07 | 1.40 | 44 | 61.4% | ❌ |
| PG | consumer | -12.87% | 26.47% | -1.93% | 3.38% | -20.59% | -24.63% | -0.40 | 0.27 | 37 | 40.5% | ❌ |
| PLD | real_estate | 13.57% | 71.12% | 1.82% | 7.91% | -11.58% | -48.12% | 0.30 | 0.41 | 31 | 51.6% | ❌ |
| UNH | healthcare | -13.24% | 63.30% | -1.99% | 7.20% | -23.64% | -61.97% | -0.25 | 0.38 | 37 | 56.8% | ❌ |
| WMT | consumer | 21.36% | 202.66% | 2.78% | 16.99% | -15.91% | -26.01% | 0.46 | 0.80 | 31 | 54.8% | ❌ |
| XOM | energy | 14.02% | 135.73% | 1.88% | 12.92% | -18.62% | -57.34% | 0.30 | 0.54 | 31 | 45.2% | ❌ |

Al-ve-tut'u yenen sembol sayısı: 1 / 20
