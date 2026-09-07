# Drawdown halt eşiği: %20 / %25 / %30 / %35 karşılaştırması

**Soru:** `MAX_DRAWDOWN_PCT` %20'de sistemi kilitliyor, %35'te hiç tetiklenmiyor.
Aradaki %25 ve %30 gerçek bir orta nokta mı?

**Kısa cevap:** Hayır, aralık dar. Bu test yatağında **%25, halt'ın hâlâ
bağladığı son eşik; %30 zaten tamamen işlevsiz (%35 ile birebir aynı sonuç).**
Yani "işlevi olsun ama kilitlemesin" hedefine en yakın değer **%25**.

## Nasıl üretildi

`backtest/halt_sweep.py` — `backtest/portfolio_backtest.py` ile *aynı* sinyal
motoru, aynı risk motoru, aynı maliyet modeli (5bps komisyon + 5bps slipaj,
her iki tarafta) ve aynı look-ahead'siz T+1 açılış yürütmesi. Eşik dışında
hiçbir parametre değişmiyor.

> ⚠️ **Bu rapordaki sayılar sentetik veriyle üretildi.** Bu oturumda ne
> `TWELVEDATA_API_KEY` ne de dış ağ erişimi var; gerçek fiyat verisi
> çekilemedi. Sayılar `generate_synthetic_data()`'nın deterministik rastgele
> yürüyüşünden geliyor — eşiklerin *göreli* davranışı (hangisi kilitliyor,
> hangisi hiç tetiklenmiyor) okunabilir, **getiri rakamları gerçek performans
> tahmini değildir.** Gerçek veriyle aynı süpürme için:
> Actions → **Manual drawdown-halt threshold sweep** (workflow'un `main`'de
> olması gerekir), sonuçlar `backtest/results/halt_sweep.md` olarak commit'lenir.

Ham çıktı: [`backtest/results/synthetic/halt_sweep.md`](results/synthetic/halt_sweep.md)
(+ `halt_sweep.json`). Yeniden üretmek için:

```bash
python backtest/halt_sweep.py --synthetic --out-dir backtest/results/synthetic
```

## İzole hesaplar (20 ayrı tek-sembol hesabı) — kilitlenmenin görüldüğü yer

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| Toplam getiri (20 hesap) | 3.89% | 4.94% | 4.94% | 4.94% |
| Toplam işlem | 509 | 537 | 537 | 537 |
| Halt'a hiç giren hesap | 6/20 | 1/20 | 0/20 | 0/20 |
| **Sonda kilitli kalan hesap** | **6/20** | **0/20** | 0/20 | 0/20 |
| Halt'ın engellediği ALIM sinyali | 471 | 0 | 0 | 0 |

- %20 → kilitli: AAPL, AMZN, BAC, DIS, PLD, WMT. Bunların dördü 200–520 gün
  boyunca hiç alım yapamadı (AMZN 522 gün, 176 sinyal engellendi).
- %25 → tek bir hesap (DIS) tek bir gün halt'a girdi, hiçbir ALIM engellenmedi.
- %30 ve %35 → hiç tetiklenmedi; ikisi de %35 ile birebir aynı sonuç veriyor,
  yani %30'u seçmek halt'ı fiilen kapatmakla eşdeğer.

## Portföy geneli (paylaşılan sermaye)

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| Toplam getiri | -14.23% | -21.06% | -24.60% | -30.57% |
| Gerçekleşen maks. DD | -24.19% | -30.43% | -34.19% | -38.64% |
| Sharpe | -0.26 | -0.41 | -0.48 | -0.63 |
| Halt aktif gün oranı | 57.8% | 57.2% | 54.4% | 52.2% |
| Sonda kilitli mi? | EVET | EVET | EVET | EVET |

Portföy tarafı eşikler arasında ayrım yapmıyor: sentetik dünyada strateji
paylaşılan sermayeyle para kaybediyor, dolayısıyla **her eşikte** halt bir kez
tetikleniyor ve pencere sonuna kadar açık kalıyor. Buradan çıkan tek okunabilir
sinyal, eşiği gevşetmenin bu koşuda zararı büyütmesi (-14% → -31%): halt geç
devreye girdiğinde daha fazla sermaye kaybediliyor.

## Asıl sorun eşik değil: halt tek yönlü bir mandal

Kural yalnızca **yeni ALIM'ları** durduruyor. Ama düşen equity'yi zirveye geri
taşıyabilecek tek mekanizma da yeni alımlar. Bu yüzden halt bir kez tetiklendiğinde
kendini serbest bırakacak bir yol kalmıyor — %20'de "kilitlenme" olarak görülen
şey tam olarak bu. Eşiği büyütmek kilitlenmeyi çözmüyor, sadece tetiklenme
olasılığını düşürüyor; %30'da olduğu gibi kuralı tamamen etkisizleştirene kadar.

Kalıcı çözüm bir **serbest bırakma koşulu** eklemek olur, örneğin:

- drawdown daha dar bir banda (ör. %10) geri döndüğünde halt'ı kaldırmak
  (histerezis), ya da
- halt N gün sürdükten sonra `peak_equity`'yi güncel equity'ye çekip yeniden
  başlamak (soğuma süresi), ya da
- halt sırasında pozisyon büyüklüğünü sıfırlamak yerine küçültmek (ör. %25 boyut).

Bu rapor bunları uygulamıyor; ölçüm ve öneriyle sınırlı.

## Öneri

1. Eşiği **%25**'e almak, %20'nin kalıcı kilitlenmesini ortadan kaldırırken
   kuralın bağlayıcılığını (marjinal de olsa) koruyan tek seçenek. %30 ve %35
   arasında ölçülebilir bir fark yok.
2. Bunu gerçek veriyle bir kez daha doğrulamak gerekir — sentetik koşu yalnızca
   göreli davranışı gösteriyor.
3. Asıl kazanç, eşikte değil, yukarıdaki histerezis/soğuma mekanizmasında.

`alsatbotu/config.py` içindeki canlı varsayılan bu çalışmada **değiştirilmedi**
(hâlâ %20). Değer artık `ALSATBOTU_MAX_DRAWDOWN_PCT` ortam değişkeniyle de
ezilebiliyor, böylece canlı varsayılanı değiştirmeden deneme yapılabiliyor.
