# Drawdown halt: üç turluk ölçüm kaydı

> ## 🟡 DURUM: kademeli merdiven öneriliyor, canlı hâlâ sabit %20 mandalda
>
> Canlı davranış **değişmedi**: `MAX_DRAWDOWN_PCT = 0.20`, tek yönlü mandal,
> `scripts/run_portfolio.py` durum makinesini çağırmıyor. Kademeli mekanizma
> yalnızca `policy=` verildiğinde çalışıyor; verilmezse eski kod yolu birebir
> korunuyor (bu, sentetik veride 1200 günlük equity eğrisinin `origin/main`
> ile byte-byte aynı çıkmasıyla doğrulandı).
>
> Gerçek veri koşusu kademeli merdivenin lehine çıktı, **ama tasarımın dört
> bileşeninden üçü o koşuda hiç yürümedi.** Ayrıntı: [§5](#5-ne-sınandı-ne-sınanmadı).
> Canlıya geçiş bu yüzden henüz önerilmiyor; sıradaki adım [§7](#7-sıradaki-adım).

Bu belge üç turu sırayla kaydediyor:

| Tur | Soru | Sonuç |
|---|---|---|
| 1 | Eşik ayarı kilitlenmeyi çözer mi? | ❌ Hayır — her eşik ya kilitliyor ya hiç tetiklenmiyor |
| 2 | Histerezis + kısmi peak reset çözer mi? | ❌ Ölçüldü, reddedildi, geri alındı |
| 3 | Kademeli kapasite merdiveni çözer mi? | ✅ Sentetikte ve gerçek veride evet — ama eksik sınamayla |

---

## ⚠️ Verinin niteliği

Tur 1 ve 2 **yalnızca sentetik** veriyle koşuldu (o oturumlarda API anahtarı
yoktu). Tur 3 hem sentetik (8 tohum) hem **gerçek Twelve Data** (5 yıl, 20
sembol) ile koşuldu.

Sentetik sayılarda **getiri seviyeleri gerçek performans tahmini değildir**;
okunabilir olan politikaların *göreli* davranışıdır. Gerçek veri koşusunda ise
tek bir 5 yıllık pencere var — tohum ortalaması yok, yani "şu oranda koşuda
şu olur" türü istatistik çıkarılamaz.

> **Ölçüm zemini düzeltmesi (tur 2'den kalma, hâlâ geçerli):**
> `generate_synthetic_data()` sembol tohumunu `hash(symbol)` ile üretiyordu.
> Python'da string hash'i süreç başına rastgelelendiği için "deterministik"
> yazan veri süreçler arasında yeniden üretilemiyordu. `crc32`'ye geçildi.

Ham çıktılar: [`results/halt_compare.md`](results/halt_compare.md) (gerçek veri),
[`results/synthetic/`](results/synthetic/) (sentetik).

---

## 1) Tur 1 — eşik tek başına: %20 / %25 / %30 / %35

4 tohum, izole hesaplar, mandal modunda:

| Metrik | %20 | %25 | %30 | %35 |
|---|---|---|---|---|
| **Sonda kilitli hesap** | **5.5/20** (3–8) | 1 (1–3) | 0 (0–1) | **0** |
| Engellenen ALIM sinyali | 388 (266–733) | 45.5 (1–256) | 0 (0–11) | **0** |
| Halt gün oranı | 6.84% | 0.99% | 0.00% | **0.00%** |
| En kötü hesap DD | -22.79% | -25.35% | -27.14% | -27.14% |

**%20 kilitliyor, %35 hiç tetiklenmiyor, %30 pratikte etkisiz** (%35 ile aynı
getiri ve drawdown). %25 kilitlenmeyi 5.5'ten 1 hesaba düşürüyor ama sıfırlamıyor.

Sonuç: eşik büyütmek kilitlenmeyi ortadan kaldırmıyor, kuralı etkisizleştirene
kadar seyrekleştiriyor. **Sorun eşikte değil, mekanizmada.**

---

## 2) Tur 2 — histerezis + kısmi peak reset (REDDEDİLDİ)

8 tohum, izole hesaplar:

| Metrik | %20 mandal | H%20 → R%5 | H%20 → R%10 | H%20 → R%15 |
|---|---|---|---|---|
| **Sonda kilitli hesap** | **6/20** (3–10) | 0 (0–1) | **0** (0–1) | 0.5 (0–1) |
| Toparlanmayla çıkış | 0 | **0** | **0** | **0** (0–1) |
| Kısmi reset ile çıkış | 0 | 6 (3–9) | 6 (3–9) | 5 (3–9) |
| Engellenen ALIM sinyali | 454 (203–1058) | 54 (16–111) | 54 (16–111) | 44 (16–111) |
| **En kötü hesap DD** | **-22.79%** | -28.37% | **-28.37%** | -28.37% |

**Neden reddedildi:** (a) getiri/drawdown sonuçları halt'ı tamamen kapatmakla
ayırt edilemiyordu; (b) onaylanan iki eşikten biri fiilen hiç çalışmadı —
toparlanmayla çıkış 8 tohum × 20 hesapta **toplam bir kez** oldu; (c) en kötü
hesap drawdown'ı -22.8%'den -28.4%'e çıktı. Ölçülen tek şey maliyetti.

**(b)'nin sebebi tur 3'ün de temel dayanağı:** halt'a giren hesap kısa sürede
nakde dönüyor (halt günlerinin %85–94'ünde equity kelimesi kelimesine sabit).
Nakitteki bir hesabın equity'si donduğu için "drawdown geri gerilesin" koşulu
**yapısal olarak ulaşılamaz**. Histerezis tek başına ölü hesabı diriltemez.

Mekanizmanın kodu `432f577` commit'inde eklendi, `6254c93`'te geri alındı.
(Bu belgenin önceki sürümü kodun yerini `1fc8e31` diye veriyordu; o commit
eşik tablosunun yeniden koşulması, mekanizmanın eklendiği commit değil.)
`results/synthetic/halt_sweep_hysteresis*`, `*_reset_marks`, `*_reset_fraction`
dosyaları artık kodda olmayan bir mekanizmayı ölçüyor; kayıt olarak duruyorlar.

---

## 3) Tur 3 — kademeli kapasite merdiveni

Tasarım (`engine/halt.py`), dört bileşen:

| Durum | Drawdown | Pozisyon kapasitesi |
|---|---|---|
| NORMAL | 0–10% | %100 |
| CAUTION | 10–15% | %75 |
| DEFENSIVE | 15–20% | %50 |
| HALT | 20%+ | %0, 14 gün sonra %25 (güvenlik ağı) |

Artı: her kademede histerezis (girişte %20, çıkışta %15 gibi) ve %30/%25
mutlak taban.

Tur 2'den farkı: **kademeli kapasite hesabı tam nakde hiç düşürmüyor**, yani
equity hareket etmeye devam ediyor ve drawdown gerçekten toparlanabiliyor.
Histerezisin tek başına çözemediği şey buydu.

### 3a) Sentetik ablasyon, 8 tohum

Hangi bileşenin neyi yaptığını ayrıştırmak için yedi kol:

| Kol | Kilitli /20 | Portföy kilitli | Portföy getiri | Sharpe | En derin DD | En kötü hesap DD |
|---|---|---|---|---|---|---|
| legacy %20 | 6.0 | 6/8 | 20.84% | 0.16 | **-25.72%** | -22.34% |
| **kademeli v1** | **0.0** | **0/8** | **21.67%** | **0.28** | -34.84% | -23.21% |
| v1 + taban %30 | **0.0** | 2/8 | 19.68% | 0.19 | -32.21% | -23.21% |
| v1 + taban %25 | 0.1 | 5/8 | 13.23% | 0.08 | -27.55% | -23.14% |
| + koşullu ağ | 3.8 | 5/8 | 14.95% | 0.12 | **-24.16%** | **-21.50%** |
| + koşullu ağ + taban %30 | 3.8 | 5/8 | 14.95% | 0.12 | -24.16% | -21.50% |
| + koşullu ağ + taban %25 | 3.8 | 5/8 | 14.95% | 0.12 | -24.16% | -21.50% |

### Bulgu A: kilitlenme çözüldü, ama kuyruk açıldı

v1 kilitlenmeyi 8 tohumun **hepsinde** sıfırladı (6.0 → 0.0 hesap, 6/8 → 0/8
portföy koşusu) ve hem getiriyi hem Sharpe'ı iyileştirdi. Bedeli: iki tohumda
portföy drawdown'ı **-34.8%** ve **-34.6%**'ya çıktı (legacy'de -21.7% / -23.4%).
Kalan altı tohumda fark küçüktü (ortalama -1.24 puan). Yani kalın kuyruk:
çoğu zaman nötr, bazen çok kötü.

### Bulgu B: taban kuyruğu daraltıyor ama kapatmıyor — yapısal sebeple

| En derin portföy DD | legacy | v1 | v1+%30 | v1+%25 |
|---|---|---|---|---|
| 8 tohum | -25.72% | -34.84% | -32.21% | -27.55% |

Hiçbir taban legacy seviyesine inemiyor. **Sebebi parametre değil:** taban
yalnızca *yeni alımı* durduruyor. Hesap eşiği geçtiğinde zaten yüklü ve mevcut
pozisyonlar kaybetmeye devam ediyor. Alım tarafındaki bir taban drawdown'ı
tanım gereği sınırlayamaz — bunun için zorunlu likidasyon gerekir, ki bu
tasarımda hiç konuşulmadı.

### Bulgu C: taban kilitlenmeyi geri getiriyor

İzole hesaplarda taban zararsız görünüyor (kilitli 0.0 / 0.1), ama **portföy
seviyesinde kilitlenme geri geliyor**: 0/8 → 2/8 (taban %30), 0/8 → **5/8**
(taban %25). Sebebi tabanın kendi histerezisi: %30'da bağlayan taban ancak DD
%25'e gerileyince bırakıyor, sürekli düşen bir piyasada portföy o bandın
altında uzun süre kalıyor.

Bedeli getiride de görünüyor: taban %30 → 21.67%'den 19.68%'e; taban %25 →
**13.23%**, yani v1'in kazancının tamamından fazlası.

**Taban %25 elendi:** her eksende kötü — getiriyi 8.4 puan yakıyor,
kilitlenmenin çoğunu geri getiriyor, ve kuyruğu yine legacy seviyesine
indiremiyor.

### Bulgu D: koşullu ağ elendi (kendi önerim, veri desteklemedi)

"Ağ yalnızca drawdown derinleşmiyorsa açılsın" varyantı en iyi kuyruğu verdi
(-24.16%, legacy'den bile iyi) — **ama bunu hesapları yeniden kilitleyerek
başardı.** Sonda bloke kalan hesapların bloke serileri ölçüldü:

| Hesap (tohum 2) | legacy | koşullu ağ |
|---|---|---|
| AAPL | son 583 gün | son **519 gün** |
| NVDA | son 829 gün | son **617 gün** |
| AMZN (tohum 4) | son 649 gün | son **641 gün** |

1200 günlük pencerede yarısı boyunca alım yok. Ayrıca portföy getirisini
21.67%'den 14.95%'e düşürüyor. Legacy'ye kıyasla bile getiri 5.9 puan aşağıda.

**Varsayılan olarak kapatıldı**
(`ALSATBOTU_HALT_RECOVERY_REQUIRES_STABLE_DD=0`), kodu ve testleri duruyor.

### Bulgu E: 14 günlük ağ, "nadir kaçış kapısı" değil

v1'de 1406 HALT gününün **1357'si** (%96.5) ağın açık olduğu günler. HALT
pratikte "14 gün %0, sonra süresiz %25" anlamına geliyor. Tasarım kararı yanlış
değil ama **"güvenlik ağı" adı olan biteni yanlış anlatıyor**; v1'in kuyruğunun
mekanizması da tam bu — HALT'a giren hesap 14 gün sonra düşüşe %25 ile geri
biniyor.

---

## 4) Tur 3 — gerçek veri koşusu (7 Eylül 2026)

Twelve Data, 5 yıl, 20 sembol, tek pencere.
Ham çıktı: [`results/halt_compare.md`](results/halt_compare.md).
Koşu: `manual-halt-sweep.yml`, `--mode compare`.

### İzole hesaplar (20 tek-sembol hesabı)

| Metrik | legacy %20 | kademeli v1 | v1+taban%30 |
|---|---|---|---|
| **Sonda kilitli hesap** | 4/20 | **0/20** | **0/20** |
| Halt'a hiç girmiş hesap | 6/20 | **0/20** | **0/20** |
| **En kötü hesap maks. DD** | -23.64% | **-19.72%** | **-19.72%** |
| Medyan hesap maks. DD | -16.58% | -15.65% | -15.65% |
| Toplam getiri (20 hesap) | 20.74% | 20.53% | 20.53% |
| Toplam işlem | 671 | 701 | 701 |
| Engellenen ALIM sinyali | 262 | **0** | **0** |

### Portföy geneli

| Metrik | legacy %20 | kademeli v1 | v1+taban%30 |
|---|---|---|---|
| **Toplam getiri** | **-9.43%** | **+9.10%** | **+9.10%** |
| CAGR | -1.39% | +1.24% | +1.24% |
| Maks. DD | -26.53% | -27.84% | -27.84% |
| Sharpe | -0.19 | **+0.16** | **+0.16** |
| İşlem sayısı | **38** | 422 | 422 |
| Halt aktif gün oranı | **92.0%** | 2.3% | 2.3% |
| Engellenen ALIM | **6358** | 9 | 9 |
| Sonda kilitli | **EVET** | hayır | hayır |

### Bulgu F: kilitlenme gerçek veride sentetikten çok daha ağır

Legacy portföy kolu 5 yılın **%92'sinde** halt'ta, 6358 ALIM sinyalini
engelliyor, toplam **38 işlem** yapıyor ve **-9.43%** ile bitiriyor. Bu "ara
sıra tetikleniyor" değil, sistemin fiilen donması. Kademeli merdiven aynı
veride 422 işlem yapıyor ve **+9.10%** getiriyor.

### Bulgu G: sentetik kuyruk gerçek veride görünmedi

Portföy maks. DD farkı yalnızca 1.31 puan (-26.53% → -27.84%). Sentetikteki
-34.8% kuyruğu bu pencerede yok. Dahası, tur 2'yi eleyen metrik olan **en kötü
hesap DD'si kötüleşmedi, iyileşti**: -23.64% → -19.72%.

Bu, kuyruğun yok olduğu anlamına gelmez — bu pencerede denk gelmediği anlamına
gelir.

### Bulgu H: HALT'a hiç girilmedi

İzole hesapların durum dağılımı (hesap-günü):

| Durum | Kapasite | gün |
|---|---|---|
| NORMAL | %100 | 22.838 |
| CAUTION | %75 | 6.436 |
| DEFENSIVE | %50 | 6.226 |
| **HALT** | %0 → %25 | **0** |
| Güvenlik ağı açık | — | **0** |

Sebebi aslında iyi haber: CAUTION/DEFENSIVE kademelerinde pozisyonu küçültmek,
drawdown'ın %20'ye ulaşmasını **en baştan engelledi** — en kötü hesap %19.72'de
kaldı. Merdiven işini o kadar iyi yaptı ki HALT'a sıra gelmedi.

Ama sonucu şu: `v1` ile `v1+taban%30` kolları gerçek veride **byte-byte aynı
sonuç** verdi. Taban hiç bağlamadı.

Portföy kolunda halt %2.3 gün aktif (~29 gün), yani orada HALT'a girildi. Ağın
o episodlarda açılıp açılmadığı **ölçülmedi** — `recovery_net_days` metriği
yalnızca izole hesaplar üzerinden toplanıyor.

---

## 5) Ne sınandı, ne sınanmadı

Tasarımın dört bileşeninden gerçek veride yalnızca biri yürüdü:

| Bileşen | Sentetik | Gerçek veri |
|---|---|---|
| Kademeli merdiven (%100/75/50) | ✅ | ✅ 12.662 hesap-günü CAUTION+DEFENSIVE |
| HALT (%0 kapasite) | ✅ 1406 hesap-günü | ❌ izole hesaplarda 0 gün |
| 14 günlük güvenlik ağı | ✅ 1357 gün açık | ❌ 0 gün |
| Mutlak taban %30 | ✅ (yalnızca v1 kolunda) | ❌ hiç bağlamadı |

**Canlıya alınırsa, risk motoruna gerçek veride hiç yürütülmemiş üç kod yolu
gönderilmiş olur.** Birim testleri var (59 test: durum geçişleri, her kademede
histerezis boşluğu, eşik etrafında zikzak yapmama ve düz eşiğin aynı seride
zikzak yaptığının karşı-kanıtı, çok kademe atlama, donmuş nakit hesabın 14.
günde açılması, saatin HALT'tan çıkışta sıfırlanması, tabanın saatten bağımsız
sıfırlaması ve kendi histerezisi) — ama birim testi gerçek veri değildir.

---

## 6) Kabul kriterleri

| Kriter | Sonuç |
|---|---|
| Kalıcı kilitli hesap: 0 | ✅ Sentetik 8/8 tohumda 0.0; gerçek veride 0/20 |
| Çırpınma yok | ✅ Histerezis testi: %20 etrafında salınan 30 marklık seride 1 geçiş (düz eşik aynı seride 29 kez açılıp kapanıyor) |
| Halt hâlâ ALIM engelliyor | ⚠️ Gerçek veride izole hesaplarda **0** sinyal engellendi — merdiven yeterli oldu, ama HALT'ın frenleme gücü ölçülmedi |
| Maks. DD bugünkünden kötü değil | ⚠️ Karışık: gerçek veride en kötü **hesap** DD'si iyileşti (-23.6% → -19.7%), **portföy** DD'si 1.31 puan kötüleşti |
| Legacy yolu bozulmadı | ✅ Sentetik veride 1200 günlük equity eğrisi `origin/main` ile birebir aynı (122 işlem, 4657 red, 761 halt günü) |
| Gerçek veriyle doğrulanmış | ⚠️ Merdiven evet; HALT / ağ / taban **hayır** |

---

## 7) Sıradaki adım

**Kriz dönemi koşusu (planlandı, henüz yapılmadı).** Bugünkü pencere HALT'ı
hiç tetiklemedi, yani mekanizmanın asıl koruma katmanı gerçek veride
sınanmadan duruyor. Yapılacak: 2020 çöküşünü içeren daha uzun bir pencere
(8–10 yıl) ya da daha oynak bir sembol evreniyle bir koşu daha — HALT, 14
günlük ağ ve taban gerçekten yürüsün.

Ondan sonra canlıya geçiş ayrıca değerlendirilecek. Geçiş yapılırsa gereken
diff küçük: `scripts/run_portfolio.py`'a `policy=DEFAULT_HALT_POLICY` ve günlük
mark'ta `update_halt_state()`, `scripts/daily_report.py`'a durum raporlaması.

### Öneri (kriz koşusundan sonra yeniden değerlendirilmek üzere)

1. **Kademeli merdiven alınmalı.** Gerçek veride neredeyse her eksende
   legacy'yi yeniyor; tek kötüleşen metrik 1.31 puan portföy DD'si, buna
   karşılık 18.5 puan getiri ve tamamen çözülmüş kilitlenme.
2. **Taban %30 kalsın.** Bağlamadığında maliyeti tam olarak sıfır — kanıtı
   elimizde: gerçek veride iki kol byte-byte aynı sonuç verdi. Yalnızca
   felaket senaryosunda devreye giren sigorta. Ama sentetikte portföy
   kilitlenmesini 0/8'den 2/8'e çıkardığı unutulmamalı (bulgu C).
3. **Koşullu ağ kapalı kalsın** (bulgu D).
4. **"Güvenlik ağı" adı gözden geçirilmeli** (bulgu E) — mekanizma "14 gün
   sonra kalıcı %25 kapasite", nadir bir kaçış kapısı değil.
