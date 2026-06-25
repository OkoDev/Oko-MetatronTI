"""
OKO-OTE Observer Loop — НОВАЯ стратегия (метод Егора, валидирован 22.06.2026).

Отдельная стратегия (НЕ замена ote_nested). Источник сигналов = detect_oko_ote:
  WT-зона(зона-ТФ OB/OS) → слом структуры(слом-ТФ) → OTE 0.618 → фильтр средней глубины
  → SL=Strong Low, TP=ближайший магнит. Карта связок: 4h→1h / 4h→15m / 1h→15m (SHADOW-ядро).

Брат-близнец ote_observer_loop — REUSE инфры:
  - _get_active_pairs / _fetch_df  (тот же кэш scan_loop, без REST-дублей)
  - регистрация — образец _register_ote_trade (TradingRecommendation → trade_router/simulator)
Gated: config trading.strategies.oko_ote.enabled (default false). Выключено → loop не стартует.
signal_type='oko_ote', trade_mode='oko_ote' (свой режим, dedup, отдельные метрики).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import pandas as pd

from bot.loops.arch104_observer_loop import _get_active_pairs, _fetch_df

logger = logging.getLogger(__name__)

OKO_OTE_INTERVAL_SECONDS = 600
OKO_OTE_CONCURRENCY = 3
MIN_BARS = 50
DEFAULT_LINKS = [("4h", "1h"), ("4h", "15m"), ("1h", "15m")]

# ARMED-watcher (25.06, Егор): окно слепоты между сканами скан-цикла (600с) — если гейт
# свежести не пустил (цена ушла от зоны), сетап раньше просто забывался до следующего скана
# (10 мин слепоты). Теперь храним его здесь и проверяем ЧАСТО (get_current_price — WS,
# 0 latency, без REST) — окно падает с 600с до ARMED_CHECK_INTERVAL_SECONDS. Детектор
# (дорогой: zigzag+WT+confirmations) НЕ перезапускается чаще — только дешёвая цена.
ARMED_CHECK_INTERVAL_SECONDS = 12
# TTL зависит от break_tf сделки (Егор 25.06: 8 баров 15m ≠ 8 баров 1h по факт. времени) —
# не флэт-минуты, а N баров ТОГО ТФ, на котором нашли слом (confirmations считаются по его
# барам, естественный масштаб дрифта). 8 баров ≈ тот же порядок, что обычно занимает набор
# confs≥3 (эталон оценки, не измерено отдельно) — НЕ магическое число навечно, see TASKS если
# нужно калибровать по факту armed_at→fire задержкам.
ARMED_TTL_BARS = 8
_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
_ARMED_SETUPS: dict = {}   # symbol -> {"sig":..., "cfg":..., "armed_at": float, "expiry": float}


def _armed_ttl_minutes(sig, cfg) -> float:
    """TTL = N баров break_tf (N из cfg.armed_ttl_bars, default ARMED_TTL_BARS)."""
    bars = float(cfg.get("armed_ttl_bars", ARMED_TTL_BARS) or ARMED_TTL_BARS)
    tf_min = _TF_MINUTES.get(getattr(sig, "break_tf", None), 15)
    return bars * tf_min


def _cfg(bot) -> dict:
    try:
        return bot.config.get("trading.strategies.oko_ote", {}) or {}
    except Exception:
        return {}


async def oko_ote_observer_loop(bot, interval_seconds: int = OKO_OTE_INTERVAL_SECONDS):
    """Главный loop OKO-OTE — раз в interval сканит ядро связок, регистрирует FIRE на VST."""
    cfg = _cfg(bot)
    if not cfg.get("enabled", False):
        logger.info("[OKO-OTE] disabled (config strategies.oko_ote.enabled=false) — loop не стартует")
        return
    try:
        from core.smc.oko_ote import detect_oko_ote, SHADOW_LINKS  # noqa
    except ImportError as e:
        logger.error("[OKO-OTE] detector import failed: %s", e)
        return
    links = [(l["zone"], l["break"]) for l in cfg.get("links", [])] or DEFAULT_LINKS
    logger.info("[OKO-OTE] started. links=%s interval=%ds risk=%.2f%% max_conc=%d",
                links, interval_seconds, cfg.get("risk_pct", 0.5), cfg.get("max_concurrent", 10))
    asyncio.create_task(_armed_watcher_loop(bot, cfg))

    first = True
    while True:
        try:
            await asyncio.sleep(60 if first else interval_seconds)
            first = False
            t0 = time.time()
            pairs = await _get_active_pairs(bot)
            if not pairs:
                continue
            sem = asyncio.Semaphore(OKO_OTE_CONCURRENCY)
            counters = {"scanned": 0, "fired": 0}
            lock = asyncio.Lock()

            async def _bounded(sym):
                async with sem:
                    try:
                        fired = await _scan_one_oko(bot, sym, links, cfg)
                        async with lock:
                            counters["scanned"] += 1
                            counters["fired"] += fired
                    except Exception as e:
                        logger.debug("[OKO-OTE] %s: %s", sym, e)

            await asyncio.gather(*[_bounded(s) for s in pairs])
            logger.info("[OKO-OTE] cycle: scanned=%d fired=%d за %.1fs",
                        counters["scanned"], counters["fired"], time.time() - t0)
        except asyncio.CancelledError:
            logger.info("[OKO-OTE] loop cancelled")
            raise
        except Exception as e:
            logger.exception("[OKO-OTE] loop error: %s", e)
            await asyncio.sleep(interval_seconds)


def _arm_setup(sig, cfg) -> None:
    """Кладёт сетап в ARMED — частый WS-поллинг (_armed_watcher_loop) подхватит, когда
    цена дойдёт до зоны. Один ARMED на символ — новый сигнал замещает старый (не копится).
    TTL зависит от sig.break_tf (_armed_ttl_minutes) — 8 баров 15m ≠ 8 баров 1h."""
    now = time.time()
    ttl_min = _armed_ttl_minutes(sig, cfg)
    _ARMED_SETUPS[sig.symbol] = {"sig": sig, "cfg": cfg, "armed_at": now, "expiry": now + ttl_min * 60}


async def _armed_watcher_loop(bot, cfg) -> None:
    """Частый (ARMED_CHECK_INTERVAL_SECONDS) дешёвый поллинг цены для ARMED-сетапов — закрывает
    окно слепоты 10-минутного скан-цикла без пересчёта детектора и без лимит-ордера на бирже
    (Вариант Б, полноценный лимит-вход, — отдельная задача). get_current_price = WS, 0 REST.
    """
    interval = float(cfg.get("armed_check_interval_sec", ARMED_CHECK_INTERVAL_SECONDS) or ARMED_CHECK_INTERVAL_SECONDS)
    dc = getattr(bot, "data_collector", None)
    while True:
        try:
            await asyncio.sleep(interval)
            if not _ARMED_SETUPS or dc is None:
                continue
            now = time.time()
            for symbol, item in list(_ARMED_SETUPS.items()):
                if now >= item["expiry"]:
                    logger.info("[OKO-OTE ARMED-EXPIRE] %s истёк (%.0f мин)", symbol,
                                (now - item["armed_at"]) / 60.0)
                    _ARMED_SETUPS.pop(symbol, None)
                    continue
                sig, sig_cfg = item["sig"], item["cfg"]
                try:
                    px = await dc.get_current_price(symbol)
                except Exception:
                    px = None
                if not px or not sig.entry:
                    continue
                max_slip = float(sig_cfg.get("max_entry_slippage_pct", 0.5) or 0)
                slip = abs(float(px) - sig.entry) / sig.entry * 100.0
                if slip <= max_slip:
                    _ARMED_SETUPS.pop(symbol, None)   # снять ДО await — не словить дублирующий fire
                    logger.info("[OKO-OTE ARMED-FIRE] %s цена догнала зону (px=%.6g vs OTE=%.6g, slip=%.2f%%, ждали %.0fс)",
                                symbol, px, sig.entry, slip, now - item["armed_at"])
                    await _register_oko_trade(bot, sig, sig_cfg)
        except asyncio.CancelledError:
            logger.info("[OKO-OTE ARMED] watcher cancelled")
            raise
        except Exception as e:
            logger.debug("[OKO-OTE ARMED] watcher error: %s", e)


async def _scan_one_oko(bot, symbol: str, links, cfg) -> int:
    dc = getattr(bot, "data_collector", None)
    if dc is None:
        return 0
    # ТФ из кэша (cache-hit от scan_loop): нужны 4h/1h/15m для ядра связок
    df_4h, df_1h, df_15m = await asyncio.gather(
        _fetch_df(dc, symbol, "4h", 200),
        _fetch_df(dc, symbol, "1h", 300),
        _fetch_df(dc, symbol, "15m", 400),
    )
    dfs = {"4h": df_4h, "1h": df_1h, "15m": df_15m}
    from core.smc.oko_ote import detect_oko_ote
    _loop = asyncio.get_running_loop()
    fired = 0
    for zone_tf, break_tf in links:
        dz, db = dfs.get(zone_tf), dfs.get(break_tf)
        if dz is None or db is None or len(dz) < MIN_BARS or len(db) < 200:
            continue
        # детектор CPU-bound (zigzag+wt+detect_*) → в executor, не морозить loop (PERF-LOOP-DRIFT)
        # dfs (полный: 4h/1h/15m) → подтверждения как ote_nested (atr 3m/15m + div/wt/vol/liq)
        sig = await _loop.run_in_executor(None, detect_oko_ote, symbol, dz, db, zone_tf, break_tf,
                                          True, None, dfs)
        if sig is None:
            continue
        logger.info("[OKO-OTE FIRE] %s %s %s->%s entry=%s SL=%s TP=%s RR=%s depth=%s [%s]",
                    sig.symbol, sig.direction, sig.zone_tf, sig.break_tf,
                    sig.entry, sig.sl, sig.tp, sig.rr, sig.depth, sig.tp_source)
        # WATCHLIST-UNI: публикуем в универсальный watchlist (% хода, НЕ фейк-R)
        try:
            _bus = getattr(bot, "pair_context", None)
            if _bus is not None:
                _pot = round(abs(sig.tp - sig.entry) / sig.entry * 100, 1) if sig.entry else 0.0
                _bus.set_watchlist(sig.symbol, "oko_ote", {
                    "direction": sig.direction, "status": "FIRE",
                    "entry": sig.entry, "sl": sig.sl,
                    "targets": sig.targets or [[sig.tp, sig.tp_source]],
                    "setup": f"{sig.zone_tf}->{sig.break_tf}",
                    "confs": sig.zone_ts, "potential_pct": _pot, "tf": sig.break_tf,
                })
        except Exception:
            pass
        if cfg.get("enabled", False):
            # ГЕЙТ СВЕЖЕСТИ ВХОДА (25.06): вход исполняется MARKET по ТЕКУЩЕЙ цене, а SL/TP/цели
            # считаются от sig.entry (OTE-уровень X). Если цена ушла от X (медиана разрыва была
            # 3.57%, 55% сделок >3%) — market войдёт по уехавшей Y, R:R сломан, даже TP в минус.
            # Skip если |цена−OTE|/OTE > порога → поймаем на следующем 10-мин цикле когда цена у зоны
            # (метод OTE = ждать откат В зону, не гнаться маркетом). Полный лимит-вход = Фаза Б.
            # 25.06 ОТКАТ Варианта А (zone_lo/zone_hi): валидация на 336 закрытых VST показала
            # тугой 0.5%-гейт отсекает сделки в 6× хуже среднего (−1.203% vs −0.206%) — расширение
            # до зоны 0.5-0.705 впустило бы обратно именно эти убыточные. Тугой гейт ВЕРНЫЙ, не
            # бракует находки — отсекает версии сетапа, где рынок уже ушёл пока копились подтв.
            max_slip = float(cfg.get("max_entry_slippage_pct", 0.5) or 0)
            if max_slip > 0 and sig.entry:
                px = 0.0
                try:
                    tk = await bot.data_collector.get_ticker(sig.symbol)
                    px = float((tk or {}).get("last") or (tk or {}).get("close") or 0)
                except Exception:
                    px = 0.0
                if px > 0:
                    slip = abs(px - sig.entry) / sig.entry * 100.0
                    if slip > max_slip:
                        # ARMED-watcher (25.06): не забываем сетап до след. скана (10 мин слепоты) —
                        # кладём на частый WS-поллинг (ARMED_CHECK_INTERVAL_SECONDS), см. _armed_watcher_loop.
                        _arm_setup(sig, cfg)
                        logger.info("[OKO-OTE ARMED] %s slippage %.2f%% > %.2f%% (px=%.6g vs OTE=%.6g) — ждём отката (watcher %ds)",
                                    sig.symbol, slip, max_slip, px, sig.entry, ARMED_CHECK_INTERVAL_SECONDS)
                        break
            await _register_oko_trade(bot, sig, cfg)
            fired += 1
        break   # один сетап на пару за цикл (старшая связка приоритетна — links отсортированы)
    return fired


async def _register_oko_trade(bot, sig, cfg) -> None:
    """Регистрация OKO-OTE FIRE на VST. Образец: _register_ote_trade (reuse контракт)."""
    try:
        from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    except ImportError as e:
        logger.warning("[OKO-OTE VST] import failed: %s", e)
        return
    is_long = sig.direction == "long"
    vol24 = 0.0
    try:
        tk = await bot.data_collector.get_ticker(sig.symbol)
        if tk:
            vol24 = float(tk.get("quoteVolume") or 0.0)
    except Exception:
        pass
    rec = TradingRecommendation(
        symbol=sig.symbol,
        action="BUY" if is_long else "SELL",
        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
        overall_strength=70, confidence=0.7, risk_level="MEDIUM", signals_count=1,
        supporting_signals=[], conflicting_signals=[],
        market_context=MarketContext(
            symbol=sig.symbol, current_price=sig.entry,
            volume_24h=vol24, volume_change_24h=0.0, price_change_24h=0.0,
        ),
        entry_price=sig.entry, stop_loss=sig.sl, take_profit=sig.tp,
        sl_source="oko:strong_low", tp_source=f"oko:{sig.tp_source}",
    )
    extra = {
        "signal_type_override": "oko_ote",
        "trade_mode": "oko_ote",
        "trigger_source": f"oko:{sig.zone_tf}->{sig.break_tf}",
        "oko_zone_tf": sig.zone_tf, "oko_break_tf": sig.break_tf,
        "oko_depth": sig.depth, "oko_rr": sig.rr,
        "oko_zone_ts": sig.zone_ts, "oko_choch_ts": sig.choch_ts,
    }
    try:
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            res = await bot.trade_router.submit(rec, source="oko_ote", extra_features=extra)
            if not getattr(res, "trade_id", None):
                drops = "; ".join(f"{g}:{d}" for g, d in getattr(res, "hard_drops", [])) or "none"
                logger.info("[OKO-OTE VST] %s router dropped: %s", sig.symbol, drops)
        else:
            await bot.trade_simulator.register_trade_async(rec, bot.data_collector, extra_features=extra)
            logger.info("[OKO-OTE VST] %s registered (simulator)", sig.symbol)
    except Exception as e:
        logger.exception("[OKO-OTE VST] %s register error: %s", sig.symbol, e)
