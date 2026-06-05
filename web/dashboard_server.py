"""
Лёгкий aiohttp-дашборд для мониторинга симулированных сделок.
Запускается как фоновая задача внутри event loop бота.

Эндпоинты:
  GET /                     — HTML-дашборд (авто-обновление каждые 30 сек)
  GET /api/stats            — полная статистика в JSON
  GET /settings             — страница настроек бота
  GET /api/settings         — текущие настройки в JSON
  POST /api/settings        — сохранить и применить настройки
  GET /backtest             — страница бэктестинга
  GET /api/backtest/results — последние результаты бэктеста (JSON)
  GET /api/backtest/status  — статус запуска (running/idle)
  POST /api/backtest/run    — запустить бэктест в фоне
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from pathlib import Path
from aiohttp import web

from core.trading.performance_engine import PerformanceEngine



logger = logging.getLogger(__name__)

# _HTML moved to web/static/


# _SETTINGS_HTML moved to web/static/
# _BACKTEST_HTML moved to web/static/

# ── SSE broadcast: список активных dashboard-клиентов ──────────────────────
# Каждый элемент — asyncio.Queue, в которую кладём строки SSE-событий.
_sse_dashboard_clients: list = []


async def _sse_broadcast(event_str: str) -> None:
    """Отправить сырую SSE-строку всем подключённым dashboard-клиентам."""
    dead = []
    for q in _sse_dashboard_clients:
        try:
            q.put_nowait(event_str)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _sse_dashboard_clients.remove(q)
        except ValueError:
            pass


async def _handle_index(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/index.html")


# DEV-231 (30.05): тяжёлые SQL handlers вынесены в thread pool через run_in_executor.
# Корень: 823 RequestHandler slow callbacks / 5 мин, total 968s блокировок event loop.
# sync_time HTTP стояли в очереди → timestamp invalid (recvWindow=5000ms expired).
async def _run_sync(fn, *args, **kwargs):
    """Helper: запустить sync функцию в thread pool, не блокируя event loop."""
    _loop = asyncio.get_running_loop()
    return await _loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _handle_confluence_breakdown(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = await _run_sync(engine.confluence_breakdown)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_breakeven_stats(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = await _run_sync(engine.breakeven_stats)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


def _analytics_compute_sync(engine) -> dict:
    """4 sync вызова engine — выполняются в thread pool. DEV-231."""
    return {
        "by_session":    engine.by_session(),
        "r_distribution": engine.r_distribution(),
        "pnl_calendar":  engine.pnl_calendar(),
        "mfe_scatter":   engine.mfe_scatter(),
    }


async def _handle_analytics(request: web.Request) -> web.Response:
    """GET /api/stats/analytics — данные для DEV-116 графиков."""
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = await _run_sync(_analytics_compute_sync, engine)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("analytics error: %s", e)
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_equity(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        # DEV-231: тяжёлый payload (3.77 MB) — sync вычисление + JSON serialize в thread pool
        data = await _run_sync(engine.equity_data)
        payload_str = await _run_sync(json.dumps, data, ensure_ascii=False, default=str)
        return web.Response(
            text=payload_str,
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


def _signal_weights_compute_sync(engine, days: int) -> dict:
    """DEV-231: SQL + pivot для signal_weights_history — выполняется в thread pool."""
    import sqlite3 as _sqlite3
    db_path = engine.db_path if hasattr(engine, "db_path") else "subscriptions.db"
    with _sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = _sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT computed_at, signal_type, adapted_weight, base_weight,
                   ema_avg_r, full_avg_r, n_trades, method, half_life
            FROM signal_weights_history
            WHERE computed_at >= datetime('now', ?)
            ORDER BY computed_at ASC
            """,
            (f"-{days} days",),
        )
        rows = [dict(r) for r in cur.fetchall()]
    points: Dict[str, Dict[str, Any]] = {}
    base_weights: Dict[str, float] = {}
    ema_r_by_point: Dict[str, Dict[str, float]] = {}
    signal_types: set = set()
    for r in rows:
        t = r["computed_at"]
        st = r["signal_type"]
        signal_types.add(st)
        p = points.setdefault(t, {"t": t, "weights": {}})
        p["weights"][st] = r["adapted_weight"]
        ema_r_by_point.setdefault(t, {})[st] = r["ema_avg_r"]
        if r["base_weight"] is not None:
            base_weights[st] = r["base_weight"]
    ordered_points = [
        {"t": t, "weights": points[t]["weights"], "ema_avg_r": ema_r_by_point.get(t, {})}
        for t in sorted(points.keys())
    ]
    return {
        "days": days,
        "signal_types": sorted(signal_types),
        "points": ordered_points,
        "base_weights": base_weights,
    }


async def _handle_signal_weights_history(request: web.Request) -> web.Response:
    """DEV-177: GET /api/signal_weights/history?days=14 — траектория адаптивных весов.

    Возвращает pivot-структуру для SVG multi-line chart в дашборде.
    """
    engine: PerformanceEngine = request.app["engine"]
    try:
        days = int(request.query.get("days", "14"))
    except (TypeError, ValueError):
        days = 14
    days = max(1, min(days, 90))

    try:
        # DEV-231: SQL + pivot в thread pool
        data = await _run_sync(_signal_weights_compute_sync, engine, days)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("signal_weights_history error: %s", e)
        return web.Response(
            text=json.dumps({"error": str(e)}),
            content_type="application/json",
            status=500,
        )


def _current_price_from_cache(dc, symbol: str):
    """Берёт последнюю цену закрытия из кеша OHLCV (без API-запроса)."""
    try:
        cache = getattr(dc, "_ohlcv_cache", {})
        for tf in ("15m", "1m", "5m", "1h"):
            entry = cache.get((symbol, tf))
            if entry and "df" in entry and not entry["df"].empty:
                return float(entry["df"]["close"].iloc[-1])
    except Exception:
        pass
    return None


_STATS_CACHE = {"payload": None, "ts": 0.0, "ttl": 5.0}
_STATS_LOCK = None   # lazy init в _handle_stats (asyncio.Lock требует running loop)


async def _handle_stats(request: web.Request) -> web.Response:
    global _STATS_LOCK
    if _STATS_LOCK is None:
        import asyncio as _aio
        _STATS_LOCK = _aio.Lock()
    """GET /api/stats — D-074 (26.05): cache TTL=5s. Per-client aggregation
    блокировала event loop при N клиентах × 5s polling (SSE inline call)."""
    import time as _time
    now = _time.time()
    cached = _STATS_CACHE["payload"]
    if cached is not None and (now - _STATS_CACHE["ts"]) < _STATS_CACHE["ttl"]:
        return web.Response(
            text=cached,
            content_type="application/json", charset="utf-8",
            headers={"X-Cache": "HIT", "X-Cache-Age": f"{now - _STATS_CACHE['ts']:.1f}"},
        )

    async with _STATS_LOCK:
        # Double-check: первый клиент через lock мог уже заполнить cache
        now2 = _time.time()
        cached2 = _STATS_CACHE["payload"]
        if cached2 is not None and (now2 - _STATS_CACHE["ts"]) < _STATS_CACHE["ttl"]:
            return web.Response(
                text=cached2,
                content_type="application/json", charset="utf-8",
                headers={"X-Cache": "HIT-LOCK", "X-Cache-Age": f"{now2 - _STATS_CACHE['ts']:.1f}"},
            )
        return await _stats_compute_and_cache(request)


def _compute_stats_payload_sync(engine, dc, bot) -> str:
    """DEV-231 (30.05): тяжёлая sync часть _handle_stats для run_in_executor.
    Раньше блокировала event loop на 1.24s avg (493s/5min из task sampler).
    SQL + open_trades enrichment + JSON dumps теперь в thread pool, не event loop.
    """
    data = engine.full_stats()
    # Обогащаем open_trades текущей ценой, нереализованным P&L и MFE
    for t in data.get("open_trades", []):
        cur = _current_price_from_cache(dc, t["symbol"]) if dc else None
        t["current_price"] = cur
        ep = t.get("entry_price") or 0
        osl = t.get("original_sl") or None
        sl  = t.get("stop_loss") or None
        direction = t.get("direction", "LONG")
        # 27.05.2026 (r_math refactor): все вычисления R через core.trading.r_math.
        # 1R = |entry - original_sl| (исходный риск); если NULL → fallback на текущий
        # stop_loss. Sanity clamp [-15,+15] защищает от sl_dist≈0 артефактов
        # (#15101 SWARMS показал +8103R через текущий stop_loss).
        from core.trading.r_math import compute_one_r, compute_r, clamp_r
        one_r, _r_src = compute_one_r(ep, osl, fallback_sl=sl)
        if cur is not None and ep:
            if direction == "LONG":
                pnl_pct = (cur - ep) / ep * 100
            else:
                pnl_pct = (ep - cur) / ep * 100
            t["unrealized_pct"] = round(pnl_pct, 2)
            _r = compute_r(direction, ep, cur, one_r) if one_r else None
            _r = clamp_r(_r)
            t["unrealized_r"] = round(_r, 2) if _r is not None else None
        else:
            t["unrealized_pct"] = None
            t["unrealized_r"] = None
        # MFE: max R достигнутый за время жизни сделки. Тоже от original_sl.
        max_r = t.get("max_R_possible")
        if max_r is None and ep and one_r:
            max_p = t.get("max_price")
            min_p = t.get("min_price")
            _peak = float(max_p) if direction == "LONG" and max_p else (
                    float(min_p) if direction == "SHORT" and min_p else None)
            if _peak is not None:
                max_r = clamp_r(compute_r(direction, ep, _peak, one_r))
        t["mfe_r"] = round(max_r, 2) if max_r is not None else None
        # Cascade level из features_json
        try:
            fj = t.get("features_json")
            if fj:
                import json as _json
                _fj = _json.loads(fj) if isinstance(fj, str) else fj
                t["cascade_level"] = _fj.get("cascade_level") or _fj.get("tsl_tf")
                t["signal_mode"] = _fj.get("signal_mode") or _fj.get("trigger_source")
                confs = _fj.get("confirmations") or []
                t["conf_sources"] = [c.get("source", "") for c in confs if isinstance(c, dict)]
            else:
                t["cascade_level"] = t.get("tsl_tf")
                t["signal_mode"] = None
                t["conf_sources"] = []
        except Exception:
            t["cascade_level"] = t.get("tsl_tf")
            t["signal_mode"] = None
            t["conf_sources"] = []

    # BTC 4h regime
    btc_4h_regime = None
    if bot:
        _cache = getattr(bot, "_btc_4h_regime_cache", None)
        if _cache:
            btc_4h_regime = _cache.get("regime")

    # Risk Exposure + Open P&L R
    open_trades = data.get("open_trades", [])
    deposit_usdt = 1000.0
    risk_pct = 1.0
    try:
        import sqlite3 as _sqlite3
        db_path = engine.db_path if hasattr(engine, "db_path") else "subscriptions.db"
        with _sqlite3.connect(db_path) as _conn:
            _row = _conn.execute(
                "SELECT deposit_usdt, risk_pct FROM user_settings ORDER BY user_id LIMIT 1"
            ).fetchone()
            if _row:
                deposit_usdt = float(_row[0]) or deposit_usdt
                risk_pct = float(_row[1]) or risk_pct
    except Exception:
        pass
    # DEV-231 (30.05): разделение OPEN на VST (есть exchange_order_id) и shadow (нет).
    n_open = len(open_trades)
    n_vst    = sum(1 for t in open_trades if t.get("exchange_order_id"))
    n_shadow = n_open - n_vst
    for t in open_trades:
        t["is_shadow"] = not bool(t.get("exchange_order_id"))
    total_risk_usdt = n_vst * deposit_usdt * risk_pct / 100.0
    total_risk_pct  = total_risk_usdt / deposit_usdt * 100.0 if deposit_usdt else 0.0
    open_pnl_r = sum(t["unrealized_r"] for t in open_trades if t.get("unrealized_r") is not None)
    data["btc_4h_regime"]      = btc_4h_regime
    data["open_count"]         = n_open
    data["open_vst_count"]     = n_vst
    data["open_shadow_count"]  = n_shadow
    data["risk_exposure_pct"]  = round(total_risk_pct, 2)
    data["risk_exposure_usdt"] = round(total_risk_usdt, 2)
    data["deposit_usdt"]       = deposit_usdt
    data["open_pnl_r"]         = round(open_pnl_r, 2)
    data["exchange_health"]      = getattr(bot, "exchange_health", "HEALTHY") if bot else "HEALTHY"
    data["exchange_latency_ms"]  = round(getattr(bot, "exchange_latency_ms", 0.0), 0) if bot else 0
    return json.dumps(data, ensure_ascii=False, default=str)


async def _stats_compute_and_cache(request: web.Request) -> web.Response:
    import time as _time
    engine: PerformanceEngine = request.app["engine"]
    dc = request.app.get("data_collector")
    bot = request.app.get("bot")
    try:
        # DEV-231 (30.05): тяжёлая sync работа в thread pool — НЕ блокирует event loop.
        # До правки: 399 RequestHandler slow callbacks за 5 мин, avg 1.24s, total 493s
        # (event loop был занят дашбордом >100% времени → sync_time HTTP стояли в очереди).
        _loop = asyncio.get_running_loop()
        payload_str = await _loop.run_in_executor(None, _compute_stats_payload_sync, engine, dc, bot)
        _STATS_CACHE["payload"] = payload_str
        _STATS_CACHE["ts"] = _time.time()
        return web.Response(
            text=payload_str,
            content_type="application/json",
            charset="utf-8",
            headers={"X-Cache": "MISS"},
        )
    except Exception as e:
        logger.exception("dashboard /api/stats error: %s", e)
        # Stale fallback: при ошибке отдаём предыдущий cached payload если есть
        if _STATS_CACHE["payload"] is not None:
            return web.Response(
                text=_STATS_CACHE["payload"],
                content_type="application/json", charset="utf-8",
                headers={"X-Cache": "STALE", "X-Cache-Age": f"{_time.time() - _STATS_CACHE['ts']:.0f}"},
            )
        return web.Response(status=500, text=str(e))


async def _handle_closed_trades(request: web.Request) -> web.Response:
    """GET /api/closed_trades?page=1&per_page=50 — пагинированный список закрытых сделок."""
    engine: PerformanceEngine = request.app["engine"]
    try:
        page = max(1, int(request.rel_url.query.get("page", 1)))
        per_page = min(200, max(10, int(request.rel_url.query.get("per_page", 50))))
        offset = (page - 1) * per_page
        total = engine.closed_trades_count()
        rows = engine.recent_closed(limit=per_page, offset=offset)
        data = {
            "rows": rows,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("dashboard /api/closed_trades error: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_close_trade(request: web.Request) -> web.Response:
    """POST /api/trades/{trade_id}/close — ручное закрытие сделки."""
    ts = request.app.get("trade_simulator")
    dc = request.app.get("data_collector")
    if ts is None:
        return web.Response(status=503, text="TradeSimulator недоступен")
    try:
        trade_id = int(request.match_info["trade_id"])
        # Получаем текущую цену из кеша или из тела запроса
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        # Читаем символ из БД
        import sqlite3
        with sqlite3.connect(ts.db_path) as conn:
            row = conn.execute(
                "SELECT symbol, entry_price FROM simulated_trades WHERE id=? AND status='OPEN'",
                (trade_id,)
            ).fetchone()
        if not row:
            return web.Response(status=404, text="Сделка не найдена или уже закрыта")
        symbol, entry_price = row
        # Текущая цена: из кеша → из тела запроса → entry_price (нейтрально)
        cur_price = (_current_price_from_cache(dc, symbol) if dc else None) \
                    or body.get("price") or entry_price
        ok = ts.close_trade(trade_id, "EXPIRED", float(cur_price))
        if ok:
            logger.info("Dashboard: ручное закрытие сделки #%d %s @ %.5f", trade_id, symbol, cur_price)
            # ── SSE broadcast: уведомить все dashboard-вкладки о новой закрытой сделке ──
            try:
                import sqlite3 as _sq2
                with _sq2.connect(ts.db_path) as _c2:
                    _c2.row_factory = _sq2.Row
                    _closed_row = _c2.execute(
                        """SELECT id, symbol, direction, signal_type, timeframe, regime,
                                  status, profit_pct, R_multiple, max_R_possible,
                                  captured_R_pct, tp_source, duration_minutes,
                                  created_at, closed_at, features_json, tsl_tf
                           FROM simulated_trades WHERE id=?""",
                        (trade_id,)
                    ).fetchone()
                if _closed_row:
                    _trade_dict = dict(_closed_row)
                    _sse_str = (
                        "event: trade_closed\n"
                        f"data: {json.dumps(_trade_dict, ensure_ascii=False, default=str)}\n\n"
                    )
                    import asyncio as _aio2
                    _aio2.ensure_future(_sse_broadcast(_sse_str))
            except Exception as _be:
                logger.debug("SSE broadcast trade_closed failed: %s", _be)
            return web.Response(
                text=json.dumps({"ok": True, "trade_id": trade_id, "price": cur_price}, ensure_ascii=False),
                content_type="application/json",
            )
        return web.Response(status=500, text="Не удалось закрыть сделку")
    except Exception as e:
        logger.exception("_handle_close_trade: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_v2_index(request: web.Request) -> web.Response:
    """GET /v2/ + /v2/{any}  — отдаём Vue dashboard SPA index.html.

    DEV-144: prod bundle Vue 3 живёт в web/dashboard/dist/. Все non-asset пути
    отдают index.html (history mode роутинга — vue-router сам разрулит).
    Статика /v2/assets/* регистрируется через add_static отдельно.
    """
    # TEMP DISABLED: снижение нагрузки на BingX API
    return web.Response(
        status=503,
        text="Dashboard v2 временно отключён для снижения нагрузки на BingX API.",
        content_type="text/plain",
    )
    index_path = Path(__file__).resolve().parent / "dashboard" / "dist" / "index.html"
    if not index_path.exists():
        return web.Response(
            status=503,
            text="Vue dashboard не собран. Выполните `cd web/dashboard && npm run build`.",
            content_type="text/plain",
        )
    return web.FileResponse(index_path)


async def _handle_patterns(request: web.Request) -> web.Response:
    """GET /api/patterns — список ARCH-104 production patterns из config/arch104_patterns.yaml.

    DEV-144 Stage 5: данные для страницы «Паттерны». Возвращает per-pattern walkforward
    статистику (test_n / test_avgR / test_WR) + структуру anchor_factors. Live статистика
    из simulated_trades — TODO (требует pattern_id в features_json).
    """
    try:
        import yaml as _yaml
        from pathlib import Path as _Path
        yaml_path = _Path(__file__).resolve().parent.parent / "config" / "arch104_patterns.yaml"
        if not yaml_path.exists():
            return web.Response(
                text=json.dumps({"patterns": [], "error": "arch104_patterns.yaml not found"}),
                content_type="application/json",
            )
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = _yaml.safe_load(f) or {}

        out = []
        for pid, pdata in (cfg.get("patterns") or {}).items():
            if not isinstance(pdata, dict):
                continue
            out.append({
                "id": pid,
                "direction": pdata.get("direction"),
                "anchor_factors": pdata.get("anchor_factors") or [],
                "test_n": pdata.get("test_n"),
                "test_avgR": pdata.get("test_avgR"),
                "test_WR": pdata.get("test_WR"),
                "mht_p_adj": pdata.get("mht_p_adj"),
                "weight": pdata.get("weight"),
                "priority": pdata.get("priority"),
                "sl_source": (pdata.get("sl") or {}).get("source"),
                "tp_strategy": (pdata.get("tp") or {}).get("strategy"),
                "time_exit_hours": pdata.get("time_exit_hours"),
                "status": "live",  # TODO: вычислять из retire/shadow триггеров
            })
        return web.Response(
            text=json.dumps({
                "patterns": out,
                "version": cfg.get("version"),
                "generated": str(cfg.get("generated") or ""),
                "count": len(out),
            }, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("_handle_patterns: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_trade_trace(request: web.Request) -> web.Response:
    """GET /api/trades/{trade_id}/trace — Decision Trace для сделки (DEV-12)."""
    ts = request.app.get("trade_simulator")
    if ts is None:
        return web.Response(status=503, text="TradeSimulator недоступен")
    try:
        trade_id = int(request.match_info["trade_id"])
        import sqlite3
        with sqlite3.connect(ts.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, symbol, signal_type, direction, strength, confidence, regime, "
                "strategy_name, status, created_at, decision_trace_json, features_json "
                "FROM simulated_trades WHERE id=?",
                (trade_id,)
            ).fetchone()
        if not row:
            return web.Response(status=404, text="Сделка не найдена")
        result = dict(row)
        # Парсим JSON-поля
        for jf in ("decision_trace_json", "features_json"):
            raw = result.get(jf)
            if raw:
                try:
                    result[jf] = json.loads(raw)
                except Exception:
                    pass
        return web.Response(
            text=json.dumps(result, ensure_ascii=False, default=str),
            content_type="application/json",
        )
    except Exception as e:
        logger.exception("_handle_trade_trace: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_live_orders(request: web.Request) -> web.Response:
    """GET /api/live_orders — открытые позиции на бирже (VST/LIVE режим).
    DEV-144b: JOIN с simulated_trades для получения реальных SL/TP цен.
    """
    bot = request.app.get("bot")
    try:
        orders = []
        pm = getattr(bot, "position_manager", None) if bot else None
        if pm is not None:
            open_pos = pm.get_open_positions()

            # Подтягиваем SL/TP цены из simulated_trades по sim_trade_id
            sim_trade_ids = [p.sim_trade_id for p in open_pos if p.sim_trade_id]
            sl_tp_map: dict = {}
            if sim_trade_ids:
                import sqlite3 as _sq
                engine = request.app.get("engine")
                db_path = engine.db_path if (engine and hasattr(engine, "db_path")) else "subscriptions.db"
                try:
                    with _sq.connect(db_path) as _conn:
                        _conn.row_factory = _sq.Row
                        placeholders = ",".join("?" * len(sim_trade_ids))
                        rows = _conn.execute(
                            f"SELECT id, stop_loss, take_profit, entry_price, strength, signal_type "
                            f"FROM simulated_trades WHERE id IN ({placeholders})",
                            sim_trade_ids,
                        ).fetchall()
                        for row in rows:
                            sl_tp_map[row["id"]] = {
                                "stop_loss":   row["stop_loss"],
                                "take_profit": row["take_profit"],
                                "entry_price": row["entry_price"],
                                "strength":    row["strength"],
                                "signal_type": row["signal_type"],
                            }
                except Exception as db_e:
                    logger.warning("_handle_live_orders JOIN failed: %s", db_e)

            for pos in open_pos:
                sim = sl_tp_map.get(pos.sim_trade_id) or {}
                orders.append({
                    "id":                 pos.id,
                    "sim_trade_id":       pos.sim_trade_id,
                    "exchange_order_id":  pos.exchange_order_id,
                    "symbol":             pos.symbol,
                    "side":               pos.side,
                    "qty":                pos.qty,
                    "sl_order_id":        pos.sl_order_id,
                    "tp_order_id":        pos.tp_order_id,
                    "status":             pos.status,
                    "slip_pct":           pos.slip_pct,
                    "created_at":         pos.created_at,
                    # DEV-144b: реальные цены из simulated_trades
                    "stop_loss":          sim.get("stop_loss"),
                    "take_profit":        sim.get("take_profit"),
                    "entry_price":        sim.get("entry_price"),
                    "strength":           sim.get("strength"),
                    "signal_type":        sim.get("signal_type"),
                })

        # Режим торговли из конфига
        cfg = request.app.get("config", {})
        trading_cfg = cfg.get("trading", {}) if hasattr(cfg, "get") else {}
        raw_mode = (trading_cfg.get("execution_mode") or "sim_only").upper()
        mode = {"SIM_ONLY": "SIM", "VST": "VST", "LIVE": "LIVE"}.get(raw_mode, raw_mode)

        return web.Response(
            text=json.dumps({"mode": mode, "orders": orders, "count": len(orders)},
                            ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("_handle_live_orders: %s", e)
        return web.Response(status=500, text=json.dumps({"error": str(e)}),
                            content_type="application/json")


# ── DEV-144 (ARCH утверждено 25.05): /api/live cache TTL=10s + stale fallback ──
# BingX в DEGRADED/DOWN отдаёт snapshot за 5-10с, что блокирует event loop бота
# при N клиентах × 30s polling. Cache даёт 1 BingX call/10с независимо от вкладок.
# Stale fallback: если новый snapshot fail (timeout) → отдаём предыдущий + age в header.
import asyncio as _asyncio_live
_LIVE_CACHE = {"payload": None, "ts": 0.0, "ttl": 10.0}
_LIVE_LOCK = _asyncio_live.Lock()


async def _handle_live(request: web.Request) -> web.Response:
    """GET /api/live — реальный баланс BingX + позиции (DEV-144c).
    В SIM_ONLY режиме возвращает mode=SIM и пустые данные.
    Cache TTL=10с — все клиенты в окне 10с получают один и тот же snapshot.
    """
    import time as _time
    now = _time.time()

    # Cache hit: отдаём cached payload (без BingX call).
    cached = _LIVE_CACHE["payload"]
    if cached is not None and (now - _LIVE_CACHE["ts"]) < _LIVE_CACHE["ttl"]:
        return web.Response(
            text=json.dumps(cached, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
            headers={"X-Cache": "HIT", "X-Cache-Age": f"{now - _LIVE_CACHE['ts']:.1f}"},
        )

    bot = request.app.get("bot")
    cfg = request.app.get("config", {})

    trading_cfg = cfg.get("trading", {}) if hasattr(cfg, "get") else {}
    raw_mode = (trading_cfg.get("execution_mode") or "sim_only").upper()
    mode = {"SIM_ONLY": "SIM", "VST": "VST", "LIVE": "LIVE"}.get(raw_mode, raw_mode)

    result: dict = {
        "mode": mode,
        "balance": None,
        "positions": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }

    # 26.05: safety-bound /api/live — get_exchange_snapshot с timeout 5s.
    # При таймауте → cached (stale) если есть, иначе пустой payload.
    # Это защищает event loop от зависания на BingX REST.
    if bot and hasattr(bot, "order_executor") and mode in ("VST", "LIVE"):
        async with _LIVE_LOCK:
            now2 = _time.time()
            cached2 = _LIVE_CACHE.get("payload")
            if cached2 is not None and (now2 - _LIVE_CACHE.get("ts", 0)) < _LIVE_CACHE.get("ttl", 10):
                return web.Response(
                    text=json.dumps(cached2, ensure_ascii=False, default=str),
                    content_type="application/json", charset="utf-8",
                    headers={"X-Cache": "HIT"},
                )
            # Try fetch с timeout 5s
            try:
                return await asyncio.wait_for(
                    _live_fetch_and_cache(request, result, bot),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.debug("[/api/live] BingX snapshot timeout 5s — fallback to stale cache")
                if cached2 is not None:
                    return web.Response(
                        text=json.dumps(cached2, ensure_ascii=False, default=str),
                        content_type="application/json", charset="utf-8",
                        headers={"X-Cache": "STALE-TIMEOUT"},
                    )
                return web.Response(
                    text=json.dumps(result, ensure_ascii=False, default=str),
                    content_type="application/json", charset="utf-8",
                    headers={"X-Cache": "EMPTY-TIMEOUT"},
                )

    # SIM mode
    return web.Response(
        text=json.dumps(result, ensure_ascii=False, default=str),
        content_type="application/json", charset="utf-8",
    )


async def _live_fetch_and_cache(request: web.Request, result: dict, bot) -> web.Response:
    """Делает BingX snapshot, сохраняет в _LIVE_CACHE.

    При ошибке/таймауте — fallback на stale cache (если есть): отдаём предыдущий
    snapshot + X-Cache: STALE header. Это лучше пустого ответа когда BingX лежит.
    """
    import time as _time
    try:
        snapshot = await bot.order_executor.get_exchange_snapshot()
        result["balance"] = snapshot.get("balance")
        # Нормализуем поля позиций BingX → удобный формат
        raw_positions = snapshot.get("positions", [])
        for p in raw_positions:
            amt = float(p.get("positionAmt") or p.get("availableAmt") or 0)
            if amt == 0:
                continue
            # BingX Hedge Mode: positionSide = "LONG"/"SHORT" (positionAmt всегда ≥ 0)
            pos_side = p.get("positionSide") or ("LONG" if amt > 0 else "SHORT")
            result["positions"].append({
                "symbol":            p.get("symbol", ""),
                "side":              pos_side,
                "size":              abs(amt),
                "entry_price":       float(p.get("avgPrice") or p.get("entryPrice") or 0),
                "mark_price":        float(p.get("markPrice") or 0),
                "unrealized_pnl":    float(p.get("unrealizedProfit") or 0),
                "leverage":          int(p.get("leverage") or 1),
                "margin":            float(p.get("initialMargin") or p.get("positionInitialMargin") or 0),
                "liquidation_price": float(p.get("liquidationPrice") or 0),
            })
        # JOIN с simulated_trades через live_orders → получаем SL/TP для отображения
        # Используем live_orders.sim_trade_id как мост, чтобы корректно находить
        # "зомби" позиции (live_orders=OPEN, но simulated_trades=TSL/SL/EXPIRED).
        # BingX symbol "ATOM-USDT" → БД "ATOM/USDT:USDT"
        if result["positions"]:
            from core.exchange.bingx_client import from_bingx_symbol
            syms = list({from_bingx_symbol(p["symbol"]) for p in result["positions"]})
            engine = request.app.get("engine")
            db_path = engine.db_path if (engine and hasattr(engine, "db_path")) else "subscriptions.db"
            sl_tp_map: dict = {}
            try:
                import sqlite3 as _sq
                with _sq.connect(db_path) as _conn:
                    _conn.row_factory = _sq.Row
                    ph = ",".join("?" * len(syms))
                    # Через live_orders чтобы найти sim_trade_id независимо от статуса
                    rows = _conn.execute(
                        f"SELECT lo.symbol, st.stop_loss, st.take_profit, "
                        f"st.tsl_activated, st.tsl_tf "
                        f"FROM live_orders lo "
                        f"JOIN simulated_trades st ON lo.sim_trade_id = st.id "
                        f"WHERE lo.status='OPEN' AND lo.symbol IN ({ph})",
                        syms,
                    ).fetchall()
                    for row in rows:
                        sl = row["stop_loss"]
                        tp = row["take_profit"]
                        # Фильтруем нечисловые значения ("OPEN" — legacy артефакт)
                        try:
                            sl = float(sl) if sl and sl != "OPEN" else None
                        except (TypeError, ValueError):
                            sl = None
                        try:
                            tp = float(tp) if tp else None
                        except (TypeError, ValueError):
                            tp = None
                        # Не перезаписываем если уже есть данные (первая запись = приоритет)
                        if row["symbol"] not in sl_tp_map:
                            sl_tp_map[row["symbol"]] = {
                                "stop_loss": sl,
                                "take_profit": tp,
                                "tsl_activated": bool(row["tsl_activated"]),
                                "tsl_tf": row["tsl_tf"],
                            }
            except Exception as db_e:
                logger.debug("_handle_live JOIN failed: %s", db_e)
            for pos in result["positions"]:
                db_sym = from_bingx_symbol(pos["symbol"])
                st = sl_tp_map.get(db_sym) or {}
                pos["stop_loss"]  = st.get("stop_loss")
                pos["take_profit"] = st.get("take_profit")
                pos["tsl_activated"] = st.get("tsl_activated", False)
                pos["tsl_tf"] = st.get("tsl_tf")

        result["error"] = snapshot.get("error")

        # ── Сохраняем в cache (успех) ──
        _LIVE_CACHE["payload"] = result
        _LIVE_CACHE["ts"] = _time.time()

        return web.Response(
            text=json.dumps(result, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
            headers={"X-Cache": "MISS"},
        )

    except Exception as e:
        logger.warning("_handle_live error: %s", e)
        # ── Fallback на stale cache (если был хоть один успех) ──
        stale = _LIVE_CACHE["payload"]
        if stale is not None:
            age = _time.time() - _LIVE_CACHE["ts"]
            stale_resp = dict(stale)
            stale_resp["error"] = f"using stale cache (age={age:.1f}s), live error: {e}"
            return web.Response(
                text=json.dumps(stale_resp, ensure_ascii=False, default=str),
                content_type="application/json", charset="utf-8",
                headers={"X-Cache": "STALE", "X-Cache-Age": f"{age:.1f}"},
            )
        # Cache пуст → отдаём пустой payload с error
        result["error"] = str(e)
        return web.Response(
            text=json.dumps(result, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
            headers={"X-Cache": "ERROR"},
        )


async def _handle_exchange_history(request: web.Request) -> web.Response:
    """GET /api/exchange_history?days=7 — история LIVE сделок из simulated_trades.

    Возвращает закрытые сделки с exchange_order_id за последние N дней.
    Включает все метрики: profit_pct, R_multiple, duration, signal_type, direction.
    """
    try:
        days = int(request.rel_url.query.get("days", "7"))
        days = max(1, min(days, 90))
        engine = request.app.get("engine")
        db_path = engine.db_path if (engine and hasattr(engine, "db_path")) else "subscriptions.db"
        # DEV-231: SQL LIMIT 500 + 500x effective_status + JSON serialize (255KB) — в thread pool
        payload_str = await _run_sync(_exchange_history_compute_sync, db_path, days)
        return web.Response(
            text=payload_str,
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("_handle_exchange_history: %s", e)
        return web.Response(status=500, text=json.dumps({"error": str(e)}),
                            content_type="application/json")


def _exchange_history_compute_sync(db_path: str, days: int) -> str:
    """DEV-231: SQL + effective_status + JSON для /api/exchange_history."""
    import sqlite3 as _sq
    from datetime import timezone as _tz, timedelta as _td
    cutoff = (datetime.now(_tz.utc) - _td(days=days)).isoformat()
    with _sq.connect(db_path) as conn:
        conn.row_factory = _sq.Row
        rows = conn.execute(
            """
            SELECT id, symbol, direction, signal_type,
                   entry_price, actual_entry_price, exit_price,
                   stop_loss, take_profit,
                   status, profit_pct, R_multiple,
                   strength, confidence, regime,
                   created_at, closed_at, duration_minutes,
                   exchange_order_id, tsl_activated
            FROM simulated_trades
            WHERE exchange_order_id IS NOT NULL
              AND status IN ('TP','SL','TSL','EXPIRED')
              AND closed_at >= ?
            ORDER BY closed_at DESC
            LIMIT 500
            """,
            (cutoff,),
        ).fetchall()
    from core.trading.effective_status import effective_status as _eff
    trades = []
    for r in rows:
        ep = r["actual_entry_price"] or r["entry_price"]
        eff = _eff(r["status"], r["R_multiple"], r["tsl_activated"])
        trades.append({
            "id":              r["id"],
            "symbol":          r["symbol"],
            "direction":       r["direction"],
            "signal_type":     r["signal_type"],
            "entry_price":     ep,
            "exit_price":      r["exit_price"],
            "stop_loss":       r["stop_loss"],
            "take_profit":     r["take_profit"],
            "status":          r["status"],
            "effective_status": eff,
            "profit_pct":      r["profit_pct"],
            "R_multiple":      r["R_multiple"],
            "strength":        r["strength"],
            "confidence":      r["confidence"],
            "regime":          r["regime"],
            "created_at":      r["created_at"],
            "closed_at":       r["closed_at"],
            "duration_minutes": r["duration_minutes"],
        })
    tp_cnt        = sum(1 for t in trades if t["status"] == "TP")
    sl_cnt        = sum(1 for t in trades if t["status"] == "SL")
    tsl_cnt       = sum(1 for t in trades if t["status"] == "TSL")
    tsl_hidden_n  = sum(1 for t in trades if t["effective_status"] == "TSL_hidden_win")
    sl_slipped_n  = sum(1 for t in trades if t["effective_status"] == "SL_slipped")
    closed        = tp_cnt + sl_cnt + tsl_cnt
    eff_wins      = tp_cnt + tsl_cnt + tsl_hidden_n
    r_vals        = [t["R_multiple"] for t in trades if t["R_multiple"] is not None]
    avg_r         = round(sum(r_vals) / len(r_vals), 3) if r_vals else None
    return json.dumps({
        "days":     days,
        "total":    len(trades),
        "summary": {
            "tp":             tp_cnt,
            "sl":             sl_cnt,
            "tsl":            tsl_cnt,
            "tsl_hidden":     tsl_hidden_n,
            "tsl_effective":  tsl_cnt + tsl_hidden_n,
            "sl_slipped":     sl_slipped_n,
            "win_rate":       round(eff_wins / closed * 100, 1) if closed else None,
            "win_rate_raw":   round((tp_cnt + tsl_cnt) / closed * 100, 1) if closed else None,
            "avg_r":          avg_r,
        },
        "trades": trades,
    }, ensure_ascii=False, default=str)


async def _handle_trading_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/trading.html")


async def _handle_trading_status(request: web.Request) -> web.Response:
    """Возвращает текущий режим торговли, параметры риска и баланс VST."""
    cfg = request.app["config"]
    trading_cfg = cfg.get("trading", {}) if hasattr(cfg, "get") else {}
    raw_mode = (trading_cfg.get("execution_mode") or "sim_only").upper()
    mode_label = {"SIM_ONLY": "SIM", "VST": "VST", "LIVE": "LIVE"}.get(raw_mode, raw_mode)

    result = {
        "mode": mode_label,
        "use_tsl": trading_cfg.get("use_tsl", True),
        "tsl_activation_r": trading_cfg.get("tsl_activation_r", 1.0),
        "deposit_usdt": trading_cfg.get("deposit_usdt", 1000.0),
        "risk_pct": trading_cfg.get("risk_pct", 1.0),
        "leverage": trading_cfg.get("leverage", 5),
        "vst_balance": None,
    }

    # Для VST/LIVE — получаем реальный баланс (DEV-231: wait_for 2s — защита от висящего BingX).
    # При DEGRADED биже get_available_balance может зависнуть >10s и заблокировать event loop.
    # На timeout отдаём vst_balance=None — UI не блокируется, бот работает.
    if mode_label in ("VST", "LIVE"):
        try:
            bot = request.app.get("bot")
            if bot and hasattr(bot, "order_executor"):
                result["vst_balance"] = round(
                    await asyncio.wait_for(bot.order_executor.get_available_balance(), timeout=2.0),
                    2,
                )
        except asyncio.TimeoutError:
            logger.debug("[/api/trading/status] BingX balance timeout 2s — vst_balance=None")
        except Exception:
            pass

    return web.Response(
        text=json.dumps(result, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


async def _handle_trading_instrument_info(request: web.Request) -> web.Response:
    """Возвращает min_notional для символа (BingX perpetual)."""
    symbol = request.rel_url.query.get("symbol", "").strip()
    if not symbol:
        return web.Response(status=400, text='{"error": "symbol required"}',
                            content_type="application/json")
    try:
        import ccxt.async_support as ccxt_async
        exch = ccxt_async.bingx({"enableRateLimit": True})
        try:
            markets = await exch.load_markets()
            market = markets.get(symbol) or markets.get(symbol.replace(":USDT", ""))
            min_notional = None
            if market:
                limits = market.get("limits", {})
                cost = limits.get("cost", {})
                min_notional = cost.get("min")
        finally:
            await exch.close()
        return web.Response(
            text=json.dumps({"symbol": symbol, "min_notional": min_notional}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.warning("instrument_info error for %s: %s", symbol, e)
        return web.Response(
            text=json.dumps({"symbol": symbol, "min_notional": None, "error": str(e)},
                            ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )


async def _handle_settings_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/settings.html")


async def _handle_settings_get(request: web.Request) -> web.Response:
    """Возвращает текущие настройки: параметры анализа + адаптивные веса из БД."""
    cfg = request.app["config"]
    engine: PerformanceEngine = request.app["engine"]

    analysis = cfg.get("analysis", {})
    safe_analysis = {
        "volume_multiplier": analysis.get("volume_multiplier", 5.0),
        "price_threshold":   analysis.get("price_threshold", 7.0),
        "check_interval":    analysis.get("check_interval", 60),
        "history_size":      analysis.get("history_size", 200),
    }

    # Адаптивные веса: вычисляем на лету из PerformanceEngine
    signal_weights: dict = {}
    base = {
        "anomaly":        0.30,
        "wt_signal":      0.10,
        "mtf_alert":      0.25,
        "trend_signal":   0.10,
        "divergence":     0.05,
        "pivot_reversal": 0.20,
    }
    try:
        for row in engine.by_signal_type():
            sig = row.get("signal_type") or ""
            avg_r = float(row.get("avg_r") or 0.0)
            total = row.get("total", 0)
            if sig in base:
                if total >= 20:
                    factor = max(0.5, min(2.0, 1.0 + avg_r * 0.4))
                    signal_weights[sig] = round(base[sig] * factor, 4)
                else:
                    signal_weights[sig] = base[sig]
    except Exception:
        pass

    ind_cfg = analysis.get("indicators", {})
    wt_cfg  = ind_cfg.get("wavetrend", {})
    tr_cfg  = ind_cfg.get("trend", {})
    safe_indicators = {
        "wavetrend": {
            "n1":           wt_cfg.get("n1", 10),
            "n2":           wt_cfg.get("n2", 21),
            "ob_threshold": wt_cfg.get("ob_threshold", 60),
            "os_threshold": wt_cfg.get("os_threshold", -60),
        },
        "trend": {
            "atr_period": tr_cfg.get("atr_period", 43),
            "factor":     tr_cfg.get("factor", 1.0),
        },
    }

    safe_trading = {
        "use_tsl":          cfg.get("trading.use_tsl", True),
        "tsl_activation_r": cfg.get("trading.tsl_activation_r", 1.0),
        "tsl_buffer_pct":   cfg.get("trading.tsl_buffer_pct", 0.1),
    }
    safe_signal_quality = {
        "sl_cooldown_hours":    cfg.get("signal_quality.sl_cooldown_hours", 4),
        "dedup_minutes":        cfg.get("signal_quality.dedup_minutes", 30),
        "min_volume_usd":       cfg.get("signal_quality.min_volume_usd", 1_000_000),
        "min_strength":         cfg.get("signal_quality.min_strength", 50),
        "min_strength_register":cfg.get("signal_quality.min_strength_register", 20),
        "counter_trend_strength_threshold": cfg.get("signal_quality.counter_trend_strength_threshold", 70),
    }

    det_cfg = cfg.get("detectors", {}).get("anomaly", {}) or {}
    safe_detectors = {
        "anomaly": {
            "volume_ratio_threshold":      det_cfg.get("volume_ratio_threshold", 3.0),
            "volume_ma_period":            det_cfg.get("volume_ma_period", 20),
            "min_bars":                    det_cfg.get("min_bars", 20),
            "strength_trend_multiplier":   det_cfg.get("strength_trend_multiplier", 12),
            "strength_counter_multiplier": det_cfg.get("strength_counter_multiplier", 8),
        }
    }

    mon_cfg = cfg.get("monitoring", {}).get("check_intervals", {}) or {}
    safe_monitoring = {
        "divergences_every_n_cycles": mon_cfg.get("divergences_every_n_cycles", 3),
        "background_every_n_cycles":  mon_cfg.get("background_every_n_cycles", 5),
        "cascade_div_every_n_cycles": mon_cfg.get("cascade_div_every_n_cycles", 60),
    }

    sig_cfg = analysis.get("signals", {}) or {}
    safe_signals_config = {
        "min_signals":              sig_cfg.get("min_signals", 2),
        "single_signal_min_strength": sig_cfg.get("single_signal_min_strength", 70),
        "pivot_proximity_pct":      cfg.get("analysis.divergence.pivot_proximity_pct", 4.0),
        "btc_filter_enabled":       cfg.get("signal_quality.btc_filter_enabled", True),
        "counter_trend_strength_threshold": cfg.get("signal_quality.counter_trend_strength_threshold", 70),
    }

    confl_cfg = analysis.get("confluence", {}) or {}
    safe_confluence = {
        "enabled":              confl_cfg.get("enabled", True),
        "lookback_bars":        confl_cfg.get("lookback_bars", 40),
        "min_strength":         confl_cfg.get("min_strength", 60),
        "wt_os_threshold":      confl_cfg.get("wt_os_threshold", -58),
        "wt_ob_threshold":      confl_cfg.get("wt_ob_threshold", 58),
        "pivot_proximity_pct":  confl_cfg.get("pivot_proximity_pct", 0.5),
        "div_min_bars":         confl_cfg.get("div_min_bars", 3),
    }

    data = {
        "analysis": safe_analysis,
        "indicators": safe_indicators,
        "signal_weights": signal_weights,
        "trading": safe_trading,
        "signal_quality": safe_signal_quality,
        "detectors": safe_detectors,
        "monitoring_intervals": safe_monitoring,
        "signals_config": safe_signals_config,
        "confluence": safe_confluence,
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        content_type="application/json",
        charset="utf-8",
    )


async def _handle_settings_post(request: web.Request) -> web.Response:
    """Сохраняет параметры анализа в config.yaml и перезагружает конфиг (hot-reload)."""
    cfg = request.app["config"]
    try:
        body = await request.json()
    except Exception:
        return web.Response(
            status=400,
            text=json.dumps({"ok": False, "error": "invalid JSON"}),
            content_type="application/json",
        )

    # --- Блок risk (deposit / risk_pct / leverage) ---
    risk_body = body.get("risk")
    if risk_body is not None:
        try:
            deposit  = float(risk_body.get("deposit_usdt", 1000.0))
            risk_pct = float(risk_body.get("risk_pct", 1.0))
            leverage = int(risk_body.get("leverage", 5))
            errors: list = []
            if not (10 <= deposit <= 10_000_000): errors.append("deposit_usdt: 10–10 000 000")
            if not (0.1 <= risk_pct <= 10.0):     errors.append("risk_pct: 0.1–10.0")
            if not (1 <= leverage <= 100):         errors.append("leverage: 1–100")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_risk(deposit_usdt=deposit, risk_pct=risk_pct, leverage=leverage)
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок trading (TSL) ---
    trading_body = body.get("trading")
    if trading_body is not None:
        try:
            use_tsl   = bool(trading_body.get("use_tsl", True))
            act_r     = float(trading_body.get("tsl_activation_r", 1.0))
            buf       = float(trading_body.get("tsl_buffer_pct", 0.1))
            errors: list = []
            if not (0.1 <= act_r <= 5.0): errors.append("tsl_activation_r: 0.1–5.0")
            if not (0.0 <= buf <= 1.0):   errors.append("tsl_buffer_pct: 0.0–1.0")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_trading(use_tsl=use_tsl, tsl_activation_r=act_r, tsl_buffer_pct=buf)
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок signal_quality ---
    sq_body = body.get("signal_quality")
    if sq_body is not None:
        try:
            sl_h  = int(sq_body.get("sl_cooldown_hours", 4))
            ded   = int(sq_body.get("dedup_minutes", 30))
            vol   = int(sq_body.get("min_volume_usd", 1_000_000))
            ms    = int(sq_body.get("min_strength", 50))
            msr   = int(sq_body.get("min_strength_register", 20))
            errors = []
            if not (1 <= sl_h <= 48):         errors.append("sl_cooldown_hours: 1–48")
            if not (5 <= ded <= 120):          errors.append("dedup_minutes: 5–120")
            if not (100_000 <= vol <= 100_000_000): errors.append("min_volume_usd: 100К–100М")
            if not (20 <= ms <= 100):          errors.append("min_strength: 20–100")
            if not (10 <= msr <= ms):          errors.append(f"min_strength_register: 10–{ms}")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_signal_quality(
            sl_cooldown_hours=sl_h, dedup_minutes=ded, min_volume_usd=vol,
            min_strength=ms, min_strength_register=msr,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок detectors ---
    det_body = body.get("detectors")
    if det_body is not None:
        try:
            ratio_thr  = float(det_body.get("volume_ratio_threshold", 3.0))
            ma_period  = int(det_body.get("volume_ma_period", 20))
            min_bars   = int(det_body.get("min_bars", 20))
            str_trend  = int(det_body.get("strength_trend_multiplier", 12))
            str_ctr    = int(det_body.get("strength_counter_multiplier", 8))
            errors = []
            if not (1.0 <= ratio_thr <= 20.0): errors.append("volume_ratio_threshold: 1.0–20.0")
            if not (5 <= ma_period <= 100):     errors.append("volume_ma_period: 5–100")
            if not (5 <= min_bars <= 200):      errors.append("min_bars: 5–200")
            if not (1 <= str_trend <= 30):      errors.append("strength_trend_multiplier: 1–30")
            if not (1 <= str_ctr <= 30):        errors.append("strength_counter_multiplier: 1–30")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_detectors(
            volume_ratio_threshold=ratio_thr, volume_ma_period=ma_period,
            min_bars=min_bars, strength_trend_multiplier=str_trend,
            strength_counter_multiplier=str_ctr,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок signals_config ---
    sc_body = body.get("signals_config")
    if sc_body is not None:
        try:
            min_sig    = int(sc_body.get("min_signals", 2))
            ss_min     = int(sc_body.get("single_signal_min_strength", 70))
            prox_pct   = float(sc_body.get("pivot_proximity_pct", 4.0))
            btc_en     = bool(sc_body.get("btc_filter_enabled", True))
            ct_thr     = int(sc_body.get("counter_trend_strength_threshold", 70))
            errors = []
            if not (1 <= min_sig <= 10):        errors.append("min_signals: 1–10")
            if not (30 <= ss_min <= 100):        errors.append("single_signal_min_strength: 30–100")
            if not (0.5 <= prox_pct <= 20.0):    errors.append("pivot_proximity_pct: 0.5–20.0")
            if not (30 <= ct_thr <= 100):        errors.append("counter_trend_strength_threshold: 30–100")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        # Сохраняем в разные секции конфига
        with open(cfg.config_path, "r", encoding="utf-8") as f:
            import yaml as _yaml
            raw = _yaml.safe_load(f)
        raw.setdefault("analysis", {}).setdefault("signals", {})
        raw["analysis"]["signals"]["min_signals"] = min_sig
        raw["analysis"]["signals"]["single_signal_min_strength"] = ss_min
        raw.setdefault("analysis", {}).setdefault("divergence", {})
        raw["analysis"]["divergence"]["pivot_proximity_pct"] = round(prox_pct, 2)
        raw.setdefault("signal_quality", {})
        raw["signal_quality"]["btc_filter_enabled"] = btc_en
        raw["signal_quality"]["counter_trend_strength_threshold"] = ct_thr
        with open(cfg.config_path, "w", encoding="utf-8") as f:
            _yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        cfg.reload()
        return web.Response(
            text=json.dumps({"ok": True, "error": None}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок confluence ---
    conf_body = body.get("confluence")
    if conf_body is not None:
        try:
            enabled   = bool(conf_body.get("enabled", True))
            lookback  = int(conf_body.get("lookback_bars", 40))
            min_str   = int(conf_body.get("min_strength", 60))
            wt_os     = float(conf_body.get("wt_os_threshold", -58))
            wt_ob     = float(conf_body.get("wt_ob_threshold", 58))
            piv_pct   = float(conf_body.get("pivot_proximity_pct", 0.5))
            div_bars  = int(conf_body.get("div_min_bars", 3))
            errors = []
            if not (5 <= lookback <= 200):     errors.append("lookback_bars: 5–200")
            if not (40 <= min_str <= 100):     errors.append("min_strength: 40–100")
            if not (-100 <= wt_os <= -20):     errors.append("wt_os_threshold: -100 до -20")
            if not (20 <= wt_ob <= 100):       errors.append("wt_ob_threshold: 20–100")
            if not (0.1 <= piv_pct <= 5.0):   errors.append("pivot_proximity_pct: 0.1–5.0")
            if not (1 <= div_bars <= 20):      errors.append("div_min_bars: 1–20")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        try:
            import yaml as _yaml
            with open(cfg.config_path, "r", encoding="utf-8") as f:
                raw = _yaml.safe_load(f)
            raw.setdefault("analysis", {}).setdefault("confluence", {})
            raw["analysis"]["confluence"].update({
                "enabled": enabled,
                "lookback_bars": lookback,
                "min_strength": min_str,
                "wt_os_threshold": wt_os,
                "wt_ob_threshold": wt_ob,
                "pivot_proximity_pct": round(piv_pct, 2),
                "div_min_bars": div_bars,
            })
            with open(cfg.config_path, "w", encoding="utf-8") as f:
                _yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            cfg.reload()
            ok = True
        except Exception as e:
            logger.exception("Ошибка сохранения confluence: %s", e)
            ok = False
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # --- Блок monitoring_intervals ---
    mon_body = body.get("monitoring_intervals")
    if mon_body is not None:
        try:
            div_n = int(mon_body.get("divergences_every_n_cycles", 3))
            bg_n  = int(mon_body.get("background_every_n_cycles", 5))
            cas_n = int(mon_body.get("cascade_div_every_n_cycles", 60))
            errors = []
            if not (1 <= div_n <= 20):   errors.append("divergences_every_n_cycles: 1–20")
            if not (1 <= bg_n <= 30):    errors.append("background_every_n_cycles: 1–30")
            if not (10 <= cas_n <= 300): errors.append("cascade_div_every_n_cycles: 10–300")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_monitoring(
            divergences_every_n_cycles=div_n,
            background_every_n_cycles=bg_n,
            cascade_div_every_n_cycles=cas_n,
        )
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    # Если передан блок indicators — сохраняем только его
    ind_body = body.get("indicators")
    if ind_body is not None:
        try:
            wt  = ind_body.get("wavetrend", {})
            tr  = ind_body.get("trend", {})
            n1  = int(wt.get("n1", 10))
            n2  = int(wt.get("n2", 21))
            ob  = float(wt.get("ob_threshold", 60))
            os_ = float(wt.get("os_threshold", -60))
            atr = int(tr.get("atr_period", 43))
            fac = float(tr.get("factor", 1.0))
            errors = []
            if not (5 <= n1 <= 30):   errors.append("n1 должен быть 5-30")
            if not (10 <= n2 <= 50):  errors.append("n2 должен быть 10-50")
            if not (30 <= ob <= 100): errors.append("ob_threshold должен быть 30-100")
            if not (-100 <= os_ <= -30): errors.append("os_threshold должен быть -100 до -30")
            if not (5 <= atr <= 200): errors.append("atr_period должен быть 5-200")
            if not (0.1 <= fac <= 5): errors.append("factor должен быть 0.1-5")
        except (TypeError, ValueError) as e:
            errors = [f"Некорректный тип данных: {e}"]
        if errors:
            return web.Response(
                text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
                content_type="application/json", charset="utf-8",
            )
        ok = cfg.save_indicators(wt_n1=n1, wt_n2=n2, wt_ob=ob, wt_os=os_,
                                 trend_atr_period=atr, trend_factor=fac)
        return web.Response(
            text=json.dumps({"ok": ok, "error": None if ok else "ошибка записи файла"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )

    errors = []
    vol      = body.get("volume_multiplier")
    thr      = body.get("price_threshold")
    interval = body.get("check_interval")
    history  = body.get("history_size")

    try:
        if vol is None or not (1.0 <= float(vol) <= 100.0):
            errors.append("volume_multiplier должен быть от 1 до 100")
        if thr is None or not (0.5 <= float(thr) <= 50.0):
            errors.append("price_threshold должен быть от 0.5 до 50")
        if interval is None or not (10 <= int(interval) <= 3600):
            errors.append("check_interval должен быть от 10 до 3600 сек")
        if history is None or not (50 <= int(history) <= 1000):
            errors.append("history_size должен быть от 50 до 1000")
    except (TypeError, ValueError) as e:
        errors.append(f"Некорректный тип данных: {e}")

    if errors:
        return web.Response(
            text=json.dumps({"ok": False, "error": "; ".join(errors)}, ensure_ascii=False),
            content_type="application/json",
            charset="utf-8",
        )

    ok = cfg.save_analysis(
        volume_multiplier=float(vol),
        price_threshold=float(thr),
        check_interval=int(interval),
        history_size=int(history),
    )
    return web.Response(
        text=json.dumps(
            {"ok": ok, "error": None if ok else "ошибка записи файла"},
            ensure_ascii=False,
        ),
        content_type="application/json",
        charset="utf-8",
    )


async def _handle_backtest_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/backtest.html")


async def _handle_backtest_results(request: web.Request) -> web.Response:
    """Возвращает последние сохранённые результаты из backtest_results.json."""
    path = "backtest_results.json"
    if not os.path.exists(path):
        return web.Response(
            text=json.dumps({"results": [], "generated_at": None}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return web.Response(
            text=json.dumps(data, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def _handle_backtest_status(request: web.Request) -> web.Response:
    """Возвращает текущий статус фонового бэктеста."""
    state = request.app["backtest_state"]
    total = state.get("total", 0)
    done = state.get("done", 0)
    progress = f"{done}/{total}" if total else ""
    return web.Response(
        text=json.dumps({
            "running": state["running"],
            "error": state.get("error"),
            "progress": progress,
            "log": state.get("log", [])[-60:],  # последние 60 строк
        }, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


async def _handle_backtest_run(request: web.Request) -> web.Response:
    """Запускает бэктест в фоне. POST /api/backtest/run."""
    state = request.app["backtest_state"]
    if state["running"]:
        return web.Response(
            text=json.dumps({"ok": False, "error": "Бэктест уже запущен"}, ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    try:
        body = await request.json()
    except Exception:
        body = {}

    symbols = body.get("symbols") or None
    period_names = body.get("periods") or None
    atr_period = int(body.get("atr_period", 14))
    atr_factor = float(body.get("atr_factor", 1.5))
    use_wt = bool(body.get("use_wt", True))
    use_divergence = bool(body.get("use_divergence", True))
    div_regular = bool(body.get("div_regular", True))
    div_hidden = bool(body.get("div_hidden", True))
    use_anomaly = bool(body.get("use_anomaly", True))
    use_trend = bool(body.get("use_trend", True))
    use_fvg = bool(body.get("use_fvg", False))
    use_fvg_boost = bool(body.get("use_fvg_boost", False))
    use_pivot_boost = bool(body.get("use_pivot_boost", False))
    fvg_timeframe = str(body.get("fvg_timeframe", "15m"))
    wt_ob = float(body.get("wt_ob", 60.0))
    wt_os = float(body.get("wt_os", -60.0))
    tp_type = str(body.get("tp_type", "fixed_2r"))
    tp_r = float(body.get("tp_r", 2.0))
    tsl_activation_r = float(body.get("tsl_activation_r", 1.0))
    tsl_lag_bars = int(body.get("tsl_lag_bars", 0))
    use_reentry = bool(body.get("use_reentry", False))
    timeframe = str(body.get("timeframe", "1h"))

    # Конвертируем period_names в (name, start, end) tuples
    from backtesting_engine import DEFAULT_PERIODS, DEFAULT_SYMBOLS, run_comprehensive_backtest
    all_periods_map = {p[0]: p for p in DEFAULT_PERIODS}
    if period_names:
        periods = [all_periods_map[n] for n in period_names if n in all_periods_map] or None
    else:
        periods = None
    if not symbols:
        symbols = DEFAULT_SYMBOLS

    state["running"] = True
    state["error"] = None
    state["log"] = []
    state["done"] = 0
    state["total"] = len(symbols) * len(periods or DEFAULT_PERIODS)

    def on_progress(msg: str) -> None:
        state["log"].append(msg)
        if msg.strip().startswith("сд=") or "ПРОПУСК" in msg:
            state["done"] = min(state["done"] + 1, state["total"])

    async def _run():
        try:
            await run_comprehensive_backtest(
                symbols=symbols, periods=periods, on_progress=on_progress,
                atr_period=atr_period, atr_factor=atr_factor,
                timeframe=timeframe,
                use_wt=use_wt, use_divergence=use_divergence,
                div_regular=div_regular, div_hidden=div_hidden,
                use_anomaly=use_anomaly, use_trend=use_trend,
                use_fvg=use_fvg, fvg_timeframe=fvg_timeframe,
                use_fvg_boost=use_fvg_boost,
                use_pivot_boost=use_pivot_boost,
                wt_ob=wt_ob, wt_os=wt_os,
                tp_type=tp_type, tp_r=tp_r,
                tsl_activation_r=tsl_activation_r,
                tsl_lag_bars=tsl_lag_bars,
                use_reentry=use_reentry,
            )
        except Exception as e:
            state["error"] = str(e)
            logger.exception("Backtest background error: %s", e)
        finally:
            state["running"] = False

    asyncio.create_task(_run())

    return web.Response(
        text=json.dumps({"ok": True}, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


# ---------------------------------------------------------------------------
# Operations Dashboard API + Page (ARCH-13)
# ---------------------------------------------------------------------------

_TOGGLES = [
    ("future_pivots.broadcast_tg", "Future Pivot -> TG", False),
    ("signals.mtf_alert_register", "MTF Alert Register", True),
    ("signals.cascade_div_enabled", "Cascade Divergences", True),
    ("analysis.confluence.enabled", "Confluence Scanner", True),
    ("analysis.confluence.use_state_machine", "Confluence State Machine", False),
    ("trading.use_tsl", "Trailing Stop (TSL)", True),
    ("trading.cascade_tsl", "Cascade TSL (15m->1h->4h)", True),
    ("trading.use_breakeven", "Breakeven SL", False),
    ("signal_quality.btc_filter_enabled", "BTC Correlation Filter", True),
    ("trading.dual_tp.enabled", "DUAL TP (TREND only)", True),
    ("risk_management.regime_strategy.enabled", "Regime Adaptive SL/TP", True),
    ("future_pivots.enabled", "Future Pivots Calc", False),
]

_PARAMS = [
    ("signal_quality.min_strength_register", "min_strength_register", 40, 10, 100, 5),
    ("signal_quality.min_strength", "min_strength (TG)", 50, 20, 100, 5),
    ("signal_quality.dedup_minutes", "dedup_minutes", 30, 5, 120, 5),
    ("signal_quality.sl_cooldown_hours", "sl_cooldown_hours", 1, 1, 48, 1),
    ("analysis.confluence.max_per_cycle", "max_confluence/cycle", 10, 1, 50, 1),
    ("signal_quality.counter_trend_strength_threshold", "counter_trend_thr", 30, 10, 100, 5),
    ("trading.min_rr_ratio", "min R:R ratio", 2.0, 1.0, 5.0, 0.5),
    ("trading.max_trade_duration_hours", "trade expiry (hours)", 48, 12, 168, 12),
    ("trading.tsl_activation_r", "TSL activation R", 1.0, 0.3, 3.0, 0.1),
    ("trading.dual_tp.tp1_fix_pct", "TP1 fix % (DUAL)", 70, 10, 100, 5),
    ("signal_quality.min_volume_usd", "min volume USD", 1000000, 100000, 100000000, 100000),
    ("monitoring.check_intervals.background_every_n_cycles", "bg check cycles", 5, 1, 20, 1),
]


async def _handle_dashboard_api(request: web.Request) -> web.Response:
    config = request.app["config"]
    bot = request.app.get("bot")
    engine: PerformanceEngine = request.app["engine"]

    
    # Live status
    # D-056: last_scan + health detection (D-053 cascade crash visibility)
    _last_scan = getattr(bot, "_last_scan", None) if bot else None
    _scan_health = "unknown"
    _scan_age_sec = None
    if _last_scan:
        import time as _t_mod
        _scan_age_sec = round(_t_mod.time() - _last_scan["ts"])
        if _scan_age_sec < 360:    # < 6 min — здоров
            _scan_health = "ok"
        elif _scan_age_sec < 900:  # 6-15 min — задержка
            _scan_health = "delayed"
        else:                      # > 15 min — мёртв (D-053 cascade)
            _scan_health = "DEAD"

    status = {
        "is_monitoring": getattr(bot, "is_monitoring", False) if bot else False,
        "monitored_pairs": len(getattr(bot, "monitored_pairs", [])) if bot else 0,
        "signal_counters": dict(getattr(bot, "signal_counters", {})) if bot else {},
        "start_time": getattr(bot, "start_time", None),
        "last_scan": _last_scan,                # {ts, pairs, elapsed_sec} или None
        "scan_age_sec": _scan_age_sec,          # сколько секунд прошло с последнего scan
        "scan_health": _scan_health,            # ok / delayed / DEAD / unknown
    }
    if status["start_time"]:
        status["start_time"] = status["start_time"].isoformat()

    # BTC regime
    btc_regime = "N/A"
    if bot and hasattr(bot, "_btc_regime_cache"):
        btc_regime = (getattr(bot, "_btc_regime_cache", None) or {}).get("regime", "N/A")

    # ML status
    ml_status = "not trained"
    ml_trained_at = None
    if bot:
        op = getattr(bot, "outcome_predictor", None)
        if op and getattr(op, "is_trained", False):
            ml_status = "trained"
            ml_trained_at = getattr(op, "trained_at", None)
            if ml_trained_at:
                ml_trained_at = ml_trained_at.isoformat() if hasattr(ml_trained_at, "isoformat") else str(ml_trained_at)

    # Trade stats
    try:
        stats = engine.full_stats()
        trade_stats = {
            "open_count": stats.get("open_count", 0),
            "closed_count": stats.get("closed_count", 0),
            "win_rate": stats.get("win_rate", 0),
            "avg_r": stats.get("avg_r", 0),
        }
        # Direction breakdown
        by_dir = stats.get("by_direction", [])
        long_count = sum(d.get("total", 0) for d in by_dir if d.get("direction") == "LONG")
        short_count = sum(d.get("total", 0) for d in by_dir if d.get("direction") == "SHORT")
        trade_stats["long_count"] = long_count
        trade_stats["short_count"] = short_count
    except Exception:
        trade_stats = {"open_count": 0, "closed_count": 0, "win_rate": 0, "avg_r": 0,
                       "long_count": 0, "short_count": 0}

    # Toggles
    toggles = {}
    for key, label, default in _TOGGLES:
        toggles[key] = {"label": label, "value": bool(config.get(key, default))}
    # BTC filter mode (special: 3-state)
    toggles["signal_quality.btc_filter_mode"] = {
        "label": "BTC Filter Mode",
        "value": config.get("signal_quality.btc_filter_mode", "shadow"),
        "options": ["shadow", "block", "off"],
    }

    # Params
    params = {}
    for key, label, default, mn, mx, step in _PARAMS:
        params[key] = {
            "label": label,
            "value": config.get(key, default),
            "min": mn, "max": mx, "step": step,
        }

    data = {
        "status": status,
        "btc_regime": btc_regime,
        "ml_status": ml_status,
        "ml_trained_at": ml_trained_at,
        "trade_stats": trade_stats,
        "toggles": toggles,
        "params": params,
    }
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json", charset="utf-8",
    )


async def _handle_toggles_post(request: web.Request) -> web.Response:
    config = request.app["config"]
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text='{"error":"invalid JSON"}',
                            content_type="application/json")

    changes = {}
    for key, value in body.items():
        if key == "signal_quality.btc_filter_mode":
            if value in ("shadow", "block", "off"):
                config.set(key, value)
                changes[key] = value
        else:
            # Boolean toggles or numeric params
            config.set(key, value)
            changes[key] = value

    # Persist to config.yaml
    try:
        config.save()
    except Exception:
        logger.debug("config.save() failed, changes applied in-memory only")

    return web.Response(
        text=json.dumps({"ok": True, "changes": changes}, ensure_ascii=False),
        content_type="application/json", charset="utf-8",
    )


# _DASHBOARD_HTML moved to web/static/


# ── /api/cube/* — Куб Метатрона: внешний MCP-слой (Фаза 1) ──────────────────

# Разрешённые события для ручной инжекции (только аналитические, не торговые)
_CUBE_EVENT_WHITELIST = {
    "wt_cross_4h", "wt_cross_1d", "wt_confluence",
    "regime_change", "trend_change_1h",
    "anomaly_volume", "cascade", "ote_reentry",
}


async def _handle_cube_context(request: web.Request) -> web.Response:
    """GET /api/cube/context/{symbol} — живое состояние пары из PairContextBus."""
    bot = request.app.get("bot")
    symbol = request.match_info.get("symbol", "")
    # Символы в URL приходят с '_' вместо '/' (BTC_USDT → BTC/USDT)
    symbol = symbol.replace("_", "/")
    try:
        pair_ctx = getattr(bot, "pair_context", None)
        if pair_ctx is None:
            return web.Response(
                text=json.dumps({"error": "PairContextBus not available"}),
                content_type="application/json", status=503,
            )
        state = pair_ctx.get_full_state(symbol)
        return web.Response(
            text=json.dumps(state, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("[cube/context] %s: %s", symbol, e)
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_cube_events(request: web.Request) -> web.Response:
    """GET /api/cube/events?limit=50 — лог событий шины."""
    bot = request.app.get("bot")
    limit = int(request.rel_url.query.get("limit", 50))
    try:
        pair_ctx = getattr(bot, "pair_context", None)
        if pair_ctx is None:
            return web.Response(
                text=json.dumps({"error": "PairContextBus not available"}),
                content_type="application/json", status=503,
            )
        events = pair_ctx.get_event_log(limit=limit)
        return web.Response(
            text=json.dumps({"events": events, "count": len(events)}, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_cube_stats(request: web.Request) -> web.Response:
    """GET /api/cube/stats — статистика шины: пары, подписчики, очередь EventBus."""
    bot = request.app.get("bot")
    try:
        pair_ctx = getattr(bot, "pair_context", None)
        event_bus = getattr(bot, "event_bus", None)
        ctx_stats = pair_ctx.stats() if pair_ctx else {}
        bus_stats = event_bus.stats() if event_bus else {}
        return web.Response(
            text=json.dumps({"context_bus": ctx_stats, "event_bus": bus_stats}, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_cube_event_inject(request: web.Request) -> web.Response:
    """POST /api/cube/event — ручная инжекция события в EventBus (Full CALL триггер).

    Body: {"symbol": "BTC/USDT", "event_type": "wt_confluence", "data": {...}}
    Whitelist: только аналитические события, не торговые.
    """
    bot = request.app.get("bot")
    try:
        body = await request.json()
    except Exception:
        return web.Response(text=json.dumps({"error": "invalid JSON"}), content_type="application/json", status=400)

    symbol = body.get("symbol", "").strip()
    event_type = body.get("event_type", "").strip()
    data = body.get("data") or {}

    if not symbol or not event_type:
        return web.Response(
            text=json.dumps({"error": "symbol and event_type required"}),
            content_type="application/json", status=400,
        )
    if event_type not in _CUBE_EVENT_WHITELIST:
        return web.Response(
            text=json.dumps({"error": f"event_type '{event_type}' not in whitelist", "allowed": sorted(_CUBE_EVENT_WHITELIST)}),
            content_type="application/json", status=400,
        )

    event_bus = getattr(bot, "event_bus", None)
    if event_bus is None:
        return web.Response(
            text=json.dumps({"error": "EventBus not available"}),
            content_type="application/json", status=503,
        )

    data["_source"] = "MANUAL_INJECT"
    accepted = await event_bus.publish(symbol, event_type, data)
    logger.info("[cube/event] MANUAL_INJECT %s %s → accepted=%s", symbol, event_type, accepted)
    return web.Response(
        text=json.dumps({"ok": True, "accepted": accepted, "symbol": symbol, "event_type": event_type}),
        content_type="application/json", charset="utf-8",
    )


async def _handle_cube_ml_train(request: web.Request) -> web.Response:
    """POST /api/cube/ml/train — ручной запуск ML-обучения (веса + OutcomePredictor)."""
    bot = request.app.get("bot")
    try:
        ti = getattr(bot, "trading_intelligence", None)
        if ti is None:
            return web.Response(
                text=json.dumps({"error": "TradingIntelligence not available"}),
                content_type="application/json", status=503,
            )
        # Обновляем адаптивные веса сигналов
        weights_updated = False
        if hasattr(ti, "update_signal_weights"):
            ti.update_signal_weights()
            weights_updated = True

        # Переобучаем OutcomePredictor
        op_result = None
        if hasattr(ti, "outcome_predictor") and ti.outcome_predictor is not None:
            db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
            ti.outcome_predictor.fit(db_path)
            op_result = ti.outcome_predictor.info() if hasattr(ti.outcome_predictor, "info") else "ok"

        logger.info("[cube/ml/train] MANUAL: weights=%s outcome_predictor=%s", weights_updated, op_result)
        return web.Response(
            text=json.dumps({"ok": True, "weights_updated": weights_updated, "outcome_predictor": str(op_result)},
                            ensure_ascii=False),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("[cube/ml/train] %s", e)
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_performance_api(request: web.Request) -> web.Response:
    """GET /api/performance — агрегированная аналитика (DEV-117)."""
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = {
            "summary":       engine.summary(),
            "by_signal":     engine.by_signal_type(),
            "by_direction":  engine.by_direction(),
            "by_regime":     engine.by_regime(),
            "by_strategy":   engine.by_strategy(),
            "top_pairs":     engine.top_pairs(20),
            "weekly":        engine.weekly_summary(7),
            "rolling_wr":    engine.rolling_win_rate(50),
        }
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("/api/performance error: %s", e)
        return web.Response(status=500, text=str(e))


async def _handle_pair_api(request: web.Request) -> web.Response:
    """GET /api/pair/{symbol} — статистика + история по паре (DEV-117)."""
    engine: PerformanceEngine = request.app["engine"]
    dc = request.app.get("data_collector")
    symbol = request.match_info.get("symbol", "").replace("_", "/")
    try:
        stats   = engine.pair_stats(symbol)
        history = engine.pair_history(symbol, limit=50)
        # Открытые сделки по паре
        open_all = engine.open_trades()
        open_pair = [t for t in open_all if t.get("symbol") == symbol]
        # Обогащаем unrealized R
        for t in open_pair:
            cur = _current_price_from_cache(dc, symbol) if dc else None
            t["current_price"] = cur
            ep, sl = t.get("entry_price") or 0, t.get("stop_loss") or 0
            sl_dist = abs(ep - sl) if ep and sl else 0
            if cur and ep and sl_dist:
                direction = t.get("direction", "LONG")
                pnl_pct = (cur - ep) / ep * 100 if direction == "LONG" else (ep - cur) / ep * 100
                t["unrealized_r"] = round(pnl_pct / (sl_dist / ep * 100), 2) if sl_dist else None
            else:
                t["unrealized_r"] = None
        return web.Response(
            text=json.dumps({"symbol": symbol, "stats": stats, "history": history, "open": open_pair},
                            ensure_ascii=False, default=str),
            content_type="application/json", charset="utf-8",
        )
    except Exception as e:
        logger.exception("/api/pair/%s error: %s", symbol, e)
        return web.Response(status=500, text=str(e))


async def _handle_sse(request: web.Request) -> web.StreamResponse:
    """GET /api/events — SSE-поток обновлений stats (DEV-117).

    Клиент подписывается один раз; сервер каждые 5 сек отправляет event: dashboard.
    Также немедленно передаёт event: trade_closed при ручном закрытии сделки.
    """
    import asyncio as _aio
    engine: PerformanceEngine = request.app["engine"]
    send_dashboard = request.rel_url.query.get("dashboard") == "1"

    def _response_json(resp: web.Response) -> dict:
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {resp.text}")
        body = resp.text
        if body is None and resp.body is not None:
            body = resp.body.decode("utf-8")
        return json.loads(body or "{}")

    async def _safe_json(name: str, handler) -> dict:
        try:
            return _response_json(await handler(request))
        except Exception as exc:
            logger.warning("[SSE] dashboard block %s failed: %s", name, exc)
            return {}

    resp = web.StreamResponse()
    resp.headers["Content-Type"]  = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    await resp.prepare(request)

    # ── Регистрируем клиента в broadcast-списке ────────────────────────────
    # Очередь для внеплановых событий (trade_closed и др.)
    _client_queue: _aio.Queue = _aio.Queue(maxsize=50)
    if send_dashboard:
        _sse_dashboard_clients.append(_client_queue)

    try:
        while True:
            # ── Отправляем внеплановые события из очереди (trade_closed и др.) ──
            while not _client_queue.empty():
                try:
                    _evt = _client_queue.get_nowait()
                    await resp.write(_evt.encode("utf-8"))
                    await resp.drain()
                except _aio.QueueEmpty:
                    break
                except Exception as _qe:
                    logger.debug("[SSE] queue drain error: %s", _qe)
                    break

            try:
                summary = engine.summary()
                rolling = engine.rolling_win_rate(50)
                payload = json.dumps({"summary": summary, "rolling": rolling}, default=str)
                await resp.write(f"event: stats\ndata: {payload}\n\n".encode())
            except Exception as _e:
                logger.debug("[SSE] ошибка сборки данных: %s", _e)
            if send_dashboard:
                try:
                    stats = _response_json(await _handle_stats(request))
                    # FIX 26.05: добавляем status/btc_regime блок (из _handle_dashboard_api)
                    # в stats — иначе topbar badges scan_health/BingX/BTC4h не получают
                    # данные (SSE event:dashboard их раньше не слал). Это исправляет
                    # давний баг "? Скан (мп 0)" в старом дашборде.
                    try:
                        dash_data = _response_json(await _handle_dashboard_api(request))
                        if isinstance(dash_data, dict):
                            stats["status"] = dash_data.get("status", {})
                            stats["btc_regime"] = dash_data.get("btc_regime")
                            stats["btc_4h_regime"] = dash_data.get("btc_4h_regime") or dash_data.get("btc_regime")
                    except Exception as _de:
                        logger.debug("[SSE] dashboard status enrich failed: %s", _de)

                    dashboard_payload = {
                        "stats": stats,
                        "confluence": await _safe_json("confluence", _handle_confluence_breakdown),
                        "breakeven": await _safe_json("breakeven", _handle_breakeven_stats),
                        "equity": await _safe_json("equity", _handle_equity),
                        "analytics": await _safe_json("analytics", _handle_analytics),
                        "signal_weights": await _safe_json("signal_weights", _handle_signal_weights_history),
                    }
                    payload = json.dumps(dashboard_payload, ensure_ascii=False, default=str)
                    await resp.write(f"event: dashboard\ndata: {payload}\n\n".encode("utf-8"))
                    await resp.drain()
                except Exception as _e:
                    logger.debug("[SSE] dashboard payload error: %s", _e)
            await _aio.sleep(5)
    except (ConnectionResetError, _aio.CancelledError):
        pass
    finally:
        # ── Удаляем клиента из broadcast-списка ───────────────────────────
        try:
            _sse_dashboard_clients.remove(_client_queue)
        except ValueError:
            pass
    return resp


async def _handle_performance_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/performance.html")


async def _handle_pair_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/pair.html")


async def _handle_dashboard_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/operations.html")


# ── DEV-203: DecisionTrace — dropped signals endpoint ──────────────────────

async def _handle_dropped(request: web.Request) -> web.Response:
    """GET /api/dropped — топ gate_name по drops за последние hours часов.

    Query params:
      hours  — окно анализа (default: 24)
      limit  — максимум строк (default: 20)
      detail — если '1', возвращает последние drops (recent view)
    """
    from core.observability.decision_trace import get_top_drops, get_recent_drops
    engine: PerformanceEngine = request.app["engine"]
    db_path = engine.db_path if hasattr(engine, "db_path") else "subscriptions.db"

    try:
        hours = int(request.rel_url.query.get("hours", 24))
        limit = int(request.rel_url.query.get("limit", 20))
        detail = request.rel_url.query.get("detail", "0") == "1"
    except (ValueError, TypeError):
        hours, limit, detail = 24, 20, False

    # DEV-231: SQL в thread pool
    if detail:
        data = await _run_sync(get_recent_drops, db_path, limit=limit, hours=hours)
        return web.json_response({"recent": data, "hours": hours, "limit": limit})
    else:
        data = await _run_sync(get_top_drops, db_path, limit=limit, hours=hours)
        return web.json_response({"drops": data, "hours": hours, "limit": limit})


# ── DEV-207: ATR Change стратегия — агрегаты по trigger_source ──────────────

def _atr_stats_compute_sync(db_path: str) -> dict:
    """DEV-231: SQL + агрегация ATR stats — в thread pool."""
    import sqlite3

    def _tf_from_row(features_json):
        if not features_json:
            return None
        try:
            fj = json.loads(features_json)
        except Exception:
            return None
        tf = fj.get("atr_tf")
        if tf:
            return str(tf)
        src = fj.get("trigger_source", "")
        if isinstance(src, str) and src.startswith("atr_change_"):
            return src[len("atr_change_"):]
        confs = fj.get("confirmations") or []
        best = None
        for c in confs:
            if not isinstance(c, dict):
                continue
            s = c.get("source", "")
            if isinstance(s, str) and s.startswith("atr_change_"):
                w = c.get("weight") or 0
                tf_c = s[len("atr_change_"):]
                if best is None or w > best[0]:
                    best = (w, tf_c)
        return best[1] if best else None

    buckets = {
        "1h": {"closed": 0, "open": 0, "wins": 0, "r_sum": 0.0, "best_r": None},
        "4h": {"closed": 0, "open": 0, "wins": 0, "r_sum": 0.0, "best_r": None},
        "15m": {"closed": 0, "open": 0, "wins": 0, "r_sum": 0.0, "best_r": None},
    }
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT status, R_multiple, features_json
            FROM simulated_trades
            WHERE features_json IS NOT NULL
              AND (features_json LIKE '%atr_change_%' OR features_json LIKE '%"atr_tf"%')
        """)
        for row in cur.fetchall():
            tf = _tf_from_row(row["features_json"])
            if tf not in buckets:
                continue
            b = buckets[tf]
            if row["status"] == "OPEN":
                b["open"] += 1
                continue
            b["closed"] += 1
            r = row["R_multiple"]
            if r is not None:
                b["r_sum"] += float(r)
                if float(r) > 0:
                    b["wins"] += 1
                if b["best_r"] is None or float(r) > b["best_r"]:
                    b["best_r"] = float(r)
    result = {}
    for tf, b in buckets.items():
        n = b["closed"]
        result[tf] = {
            "closed": n,
            "open": b["open"],
            "wr": round(b["wins"] / n * 100, 1) if n else 0.0,
            "avg_r": round(b["r_sum"] / n, 3) if n else 0.0,
            "total_r": round(b["r_sum"], 2),
            "best_r": round(b["best_r"], 2) if b["best_r"] is not None else None,
        }
    return result


async def _handle_atr_stats(request: web.Request) -> web.Response:
    """GET /api/atr_stats — метрики ATR Change стратегии (1h / 4h / 15m).

    Группирует сделки по features_json.atr_tf (если указан) или
    извлекает таймфрейм из features_json.trigger_source ('atr_change_1h' → '1h').

    Возвращает по каждому TF: closed (n), open, wr, avg_r, total_r, best_r.
    """
    engine: PerformanceEngine = request.app["engine"]
    db_path = engine.db_path if hasattr(engine, "db_path") else "subscriptions.db"
    try:
        result = await _run_sync(_atr_stats_compute_sync, db_path)
        return web.json_response({"atr": result})
    except Exception as e:
        logger.exception("dashboard /api/atr_stats error: %s", e)
        return web.json_response({"error": str(e)}, status=500)

async def start_dashboard(db_path: str = "subscriptions.db", host: str = "0.0.0.0", port: int = 8000,
                          config=None, data_collector=None, trade_simulator=None, bot=None) -> None:
    """Запускает aiohttp-сервер. Вызывать через asyncio.create_task()."""
    import asyncio
    if config is None:
        from core.infra.config_loader import config as _cfg
        config = _cfg

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    app = web.Application()
    app["engine"] = PerformanceEngine(db_path=db_path)
    app["config"] = config
    app["data_collector"] = data_collector   # для получения текущей цены
    app["trade_simulator"] = trade_simulator  # для ручного закрытия сделок
    app["backtest_state"] = {"running": False, "error": None, "log": [], "done": 0, "total": 0}

    # Регистрируем SSE callback — при автоматическом закрытии (TP/SL/TSL) бродкастим trade_closed
    if trade_simulator is not None and hasattr(trade_simulator, "set_sse_trade_closed"):
        async def _on_auto_close(trade_id: int) -> None:
            try:
                import sqlite3 as _sq
                with _sq.connect(trade_simulator.db_path) as _c:
                    _c.row_factory = _sq.Row
                    _row = _c.execute(
                        """SELECT id, symbol, direction, signal_type, timeframe, regime,
                                  status, profit_pct, R_multiple, max_R_possible,
                                  captured_R_pct, tp_source, duration_minutes,
                                  created_at, closed_at, features_json, tsl_tf
                           FROM simulated_trades WHERE id=?""",
                        (trade_id,)
                    ).fetchone()
                if _row:
                    _evt = (
                        "event: trade_closed\n"
                        f"data: {json.dumps(dict(_row), ensure_ascii=False, default=str)}\n\n"
                    )
                    await _sse_broadcast(_evt)
            except Exception as _e:
                logger.debug("SSE auto-close broadcast error: %s", _e)
        trade_simulator.set_sse_trade_closed(_on_auto_close)
    app["bot"] = bot
    app.router.add_get("/", _handle_index)
    app.router.add_get("/dashboard", _handle_dashboard_page)

    # ── DS: временный API старта сканирования (Telegram недоступен) ──
    async def _handle_start_scan(request: web.Request) -> web.Response:
        from bot.monitoring import start_monitoring
        from unittest.mock import MagicMock
        msg = MagicMock()
        msg.from_user.id = 1
        msg.from_user.username = "admin"
        msg.from_user.first_name = "Admin"
        msg.from_user.last_name = ""
        async def _noop(*a, **kw): return None
        msg.answer = _noop
        msg.reply = _noop
        try:
            await start_monitoring(bot, msg)
            return web.json_response({"status": "ok", "monitoring": bot.is_monitoring})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)
    app.router.add_get("/api/start_scan", _handle_start_scan)
    app.router.add_static("/static", Path(__file__).parent / "static")
    app.router.add_get("/api/dashboard", _handle_dashboard_api)
    app.router.add_post("/api/toggles", _handle_toggles_post)
    app.router.add_get("/api/stats", _handle_stats)
    app.router.add_get("/api/stats/confluence", _handle_confluence_breakdown)
    app.router.add_get("/api/stats/breakeven", _handle_breakeven_stats)
    app.router.add_get("/api/stats/analytics", _handle_analytics)
    app.router.add_get("/api/equity", _handle_equity)
    app.router.add_get("/api/signal_weights/history", _handle_signal_weights_history)
    app.router.add_get("/api/closed_trades", _handle_closed_trades)
    app.router.add_post("/api/trades/{trade_id}/close", _handle_close_trade)
    app.router.add_get("/api/trades/{trade_id}/trace", _handle_trade_trace)
    app.router.add_get("/api/patterns", _handle_patterns)
    # ── DEV-144: Vue 3 dashboard (prod bundle) под /v2/ ──
    _v2_dist = Path(__file__).parent / "dashboard" / "dist"
    if (_v2_dist / "assets").exists():
        app.router.add_static("/v2/assets", _v2_dist / "assets")
    app.router.add_get("/v2", _handle_v2_index)
    app.router.add_get("/v2/", _handle_v2_index)
    app.router.add_get("/v2/{tail:.*}", _handle_v2_index)
    app.router.add_get("/api/live_orders", _handle_live_orders)
    app.router.add_get("/api/live", _handle_live)
    app.router.add_get("/api/exchange_history", _handle_exchange_history)
    app.router.add_get("/trading", _handle_trading_page)
    app.router.add_get("/api/trading/status", _handle_trading_status)
    app.router.add_get("/api/trading/instrument_info", _handle_trading_instrument_info)
    app.router.add_get("/settings", _handle_settings_page)
    app.router.add_get("/api/settings", _handle_settings_get)
    app.router.add_post("/api/settings", _handle_settings_post)
    app.router.add_get("/backtest", _handle_backtest_page)
    app.router.add_get("/api/backtest/results", _handle_backtest_results)
    app.router.add_get("/api/backtest/status", _handle_backtest_status)
    app.router.add_post("/api/backtest/run", _handle_backtest_run)
    # ── DEV-117: Performance + Pair pages + SSE ──
    app.router.add_get("/performance",            _handle_performance_page)
    app.router.add_get("/pair/{symbol}",          _handle_pair_page)
    app.router.add_get("/api/performance",        _handle_performance_api)
    app.router.add_get("/api/pair/{symbol}",      _handle_pair_api)
    app.router.add_get("/api/events",             _handle_sse)
    # ── Куб Метатрана — MCP Layer (Фаза 1) ──
    app.router.add_get("/api/cube/context/{symbol}", _handle_cube_context)
    app.router.add_get("/api/cube/events", _handle_cube_events)
    app.router.add_get("/api/cube/stats", _handle_cube_stats)
    app.router.add_post("/api/cube/event", _handle_cube_event_inject)
    app.router.add_post("/api/cube/ml/train", _handle_cube_ml_train)
    # ── DEV-203: DecisionTrace — видимость отброшенных сигналов ──
    app.router.add_get("/api/dropped", _handle_dropped)
    # ── DEV-207: ATR Change стратегия ──
    app.router.add_get("/api/atr_stats", _handle_atr_stats)

    # DS-322: быстрые цены для дашборда (из кэша, без API-запроса)
    async def _handle_prices(request: web.Request) -> web.Response:
        bot = request.app.get("bot")
        dc = bot.data_collector if bot else None
        if not dc:
            return web.json_response({})
        prices = {}
        for sym in getattr(bot, "monitored_pairs", [])[:50]:  # top-50 открытых
            try:
                p = await dc.get_current_price(sym)
                if p:
                    prices[sym] = p
            except Exception:
                pass
        return web.json_response(prices)
    app.router.add_get("/api/prices", _handle_prices)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    try:
        await site.start()
        logger.info(
            "Dashboard запущен: http://%s:%s  |  Настройки: http://%s:%s/settings",
            host, port, host, port,
        )
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        logger.exception("Dashboard error: %s", e)
    finally:
        await runner.cleanup()
