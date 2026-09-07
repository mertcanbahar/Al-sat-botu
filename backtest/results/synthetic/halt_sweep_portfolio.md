# Drawdown halt politikası: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T09:49:40.358814Z

> ⚠️ **SENTETİK VERİ, 3 tohum.** Gerçek piyasa verisi değil; ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

## İzole hesaplar (20 ayrı tek-sembol hesabı)

Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok.

| Metrik | H%20 / mandal | H%20 → R%10 |
|---|---|---|
| Toplam getiri (20 hesap) | 5.00% (2.10%–11.59%) | 6.00% (3.76%–13.30%) |
| Ortalama maks. DD | -16.28% (-16.73%–-15.87%) | -16.57% (-17.55%–-16.11%) |
| En kötü hesap DD | -22.88% (-23.13%–-21.05%) | -26.07% (-30.29%–-25.31%) |
| Toplam işlem | 497.00 (458.00–505.00) | 518.00 (510.00–534.00) |
| **Sonda kilitli hesap** | 5.00 (3.00–8.00) | 0.00 |
| **Kalıcı durdurulan hesap** | 0.00 | 0.00 |
| Halt tetiklenme sayısı | 5.00 (3.00–8.00) | 5.00 (3.00–9.00) |
| Toparlanmayla çıkış | 0.00 | 0.00 |
| Kısmi reset ile çıkış | 0.00 | 5.00 (3.00–9.00) |
| Engellenen ALIM sinyali | 339.00 (266.00–733.00) | 22.00 (16.00–50.00) |
| Ortalama halt gün oranı | 5.55% (5.24%–13.54%) | 1.25% (0.75%–2.25%) |

## Portföy geneli (paylaşılan sermaye)

| Metrik | H%20 / mandal | H%20 → R%10 |
|---|---|---|
| Toplam getiri | -5.89% (-7.18%–94.39%) | -0.12% (-25.80%–94.39%) |
| CAGR | -1.31% (-1.61%–15.58%) | -0.03% (-6.29%–15.58%) |
| Maks. DD | -20.70% (-21.96%–-12.49%) | -20.70% (-38.15%–-12.49%) |
| Sharpe | -0.05 (-0.10–1.11) | 0.07 (-0.40–1.11) |
| İşlem sayısı | 296.00 (117.00–325.00) | 312.00 (233.00–325.00) |

| Metrik | H%20 / mandal | H%20 → R%10 |
|---|---|---|
| Halt gün oranı | 20.42% (0.00%–64.58%) | 8.33% (0.00%–27.58%) |
| Halt tetiklenme sayısı | 1.00 (0.00–1.00) | 1.00 (0.00–3.00) |
| Toparlanmayla çıkış | 0.00 | 0.00 |
| Kısmi reset ile çıkış | 0.00 | 1.00 (0.00–2.00) |
| Engellenen ALIM sinyali | 1239.00 (0.00–3816.00) | 438.00 (0.00–1439.00) |

## Nasıl okunmalı

- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.
- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.
- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler birbirine fazla yakın, halt çırpınıyor.
