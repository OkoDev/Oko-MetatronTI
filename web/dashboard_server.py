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

from pathlib import Path
from aiohttp import web

from core.performance_engine import PerformanceEngine



logger = logging.getLogger(__name__)

# _HTML moved to web/static/


# _SETTINGS_HTML moved to web/static/
# _BACKTEST_HTML moved to web/static/


async def _handle_index(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/index.html")


async def _handle_confluence_breakdown(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = engine.confluence_breakdown()
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
        data = engine.breakeven_stats()
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


async def _handle_equity(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    try:
        data = engine.equity_data()
        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        return web.Response(text=json.dumps({"error": str(e)}), content_type="application/json", status=500)


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


async def _handle_stats(request: web.Request) -> web.Response:
    engine: PerformanceEngine = request.app["engine"]
    dc = request.app.get("data_collector")
    try:
        data = engine.full_stats()
        # Обогащаем open_trades текущей ценой, нереализованным P&L и MFE
        for t in data.get("open_trades", []):
            cur = _current_price_from_cache(dc, t["symbol"]) if dc else None
            t["current_price"] = cur
            ep = t.get("entry_price") or 0
            sl = t.get("stop_loss") or 0
            direction = t.get("direction", "LONG")
            sl_dist = abs(ep - sl) if ep and sl else 0
            if cur is not None and ep and sl_dist:
                if direction == "LONG":
                    pnl_pct = (cur - ep) / ep * 100
                else:
                    pnl_pct = (ep - cur) / ep * 100
                t["unrealized_pct"] = round(pnl_pct, 2)
                t["unrealized_r"] = round(pnl_pct / (sl_dist / ep * 100), 2) if sl_dist else None
            else:
                t["unrealized_pct"] = None
                t["unrealized_r"] = None
            # MFE: max R достигнутый за время жизни сделки
            max_r = t.get("max_R_possible")
            if max_r is None and ep and sl_dist:
                max_p = t.get("max_price")
                min_p = t.get("min_price")
                if direction == "LONG" and max_p:
                    max_r = round((float(max_p) - ep) / sl_dist, 2)
                elif direction == "SHORT" and min_p:
                    max_r = round((ep - float(min_p)) / sl_dist, 2)
            t["mfe_r"] = round(max_r, 2) if max_r is not None else None
            # Cascade level из features_json
            try:
                fj = t.get("features_json")
                if fj:
                    import json as _json
                    _fj = _json.loads(fj) if isinstance(fj, str) else fj
                    t["cascade_level"] = _fj.get("cascade_level") or _fj.get("tsl_tf")
                else:
                    t["cascade_level"] = t.get("tsl_tf")
            except Exception:
                t["cascade_level"] = t.get("tsl_tf")

        # BTC 4h regime
        bot = request.app.get("bot")
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
        n_open = len(open_trades)
        total_risk_usdt = n_open * deposit_usdt * risk_pct / 100.0
        total_risk_pct  = total_risk_usdt / deposit_usdt * 100.0 if deposit_usdt else 0.0
        open_pnl_r = sum(t["unrealized_r"] for t in open_trades if t.get("unrealized_r") is not None)
        data["btc_4h_regime"]      = btc_4h_regime
        data["risk_exposure_pct"]  = round(total_risk_pct, 2)
        data["risk_exposure_usdt"] = round(total_risk_usdt, 2)
        data["deposit_usdt"]       = deposit_usdt
        data["open_pnl_r"]         = round(open_pnl_r, 2)

        return web.Response(
            text=json.dumps(data, ensure_ascii=False, default=str),
            content_type="application/json",
            charset="utf-8",
        )
    except Exception as e:
        logger.exception("dashboard /api/stats error: %s", e)
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
            return web.Response(
                text=json.dumps({"ok": True, "trade_id": trade_id, "price": cur_price}, ensure_ascii=False),
                content_type="application/json",
            )
        return web.Response(status=500, text="Не удалось закрыть сделку")
    except Exception as e:
        logger.exception("_handle_close_trade: %s", e)
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


async def _handle_trading_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/trading.html")


async def _handle_trading_status(request: web.Request) -> web.Response:
    """Возвращает текущий режим торговли и параметры риска."""
    cfg = request.app["config"]
    trading_cfg = cfg.get("trading", {}) if hasattr(cfg, "get") else {}
    return web.Response(
        text=json.dumps({
            "mode": "SIM",
            "use_tsl": trading_cfg.get("use_tsl", True),
            "tsl_activation_r": trading_cfg.get("tsl_activation_r", 1.0),
        }, ensure_ascii=False),
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
    status = {
        "is_monitoring": getattr(bot, "is_monitoring", False) if bot else False,
        "monitored_pairs": len(getattr(bot, "monitored_pairs", [])) if bot else 0,
        "signal_counters": dict(getattr(bot, "signal_counters", {})) if bot else {},
        "start_time": getattr(bot, "start_time", None),
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


async def _handle_dashboard_page(request: web.Request) -> web.Response:
    return web.FileResponse(Path(__file__).parent / "static/operations.html")


async def start_dashboard(db_path: str = "subscriptions.db", host: str = "0.0.0.0", port: int = 8000,
                          config=None, data_collector=None, trade_simulator=None, bot=None) -> None:
    """Запускает aiohttp-сервер. Вызывать через asyncio.create_task()."""
    import asyncio
    if config is None:
        from core.config_loader import config as _cfg
        config = _cfg

    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    app = web.Application()
    app["engine"] = PerformanceEngine(db_path=db_path)
    app["config"] = config
    app["data_collector"] = data_collector   # для получения текущей цены
    app["trade_simulator"] = trade_simulator  # для ручного закрытия сделок
    app["backtest_state"] = {"running": False, "error": None, "log": [], "done": 0, "total": 0}
    app["bot"] = bot
    app.router.add_get("/", _handle_index)
    app.router.add_get("/dashboard", _handle_dashboard_page)
    app.router.add_static("/static", Path(__file__).parent / "static")
    app.router.add_get("/api/dashboard", _handle_dashboard_api)
    app.router.add_post("/api/toggles", _handle_toggles_post)
    app.router.add_get("/api/stats", _handle_stats)
    app.router.add_get("/api/stats/confluence", _handle_confluence_breakdown)
    app.router.add_get("/api/stats/breakeven", _handle_breakeven_stats)
    app.router.add_get("/api/equity", _handle_equity)
    app.router.add_get("/api/closed_trades", _handle_closed_trades)
    app.router.add_post("/api/trades/{trade_id}/close", _handle_close_trade)
    app.router.add_get("/api/trades/{trade_id}/trace", _handle_trade_trace)
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
