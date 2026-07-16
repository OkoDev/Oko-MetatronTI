# -*- coding: utf-8 -*-
"""core.infra.heartbeat — пульс торговых лупов (16.07, инцидент «тихой смерти»).

Корень (15.07 19:03→01:50, 6.5ч): сеть просела → все BingX-запросы FAIL → лупы повисли
на ретраях и умерли МОЛЧА. pm2 видел процесс `online` (жил только WS-таск) → не рестартил;
позиции 6.5ч без сопровождения, шина пустая, дашборд рисовал фантомный дрифт.

Механика: луп зовёт beat("scan") в конце каждого цикла → touch файла logs/heartbeat/scan.
Внешний scripts/heartbeat_watchdog.py (pm2 cron) читает mtime: тишина > порога → рестарт.
Touch-файлы вместо БД/JSON: атомарно, без локов и гонок между лупами, переживает зависший
event loop (mtime не обновится — это и есть сигнал).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HB_DIR = Path("logs/heartbeat")


def beat(name: str) -> None:
    """Отметить пульс лупа. Никогда не бросает — пульс не должен ронять торговлю."""
    try:
        HB_DIR.mkdir(parents=True, exist_ok=True)
        (HB_DIR / name).touch()
    except Exception as e:
        logger.debug("[heartbeat] %s: %s", name, e)


def age_sec(name: str) -> float | None:
    """Сколько секунд назад бился пульс (None — файла нет = луп ни разу не отметился)."""
    import time
    try:
        return time.time() - (HB_DIR / name).stat().st_mtime
    except Exception:
        return None
