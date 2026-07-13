"""
OTE Observer Loop — генерация OTE-сигналов из шкафа сетапов + регистрация VST.

Брат-близнец arch104_observer_loop, но другой источник сигналов:
  arch104 = combinator-флаги → ARCH104SignalAdapter (паттерны)
  ote     = геометрия OTE → OTESignalGenerator (скелеты сетапов)

Конвейер на пару (раз в interval):
1. Fetch ТФ из data_collector КЭШ (3m/5m/15m/1h/4h/1d) — cache-hit от scan_loop, НЕ REST дубль
2. gen.generate(sym, dfs) → [OTESignal] (status ARMED/FIRE)
3. ARMED → лог (зреет, ждём курок). FIRE → register_trade (signal_type='ote_nested')

ARCH-128. Образец регистрации — _try_register_vst_trade из arch104_observer_loop.
Калибровки в генераторе: provisional нога · zigzag per-ТФ · FVG mitigation · SC · EQL фильтр.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import pandas as pd

# Переиспользуем инфраструктуру брата (тот же кэш, тот же список пар)
from bot.loops.arch104_observer_loop import _get_active_pairs, _fetch_df
from bot.notifications.sender import notify as _notify

logger = logging.getLogger(__name__)

OTE_OBSERVER_INTERVAL_SECONDS = 600   # 5 мин — выстрел нужен timely, зоны живут часами
OTE_OBSERVER_CONCURRENCY = 3          # детекторы тяжелее compute_flags → мягче к API
MIN_BARS = 50

# ARMED-watcher (27.06, порт oko_ote): generate() тяжёлая (2.6-35s/пара) → главный цикл редкий
# (600s). ARMED-сигнал (зона найдена, цена ещё не вернулась в неё) кладём сюда; дешёвый поллинг
# цены (12s, WS get_current_price — 0 REST) ловит момент возврата в OTE-зону → FIRE. Окно слепоты
# 600s→12s БЕЗ перезапуска детектора. Один ARMED на символ (новый замещает) + pop ДО await register
# = «ОДИН СИГНАЛ — ОДНА СДЕЛКА» (idempotent, не словить дубль-fire между сканами).
ARMED_CHECK_INTERVAL_SECONDS = 12
ARMED_TTL_BARS = 8       # TTL = 8 баров ltf (масштаб дрифта зоны: 8×5m ≠ 8×1h)
_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
_ARMED_SETUPS: dict = {}   # symbol -> {"sig":..., "armed_at": float, "expiry": float}


def _arm_ote_setup(sig) -> None:
    """Кладёт ARMED-сетап в watcher. Один на символ — новый замещает старый (не копится)."""
    now = time.time()
    tf_min = _TF_MINUTES.get(getattr(sig, "ltf", None), 15)
    _ARMED_SETUPS[sig.symbol] = {"sig": sig, "armed_at": now, "expiry": now + ARMED_TTL_BARS * tf_min * 60}


async def _armed_watcher_ote_loop(bot) -> None:
    """Дешёвый поллинг цены (12s) ARMED-сетапов → FIRE когда цена вернулась в OTE-зону.
    Закрывает окно слепоты 600s-цикла без пересчёта generate(). pop ДО register = idempotent
    («один сигнал-одна сделка»). Регистрирует только при ote.vst_trading.enabled."""
    dc = getattr(bot, "data_collector", None)
    while True:
        try:
            await asyncio.sleep(ARMED_CHECK_INTERVAL_SECONDS)
            if not _ARMED_SETUPS or dc is None:
                continue
            if not bool(bot.config.get("ote.vst_trading.enabled", False)):
                continue
            now = time.time()
            for symbol, item in list(_ARMED_SETUPS.items()):
                if now >= item["expiry"]:
                    logger.info("[OTE ARMED-EXPIRE] %s истёк (%.0f мин)", symbol,
                                (now - item["armed_at"]) / 60.0)
                    _ARMED_SETUPS.pop(symbol, None)
                    continue
                sig = item["sig"]
                try:
                    px = await dc.get_current_price(symbol)
                except Exception:
                    px = None
                if not px or not getattr(sig, "ote_zone", None):
                    continue
                zlo, zhi = sig.ote_zone
                if zlo <= float(px) <= zhi:                 # цена вернулась в OTE-зону → курок
                    _ARMED_SETUPS.pop(symbol, None)         # снять ДО await: один сигнал-одна сделка
                    logger.info("[OTE ARMED-FIRE] %s цена в зоне (px=%.6g zone=[%.6g,%.6g], ждали %.0fс)",
                                symbol, px, zlo, zhi, now - item["armed_at"])
                    # CASCADE-гейт и на ARMED-пути (раньше shadow здесь вообще не считался)
                    if not await _cascade_gate_blocks(bot, dc, symbol, sig):
                        await _register_ote_trade(bot, sig)
        except asyncio.CancelledError:
            logger.info("[OTE ARMED] watcher cancelled")
            raise
        except Exception as e:
            logger.debug("[OTE ARMED] watcher error: %s", e)


async def ote_observer_loop(bot, interval_seconds: int = OTE_OBSERVER_INTERVAL_SECONDS):
    """Главный loop — раз в interval генерит OTE-сигналы для всех пар, регистрирует FIRE."""
    try:
        from core.smc.ote_signal_generator import OTESignalGenerator
    except ImportError as e:
        logger.error("[OTE observer] generator import failed: %s", e)
        return

    gen = OTESignalGenerator()
    logger.info("[OTE observer] started. %d enabled-сетапов. Interval=%ds + ARMED-watcher %ds",
                len(gen.setups), interval_seconds, ARMED_CHECK_INTERVAL_SECONDS)
    asyncio.create_task(_armed_watcher_ote_loop(bot))   # 27.06: окно слепоты 600s→12s

    first_cycle = True
    while True:
        try:
            await asyncio.sleep(60 if first_cycle else interval_seconds)
            first_cycle = False
            t0 = time.time()
            pairs = await _get_active_pairs(bot)
            if not pairs:
                logger.debug("[OTE observer] no active pairs")
                continue

            sem = asyncio.Semaphore(OTE_OBSERVER_CONCURRENCY)
            counters = {"scanned": 0, "armed": 0, "fired": 0}
            lock = asyncio.Lock()

            async def _bounded(sym):
                async with sem:
                    try:
                        armed, fired = await _scan_one_pair_ote(bot, sym, gen)
                        async with lock:
                            counters["scanned"] += 1
                            counters["armed"] += armed
                            counters["fired"] += fired
                    except Exception as e:
                        logger.debug("[OTE observer] %s: %s", sym, e)

            await asyncio.gather(*[_bounded(s) for s in pairs])
            elapsed = time.time() - t0
            logger.info("[OTE observer] scanned=%d armed=%d fired=%d in %.1fs (pairs=%d)",
                        counters["scanned"], counters["armed"], counters["fired"],
                        elapsed, len(pairs))

        except asyncio.CancelledError:
            logger.info("[OTE observer] cancelled")
            break
        except Exception as e:
            logger.exception("[OTE observer] error: %s", e)
            await asyncio.sleep(60)


async def _scan_one_pair_ote(bot, symbol: str, gen) -> tuple[int, int]:
    """Scan одной пары → (armed_count, fired_count). FIRE-сигналы регистрируются."""
    data_collector = getattr(bot, "data_collector", None)
    if data_collector is None:
        return 0, 0

    # Fetch из кэша (cache-hit от scan_loop). 3m может отсутствовать — генератор gracefully.
    df_3m, df_5m, df_15m, df_1h, df_4h = await asyncio.gather(
        _fetch_df(data_collector, symbol, "3m", 600),
        _fetch_df(data_collector, symbol, "5m", 500),
        _fetch_df(data_collector, symbol, "15m", 400),
        _fetch_df(data_collector, symbol, "1h", 300),
        _fetch_df(data_collector, symbol, "4h", 200),
    )
    if df_1h is None or len(df_1h) < MIN_BARS:
        return 0, 0

    dfs = {"3m": df_3m, "5m": df_5m, "15m": df_15m, "1h": df_1h, "4h": df_4h}
    # 1d агрегат из 1h (зоны на 1d-импульсах)
    if df_1h is not None:
        dfs["1d"] = pd.DataFrame({
            "open": df_1h["open"].resample("1D").first(), "high": df_1h["high"].resample("1D").max(),
            "low": df_1h["low"].resample("1D").min(), "close": df_1h["close"].resample("1D").last(),
        }).dropna()
    dfs = {k: v for k, v in dfs.items() if v is not None}

    # ⚡ PERF (Шаг executor, 13.06): generate() — СИНХРОННАЯ CPU-bound (ZigZag+FVG+OB+OTE,
    # 2.6-35s). В главном loop она замораживала его целиком → торговые direct-запросы
    # (sync_time/get_positions) виснут → timestamp invalid → DRIFT. run_in_executor выносит
    # расчёт в thread pool → loop свободен. generate stateless (self read-only) → thread-safe.
    # PERF-LOOP-DRIFT.
    _loop = asyncio.get_running_loop()
    signals = await _loop.run_in_executor(None, gen.generate, symbol, dfs)
    armed = fired = 0
    for sig in signals:
        if sig.status == "ARMED":
            armed += 1
            logger.info("[OTE armed] %s [%s T%d] %s zone=%s trgN=%d conf=%d%s unconf=%s",
                        symbol, sig.setup_id, sig.tier, sig.direction,
                        sig.ote_zone, sig.meta.get("triggers_n"), sig.conf_score,
                        sig.confirmations, sig.meta.get("unconfirmed"))
            # 27.06: в ARMED-watcher — поймает возврат цены в OTE-зону через ≤12с (не ≤600с).
            # Один на символ (замещает) → «один сигнал-одна сделка».
            if bool(bot.config.get("ote.vst_trading.enabled", False)):
                _arm_ote_setup(sig)
        elif sig.status == "FIRE":
            fired += 1
            logger.info("[OTE FIRE] %s [%s T%d] %s entry=%s SL=%s TP1=%s trg=%s conf=%d%s",
                        symbol, sig.setup_id, sig.tier, sig.direction,
                        sig.entry, sig.sl, sig.tp1, sig.trigger_type,
                        sig.conf_score, sig.confirmations)
            # OTE-CASCADE: shadow-лог всегда (сверка DS); при ote.cascade_gate=true —
            # вход против 1D-тренда БЛОКИРУЕТСЯ (03.07, диагноз Егора «слеп к матрице HTF»).
            _casc_blocked = await _cascade_gate_blocks(bot, data_collector, symbol, sig)
            if bool(bot.config.get("ote.vst_trading.enabled", False)) and not _casc_blocked:
                await _register_ote_trade(bot, sig)   # 27.06: phase_gate shadow снят

    # ARCH-128: проявление в шину — лучший сигнал (FIRE > ARMED, max conf) в pair_context.
    # Только observability для вотчлиста/ручной торговли — торговая логика выше не меняется.
    _publish_ote_ltf_state(bot, symbol, signals)
    return armed, fired


async def _cascade_1d_shadow(data_collector, symbol: str, sig):
    """OTE-CASCADE (19.06, Claude→DS): 1D-трендфильтр на каждый ote_nested FIRE.
    Лог would_block (сверка DS) + ВОЗВРАТ вердикта: True=против 1D-тренда, False=по тренду,
    None=unknown (мало баров/NaN — fail-open, не гадаем). Блокирует ли регистрацию —
    решает вызывающий по флагу ote.cascade_gate (03.07). Контракт: DISCUSSION 19.06 ~09:30.
    🔴 Фетчим 60 НАСТОЯЩИХ 1D-баров (НЕ dfs['1d'] из resample 1h×300 = ~12 баров < 43 для ATR)."""
    df_1d = await data_collector.get_ohlcv(symbol, timeframe="1d", limit=60)
    n = 0 if df_1d is None else len(df_1d)
    if n < 43:  # calculate_trend atr_period=43 → меньше баров = NaN тренд
        logger.info("[CASCADE][shadow] %s dir=%s 1d_trend=NA bars=%d would_block=unknown",
                    symbol, sig.direction, n)
        return None
    from core.indicators.indicators import calculate_trend
    last = calculate_trend(df_1d)["trend"].iloc[-1]
    if pd.isna(last):
        logger.info("[CASCADE][shadow] %s dir=%s 1d_trend=NaN would_block=unknown", symbol, sig.direction)
        return None
    d1 = "LONG" if last > 0 else "SHORT"
    _sdir = str(sig.direction).upper()  # sig.direction = 'long'/'short' (lowercase) → нормализуем
    would_block = _sdir != d1  # вход ПРОТИВ 1D-тренда
    logger.info("[CASCADE][shadow] %s dir=%s 1d_trend=%s would_block=%s entry=%s conf=%d",
                symbol, _sdir, d1, would_block, sig.entry, sig.conf_score)
    return would_block


async def _cascade_gate_blocks(bot, data_collector, symbol: str, sig) -> bool:
    """OTE-CASCADE GATE (03.07, Егор: «ote_nested не знает где находится относительно матрицы
    HTF»). shadow-данные n=37: против-1D = −0.72%/сд win17%, по-1D = +1.07%/сд win44%.
    True = вход блокируется (против 1D-тренда при ote.cascade_gate=true). unknown → fail-open."""
    _shadow_on = bool(bot.config.get("ote.cascade_shadow", True))
    _gate_on = bool(bot.config.get("ote.cascade_gate", False))
    if not (_shadow_on or _gate_on):
        return False
    try:
        wb = await _cascade_1d_shadow(data_collector, symbol, sig)
    except Exception as _e:
        logger.debug("[CASCADE] %s error (fail-open): %s", symbol, _e)
        return False
    if _gate_on and wb is True:
        logger.info("[CASCADE][GATE] %s %s BLOCKED — вход против 1D-тренда", symbol,
                    str(sig.direction).upper())
        try:
            from core.observability.decision_trace import record_drop
            asyncio.create_task(record_drop(
                symbol=symbol, gate_name="cascade_1d_gate",
                drop_reason=f"ote_nested/{str(sig.direction).upper()}: против 1D-тренда",
                signal_type="ote_nested", direction=str(sig.direction).upper(),
                strength=int(getattr(sig, "conf_score", 0) or 0), features={}))
        except Exception:
            pass
        return True
    return False


def _publish_ote_ltf_state(bot, symbol: str, signals: list) -> None:
    """Пишет LTF-состояние OTE в pair_context — чтобы дашборд видел сигнал ЗАРАНЕЕ
    (ARMED зреет) и при FIRE имел все вводные для ручного входа (entry/SL/TP)."""
    pair_ctx = getattr(bot, "pair_context", None)
    if pair_ctx is None:
        return
    try:
        st = pair_ctx.get(symbol)
        if not signals:
            # сброс протухшего состояния, если сетап ушёл
            if st.ote_ltf_status is not None:
                st.ote_ltf_status = None
                st.ote_ltf_score = 0
            return
        # лучший: FIRE приоритетнее ARMED, затем по conf_score
        best = max(signals, key=lambda s: (1 if s.status == "FIRE" else 0, s.conf_score))
        st.ote_ltf_status    = best.status
        st.ote_ltf_score     = int(best.conf_score)
        st.ote_ltf_min       = 3   # min_confirmations (порог выстрела, из ote config)
        st.ote_ltf_direction = best.direction
        st.ote_ltf_trigger   = best.trigger_type or None
        st.ote_ltf_entry     = float(best.entry) if best.entry else None
        st.ote_ltf_sl        = float(best.sl) if best.sl else None
        st.ote_ltf_tp1       = float(best.tp1) if best.tp1 else None
        st.ote_ltf_tp        = float(best.tp_runner) if getattr(best, "tp_runner", None) else None
        st.ote_ltf_setup     = best.setup_id
        from datetime import datetime, timezone
        st.ote_ltf_time      = datetime.now(timezone.utc)
    except Exception as e:
        logger.debug("[OTE ltf-publish] %s: %s", symbol, e)


async def _register_ote_trade(bot, sig):
    """Регистрирует OTE-сигнал (FIRE) через trade_router/simulator. signal_type='ote_nested'.

    Образец: _try_register_vst_trade (arch104). TP = tp1 (+1R, ПОЛНЫЙ выход, mean-reversion;
    27.06 — было tp_runner). SL = sig.sl (за свип/импульс).
    """
    try:
        from core.signals.signal_models import (
            TradingRecommendation, SignalDirection, MarketContext,
        )
    except ImportError as e:
        logger.warning("[OTE VST] import failed: %s", e)
        return

    is_long = sig.direction == "long"
    # 🔴 ГЕЙТ СВЕЖЕСТИ ВХОДА (27.06): generate() даёт FIRE по КЭШУ (до ~10 мин) → MARKET-вход
    # по уехавшей цене ломает R:R (TP/SL считаны от сигнальной entry, факт-вход иной). MMT #37454
    # LONG: факт-вход +1.6% выше сигнала → собственный TP оказался НИЖЕ входа → «TP» в −0.42%.
    # Регистрируем ТОЛЬКО если цена ещё у sig.entry и на правильной стороне (LONG не выше зоны /
    # SHORT не ниже). Та же защита, что у oko_ote (aa3ad63). Порог ote.max_entry_slippage_pct.
    try:
        _px = await bot.data_collector.get_current_price(sig.symbol)
    except Exception:
        _px = None
    if _px and sig.entry:
        _max_slip = float(bot.config.get("ote.max_entry_slippage_pct", 0.5) or 0)
        _slip = abs(float(_px) - sig.entry) / sig.entry * 100.0
        _dir_ok = (float(_px) <= sig.entry * (1 + _max_slip / 100)) if is_long \
                  else (float(_px) >= sig.entry * (1 - _max_slip / 100))
        if _slip > _max_slip or not _dir_ok:
            logger.info("[OTE VST] %s %s SKIP слиппедж: px=%.6g vs entry=%.6g (slip=%.2f%%>%.2f%% / dir_ok=%s)",
                        sig.symbol, sig.direction, _px, sig.entry, _slip, _max_slip, _dir_ok)
            return
    side_enum = SignalDirection.LONG if is_long else SignalDirection.SHORT
    action = "BUY" if is_long else "SELL"
    # strength из tier: T1→~85, T2→~73, T3→~61
    strength = max(60, min(95, 55 + int(sig.weight * 30)))
    confidence = max(0.55, min(0.9, 0.55 + sig.weight * 0.3))

    # реальный 24h оборот (был хардкод 0.0 → ломал LIQ-GATE эксперимент: нечем split ликвид/неликвид)
    _vol24 = 0.0
    try:
        _tk = await bot.data_collector.get_ticker(sig.symbol)
        if _tk:
            _vol24 = float(_tk.get("quoteVolume") or 0.0)
    except Exception:
        pass

    rec = TradingRecommendation(
        symbol=sig.symbol,
        action=action,
        direction=side_enum,
        overall_strength=strength,
        confidence=confidence,
        risk_level="MEDIUM",
        signals_count=1,
        supporting_signals=[],
        conflicting_signals=[],
        market_context=MarketContext(
            symbol=sig.symbol, current_price=sig.entry,
            volume_24h=_vol24, volume_change_24h=0.0, price_change_24h=0.0,
        ),
        entry_price=sig.entry,
        stop_loss=sig.sl,
        take_profit=sig.tp1,          # 27.06: выход = tp1 (1R, mean-reversion), не runner
        sl_source=f"ote:{sig.htf}_impulse",
        tp_source=f"ote:tp1_{sig.setup_id}",
    )

    extra = {
        "signal_type_override": "ote_nested",
        "trigger_source": f"ote:{sig.setup_id}:{sig.trigger_type}",
        "ote_setup_id": sig.setup_id,
        "ote_tier": sig.tier,
        "ote_type": sig.type,          # pull / cont
        "ote_htf": sig.htf,
        "ote_ltf": sig.ltf,
        "ote_trigger": sig.trigger_type,
        "ote_tp1": sig.tp1,            # частичный +1R (50%)
        "ote_zone_lo": sig.ote_zone[0],
        "ote_zone_hi": sig.ote_zone[1],
        "ote_unconfirmed": bool(sig.meta.get("unconfirmed")),
        "ote_atr_trend_up": sig.atr_trend_up,
        # confirmations-лог (18.06): какие подтверждения РЕАЛЬНО сработали (div/fvg_held/vol/
        # liq_sweep/wt_cross/atr). Превращает слепое пятно в обучающий контур. ПРИНЦИП для ВСЕХ
        # составных стратегий: логировать сработавшие компоненты (arch104 → matched_patterns).
        # 🔴 12.07 ДИСКРЕТИЗАЦИЯ + разрез Егора (ИЗМЕРЕНИЕ, без гейтов — рано): fvg_held +0.27%.
        # div TF-условен (ltf=1h +0.34% vs 15m/5m −0.16%), НО на LTF валиден каскад (двойное/
        # тройное дно, div_cascade_1h_15m) ≠ одиночный див против импульса. Различие капчерим,
        # гейт НЕ вводим до форвард-валидации на честной эре.
        "ote_confirmations": "+".join(sig.confirmations) if sig.confirmations else "",
        "ote_conf_score": sig.conf_score,
        "trade_mode": "ote_nested",   # dedup: свой режим
    }
    # OB/SC ПЛУМБИНГ (12.07, DS: «OB у ote_nested 1/8645» + Егор «SC сильнее OB»):
    # trigger_type = склеенная строка "FVG+OB+SC" — майнинг видит её как одну фичу, компоненты
    # невидимы. Раскладываем на дискретные булевы флаги → минабельно per-компонент.
    # Приоритет силы генератора (ote_signal_generator:131): SC*>EQL>OB>FVG (SC*=5 OB=3 FVG=2).
    _trg = set((sig.trigger_type or "").split("+"))
    _trg_w = {"SC*": 5, "EQL": 4, "SC": 4, "OB": 3, "FVG": 2}
    extra.update({
        "ote_trg_fvg":      int("FVG" in _trg),
        "ote_trg_ob":       int("OB" in _trg),
        "ote_trg_eql":      int("EQL" in _trg),
        "ote_trg_sc":       int("SC" in _trg),    # sponsor candle (неподтв.)
        "ote_trg_sc_star":  int("SC*" in _trg),   # подтверждённый SC — сильнейший (Егор)
        "ote_trg_strength": max((_trg_w.get(t, 0) for t in _trg), default=0),
    })
    # ПОДТВЕРЖДЕНИЯ тоже склейка (ote_confirmations="div+wt_cross+atr" — код помечал
    # «какое несёт edge, особенно div», но майнить строку нельзя). Дискретизируем.
    _cf = set(sig.confirmations or [])
    extra.update({
        "ote_cf_atr":       int("atr" in _cf),
        "ote_cf_wt_cross":  int("wt_cross" in _cf),
        "ote_cf_fvg_held":  int("fvg_held" in _cf),
        "ote_cf_div":       int("div" in _cf),
        "ote_cf_vol":       int("vol" in _cf),
    })
    # CASCADE-DIV из meta (12.07, Егор): div на каждом ТФ + флаг каскада (≥2 ТФ) — прозрачно,
    # обучение различит одиночный див (ловушка) vs MTF-каскад/двойное-тройное дно (разворот).
    _dbt = sig.meta.get("div_by_tf") or {}
    for _tf, _v in _dbt.items():
        extra[f"ote_div_{_tf}"] = int(_v)
    extra["ote_div_cascade"] = int(sig.meta.get("div_cascade", 0))
    trade_id = None
    exchange_id = None
    if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
        try:
            res = await bot.trade_router.submit(rec, source="ote_nested", extra_features=extra)
            trade_id = res.trade_id
            exchange_id = getattr(res, "exchange_order_id", None)
            if not trade_id:
                drops = ",".join(g for g, _ in getattr(res, "hard_drops", [])) or "none"
                logger.info("[OTE VST] %s %s router dropped: %s", sig.symbol, sig.setup_id, drops)
                return
        except Exception as e:
            logger.exception("[OTE VST] %s router error: %s", sig.symbol, e)
            return
    else:
        try:
            trade_id = await bot.trade_simulator.register_trade_async(
                rec, bot.data_collector, extra_features=extra,
            )
        except Exception as e:
            logger.exception("[OTE VST] %s register error: %s", sig.symbol, e)
            return

    if trade_id:
        logger.info("[OTE VST] %s [%s T%d] %s → trade #%s str=%d entry=%.6f SL=%.6f TP=%.6f exch=%s",
                    sig.symbol, sig.setup_id, sig.tier, sig.direction, trade_id,
                    strength, sig.entry, sig.sl, sig.tp1, exchange_id or "none")
        await _notify(
            bot, "strategy_fire_ote", sig.symbol,
            setup_id=sig.setup_id,
            direction="LONG" if sig.direction == "long" else "SHORT",
            dir_emoji="🟢" if sig.direction == "long" else "🔴",
            entry=sig.entry, sl=sig.sl, tp=sig.tp1,
            strength=strength, trade_id=trade_id,
        )


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("OTE Observer Loop — standalone module")
    print(f"  Default interval: {OTE_OBSERVER_INTERVAL_SECONDS}s")
    print("  Источник: OTESignalGenerator (шкаф config/ote_setups.yaml)")
    print("  signal_type='ote_nested', register на FIRE")
    print("\n✅ Интеграция: asyncio.create_task(ote_observer_loop(bot))")
