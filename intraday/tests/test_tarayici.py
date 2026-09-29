import copy
from datetime import date, timedelta

from intraday.ayarlar import config_yukle
from intraday.tarayici import SembolGunTarayici, sembol_gun_tara
from intraday.zaman import seans_olustur

CFG = config_yukle()
T = CFG["tarayici"]


def _bar(seans, dk, v, c):
    return {"t": seans.acilis + timedelta(minutes=dk), "o": c, "h": c, "l": c, "c": c, "v": v}


def _taban(gun_sayisi=20, dakika_hacmi=1_000):
    sonuc = []
    for i in range(gun_sayisi):
        s = seans_olustur(date(2026, 2, 2) + timedelta(days=i), "09:30", "16:00")
        sonuc.append((s, [_bar(s, k, dakika_hacmi, 5.0) for k in range(390)], 1.0))
    return sonuc


def _bugun(seans):
    # 0-9. dk sakin, 10. dakikadan itibaren fiyat +%4 ve hacim 5 kat
    barlar = [_bar(seans, k, 1_000, 5.0) for k in range(10)]
    barlar += [_bar(seans, k, 5_000, 5.2) for k in range(10, 390)]
    return barlar


class SahteQuote:
    def __init__(self, bid=5.19, ask=5.21):
        self.bid, self.ask = bid, ask
        self.istenen = []

    def __call__(self, sembol, an, feed):
        self.istenen.append(an)
        return {"bp": self.bid, "ap": self.ask}


def test_takilma_ve_karar_ani():
    seans = seans_olustur("2026-03-09", "09:30", "16:00")  # DST sonrası ilk gün
    q = SahteQuote()
    oz = sembol_gun_tara("ABCD", seans, 5.0, _bugun(seans), _taban(), T, q, ["iex"])
    h = oz.takilma["iex"]
    assert h is not None
    # göreli hacim 10. dakikada: (10*1000 + 5000) / (11*1000) = 1.36 < 2 -> henüz yok
    # 2'yi geçtiği ilk dakika: (10000 + 5000*n)/(1000*(10+n)) >= 2 -> n >= 3.33 -> dk 13
    assert h.t == seans.acilis + timedelta(minutes=13)
    assert h.karar_ani == h.t + timedelta(minutes=1)
    assert h.goreli_hacim >= 2.0 and h.degisim >= 3.0
    # quote yalnızca karar anında soruldu (geleceğe bakmıyor)
    assert q.istenen == [h.karar_ani]


def test_genis_spread_takilmaz_ve_sorgu_siniri():
    seans = seans_olustur("2026-03-09", "09:30", "16:00")
    q = SahteQuote(bid=5.0, ask=5.4)  # ~%7.7 spread
    oz = sembol_gun_tara("ABCD", seans, 5.0, _bugun(seans), _taban(), T, q, ["iex"])
    assert oz.takilma["iex"] is None
    assert oz.quote_sorgu["iex"] == T["max_quote_sorgu_sembol_gun"]
    assert oz.spread_dogrulanamadi["iex"]
    assert oz.sirali == {"fiyat": True, "degisim": True, "goreli_hacim": True}


def test_quote_yok_sayilir():
    seans = seans_olustur("2026-03-09", "09:30", "16:00")
    oz = sembol_gun_tara("ABCD", seans, 5.0, _bugun(seans), _taban(), T,
                         lambda s, an, f: None, ["iex"])
    assert oz.takilma["iex"] is None
    assert oz.quote_yok["iex"] == oz.quote_sorgu["iex"] > 0


def test_lookahead_yok_gelecek_barlar_degisse_de_gecmis_ayni():
    """Kesim anından sonraki barları bozmak, kesime kadarki kararları değiştirmemeli."""
    seans = seans_olustur("2026-03-09", "09:30", "16:00")
    taban = _taban()
    from intraday.hesap import kumulatif_hacim_profili, ortalama_profil

    prof = ortalama_profil([kumulatif_hacim_profili(b, s, c) for s, b, c in taban], 390)
    tam = _bugun(seans)
    bozuk = copy.deepcopy(tam)
    kesim = 60
    for b in bozuk[kesim:]:
        b["c"] = 9.9
        b["v"] = 10_000_000

    def durumlar(barlar):
        t = SembolGunTarayici("ABCD", seans, 5.0, prof, T)
        return [t.bar_isle(b) for b in barlar]

    a, b = durumlar(tam), durumlar(bozuk)
    for x, y in zip(a[:kesim], b[:kesim]):
        assert (x.fiyat, x.kumulatif_hacim, x.goreli_hacim, x.gecti) == (
            y.fiyat, y.kumulatif_hacim, y.goreli_hacim, y.gecti)


def test_taban_yetersiz():
    seans = seans_olustur("2026-03-09", "09:30", "16:00")
    oz = sembol_gun_tara("ABCD", seans, 5.0, _bugun(seans), _taban(gun_sayisi=5), T,
                         SahteQuote(), ["iex"])
    assert oz.durum == "taban_yetersiz"


def test_sirasiz_bar_reddedilir():
    seans = seans_olustur("2026-03-09", "09:30", "16:00")
    t = SembolGunTarayici("ABCD", seans, 5.0, [1.0] * 390, T)
    t.bar_isle(_bar(seans, 5, 1, 5.0))
    try:
        t.bar_isle(_bar(seans, 4, 1, 5.0))
    except ValueError:
        return
    raise AssertionError("sırasız bar kabul edildi")


def test_yaz_saati_gecis_gunu_taban_hizalamasi():
    """Taban günleri EST'de (UTC-5), hedef gün EDT'de (UTC-4): hizalama seans ofsetiyle olmalı."""
    hedef = seans_olustur("2026-03-09", "09:30", "16:00")
    taban = []
    for g in range(20):
        s = seans_olustur(date(2026, 2, 6) + timedelta(days=g), "09:30", "16:00")
        assert s.acilis.hour == 14  # EST
        # ilk dakikada 10k, sonra 100
        taban.append((s, [_bar(s, 0, 10_000, 5.0)] + [_bar(s, k, 100, 5.0) for k in range(1, 390)], 1.0))
    assert hedef.acilis.hour == 13  # EDT
    q = SahteQuote(5.19, 5.21)
    bugun = [_bar(hedef, 0, 25_000, 5.2)]
    oz = sembol_gun_tara("ABCD", hedef, 5.0, bugun, taban, T, q, ["iex"])
    # UTC saatine göre hizalansaydı taban[0] 0 olurdu; seans ofsetiyle 10k -> rv 2.5
    assert oz.takilma["iex"] is not None
    assert abs(oz.takilma["iex"].goreli_hacim - 2.5) < 1e-9
