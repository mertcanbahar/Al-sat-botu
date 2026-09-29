"""Yerel veri deposu (parquet + küçük JSON manifestler).

Düzen (`veri.veri_dizini` altında, git dışı):
  takvim_<bas>_<bit>.json
  evren/evren_<tarih>.json
  gunluk/<feed>_<adj>_<bas>_<bit>.parquet     (+ .manifest.json)
  dakika/<feed>/<tarih>.parquet               (+ .manifest.json: istenen semboller)
  quote/<feed>/<tarih>.json                   (sembol|dakika_sonu -> quote/None)

Manifest, "istendi ama bar yok" ile "hiç istenmedi"yi ayırır; böylece aynı
şey tekrar indirilmez. Zaman damgaları parquet'te epoch saniye (int64, UTC).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:  # pyarrow yalnızca depolamada gerekli; saf hesap testleri onsuz koşar
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None

BAR_ALANLARI = ("o", "h", "l", "c", "v")


def _pyarrow_gerekli() -> None:
    if pa is None:
        raise RuntimeError("pyarrow kurulu değil: pip install -r intraday/requirements.txt")


def _epoch(t: datetime) -> int:
    return int(t.timestamp())


def _dt(e: int) -> datetime:
    return datetime.fromtimestamp(int(e), tz=timezone.utc)


def barlari_yaz(yol: Path, barlar: dict[str, list[dict]]) -> None:
    """{sembol: [{t: datetime, o,h,l,c,v}]} -> parquet."""
    _pyarrow_gerekli()
    yol.parent.mkdir(parents=True, exist_ok=True)
    sutunlar: dict[str, list] = {"sembol": [], "t": [], **{a: [] for a in BAR_ALANLARI}}
    for sembol in sorted(barlar):
        for b in barlar[sembol]:
            sutunlar["sembol"].append(sembol)
            sutunlar["t"].append(_epoch(b["t"]))
            for a in BAR_ALANLARI:
                sutunlar[a].append(float(b[a]))
    sema = pa.schema(
        [("sembol", pa.string()), ("t", pa.int64())] + [(a, pa.float64()) for a in BAR_ALANLARI]
    )
    tmp = yol.with_suffix(".tmp")
    pq.write_table(pa.table(sutunlar, schema=sema), tmp)
    tmp.replace(yol)


def barlari_oku(yol: Path) -> dict[str, list[dict]]:
    _pyarrow_gerekli()
    if not yol.exists():
        return {}
    tablo = pq.read_table(yol).to_pydict()
    sonuc: dict[str, list[dict]] = {}
    for i, sembol in enumerate(tablo["sembol"]):
        bar = {"t": _dt(tablo["t"][i])}
        for a in BAR_ALANLARI:
            bar[a] = tablo[a][i]
        sonuc.setdefault(sembol, []).append(bar)
    for liste in sonuc.values():
        liste.sort(key=lambda b: b["t"])
    return sonuc


def manifest_oku(yol: Path) -> set[str]:
    m = yol.with_suffix(".manifest.json")
    if not m.exists():
        return set()
    return set(json.loads(m.read_text(encoding="utf-8"))["semboller"])


def manifest_yaz(yol: Path, semboller: set[str]) -> None:
    m = yol.with_suffix(".manifest.json")
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"semboller": sorted(semboller)}), encoding="utf-8")


def json_oku(yol: Path, varsayilan):
    if not yol.exists():
        return varsayilan
    return json.loads(yol.read_text(encoding="utf-8"))


def json_yaz(yol: Path, veri) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    tmp = yol.with_suffix(".tmp")
    tmp.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    tmp.replace(yol)


class Depo:
    def __init__(self, kok: Path):
        self.kok = kok

    def takvim_yolu(self, bas: str, bit: str) -> Path:
        return self.kok / f"takvim_{bas}_{bit}.json"

    def evren_dizini(self) -> Path:
        return self.kok / "evren"

    def gunluk_yolu(self, feed: str, adj: str, bas: str, bit: str) -> Path:
        return self.kok / "gunluk" / f"{feed}_{adj}_{bas}_{bit}.parquet"

    def dakika_yolu(self, feed: str, gun: str) -> Path:
        return self.kok / "dakika" / feed / f"{gun}.parquet"

    def quote_yolu(self, feed: str, gun: str) -> Path:
        return self.kok / "quote" / feed / f"{gun}.json"
