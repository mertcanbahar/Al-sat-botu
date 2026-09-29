# intraday/ — Gün içi Nasdaq sistemi

Eski günlük sistemden (alsatbotu/, engine/, portfolio/, evaluation/, scripts/,
workflow'lar) bağımsız. Eski koddan yalnızca `notify.telegram` ve stdlib
`logging` kullanılabilir. Eski sisteme dokunulmaz; arşiv tag'i: `v1-gunluk`.

## Aşama 1: veri + tarayıcı (işlem yok, sinyal yok)

```bash
pip install -r intraday/requirements.txt
cp .env.example .env          # anahtarları .env'e yazın (git'e girmez)
python -m intraday evren      # bugünün evreni (günde bir kez; aynı gün tekrar çalışırsa dosyadan okur)
python -m intraday tara       # 6 ay veri indir (önbellekli) + tara + rapor
python -m pytest intraday/tests
```

Çıktılar:
- `backtest/results/intraday/scanner_report.md` — rapor
- `backtest/results/intraday/scanner_hits.csv` — her takılma
- `.cache/intraday/` — parquet/JSON veri (git dışı; ikinci koşuda tekrar indirilmez)

Tüm eşikler: `intraday/config.yaml`.

## Modüller

| Dosya | Görev |
|---|---|
| `ayarlar.py` | config.yaml + .env okuma (anahtarlar loglanmaz) |
| `zaman.py` | UTC iç zaman, ET seans, TR gösterim, yaz/kış saati |
| `alpaca.py` | REST istemcisi: hız sınırı (kayan 60 sn), 429/5xx yeniden deneme, sayfalama |
| `evren.py` | Nasdaq evreni, ETF/warrant/right/unit/preferred eleme |
| `indir.py` | takvim, günlük barlar, kayıpsız ön filtre, yalnızca gereken dakikalık veri |
| `hesap.py` | saf hesaplar: aynı-saat göreli hacim, spread, değişim, split faktörü |
| `tarayici.py` | bar-bar (akış) tarayıcı — Aşama 3'te canlı akış da aynı sınıfı kullanacak |
| `rapor.py` | markdown rapor + CSV |
