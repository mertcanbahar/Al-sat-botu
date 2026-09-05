
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
