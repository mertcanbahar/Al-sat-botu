"""Sahte Alpaca API ile indir -> tara -> rapor akışı (ağ yok).

Depolama bellek içine yamalanır (pyarrow olmadan da koşsun). Ayrıca
ikinci koşunun hiçbir veriyi yeniden indirmediği doğrulanır.
"""
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from intraday import depo as depo_mod
from intraday.ayarlar import config_yukle
from intraday.depo import Depo
from intraday.indir import Indirici
from intraday.rapor import rapor_uret
from intraday.tarayici import OnbellekliQuote, gecmisi_tara
from intraday.zaman import ET, UTC, seans_olustur, utc_str

CFG = config_yukle()
SPIKE_GUNU = date(2026, 9, 15)


def _takvim(bas, bit):
    out, g = [], date.fromisoformat(bas)
    while g <= date.fromisoformat(bit):
        if g.weekday() < 5 and g != date(2026, 9, 7):  # Labor Day tatil
            out.append({"date": g.isoformat(), "open": "09:30",
                        "close": "13:00" if g == date(2026, 7, 3) else "16:00"})
        g += timedelta(days=1)
    return out


class SahteAPI:
    def __init__(self):
        self.istek_sayisi = 0
        self.bar_istekleri = []

    def takvim(self, bas, bit):
        self.istek_sayisi += 1
        return _takvim(bas, bit)

    def varliklar(self, borsa):
        self.istek_sayisi += 1
        return [
            {"symbol": s, "name": n, "exchange": "NASDAQ", "status": "active", "tradable": True}
            for s, n in [("HOT", "Hot Corp"), ("COLD", "Cold Inc"), ("HOTW", "Hot Corp Warrant")]
        ]

    def barlar(self, semboller, timeframe, bas, bit, feed, adjustment="raw"):
        self.istek_sayisi += 1
        self.bar_istekleri.append((timeframe, feed, tuple(sorted(semboller)), bas))
        sonuc = {}
        for s in semboller:
            if timeframe == "1Day":
                liste = []
                for r in _takvim(bas.astimezone(ET).date().isoformat(), bit.astimezone(ET).date().isoformat()):
                    g = date.fromisoformat(r["date"])
                    spike = s == "HOT" and g == SPIKE_GUNU
                    liste.append({"t": utc_str(datetime(g.year, g.month, g.day, 4, tzinfo=UTC)),
                                  "o": 5.0, "h": 5.4 if spike else 5.05, "l": 4.95,
                                  "c": 5.3 if spike else 5.0,
                                  "v": 2_000_000 if s == "HOT" else 50_000})
                sonuc[s] = liste
            else:
                seans = seans_olustur(bas.astimezone(ET).date(), "09:30", "16:00")
                spike = s == "HOT" and seans.gun == SPIKE_GUNU
                kat = 1 if feed == "iex" else 30
                liste = []
                for k in range(0, 390, 2 if feed == "iex" else 1):  # IEX seyrek
                    ileri = spike and k >= 30
                    liste.append({"t": utc_str(seans.acilis + timedelta(minutes=k)),
                                  "o": 5.0, "h": 5.0, "l": 5.0, "c": 5.3 if ileri else 5.0,
                                  "v": (800 if ileri else 100) * kat})
                sonuc[s] = liste
        return sonuc

    def son_quote(self, sembol, bas, bit, feed):
        self.istek_sayisi += 1
        if feed == "iex":
            return None if bit.minute % 3 else {"bp": 5.29, "ap": 5.31, "t": utc_str(bit)}
        return {"bp": 5.295, "ap": 5.305, "t": utc_str(bit)}


def _bellek_depo(monkey):
    bellek = {}

    def yaz(yol, barlar):
        bellek[str(yol)] = {s: list(v) for s, v in barlar.items()}

    def oku(yol):
        return {s: list(v) for s, v in bellek.get(str(yol), {}).items()}

    monkey["yaz"], monkey["oku"] = depo_mod.barlari_yaz, depo_mod.barlari_oku
    depo_mod.barlari_yaz, depo_mod.barlari_oku = yaz, oku


def test_uctan_uca():
    eski = {}
    _bellek_depo(eski)
    try:
        kok = Path(tempfile.mkdtemp())
        api = SahteAPI()
        depo = Depo(kok / "veri")
        ind = Indirici(api, depo, CFG).calistir(date(2026, 9, 29))

        assert ind.evren.kalan == ["COLD", "HOT"]
        assert ind.on.adaylar == {SPIKE_GUNU: {"HOT"}}
        # dakikalık: aday gün + 20 taban günü (IEX) ve yalnızca aday gün (SIP)
        iex_gunler = {b[3] for b in api.bar_istekleri if b[0] == "1Min" and b[1] == "iex"}
        sip_gunler = {b[3] for b in api.bar_istekleri if b[0] == "1Min" and b[1] == "sip"}
        assert len(iex_gunler) == 21 and len(sip_gunler) == 1
        assert all(b[2] == ("HOT",) for b in api.bar_istekleri if b[0] == "1Min")

        quote = OnbellekliQuote(api, depo, CFG["tarayici"]["quote_penceresi_sn"])
        oz = gecmisi_tara(ind, depo, CFG, quote)
        assert len(oz) == 1 and oz[0].durum == "tarandi"
        h_iex, h_sip = oz[0].takilma["iex"], oz[0].takilma["sip"]
        assert h_sip is not None and h_iex is not None
        assert h_iex.karar_ani >= h_sip.karar_ani  # IEX quote'u bazı dakikalarda yok
        assert oz[0].quote_yok["iex"] > 0

        metin = rapor_uret(ind, oz, CFG, kok / "rapor.md", quote.erisimsiz)
        assert "HOT" in metin and "YANILTICI" in metin

        # ikinci koşu: bar indirmesi tekrarlanmamalı (önbellek + manifest)
        onceki = len(api.bar_istekleri)
        ind2 = Indirici(api, depo, CFG).calistir(date(2026, 9, 29))
        assert len(api.bar_istekleri) == onceki
        assert ind2.on.adaylar == ind.on.adaylar
    finally:
        depo_mod.barlari_yaz, depo_mod.barlari_oku = eski["yaz"], eski["oku"]
