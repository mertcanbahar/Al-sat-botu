import logging
from datetime import date, datetime, timedelta

import requests

from intraday.alpaca import AlpacaIstemci, ErisimYok, HizSinirlayici
from intraday.ayarlar import AlpacaKimlik, config_yukle
from intraday.evren import EvrenSonucu
from intraday.indir import IndirmeSonucu, OnFiltreSonucu
from intraday.rapor import rapor_uret
from intraday.tarayici import SembolGunOzet, Takilma
from intraday.zaman import UTC, seans_olustur

CFG = config_yukle()
GIZLI = "SUPERGIZLI123"


class Yanit:
    def __init__(self, kod, veri=None, basliklar=None):
        self.status_code = kod
        self._veri = veri
        self.headers = basliklar or {}
        self.text = str(veri)

    def json(self):
        return self._veri


class SahteOturum:
    def __init__(self, yanitlar):
        self.yanitlar = list(yanitlar)
        self.cagrilar = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.cagrilar.append((url, dict(params or {}), headers))
        y = self.yanitlar.pop(0)
        if isinstance(y, Exception):
            raise y
        return y


def _istemci(yanitlar):
    uykular = []
    o = SahteOturum(yanitlar)
    ist = AlpacaIstemci(AlpacaKimlik("KEYID", GIZLI, "iex"), CFG["veri"], oturum=o,
                        uyu=uykular.append)
    return ist, o, uykular


def test_sayfalama_ve_basliklar():
    ist, o, _ = _istemci([
        Yanit(200, {"bars": {"A": [{"t": "x1"}]}, "next_page_token": "tok"}),
        Yanit(200, {"bars": {"A": [{"t": "x2"}], "B": [{"t": "y"}]}, "next_page_token": None}),
    ])
    t = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    r = ist.barlar(["B", "A"], "1Min", t, t, "iex")
    assert r == {"A": [{"t": "x1"}, {"t": "x2"}], "B": [{"t": "y"}]}
    assert o.cagrilar[1][1]["page_token"] == "tok"
    assert o.cagrilar[0][1]["feed"] == "iex"
    # anahtar yalnızca başlıkta, URL/parametrede yok
    url, params, basliklar = o.cagrilar[0]
    assert basliklar["APCA-API-SECRET-KEY"] == GIZLI
    assert GIZLI not in url and GIZLI not in str(params)


def test_429_yeniden_dener_retry_after():
    ist, o, uykular = _istemci([
        Yanit(429, {}, {"Retry-After": "3"}),
        requests.ConnectionError("koptu"),
        Yanit(200, [{"date": "2026-03-09"}]),
    ])
    assert ist.takvim("2026-03-09", "2026-03-09") == [{"date": "2026-03-09"}]
    assert uykular[0] == 3.0
    assert len(uykular) == 2


def test_403_erisim_yok_ve_gizli_loglanmaz():
    kayitlar = []

    class H(logging.Handler):
        def emit(self, r):
            kayitlar.append(r.getMessage())

    h = H()
    logging.getLogger("intraday").addHandler(h)
    try:
        ist, _, _ = _istemci([Yanit(500, {}), Yanit(403, {"message": "subscription does not permit"})])
        try:
            ist.varliklar("NASDAQ")
        except ErisimYok:
            pass
        else:
            raise AssertionError("ErisimYok bekleniyordu")
    finally:
        logging.getLogger("intraday").removeHandler(h)
    assert kayitlar and all(GIZLI not in k for k in kayitlar)
    assert GIZLI not in repr(AlpacaKimlik("KEYID", GIZLI, "iex"))


def test_hiz_sinirlayici():
    saat = [0.0]
    uykular = []

    def uyu(s):
        uykular.append(s)
        saat[0] += s

    hs = HizSinirlayici(3, saat=lambda: saat[0], uyu=uyu)
    for _ in range(3):
        hs.bekle()
    assert uykular == []
    hs.bekle()  # 4. istek: pencere dolana kadar bekler
    assert len(uykular) == 1 and 59.9 < uykular[0] <= 60.1


def test_rapor_duman(tmp_path=None):
    import tempfile
    from pathlib import Path

    kok = Path(tmp_path or tempfile.mkdtemp())
    seanslar = [seans_olustur("2026-03-06", "09:30", "16:00"), seans_olustur("2026-03-09", "09:30", "16:00")]
    ev = EvrenSonucu("2026-09-29", 3, ["AAA", "BBB"], {"isim_etf": ["QQQ"]}, {"AAA": "Aaa Inc"})
    on = OnFiltreSonucu(adaylar={seanslar[1].gun: {"AAA", "BBB"}},
                        huni={"veri_yok": 1, "ort_hacim": 1}, toplam_sembol_gun=4,
                        onceki_kapanis={("AAA", seanslar[1].gun): 5.0, ("BBB", seanslar[1].gun): 3.0})
    ind = IndirmeSonucu(ev, seanslar, seanslar, {}, {}, on, "sip", "sip", [], 42)
    t = seanslar[1].acilis + timedelta(minutes=13)
    h = Takilma("AAA", seanslar[1].gun, t, t + timedelta(minutes=1), 5.2, 4.0, 2.3, 0.3, "iex")
    oz1 = SembolGunOzet("AAA", seanslar[1].gun, "tarandi", bar_sayisi=100,
                        tek_basina={"fiyat": True, "degisim": True, "goreli_hacim": True},
                        sirali={"fiyat": True, "degisim": True, "goreli_hacim": True},
                        on_gecen_dakika=5, quote_sorgu={"iex": 3, "sip": 1},
                        quote_yok={"iex": 2, "sip": 0}, spread_ornek={"iex": [0.3], "sip": [0.2]},
                        spread_dogrulanamadi={"iex": False, "sip": False},
                        takilma={"iex": h, "sip": h}, tarama_hacmi=30_000,
                        karsilastirma_hacmi=1_000_000, karsilastirma_bar_sayisi=390)
    oz2 = SembolGunOzet("BBB", seanslar[1].gun, "taban_yetersiz")
    metin = rapor_uret(ind, [oz1, oz2], CFG, kok / "r.md", set(),
                       olusturma=datetime(2026, 9, 29, 12, 0, tzinfo=UTC))
    for bolum in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7."):
        assert bolum in metin
    assert "%3.0" in metin  # IEX/SIP hacim oranı 30k/1M
    assert "Geçmiş SIP erişimi (bu plan): günlük bar **VAR**, dakikalık bar **VAR**, quote **VAR**" in metin
    assert "YANILTICI" in metin  # %5 eşiğinin altında -> açık uyarı
    assert "| 16:00–16:59 | 1 |" in metin  # 13:44 UTC = 16:44 TR
    assert (kok / "scanner_hits.csv").read_text().count("AAA") == 2
    assert date(2026, 3, 9).isoformat() in metin
