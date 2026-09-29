"""Alpaca REST istemcisi: hız sınırı, yeniden deneme, sayfalama.

Anahtarlar yalnızca HTTP başlığında taşınır; URL'de yoktur ve hiçbir
log satırına yazılmaz. `requests.Session` enjekte edilebilir (testler için).
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Iterable, Optional

import requests

from intraday.ayarlar import AlpacaKimlik
from intraday.zaman import utc_str

logger = logging.getLogger(__name__)

YENIDEN_DENENEBILIR = frozenset({429, 500, 502, 503, 504})


class AlpacaHatasi(RuntimeError):
    pass


class ErisimYok(AlpacaHatasi):
    """403/401: plan bu veriye izin vermiyor (ör. SIP) ya da anahtar hatalı."""


class HizSinirlayici:
    """Kayan pencere: son 60 sn içinde en fazla `dakika_basina` istek."""

    def __init__(
        self,
        dakika_basina: int,
        saat: Callable[[], float] = time.monotonic,
        uyu: Callable[[float], None] = time.sleep,
    ):
        self.limit = dakika_basina
        self._saat = saat
        self._uyu = uyu
        self._anlar: deque[float] = deque()
        self._kilit = threading.Lock()

    def bekle(self) -> None:
        with self._kilit:
            while True:
                simdi = self._saat()
                while self._anlar and simdi - self._anlar[0] >= 60.0:
                    self._anlar.popleft()
                if len(self._anlar) < self.limit:
                    self._anlar.append(simdi)
                    return
                self._uyu(60.0 - (simdi - self._anlar[0]) + 0.01)


class AlpacaIstemci:
    def __init__(
        self,
        kimlik: AlpacaKimlik,
        veri_cfg: dict,
        oturum: Optional[requests.Session] = None,
        uyu: Callable[[float], None] = time.sleep,
    ):
        self._kimlik = kimlik
        self.trading_url = veri_cfg["trading_api_url"].rstrip("/")
        self.data_url = veri_cfg["data_api_url"].rstrip("/")
        self.max_deneme = int(veri_cfg["max_yeniden_deneme"])
        self.bekleme_taban = float(veri_cfg["bekleme_taban_sn"])
        self.zaman_asimi = float(veri_cfg["istek_zaman_asimi_sn"])
        self.sayfa_limiti = int(veri_cfg["sayfa_limiti"])
        self.grup = int(veri_cfg["sembol_grup_boyutu"])
        self._oturum = oturum or requests.Session()
        self._uyu = uyu
        self.sinirlayici = HizSinirlayici(int(veri_cfg["istek_limiti_dakika"]), uyu=uyu)
        self.istek_sayisi = 0

    # -- düşük seviye -----------------------------------------------------

    def _basliklar(self) -> dict:
        return {
            "APCA-API-KEY-ID": self._kimlik.api_key,
            "APCA-API-SECRET-KEY": self._kimlik.secret_key,
            "Accept": "application/json",
        }

    def _get(self, url: str, params: dict) -> dict | list:
        son_hata: Exception | None = None
        for deneme in range(self.max_deneme + 1):
            self.sinirlayici.bekle()
            self.istek_sayisi += 1
            try:
                yanit = self._oturum.get(
                    url, params=params, headers=self._basliklar(), timeout=self.zaman_asimi
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                son_hata = exc
                if deneme == self.max_deneme:
                    break
                gecikme = self._geri_cekilme(deneme)
                logger.warning("GET %s bağlantı hatası (%s); %.1fs sonra tekrar (%d/%d)",
                               url, type(exc).__name__, gecikme, deneme + 1, self.max_deneme)
                self._uyu(gecikme)
                continue

            if yanit.status_code == 200:
                return yanit.json()
            if yanit.status_code in (401, 403):
                raise ErisimYok(f"GET {url} -> HTTP {yanit.status_code}: {yanit.text[:200]}")
            if yanit.status_code in YENIDEN_DENENEBILIR and deneme < self.max_deneme:
                gecikme = self._retry_after(yanit) or self._geri_cekilme(deneme)
                logger.warning("GET %s -> HTTP %d; %.1fs sonra tekrar (%d/%d)",
                               url, yanit.status_code, gecikme, deneme + 1, self.max_deneme)
                self._uyu(gecikme)
                continue
            raise AlpacaHatasi(f"GET {url} -> HTTP {yanit.status_code}: {yanit.text[:200]}")
        raise AlpacaHatasi(f"GET {url} başarısız: {son_hata}")

    def _geri_cekilme(self, deneme: int) -> float:
        return self.bekleme_taban * (2**deneme) + random.uniform(0, self.bekleme_taban)

    @staticmethod
    def _retry_after(yanit: requests.Response) -> float | None:
        try:
            return float(yanit.headers.get("Retry-After", ""))
        except ValueError:
            return None

    # -- trading API -----------------------------------------------------

    def varliklar(self, borsa: str) -> list[dict]:
        return self._get(
            f"{self.trading_url}/v2/assets",
            {"status": "active", "asset_class": "us_equity", "exchange": borsa},
        )

    def takvim(self, baslangic: str, bitis: str) -> list[dict]:
        return self._get(f"{self.trading_url}/v2/calendar", {"start": baslangic, "end": bitis})

    # -- market data API -------------------------------------------------

    def barlar(
        self,
        semboller: Iterable[str],
        timeframe: str,
        baslangic: datetime,
        bitis: datetime,
        feed: str,
        adjustment: str = "raw",
    ) -> dict[str, list[dict]]:
        """Çoklu sembol bar isteği; grup + sayfalama. {sembol: [bar,...]}"""
        semboller = sorted(set(semboller))
        sonuc: dict[str, list[dict]] = {}
        for i in range(0, len(semboller), self.grup):
            grup = semboller[i : i + self.grup]
            params = {
                "symbols": ",".join(grup),
                "timeframe": timeframe,
                "start": utc_str(baslangic),
                "end": utc_str(bitis),
                "limit": self.sayfa_limiti,
                "feed": feed,
                "adjustment": adjustment,
            }
            while True:
                veri = self._get(f"{self.data_url}/v2/stocks/bars", params)
                for sembol, bar_listesi in (veri.get("bars") or {}).items():
                    sonuc.setdefault(sembol, []).extend(bar_listesi or [])
                token = veri.get("next_page_token")
                if not token:
                    break
                params = {**params, "page_token": token}
        return sonuc

    def son_quote(
        self, sembol: str, baslangic: datetime, bitis: datetime, feed: str
    ) -> dict | None:
        """[baslangic, bitis] aralığındaki EN SON quote (bitis sonrası yok -> lookahead yok)."""
        veri = self._get(
            f"{self.data_url}/v2/stocks/{sembol}/quotes",
            {
                "start": utc_str(baslangic),
                "end": utc_str(bitis),
                "limit": 1,
                "sort": "desc",
                "feed": feed,
            },
        )
        quotes = veri.get("quotes") or []
        return quotes[0] if quotes else None
