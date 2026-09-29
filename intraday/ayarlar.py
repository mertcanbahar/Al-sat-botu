"""intraday/config.yaml ve .env yükleyicisi.

Eşikler yalnızca config.yaml'dan gelir. Gizli anahtarlar yalnızca ortam
değişkenlerinden (.env dosyası varsa oradan) gelir; hiçbir zaman loglanmaz.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

KOK_DIZIN = Path(__file__).resolve().parent.parent
VARSAYILAN_CONFIG = Path(__file__).resolve().parent / "config.yaml"


def config_yukle(yol: Path | str | None = None) -> dict[str, Any]:
    with open(yol or VARSAYILAN_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def env_dosyasi_yukle(yol: Path | str | None = None) -> None:
    """Basit KEY=VALUE .env okuyucusu. Zaten tanımlı ortam değişkenini ezmez.

    Değerleri asla yazdırmaz/loglamaz.
    """
    yol = Path(yol) if yol else KOK_DIZIN / ".env"
    if not yol.exists():
        return
    for satir in yol.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, deger = satir.split("=", 1)
        anahtar = anahtar.strip()
        deger = deger.strip().strip('"').strip("'")
        if anahtar and anahtar not in os.environ:
            os.environ[anahtar] = deger


@dataclass(frozen=True)
class AlpacaKimlik:
    api_key: str
    secret_key: str
    data_feed: str

    def __repr__(self) -> str:  # anahtarlar repr/log'a sızmasın
        return f"AlpacaKimlik(api_key=<gizli>, secret_key=<gizli>, data_feed={self.data_feed!r})"


def alpaca_kimlik() -> AlpacaKimlik:
    env_dosyasi_yukle()
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY tanımlı değil. .env.example'ı "
            ".env olarak kopyalayıp doldurun (dosya git'e girmez)."
        )
    return AlpacaKimlik(key, secret, os.environ.get("ALPACA_DATA_FEED", "iex"))


def kok_yolu(goreli: str) -> Path:
    """Göreli yolu repo köküne göre çözer."""
    p = Path(goreli)
    return p if p.is_absolute() else KOK_DIZIN / p
