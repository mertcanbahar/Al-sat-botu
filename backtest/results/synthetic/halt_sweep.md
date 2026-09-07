# Drawdown halt eşiği: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T08:59:16.482778Z

> ⚠️ **SENTETİK VERİ.** Bu tablo gerçek piyasa verisiyle değil, `generate_synthetic_data()`'nın deterministik rastgele yürüyüşüyle üretildi (ağ/API anahtarı olmadan koşabilmek için). Eşiklerin göreli davranışı (hangisi kilitliyor, hangisi hiç tetiklenmiyor) okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

Pencere: 2021-03-29 → 2025-10-31

## 1) Portföy geneli (paylaşılan sermaye, tüm risk kısıtları aktif)

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| Toplam getiri | -14.23% | -21.06% | -24.60% | -30.57% |
| CAGR | -3.29% | -5.02% | -5.97% | -7.64% |
| Gerçekleşen maks. DD | -24.19% | -30.43% | -34.19% | -38.64% |
| Sharpe | -0.26 | -0.41 | -0.48 | -0.63 |
| İşlem sayısı | 142 | 146 | 156 | 163 |
| İsabet oranı | 41.5% | 41.1% | 39.7% | 40.5% |
| **Halt aktif gün** | 694 | 686 | 653 | 626 |
| **Halt aktif gün oranı** | 57.8% | 57.2% | 54.4% | 52.2% |
| En uzun kesintisiz halt (gün) | 694 | 686 | 644 | 624 |
| İlk halt tarihi | 2023-03-07 | 2023-03-17 | 2023-04-19 | 2023-06-08 |
| Halt'ın engellediği ALIM sinyali | 3395 | 3359 | 3267 | 3231 |
| **Pencere sonunda kilitli mi?** | 🔒 EVET | 🔒 EVET | 🔒 EVET | 🔒 EVET |

## 2) İzole hesaplar (20 ayrı tek-sembol hesabı)

Portföy kısıtları paylaşılmadığı için halt'ın kilitleme etkisi burada en net görünür: bir alt hesap halt'a girip zirvesine dönemezse bir daha hiç alım yapamaz.

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| Toplam getiri (20 hesap toplamı) | 3.89% | 4.94% | 4.94% | 4.94% |
| Toplam işlem sayısı | 509 | 537 | 537 | 537 |
| Halt'a hiç girmiş hesap | 6/20 | 1/20 | 0/20 | 0/20 |
| **Sonda kilitli kalan hesap** | 6/20 | 0/20 | 0/20 | 0/20 |
| Ortalama halt gün oranı | 7.3% | 0.0% | 0.0% | 0.0% |
| Halt'ın engellediği ALIM sinyali | 471 | 0 | 0 | 0 |

- %20 → kilitli kalan semboller: AAPL, AMZN, BAC, DIS, PLD, WMT
- %25 → kilitli kalan semboller: yok
- %30 → kilitli kalan semboller: yok
- %35 → kilitli kalan semboller: yok

## Nasıl okunmalı

- **Halt aktif gün oranı = 0** ise kural hiç tetiklenmemiştir: koruma sağlamaz, parametre sınanmamış demektir.
- **Sonda kilitli hesap sayısı yüksek** ise kural bir kez tetiklenip bir daha bırakmamış, yani stratejiyi kalıcı olarak durdurmuştur.
- Aranan orta nokta: halt'ın ölçülebilir biçimde tetiklendiği ama hesapların büyük kısmının pencere sonunda kilitli kalmadığı eşik.
