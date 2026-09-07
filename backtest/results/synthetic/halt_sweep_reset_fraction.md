# Drawdown halt politikası: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T10:00:31.303386Z

> ⚠️ **SENTETİK VERİ, 4 tohum.** Gerçek piyasa verisi değil; ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

## İzole hesaplar (20 ayrı tek-sembol hesabı)

Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok.

| Metrik | H%20 → R%10 / reset 60g×0.25 | H%20 → R%10 / reset 60g×0.5 | H%20 → R%10 / reset 60g×0.75 |
|---|---|---|---|
| Toplam getiri (20 hesap) | 7.32% (3.76%–13.30%) | 7.32% (3.76%–13.30%) | 7.03% (3.76%–13.29%) |
| Ortalama maks. DD | -16.76% (-17.55%–-16.11%) | -16.76% (-17.55%–-16.11%) | -16.80% (-17.48%–-16.11%) |
| En kötü hesap DD | -26.80% (-30.29%–-25.31%) | -26.80% (-30.29%–-25.31%) | -27.58% (-29.32%–-25.31%) |
| Toplam işlem | 522.50 (510.00–534.00) | 522.50 (510.00–534.00) | 522.00 (507.00–533.00) |
| **Sonda kilitli hesap** | 0.00 (0.00–1.00) | 0.00 (0.00–1.00) | 1.00 (0.00–3.00) |
| **Kalıcı durdurulan hesap** | 0.00 | 0.00 | 0.50 (0.00–1.00) |
| Halt tetiklenme sayısı | 5.50 (3.00–8.00) | 5.50 (3.00–9.00) | 8.00 (4.00–11.00) |
| Toparlanmayla çıkış | 0.00 | 0.00 | 0.00 |
| Kısmi reset ile çıkış | 5.00 (3.00–8.00) | 5.00 (3.00–9.00) | 6.50 (3.00–10.00) |
| Engellenen ALIM sinyali | 36.00 (16.00–58.00) | 36.00 (16.00–58.00) | 48.00 (17.00–102.00) |
| Ortalama halt gün oranı | 1.37% (0.75%–2.00%) | 1.37% (0.75%–2.25%) | 1.96% (0.87%–3.40%) |

## Nasıl okunmalı

- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.
- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.
- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler birbirine fazla yakın, halt çırpınıyor.
