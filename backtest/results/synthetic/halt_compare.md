# Halt mekanizması: legacy sabit %20 mandal vs kademeli durum makinesi

Üretim zamanı: 2026-09-07T13:28:24.908988Z

> ⚠️ **SENTETİK VERİ**, 8 tohum (1, 2, 3, 4, 5, 6, 7, 8). Gerçek piyasa verisi değil; `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü. Mekanizmaların *göreli* davranışı okunabilir, getiri rakamları gerçek performans tahmini DEĞİLDİR. Tüm sayılar tohumlar arası ortalamadır.

İki kol arasındaki tek fark halt mekanizması: aynı sinyal motoru, aynı pozisyon boyutlandırma, aynı maliyet modeli, aynı veri, aynı T+1 açılış yürütmesi.

## 1) İzole hesaplar (20 tek-sembol hesabı) — kilitlenmenin görüldüğü yer

| Metrik | legacy %20 | kademeli |
|---|---|---|
| **Sonda kilitli hesap** (20 üzerinden) | 6.0 | 0.0 |
| Halt'a hiç girmiş hesap | 6.2 | 4.9 |
| **En kötü hesap maks. DD** (ort.) | -22.34% | -23.21% |
| En kötü hesap maks. DD (tüm tohumların en kötüsü) | -23.93% | -25.59% |
| Medyan hesap maks. DD | -16.99% | -16.55% |
| Toplam getiri (20 hesap) | 3.66% | 3.67% |
| Toplam işlem | 483.2 | 524.0 |
| Halt'ın engellediği ALIM sinyali | 484.1 | 3.4 |
| Güvenlik ağının açık olduğu gün | 0.0 | 1357.2 |

## 2) Portföy geneli (paylaşılan sermaye)

| Metrik | legacy %20 | kademeli |
|---|---|---|
| Toplam getiri | 20.84% | 21.67% |
| CAGR | 2.84% | 3.58% |
| Gerçekleşen maks. DD | -21.89% | -25.87% |
| Sharpe | 0.16 | 0.28 |
| İşlem sayısı | 194.5 | 353.6 |
| Halt aktif gün oranı | 40.9% | 1.2% |
| **Sonda kilitli koşu sayısı** | 6/8 | 0/8 |

## 3) Kademeli kolun durum dağılımı (izole hesap-günü)

| Durum | Ortalama gün | Kapasite |
|---|---|---|
| NORMAL | 13733.2 | 100% |
| CAUTION | 5091.0 | 75% |
| DEFENSIVE | 3769.8 | 50% |
| HALT | 1406.0 | 0% → 14 gün sonra 25% |

## Nasıl okunmalı

- **Sonda kilitli hesap**: mekanizmanın çözmesi istenen asıl sorun. Legacy'de bir kez tetiklenen hesap bir daha alım yapamıyor.
- **En kötü hesap maks. DD**: koruma gerçekten koruyor mu? Dünkü histerezis denemesi tam burada elendi — kilitlenmeyi azaltırken en kötü hesabın drawdown'ını büyütmüştü. Bu sayı legacy'den kötüyse mekanizma sadece maliyet.
- **Güvenlik ağının açık olduğu gün** sıfırsa 14 günlük kural hiç devreye girmemiştir, yani o parametre bu test yatağında sınanmamış demektir.
