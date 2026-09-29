from datetime import date, datetime, timedelta

from intraday.zaman import (
    UTC,
    dakika_sonu,
    seans_olustur,
    takvimden_seanslar,
    tr_saat,
    utc_parse,
)


def test_normal_seans_yaz_saati():
    s = seans_olustur("2026-07-15", "09:30", "16:00")
    assert s.acilis == datetime(2026, 7, 15, 13, 30, tzinfo=UTC)  # EDT = UTC-4
    assert s.kapanis == datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
    assert s.dakika_sayisi == 390
    assert not s.yarim_gun


def test_yaz_saati_gecisi_mart_2026():
    # ABD yaz saati 8 Mart 2026 Pazar başlar.
    cuma = seans_olustur("2026-03-06", "09:30", "16:00")
    pazartesi = seans_olustur("2026-03-09", "09:30", "16:00")
    assert cuma.acilis == datetime(2026, 3, 6, 14, 30, tzinfo=UTC)  # EST = UTC-5
    assert pazartesi.acilis == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)  # EDT = UTC-4
    assert cuma.dakika_sayisi == pazartesi.dakika_sayisi == 390
    # Türkiye UTC+3 sabit: TR açılış saati bir saat kayar
    assert tr_saat(cuma.acilis).strftime("%H:%M") == "17:30"
    assert tr_saat(pazartesi.acilis).strftime("%H:%M") == "16:30"


def test_kis_saati_gecisi_kasim_2026():
    # ABD yaz saati 1 Kasım 2026 Pazar biter.
    cuma = seans_olustur("2026-10-30", "09:30", "16:00")
    pazartesi = seans_olustur("2026-11-02", "09:30", "16:00")
    assert cuma.acilis == datetime(2026, 10, 30, 13, 30, tzinfo=UTC)
    assert pazartesi.acilis == datetime(2026, 11, 2, 14, 30, tzinfo=UTC)
    assert pazartesi.kapanis == datetime(2026, 11, 2, 21, 0, tzinfo=UTC)


def test_yarim_gun():
    # Şükran Günü ertesi: 13:00 kapanış
    s = seans_olustur("2026-11-27", "09:30", "13:00")
    assert s.kapanis == datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    assert s.dakika_sayisi == 210
    assert s.yarim_gun


def test_seans_icerik_ve_ofset():
    s = seans_olustur("2026-03-09", "09:30", "16:00")
    assert not s.iceriyor(s.acilis - timedelta(minutes=1))  # pre-market
    assert s.iceriyor(s.acilis)
    assert s.iceriyor(s.kapanis - timedelta(minutes=1))
    assert not s.iceriyor(s.kapanis)  # 16:00 barı seans dışı
    assert s.acilistan_dakika(s.acilis + timedelta(minutes=30)) == 30


def test_takvim_sirali_ve_alpaca_formati():
    takvim = [
        {"date": "2026-03-09", "open": "09:30", "close": "16:00"},
        {"date": "2026-03-06", "open": "0930", "close": "1600"},
    ]
    s = takvimden_seanslar(takvim)
    assert [x.gun for x in s] == [date(2026, 3, 6), date(2026, 3, 9)]


def test_utc_parse_nanosaniye():
    t = utc_parse("2026-03-09T13:30:00.123456789Z")
    assert t == datetime(2026, 3, 9, 13, 30, 0, 123456, tzinfo=UTC)
    assert utc_parse("2026-03-09T09:30:00-04:00") == datetime(2026, 3, 9, 13, 30, tzinfo=UTC)


def test_karar_ani_bar_kapanisi():
    t = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    assert dakika_sonu(t) == datetime(2026, 3, 9, 13, 31, tzinfo=UTC)
