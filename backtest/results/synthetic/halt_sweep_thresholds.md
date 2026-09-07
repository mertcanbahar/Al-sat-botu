# Drawdown halt politikası: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T10:08:21.259438Z

> ⚠️ **SENTETİK VERİ, 4 tohum.** Gerçek piyasa verisi değil; ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

## İzole hesaplar (20 ayrı tek-sembol hesabı)

Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok.

| Metrik | H%20 / mandal | H%20 → R%10 / reset 60g×0.5 | H%25 / mandal | H%25 → R%10 / reset 60g×0.5 | H%30 / mandal | H%30 → R%10 / reset 60g×0.5 | H%35 / mandal | H%35 → R%10 / reset 60g×0.5 |
|---|---|---|---|---|---|---|---|---|
| Toplam getiri (20 hesap) | 6.12% (2.10%–11.59%) | 7.32% (3.76%–13.30%) | 6.47% (3.17%–13.45%) | 7.17% (3.31%–13.45%) | 7.15% (3.31%–13.46%) | 7.16% (3.31%–13.46%) | 7.21% (3.31%–13.46%) | 7.21% (3.31%–13.46%) |
| Ortalama maks. DD | -16.25% (-16.73%–-15.87%) | -16.76% (-17.55%–-16.11%) | -16.97% (-17.24%–-16.16%) | -17.06% (-17.51%–-16.16%) | -17.05% (-17.51%–-16.16%) | -17.05% (-17.51%–-16.16%) | -17.05% (-17.51%–-16.16%) | -17.05% (-17.51%–-16.16%) |
| En kötü hesap DD | -22.79% (-23.13%–-21.05%) | -26.80% (-30.29%–-25.31%) | -25.35% (-26.72%–-25.29%) | -27.80% (-30.77%–-25.29%) | -27.14% (-30.77%–-25.29%) | -27.14% (-30.77%–-25.29%) | -27.14% (-30.77%–-25.29%) | -27.14% (-30.77%–-25.29%) |
| Toplam işlem | 495.00 (458.00–505.00) | 522.50 (510.00–534.00) | 513.00 (510.00–533.00) | 527.00 (515.00–533.00) | 527.50 (514.00–534.00) | 527.50 (514.00–534.00) | 527.50 (515.00–534.00) | 527.50 (515.00–534.00) |
| **Sonda kilitli hesap** | 5.50 (3.00–8.00) | 0.00 (0.00–1.00) | 1.00 (1.00–3.00) | 0.00 (0.00–1.00) | 0.00 (0.00–1.00) | 0.00 | 0.00 | 0.00 |
| **Kalıcı durdurulan hesap** | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Halt tetiklenme sayısı | 5.50 (3.00–8.00) | 5.50 (3.00–9.00) | 1.00 (1.00–3.00) | 1.00 (1.00–3.00) | 0.00 (0.00–1.00) | 0.00 (0.00–1.00) | 0.00 | 0.00 |
| Toparlanmayla çıkış | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| Kısmi reset ile çıkış | 0.00 | 5.00 (3.00–9.00) | 0.00 | 1.00 (0.00–3.00) | 0.00 | 0.00 (0.00–1.00) | 0.00 | 0.00 |
| Engellenen ALIM sinyali | 387.50 (266.00–733.00) | 36.00 (16.00–58.00) | 45.50 (1.00–256.00) | 0.50 (0.00–29.00) | 0.00 (0.00–11.00) | 0.00 (0.00–2.00) | 0.00 | 0.00 |
| Ortalama halt gün oranı | 6.84% (5.24%–13.54%) | 1.37% (0.75%–2.25%) | 0.99% (0.10%–4.45%) | 0.25% (0.10%–0.75%) | 0.00% (0.00%–0.32%) | 0.00% (0.00%–0.25%) | 0.00% | 0.00% |

## Nasıl okunmalı

- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.
- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.
- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler birbirine fazla yakın, halt çırpınıyor.
