# -*- coding: utf-8 -*-
"""Вахта свежести данных и кабины :8010 (ARCH-153.4, 31.10.2026).

Поводов два, и оба стоили доверия к терминалу:
  • 26.10 :8010 держал сирота, свечи отдавались 21-часовой давности — МОЛЧА;
  • 27.10 терминал вообще остался остановленным (`pm2 stop` без `start`, 2,5 суток) — не заметил никто,
    сторож `pm2_guard` следит только за oko-bot.

Поэтому вахта смотрит ВОЗРАСТ ДАННЫХ, а не «отвечает ли порт» (закон
law_freshness_by_data_age_not_response). Проверки раз в минуту:

  1) :8010 отвечает и отдаёт НЕПУСТЫЕ свечи; возраст последнего бара ≤ 2 шагов ТФ;
  2) хранилище market-store: возраст последнего закрытого 15m бара ≤ 3 шагов;
  3) баны 100410 за последние 15 мин (порог 50 — это ~10× фона 19/час, замер 30.10).

Смена состояния → Telegram + WATCH.md через scripts/_alert.py (как у прочих вахт).

Запуск: python scripts/freshness_watch.py --once     # под pm2 --cron "* * * * *"
        python scripts/freshness_watch.py --once --dry-run   # только печать
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TERM_URL = "http://127.0.0.1:8010/api/klines?syms=BTC,ETH&tf=15m&limit=2"
TF_MS = 15 * 60 * 1000
TERM_MAX_AGE_MS = 2 * TF_MS      # терминал: последний бар не старше двух шагов
STORE_MAX_AGE_MS = 3 * TF_MS     # хранилище: закрытый бар не старше трёх шагов
BAN_WINDOW_MIN = 15
BAN_MAX = 50
KEY = "Свежесть данных · кабинет :8010"


def _term_freshness() -> tuple[str, str]:
    """(состояние, пояснение) по кабине :8010 — возраст баров, а не код ответа."""
    try:
        with urllib.request.urlopen(TERM_URL, timeout=12) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — недоступность и есть предмет проверки
        return "DOWN", f":8010 не отвечает ({type(e).__name__})"
    bars = data.get("bars") or {}
    if not bars:
        return "EMPTY", ":8010 ответил без свечей"
    oldest_age, empty = 0.0, []
    for sym, rows in bars.items():
        if not rows:
            empty.append(sym)
            continue
        age = (time.time() - int(rows[-1]["t"])) * 1000.0   # терминал отдаёт t в СЕКУНДАХ
        oldest_age = max(oldest_age, age)
    if empty:
        return "EMPTY", f":8010 отдал пустые свечи: {', '.join(empty)}"
    if oldest_age > TERM_MAX_AGE_MS:
        return "STALE", f":8010: последний бар старше {oldest_age / 60_000:.0f} мин при шаге 15m"
    return "OK", f":8010 бары {oldest_age / 60_000:.0f} мин"


def _store_freshness() -> tuple[str, str]:
    """Возраст последнего ЗАКРЫТОГО 15m бара в хранилище Сферы 1."""
    try:
        from core.infra.market_store import last_time
    except Exception as e:  # noqa: BLE001 — нет хранилища = проблема, но не падаем
        return "STALE", f"хранилище: модуль не загрузился ({type(e).__name__})"
    stamps = []
    for base in ("BTC", "ETH"):
        try:
            t = last_time(base, "15m")
        except Exception:  # noqa: BLE001
            t = None
        if t:
            stamps.append(int(t))
    if not stamps:
        return "STALE", "хранилище: нет закрытых 15m баров"
    age_ms = time.time() * 1000 - min(stamps)
    if age_ms > STORE_MAX_AGE_MS:
        return "STALE", f"хранилище: закрытый 15m бар старше {age_ms / 60_000:.0f} мин"
    return "OK", f"хранилище {age_ms / 60_000:.0f} мин"


def _bans_recent() -> tuple[str, str]:
    """Сколько строк 100410 в логе бота за последние BAN_WINDOW_MIN минут."""
    path = os.path.join(ROOT, "logs", "crypto_bot.log")
    if not os.path.exists(path):
        return "OK", "лог бота не найден — баны не считаю"
    edge = datetime.now() - timedelta(minutes=BAN_WINDOW_MIN)
    n, size = 0, os.path.getsize(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(max(0, size - 4_000_000))       # хвост: 15 мин лога ≈ 1-2 МБ
        for line in f:
            if "100410" not in line:
                continue
            try:
                ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if ts >= edge:
                n += 1
    state = "BANS" if n >= BAN_MAX else "OK"
    return state, f"банов 100410 за {BAN_WINDOW_MIN} мин: {n} (порог {BAN_MAX})"


def check() -> tuple[str, str]:
    """Итоговое состояние: худшее из проверок (DOWN > EMPTY > STALE > BANS > OK)."""
    order = ["OK", "BANS", "STALE", "EMPTY", "DOWN"]
    parts, worst = [], "OK"
    for fn in (_term_freshness, _store_freshness, _bans_recent):
        try:
            st, txt = fn()
        except Exception as e:  # noqa: BLE001 — вахта не должна умирать от своей проверки
            st, txt = "STALE", f"{fn.__name__}: {type(e).__name__}: {e}"
        parts.append(txt)
        if order.index(st) > order.index(worst):
            worst = st
    return worst, " · ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="одна проверка (режим pm2 --cron)")
    ap.add_argument("--dry-run", action="store_true", help="только напечатать, не оповещать")
    args = ap.parse_args()

    if args.once:
        state, detail = check()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {state} · {detail}")
        if args.dry_run:
            return
        from scripts._alert import notify
        notify(KEY, state, title="Вахта свежести · :8010 и баны",
               tg_text=f"{state} · {detail}",
               task_detail=detail, first_time=True)
        return

    while True:                      # долгий режим — для ручного запуска
        state, detail = check()
        print(f"[{datetime.now():%H:%M:%S}] {state} · {detail}")
        time.sleep(60)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
