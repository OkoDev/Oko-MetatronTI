"""
METHOD-V2 loop — боевой фрактальный вход (метод Егора, прошёл walk-forward OOS 05.07).

4h = волна 1 старшего (контекст) · 15m = волна 3 младшего (BOS-вход) · стоп за волну 2 ·
лестница целей по старшему импульсу. Детектор: core/smc/method_v2_mtf.detect_v2_mtf.

Живой поток: сканит ликвидные пары (4h+15m кэш), детектит сетапы, СВЕЖИЙ (entry_ts в
последних N барах 15m) → register через trade_router source='method_v2' (VST-песочница,
добро Егора «сразу в прод»). Reuse обвязки radar: multi-TP лестница, BE, TSL, positionId.

Gated: config trading.method_v2.enabled (default false). Валидация: docs/OTE_METHOD_ENTRY_V2.md.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

import pandas as pd

from bot.loops.arch104_observer_loop import _get_active_pairs, _fetch_df

logger = logging.getLogger(__name__)

DEFAULT_SCAN_SEC = 900
CONCURRENCY = 3


def _cfg(bot) -> dict:
    try:
        return bot.config.get("trading.method_v2", {}) or {}
    except Exception:
        return {}


def _liquid_pairs(bot, pairs: list[str], topn: int) -> list[str]:
    """top-N по 24ч $-обороту (метод на неликвиде тонет в спреде). Из тикеров data_collector."""
    ranked = []
    for p in pairs:
        try:
            tk = bot.data_collector.get_cached_ticker(p) if hasattr(bot.data_collector, "get_cached_ticker") else None
            qv = float((tk or {}).get("quoteVolume") or 0) if tk else 0
        except Exception:
            qv = 0
        ranked.append((qv, p))
    ranked.sort(reverse=True)
    picked = [p for qv, p in ranked if qv > 0][:topn]
    return picked or pairs[:topn]   # тикеры не прогреты → просто первые topn


def _open_count(db_path) -> int:
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT COUNT(*) FROM simulated_trades WHERE status IN ('OPEN','PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"method_v2\"%'").fetchone()[0]
    except Exception:
        return 10**9


def _symbol_busy(db_path, symbol: str) -> bool:
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            return c.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status IN ('OPEN','PENDING_ENTRY') "
                "AND features_json LIKE '%\"trade_mode\": \"method_v2\"%' LIMIT 1",
                (symbol,)).fetchone() is not None
    except Exception:
        return True


async def method_v2_loop(bot) -> None:
    """Скан ликвидных 4h+15m → detect_v2_mtf → свежий сетап → register (source='method_v2')."""
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[METHOD-V2] disabled (trading.method_v2.enabled=false) — loop не стартует")
        return
    try:
        from core.smc.method_v2_mtf import detect_v2_mtf
    except ImportError as e:
        logger.error("[METHOD-V2] detector import failed: %s", e)
        return
    scan_sec = float(cfg.get("scan_sec", DEFAULT_SCAN_SEC) or DEFAULT_SCAN_SEC)
    fresh_bars = int(cfg.get("fresh_bars_15m", 3))
    max_pos = int(cfg.get("max_positions", 5))
    conf_only = bool(cfg.get("conf_only", False))
    max_syms = int(cfg.get("max_symbols", 60))
    logger.info("[METHOD-V2] started: scan=%ds fresh=%d бар max_pos=%d conf_only=%s max_syms=%d",
                scan_sec, fresh_bars, max_pos, conf_only, max_syms)

    first = True
    while True:
        try:
            await asyncio.sleep(60 if first else scan_sec)
            first = False
            t0 = time.time()
            pairs = await _get_active_pairs(bot)
            if not pairs:
                continue
            pairs = _liquid_pairs(bot, pairs, max_syms)
            sem = asyncio.Semaphore(CONCURRENCY)
            fired = [0]

            async def _scan(sym):
                async with sem:
                    try:
                        if await _scan_one(bot, sym, detect_v2_mtf, fresh_bars, conf_only, max_pos):
                            fired[0] += 1
                    except Exception as e:
                        logger.debug("[METHOD-V2] %s: %s", sym, e)

            await asyncio.gather(*[_scan(s) for s in pairs])
            logger.info("[METHOD-V2] cycle: %d пар, fired=%d за %.1fs", len(pairs), fired[0], time.time() - t0)
        except asyncio.CancelledError:
            logger.info("[METHOD-V2] loop cancelled")
            raise
        except Exception as e:
            logger.exception("[METHOD-V2] loop error: %s", e)
            await asyncio.sleep(scan_sec)


async def _scan_one(bot, symbol, detect_v2_mtf, fresh_bars, conf_only, max_pos) -> bool:
    dc = getattr(bot, "data_collector", None)
    if dc is None:
        return False
    df_4h, df_15m = await asyncio.gather(
        _fetch_df(dc, symbol, "4h", 200),
        _fetch_df(dc, symbol, "15m", 500),
    )
    if df_4h is None or df_15m is None or len(df_4h) < 70 or len(df_15m) < 200:
        return False
    # детектор ждёт DatetimeIndex — _fetch_df даёт RangeIndex+ts-колонку; выставим индекс
    for _df in (df_4h, df_15m):
        if "ts" in _df.columns:
            _df.index = pd.to_datetime(_df["ts"], utc=True, errors="coerce")
        elif "time" in _df.columns:
            _df.index = pd.to_datetime(_df["time"], unit="ms", utc=True, errors="coerce")
    import functools
    _call = functools.partial(detect_v2_mtf, df_4h, df_15m)
    setups = await asyncio.get_running_loop().run_in_executor(None, _call)
    if not setups:
        return False
    # СВЕЖИЙ сетап = entry_ts в последних fresh_bars 15m-баров (иначе исторический, не торгуем)
    last_ts = df_15m.index[-1]
    fresh_cut = df_15m.index[-fresh_bars] if len(df_15m) >= fresh_bars else df_15m.index[0]
    fresh = [s for s in setups if s.entry_ts >= fresh_cut]
    if conf_only:
        fresh = [s for s in fresh if s.conf]
    if not fresh:
        return False
    s = fresh[-1]                                        # самый свежий
    if _open_count(bot.trade_simulator.db_path) >= max_pos:
        logger.info("[METHOD-V2] %s свежий сетап, но max_positions %d — skip", symbol, max_pos)
        return False
    if _symbol_busy(bot.trade_simulator.db_path, symbol):
        return False
    await _register(bot, symbol, s)
    return True


async def _register(bot, symbol, s) -> None:
    """Регистрация method_v2 FIRE через trade_router (образец _register_oko_trade)."""
    try:
        from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    except ImportError as e:
        logger.warning("[METHOD-V2] import failed: %s", e)
        return
    is_long = s.direction == "LONG"
    tps = [float(t) for t in s.targets if t]
    if not tps:
        return
    # v1: основной TP = ПЕРВАЯ цель (пробой волны 1, берётся 78% в бэктесте) — надёжный выход
    # через стандартный open_bracket (один attached TP). Лестница 40/30/30 (radar_tps в extra) =
    # v1.1: нужен post-fill хук для method_v2 (аналог radar_armed_loop._on_entry_filled).
    tp_main = tps[0]
    px_now = 0.0
    vol24 = 0.0
    try:
        tk = await bot.data_collector.get_ticker(symbol)
        if tk:
            px_now = float(tk.get("last") or tk.get("close") or 0)
            vol24 = float(tk.get("quoteVolume") or 0)
    except Exception:
        pass
    # свежесть цены: вход MARKET по волне 3, но если цена уже за первой целью / за стопом — skip
    if px_now > 0:
        if (tps[0] <= px_now) if is_long else (tps[0] >= px_now):
            logger.info("[METHOD-V2] %s %s: t1 уже пройдена (px=%.6g) — skip", symbol, s.direction, px_now)
            return
        if (px_now <= s.sl) if is_long else (px_now >= s.sl):
            logger.info("[METHOD-V2] %s %s: цена за стопом (px=%.6g) — skip", symbol, s.direction, px_now)
            return
    entry_px = px_now if px_now > 0 else float(s.entry)
    rec = TradingRecommendation(
        symbol=symbol, action="BUY" if is_long else "SELL",
        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
        overall_strength=75, confidence=0.75, risk_level="MEDIUM", signals_count=1,
        supporting_signals=[], conflicting_signals=[],
        market_context=MarketContext(symbol=symbol, current_price=entry_px,
                                     volume_24h=vol24, volume_change_24h=0.0, price_change_24h=0.0),
        entry_price=entry_px, stop_loss=float(s.sl), take_profit=tp_main,
        sl_source="v2:wave2", tp_source="v2:htf_t1",
    )
    extra = {
        "signal_type_override": "method_v2",
        "trade_mode": "method_v2",
        "trigger_source": "v2:wave3_bos",
        "v2_conf": bool(s.conf),
        "v2_htf_lo": s.htf_lo, "v2_htf_hi": s.htf_hi,
        "radar_tps": tps,                                # лестница целей → post-fill multi-TP (reuse)
    }
    try:
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            res = await bot.trade_router.submit(rec, source="method_v2", extra_features=extra)
            tid = getattr(res, "trade_id", None)
            if tid:
                logger.info("[METHOD-V2] %s %s → #%s entry=%.6g sl=%.6g tps=%s conf=%s",
                            symbol, s.direction, tid, entry_px, s.sl, tps, s.conf)
            else:
                drops = "; ".join(f"{g}:{d}" for g, d in getattr(res, "hard_drops", [])) or "none"
                logger.info("[METHOD-V2] %s router dropped: %s", symbol, drops)
        else:
            logger.warning("[METHOD-V2] signal_router.enabled=false — не регистрирую")
    except Exception as e:
        logger.exception("[METHOD-V2] %s register error: %s", symbol, e)
