"""
time_utils.py — единые helpers для UTC времени.

До этого 29+ мест писали datetime.now(timezone.utc).isoformat() вручную.
Если когда-нибудь захотим заменить на monotonic-aware timestamps или добавить
тест-mock (freeze_time), правка пойдёт в одно место.

Использование:
    from core.infra.time_utils import utc_now, utc_iso, utc_unix_ms
    ts = utc_now()              # datetime (timezone-aware UTC)
    iso = utc_iso()             # "2026-05-27T01:23:45.678+00:00"
    ms = utc_unix_ms()          # int milliseconds since epoch
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Текущее UTC время, timezone-aware. Замена datetime.now(timezone.utc)."""
    return datetime.now(timezone.utc)


def utc_iso() -> str:
    """ISO-8601 UTC строка для записи в БД (created_at/closed_at)."""
    return utc_now().isoformat()


def utc_unix_ms() -> int:
    """Unix timestamp в миллисекундах (для BingX API, JS frontend)."""
    return int(utc_now().timestamp() * 1000)


def ensure_utc(dt: datetime) -> datetime:
    """Если datetime naive — пометить как UTC; если уже aware — вернуть как есть.

    Полезно при чтении created_at из БД (старые записи могли быть naive).
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso_utc(s: str) -> datetime:
    """Парсит ISO-8601 строку в UTC-aware datetime.

    Принимает 'Z' suffix или explicit +00:00. Naive → считается UTC.
    """
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(s2)
    return ensure_utc(dt)
