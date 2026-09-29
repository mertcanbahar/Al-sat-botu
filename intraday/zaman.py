"""Saat dilimi ve seans hesapları.

Kural: tüm iç zamanlar UTC (tz-aware datetime). Seans saatleri Alpaca
calendar endpoint'inin verdiği America/New_York yerel saatlerinden UTC'ye
çevrilir; yaz/kış saati geçişini zoneinfo halleder. Raporlarda ayrıca
Europe/Istanbul gösterilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
TR = ZoneInfo("Europe/Istanbul")

NORMAL_SEANS_DAKIKA = 390  # 09:30-16:00 ET


@dataclass(frozen=True)
class Seans:
    """Bir işlem gününün düzenli seansı (UTC)."""

    gun: date
    acilis: datetime  # UTC
    kapanis: datetime  # UTC

    @property
    def dakika_sayisi(self) -> int:
        return int((self.kapanis - self.acilis).total_seconds() // 60)

    @property
    def yarim_gun(self) -> bool:
        return self.dakika_sayisi < NORMAL_SEANS_DAKIKA

    def iceriyor(self, an: datetime) -> bool:
        """`an` (bar başlangıcı) düzenli seans içinde mi? [acilis, kapanis)"""
        return self.acilis <= an < self.kapanis

    def acilistan_dakika(self, an: datetime) -> int:
        return int((an - self.acilis).total_seconds() // 60)


def _saat_coz(s: str) -> time:
    s = s.strip()
    if len(s) == 4 and ":" not in s:  # "0930"
        return time(int(s[:2]), int(s[2:]))
    saat, dakika = s.split(":")[:2]
    return time(int(saat), int(dakika))


def et_yerel_to_utc(gun: date, saat: time) -> datetime:
    return datetime.combine(gun, saat, tzinfo=ET).astimezone(UTC)


def seans_olustur(gun: date | str, acilis: str, kapanis: str) -> Seans:
    """Alpaca calendar satırından (ET yerel "09:30"/"16:00") UTC seans üretir."""
    if isinstance(gun, str):
        gun = date.fromisoformat(gun)
    return Seans(
        gun=gun,
        acilis=et_yerel_to_utc(gun, _saat_coz(acilis)),
        kapanis=et_yerel_to_utc(gun, _saat_coz(kapanis)),
    )


def takvimden_seanslar(takvim: list[dict]) -> list[Seans]:
    """Alpaca /v2/calendar yanıtı -> Seans listesi (tarihe göre sıralı)."""
    return sorted(
        (seans_olustur(r["date"], r["open"], r["close"]) for r in takvim),
        key=lambda s: s.gun,
    )


def utc_parse(s: str) -> datetime:
    """Alpaca RFC3339 zaman damgası ('2026-03-09T13:30:00Z') -> UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # nanosaniye hassasiyetini mikrosaniyeye kırp
    if "." in s:
        ana, kalan = s.split(".", 1)
        kesir = ""
        i = 0
        while i < len(kalan) and kalan[i].isdigit():
            kesir += kalan[i]
            i += 1
        s = f"{ana}.{kesir[:6].ljust(6, '0')}{kalan[i:]}"
    return datetime.fromisoformat(s).astimezone(UTC)


def utc_str(an: datetime) -> str:
    return an.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def tr_saat(an: datetime) -> datetime:
    return an.astimezone(TR)


def et_saat(an: datetime) -> datetime:
    return an.astimezone(ET)


def dakika_sonu(bar_baslangici: datetime) -> datetime:
    """1 dakikalık bar kapanış (karar) anı: bu andan önce bar bilinemez."""
    return bar_baslangici + timedelta(minutes=1)
