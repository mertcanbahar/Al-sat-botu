# Backtest: Kural Motoru vs. Al-ve-Tut

Üretim zamanı: 2026-09-06T19:49:30.110746Z

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
Strateji toplam getiri 24.95% (CAGR 3.21%, Sharpe 0.33) vs. eşit ağırlıklı al-ve-tut 475.83% (CAGR 28.15%, Sharpe 1.12).

## Portföy Genelinde (paylaşılan sermaye, risk motoru kısıtlarıyla)

Pencere: 2019-08-14 → 2026-09-04

| Metrik | Strateji | Al-ve-Tut |
|---|---|---|
| Toplam Getiri | 24.95% | 475.83% |
| CAGR | 3.21% | 28.15% |
| Maks. Drawdown | -22.79% | -32.02% |
| Sharpe | 0.33 | 1.12 |
| İşlem Sayısı | 150 | 1 |
| İsabet Oranı | 45.3% | — |
| Ort. Kazanç/Kayıp Oranı | 1.79 | — |
| Piyasada Kalma Oranı | 11.6% | 100.0% |
| Reddedilen Sinyal Sayısı (kısıtlar nedeniyle) | 3884 | — |

## Sembol Başına (izole hesap, portföy kısıtları paylaşılmıyor)

| Sembol | Kategori | Strat. Getiri | B&H Getiri | Strat. CAGR | B&H CAGR | Strat. DD | B&H DD | Strat. Sharpe | B&H Sharpe | İşlem | İsabet | Yener mi? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | tech | 72.71% | 531.26% | 8.05% | 29.83% | -7.91% | -33.43% | 1.13 | 1.00 | 38 | 52.6% | ❌ |
| AMZN | tech | 12.21% | 193.27% | 1.65% | 16.47% | -16.17% | -56.15% | 0.24 | 0.61 | 27 | 37.0% | ❌ |
| APD | materials | -6.16% | 35.35% | -0.90% | 4.38% | -17.33% | -33.78% | -0.11 | 0.29 | 30 | 30.0% | ❌ |
| BAC | financials | 15.98% | 137.24% | 2.12% | 13.02% | -17.26% | -49.27% | 0.35 | 0.54 | 31 | 45.2% | ❌ |
| CAT | industrials | 40.91% | 606.48% | 4.98% | 31.92% | -17.87% | -38.98% | 0.65 | 1.01 | 31 | 45.2% | ❌ |
| DIS | communication | -4.33% | -20.73% | -0.63% | -3.24% | -18.08% | -60.72% | -0.08 | 0.06 | 16 | 37.5% | ✅ |
| GOOGL | tech | 73.27% | 481.42% | 8.10% | 28.33% | -11.00% | -44.32% | 1.00 | 0.94 | 32 | 50.0% | ❌ |
| HON | industrials | -5.51% | 35.57% | -0.80% | 4.41% | -17.27% | -43.32% | -0.12 | 0.30 | 31 | 35.5% | ❌ |
| JNJ | healthcare | 14.91% | 111.29% | 1.99% | 11.18% | -10.49% | -27.83% | 0.44 | 0.64 | 31 | 45.2% | ❌ |
| JPM | financials | 32.57% | 242.21% | 4.08% | 19.04% | -10.97% | -43.99% | 0.60 | 0.73 | 29 | 48.3% | ❌ |
| KO | consumer | -1.56% | 66.20% | -0.22% | 7.46% | -10.55% | -37.54% | -0.01 | 0.46 | 31 | 45.2% | ❌ |
| META | tech | 54.00% | 243.20% | 6.31% | 19.09% | -8.77% | -76.74% | 0.88 | 0.63 | 21 | 57.1% | ❌ |
| MSFT | tech | 22.13% | 272.97% | 2.87% | 20.50% | -14.09% | -37.56% | 0.44 | 0.78 | 32 | 46.9% | ❌ |
| NEE | utilities | -11.31% | 55.25% | -1.69% | 6.43% | -17.95% | -47.17% | -0.22 | 0.36 | 30 | 40.0% | ❌ |
| NVDA | tech | 89.35% | 6040.07% | 9.47% | 79.20% | -12.60% | -66.36% | 0.95 | 1.40 | 31 | 45.2% | ❌ |
| PG | consumer | -14.56% | 26.47% | -2.20% | 3.38% | -21.14% | -24.63% | -0.47 | 0.27 | 30 | 30.0% | ❌ |
| PLD | real_estate | 8.35% | 71.12% | 1.14% | 7.91% | -14.36% | -48.12% | 0.20 | 0.41 | 25 | 44.0% | ❌ |
| UNH | healthcare | -13.73% | 63.30% | -2.07% | 7.20% | -22.36% | -61.97% | -0.28 | 0.38 | 28 | 42.9% | ❌ |
| WMT | consumer | 27.01% | 202.66% | 3.45% | 16.99% | -13.86% | -26.01% | 0.58 | 0.80 | 27 | 55.6% | ❌ |
| XOM | energy | 20.09% | 135.73% | 2.63% | 12.92% | -15.03% | -57.34% | 0.41 | 0.54 | 27 | 44.4% | ❌ |

Al-ve-tut'u yenen sembol sayısı: 1 / 20
