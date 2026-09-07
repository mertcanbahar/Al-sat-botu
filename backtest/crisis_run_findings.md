# Kriz dönemi koşusu: halt sonunda gerçekten tetiklendi

> ## 🔴 Kısa cevap
>
> **Halt tetiklendi — hem de fazlasıyla.** 2008 ve 2020 çöküşlerini içeren
> 17 yıllık pencerede portföy hesabı günlerin **%83'ünde** halt altında
> kaldı ve **üç kolun hiçbiri pencere sonunda çalışır durumda değildi.**
>
> - **legacy %20** (canlı davranış): 2007 sonunda halt'a giriyor ve
>   **14 yıl boyunca bir daha çıkmıyor.** 5 tohumun 5'inde de pencere
>   sonunda hâlâ halt'ta. Bu bir koruma değil, kalıcı kapanma.
> - **v1** (histerezisli durum makinesi): kilidi geçici olarak açıyor
>   (2 kısmi reset), ama **5 tohumun 5'inde de 2008 içinde kalıcı olarak
>   duruyor** — hepsi `max_resets` nedeniyle, 2008 Ekim'inden önce.
> - **v1 taban%30**: v1 ile **bit-bit aynı** çıktı. Sert taban hiçbir
>   tohumda, hiçbir hesapta devreye girmedi.
>
> Önceki sakin-veri süpürmesinin (`halt_threshold_findings.md`) cevaplayamadığı
> soru buydu; artık ölçülmüş durumda.

Ham çıktılar: [`results/synthetic/crisis/`](results/synthetic/crisis/) —
`crisis_run.md` (tam tablo + geçiş logları), `crisis_run.json`,
`crisis_transitions.jsonl` (654 geçiş: 3 kol × 5 tohum × portföy + 20 izole hesap).

---

## ⚠️ Verinin niteliği

Bu ortamda `TWELVEDATA_API_KEY` yok ve dış ağ kapalı — gerçek 2008/2020
fiyatları çekilemedi. Veri `backtest/crisis_data.py` ile üretildi: **ortak
bir piyasa faktörü** (yani bütün semboller aynı anda düşüyor, krizde
çeşitlendirme işe yaramıyor) artı tarihli bir rejim takvimi.

Bu, önceki süpürmelerdeki üreteçten kasıtlı olarak farklı. Orada her sembol
*bağımsız* bir rastgele yürüyüştü; 20 bağımsız yürüyüş aynı anda çökmediği
için portföy düzeyinde halt neredeyse hiç tetiklenmiyordu. Ölçülen şey
kuralın davranışı değil, verinin sakinliğiydi.

Üretilen senaryonun gerçekten kriz içerdiği ölçüldü (eşit ağırlıklı,
günlük dengelenen endeks üzerinden):

| Tohum | GFC (2008) | COVID (2020) | 17 yıl toplam |
|---|---|---|---|
| 1 | -57.0% | -37.0% | +661% |
| 2 | -64.4% | -38.5% | +979% |
| 7 | -56.3% | -37.0% | +777% |
| 42 | -49.8% | -23.8% | +913% |
| 101 | -56.5% | -34.7% | +725% |

Kriz derinlikleri rejim başına hedefe sabitlendiği için her tohumda
karşılaştırılabilir; değişen yol, sabit olan çöküşün büyüklüğü.

**Getiri seviyeleri gerçek performans tahmini değildir.** Okunabilir olan:
böyle bir çöküşte halt kuralının ne yaptığı ve kolların birbirine göre
davranışı. Gerçek veriyle aynı koşu: Actions → **Manual crisis-period halt
run** (`manual-crisis-run.yml`, workflow main'e girdikten sonra).

---

## Bulgu A: legacy %20 krizde kalıcı olarak kapanıyor

| Metrik | legacy %20 | v1 | v1 taban%30 |
|---|---|---|---|
| Halt aktif gün oranı | **83.8%** (80.8–88.2) | 82.9% (67.0–86.9) | 82.9% (67.0–86.9) |
| En uzun kesintisiz halt | **3657 gün** (3533–3806) | 3507 (2745–3609) | 3507 (2745–3609) |
| Pencere sonunda halt'ta | **5/5 tohum** | 5/5 tohum | 5/5 tohum |
| Engellenen ALIM sinyali | 19214 | 19134 | 19134 |

Tohum 1'in tam geçiş dizisi üç satır:

```
2007-12-14  halted    eq=104,775  peak=131,552  dd=20.4%
2007-12-17  released  eq=108,701  peak=131,552  dd=17.4%
2007-12-18  halted    eq=105,007  peak=131,552  dd=20.2%
```

Üçüncü satırdan sonra **hiçbir şey yok**: 2007 Aralık'ından 2021 sonuna
kadar 3664 işlem günü kesintisiz halt (toplam 4375 günün 3665'i). Sebep tam olarak
`halt_threshold_findings.md`'nin öngördüğü kısır döngü: equity'yi zirveye
taşıyacak tek mekanizma alımdır, halt alımı durdurur, hesap nakde döner ve
equity donar — zirve ise düşmez. Bot 2009 toparlanmasını, 2011-2019 boğasını
ve COVID sonrası ralliyi bütünüyle kaçırıyor.

Bir önceki raporda bu "izole hesaplarda 6/20 kilitlenme" olarak görünmüştü;
kriz verisinde **portföyün tamamı** kilitleniyor.

## Bulgu B: v1 kilidi açıyor ama krizin içinde kalıcı olarak duruyor

v1'in kısmi peak reset'i gerçekten çalışıyor — ve tam olarak tasarlandığı
gibi ikinci reset'ten sonra pes ediyor. Tohum 1, altı geçişin tamamı:

```
2007-12-14  halted   eq=104,775  peak=131,552  dd=20.4%
2008-03-07  reset    eq= 93,939  peak 131,552 -> 112,746   (1/2 reset)
2008-04-23  halted   eq= 88,151  peak=112,746  dd=21.8%
2008-07-16  reset    eq= 79,069  peak 112,746 ->  95,907   (2/2 reset)
2008-07-24  halted   eq= 75,858  peak= 95,907  dd=20.9%
2008-10-16  stopped  eq= 74,612  peak= 95,907  dd=22.2%   -> max_resets
```

Beş tohumun beşinde de aynı desen: halt → reset → halt → reset → halt →
**kalıcı durdurma, hepsi 2008 içinde.** Yani v1, legacy'nin sessiz
kilitlenmesini "insan onayı bekleyen açık bir durdurma"ya çeviriyor. Kâğıt
üzerinde daha dürüst bir başarısızlık, ama sonuç aynı: 2008'den sonra bot
çalışmıyor.

Karşılığında ölçülen fark:

| Metrik | legacy %20 | v1 |
|---|---|---|
| İzole: sonda kilitli hesap | **10/20** (7–15) | **1/20** (1–2) |
| İzole: ortalama halt gün oranı | 28.0% | **4.2%** |
| İzole: toplam getiri (20 hesap) | 47.7% | **71.3%** |
| İzole: en kötü hesap DD | **-22.9%** | -32.6% |
| Portföy: gerçekleşen maks. DD | **-27.0%** | -34.2% |

İzole hesap düzeyinde v1 açık ara daha iyi (kilitlenme 10'dan 1'e, getiri
47.7%'den 71.3%'e). Portföy düzeyinde ise **daha derin drawdown** karşılığında
neredeyse aynı getiri (-4.2% vs -1.2% medyan). Bu, önceki raporun D
bulgusunun kriz verisindeki tekrarı: kilidi açmak drawdown'ı kötüleştiriyor.

## Bulgu C: sert taban hiç devreye girmedi — taban%30 ölçülmemiş bir parametre

**v1 taban%30, v1 ile bit-bit aynı sonuç verdi** (5 tohumun 5'inde hem
portföy hem 20 izole hesap için JSON düzeyinde birebir eşit).

Nedeni ölçüldü: **bütün kalıcı durdurmalar `max_resets` kaynaklı, hiçbiri
`hard_floor` değil** — portföyde 5/5 tohum, izole hesaplarda 6/6 durdurma.
Durdurma anındaki equity 74,060–124,632 aralığında; taban%50 eşiği 50,000,
taban%30 eşiği 30,000. Hesap iki eşiğin de çok üstünde dururken reset
hakkını tüketiyor.

Bunun yapısal bir sebebi var: halt'a giren hesap hızla nakde dönüyor, o
noktada equity donuyor ve **daha fazla düşemiyor.** Sert taban ancak
pozisyondayken hızla erimekle tetiklenebilir; halt zaten pozisyon almayı
engellediği için taban ulaşılamaz hale geliyor. Yani `HALT_HARD_FLOOR_PCT`
bu tasarımda büyük ölçüde ölü bir parametre — tıpkı önceki raporun
"toparlanmayla çıkış hiç çalışmıyor" bulgusundaki gibi.

**Sonuç: "taban %30 olsun mu" sorusunun bu veride ölçülebilir bir cevabı
yok.** Ayırt edici parametre taban değil, `MAX_HALT_RESETS`.

## Bulgu D: COVID'de halt equity'yi korumadı, çünkü koruyacak bir şey yoktu

COVID penceresinde (2020-02-20 → 2020-03-23) üç kolun üçünde de halt
23 günün 23'ünde aktif ve portföy equity düşüşü **%0.0**. Bu bir başarı
değil: hesap zaten 2008'den beri halt'ta (legacy) ya da durdurulmuş (v1),
yani nakitte. Piyasa %34 düşerken hesabın hiç etkilenmemesinin sebebi
korunmuş olması değil, **12 yıldır işlem yapmıyor olması.**

---

## Kabul kriterleri: ne tuttu, ne tutmadı

| Kriter | Sonuç |
|---|---|
| Halt kriz verisinde tetikleniyor | ✅ üç kolda da, günlerin %83'ünde |
| Geçiş logları üretiliyor | ✅ 654 geçiş, `crisis_transitions.jsonl` |
| legacy %20 krizden sağ çıkıyor | ❌ 5/5 tohumda 14 yıl kilitli |
| v1 krizden sağ çıkıyor | ❌ 5/5 tohumda 2008 içinde kalıcı durdurma |
| taban%30, taban%50'den farklı davranıyor | ❌ bit-bit aynı; taban hiç bağlamadı |
| Gerçek veriyle doğrulanmış | ❌ ortamda API anahtarı/ağ yok — `manual-crisis-run.yml` ile koşulmalı |

## Öneri

1. **Gerçek veriyle bir kez koşulmalı.** Sentetik senaryo kriz *biçimini*
   doğru veriyor ama seviyeleri değil; `manual-crisis-run.yml` main'e
   girdikten sonra Actions'tan tetiklenebilir.
2. **Asıl sorun eşik ya da taban değil, peak'in düşememesi.** Üç kol da
   aynı kısır döngüde takılıyor; v1 sadece takılmayı görünür kılıyor.
   Ölçülmeye değer bir sonraki değişiklik `MAX_HALT_RESETS` (2 → sınırsız
   ya da zamana bağlı yenilenen bir bütçe) ya da peak'i takvimle
   yaşlandırmak olur — ikisi de bu koşuda ölçülmedi.
3. **`HALT_HARD_FLOOR_PCT` ölü parametre olarak işaretlenmeli.** Halt
   pozisyon almayı engellediği için taban yapısal olarak ulaşılamıyor;
   değerini tartışmak ölçülebilir bir şey değiştirmiyor.

**Bu koşu bir karar önerisi değildir.** Canlı davranış değişmedi:
`engine/risk.py` hâlâ sabit %20 mandalı, `6254c93`'teki geri alma kararı
yürürlükte. v1 yalnızca `backtest/halt_policy.py` içinde, yalnızca
karşılaştırma kolu olarak yaşıyor.
