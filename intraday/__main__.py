"""Komut satırı.

  python -m intraday evren     # bugünün evrenini güncelle (günde bir kez)
  python -m intraday tara      # 6 aylık veriyi indir (önbellekli) + tara + rapor yaz

Anahtarlar .env'den (bkz. .env.example) ya da ortam değişkenlerinden okunur.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from intraday.alpaca import AlpacaIstemci
from intraday.ayarlar import alpaca_kimlik, config_yukle, kok_yolu
from intraday.depo import Depo
from intraday.indir import Indirici
from intraday.rapor import rapor_uret
from intraday.tarayici import OnbellekliQuote, gecmisi_tara


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m intraday")
    p.add_argument("komut", choices=["evren", "tara"])
    p.add_argument("--config", default=None)
    p.add_argument("--bugun", default=None, help="YYYY-MM-DD (varsayılan: bugün, UTC)")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_yukle(a.config)
    bugun = date.fromisoformat(a.bugun) if a.bugun else date.today()
    istemci = AlpacaIstemci(alpaca_kimlik(), cfg["veri"])
    depo = Depo(kok_yolu(cfg["veri"]["veri_dizini"]))
    ind = Indirici(istemci, depo, cfg)

    if a.komut == "evren":
        ev = ind.evren(bugun)
        print(f"Evren {ev.tarih}: {ev.toplam} varlık -> {len(ev.kalan)} hisse; elenen: {ev.sayilar()}")
        return 0

    sonuc = ind.calistir(bugun)
    quote = OnbellekliQuote(istemci, depo, int(cfg["tarayici"]["quote_penceresi_sn"]))
    ozetler = gecmisi_tara(sonuc, depo, cfg, quote)
    quote.kaydet()
    sonuc.istek_sayisi = istemci.istek_sayisi
    yol = kok_yolu(cfg["rapor"]["dosya"])
    rapor_uret(sonuc, ozetler, cfg, yol, quote.erisimsiz)
    print(f"Rapor: {yol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
