# Drawdown halt politikası: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T09:55:39.843229Z

> ⚠️ **SENTETİK VERİ, 8 tohum.** Gerçek piyasa verisi değil; ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

## İzole hesaplar (20 ayrı tek-sembol hesabı)

Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok.

| Metrik | H%20 / mandal | H%20 → R%5 | H%20 → R%10 | H%20 → R%15 |
|---|---|---|---|---|
| Toplam getiri (20 hesap) | 4.42% (0.56%–11.59%) | 4.83% (0.42%–13.30%) | 4.83% (0.42%–13.30%) | 4.78% (0.42%–13.30%) |
| Ortalama maks. DD | -16.50% (-17.35%–-15.87%) | -17.33% (-18.66%–-16.11%) | -17.33% (-18.66%–-16.11%) | -17.38% (-18.66%–-16.11%) |
| En kötü hesap DD | -22.79% (-23.23%–-21.05%) | -28.37% (-30.29%–-25.31%) | -28.37% (-30.29%–-25.31%) | -28.37% (-31.39%–-25.31%) |
| Toplam işlem | 495.00 (444.00–541.00) | 530.00 (478.00–559.00) | 530.00 (478.00–559.00) | 530.00 (478.00–559.00) |
| **Sonda kilitli hesap** | 6.00 (3.00–10.00) | 0.00 (0.00–1.00) | 0.00 (0.00–1.00) | 0.50 (0.00–1.00) |
| **Kalıcı durdurulan hesap** | 0.00 | 0.00 | 0.00 | 0.00 |
| Halt tetiklenme sayısı | 6.00 (3.00–10.00) | 6.50 (3.00–10.00) | 6.50 (3.00–10.00) | 7.00 (3.00–10.00) |
| Toparlanmayla çıkış | 0.00 | 0.00 | 0.00 | 0.00 (0.00–1.00) |
| Kısmi reset ile çıkış | 0.00 | 6.00 (3.00–9.00) | 6.00 (3.00–9.00) | 5.00 (3.00–9.00) |
| Engellenen ALIM sinyali | 453.50 (203.00–1058.00) | 54.00 (16.00–111.00) | 54.00 (16.00–111.00) | 44.00 (16.00–111.00) |
| Ortalama halt gün oranı | 8.72% (5.24%–17.01%) | 1.55% (0.75%–2.30%) | 1.55% (0.75%–2.30%) | 1.52% (0.75%–2.30%) |

## Nasıl okunmalı

- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.
- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.
- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler birbirine fazla yakın, halt çırpınıyor.
