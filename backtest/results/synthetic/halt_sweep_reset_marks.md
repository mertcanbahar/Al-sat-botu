# Drawdown halt politikası: yan yana karşılaştırma

Üretim zamanı: 2026-09-07T09:53:53.871727Z

> ⚠️ **SENTETİK VERİ, 3 tohum.** Gerçek piyasa verisi değil; ağ/API anahtarı olmadan koşabilmek için `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü kullanıldı. Hücrelerde medyan, parantezde tohumlar arası aralık var. Eşiklerin göreli davranışı okunabilir; getiri rakamları gerçek performans tahmini DEĞİLDİR.

## İzole hesaplar (20 ayrı tek-sembol hesabı)

Kilitlenme burada en net görünür: portföy kısıtları paylaşılmadığı için halt'a giren bir alt hesabı kurtaracak başka bir mekanizma yok.

| Metrik | H%20 → R%10 / reset 20g | H%20 → R%10 / reset 40g | H%20 → R%10 / reset 60g |
|---|---|---|---|
| Toplam getiri (20 hesap) | 6.24% (3.37%–13.46%) | 5.90% (3.68%–13.46%) | 6.00% (3.76%–13.30%) |
| Ortalama maks. DD | -16.78% (-17.29%–-16.16%) | -16.55% (-17.57%–-16.14%) | -16.57% (-17.55%–-16.11%) |
| En kötü hesap DD | -25.39% (-30.77%–-25.29%) | -25.39% (-30.77%–-25.29%) | -26.07% (-30.29%–-25.31%) |
| Toplam işlem | 520.00 (513.00–534.00) | 518.00 (512.00–534.00) | 518.00 (510.00–534.00) |
| **Sonda kilitli hesap** | 0.00 | 0.00 | 0.00 |
| **Kalıcı durdurulan hesap** | 0.00 | 0.00 | 0.00 |
| Halt tetiklenme sayısı | 5.00 (3.00–9.00) | 5.00 (3.00–9.00) | 5.00 (3.00–9.00) |
| Toparlanmayla çıkış | 0.00 | 0.00 | 0.00 |
| Kısmi reset ile çıkış | 5.00 (3.00–9.00) | 5.00 (3.00–9.00) | 5.00 (3.00–9.00) |
| Engellenen ALIM sinyali | 1.00 (0.00–5.00) | 12.00 (8.00–24.00) | 22.00 (16.00–50.00) |
| Ortalama halt gün oranı | 0.42% (0.25%–0.76%) | 0.83% (0.50%–1.50%) | 1.25% (0.75%–2.25%) |

## Nasıl okunmalı

- **Sonda kilitli hesap > 0** → kural tetiklenip bir daha bırakmamış.
- **Halt tetiklenme sayısı = 0** → kural hiç çalışmamış, koruma yok.
- **Tetiklenme sayısı çok yüksek** (yılda birkaç kereden fazla) → eşikler birbirine fazla yakın, halt çırpınıyor.
