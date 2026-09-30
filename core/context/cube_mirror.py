"""
cube_mirror.py — бот зеркалит свою шину в хаб Куба (ADR-003, шаг 1: хаб в тени).

Синхронная шина (`PairContextBus`) остаётся в боте — так устроен любой Sub-куб. Зеркало только
копирует её наружу, чтобы доска пережила рестарт бота и была видна другим процессам:

    publish/update ──► пара «грязная» ─┐  раз в flush_sec (в цикле событий):
    факт ──► JSON в очередь сразу      │  грязные + N давно не отправленных пар → JSON в очередь
                                       ▼
                          очередь (ограниченная, старое выбрасывается со счётчиком)
                                       ▼
                          поток-отправщик ──► POST {url}/publish (пачкой, токен)

🔑 Круговой досыл нужен не «на всякий случай»: часть кода пишет поля пары напрямую
(`state.btc_regime = …`) мимо publish/update — без досыла хаб видел бы их устаревшими.
Он же сам восстанавливает хаб после рестарта хаба (полный круг по ~580 парам ≈ 30 с при 20/тик).

🔴 Состояние = ВСЕ поля PairState, а не `get_full_state()`: та выборка не отдаёт фандинг, OI, волны —
класс ошибки «API-дырка» (25.07 smc/pivot, 29.09 оборот). Ключи те же — формат /api/cube/context не ломается.

Публикация никогда не блокирует скан: крючки в цикле событий делают только set.add / json.dumps,
сеть — в отдельном потоке. Хаб лёг — бот торгует как раньше, очередь копит, лишнее выбрасывает.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import queue
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

from core.context.bus_catalog import event_class
from core.context.pair_context import PairState

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(__file__).resolve().parents[2] / "oko_feed" / "cube_hub.token"
PRODUCER = "oko-bot"
_FIELDS = [f.name for f in dataclasses.fields(PairState)]


def pair_state_dict(state: PairState) -> dict:
    """Все поля пары — то, что уходит в хаб."""
    return {name: getattr(state, name) for name in _FIELDS}


class CubeMirror:
    def __init__(self, bus, url: str, flush_sec: float = 1.0, rolling_per_tick: int = 20,
                 queue_max: int = 20000, batch_max: int = 400, token_file: Path = TOKEN_FILE):
        self._bus = bus
        self._url = url.rstrip("/")
        self._flush_sec = flush_sec
        self._roll = rolling_per_tick
        self._batch_max = batch_max
        self._token_file = token_file
        self._token: Optional[str] = None
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)   # (kind, json_str)
        self._dirty: set[str] = set()
        self._sent_at: dict[str, float] = {}                   # символ → когда состояние ушло в очередь
        self._seq = 0
        self._stop = threading.Event()
        self.sent = 0
        self.dropped = {"state": 0, "fact": 0}
        self.errors = 0
        self.last_error = ""
        self.last_ok = 0.0

    # ── крючки из PairContextBus: в цикле событий, только дешёвые операции ──
    def on_publish(self, symbol: str, event_type: str, data: dict) -> None:
        self._dirty.add(symbol)
        if event_class(event_type) == "fact":
            self._put("fact", json.dumps(
                {"k": "f", "sym": symbol, "ev": event_type, "data": data or {},
                 "ts": time.time(), "seq": self._next()},
                ensure_ascii=False, default=str))

    def on_update(self, symbol: str) -> None:
        self._dirty.add(symbol)

    # ── очередь ──
    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def _put(self, kind: str, payload: str) -> None:
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            try:                                # выбрасываем самое старое — свежее важнее
                old_kind, _ = self._q.get_nowait()
                self.dropped[old_kind] = self.dropped.get(old_kind, 0) + 1
            except queue.Empty:
                pass
            try:
                self._q.put_nowait((kind, payload))
            except queue.Full:
                self.dropped[kind] = self.dropped.get(kind, 0) + 1

    def flush_states(self) -> int:
        """Грязные пары + N давно не отправленных → в очередь. Возвращает число пар."""
        now = time.monotonic()
        syms, self._dirty = self._dirty, set()
        states = self._bus._states                     # не get(): незнакомую пару не создаём
        if self._roll > 0:
            rest = [s for s in states if s not in syms]
            rest.sort(key=lambda s: self._sent_at.get(s, 0.0))
            syms.update(rest[:self._roll])
        n = 0
        for sym in syms:
            st = states.get(sym)
            if st is None:
                continue
            self._put("state", json.dumps(
                {"k": "s", "sym": sym, "st": pair_state_dict(st), "ts": time.time(), "seq": self._next()},
                ensure_ascii=False, default=str))
            self._sent_at[sym] = now
            n += 1
        return n

    # ── отправка (отдельный поток) ──
    def _read_token(self) -> str:
        if self._token is None:
            self._token = self._token_file.read_text(encoding="utf-8").strip()
        return self._token

    def _post(self, body: bytes) -> None:
        req = urllib.request.Request(
            f"{self._url}/publish", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Cube-Token": self._read_token()})
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}")

    def _sender(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                items = [self._q.get(timeout=1.0)[1]]
            except queue.Empty:
                continue
            while len(items) < self._batch_max:
                try:
                    items.append(self._q.get_nowait()[1])
                except queue.Empty:
                    break
            body = ('{"producer":"%s","items":[%s]}' % (PRODUCER, ",".join(items))).encode("utf-8")
            while not self._stop.is_set():
                try:
                    self._post(body)
                    self.sent += len(items)
                    self.last_ok = time.time()
                    backoff = 1.0
                    break
                except Exception as e:                         # noqa: BLE001 — хаб лёг: ждём и повторяем
                    self.errors += 1
                    self.last_error = str(e)[:200]
                    if "401" in self.last_error:
                        self._token = None                     # хаб мог пересоздать токен
                    time.sleep(backoff)
                    backoff = min(30.0, backoff * 2)

    def stats(self) -> dict:
        return {"sent": self.sent, "queued": self._q.qsize(), "dropped": dict(self.dropped),
                "errors": self.errors, "last_error": self.last_error,
                "last_ok_age_sec": round(time.time() - self.last_ok, 1) if self.last_ok else None}

    async def run(self, log_every_sec: float = 300.0) -> None:
        threading.Thread(target=self._sender, daemon=True, name="cube-mirror").start()
        logger.info("[CUBE-MIRROR] старт → %s · сброс каждые %.1f с · круговой досыл %d/тик",
                    self._url, self._flush_sec, self._roll)
        last_log = time.monotonic()
        while True:
            await asyncio.sleep(self._flush_sec)
            try:
                self.flush_states()
            except Exception as e:                             # noqa: BLE001 — зеркало не роняет бота
                logger.warning("[CUBE-MIRROR] ошибка сброса: %s", e)
            if time.monotonic() - last_log >= log_every_sec:
                last_log = time.monotonic()
                logger.info("[CUBE-MIRROR] %s", self.stats())
