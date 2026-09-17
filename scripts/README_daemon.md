# Telegram kontrol daemon'ı (Termux, telefon)

`.github/workflows/telegram-control.yml` her 5 dakikada bir kısa-poll yapıyor
-- her zaman çalışır ama Telegram'ın `answerCallbackQuery`'si birkaç saniye
içinde cevap beklediği için buton üzerindeki yükleniyor ikonu her zaman
takılı kalır (eylem yine de doğru uygulanır, sadece görsel gecikme).
`telegram_control_daemon.py`, telefonda gerçek zamanlı geri bildirim için
buna EK bir seçenek -- cron job'un yerine geçmiyor, GitHub Actions telefon
kapalıyken/uygulama kapalıyken güvenilir yedek olarak çalışmaya devam eder.

## Başlatma

```bash
cd ~/Al-sat-botu
export TELEGRAM_TOKEN=...       # aynı .env / secret değerleri
export TELEGRAM_CHAT_ID=...
export TWELVEDATA_API_KEY=...
mkdir -p logs                   # *.log zaten .gitignore'da, repoya girmez
nohup python3 scripts/telegram_control_daemon.py > logs/daemon.log 2>&1 &
```

Telefon kilitlenince Termux'un arka plan işlemini öldürmemesi için
(opsiyonel): `pkg install termux-api`, sonra `termux-wake-lock`.

Durdurmak için: `pkill -f telegram_control_daemon.py`

## Not

Bu süreç `data/portfolio.json`'ı yalnızca **yerelde** günceller, commit/push
YAPMAZ -- paylaşılan state dosyasına iki ayrı otomatik yazıcı (CI + telefon)
eklemek yerine, GitHub Actions job'u bunu kendi kontrollü rebase/retry
mantığıyla üstlenir. Telefondaki aksiyonun GitHub'a hemen yansımasını
istiyorsan `git add data/portfolio.json data/telegram_control_offset.json &&
git commit && git push` kendin çalıştır.
