"""depo.py: gerçek parquet okuma/yazma (pyarrow gerekir, yoksa atlanır)."""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from intraday.depo import Depo, barlari_oku, barlari_yaz, manifest_oku, manifest_yaz  # noqa: E402
from intraday.zaman import UTC  # noqa: E402


def _bar(t, c, v):
    return {"t": t, "o": c - 0.1, "h": c + 0.2, "l": c - 0.3, "c": c, "v": v}


def test_parquet_gidis_donus():
    t0 = datetime(2026, 9, 15, 13, 30, tzinfo=UTC)
    # Sırasız yazılan barlar okunurken zamana göre sıralanmalı.
    barlar = {
        "ZZZ": [_bar(t0 + timedelta(minutes=1), 3.5, 1200), _bar(t0, 3.4, 800)],
        "AAA": [_bar(t0, 7.25, 50_000)],
    }
    with tempfile.TemporaryDirectory() as d:
        yol = Depo(Path(d)).dakika_yolu("iex", "2026-09-15")
        barlari_yaz(yol, barlar)
        assert yol.exists()
        assert not yol.with_suffix(".tmp").exists()

        okunan = barlari_oku(yol)
        assert set(okunan) == {"AAA", "ZZZ"}
        assert [b["t"] for b in okunan["ZZZ"]] == [t0, t0 + timedelta(minutes=1)]
        assert okunan["ZZZ"][0]["t"].tzinfo is not None
        assert okunan["ZZZ"][0]["t"].utcoffset() == timedelta(0)
        assert okunan["ZZZ"][1] == barlar["ZZZ"][0]
        assert okunan["AAA"][0] == barlar["AAA"][0]
        assert isinstance(okunan["AAA"][0]["v"], float)


def test_parquet_ustune_yazma_ve_bos():
    t0 = datetime(2026, 9, 15, 13, 30, tzinfo=UTC)
    with tempfile.TemporaryDirectory() as d:
        yol = Path(d) / "gunluk" / "x.parquet"
        assert barlari_oku(yol) == {}
        barlari_yaz(yol, {"AAA": [_bar(t0, 5.0, 10)]})
        barlari_yaz(yol, {"BBB": [_bar(t0, 6.0, 20)]})
        assert set(barlari_oku(yol)) == {"BBB"}
        barlari_yaz(yol, {})
        assert barlari_oku(yol) == {}


def test_manifest_gidis_donus():
    with tempfile.TemporaryDirectory() as d:
        yol = Path(d) / "dakika" / "iex" / "2026-09-15.parquet"
        assert manifest_oku(yol) == set()
        manifest_yaz(yol, {"ZZZ", "AAA"})
        assert manifest_oku(yol) == {"AAA", "ZZZ"}
