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

logger = logging.getLogger(__name__)

OTE_OBSERVER_INTERVAL_SECONDS = 600   # 5 мин — выстрел нужен timely, зоны живут часами
OTE_OBSERVER_CONCURRENCY = 3          # детекторы тяжелее compute_flags → мягче к API
MIN_BARS = 50


async def ote_observer_loop(bot, interval_seconds: int = OTE_OBSERVER_INTERVAL_SECONDS):
    """Главный loop — раз в interval генерит OTE-сигналы для всех пар, регистрирует FIRE."""
    try:
        from core.smc.ote_signal_generator import OTESignalGenerator
    except ImportError as e:
        logger.error("[OTE observer] generator import failed: %s", e)
        return

    gen = OTESignalGenerator()
    logger.info("[OTE observer] started. %d enabled-сетапов. Interval=%ds",
                len(gen.setups), interval_seconds)

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
        elif sig.status == "FIRE":
            fired += 1
            logger.info("[OTE FIRE] %s [%s T%d] %s entry=%s SL=%s TP1=%s trg=%s conf=%d%s",
                        symbol, sig.setup_id, sig.tier, sig.direction,
                        sig.entry, sig.sl, sig.tp1, sig.trigger_type,
                        sig.conf_score, sig.confirmations)
            if bool(bot.config.get("ote.vst_trading.enabled", False)):
                try:    # DEV-226 Ph2 SHADOW: фаза импульса на входе (не блокирует)
                    sig.meta["phase_shadow"] = _elliott_phase_shadow(dfs, sig.direction, sig.type)
                except Exception:
                    pass
                await _register_ote_trade(bot, sig)

    # ARCH-128: проявление в шину — лучший сигнал (FIRE > ARMED, max conf) в pair_context.
    # Только observability для вотчлиста/ручной торговли — торговая логика выше не меняется.
    _publish_ote_ltf_state(bot, symbol, signals)
    return armed, fired


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


def _elliott_phase_shadow(dfs, direction, otype) -> dict:
    """DEV-226 Ph2 SHADOW: фаза импульса (n_down/n_up MTF на входе) + вердикт would_block.
    НЕ блокирует — пишет в features_json для замера эффекта на реальных сделках перед hard-гейтом.

    Правила (ELLIOTT v2, 11.06): cont → would_block если n_в_сторону_4h>=3 (конец импульса=ловушка);
    pull → would_block если n_в_сторону_4h<1 (контр-тренд без HTF-импульса). Reuse calculate_n_down/_up.
    """
    from core.indicators.indicators import (
        find_swing_highs, find_swing_lows, calculate_n_down, calculate_n_up,
    )

    def _nd_nu(df, period=5):
        if df is None or len(df) < period * 2 + 2:
            return 0, 0
        return (calculate_n_down(find_swing_highs(df["high"], period=period)),
                calculate_n_up(find_swing_lows(df["low"], period=period)))

    nd_4h, nu_4h = _nd_nu(dfs.get("4h"))
    nd_1h, nu_1h = _nd_nu(dfs.get("1h"))
    is_short = direction == "short"
    n_dir = nd_4h if is_short else nu_4h        # счётчик импульса В СТОРОНУ сделки (4h)
    if otype == "cont":
        would_block = n_dir >= 3                 # тренд в конце волны 5 = ловушка (avgR −0.19)
        reason = "cont_phase_end" if would_block else ""
    else:                                        # pull
        would_block = n_dir < 1                  # контр-тренд без HTF-импульса = против всего (−0.21)
        reason = "pull_no_htf_impulse" if would_block else ""
    return {
        "phase_nd_4h": nd_4h, "phase_nu_4h": nu_4h,
        "phase_nd_1h": nd_1h, "phase_nu_1h": nu_1h,
        "phase_n_dir_4h": n_dir,
        "phase_gate_would_block": bool(would_block),
        "phase_gate_reason": reason,
    }


async def _register_ote_trade(bot, sig):
    """Регистрирует OTE-сигнал (FIRE) через trade_router/simulator. signal_type='ote_nested'.

    Образец: _try_register_vst_trade (arch104). TP = tp_runner (финальная цель шкафа),
    tp1 (+1R, частичный) в extra. SL = sig.sl (за свип/импульс).
    """
    try:
        from core.signals.signal_models import (
            TradingRecommendation, SignalDirection, MarketContext,
        )
    except ImportError as e:
        logger.warning("[OTE VST] import failed: %s", e)
        return

    is_long = sig.direction == "long"
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
        take_profit=sig.tp_runner,
        sl_source=f"ote:{sig.htf}_impulse",
        tp_source=f"ote:{sig.type}_{sig.setup_id}",
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
        "trade_mode": "ote_nested",   # dedup: свой режим
    }
    _ps = sig.meta.get("phase_shadow")    # DEV-226 Ph2 SHADOW: фаза импульса → features_json
    if isinstance(_ps, dict):
        extra.update(_ps)

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
                    strength, sig.entry, sig.sl, sig.tp_runner, exchange_id or "none")


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("OTE Observer Loop — standalone module")
    print(f"  Default interval: {OTE_OBSERVER_INTERVAL_SECONDS}s")
    print("  Источник: OTESignalGenerator (шкаф config/ote_setups.yaml)")
    print("  signal_type='ote_nested', register на FIRE")
    print("\n✅ Интеграция: asyncio.create_task(ote_observer_loop(bot))")
