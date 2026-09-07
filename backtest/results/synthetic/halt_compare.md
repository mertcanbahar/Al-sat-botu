# Halt mekanizması: legacy sabit %20 mandal vs kademeli durum makinesi

Üretim zamanı: 2026-09-07T14:30:32.147924Z

> ⚠️ **SENTETİK VERİ**, 8 tohum (1, 2, 3, 4, 5, 6, 7, 8). Gerçek piyasa verisi değil; `generate_synthetic_data()`'nın deterministik rastgele yürüyüşü. Mekanizmaların *göreli* davranışı okunabilir, getiri rakamları gerçek performans tahmini DEĞİLDİR. Tüm sayılar tohumlar arası ortalamadır.

İki kol arasındaki tek fark halt mekanizması: aynı sinyal motoru, aynı pozisyon boyutlandırma, aynı maliyet modeli, aynı veri, aynı T+1 açılış yürütmesi.

## 1) İzole hesaplar (20 tek-sembol hesabı) — kilitlenmenin görüldüğü yer

| Metrik | legacy %20 | kademeli v1 | + koşullu ağ | + taban %30 | + taban %25 |
|---|---|---|---|---|---|
| **Sonda kilitli hesap** (20 üzerinden) | 6.0 | 0.0 | 3.8 | 3.8 | 3.8 |
| Halt'a hiç girmiş hesap | 6.2 | 4.9 | 4.9 | 4.9 | 4.9 |
| **En kötü hesap maks. DD** (ort.) | -22.34% | -23.21% | -21.50% | -21.50% | -21.50% |
| En kötü hesap maks. DD (tüm tohumların en kötüsü) | -23.93% | -25.59% | -22.11% | -22.11% | -22.11% |
| Medyan hesap maks. DD | -16.99% | -16.55% | -16.55% | -16.55% | -16.55% |
| Toplam getiri (20 hesap) | 3.66% | 3.67% | 3.61% | 3.61% | 3.61% |
| Toplam işlem | 483.2 | 524.0 | 508.6 | 508.6 | 508.6 |
| Halt'ın engellediği ALIM sinyali | 484.1 | 3.4 | 201.8 | 201.8 | 201.8 |
| Güvenlik ağının açık olduğu gün | 0.0 | 1357.2 | 408.5 | 408.5 | 408.5 |

## 2) Portföy geneli (paylaşılan sermaye)

| Metrik | legacy %20 | kademeli v1 | + koşullu ağ | + taban %30 | + taban %25 |
|---|---|---|---|---|---|
| Toplam getiri | 20.84% | 21.67% | 14.95% | 14.95% | 14.95% |
| CAGR | 2.84% | 3.58% | 2.23% | 2.23% | 2.23% |
| Gerçekleşen maks. DD | -21.89% | -25.87% | -22.29% | -22.29% | -22.29% |
| Sharpe | 0.16 | 0.28 | 0.12 | 0.12 | 0.12 |
| İşlem sayısı | 194.5 | 353.6 | 229.6 | 229.6 | 229.6 |
| Halt aktif gün oranı | 40.9% | 1.2% | 34.4% | 34.4% | 34.4% |
| **Sonda kilitli koşu sayısı** | 6/8 | 0/8 | 5/8 | 5/8 | 5/8 |

## 3) Kademeli kolların durum dağılımı (izole hesap-günü)

| Durum | Kapasite | kademeli v1 | + koşullu ağ | + taban %30 | + taban %25 |
|---|---|---|---|---|---|
| NORMAL | 100% | 13733.2 | 13733.2 | 13733.2 | 13733.2 |
| CAUTION | 75% | 5091.0 | 5091.0 | 5091.0 | 5091.0 |
| DEFENSIVE | 50% | 3769.8 | 3769.8 | 3769.8 | 3769.8 |
| HALT | 0% → ağ açılırsa 25% | 1406.0 | 1406.0 | 1406.0 | 1406.0 |

| Güvenlik ağının açık olduğu gün | — | 1357.2 | 408.5 | 408.5 | 408.5 |

## Nasıl okunmalı

- **Sonda kilitli hesap**: mekanizmanın çözmesi istenen asıl sorun. Legacy'de bir kez tetiklenen hesap bir daha alım yapamıyor.
- **En kötü hesap maks. DD**: koruma gerçekten koruyor mu? Dünkü histerezis denemesi tam burada elendi — kilitlenmeyi azaltırken en kötü hesabın drawdown'ını büyütmüştü. Bu sayı legacy'den kötüyse mekanizma sadece maliyet.
- **Güvenlik ağının açık olduğu gün** sıfırsa 14 günlük kural hiç devreye girmemiştir, yani o parametre bu test yatağında sınanmamış demektir.
