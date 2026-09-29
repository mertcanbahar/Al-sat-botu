from datetime import timedelta

from intraday.hesap import (
    degisim_gecti,
    degisim_pct,
    fiyat_dilimi,
    goreli_hacim,
    kumulatif_hacim_profili,
    ortalama_profil,
    split_carpani,
    spread_pct,
)
from intraday.zaman import seans_olustur


def _bar(seans, dk, v, c=5.0):
    return {"t": seans.acilis + timedelta(minutes=dk), "o": c, "h": c, "l": c, "c": c, "v": v}


def test_kumulatif_profil_bosluklu_ve_seans_disi():
    s = seans_olustur("2026-03-09", "09:30", "16:00")
    barlar = [
        _bar(s, -5, 999),  # pre-market: sayılmaz
        _bar(s, 0, 100),
        _bar(s, 3, 50),  # 1-2. dakikada bar yok (IEX'te olağan)
        _bar(s, 390, 999),  # 16:00: sayılmaz
    ]
    p = kumulatif_hacim_profili(barlar, s)
    assert len(p) == 390
    assert p[0] == 100 and p[1] == 100 and p[2] == 100 and p[3] == 150
    assert p[-1] == 150


def test_kumulatif_profil_split_carpani():
    s = seans_olustur("2026-03-09", "09:30", "16:00")
    p = kumulatif_hacim_profili([_bar(s, 0, 1000)], s, carpan=0.1)
    assert p[0] == 100


def test_goreli_hacim_ayni_saate_gore():
    """Sabah hacmi yoğun geçmiş günler: 10:00'da tüm günle değil 10:00'a kadarkiyle kıyasla."""
    s = seans_olustur("2026-03-09", "09:30", "16:00")
    # geçmiş gün: ilk 30 dk'da 300k, gün boyu toplam 1M
    gecmis = [_bar(s, k, 10_000) for k in range(30)] + [_bar(s, 30 + k, 2_000) for k in range(350)]
    taban = ortalama_profil([kumulatif_hacim_profili(gecmis, s)] * 20, s.dakika_sayisi)
    assert taban[29] == 300_000
    assert abs(taban[-1] - 1_000_000) < 1e-6
    # bugün 10:00'a kadar 600k
    rv = goreli_hacim(600_000, taban[29])
    assert rv == 2.0
    # yanlış yöntem (tüm gün ortalaması) 0.6 verirdi -> filtreden geçemezdi
    assert goreli_hacim(600_000, taban[-1]) < 1.0


def test_ortalama_profil_yarim_gun():
    tam = [1.0] * 390
    yarim = [3.0] * 210
    ort = ortalama_profil([tam, yarim], 390)
    assert ort[0] == 2.0
    assert ort[209] == 2.0
    assert ort[210] == 1.0  # yarım gün 13:00 sonrasına katkı vermez


def test_goreli_hacim_taban_yok():
    assert goreli_hacim(100, None) is None
    assert goreli_hacim(100, 0) is None


def test_spread():
    assert abs(spread_pct(4.99, 5.01) - 0.4) < 1e-9
    assert spread_pct(0, 5.01) is None  # tek taraflı
    assert spread_pct(5.0, 0) is None
    assert spread_pct(5.02, 5.00) is None  # ters (crossed)
    assert spread_pct(None, 5.0) is None
    assert spread_pct(5.0, 5.0) == 0.0


def test_degisim():
    assert abs(degisim_pct(5.15, 5.0) - 3.0) < 1e-9
    assert degisim_pct(5.0, 0) is None
    assert degisim_gecti(3.0, 3.0, "yukari")
    assert not degisim_gecti(-4.0, 3.0, "yukari")
    assert degisim_gecti(-4.0, 3.0, "iki_yonlu")
    assert not degisim_gecti(None, 3.0, "yukari")


def test_split_carpani_ters_split():
    # 1:10 ters split öncesi gün: ham 1.0, düzeltilmiş 10.0
    f_eski = split_carpani(1.0, 10.0)
    f_yeni = split_carpani(5.0, 5.0)
    assert f_eski == 0.1 and f_yeni == 1.0
    assert 1000 * f_eski / f_yeni == 100  # hacim yeni hisse cinsine
    assert split_carpani(0, 1) is None


def test_fiyat_dilimi():
    d = [2, 4, 6, 8, 10]
    assert fiyat_dilimi(2.0, d) == "2-4"
    assert fiyat_dilimi(3.99, d) == "2-4"
    assert fiyat_dilimi(4.0, d) == "4-6"
    assert fiyat_dilimi(10.0, d) == "8-10"
    assert fiyat_dilimi(10.01, d) is None
    assert fiyat_dilimi(1.99, d) is None
