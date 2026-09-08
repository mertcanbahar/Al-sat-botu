# Drawdown halt: eşik süpürmesi, histerezis ve trend kapısı

> ## 🟢 KARAR: trend kapılı halt production'a alınıyor
>
> Bu belgenin gövdesi **sentetik veriye** dayanıyor ve orada histerezisin
> ölçülebilir bir faydası görünmemişti (mekanizma bir kez geri alındı).
> Gerçek veri koşusu tabloyu değiştirdi. 2007-01-18 → 2026-09-04, 19 sembol
> (META 2012 IPO olduğu için evren dışı):
>
> | | Halt kapalı | Trend kapısı |
> |---|---|---|
> | Toplam getiri | +537.25% | **+653.22%** |
> | CAGR | 9.90% | **10.84%** |
> | Sharpe | 0.65 | **0.71** |
> | Maks. drawdown | -42.13% | **-40.68%** |
> | Halt aktif gün | 0 | 144 (%2.9) |
> | Kilitlenme / kalıcı durdurma | yok | **yok** |
>
> Halt 9 kez tetiklendi (dördü 2008'de), dokuzunda da trend dönüşüyle açıldı.
> 2008 penceresinde hem getiri (-23.67% vs -25.32%) hem drawdown
> (-40.68% vs -42.13%) daha iyi. Ham çıktı: `results/crisis_real.json`.
>
> **Sınırlar:** fark mütevazı (yılda ~0.94 puan CAGR, 0.06 Sharpe) ve tek bir
> tarihsel yol üzerinden ölçüldü — bir yoldan istatistiksel anlamlılık
> çıkmaz. 5 stres penceresinin 2'sinde (2020, 2022) halt kapalı biraz daha
> iyi. Evren bugünün blue chip'lerinden seçili (survivorship). "Halt'ı
> tamamen kaldır" da savunulabilir bir karardı; trend kapısı, aynı getiriyi
> daha az drawdown'la verdiği ve mandalın kilitlenme kusurunu da ortadan
> kaldırdığı için seçildi.
>
> Sentetik kriz senaryolarında (3 çöküş şekli × 6 tohum) trend kapısı, sabit
> gün sayılı reset'lerin şekle bağımlılığını da çözüyordu: 60 gün çift dipte
> iyi/uzun-yavaşta kötü, 120 gün tersi iken trend kapısı üçünde de tutarlıydı
> ve tek kalıcı durdurma vakasını ortadan kaldırdı.


Bu belge iki soruyu sırayla cevaplıyor:

1. `MAX_DRAWDOWN_PCT` için %20 / %25 / %30 / %35 arasında işe yarar bir orta
   nokta var mı?
2. Kilitlenmeyi eşik ayarıyla değil mekanizmayla çözersek ne oluyor?

Kısa cevaplar: **(1) Yok** — eşik ne olursa olsun tek yönlü mandal ya kilitliyor
ya hiç tetiklenmiyor. **(2) Histerezis + kısmi peak reset'i kilitlenmeyi tamamen
kaldırıyor (6/20 → 0/20), ama en kötü hesap drawdown'ını -22.8%'den -28.4%'e
çıkarıyor.** Bu bir takas; ayarla giderilemiyor.

---

## ⚠️ Verinin niteliği

Bu ortamda `TWELVEDATA_API_KEY` ve dış ağ erişimi yok, gerçek fiyat verisi
çekilemiyor. Bütün sayılar `generate_synthetic_data()`'nın deterministik
rastgele yürüyüşünden geliyor. **Getiri seviyeleri gerçek performans tahmini
değildir**; okunabilir olan, politikaların *göreli* davranışı (hangisi
kilitliyor, hangisi hiç tetiklenmiyor, hangisi çırpınıyor).

Tek bir çekilişe dayanmasın diye her politika 4–8 farklı tohumda koşuldu;
tablolarda medyan, parantezde tohumlar arası aralık var.

> **Ölçüm zemini düzeltmesi:** `generate_synthetic_data()` sembol tohumunu
> `hash(symbol)` ile üretiyordu. Python'da string hash'i süreç başına
> rastgelelendiği için "deterministik" olduğu yazan veri süreçler arasında
> yeniden üretilemiyordu — aynı komut üç kez koşulduğunda AAPL'nin son fiyatı
> 231.57 / 242.50 / 244.93 çıkıyordu. `crc32`'ye geçildi. Bu belgeden önceki
> tek-tohumlu eşik tablosu o bozuk üreteçle üretilmişti ve silindi.

Gerçek veriyle aynı süpürme: Actions → **Manual drawdown-halt threshold sweep**
(workflow'un `main`'de olması gerekir). Ham çıktılar:
[`results/synthetic/`](results/synthetic/).

---

## 1) Eşik tek başına: %20 / %25 / %30 / %35

4 tohum, izole hesaplar, **mandal modunda** (histerezis kapalı) — yani orijinal
sorunun sorulduğu haliyle:

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| **Sonda kilitli hesap** | **5.5/20** (3–8) | 1 (1–3) | 0 (0–1) | **0** |
| Halt tetiklenme | 5.5 (3–8) | 1 (1–3) | 0 (0–1) | **0** |
| Engellenen ALIM sinyali | 388 (266–733) | 45.5 (1–256) | 0 (0–11) | **0** |
| Halt gün oranı | 6.84% | 0.99% | 0.00% | **0.00%** |
| Toplam getiri (20 hesap) | 6.12% | 6.47% | 7.15% | 7.21% |
| En kötü hesap DD | -22.79% | -25.35% | -27.14% | -27.14% |

Okunuşu: **%20 kilitliyor** (20 hesabın 5–8'i pencere sonuna kadar alım
yapamıyor), **%35 hiç tetiklenmiyor** (dört tohumun hiçbirinde tek bir kez
bile), **%30 pratikte etkisiz** (medyan sıfır tetiklenme; %35 ile aynı getiri
ve aynı drawdown). Geriye tek aday olarak **%25** kalıyor: kural hâlâ gerçek
sinyalleri engelliyor (medyan 45) ama kilitlenme 5.5'ten 1 hesaba düşüyor.

Yine de %25 sorunu *çözmüyor*, sadece küçültüyor: dört tohumun hepsinde en az
bir hesap pencere sonunda kilitli kalıyor. Eşik büyütmek kilitlenmeyi ortadan
kaldırmıyor, kuralı etkisizleştirene kadar seyrekleştiriyor. Aynı tablo
histerezisli mekanizmayla koşulduğunda **her eşikte** kilitli hesap sıfıra
iniyor — asıl fark eşikten değil mekanizmadan geliyor.

> **Önceki rapordan düzeltme:** bozuk üreteçle koşan ilk tabloda "%25'te hiç
> kilitlenme yok" ve "%30 hiç tetiklenmiyor" yazıyordu. Düzeltilmiş üreteçle
> %25 dört tohumun hepsinde 1–3 hesabı kilitliyor ve %30 bazı tohumlarda
> tetikleniyor. Yön aynı kaldı, rakamlar değişti — tek çekilişe güvenmemenin
> sebebi tam olarak bu.


## 2) Mekanizma: mandal vs. histerezis + kısmi reset

8 tohum, izole hesaplar (kilitlenme burada en net görünür, çünkü halt'a giren
alt hesabı kurtaracak başka mekanizma yok).

| Metrik | H%20 mandal (mevcut) | H%20 → R%5 | H%20 → R%10 | H%20 → R%15 |
|---|---|---|---|---|
| **Sonda kilitli hesap** | **6/20** (3–10) | 0 (0–1) | **0** (0–1) | 0.5 (0–1) |
| Kalıcı durdurulan hesap | 0 | 0 | 0 | 0 |
| Halt tetiklenme | 6 (3–10) | 6.5 (3–10) | 6.5 (3–10) | 7 (3–10) |
| Toparlanmayla çıkış | 0 | **0** | **0** | **0** (0–1) |
| Kısmi reset ile çıkış | 0 | 6 (3–9) | 6 (3–9) | 5 (3–9) |
| Engellenen ALIM sinyali | 454 (203–1058) | 54 (16–111) | 54 (16–111) | 44 (16–111) |
| Halt gün oranı | 8.72% | 1.55% | 1.55% | 1.52% |
| Toplam getiri (20 hesap) | 4.42% | 4.83% | 4.83% | 4.78% |
| Ortalama maks. DD | -16.50% | -17.33% | -17.33% | -17.38% |
| **En kötü hesap DD** | **-22.79%** | -28.37% | **-28.37%** | -28.37% |

### Bulgu A: kilitlenme çözüldü

Mandal 20 hesabın 6'sını (en kötü tohumda 10'unu) pencere sonuna kadar kilitli
bırakıyor. Histerezisli mekanizmada bu 0'a iniyor ve kalıcı durdurma sekiz
tohumun hiçbirinde tetiklenmiyor. Halt'ın engellediği ALIM sinyali 454'ten
54'e düşüyor: kural hâlâ fren yapıyor, ama artık frene basılı kalmıyor.

### Bulgu B: onaylanan iki eşikten biri fiilen çalışmıyor

**Toparlanmayla çıkış 8 tohum × 20 hesapta toplam BİR kez oldu** (o da yalnızca
R=%15'te). Bütün diğer çıkışlar kısmi reset'ten geldi. Nedeni ölçüldü: halt'a
giren hesap kısa sürede nakde dönüyor (halt günlerinin %85–94'ünde equity
kelimesi kelimesine sabit, pencere sonunda açık pozisyon sıfır). Nakitteki bir
hesabın equity'si donduğu için "drawdown %10'a gerilesin" koşulu yapısal olarak
ulaşılamaz.

Pratik sonucu: **R=%5, %10 ve %15 birbirinden ayırt edilemiyor.** Kilidi açan
şey histerezis değil, kısmi peak reset'i. R mekanizmada kalmalı — halt
pozisyonlar hâlâ açıkken tetiklenirse doğru çıkış yolu odur — ama "iki eşik
arasındaki fark ne olmalı" sorusunun bu veride ölçülebilir bir cevabı yok.

### Bulgu C: asıl belirleyici parametre reset bekleme süresi

| Metrik | 20 gün | 40 gün | 60 gün (varsayılan) |
|---|---|---|---|
| Sonda kilitli hesap | 0 | 0 | 0 |
| Engellenen ALIM sinyali | 1 (0–5) | 12 (8–24) | 22 (16–50) |
| Halt gün oranı | 0.42% | 0.83% | 1.25% |
| Toplam getiri | 6.24% | 5.90% | 6.00% |

Üçü de kilidi açıyor; fark halt'ın ne kadar fren yaptığında. 20 gün kuralı
neredeyse dişsiz bırakıyor (medyan 1 engellenen sinyal). **60 gün** en fazla
korumayı veren ve hâlâ kilitlemeyen değer.

### Bulgu D: drawdown artışı ayarla giderilemiyor

Kilidin açılması bedava değil: bot yeniden pozisyon aldığı için en kötü hesabın
drawdown'ı -22.79%'dan -28.37%'ye çıkıyor (ortalama -16.50% → -17.33%). Bunu
`reset_fraction`'la (reset'te peak'in equity'ye ne kadar çekildiği) telafi
etmeyi denedim — olmuyor:

| Metrik | 0.25 | 0.5 (varsayılan) | 0.75 |
|---|---|---|---|
| Sonda kilitli hesap | 0 (0–1) | 0 (0–1) | **1** (0–3) |
| Kalıcı durdurulan hesap | 0 | 0 | 0.5 (0–1) |
| En kötü hesap DD | -26.80% | -26.80% | **-27.58%** |
| Halt tetiklenme | 5.5 | 5.5 | 8 |

Peak'i daha az çekmek (0.75) korumayı artırmıyor; hem kilitlenmeyi geri
getiriyor hem de en kötü drawdown'ı kötüleştiriyor, çünkü hesap daha sık halt'a
girip çıkıyor. 0.25 ile 0.5 bu pencerede birebir aynı. **0.5 kalıyor.**

Dürüst okuma: mandalın "daha iyi drawdown"ı bir koruma değil, ölü hesabın
kaybedememesinin yan etkisi. Kilitlenmeyi istemiyorsak bu farkı kabul ediyoruz.

---

## Kabul kriterleri: ne tuttu, ne tutmadı

| Kriter | Sonuç |
|---|---|
| Kalıcı kilitli hesap: 0 | ✅ 8 tohumda medyan 0 (bir tohumda 1 hesap, pencere sonuna yakın halt'a girdiği için henüz reset süresini doldurmamıştı — kalıcı kilit değil) |
| Çırpınma yok (döngü ≤ ~1/yıl) | ✅ 5 yılda hesap başına ~0.06 tetiklenme |
| Halt hâlâ ALIM engelliyor | ✅ medyan 54 sinyal (mandal: 454) |
| Maks. DD bugünkünden kötü değil | ❌ **düştü** — en kötü hesap -22.8% → -28.4%, ortalama -16.5% → -17.3% |
| ≥20 tohumda tutarlı | ⚠️ 8 tohumda koşuldu (her tohum ~13 dk); yön bütün tohumlarda aynı |
| Gerçek veriyle doğrulanmış | ❌ **yapılmadı** — bu ortamda API anahtarı/ağ yok |

## Öneri

1. Mekanizma canlıya alınmadan önce **gerçek Twelve Data ile** bir kez koşulmalı
   (`manual-halt-sweep.yml`, workflow main'e girdikten sonra). Sentetik veri
   yalnızca göreli davranışı gösteriyor.
2. Parametreler bu ölçümlere göre: **H %20** (değişmedi), **R %10**,
   **reset 60 gün × 0.5**, **max 2 reset**, **sert taban %50**. R'nin değeri bu
   veride belirleyici olmadığı için ortadaki değer seçildi.
3. Kabul edilmesi gereken takas: en kötü senaryoda drawdown ~5.6 puan artıyor.
   Bu kabul edilemezse alternatif, kilidi açarken pozisyon boyutunu da kısmak
   olur (halt sonrası ilk N işlemde %50 boyut gibi) — ölçülmedi, önerilmedi.

`alsatbotu/config.py` içindeki canlı varsayılanlar bu çalışmada **değiştirilmedi**
(H hâlâ %20). Yeni mekanizma varsayılan olarak aktif; hepsi ortam değişkeniyle
ezilebiliyor.
