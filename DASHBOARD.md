# Kontrol Paneli — Teknik Spec

Tek dosyalık statik panel. `docs/index.html`. Bağımlılık yok, kütüphane yok,
saf HTML + CSS + vanilla JS. GitHub Pages ile yayınlanır.

## Veri kaynağı

Panel aynı repodaki iki dosyayı `fetch` ile okur:

- `../data/portfolio.json` — nakit, açık pozisyonlar, kapanmış işlemler,
  başlangıç sermayesi, tepe değer
- `../data/signals.jsonl` — her satır bir sinyal kaydı (sembol, karar, fiyat,
  tarih, tetikleyen kural, indikatör değerleri)

Ayrıca `alsatbotu/config.py` içindeki WATCHLIST ve kategori haritasının bir
kopyası `docs/watchlist.json` olarak üretilsin (workflow adımı), böylece panel
sembol listesini ve kategorileri bilir.

**Veri yoksa panel çökmez.** Her bölüm boş durumda "veri yok" gösterir.
Sayılar `—` olur, renkler nötr kalır.

## Görünüm

Koyu tema, siyah zemin (`#000`), altın vurgu (`#f5c34b`), monospace yazı tipi.

| Rol | Renk |
|---|---|
| Vurgu / başlık | `#f5c34b` |
| Pozitif / AL | `#00e57a` |
| Negatif / SAT | `#ff4d4d` |
| Uyarı / veri sorunu | `#ffb020` |
| Nötr metin | `#7c7566` |
| Ana metin | `#e6e2d5` |
| Çizgi / kenarlık | `#1f1a0a`, `#2b2007` |

## Düzen — iki mod, tek sayfa

CSS media query ile ekran genişliğine göre değişir. Ayrı sayfa yok.

### Dikey (genişlik < 700px)

Tek sütun, yukarıdan aşağı:

1. **Üst şerit** — logo, "AL/SAT ZEKA SISTEMI", canlı noktası, son
   çalıştırma saati
2. **Sekmeler** — Borsa / Forex / Kripto. Şu an sadece Borsa dolu; diğer
   ikisi tıklanınca "bu varlık sınıfı henüz aktif değil" yazsın
3. **Fiyat ızgarası** — 3 sütunlu, her hücre: sembol, son fiyat, günlük yüzde
4. **Orta blok** — üç parça yan yana:
   - Sol dar sütun: sektör trendleri (mini çizgi + yüzde)
   - Orta: karar çekirdeği (aşağıda anlatılıyor)
   - Sağ dar sütun: sinyal motoru (AL/SAT rozeti + kural çubukları)
5. **Grafik bloğu** — solda seçili sembolün mum grafiği, sağda teknik
   göstergeler listesi (RSI, EMA20, EMA50, ATR, stop, hacim oranı)
6. **Sektör sütunları** — 3 sütun: teknoloji / finans-enerji / tüketim
7. **Son sinyaller + portföy halkası** — yan yana
8. **Alt metrik şeridi** — 5 hücre: pozisyon, K/Z, risk, isabet, sinyal sayısı

### Yatay (genişlik ≥ 700px)

Üç sütunlu geniş düzen:

- **Sol sütun (~24%)** — piyasa genel bakış tablosu, altında sektör
  performans çubukları
- **Orta sütun (~50%)** — karar çekirdeği, sağında mum grafiği + hacim
  çubukları
- **Sağ sütun (~26%)** — sinyal motoru, altında karar ısı haritası (5×2
  ızgara, tüm semboller)
- **Alt şerit** — 5 panel: portföy, risk monitörü, aktif pozisyonlar, son
  sinyaller, sistem durumu
- **En alt** — özet satırı: isabet, işlem sayısı, nakit oranı, kaynak, son
  güncelleme

## Karar çekirdeği

Ortadaki altın küre. Dekoratif değil, veriye bağlı:

- SVG ile çizilir: iç içe elipsler (küre teli) + düğüm noktaları + düğümler
  arası çizgiler
- **Düğüm sayısı = WATCHLIST uzunluğu.** Sembol eklenirse düğüm eklenir
- **Düğüm rengi = o sembolün son kararı:** AL yeşil, SAT kırmızı, BEKLE
  soluk altın, veri hatası turuncu
- **Düğüm boyutu = açık pozisyon varsa büyük, yoksa küçük**
- Düğümler küre üzerinde eşit aralıkla dağıtılır (açı = index / toplam × 360)
- Merkezde "AI / KARAR MOTORU" yazısı
- Küre teli `prefers-reduced-motion: no-preference` altında yavaş nabız
  animasyonu (opacity 0.5 ↔ 1, 3 saniye). Başka animasyon yok

## Sinyal motoru paneli

En son AL veya SAT sinyalini gösterir:

- Büyük rozet: AL (yeşil) / SAT (kırmızı) / BEKLE (gri)
- Kaç kuralın sağlandığı: "3/3 kural"
- Dört çubuk, sinyalin kaydedilmiş indikatör değerlerinden hesaplanır:
  - Trend — EMA20/EMA50 farkının yüzdesi
  - Volatilite — ATR / fiyat oranı
  - Hacim — son hacim / 20 günlük ortalama
  - Risk/Ödül — (giriş − stop) mesafesine göre

Sinyal yoksa panel "sinyal bekleniyor" gösterir.

## Karar ısı haritası

Tüm WATCHLIST sembolleri için ızgara. Her hücre:
- Sembol adı
- Arka plan rengi = son karar (yeşil AL / kırmızı SAT / koyu BEKLE /
  turuncu veri hatası)
- Hücreye tıklanınca o sembolün detayları grafik bloğunda açılır

## Sistem durumu paneli

`data/health.json` dosyasından okur. Bu dosya yoksa panel bu bölümü
"izleme yok" olarak gösterir.

Sağlık dosyası şu yapıda olsun ve `run_portfolio.py` her çalıştırmada yazsın:

```json
{
  "timestamp": "2026-09-06T22:00:00Z",
  "modules": [
    {"name": "twelvedata", "status": "ok", "detail": "10/10 sembol"},
    {"name": "indikator", "status": "ok", "detail": "10 sembol"},
    {"name": "hacim", "status": "warn", "code": "W118", "detail": "7/10"},
    {"name": "kural", "status": "ok", "detail": "3 sinyal"},
    {"name": "portfoy", "status": "ok", "detail": "2 pozisyon"},
    {"name": "telegram", "status": "ok", "detail": "gonderildi"}
  ]
}
```

Panelde her modül bir satır: nokta (yeşil ok / turuncu warn / kırmızı error),
modül adı, detay. Hata varsa kodu da yazılır.

## Portföy eğrisi

`portfolio.json` içindeki geçmiş değer kayıtlarından çizilir. Böyle bir
geçmiş tutulmuyorsa, `run_portfolio.py` her çalıştırmada portföy değerini
`data/equity.jsonl` dosyasına tarih + değer olarak eklesin.

Grafik: basit SVG polyline, ızgara çizgileri, son noktada yanıp sönen daire.
Canvas veya kütüphane kullanma.

## Yayınlama

`.github/workflows/pages.yml`:
- `main`'e her push'ta çalışır
- `docs/` klasörünü GitHub Pages artifact olarak yükler ve yayınlar
- `permissions: pages: write, id-token: write` gerekli

## Kısıtlar

- Dış kütüphane yok, CDN yok, npm yok
- Tek HTML dosyası — CSS ve JS aynı dosyada
- Tüm sayılar yuvarlanmış gösterilir (yüzdeler 2 basamak, fiyatlar 2 basamak)
- Hiçbir veri uydurulmaz. Dosya okunamazsa "veri yok" yazılır
- Animasyon sadece: küre nabzı ve son nokta yanıp sönmesi. İkisi de
  `prefers-reduced-motion` altında
- Mobilde yatay kaydırma olmayacak
