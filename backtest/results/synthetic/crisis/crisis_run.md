# Kriz dönemi koşusu: 2008 + 2020 çöküşlerinde drawdown halt

Üretim zamanı: 2026-09-07T21:22:26.222928Z

> ⚠️ **SENTETİK KRİZ SENARYOSU — GERÇEK PİYASA VERİSİ DEĞİL.** Bu ortamda `TWELVEDATA_API_KEY` yok ve dış ağ kapalı, yani gerçek 2008/2020 fiyatları çekilemedi. Veri `backtest/crisis_data.py` ile üretildi: ortak bir piyasa faktörü + rejim takvimi, GFC'de ~-55%, COVID'de 23 işlem gününde ~-34% hedefiyle. **Getiri seviyeleri gerçek performans tahmini değildir.** Okunabilir olan: böyle bir çöküşte halt kuralının ne yaptığı ve üç kolun birbirine göre davranışı. Anahtar/ağ olan bir ortamda aynı koşu `--real` ile gerçek veriyle tekrarlanabilir.

Pencere: **2005-03-28 → 2021-12-31** · Tohumlar: 1, 2, 7, 42, 101 · 20 sembol · $100,000 portföy sermayesi. Tablolar tohumlar arası **medyan (min–maks)**.

## 0) Senaryo gerçekten kriz içeriyor mu?

Eşit ağırlıklı (günlük dengelenen) endeks üzerinden ölçülen kriz derinlikleri — halt'ın tetiklenmemesi için bir mazeret kalmadığını göstermek için:

| Tohum | GFC (2008) | COVID (2020) | 17y toplam |
|---|---|---|---|
| 1 | -57.0% | -37.0% | 661% |
| 2 | -64.4% | -38.5% | 979% |
| 7 | -56.3% | -37.0% | 777% |
| 42 | -49.8% | -23.8% | 913% |
| 101 | -56.5% | -34.7% | 725% |

Rejim takvimi:

| Rejim | Başlangıç | Hedef hareket | Günlük oynaklık |
|---|---|---|---|
| Boğa 2005-2007 | 2005-01-03 | +28% | 0.75% |
| GFC çöküşü | 2007-10-10 | -55% | 2.40% |
| GFC toparlanması | 2009-03-10 | +95% | 1.30% |
| 2011 düzeltmesi | 2011-05-02 | -19% | 1.70% |
| Boğa 2011-2015 | 2011-10-04 | +100% | 0.90% |
| 2015-16 düzeltmesi | 2015-05-21 | -14% | 1.50% |
| Boğa 2016-2018 | 2016-02-12 | +60% | 0.80% |
| 2018Q4 düzeltmesi | 2018-09-21 | -20% | 1.80% |
| Boğa 2019 | 2018-12-26 | +45% | 1.00% |
| COVID çöküşü | 2020-02-20 | -34% | 4.20% |
| COVID toparlanması | 2020-03-24 | +110% | 1.60% |

## 1) Portföy geneli (paylaşılan sermaye, tüm risk kısıtları aktif)

| Metrik | legacy %20 | v1 | v1 taban%30 |
|---|---|---|---|
| Toplam getiri | -4.2% (-12.0%–20.2%) | -1.2% (-25.9%–24.6%) | -1.2% (-25.9%–24.6%) |
| CAGR | -0.26% (-0.76%–1.11%) | -0.07% (-1.78%–1.32%) | -0.07% (-1.78%–1.32%) |
| Gerçekleşen maks. DD | -27.0% (-28.5%–-24.7%) | -34.2% (-43.4%–-31.5%) | -34.2% (-43.4%–-31.5%) |
| Sharpe | 0.02 (-0.12–0.17) | 0.03 (-0.22–0.16) | 0.03 (-0.22–0.16) |
| İşlem sayısı | 146 (96–186) | 165 (134–281) | 165 (134–281) |
| İsabet oranı | 42.5% (36.9%–43.8%) | 40.9% (35.8%–44.2%) | 40.9% (35.8%–44.2%) |
| | | | |
| **Halt aktif gün** | 3665 (3533–3859) | 3627 (2931–3803) | 3627 (2931–3803) |
| **Halt aktif gün oranı** | 83.8% (80.8%–88.2%) | 82.9% (67.0%–86.9%) | 82.9% (67.0%–86.9%) |
| En uzun kesintisiz halt (gün) | 3657 (3533–3806) | 3507 (2745–3609) | 3507 (2745–3609) |
| Halt'ın engellediği ALIM sinyali | 19214 (18850–19711) | 19134 (15673–19344) | 19134 (15673–19344) |
| İlk halt tarihi (tohum başına) | 2007-12-14, 2005-11-14, 2008-06-18, 2007-11-29, 2006-10-19 | 2007-12-14, 2005-11-14, 2008-06-18, 2007-11-29, 2006-10-19 | 2007-12-14, 2005-11-14, 2008-06-18, 2007-11-29, 2006-10-19 |
| | | | |
| Geçiş: halt'a giriş | 2 (1–10) | 3 (3–4) | 3 (3–4) |
| Geçiş: toparlanmayla çıkış | 1 (0–9) | 0 (0–1) | 0 (0–1) |
| Geçiş: kısmi reset ile çıkış | 0 | 2 | 2 |
| Geçiş: kalıcı durdurma | 0 | 1 | 1 |
| **Pencere sonunda halt'ta** | 5/5 tohum | 5/5 tohum | 5/5 tohum |
| **Pencere sonunda kalıcı durdurulmuş** | 0/5 tohum | 5/5 tohum | 5/5 tohum |
| Durdurma nedeni | — | `max_resets` | `max_resets` |

## 2) Krizlerin içinde ne oldu

### GFC (2008) — 2007-10-10 → 2009-03-09

| Metrik | legacy %20 | v1 | v1 taban%30 |
|---|---|---|---|
| Halt aktif gün (pencere içinde) | 321 (189–369) | 265 (120–325) | 265 (120–325) |
| Portföy equity düşüşü | -25.1% (-28.1%–0.0%) | -31.8% (-43.1%–-31.2%) | -31.8% (-43.1%–-31.2%) |
| Halt'ın devreye girdiği gün | 2007-12-14, 2007-12-27, 2008-06-18, 2007-11-29, 2007-10-10 | 2007-12-14, 2007-12-27, 2008-06-18, 2007-11-29, 2007-12-04 | 2007-12-14, 2007-12-27, 2008-06-18, 2007-11-29, 2007-12-04 |

### COVID (2020) — 2020-02-20 → 2020-03-23

| Metrik | legacy %20 | v1 | v1 taban%30 |
|---|---|---|---|
| Halt aktif gün (pencere içinde) | 23 | 23 | 23 |
| Portföy equity düşüşü | 0.0% | 0.0% | 0.0% |
| Halt'ın devreye girdiği gün | 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20 | 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20 | 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20, 2020-02-20 |

## 3) İzole hesaplar (20 ayrı tek-sembol hesabı)

Portföy kısıtları paylaşılmadığı için halt'ın kilitleme etkisi burada en net görünür: bir alt hesap halt'a girip zirvesine dönemezse bir daha hiç alım yapamaz.

| Metrik | legacy %20 | v1 | v1 taban%30 |
|---|---|---|---|
| Toplam getiri (20 hesap toplamı) | 47.7% (16.6%–72.6%) | 71.3% (51.8%–82.9%) | 71.3% (51.8%–82.9%) |
| Toplam işlem sayısı | 1346 (1020–1436) | 1812 (1757–1916) | 1812 (1757–1916) |
| Halt'a hiç girmiş hesap | 12.0 (10.0–17.0)/20 | 12.0 (10.0–17.0)/20 | 12.0 (10.0–17.0)/20 |
| **Sonda kilitli kalan hesap** | 10.0 (7.0–15.0)/20 | 1.0 (1.0–2.0)/20 | 1.0 (1.0–2.0)/20 |
| **Kalıcı durdurulan hesap** | 0.0/20 | 1.0 (1.0–2.0)/20 | 1.0 (1.0–2.0)/20 |
| Ortalama halt gün oranı | 28.0% (21.6%–44.5%) | 4.2% (2.0%–5.8%) | 4.2% (2.0%–5.8%) |
| Halt'ın engellediği ALIM sinyali | 6408 (5061–10243) | 836 (304–1080) | 836 (304–1080) |
| Ortalama hesap maks. DD | -19.5% (-20.2%–-19.2%) | -21.7% (-23.1%–-21.1%) | -21.7% (-23.1%–-21.1%) |
| **En kötü hesap maks. DD** | -22.9% (-23.3%–-21.8%) | -32.6% (-37.5%–-31.0%) | -32.6% (-37.5%–-31.0%) |

## 4) Durum makinesi geçiş logları (portföy geneli)

Her kolun ilk tohumundaki portföy hesabının tam geçiş dizisi. `halted` = yeni ALIM durdu, `released` = toparlanmayla kalktı, `reset` = kısmi peak reset'iyle kalktı, `stopped` = kalıcı durdurma.

### legacy %20 (tohum 1) — 3 geçiş

| # | Tarih | Geçiş | Equity | Peak | Drawdown | Ayrıntı |
|---|---|---|---|---|---|---|
| 1 | 2007-12-14 | `halted` | 104,775 | 131,552 | 20.4% | Drawdown eşiği aşıldı; yeni ALIM durduruldu. |
| 2 | 2007-12-17 | `released` | 108,701 | 131,552 | 17.4% | Equity eşiğin üstüne döndü; halt kendiliğinden kalktı. |
| 3 | 2007-12-18 | `halted` | 105,007 | 131,552 | 20.2% | Drawdown eşiği aşıldı; yeni ALIM durduruldu. |

### v1 (tohum 1) — 6 geçiş

| # | Tarih | Geçiş | Equity | Peak | Drawdown | Ayrıntı |
|---|---|---|---|---|---|---|
| 1 | 2007-12-14 | `halted` | 104,775 | 131,552 | 20.4% | Drawdown %20.35 >= %20; yeni ALIM durduruldu. |
| 2 | 2008-03-07 | `reset` | 93,939 | 112,746 | 28.6% | 60 işaretlemedir halt'ta ve açık pozisyon yok. Peak 131552.24 -> 112745.61 çekildi (1/2 reset), halt kalktı. |
| 3 | 2008-04-23 | `halted` | 88,151 | 112,746 | 21.8% | Drawdown %21.81 >= %20; yeni ALIM durduruldu. |
| 4 | 2008-07-16 | `reset` | 79,069 | 95,907 | 29.9% | 60 işaretlemedir halt'ta ve açık pozisyon yok. Peak 112745.61 -> 95907.32 çekildi (2/2 reset), halt kalktı. |
| 5 | 2008-07-24 | `halted` | 75,858 | 95,907 | 20.9% | Drawdown %20.90 >= %20; yeni ALIM durduruldu. |
| 6 | 2008-10-16 | `stopped` | 74,612 | 95,907 | 22.2% | 2 kısmi reset'ten sonra hâlâ halt'ta ve nakitte. Bot kalıcı olarak durduruldu. |

### v1 taban%30 (tohum 1) — 6 geçiş

| # | Tarih | Geçiş | Equity | Peak | Drawdown | Ayrıntı |
|---|---|---|---|---|---|---|
| 1 | 2007-12-14 | `halted` | 104,775 | 131,552 | 20.4% | Drawdown %20.35 >= %20; yeni ALIM durduruldu. |
| 2 | 2008-03-07 | `reset` | 93,939 | 112,746 | 28.6% | 60 işaretlemedir halt'ta ve açık pozisyon yok. Peak 131552.24 -> 112745.61 çekildi (1/2 reset), halt kalktı. |
| 3 | 2008-04-23 | `halted` | 88,151 | 112,746 | 21.8% | Drawdown %21.81 >= %20; yeni ALIM durduruldu. |
| 4 | 2008-07-16 | `reset` | 79,069 | 95,907 | 29.9% | 60 işaretlemedir halt'ta ve açık pozisyon yok. Peak 112745.61 -> 95907.32 çekildi (2/2 reset), halt kalktı. |
| 5 | 2008-07-24 | `halted` | 75,858 | 95,907 | 20.9% | Drawdown %20.90 >= %20; yeni ALIM durduruldu. |
| 6 | 2008-10-16 | `stopped` | 74,612 | 95,907 | 22.2% | 2 kısmi reset'ten sonra hâlâ halt'ta ve nakitte. Bot kalıcı olarak durduruldu. |

Bütün kolların, bütün tohumların ve 20 izole hesabın geçişleri `crisis_transitions.jsonl` dosyasında.

## Nasıl okunmalı

- **Halt aktif gün oranı = 0** ise kural bu krizde bile hiç tetiklenmemiştir; koruma iddiası ölçülmemiş demektir.
- **Pencere sonunda halt'ta / kilitli hesap sayısı yüksek** ise kural bir kez tetiklenip bırakmamıştır: strateji kalıcı olarak durmuştur.
- **Kalıcı durdurma (`stopped`) nedeni** iki v1 kolunu ayıran tek şeydir. Neden `hard_floor` ise taban değeri bağlamıştır ve taban%50 ile taban%30 farklı davranır. Neden `max_resets` ise taban hiç devreye girmemiştir: hesap reset hakkını tüketerek durmuştur, tabanın nerede olduğu sonucu değiştirmez ve iki kol birebir aynı çıkar.
