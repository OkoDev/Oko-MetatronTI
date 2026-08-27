"""
_alert.py — ОПОВЕЩЕНИЯ ИЗ ФОНОВЫХ ВАХТ: Telegram + след в TASKS.md.

Повод (Егор, 21.08.2026):
  1. «как мы узнаем об изменении? нужно мониторить самостоятельно?»
     Вахта писала в лог pm2, который никто не читает. Результат наблюдения,
     о котором никто не узнаёт, наблюдением не является.
  2. «телеграм хорошо конечно! но я могу пропустить! таск в бэклог нужен».
     Верно: сообщение листается, а `TASKS.md` читается при старте КАЖДОЙ сессии
     (он в обязательном списке в CLAUDE.md).

Поэтому у изменения ТРИ независимых пути распространения:
    Telegram        — узнать сразу
    TASKS.md        — не потерять, если пропустил
    шина событий    — через `core/context/watch_bridge.py`, чтобы узнали ОСТАЛЬНЫЕ СФЕРЫ
                      (Куб: сферы общаются через шину, а не напрямую)

    from scripts._alert import notify
    notify("long_watch", "ALIVE", title="Лонг на 15m",
           tg_text="...", task_detail="перемерить полным протоколом")

🔑 Сообщения уходят ТОЛЬКО при смене состояния. Еженедельное «всё по-прежнему»
превращается в шум, который перестают читать.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "subscriptions.db")
TASKS = ROOT / "TASKS.md"
SECTION = "## 🔭 СРАБОТАВШИЕ ВАХТЫ"
logger = logging.getLogger(__name__)

NL = "\n"


def _creds() -> tuple[str, str] | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:  # noqa: BLE001
        pass
    token = (os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
             or os.environ.get("BOT_TOKEN") or "")
    chat = (os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_ID")
            or os.environ.get("TELEGRAM_ADMIN_ID") or "")
    if not chat:
        try:
            import yaml
            with open(ROOT / "config.yaml", encoding="utf-8") as f:
                chat = str(((yaml.safe_load(f) or {}).get("telegram") or {}).get("admin_id", ""))
        except Exception:  # noqa: BLE001
            pass
    return (token, chat) if token and chat else None


def alert(text: str, *, silent: bool = False) -> bool:
    """Сообщение админу. Любая ошибка — в лог, не наверх: оповещение не должно
    ронять скрипт, ради которого существует."""
    c = _creds()
    if c is None:
        logger.warning("[alert] нет TELEGRAM_TOKEN/ADMIN_ID — не отправлено")
        return False
    token, chat = c
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text[:4000], "parse_mode": "Markdown",
        "disable_notification": "true" if silent else "false",
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:  # noqa: BLE001
        logger.warning("[alert] отправка не удалась: %s", e)
        return False


def _ensure_table() -> None:
    with sqlite3.connect(DB, timeout=20) as c:
        c.execute("PRAGMA busy_timeout=10000")
        c.execute("CREATE TABLE IF NOT EXISTS watch_state ("
                  "key TEXT PRIMARY KEY, state TEXT NOT NULL, changed_at TEXT NOT NULL)")


def last_state(key: str) -> str | None:
    try:
        _ensure_table()
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10) as c:
            row = c.execute("SELECT state FROM watch_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001
        return None


def _save_state(key: str, state: str) -> None:
    try:
        _ensure_table()
        with sqlite3.connect(DB, timeout=20) as c:
            c.execute("PRAGMA busy_timeout=10000")
            c.execute("INSERT OR REPLACE INTO watch_state (key,state,changed_at) "
                      "VALUES (?,?,?)",
                      (key, state, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    except Exception as e:  # noqa: BLE001
        logger.warning("[alert] не смог сохранить состояние %s: %s", key, e)


def log_to_tasks(title: str, state: str, detail: str) -> bool:
    """
    Дописывает строку о срабатывании вахты в TASKS.md.

    Секция создаётся при первом срабатывании и живёт сразу после заголовка файла,
    чтобы попадаться на глаза раньше списка задач. Записи копятся, не затирая
    друг друга: история срабатываний — тоже информация.
    """
    try:
        text = TASKS.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("[alert] TASKS.md недоступен: %s", e)
        return False
    stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    row = "| " + stamp + " | **" + title + "** | `" + state + "` | " + detail + " |" + NL
    if SECTION in text:
        i = text.index(SECTION)
        sep = text.index("|---", i)                 # строка-разделитель таблицы
        j = text.index(NL, sep) + 1                 # сразу после неё
        text = text[:j] + row + text[j:]
    else:
        head_end = text.index(NL, text.index("# ")) + 1
        block = (NL + SECTION + NL + NL
                 + "> Пишется автоматически из фоновых вахт (`scripts/_alert.py`)." + NL
                 + "> Telegram можно пропустить — эта таблица читается при старте сессии." + NL + NL
                 + "| когда | вахта | состояние | что делать |" + NL
                 + "|---|---|---|---|" + NL)
        text = text[:head_end] + block + row + text[head_end:]
    try:
        TASKS.write_text(text, encoding="utf-8")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("[alert] не смог записать в TASKS.md: %s", e)
        return False


def notify(key: str, state: str, *, title: str, tg_text: str, task_detail: str,
           first_time: bool = False) -> dict:
    """
    Оповещение о смене состояния вахты: Telegram + след в TASKS.md.

    Состояние сохраняется в `watch_state`, откуда его подхватывает
    `core/context/watch_bridge.py` и публикует в шину событий — так узнают
    остальные сферы Куба. Мы никого не оповещаем напрямую, кроме админа.

    Возвращает {'tg': bool, 'tasks': bool, 'prev': str|None, 'state': str}.
    """
    prev = last_state(key)
    changed = prev != state
    _save_state(key, state)
    if not changed or (prev is None and not first_time):
        return {"tg": False, "tasks": False, "prev": prev, "state": state}
    sent = alert(tg_text)
    logged = log_to_tasks(title, state, task_detail)
    logger.info("[alert] %s: %s → %s · tg=%s · tasks=%s", key, prev, state, sent, logged)
    return {"tg": sent, "tasks": logged, "prev": prev, "state": state}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    c = _creds()
    print("учётные данные:", "найдены" if c else "🔴 НЕТ")
    if c:
        print(f"  chat_id: {c[1]}")
    if "--test" in sys.argv:
        print("отправка:", "✅ дошло" if alert("🔧 Проверка канала оповещений.") else "🔴 не дошло")
    elif "--test-task" in sys.argv:
        ok = log_to_tasks("Проверка", "TEST", "тестовая запись, можно удалить")
        print("запись в TASKS.md:", "✅" if ok else "🔴")
    else:
        print("  --test       проверить Telegram")
        print("  --test-task  проверить запись в TASKS.md")
