# Halt mekanizması: legacy sabit %20 mandal vs kademeli durum makinesi

Üretim zamanı: 2026-09-07T15:13:25.257418Z

Gerçek Twelve Data günlük verisi, 5 yıl, 20 sembol. Tek veri seti olduğu için tohum ortalaması yok.

İki kol arasındaki tek fark halt mekanizması: aynı sinyal motoru, aynı pozisyon boyutlandırma, aynı maliyet modeli, aynı veri, aynı T+1 açılış yürütmesi.

## 1) İzole hesaplar (20 tek-sembol hesabı) — kilitlenmenin görüldüğü yer

| Metrik | legacy %20 | kademeli v1 | v1 + taban %30 |
|---|---|---|---|
| **Sonda kilitli hesap** (20 üzerinden) | 4.0 | 0.0 | 0.0 |
| Halt'a hiç girmiş hesap | 6.0 | 0.0 | 0.0 |
| **En kötü hesap maks. DD** (ort.) | -23.64% | -19.72% | -19.72% |
| En kötü hesap maks. DD (tüm tohumların en kötüsü) | -23.64% | -19.72% | -19.72% |
| Medyan hesap maks. DD | -16.58% | -15.65% | -15.65% |
| Toplam getiri (20 hesap) | 20.74% | 20.53% | 20.53% |
| Toplam işlem | 671.0 | 701.0 | 701.0 |
| Halt'ın engellediği ALIM sinyali | 262.0 | 0.0 | 0.0 |
| Güvenlik ağının açık olduğu gün | 0.0 | 0.0 | 0.0 |

## 2) Portföy geneli (paylaşılan sermaye)

| Metrik | legacy %20 | kademeli v1 | v1 + taban %30 |
|---|---|---|---|
| Toplam getiri | -9.43% | 9.10% | 9.10% |
| CAGR | -1.39% | 1.24% | 1.24% |
| Gerçekleşen maks. DD | -26.53% | -27.84% | -27.84% |
| Sharpe | -0.19 | 0.16 | 0.16 |
| İşlem sayısı | 38.0 | 422.0 | 422.0 |
| Halt aktif gün oranı | 92.0% | 2.3% | 2.3% |
| **Sonda kilitli koşu sayısı** | 1/1 | 0/1 | 0/1 |

## 3) Kademeli kolların durum dağılımı (izole hesap-günü)

| Durum | Kapasite | kademeli v1 | v1 + taban %30 |
|---|---|---|---|
| NORMAL | 100% | 22838.0 | 22838.0 |
| CAUTION | 75% | 6436.0 | 6436.0 |
| DEFENSIVE | 50% | 6226.0 | 6226.0 |
| HALT | 0% → ağ açılırsa 25% | 0.0 | 0.0 |

| Güvenlik ağının açık olduğu gün | — | 0.0 | 0.0 |

## Nasıl okunmalı

- **Sonda kilitli hesap**: mekanizmanın çözmesi istenen asıl sorun. Legacy'de bir kez tetiklenen hesap bir daha alım yapamıyor.
- **En kötü hesap maks. DD**: koruma gerçekten koruyor mu? Dünkü histerezis denemesi tam burada elendi — kilitlenmeyi azaltırken en kötü hesabın drawdown'ını büyütmüştü. Bu sayı legacy'den kötüyse mekanizma sadece maliyet.
- **Güvenlik ağının açık olduğu gün** sıfırsa 14 günlük kural hiç devreye girmemiştir, yani o parametre bu test yatağında sınanmamış demektir.
