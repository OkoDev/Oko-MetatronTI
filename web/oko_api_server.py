# -*- coding: utf-8 -*-
"""OKO API Server (:8001) — быстрый read-only API для дашборда, ОТДЕЛЬНЫЙ от бота процесс.

Корень «медленной доски» (03.07): dashboard_server живёт В процессе бота → GIL скана 520 пар
душит API (full_stats: 1.4с чистого SQL → 45с+ через бота; даже 135-байтовый статус = 2с).

Архитектура:
  • Тяжёлые READ-эндпоинты — ЛОКАЛЬНО из SQLite (WAL: конкурентное чтение, боту не мешаем) + кэш.
  • Live-поля бота (status/scan_health/btc_regime/ml) — фоновый рефреш у бота (не блокирует ответ).
  • ВСЁ остальное (POST /api/toggles, /api/settings, oracle, SSE...) — прозрачный прокси на :8000.

Запуск: python web/oko_api_server.py   ·   pm2: --name oko-api
Фронт: OKO_BOT_URL=http://localhost:8001 (next.config проксирует сюда; SSE у фронта и так на :8000).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.trading.performance_engine import PerformanceEngine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [oko-api] %(message)s")
log = logging.getLogger("oko-api")

BOT_URL = "http://127.0.0.1:8000"   # НЕ localhost: Windows IPv6-фоллбек = +2с на каждый коннект!
PORT = 8001
DB = "subscriptions.db"

_engine = PerformanceEngine(DB)
_cache: dict[str, tuple[float, object]] = {}
_live: dict = {"status": {}, "btc_regime": "N/A", "ml_status": "unknown",
               "ml_trained_at": None, "toggles": {}, "params": {}, "_age": None, "_ts": 0}


def _config_get(cfg: dict, dotted: str, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


async def _refresh_live_loop():
    """Фоново раз в 30с тянем live-блок у бота (терпим его медлительность тут, не в ответах)."""
    while True:
        try:
            async with ClientSession(timeout=ClientTimeout(total=25)) as s:
                async with s.get(f"{BOT_URL}/api/dashboard") as r:
                    if r.status == 200:
                        d = await r.json()
                        for k in ("status", "btc_regime", "ml_status", "ml_trained_at",
                                  "toggles", "params"):
                            if k in d:
                                _live[k] = d[k]
                        _live["_ts"] = time.time()
                        log.info("live-блок обновлён от бота")
        except Exception as e:  # noqa: BLE001
            log.info("live-блок: бот занят (%s) — отдаём последний известный", repr(e)[:40])
        await asyncio.sleep(30)


async def _run_sync(fn, *a):
    return await asyncio.get_event_loop().run_in_executor(None, fn, *a)


def _local_toggles_params() -> tuple[dict, dict]:
    """Toggles/params из config.yaml + констант dashboard_server (бот занят — собираем сами)."""
    try:
        import yaml
        from web.dashboard_server import _TOGGLES, _PARAMS
        cfg = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
        toggles = {k: {"label": lbl, "value": bool(_config_get(cfg, k, d))} for k, lbl, d in _TOGGLES}
        toggles["signal_quality.btc_filter_mode"] = {
            "label": "BTC Filter Mode",
            "value": _config_get(cfg, "signal_quality.btc_filter_mode", "shadow"),
            "options": ["shadow", "block", "off"],
        }
        params = {k: {"label": lbl, "value": _config_get(cfg, k, d), "min": mn, "max": mx, "step": st}
                  for k, lbl, d, mn, mx, st in _PARAMS}
        return toggles, params
    except Exception as e:  # noqa: BLE001
        log.info("local toggles fail: %s", repr(e)[:60])
        return {}, {}


def _cached(key: str, ttl: float):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


async def h_dashboard(request: web.Request) -> web.Response:
    data = _cached("dashboard", 30)
    if data is None:
        stats = await _run_sync(_engine.full_stats)
        summary = stats.get("summary", {})
        by_dir = stats.get("by_direction", [])
        trade_stats = {
            "open_count": summary.get("open_count", 0),
            "closed_count": summary.get("closed_count", 0),
            "win_rate": summary.get("win_rate", 0),
            "avg_r": summary.get("avg_r", 0),
            "long_count": sum(d.get("total", 0) for d in by_dir if d.get("direction") == "LONG"),
            "short_count": sum(d.get("total", 0) for d in by_dir if d.get("direction") == "SHORT"),
        }
        data = {"trade_stats": trade_stats, "full_stats": stats}
        _cache["dashboard"] = (time.time(), data)
    live_age = round(time.time() - _live["_ts"]) if _live["_ts"] else None
    toggles, params = _live["toggles"], _live["params"]
    if not toggles:                       # бот занят и live не пришёл — собираем из config.yaml
        toggles, params = _local_toggles_params()
    out = {
        "status": _live["status"], "btc_regime": _live["btc_regime"],
        "ml_status": _live["ml_status"], "ml_trained_at": _live["ml_trained_at"],
        "trade_stats": data["trade_stats"],
        "toggles": toggles, "params": params,
        "_live_age_sec": live_age, "_served_by": "oko-api",
    }
    return web.json_response(out, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))


async def h_feed(request: web.Request) -> web.Response:
    """Панель oko_feed: доминации + свежие on-chain события + BTC-флоу (для будущей вкладки)."""
    data = _cached("feed", 60)
    if data is None:
        def _collect():
            out = {"dominance": {}, "onchain_recent": [], "btc_flows_1h": {}, "usdtd_risk_off": None}
            try:
                from oko_feed import store
                try:
                    from core.signals.usdtd_regime import get_usdtd_risk_off
                    out["usdtd_risk_off"] = get_usdtd_risk_off()   # кэш 4ч внутри
                except Exception:
                    pass
                for asset in ("usdt", "btc", "eth"):
                    ser = store.dominance_series(asset)
                    if ser:
                        out["dominance"][asset] = {"date": ser[-1][0], "value": ser[-1][1]}
                import sqlite3
                c = sqlite3.connect("ohlcv_cache.db")
                rows = c.execute("""SELECT ts,kind,symbol,amount_usd,direction FROM onchain_events
                                    ORDER BY ts DESC LIMIT 30""").fetchall()
                out["onchain_recent"] = [
                    {"ts": r[0], "kind": r[1], "symbol": r[2], "usd": r[3], "dir": r[4]} for r in rows]
                c.close()
                fc = store.conn()
                cutoff = int(time.time()) - 3600
                inf = fc.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                                 "WHERE kind='btc_inflow' AND ts>?", (cutoff,)).fetchone()[0]
                outf = fc.execute("SELECT COALESCE(SUM(amount_usd),0) FROM onchain_events "
                                  "WHERE kind='btc_outflow' AND ts>?", (cutoff,)).fetchone()[0]
                fc.close()
                out["btc_flows_1h"] = {"inflow_btc": inf, "outflow_btc": outf,
                                       "net_btc": round(outf - inf, 2)}
            except Exception as e:  # noqa: BLE001
                out["error"] = str(e)[:120]
            return out
        data = await _run_sync(_collect)
        _cache["feed"] = (time.time(), data)
    return web.json_response(data)


async def h_proxy(request: web.Request) -> web.Response:
    """Прозрачный прокси всего остального на бота (POST/settings/oracle/...)."""
    url = f"{BOT_URL}{request.rel_url}"
    try:
        async with ClientSession(timeout=ClientTimeout(total=60)) as s:
            body = await request.read()
            async with s.request(request.method, url, data=body or None,
                                 headers={"Content-Type": request.headers.get("Content-Type", "application/json")}) as r:
                payload = await r.read()
                return web.Response(body=payload, status=r.status,
                                    content_type=r.content_type or "application/json")
    except Exception as e:  # noqa: BLE001
        return web.json_response({"error": f"bot unavailable: {e}"}, status=502)


def main():
    from web.local_guard import local_origin_guard      # SEC N1 (26.09): прокси снимает Origin → проверять ДО него
    app = web.Application(middlewares=[local_origin_guard])
    app.router.add_get("/api/dashboard", h_dashboard)
    app.router.add_get("/api/feed", h_feed)
    app.router.add_route("*", "/{tail:.*}", h_proxy)

    async def _on_start(app_):
        asyncio.create_task(_refresh_live_loop())
    app.on_startup.append(_on_start)
    log.info("OKO API server on :%d (dashboard local, feed local, rest -> proxy %s)", PORT, BOT_URL)
    web.run_app(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
