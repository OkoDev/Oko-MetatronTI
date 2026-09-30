"""
cube_hub.py — хаб шины Куба (ADR-003): доска состояний пар + журнал фактов для ВСЕХ процессов.

Центр главного Куба живёт отдельно от бота: бот (Sub-куб «торговый контур») зеркалит сюда свою
шину (`core/context/cube_mirror.py`), остальные процессы читают отсюда, а не из HTTP бота.
Доска переживает рестарт бота.

    POST /publish            пачка от производителя (токен X-Cube-Token; запрос с Origin — отказ)
    GET  /state              все пары: {"coins": {sym: state}, "n", "ts", "max_age_sec"}
    GET  /state/{symbol}     состояние пары (+ "_ts", "_age_sec"); символ в любом формате
    GET  /facts?since=&types=&limit=   журнал фактов по id  (?last=N — N последних, лента дашборда)
    GET  /ws?types=a,b       поток фактов (WebSocket)
    GET  /stats              производители, разрывы seq, задержка p50/p95, размеры

Правила (ADR-003): хаб ничего НЕ считает — хранит и раздаёт (один калькулятор на признак);
писатель `oko_feed/cube.db` один — сам хаб; слушает только 127.0.0.1.

Запуск: python scripts/cube_hub.py [--port 8020]   (pm2: cube-hub)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sqlite3
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

from aiohttp import WSMsgType, web

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.context.pair_context import PairContextBus  # noqa: E402 — только canon(), без состояния

FEED = ROOT / "oko_feed"
DB_PATH = FEED / "cube.db"
TOKEN_FILE = FEED / "cube_hub.token"
logger = logging.getLogger("cube_hub")


def ensure_token(path: Path = TOKEN_FILE) -> str:
    """Токен публикации: файл читают локальные процессы, браузер — нет (урок CSRF :8010)."""
    if path.exists():
        tok = path.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_hex(24)
    path.write_text(tok, encoding="utf-8")
    return tok


def _pctl(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * len(s)))], 3)


class Hub:
    """Состояние хаба без сети — чтобы проверялось тестами напрямую."""

    def __init__(self, db_path: Path = DB_PATH, retention_days: float = 30.0):
        self.retention_days = retention_days
        self.states: dict[str, tuple[float, float, str]] = {}   # sym → (ts производителя, приём, JSON)
        self._dirty_db: set[str] = set()
        self.producers: dict[str, dict] = defaultdict(
            lambda: {"last_seq": 0, "items": 0, "gaps": 0, "lost": 0, "restarts": 0, "last_recv": 0.0})
        self.lat = {"s": deque(maxlen=2000), "f": deque(maxlen=2000)}
        self.bad_items = 0
        self.started = time.time()
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (symbol TEXT PRIMARY KEY, ts REAL, json TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "producer TEXT, seq INTEGER, ts REAL, recv REAL, symbol TEXT, event TEXT, json TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS facts_event ON facts(event, id)")
        self.db.commit()
        for sym, ts, js in self.db.execute("SELECT symbol, ts, json FROM state"):
            self.states[sym] = (ts, ts, js)            # после рестарта — снимок с диска, возраст честный

    # ── приём ──
    def apply(self, producer: str, items: list, recv: float | None = None) -> list[dict]:
        """Применить пачку. Возвращает принятые факты (для рассылки подписчикам)."""
        recv = recv or time.time()
        p = self.producers[producer]
        facts_rows, facts_out = [], []
        for it in items:
            try:
                seq = int(it["seq"])
                if p["last_seq"] and seq <= p["last_seq"]:
                    p["restarts"] += 1                   # производитель перезапустился — seq с начала
                elif p["last_seq"] and seq > p["last_seq"] + 1:
                    p["gaps"] += 1
                    p["lost"] += seq - p["last_seq"] - 1
                p["last_seq"] = seq
                p["items"] += 1
                ts = float(it.get("ts") or recv)
                sym = PairContextBus.canon(str(it["sym"]))
                if it["k"] == "s":
                    self.states[sym] = (ts, recv, json.dumps(it["st"], ensure_ascii=False))
                    self._dirty_db.add(sym)
                    self.lat["s"].append(recv - ts)
                elif it["k"] == "f":
                    data_js = json.dumps(it.get("data") or {}, ensure_ascii=False)
                    facts_rows.append((producer, seq, ts, recv, sym, it["ev"], data_js))
                    self.lat["f"].append(recv - ts)
                else:
                    self.bad_items += 1
            except Exception:                                    # noqa: BLE001 — кривой элемент не роняет пачку
                self.bad_items += 1
        p["last_recv"] = recv
        if facts_rows:
            with self.db:
                for row in facts_rows:
                    cur = self.db.execute("INSERT INTO facts (producer, seq, ts, recv, symbol, event, json) "
                                          "VALUES (?,?,?,?,?,?,?)", row)
                    facts_out.append({"id": cur.lastrowid, "producer": row[0], "seq": row[1], "ts": row[2],
                                      "symbol": row[4], "event": row[5], "data": json.loads(row[6])})
        return facts_out

    # ── хранение ──
    def snapshot_to_db(self) -> int:
        if not self._dirty_db:
            return 0
        dirty, self._dirty_db = self._dirty_db, set()
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO state (symbol, ts, json) VALUES (?,?,?)",
                                [(s, self.states[s][0], self.states[s][2]) for s in dirty if s in self.states])
        return len(dirty)

    def purge(self, now: float | None = None) -> int:
        cut = (now or time.time()) - self.retention_days * 86400
        with self.db:
            return self.db.execute("DELETE FROM facts WHERE recv < ?", (cut,)).rowcount

    # ── чтение ──
    def state_json(self, symbol: str, now: float | None = None) -> str | None:
        rec = self.states.get(PairContextBus.canon(symbol))
        if rec is None:
            return None
        ts, _, js = rec
        age = round((now or time.time()) - ts, 1)
        return js[:-1] + (',' if js != '{}' else '') + f'"_ts": {ts}, "_age_sec": {age}}}'

    def all_states_json(self, now: float | None = None) -> str:
        now = now or time.time()
        parts = [json.dumps(s, ensure_ascii=False) + ":" + js for s, (_, _, js) in self.states.items()]
        ages = [now - ts for ts, _, _ in self.states.values()]
        max_age = round(max(ages, default=0.0), 1)
        p50 = _pctl(ages, 0.5)
        return ('{"coins": {' + ",".join(parts) + '}, "n": %d, "ts": %.3f, "max_age_sec": %s, "age_p50_sec": %s}'
                % (len(self.states), now, max_age, "null" if p50 is None else round(p50, 1)))

    def facts(self, since: int = 0, types: list[str] | None = None, limit: int = 500,
              last: int | None = None) -> list[dict]:
        """Факты по возрастанию id: после `since`, либо `last` последних (лента дашборда)."""
        q = "SELECT id, producer, seq, ts, symbol, event, json FROM facts WHERE id > ?"
        args: list = [since]
        if types:
            q += " AND event IN (%s)" % ",".join("?" * len(types))
            args += types
        q += " ORDER BY id DESC LIMIT ?" if last else " ORDER BY id LIMIT ?"
        args.append(min(max(1, last or limit), 5000))
        rows = [{"id": r[0], "producer": r[1], "seq": r[2], "ts": r[3], "symbol": r[4], "event": r[5],
                 "data": json.loads(r[6])} for r in self.db.execute(q, args)]
        return rows[::-1] if last else rows

    def stats(self) -> dict:
        now = time.time()
        ages = [now - ts for ts, _, _ in self.states.values()]
        n_facts = self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        return {
            "uptime_sec": round(now - self.started),
            "states": len(self.states),
            "state_age_p50": _pctl(ages, 0.5), "state_age_max": round(max(ages), 1) if ages else None,
            "facts": n_facts,
            "latency_state_p50": _pctl(self.lat["s"], 0.5), "latency_state_p95": _pctl(self.lat["s"], 0.95),
            "latency_fact_p50": _pctl(self.lat["f"], 0.5), "latency_fact_p95": _pctl(self.lat["f"], 0.95),
            "bad_items": self.bad_items,
            "producers": {k: dict(v, last_recv_age=round(now - v["last_recv"], 1) if v["last_recv"] else None)
                          for k, v in self.producers.items()},
        }


# ── HTTP ─────────────────────────────────────────────────────────────────────

def make_app(hub: Hub, token: str) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    subs: set = set()                                   # (ws, frozenset типов | None)
    app["subs"] = subs

    def _json(text: str, status: int = 200) -> web.Response:
        return web.Response(text=text, status=status, content_type="application/json", charset="utf-8")

    async def publish(req: web.Request) -> web.Response:
        if req.headers.get("Origin"):
            return _json('{"error": "origin"}', 403)    # браузерная страница не публикует
        if req.headers.get("X-Cube-Token") != token:
            return _json('{"error": "token"}', 401)
        body = await req.json()
        facts = hub.apply(str(body.get("producer") or "?"), body.get("items") or [])
        for f in facts:
            msg = json.dumps(f, ensure_ascii=False)
            for ws, types in list(subs):
                if types is None or f["event"] in types:
                    try:
                        await ws.send_str(msg)
                    except Exception:                    # noqa: BLE001 — отвалившийся подписчик
                        subs.discard((ws, types))
        return _json('{"ok": true}')

    async def state_all(req: web.Request) -> web.Response:
        return _json(hub.all_states_json())

    async def state_one(req: web.Request) -> web.Response:
        js = hub.state_json(req.match_info["symbol"].replace("_", "/"))
        return _json(js) if js is not None else _json('{"error": "unknown symbol"}', 404)

    async def facts(req: web.Request) -> web.Response:
        types = [t for t in req.query.get("types", "").split(",") if t] or None
        rows = hub.facts(int(req.query.get("since", 0) or 0), types, int(req.query.get("limit", 500) or 500),
                         last=int(req.query["last"]) if req.query.get("last") else None)
        return _json(json.dumps({"facts": rows}, ensure_ascii=False))

    async def ws_stream(req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(req)
        types = frozenset(t for t in req.query.get("types", "").split(",") if t) or None
        entry = (ws, types)
        subs.add(entry)
        try:
            async for msg in ws:
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            subs.discard(entry)
        return ws

    async def stats(req: web.Request) -> web.Response:
        st = hub.stats()
        st["ws_subscribers"] = len(subs)
        return _json(json.dumps(st, ensure_ascii=False))

    app.router.add_post("/publish", publish)
    app.router.add_get("/state", state_all)
    app.router.add_get("/state/{symbol}", state_one)
    app.router.add_get("/facts", facts)
    app.router.add_get("/ws", ws_stream)
    app.router.add_get("/stats", stats)
    return app


async def _housekeeping(hub: Hub, snapshot_sec: float = 30.0, log_sec: float = 300.0) -> None:
    last_purge = last_log = 0.0
    while True:
        await asyncio.sleep(snapshot_sec)
        try:
            hub.snapshot_to_db()
            now = time.monotonic()
            if now - last_purge >= 3600:
                last_purge = now
                n = hub.purge()
                if n:
                    logger.info("[CUBE-HUB] журнал: удалено %d фактов старше %.0f дн", n, hub.retention_days)
            if now - last_log >= log_sec:
                last_log = now
                logger.info("[CUBE-HUB] %s", json.dumps(hub.stats(), ensure_ascii=False))
        except Exception as e:                           # noqa: BLE001
            logger.warning("[CUBE-HUB] обслуживание: %s", e)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--retention-days", type=float, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    retention = args.retention_days
    if retention is None:
        try:
            import yaml
            cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
            retention = float((cfg.get("cube_hub") or {}).get("retention_days", 30))
        except Exception:                                # noqa: BLE001
            retention = 30.0
    hub = Hub(DB_PATH, retention)
    app = make_app(hub, ensure_token())

    async def _start_bg(app_):
        app_["hk"] = asyncio.create_task(_housekeeping(hub))

    async def _stop_bg(app_):
        app_["hk"].cancel()
        hub.snapshot_to_db()                             # снимок при остановке

    app.on_startup.append(_start_bg)
    app.on_cleanup.append(_stop_bg)
    logger.info("[CUBE-HUB] старт 127.0.0.1:%d · пар из снимка %d · журнал %.0f дн",
                args.port, len(hub.states), retention)
    web.run_app(app, host="127.0.0.1", port=args.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
