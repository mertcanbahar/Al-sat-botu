
## Backtest bulguları (2026-09-05)

- Twelve Data, BTC/USD için hacim vermiyor (`--diagnose`, 365 gün: 0/365 valid bar).
- CoinGecko, 30 günden uzun aralıklarda 4 günlük muma düşüyor (bitcoin, 365 gün istendi, 92 mum döndü).
- Hacim verisi sadece Twelve Data hisse sembollerinde geliyor (AAPL/MSFT/THYAO).

### 365 günlük backtest sonuçları (Twelve Data, `--diagnose`)

| Sembol | Sinyal oranı (AL koşulu) | İşlem sayısı | İsabet (win rate) | Getiri (total return) |
|---|---|---|---|---|
| AAPL | 35/316 (11.1%) | 7 | 57.14% | 38.68% |
| MSFT | 29/316 (9.2%) | 2 | 0.00% | -9.70% |
| THYAO | 54/316 (17.1%) | 6 | 33.33% | -13.55% |

### 10 ABD hissesi, 365 günlük backtest (Twelve Data, `--diagnose`)

| Sembol | Sinyal oranı (AL koşulu) | İşlem sayısı | İsabet (win rate) | Getiri (total return) | Al-ve-tut getirisi | Fark (strateji - al-ve-tut) |
|---|---|---|---|---|---|---|
| AAPL | 35/316 (11.1%) | 7 | 57.14% | 38.68% | 43.00% | -4.32% |
| MSFT | 29/316 (9.2%) | 2 | 0.00% | -9.70% | 26.46% | -36.16% |
| GOOGL | 40/316 (12.7%) | 6 | 66.67% | 67.62% | 98.44% | -30.82% |
| AMZN | 51/316 (16.1%) | 5 | 20.00% | -25.04% | 25.67% | -50.70% |
| NVDA | 82/316 (25.9%) | 7 | 42.86% | 6.53% | 90.87% | -84.34% |
| META | 25/316 (7.9%) | 4 | 50.00% | -19.20% | -1.52% | -17.68% |
| JPM | 67/316 (21.2%) | 5 | 60.00% | 21.69% | 42.81% | -21.12% |
| XOM | 71/316 (22.5%) | 6 | 50.00% | 26.18% | 36.78% | -10.60% |
| WMT | 66/316 (20.9%) | 4 | 50.00% | 29.55% | 26.40% | 3.15% |
| KO | 56/316 (17.7%) | 5 | 40.00% | 7.73% | 27.99% | -20.26% |
