"""
watch_bridge.py — НАБЛЮДАТЕЛЬ ЗА ВНЕШНИМИ ВАХТАМИ.

Повод (Егор, 21.08.2026): «мы же умный куб создаём! все сферы общаются!»
Замечание было верным: первая версия вахты слала в Telegram напрямую, минуя
общую инфраструктуру. Обходной канал — о событии узнаёт один потребитель.

🔴 НО ПРОВЕРКА ПОКАЗАЛА, ЧТО В ШИНУ ЭТО НЕ ЛОЖИТСЯ.
`EventBus.publish(symbol, ...)` запускает Full CALL для КОНКРЕТНОЙ ПАРЫ, и
`SphereEvent` через `PairContext` тоже работает по паре. А вахты РЫНОЧНЫЕ —
пары у них нет. Публикация с symbol="MARKET" заставила бы шину анализировать
несуществующий символ. Рыночному контексту соответствует Сфера 5 (Cross-Market),
но и туда класть нечего, пока нет сферы, которая ИЗМЕНИТ ПОВЕДЕНИЕ, узнав
о смене режима. Событие без потребителя — шум, который учит игнорировать шину.

Поэтому здесь остался ЛОГ смены состояния, а рабочих каналов три:
    Telegram          — узнать сразу            (scripts/_alert.py)
    TASKS.md          — не потерять, читается при старте сессии
    watch_state (БД)  — любой процесс спросит состояние сам

Когда появится потребитель, меняющий поведение («зона открылась → поднять
приоритет сканирования 15m»), здесь добавится одна строка publish — и мост
станет полноценным ребром Куба. Не раньше.

    внешняя вахта (pm2)  →  watch_state  →  этот наблюдатель  →  лог + snapshot
       тяжёлый счёт          состояние        лёгкий опрос
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = str(Path(__file__).resolve().parents[2] / "subscriptions.db")

# Человекочитаемые описания вахт — для текста события.
_WATCHES = {
    "long_watch": {
        "title": "Лонг на 15m",
        "ALIVE": "🟢 ОЖИЛ — перемерить полным протоколом, затем обсудить sides",
        "DEAD": "⚪ снова мёртв",
        "NEAR": "🟡 приблизился к порогу оживления",
    },
    "drift_zone": {
        "title": "Зона дрейфа (short 15m)",
        "IN": "🟢 ЗОНА ОТКРЫЛАСЬ — гейт пропускает, пойдут сделки",
        "OUT": "⚪ зона закрылась — гейт снова блокирует",
    },
}


def _read_states() -> dict[str, tuple[str, str]]:
    """{key: (state, changed_at)} из таблицы, которую пишут внешние вахты."""
    try:
        with sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5) as c:
            rows = c.execute("SELECT key,state,changed_at FROM watch_state").fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}
    except sqlite3.Error:
        return {}


class WatchBridge:
    """
    Опрашивает состояния вахт и отмечает смену.

    Лёгкий: одно чтение таблицы за цикл, никаких расчётов — считают вахты.
    `snapshot()` отдаёт текущее состояние всем, кому оно нужно.
    """

    def __init__(self, event_bus, poll_sec: float = 300.0):
        self._bus = event_bus
        self._poll = poll_sec
        self._seen: dict[str, str] = {}

    async def poll_once(self) -> int:
        """Один опрос. Возвращает число замеченных смен состояния."""
        published = 0
        for key, (state, changed_at) in _read_states().items():
            if self._seen.get(key) == state:
                continue
            first = key not in self._seen
            self._seen[key] = state
            if first:
                # первый опрос после старта — запоминаем, но не шумим
                continue
            meta = _WATCHES.get(key, {})
            title = meta.get("title", key)
            what = meta.get(state, f"состояние: {state}")
            text = f"{title}: {what}"
            # 🔴 21.08 В ШИНУ НЕ ПУБЛИКУЕМ — и вот почему.
            # `EventBus.publish(symbol, ...)` запускает Full CALL для ЭТОЙ ПАРЫ,
            # а наши вахты РЫНОЧНЫЕ: пары у них нет. Публикация с symbol="MARKET"
            # заставила бы шину анализировать несуществующий символ.
            # Рыночному контексту в Кубе соответствует Сфера 5 (Cross-Market),
            # но и туда класть нечего, пока нет сферы, которая ИЗМЕНИТ ПОВЕДЕНИЕ,
            # узнав о смене режима. Событие без потребителя — шум.
            #
            # Что работает СЕЙЧАС: Telegram (узнать сразу) + TASKS.md (не потерять)
            # + таблица watch_state (любой процесс может спросить состояние).
            # Когда появится потребитель — здесь добавится одна строка publish.
            published += 1
            logger.info("[WatchBridge] %s → %s · %s", key, state, text)
        return published

    async def run(self) -> None:
        """Фоновый цикл. Отказ одного опроса не должен ронять цикл."""
        import asyncio
        logger.info("[WatchBridge] старт · опрос каждые %.0f сек", self._poll)
        while True:
            try:
                await self.poll_once()
            except Exception as e:                                # noqa: BLE001
                logger.warning("[WatchBridge] ошибка опроса: %s", e)
            await asyncio.sleep(self._poll)


def snapshot() -> str:
    """Текущее состояние всех вахт — для диагностики и дашборда."""
    st = _read_states()
    if not st:
        return "вахты ещё не отмечались"
    out = []
    for key, (state, changed) in sorted(st.items()):
        meta = _WATCHES.get(key, {})
        out.append(f"  {meta.get('title', key):<26} {state:<6} с {changed[:16]}")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("СОСТОЯНИЕ ВАХТ:")
    print(snapshot())
