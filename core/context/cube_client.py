"""
cube_client.py — ПОРТ к шине Куба для процессов вне бота (ADR-003, шаг 3).

Те же три глагола, что в каноне «как слушать Куб» (`docs/BUS_SUBSCRIBER_ROADMAP.md`, LISTENER-CANON):

    PRODUCE   publish(event, symbol, data)      — сфера объявила факт
    PULL      snapshot(symbol) / snapshot()     — состояние пары / всех пар
    PUSH      subscribe(types, handler)         — поток фактов (WebSocket)
              facts(since=, types=)             — журнал фактов по id (переиграть после простоя)

Внутри процесса бота шина остаётся синхронной (`PairContextBus`) — здесь порт для СПУТНИКОВ.
Транспорт спрятан: смена хаба на брокер — правка одного этого файла (ADR-001, «подключение, а не
встраивание»).

🔑 Правила (ADR-003):
  • **торговых команд через шину нет.** Спутник публикует ФАКТ «увидел сетап»; регистрирует и
    исполняет сделку только бот, по своим `signal_router.source_policies`;
  • хаб недоступен → `publish` возвращает False и НЕ бросает: спутник продолжает работу;
  • токен читается из `oko_feed/cube_hub.token` (его создаёт хаб; браузер файл не прочитает).

    from core.context.cube_client import publish
    publish("signal_detected", "GRT/USDT:USDT", {"signal_type": "breakout", "direction": "LONG", ...})
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = ROOT / "oko_feed" / "cube_hub.token"
DEFAULT_URL = "http://127.0.0.1:8020"
_token: Optional[str] = None
_seq = 0
_warned = False


def _url() -> str:
    try:
        from core.infra.config_loader import config
        return str((config.get("cube_hub", {}) or {}).get("url") or DEFAULT_URL).rstrip("/")
    except Exception:                                   # noqa: BLE001 — спутник без конфига
        return DEFAULT_URL


def _get_token() -> str:
    global _token
    if _token is None:
        _token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return _token


def _post(path: str, payload: dict, timeout: float = 5.0) -> bool:
    global _token, _warned
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(f"{_url()}{path}", data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Cube-Token": _get_token()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _warned = False
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 401:
            _token = None                               # хаб мог пересоздать токен
        logger.warning("[cube] %s: HTTP %s", path, e.code)
        return False
    except Exception as e:                              # noqa: BLE001 — хаб лёг: не роняем спутника
        if not _warned:
            _warned = True
            logger.warning("[cube] хаб недоступен (%s) — работаем без шины", e)
        return False


def publish(event: str, symbol: str, data: dict, producer: str = "satellite") -> bool:
    """Факт в шину. True — принят хабом. Хаб недоступен → False, исключения не бросаются."""
    global _seq
    _seq += 1
    return _post("/publish", {"producer": producer, "items": [
        {"k": "f", "sym": symbol, "ev": event, "data": data, "ts": time.time(), "seq": _seq}]})


def _get(path: str, timeout: float = 15.0):
    try:
        with urllib.request.urlopen(f"{_url()}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:                              # noqa: BLE001
        logger.debug("[cube] GET %s: %s", path, e)
        return None


def snapshot(symbol: Optional[str] = None) -> Optional[dict]:
    """Состояние пары (+`_age_sec`) или всех пар. None — хаб недоступен.
    🔑 Возраст проверяет ЧИТАТЕЛЬ: доска переживает рестарт бота, но может быть несвежей."""
    if symbol:
        return _get(f"/state/{symbol.replace('/', '_').replace(':USDT', '')}")
    return _get("/state")


def facts(since: int = 0, types: Optional[Iterable[str]] = None, limit: int = 500,
          last: Optional[int] = None) -> list[dict]:
    """Журнал фактов: после `since` (переиграть пропущенное) либо `last` последних."""
    q = f"/facts?since={int(since)}&limit={int(limit)}"
    if types:
        q += "&types=" + ",".join(types)
    if last:
        q += f"&last={int(last)}"
    d = _get(q)
    return (d or {}).get("facts", [])


def subscribe(types: Iterable[str], handler: Callable[[dict], None], *,
              reconnect_sec: float = 5.0, stop: Optional[Callable[[], bool]] = None) -> None:
    """Блокирующая подписка на поток фактов (WebSocket). Разрыв → переподключение.

    Пропущенное за время разрыва ДОБИРАЕТСЯ из журнала по `id` — иначе факты теряются молча.
    Требует `websocket-client`; нет его → падаем на опрос журнала раз в reconnect_sec.
    """
    types = list(types)
    last_id = 0
    for f in facts(last=1, types=types):
        last_id = f["id"]
    while not (stop and stop()):
        try:
            import websocket                             # type: ignore
        except ImportError:
            for f in facts(since=last_id, types=types):
                last_id = max(last_id, f["id"])
                handler(f)
            time.sleep(reconnect_sec)
            continue
        try:
            ws = websocket.create_connection(
                f"{_url().replace('http://', 'ws://')}/ws?types={','.join(types)}", timeout=30)
            for f in facts(since=last_id, types=types):   # добор за время разрыва
                last_id = max(last_id, f["id"])
                handler(f)
            while not (stop and stop()):
                msg = ws.recv()
                if not msg:
                    break
                f = json.loads(msg)
                last_id = max(last_id, int(f.get("id") or 0))
                handler(f)
            ws.close()
        except Exception as e:                            # noqa: BLE001
            logger.debug("[cube] поток прерван: %s", e)
            time.sleep(reconnect_sec)
