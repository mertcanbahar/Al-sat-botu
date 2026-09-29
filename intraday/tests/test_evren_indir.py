from datetime import date, datetime, timedelta

from intraday.ayarlar import config_yukle
from intraday.evren import eleme_nedeni, evren_olustur
from intraday.indir import ay_once, on_filtre, split_faktorleri, taban_gunleri
from intraday.zaman import UTC, seans_olustur

CFG = config_yukle()


def _v(sembol, isim, **kw):
    d = {"symbol": sembol, "name": isim, "exchange": "NASDAQ", "status": "active", "tradable": True}
    d.update(kw)
    return d


def test_evren_kurallari():
    e = CFG["evren"]
    assert eleme_nedeni(_v("AAPL", "Apple Inc. Common Stock"), "NASDAQ", e) is None
    assert eleme_nedeni(_v("QQQ", "Invesco QQQ Trust, Series 1 ETF"), "NASDAQ", e) == "isim_etf"
    assert eleme_nedeni(_v("TQQQ", "ProShares UltraPro QQQ"), "NASDAQ", e) == "isim_etf"
    assert eleme_nedeni(_v("ABCDW", "Abcd Corp Warrant"), "NASDAQ", e) == "isim_warrant"
    assert eleme_nedeni(_v("ABCDW", "Abcd Corp"), "NASDAQ", e) == "besinci_harf_warrant"
    assert eleme_nedeni(_v("ABCDU", "Abcd Acquisition Corp Unit"), "NASDAQ", e) == "isim_unit"
    assert eleme_nedeni(_v("ABCDR", "Abcd Acquisition Corp Right"), "NASDAQ", e) == "isim_right"
    assert eleme_nedeni(_v("ABCDP", "Abcd 8.00% Series A Cumulative Preferred Stock"), "NASDAQ", e) == "isim_preferred"
    assert eleme_nedeni(_v("ABC.WS", "Abc"), "NASDAQ", e) == "sembol_ozel_karakter"
    assert eleme_nedeni(_v("XYZ", "Xyz", tradable=False), "NASDAQ", e) == "islem_gormez"
    assert eleme_nedeni(_v("XYZ", "Xyz", exchange="NYSE"), "NASDAQ", e) == "borsa_farkli"
    # 5 harfli ama ek anlamı taşımayan sınıf hissesi kalır
    assert eleme_nedeni(_v("GOOGL", "Alphabet Inc. Class A Common Stock"), "NASDAQ", e) is None
    # "United" kelimesi unit kuralına takılmamalı
    assert eleme_nedeni(_v("UAL", "United Airlines Holdings"), "NASDAQ", e) is None


def test_evren_olustur_sayilar():
    ev = evren_olustur(
        [_v("AAPL", "Apple"), _v("ABCDW", "Abcd Warrant"), _v("SPYX", "Some ETF")],
        "NASDAQ", CFG["evren"], date(2026, 9, 29),
    )
    assert ev.kalan == ["AAPL"]
    assert ev.sayilar() == {"isim_etf": 1, "isim_warrant": 1}


def test_ay_once():
    assert ay_once(date(2026, 9, 28), 6) == date(2026, 3, 28)
    assert ay_once(date(2026, 8, 31), 6) == date(2026, 2, 28)
    assert ay_once(date(2026, 3, 15), 6) == date(2025, 9, 15)


def _gunluk_seri(seanslar, c=5.0, v=2_000_000, h=None, l=None):
    return {
        s.gun: {"t": datetime.combine(s.gun, datetime.min.time(), tzinfo=UTC),
                "o": c, "h": h or c, "l": l or c, "c": c, "v": v}
        for s in seanslar
    }


def _seanslar(n, bas=date(2026, 1, 5)):
    out, g = [], bas
    while len(out) < n:
        if g.weekday() < 5:
            out.append(seans_olustur(g, "09:30", "16:00"))
        g += timedelta(days=1)
    return out


def test_on_filtre_huni():
    tum = _seanslar(25)
    D = tum[-1]
    seri = {
        "ADAY": _gunluk_seri(tum),
        "DUSUK": _gunluk_seri(tum, v=100_000),
        "PAHALI": _gunluk_seri(tum, c=50.0),
        "SAKIN": _gunluk_seri(tum),
    }
    seri["ADAY"][D.gun] = {**seri["ADAY"][D.gun], "h": 5.3}  # +%6
    seri["PAHALI"][D.gun] = {**seri["PAHALI"][D.gun], "h": 55.0, "l": 49.0}
    fak = split_faktorleri(seri, seri)
    on = on_filtre(sorted(seri), [D], tum, seri, fak, CFG["tarayici"])
    assert on.adaylar == {D.gun: {"ADAY"}}
    assert on.huni["ort_hacim"] == 1
    assert on.huni["fiyat_araligi"] == 1
    assert on.huni["degisim"] == 1
    assert on.onceki_kapanis[("ADAY", D.gun)] == 5.0


def test_on_filtre_ters_split_hacim_ve_kapanis_duzeltmesi():
    tum = _seanslar(25)
    D = tum[-1]
    # D gününe kadar 1:10 ters split öncesi: ham fiyat 0.5, ham hacim 20M
    ham = _gunluk_seri(tum[:-1], c=0.5, v=20_000_000)
    ham[D.gun] = {"t": None, "o": 5.0, "h": 5.3, "l": 5.0, "c": 5.2, "v": 3_000_000}
    duz = {g: {**b, "c": b["c"] * 10} for g, b in ham.items() if g != D.gun}
    duz[D.gun] = ham[D.gun]
    fak = split_faktorleri({"X": ham}, {"X": duz})
    on = on_filtre(["X"], [D], tum, {"X": ham}, fak, CFG["tarayici"])
    assert ("X", D.gun) in on.onceki_kapanis
    assert abs(on.onceki_kapanis[("X", D.gun)] - 5.0) < 1e-9  # 0.5 -> yeni hisse cinsinden 5.0
    assert abs(on.ort_hacim[("X", D.gun)] - 2_000_000) < 1e-6  # 20M eski = 2M yeni


def test_taban_gunleri_yarim_gun_ve_eksik_gun():
    tum = _seanslar(30)
    tum[10] = seans_olustur(tum[10].gun, "09:30", "13:00")  # yarım gün
    seri = _gunluk_seri(tum)
    del seri[tum[20].gun]  # sembol o gün işlem görmemiş
    D = tum[-1].gun
    tg = taban_gunleri("X", D, tum, {"X": seri}, CFG["tarayici"])
    gunler = [s.gun for s in tg]
    assert len(gunler) == CFG["tarayici"]["goreli_hacim_gun"]
    assert tum[10].gun not in gunler and tum[20].gun not in gunler
    assert D not in gunler and gunler == sorted(gunler)
