"""Nasdaq hisse evreni: Alpaca assets -> ETF/warrant/right/unit/preferred hariç.

Kurallar config.yaml `evren` bölümündedir. Her varlık, eşleşen İLK kurala
göre elenir; rapor her kuralın elediği sayıyı ve örnekleri ayrı gösterir.
Sıra: exchange/status/tradable -> özel karakter -> isim kuralları ->
5. harf kuralları.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class EvrenSonucu:
    tarih: str
    toplam: int
    kalan: list[str]
    elenen: dict[str, list[str]] = field(default_factory=dict)  # kural -> semboller
    isimler: dict[str, str] = field(default_factory=dict)

    def sayilar(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.elenen.items()}


def eleme_nedeni(varlik: dict, borsa: str, evren_cfg: dict) -> str | None:
    sembol = (varlik.get("symbol") or "").upper()
    isim = varlik.get("name") or ""

    if (varlik.get("exchange") or "").upper() != borsa.upper():
        return "borsa_farkli"
    if varlik.get("status") != "active":
        return "aktif_degil"
    if not varlik.get("tradable", False):
        return "islem_gormez"
    if re.search(evren_cfg["ozel_karakter_regex"], sembol):
        return "sembol_ozel_karakter"
    for kural, desen in evren_cfg["isim_kurallari"].items():
        if re.search(desen, isim, flags=re.IGNORECASE):
            return f"isim_{kural}"
    if len(sembol) == 5:
        for kural, harf in evren_cfg["besinci_harf_kurallari"].items():
            if sembol.endswith(harf.upper()):
                return f"besinci_harf_{kural}"
    return None


def evren_olustur(varliklar: list[dict], borsa: str, evren_cfg: dict, gun: date) -> EvrenSonucu:
    kalan: list[str] = []
    elenen: dict[str, list[str]] = {}
    isimler: dict[str, str] = {}
    for v in varliklar:
        sembol = (v.get("symbol") or "").upper()
        neden = eleme_nedeni(v, borsa, evren_cfg)
        isimler[sembol] = v.get("name") or ""
        if neden is None:
            kalan.append(sembol)
        else:
            elenen.setdefault(neden, []).append(sembol)
    return EvrenSonucu(
        tarih=gun.isoformat(),
        toplam=len(varliklar),
        kalan=sorted(kalan),
        elenen={k: sorted(v) for k, v in sorted(elenen.items())},
        isimler=isimler,
    )


def evren_kaydet(sonuc: EvrenSonucu, dizin: Path) -> Path:
    dizin.mkdir(parents=True, exist_ok=True)
    yol = dizin / f"evren_{sonuc.tarih}.json"
    yol.write_text(
        json.dumps(
            {
                "tarih": sonuc.tarih,
                "toplam": sonuc.toplam,
                "kalan": sonuc.kalan,
                "elenen": sonuc.elenen,
                "isimler": sonuc.isimler,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return yol


def evren_yukle(dizin: Path, gun: date) -> EvrenSonucu | None:
    yol = dizin / f"evren_{gun.isoformat()}.json"
    if not yol.exists():
        return None
    d = json.loads(yol.read_text(encoding="utf-8"))
    return EvrenSonucu(d["tarih"], d["toplam"], d["kalan"], d["elenen"], d.get("isimler", {}))
