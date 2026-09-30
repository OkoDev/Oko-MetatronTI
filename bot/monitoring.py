"""
Фоновый мониторинг рынка: фильтры сигналов, фоновые проверки, broadcast.
Цикл сканирования вынесен в bot/loops/scan_loop.py.
Все функции принимают bot (TradingAlertBot) первым аргументом.
"""
import asyncio
import html
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from core.ui.message_builder import anomaly_message, wt_message
from core.mtf.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.indicators.trend_signals import check_trend_following_signal, trend_signal_message
from core.indicators.divergence_detector import divergence_message, mtf_divergence_message
from core.pivots.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from core.signals.signal_checkers import check_anomaly_signals, check_wt_signals as _check_wt_signals
from core.infra.entry_config import get_primary_entry_tf
from core.signals.signal_models import SignalData, SignalType, SignalDirection
from bot.keyboards import main_menu
from core.observability import decision_trace  # DEV-203: DecisionTrace gate visibility

logger = logging.getLogger(__name__)

# Ограничиваем параллельные вызовы analyze_symbol (тяжёлый: ML + 3 OHLCV-фетча)
# Размер задаётся через config: performance.analyze_semaphore_size (default 3)
_analyze_sem: Optional[asyncio.Semaphore] = None


def _get_analyze_sem(bot) -> asyncio.Semaphore:
    """Lazy-инициализация семафора analyze_symbol из конфига (создаётся однократно)."""
    global _analyze_sem
    if _analyze_sem is None:
        size = int(bot.config.get("performance.analyze_semaphore_size", 3))
        _analyze_sem = asyncio.Semaphore(size)
    return _analyze_sem


def _div_passes_filters(div_info: dict, df_15m, pivot_calc, sym: str,
                        proximity_pct: float = 4.0,
                        market_regime: str = "") -> tuple[bool, str]:
    """
    Фильтрация дивергенций: отсеивает шумы, оставляет только подтверждённые сигналы.

    Правило 0 — Режим рынка (Этап 8.4.5):
      Hidden дивергенции в RANGE/HIGH_VOL режиме отклоняются:
      в боковике нет тренда для продолжения, в HIGH_VOL тренды рвутся.

    Правило 1 — WT zone:
      Regular Bullish:  wt1_current < -40 (OS зона, уже встроено в детектор как < -60, дублируем)
      Regular Bearish:  wt1_current > +40 (OB зона, уже встроено в детектор как > +60)
      Hidden Bullish:   wt1_current < 0   (не в перекупленности, тренд вверх но откат)
      Hidden Bearish:   wt1_current > 0   (не в перепроданности, тренд вниз но отскок)

    Правило 2 — Pivot proximity:
      цена должна быть в пределах 2% от ближайшего уровня поддержки (для LONG)
      или сопротивления (для SHORT) из дневных пивотов.
      Если пивоты не в кеше — правило пропускается (не блокируем).

    Returns: (passed: bool, reason: str)
    """
    div_type = div_info.get("type", "")
    is_bullish = "BULLISH" in div_type
    is_bearish = "BEARISH" in div_type
    is_hidden = "HIDDEN" in div_type

    # ── Правило 0: Режим рынка — hidden div только в трендовом рынке ────────
    if is_hidden and market_regime in ("RANGE", "HIGH_VOL"):
        return False, f"Hidden div пропущена: режим {market_regime} (нет тренда для продолжения)"

    # ── Правило 1: WT zone ──────────────────────────────────────────────────
    # wt1_current уже есть в details (вычислен детектором), не нужен df_15m
    details = div_info.get("details") or {}
    wt1_current = details.get("ind_current")

    if wt1_current is not None:
        if is_hidden:
            # Скрытые дивергенции — продолжение тренда: WT не должен быть в противоположной зоне
            if is_bullish and wt1_current > 0:
                return False, f"Hidden Bull: wt1={wt1_current:.1f} выше 0 (OB территория)"
            if is_bearish and wt1_current < 0:
                return False, f"Hidden Bear: wt1={wt1_current:.1f} ниже 0 (OS территория)"
        else:
            # Регулярные дивергенции — разворот: нужна соответствующая зона
            if is_bullish and wt1_current > -40:
                return False, f"Regular Bull: wt1={wt1_current:.1f} не в OS зоне (<-40)"
            if is_bearish and wt1_current < 40:
                return False, f"Regular Bear: wt1={wt1_current:.1f} не в OB зоне (>+40)"

    # ── Правило 2: Pivot proximity (из кеша, без API-запроса) ───────────────
    if pivot_calc is not None:
        daily_pivots = pivot_calc.pivot_cache.get(f"{sym}_1D")
        if daily_pivots:
            try:
                current_price = float(df_15m["close"].iloc[-1]) if df_15m is not None else 0
                if current_price > 0:
                    nearest = pivot_calc.get_nearest_levels(current_price, daily_pivots, count=3)
                    levels = nearest["support"] if is_bullish else nearest["resistance"]
                    closest_dist = levels[0][2] if levels else 999.0  # dist в %
                    if closest_dist > proximity_pct:
                        return False, f"далеко от пивота: {closest_dist:.1f}% (порог {proximity_pct}%)"
            except Exception:
                pass  # ошибка — не блокируем

    return True, ""


def _make_mtf_alert_recommendation(sym: str, signal_type: str, strength: int,
                                    current_price: float, atr: float):
    """Адаптер MTF alert → объект для register_trade (fallback_rec)."""
    is_long = signal_type == "LONG"
    sl_mult = 2.0
    tp_rr = 2.5
    sl = current_price - atr * sl_mult if is_long else current_price + atr * sl_mult
    risk = abs(current_price - sl)
    tp = current_price + risk * tp_rr if is_long else current_price - risk * tp_rr
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="mtf_alert"))
    return SimpleNamespace(
        symbol=sym,
        entry_price=current_price,
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=sl,
        take_profit=tp,
        tp1_price=None,
        overall_strength=strength,
        confidence=0.70,
        timestamp=datetime.now(timezone.utc),  # DEV-49
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source="atr_15m",
        tp_source="rr_2.5",
        metadata={},
    )


def _make_pivot_recommendation(info: dict):
    """Адаптер dict от check_pivot_level_signal → объект для register_trade."""
    is_long = "LONG" in info.get("type", "")
    confidence_str = info.get("confidence", "HIGH")
    conf_float = 0.85 if confidence_str == "VERY_HIGH" else 0.70
    # Динамический strength из детектора (60-100), иначе fallback
    strength = info.get("strength", 80 if confidence_str == "VERY_HIGH" else 65)
    tp_levels = info.get("take_profits", [])
    tp1 = tp_levels[0]["price"] if tp_levels else None
    tp_main = tp_levels[1]["price"] if len(tp_levels) > 1 else tp1  # TP2 как основная цель
    level = info.get("level", "")

    # DEV-59: R:R cap — pivot_reversal обходит calculate_levels(), применяем cap вручную
    _entry = info.get("entry_price")
    _sl    = info.get("stop_loss")
    if _entry and _sl and tp_main:
        try:
            from core.infra.config_loader import config as _cfg59
            _max_rr = float(_cfg59.get("trading.sl_management.max_rr", 6.0))
        except Exception:
            _max_rr = 6.0
        _sl_dist = abs(float(_entry) - float(_sl))
        if _sl_dist > 0:
            _actual_rr = abs(float(tp_main) - float(_entry)) / _sl_dist
            if _actual_rr > _max_rr:
                tp_main = (float(_entry) + _sl_dist * _max_rr) if is_long else (float(_entry) - _sl_dist * _max_rr)
                if tp1 and abs(float(tp1) - float(_entry)) / _sl_dist > _max_rr:
                    tp1 = tp_main
    # DEV-188 (shadow): пробрасываем real_touch/volume_z из info → sig.data → features_json.
    _sig = SimpleNamespace(
        signal_type=SimpleNamespace(value="pivot_reversal"),
        data={
            "level": info.get("level_price"),
            "pivot_type": "support" if is_long else "resistance",
            "real_touch": info.get("real_touch", 0),
            "close_rejection": info.get("close_rejection", 0),
            "volume_z": info.get("volume_z", 0),
            "trend_changed": int(bool(info.get("trend_changed", False))),
        },
    )
    return SimpleNamespace(
        symbol=info.get("symbol", ""),
        entry_price=info.get("entry_price"),
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=info.get("stop_loss"),
        take_profit=tp_main,
        tp1_price=tp1,
        overall_strength=strength,
        confidence=conf_float,
        timestamp=datetime.now(timezone.utc),  # DEV-49
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source=info.get("sl_source", "atr_14"),
        tp_source=f"pivot_1W_{level}" if level else "pivot_1W",
        # ARCH-95 H1: detector_price = entry_price при детекции (для pivot path)
        metadata={"detector_price": info.get("entry_price")},
    )


# 🔴 30.09: BingX /contracts ответил таймаутом на старте → load_markets = [] → мониторинг не запускался,
# бот жил БЕЗ скана до ручного рестарта (13:05–13:16; заметили по хабу Куба — доска старела).
# Теперь повторы идут фоном (автостарт вызывается ДО Telegram polling — ждать нельзя), пока пары
# не загрузятся или мониторинг не остановят.
_PAIRS_RETRY_DELAYS = (15, 30, 60, 120)   # дальше — каждые 120 с


async def _begin_monitoring(bot, message, pairs) -> None:
    from bot.loops.scan_loop import monitor_market, _prefetch_pivots

    bot.monitored_pairs = pairs
    bot.is_monitoring = True
    bot.start_time = datetime.now()
    bot.monitor_task = asyncio.create_task(monitor_market(bot))

    asyncio.create_task(_prefetch_pivots(bot))

    user_id = message.from_user.id
    await message.answer(
        f"✅ Запущен мониторинг {len(bot.monitored_pairs)} пар.\n"
        f"📡 Отслеживаю: аномалии, WT, MTF, тренд-сигналы и дивергенции\n\n"
        f"💎 <b>Ваша подписка:</b> "
        f"{bot.subscription_manager.get_subscription_info(user_id)['tier']}",
        reply_markup=main_menu(),
    )


async def _retry_load_pairs(bot, message, min_vol) -> None:
    """Фоновые повторы загрузки пар; на успехе — обычный запуск мониторинга."""
    attempt = 1
    try:
        while getattr(bot, "monitoring_starting", False):
            delay = _PAIRS_RETRY_DELAYS[min(attempt - 1, len(_PAIRS_RETRY_DELAYS) - 1)]
            logger.warning("[start] пары не загружены (попытка %d) — повтор через %d с", attempt, delay)
            await asyncio.sleep(delay)
            if not getattr(bot, "monitoring_starting", False):
                break
            attempt += 1
            pairs = await bot.data_collector.load_markets(min_volume_usd=min_vol)
            if pairs:
                logger.info("[start] пары загружены с попытки %d: %d — запускаю мониторинг", attempt, len(pairs))
                bot.monitoring_starting = False
                await _begin_monitoring(bot, message, pairs)
                return
        logger.info("[start] повторы загрузки пар остановлены (попыток %d)", attempt)
    finally:
        bot.monitoring_starting = False


async def start_monitoring(bot, message):
    if bot.is_monitoring:
        await message.answer("⚠️ Мониторинг уже запущен.", reply_markup=main_menu())
        return
    if getattr(bot, "monitoring_starting", False):
        await message.answer("⏳ Мониторинг уже запускается — жду, пока биржа отдаст список пар.",
                             reply_markup=main_menu())
        return

    user_id = message.from_user.id
    if user_id not in bot.subscribers:
        bot.subscribers.add(user_id)
        bot.subscription_manager.add_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        logger.info("Пользователь %s добавлен в подписчики при старте мониторинга", user_id)

    min_vol = bot.config.get("signal_quality.min_volume_usd", 0)
    pairs = await bot.data_collector.load_markets(min_volume_usd=min_vol)
    if not pairs:
        bot.monitoring_starting = True
        bot.pairs_retry_task = asyncio.create_task(_retry_load_pairs(bot, message, min_vol))
        await message.answer("⚠️ Биржа не отдала список пар — повторяю в фоне, мониторинг запустится сам.",
                             reply_markup=main_menu())
        return

    await _begin_monitoring(bot, message, pairs)


async def stop_monitoring(bot, message):
    if not bot.is_monitoring:
        if getattr(bot, "monitoring_starting", False):
            bot.monitoring_starting = False           # фоновые повторы загрузки пар увидят и выйдут
            await message.answer("⏹ Повторы запуска мониторинга остановлены.", reply_markup=main_menu())
            return
        await message.answer("⚠️ Мониторинг не запущен.", reply_markup=main_menu())
        return

    bot.is_monitoring = False
    if bot.monitor_task:
        bot.monitor_task.cancel()
    await bot.data_collector.stop()
    await message.answer("⏹ Мониторинг остановлен.", reply_markup=main_menu())


# _prefetch_pivots перемещена в bot/loops/scan_loop.py


# scan_all_pairs и monitor_market перемещены в bot/loops/scan_loop.py


async def check_anomalies(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=30)
                if df_entry is None or df_entry.empty:
                    return
                signals = await check_anomaly_signals(sym, df_entry)
                for sig in signals:
                    info = sig.data or {}
                    bot.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                    bot.signal_counters["anomaly"] += 1
                    bot.signal_counters["total"] += 1
                    raw_text = anomaly_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "anomaly")
            except Exception:
                logger.exception("Ошибка check_anomalies для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_wt_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=150)
                if df_entry is None or df_entry.empty:
                    return
                df_1h = await bot.data_collector.get_ohlcv(sym, "1h", limit=60)
                signals = await _check_wt_signals(sym, df_entry, df_1h)
                for sig in signals:
                    info = sig.data or {}
                    logger.info("WT сигнал обнаружен для %s", sym)
                    raw_text = wt_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "wt_signal")
                    bot.signal_counters["wt_signal"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_wt_signals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])



def _make_signal_stub(sym: str, signal_type: SignalType, direction_str: str,
                      strength: float = 65, data: dict = None) -> SignalData:
    """Создаёт SignalData-заглушку для передачи как pre_signals в _broadcast_intelligence_alert.
    Нужно чтобы analyze_symbol получил подсказку о сигнале из фоновых функций
    (check_mtf_alerts, check_trend_signals, check_pivot_reversals и др.)
    и не отклонил их из-за min_signals=2.
    """
    d = direction_str.upper() if direction_str else ""
    if "LONG" in d or d == "LONG":
        direction = SignalDirection.LONG
    elif "SHORT" in d or d == "SHORT":
        direction = SignalDirection.SHORT
    else:
        direction = SignalDirection.NEUTRAL
    return SignalData(
        symbol=sym, signal_type=signal_type, direction=direction,
        strength=strength, confidence=0.7, timestamp=datetime.now(timezone.utc), data=data or {},  # DEV-49
    )


async def check_mtf_alerts(bot):
    # DEV-31: mtf_alert убран — 137 сделок WR=4.4%. Отключается через signals.mtf_alert_enabled=false
    if not bot.config.get("signals.mtf_alert_enabled", True):
        return
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                snapshot = await collect_mtf_data(sym, bot.data_collector)
                if not snapshot:
                    return
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    from core.mtf.mtf_checker import analyze_mtf_strength
                    strength = analyze_mtf_strength(snapshot, sig)
                    raw_text = mtf_alert_message(sym, snapshot, sig)
                    pre = [_make_signal_stub(sym, SignalType.MTF_ALERT, sig, strength=strength)]
                    # Создаём fallback_rec для регистрации сделки (если включено)
                    mtf_fallback = None
                    if bot.config.get("signals.mtf_alert_register", True):
                        try:
                            _etf = get_primary_entry_tf()
                            df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=30)
                            if df_entry is not None and len(df_entry) >= 14:
                                cur_price = float(df_entry["close"].iloc[-1])
                                atr = float(df_entry["high"].rolling(14).max().iloc[-1]
                                            - df_entry["low"].rolling(14).min().iloc[-1]) / 14
                                if cur_price > 0 and atr > 0:
                                    mtf_fallback = _make_mtf_alert_recommendation(
                                        sym, sig, strength, cur_price, atr)
                        except Exception:
                            logger.debug("[%s] MTF alert fallback_rec: не удалось вычислить", sym)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_alert",
                                                        fallback_rec=mtf_fallback, pre_signals=pre)
                    bot.signal_counters["mtf_alert"] += 1
                    bot.signal_counters["total"] += 1
                    # Куб: MTF Alert → EventBus (prio=4)
                    _eb = getattr(bot, "event_bus", None)
                    if _eb is not None:
                        await _eb.publish(sym, "mtf_alert", priority=4)
            except Exception:
                logger.exception("Ошибка check_mtf_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_cascade_divergences(bot, senior_tf: str, junior_tf: str):
    """Проверяет MTF-конфлюэнцию дивергенций (скрытая senior_tf + регулярная junior_tf) для всех пар."""
    if not bot.config.get("signals.cascade_div_enabled", True):
        return
    sem = asyncio.Semaphore(int(bot.config.get("performance.cascade_div_semaphore_size", 5)))

    async def _one(sym):
        async with sem:
            try:
                has_cascade, cascade_info = await bot.divergence_detector.detect_cascade_divergence(
                    sym, bot.data_collector, senior_tf, junior_tf
                )
                if has_cascade:
                    raw_text = mtf_divergence_message(sym, cascade_info)
                    pre = [_make_signal_stub(sym, SignalType.MTF_DIVERGENCE,
                                            cascade_info.get("type", ""),
                                            strength=cascade_info.get("strength", 65),
                                            data=cascade_info)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_divergence", pre_signals=pre)
                    bot.signal_counters["divergence"] += 1
                    bot.signal_counters["total"] += 1
                    # Куб: Cascade Divergence → EventBus (prio=3)
                    _eb = getattr(bot, "event_bus", None)
                    if _eb is not None:
                        await _eb.publish(sym, "divergence", priority=3)
                    logger.info("[%s] Cascade-дивергенция %s→%s: %s (сила %d)",
                                sym, senior_tf, junior_tf, cascade_info.get("type"), cascade_info.get("strength"))
            except Exception:
                logger.exception("Ошибка check_cascade_divergences %s→%s для %s", senior_tf, junior_tf, sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_trend_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                is_sig, info = await check_trend_following_signal(
                    sym, bot.data_collector, bot.divergence_detector, bot.pivot_calculator
                )
                if is_sig:
                    raw_text = trend_signal_message(sym, info)
                    pre = [_make_signal_stub(sym, SignalType.TREND_SIGNAL,
                                            info.get("type", ""),
                                            strength=info.get("strength", 65),
                                            data=info)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "trend_signal", pre_signals=pre)
                    bot.signal_counters["trend_signal"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Тренд-сигнал: %s", sym, info.get("pattern"))
                    # Куб: Trend Signal → EventBus (prio=4, avg_R=-0.50 — низкий приоритет)
                    _eb = getattr(bot, "event_bus", None)
                    if _eb is not None:
                        await _eb.publish(sym, "trend_signal", priority=4)
            except Exception:
                logger.exception("Ошибка check_trend_signals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_divergences(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            for tf in (get_primary_entry_tf(), "1h"):
                try:
                    has_div, div_info = await bot.divergence_detector.detect_divergence(
                        sym, bot.data_collector, timeframe=tf
                    )
                    if has_div:
                        raw_text = divergence_message(sym, div_info)
                        pre = [_make_signal_stub(sym, SignalType.DIVERGENCE,
                                                div_info.get("type", ""),
                                                strength=div_info.get("strength", 55),
                                                data=div_info)]
                        await _broadcast_intelligence_alert(bot, sym, raw_text, "divergence", pre_signals=pre)
                        bot.signal_counters["divergence"] += 1
                        bot.signal_counters["total"] += 1
                        logger.info("[%s] Дивергенция на %s: %s", sym, tf, div_info.get("type"))
                        break
                except Exception:
                    logger.exception("Ошибка check_divergences для %s %s", sym, tf)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_pivot_reversals(bot):
    # SIGNAL-CLEANUP (11.06.2026): pivot_reversal балласт −1272R (ELLIOTT+gravity = балласт равномерный).
    # config-флаг полного отключения генерации. Вернуть после WaveService/контекст-гейта (PIVOT-CONTEXT).
    if not bool(bot.config.get("signal_quality.pivot_reversal_enabled", True)):
        return
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                has_signal, info = await check_pivot_level_signal(
                    sym, bot.data_collector, bot.pivot_calculator
                )
                if has_signal:
                    raw_text = pivot_level_signal_message(sym, info)
                    pivot_rec = _make_pivot_recommendation(info)
                    stub = _make_signal_stub(sym, SignalType.PIVOT_REVERSAL,
                                            info.get("type", ""),
                                            strength=info.get("strength", 70),
                                            data=info)
                    pre = [stub]
                    # DEV-126: загружаем entry/HTF df для htf_wt1_1h/4h в features_json
                    # get_ohlcv возвращает raw OHLCV → нужен calculate_wt перед использованием
                    _pre_dfs: dict = {}
                    try:
                        from core.indicators.indicators import calculate_wt as _calc_wt_pivot
                        for _tf, _lim in [("15m", 50), ("1h", 30), ("4h", 30)]:
                            try:
                                _df = await bot.data_collector.get_ohlcv(sym, _tf, limit=_lim)
                                if _df is not None and len(_df) >= 10:
                                    _pre_dfs[_tf] = _calc_wt_pivot(_df)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Кешируем для меню "Все сигналы"
                    bot.recent_signals.setdefault(sym, [])
                    bot.recent_signals[sym] = [
                        s for s in bot.recent_signals[sym] if s.signal_type != SignalType.PIVOT_REVERSAL
                    ] + [stub]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "pivot_reversal",
                                                        fallback_rec=pivot_rec, pre_signals=pre,
                                                        pre_fetched_dfs=_pre_dfs or None)
                    bot.signal_counters["pivot_reversal"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Вход от уровня: %s R:R=%.1f", sym, info.get("level"), info.get("rr_ratio", 0))
                    # Куб: Pivot Reversal → EventBus (prio=2, avg_R=+0.50)
                    _eb = getattr(bot, "event_bus", None)
                    if _eb is not None:
                        await _eb.publish(sym, "pivot_reversal", priority=2)
            except Exception:
                logger.exception("Ошибка check_pivot_reversals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_future_pivot_alerts(bot):
    """
    DEV-11: Pre-alert при приближении цены к future pivot уровням.
    Вызывается каждые _bg_n циклов из monitor_market.
    """
    if not bot.config.get("future_pivots.enabled", True):
        return

    pre_alert_pct = float(bot.config.get("future_pivots.pre_alert_pct", 1.0))
    ttl_sec = int(bot.config.get("future_pivots.ttl_sec", 60))
    threshold_pct = float(bot.config.get("future_pivots.confluence_threshold_pct", 0.5))
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))
    pivot_calc = getattr(bot, "pivot_calculator", None)

    if pivot_calc is None:
        return

    from core.confluence.confluence_scanner import check_future_classic_confluence

    async def _one(sym):
        async with sem:
            try:
                # Загружаем future пивоты (с TTL-кешем)
                future_daily, future_weekly, future_monthly = await asyncio.gather(
                    pivot_calc.get_future_daily_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                    pivot_calc.get_future_weekly_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                    pivot_calc.get_future_monthly_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                )

                future_map = {
                    "future_1D": future_daily,
                    "future_1W": future_weekly,
                    "future_1M": future_monthly,
                }

                # Текущая цена из кеша entry TF
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=5)
                if df_entry is None or df_entry.empty:
                    return
                current_price = float(df_entry["close"].iloc[-1])
                if current_price <= 0:
                    return

                all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
                alerts = []

                # Проверяем близость цены к каждому future-уровню
                for tf_key, f_pivots in future_map.items():
                    if not f_pivots:
                        continue
                    for lvl in all_levels:
                        price = f_pivots.get(lvl)
                        if not price or price <= 0:
                            continue
                        dist_pct = abs((current_price - price) / price * 100)
                        if dist_pct <= pre_alert_pct:
                            alerts.append({
                                "tf": tf_key,
                                "level": lvl,
                                "price": price,
                                "dist_pct": dist_pct,
                                "current_price": current_price,
                            })

                # Конфлюэнция Future × Classic
                confluence_hits = []
                for tf_key, f_pivots in future_map.items():
                    if not f_pivots:
                        continue
                    # Берём classic кеш (1D, 1W, 1M)
                    classic_tf = tf_key.replace("future_", "")
                    classic_pivots = pivot_calc.pivot_cache.get(f"{sym}_{classic_tf}")
                    if classic_pivots:
                        hits = check_future_classic_confluence(f_pivots, classic_pivots, threshold_pct)
                        confluence_hits.extend(hits)

                if not alerts and not confluence_hits:
                    return

                # Формируем сообщение pre-alert
                lines = [f"⚠️ <b>FUTURE PIVOT ALERT · {sym}</b>"]
                if alerts:
                    lines.append(f"💰 Цена: <code>{current_price:.6f}</code>")
                    for a in sorted(alerts, key=lambda x: x["dist_pct"])[:3]:
                        lines.append(
                            f"  📍 {a['tf'].replace('future_','')} {a['level']}: "
                            f"<code>{a['price']:.6f}</code> "
                            f"({a['dist_pct']:.2f}% от цены)"
                        )
                if confluence_hits:
                    lines.append("🎯 <b>Future × Classic конфлюэнции:</b>")
                    for c in confluence_hits[:2]:
                        lines.append(
                            f"  {c['label']}: <code>{c['price']:.6f}</code> "
                            f"(+{c['strength_bonus']} strength)"
                        )
                lines.append(f"⏰ {datetime.now().strftime('%d.%m %H:%M')}")
                raw_text = "\n".join(lines)

                logger.info("[future_pivots] %s: %d уровней, %d конфлюэнций",
                            sym, len(alerts), len(confluence_hits))
                if bot.config.get("future_pivots.broadcast_tg", False):
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "future_pivot_alert")

            except Exception:
                logger.exception("Ошибка check_future_pivot_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


def _is_in_sl_cooldown(bot, symbol: str, signal_type: str = "") -> bool:
    """Возвращает True если по этой паре было SL-закрытие в течение sl_cooldown_hours.

    Per-signal_type cooldown (16.05.2026): если в config задана матрица
    `signal_quality.sl_cooldown_ignore_sources: {<signal_type>: [<exclude source signal_types>]}`,
    то для signal_type из матрицы SL от excluded источников НЕ считается за cooldown.

    Пример: `anomaly: [wt_sideways]` — anomaly игнорирует SL-серии от wt_sideways.

    Backward-compat: signal_type="" → старое поведение (любой SL блокирует).
    """
    hours = bot.config.get("signal_quality.sl_cooldown_hours", 4)
    if hours <= 0:
        return False

    # Per-signal_type матрица исключений
    excluded_sources: list = []
    if signal_type:
        ignore_map = bot.config.get("signal_quality.sl_cooldown_ignore_sources") or {}
        excluded_sources = list(ignore_map.get(signal_type, []) or [])

    try:
        db_path = bot.trade_simulator.db_path
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        # DEV-215: datetime() нормализует ISO 'T' и naive форматы для правильного сравнения.
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(db_path) as conn:
            if excluded_sources:
                placeholders = ",".join("?" * len(excluded_sources))
                query = (
                    "SELECT 1 FROM simulated_trades "
                    f"WHERE symbol=? AND status='SL' AND datetime(closed_at)>=datetime(?) "
                    f"AND signal_type NOT IN ({placeholders}) LIMIT 1"
                )
                row = conn.execute(query, (symbol, cutoff_str, *excluded_sources)).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM simulated_trades WHERE symbol=? AND status='SL' AND datetime(closed_at)>=datetime(?) LIMIT 1",
                    (symbol, cutoff_str),
                ).fetchone()
        if row:
            logger.debug("[%s] Cooldown после SL — сигнал %s пропущен (%dh, excl=%s)",
                         symbol, signal_type or "?", hours, excluded_sources)
            return True
    except Exception as e:
        logger.debug("sl_cooldown check error для %s: %s", symbol, e)
    return False


def _is_duplicate_signal(bot, symbol: str, signal_type: str, direction: str = "") -> bool:
    """Дедупликация по (пара, тип, направление).
    LONG WT по паре не блокирует SHORT WT по той же паре.
    WT сигнал по паре не блокирует pivot_reversal по той же паре."""
    minutes = bot.config.get("signal_quality.dedup_minutes", 30)
    if minutes <= 0:
        return False
    key = (symbol, signal_type, direction)
    last_ts = bot._last_signal.get(key)
    if last_ts and (datetime.now() - last_ts).total_seconds() < minutes * 60:
        logger.debug("[%s] Дубликат %s/%s — пропущен (%d мин)", symbol, signal_type, direction, minutes)
        return True
    bot._last_signal[key] = datetime.now()
    return False


async def _get_btc_regime(bot):
    """Кешированный режим BTC/USDT (TTL 5 мин)."""
    cache = getattr(bot, "_btc_regime_cache", None)
    now = datetime.now().timestamp()
    if cache and (now - cache["ts"]) < 300:
        return cache["regime"]
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "1h", limit=50)
        if ohlcv is not None and not ohlcv.empty:
            regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv.values.tolist())
            bot._btc_regime_cache = {"regime": regime, "ts": now}
            return regime
    except Exception as e:
        logger.debug("BTC режим не определён: %s", e)
    return None


async def _get_btc_4h_regime(bot) -> str | None:
    """Кешированный BTC/USDT 4h режим для ARCH-63 market gate (TTL 5 мин)."""
    cache = getattr(bot, "_btc_4h_regime_cache", None)
    now = datetime.now().timestamp()
    if cache and (now - cache["ts"]) < 300:
        return cache["regime"]
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "4h", limit=50)
        if ohlcv is not None and not ohlcv.empty:
            regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv.values.tolist())
            bot._btc_4h_regime_cache = {"regime": regime, "ts": now}
            logger.info("[BTC4h] режим=%s close=%.0f", regime, ohlcv['close'].iloc[-1])
            return regime
    except Exception as e:
        logger.debug("[BTC4h] режим не определён: %s", e)
    return None


_kelly_stats_cache: dict = {}  # {"ts": float, "text": str}


def _get_kelly_footer(bot) -> str:
    """Kelly-sizing строка для TG-алерта. Кеш 30 мин. Пустая строка если не готов."""
    import time, sqlite3
    global _kelly_stats_cache
    now = time.time()
    if _kelly_stats_cache and (now - _kelly_stats_cache.get("ts", 0)) < 1800:
        return _kelly_stats_cache["text"]
    try:
        r_pred = getattr(bot, "r_predictor", None)
        if r_pred is None or not r_pred.is_trained:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END),
                       AVG(CASE WHEN status IN ('TP','TSL') THEN R_multiple ELSE NULL END)
                FROM simulated_trades WHERE status != 'OPEN'
            """).fetchone()
        if not row or not row[0] or not row[2] or row[2] <= 0:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        total, wins, avg_r = int(row[0]), int(row[1] or 0), float(row[2])
        win_rate = wins / total
        from core.ml.r_predictor import RPredictor
        kelly_f = RPredictor.kelly_fraction(win_rate, avg_r)
        if kelly_f <= 0:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        text = (f"\n📐 <i>Kelly: {kelly_f*100:.1f}% депозита"
                f" (WR={win_rate*100:.0f}%, R̄={avg_r:.2f})</i>")
        _kelly_stats_cache = {"ts": now, "text": text}
        return text
    except Exception:
        return ""


async def _broadcast_intelligence_alert(bot, symbol: str, raw_text: str, signal_type: str,
                                        fallback_rec=None, pre_signals=None,
                                        pre_fetched_dfs=None):
    # Этап 8.4.4: извлекаем direction из первого pre_signal для точного dedup
    direction = ""
    if pre_signals:
        for _sig in pre_signals:
            _d = getattr(_sig, "direction", None)
            if _d:
                direction = getattr(_d, "value", str(_d))
                break

    # Фильтры качества сигналов (Этап 5.1 + 8.4.4)
    if hasattr(bot, "_last_signal") and _is_duplicate_signal(bot, symbol, signal_type, direction):
        # DEV-203: gate — dedup
        asyncio.create_task(decision_trace.record_drop(
            symbol=symbol, gate_name="dedup",
            drop_reason=f"duplicate {signal_type}/{direction} within dedup_minutes",
            signal_type=signal_type, direction=direction,
        ))
        return
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol, signal_type):
        # DEV-203: gate — sl_cooldown (per-signal_type с 16.05.2026 — учитывает sl_cooldown_ignore_sources)
        asyncio.create_task(decision_trace.record_drop(
            symbol=symbol, gate_name="sl_cooldown",
            drop_reason=f"sl_cooldown active for {symbol} ({signal_type})",
            signal_type=signal_type, direction=direction,
        ))
        return

    recommendation = None
    try:
        async with _get_analyze_sem(bot):
            recommendation = await bot.trading_intelligence.analyze_symbol(
                symbol, pre_collected_signals=pre_signals,
                pre_fetched_dfs=pre_fetched_dfs,
            )
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    # ARCH-28: FVG + Pivot Confluence — бонус к strength если цена в зоне конфлюэнции
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        try:
            from core.smc import find_fvg_pivot_confluences
            smc_ctx = getattr(getattr(recommendation, "market_context", None), "smc_context", None)
            if smc_ctx is not None and smc_ctx.fvg is not None:
                # Строим плоский dict пивотов из кеша: {"1W_S2": 0.004406, ...}
                flat_pivots: dict = {}
                _raw_cache = getattr(bot.pivot_calculator, "pivot_cache", {})
                sym_pivots = {
                    tf: _raw_cache[f"{symbol}_{tf}"]
                    for tf in ("1W", "1D", "1M")
                    if f"{symbol}_{tf}" in _raw_cache
                }
                for tf_key, levels in sym_pivots.items():
                    if isinstance(levels, dict):
                        for lk, lv in levels.items():
                            if isinstance(lv, (int, float)) and lv > 0:
                                flat_pivots[f"{tf_key}_{lk}"] = lv

                if flat_pivots:
                    cur_price = recommendation.market_context.current_price or 0
                    zones = find_fvg_pivot_confluences(smc_ctx.fvg, flat_pivots, cur_price)
                    if zones:
                        # Сохраняем все зоны в metadata для features_json
                        if recommendation.metadata is None:
                            recommendation.metadata = {}
                        recommendation.metadata["fvg_confluences"] = [z.to_dict() for z in zones]

                        # Бонус strength: только если цена ВНУТРИ FVG зоны
                        for z in zones:
                            fvg = z.fvg
                            if fvg.bottom <= cur_price <= fvg.top:
                                bonus = z.score
                                old_str = recommendation.overall_strength
                                recommendation.overall_strength = min(100, old_str + bonus)
                                logger.info(
                                    "[ARCH-28] %s: цена в зоне %s (score=%d) → strength %d→%d",
                                    symbol, z.label, bonus, old_str, recommendation.overall_strength,
                                )
                                break  # применяем только за первую (ближайшую) зону
        except Exception:
            logger.debug("[ARCH-28] %s: ошибка FVG confluence", symbol, exc_info=True)

    # Этап 5.2: BTC-корреляционный фильтр (ARCH-09п8)
    # shadow (default): только логирует + btc_counter_trend в features_json, НЕ блокирует
    # block: блокирует слабые контртрендовые сигналы (классическое поведение)
    btc_filter_mode = bot.config.get("signal_quality.btc_filter_mode", "shadow")
    btc_regime = await _get_btc_regime(bot) if bot.config.get("signal_quality.btc_filter_enabled", True) else None
    btc_warning = ""
    btc_counter_trend = False   # флаг для features_json (аналитика WR)
    if btc_regime == "HIGH_VOL":
        btc_warning = "\n⚠️ <i>BTC (1h): высокая волатильность — повышенный риск для любых позиций</i>"
    elif recommendation and btc_regime:
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        strength_val = getattr(recommendation, "overall_strength", 0)
        is_counter_trend = (
            (btc_regime == "TREND_UP" and direction_val == "SHORT") or
            (btc_regime == "TREND_DOWN" and direction_val == "LONG")
        )
        ct_thr = int(bot.config.get("signal_quality.counter_trend_strength_threshold", 70))
        if is_counter_trend:
            btc_counter_trend = True
            if btc_filter_mode == "block" and strength_val < ct_thr:
                logger.info("[%s] BTC %s vs %s, сила %d < %d — пропущен (block mode)",
                            symbol, btc_regime, direction_val, strength_val, ct_thr)
                # DEV-203: gate — btc_counter_trend
                asyncio.create_task(decision_trace.record_drop(
                    symbol=symbol, gate_name="btc_counter_trend",
                    drop_reason=f"btc={btc_regime} vs dir={direction_val} strength={strength_val}<{ct_thr}",
                    signal_type=signal_type, direction=direction_val, strength=strength_val,
                ))
                return
            regime_ru = "восходящем" if btc_regime == "TREND_UP" else "нисходящем"
            dir_ru = "шорт" if direction_val == "SHORT" else "лонг"
            btc_warning = f"\n⚠️ <i>BTC (1h) в {regime_ru} тренде — {dir_ru} против рынка ({strength_val}/100)</i>"
            logger.info("[%s] BTC %s vs %s, сила %d, режим=%s — btc_counter_trend=True",
                        symbol, btc_regime, direction_val, strength_val, btc_filter_mode)

    # Этап 5.3: BTC 4h Market Gate (ARCH-78) — ATR Supertrend провайдер
    if recommendation is not None:
        _btc_gate_cfg = (bot.config.get("trading", {}) or {}).get("btc_market_gate", {})
        if _btc_gate_cfg.get("enabled", False):
            # ARCH-78: BTCRegimeProvider (ATR Supertrend 43/1.25) — точнее MarketRegimeClassifier
            _btc_prov78 = getattr(bot, "btc_regime_provider", None)
            if _btc_prov78 is not None:
                _btc_mode78 = _btc_prov78.get_btc_mode()  # BULL / BEAR / NEUTRAL
                _btc_4h = {"BULL": "TREND_UP", "BEAR": "TREND_DOWN"}.get(_btc_mode78)
            else:
                _btc_4h = await _get_btc_4h_regime(bot)  # fallback: MarketRegimeClassifier
            if _btc_4h is not None:
                _dir4h = getattr(recommendation.direction, "value",
                                 str(recommendation.direction))
                _shadow4h = _btc_gate_cfg.get("shadow_mode", True)
                _should_block4h = False
                _reason4h = None

                # Правило 1: BTC BEAR → блок LONG
                # Исключение: pivot_reversal с BULLISH weekly bias (разворот у уровня)
                if _btc_4h == "TREND_DOWN" and _dir4h == "LONG":
                    _has_pivot_rev1 = any(
                        getattr(_s, "signal_type", None) and _s.signal_type.value == "pivot_reversal"
                        for _s in (recommendation.supporting_signals or [])
                    )
                    _wb1 = (recommendation.metadata or {}).get("weekly_bias", "UNKNOWN")
                    _reversal_exc1 = (
                        _btc_gate_cfg.get("reversal_exception", True)
                        and _has_pivot_rev1 and _wb1 == "BULLISH"
                    )
                    if not _reversal_exc1:
                        _should_block4h = True
                        _reason4h = "BTC BEAR блокирует LONG"

                # Правило 2: BTC BULL → умный блок SHORT
                # Пропускаем: pivot_reversal у реального уровня (разворот даёт макс. прибыль)
                # Пропускаем: strength >= counter_trend_min_strength (сильный сигнал)
                elif (_btc_4h == "TREND_UP" and _dir4h == "SHORT"
                      and _btc_gate_cfg.get("block_short_in_uptrend", False)):
                    _ct_min = int(_btc_gate_cfg.get("counter_trend_min_strength", 75))
                    _str_val = getattr(recommendation, "overall_strength", 0)
                    _reversal_types2 = {"pivot_reversal", "divergence"}
                    _has_pivot_rev2 = any(
                        getattr(_s, "signal_type", None) and _s.signal_type.value in _reversal_types2
                        for _s in (recommendation.supporting_signals or [])
                    )
                    _reversal_exc2 = _btc_gate_cfg.get("reversal_exception", True) and _has_pivot_rev2
                    if not _reversal_exc2 and _str_val < _ct_min:
                        _should_block4h = True
                        _reason4h = (f"BTC BULL блокирует SHORT str={_str_val}<{_ct_min}"
                                     f" (pivot_reversal/divergence пропускается)")

                if _should_block4h:
                    if _shadow4h:
                        logger.info("[%s] ARCH-78 SHADOW WOULD_BLOCK %s btc=%s reason=%s",
                                    symbol, _dir4h, _btc_4h, _reason4h)
                    else:
                        logger.info("[%s] ARCH-78 btc_market_gate: %s→WATCH (%s)",
                                    symbol, recommendation.action, _reason4h)
                        recommendation.action = "WATCH"


    # Этап 5.3d: DEV-186 — wt_signal SHORT в TREND_UP / HIGH_VOL: regime mismatch
    # Данные RE-AUDIT 25.04: SHORT TREND_UP=22 сделки avgR=-1.12, SHORT HIGH_VOL=12 avgR=-0.77.
    # Открываем разворот вверх в восходящем тренде / в хаосе — закономерный убыток.
    # FIX 27.04: recommendation.regime ещё не установлен на этом этапе (заполняется в register_trade).
    # Берём regime из pair_context (актуальный classifier, тот же что попадёт в БД).
    if recommendation is not None and bot.config.get("signal_quality.dev186_wt_signal_regime_gate", True):
        try:
            _has_wt_signal_186 = any(
                getattr(_s, "signal_type", None) and _s.signal_type.value == "wt_signal"
                for _s in (recommendation.supporting_signals or [])
            )
            _dir186 = getattr(recommendation.direction, "value", "NEUTRAL")
            # Источники regime в порядке приоритета: pair_context → recommendation → market_context
            _reg186 = ""
            try:
                _pc186 = getattr(bot, "pair_context", None)
                if _pc186 is not None:
                    _ps186 = _pc186.get(symbol)
                    if _ps186 is not None:
                        _reg186 = getattr(_ps186, "regime", "") or ""
            except Exception:
                pass
            if not _reg186:
                _reg186 = getattr(recommendation, "regime", "") or ""
            if not _reg186:
                _mc186 = getattr(recommendation, "market_context", None)
                if _mc186 is not None:
                    _reg186 = getattr(_mc186, "regime", "") or ""
            _shadow186 = bool(bot.config.get("signal_quality.dev186_shadow", False))
            if _has_wt_signal_186 and _dir186 == "SHORT" and _reg186 in ("TREND_UP", "HIGH_VOL"):
                if _shadow186:
                    logger.info("[%s] DEV-186 SHADOW WOULD_BLOCK wt_signal SHORT regime=%s", symbol, _reg186)
                else:
                    logger.info("[%s] DEV-186 wt_signal SHORT в %s → WATCH", symbol, _reg186)
                    recommendation.action = "WATCH"
        except Exception as _e186:
            logger.debug("[DEV-186] gate error %s: %s", symbol, _e186)

    # Этап 5.3c: ARCH-88 — PAIR-COOLDOWN gate (Per-pair Loss Memory)
    # Защита от сценария API3: 8 SL подряд без автоматической остановки.
    # Shadow: 48ч только лог. Prod: блок регистрации при serie sl_streak >= limit.
    if recommendation is not None:
        try:
            _pc_ctx88 = getattr(bot, "pair_context", None)
            _pair_state88 = _pc_ctx88.get(symbol) if _pc_ctx88 is not None else None
            _cooldown_cfg88 = bot.config.get("signal_quality", {}) or {}
            _streak_limit88 = int(_cooldown_cfg88.get("pair_cooldown_sl_streak", 5))
            _cooldown_shadow88 = bool(_cooldown_cfg88.get("pair_cooldown_shadow", True))
            if (_pair_state88 is not None
                    and _pair_state88.sl_streak_count >= _streak_limit88):
                if _cooldown_shadow88:
                    logger.info(
                        "[PAIR-COOLDOWN SHADOW WOULD_BLOCK] %s: streak=%d >= %d",
                        symbol, _pair_state88.sl_streak_count, _streak_limit88,
                    )
                else:
                    logger.warning(
                        "[PAIR-COOLDOWN] %s: %d SL подряд, блок регистрации",
                        symbol, _pair_state88.sl_streak_count,
                    )
                    return
        except Exception as _e88:
            logger.debug("[ARCH-88] PAIR-COOLDOWN gate error %s: %s", symbol, _e88)

    # Этап 5.4: DEV-128 — weekly_bias gate для pivot_reversal RANGE
    # Данные: 62% pivot_reversal RANGE = weekly_bias=NONE, EV=-0.5—0.76R → блок
    # Исключение: BULLISH/BEARISH (aligned с направлением) — пропускаем
    if recommendation is not None:
        try:
            _wb128_cfg = (bot.config.get("signal_quality", {}) or {}).get("weekly_bias_gate", {})
            _wb128_enabled = _wb128_cfg.get("enabled", True)
            _wb128_shadow  = _wb128_cfg.get("shadow_mode", False)
            _wb128_sig = getattr(recommendation, "signal_type", "") or ""
            _wb128_reg = getattr(recommendation, "regime", "") or ""
            if _wb128_sig == "pivot_reversal" and _wb128_reg == "RANGE":
                _wb128_meta = recommendation.metadata or {}
                _wb128_bias = _wb128_meta.get("weekly_bias", "UNKNOWN")
                _wb128_dir  = getattr(recommendation.direction, "value", "NEUTRAL")
                # Блокируем NONE/UNKNOWN — нет контекста, EV отрицательный
                # Исключение: BULLISH+LONG или BEARISH+SHORT — aligned
                _wb128_aligned = (
                    (_wb128_bias == "BULLISH" and _wb128_dir == "LONG") or
                    (_wb128_bias == "BEARISH" and _wb128_dir == "SHORT")
                )
                _wb128_block = not _wb128_aligned  # блок если не aligned
                if _wb128_block:
                    if _wb128_shadow or not _wb128_enabled:
                        logger.info(
                            "[%s] DEV-128 SHADOW pivot_reversal RANGE weekly_bias=%s dir=%s → WOULD_BLOCK",
                            symbol, _wb128_bias, _wb128_dir,
                        )
                    else:
                        logger.info(
                            "[%s] DEV-128 pivot_reversal RANGE weekly_bias=%s dir=%s → WATCH",
                            symbol, _wb128_bias, _wb128_dir,
                        )
                        recommendation.action = "WATCH"
        except Exception as _e128:
            logger.debug("[DEV-128] %s: gate error — %s", symbol, _e128)

    # DEV-128ext / DEV-133: блок токсичных direction×regime комбо (мониторинг-уровень)
    # Соответствует config.yaml signal_regime_block.*.blocked_combos (DEV-133)
    # pivot_reversal: LONG TREND_DOWN (WR=0%), SHORT TREND_UP (WR=19%)
    # confluence:     LONG TREND_DOWN (WR=3%), SHORT TREND_UP (WR=0%), SHORT HIGH_VOL (WR=0%)
    #                 LONG HIGH_VOL (WR=0%), LONG TREND_UP (WR=18%)
    if recommendation is not None:
        try:
            _ct_sig  = getattr(recommendation, "signal_type", "") or ""
            _ct_reg  = getattr(recommendation, "regime", "") or ""
            _ct_dir  = getattr(recommendation.direction, "value", "NEUTRAL")
            _ct_block = False
            _ct_reason = ""
            # DEV-149: pivot_reversal LONG TREND_DOWN разблокирован — это классический
            # reversal setup на OS, даёт +0.33R в общем по pivot_reversal.
            # confluence HIGH_VOL разблокирован — теперь HIGH_VOL не в blocked_regimes.
            # REVERSAL-BOOST (DEV-149) обходит эти фильтры для реверс-сетапов.
            _has_rev_boost = bool((recommendation.metadata or {}).get("reversal_boost"))
            if not _has_rev_boost and _ct_sig == "confluence":
                if _ct_dir == "LONG" and _ct_reg == "TREND_DOWN":
                    _ct_block = True
                    _ct_reason = "confluence LONG TREND_DOWN (WR=3%, avg=-0.17R)"
                elif _ct_dir == "SHORT" and _ct_reg == "TREND_UP":
                    _ct_block = True
                    _ct_reason = "confluence SHORT TREND_UP (WR≈0%)"
                elif _ct_dir == "LONG" and _ct_reg == "TREND_UP":
                    _ct_block = True
                    _ct_reason = "confluence LONG TREND_UP (WR=18%, avg=-0.362R)"
            if not _has_rev_boost and _ct_sig == "pivot_reversal":
                if _ct_dir == "SHORT" and _ct_reg == "TREND_UP":
                    _ct_block = True
                    _ct_reason = "pivot_reversal SHORT TREND_UP (WR=19%)"
            if _ct_block:
                logger.info("[%s] DEV-128ext %s → WATCH", symbol, _ct_reason)
                recommendation.action = "WATCH"
        except Exception as _ect:
            logger.debug("[DEV-128ext] %s: %s", symbol, _ect)

    # Этап 6: TP по иерархии пивотов (ARCH-09п5, DEV-75)
    # Порядок: 1D → 1W → confluence(1W+1D) → confluence(1M+1W) → 1M → ATR fallback
    distance_to_pivot_pct: float = 0.0
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        entry_price = recommendation.entry_price or 0
        if direction_val in ("LONG", "SHORT") and entry_price > 0:
            strategy_type = (recommendation.metadata or {}).get("strategy_type", "")
            _rec_regime = getattr(recommendation, "regime", None) or ""
            if _rec_regime == "RANGE":
                # DEV-122: для RANGE берём ближайший пивот (avg TP 5-8R → hit rate 28-41%)
                pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r_range", 1.2)
            elif strategy_type == "reversal":
                pivot_min_r = bot.config.get("trading.sl_tp.tp_reversal_min_r", 2.0)
            elif strategy_type == "trend_following":
                pivot_min_r = bot.config.get("trading.sl_tp.tp_trend_min_r", 1.5)
            else:
                pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0)
            # ARCH-58: извлекаем impulse_high/low из metadata (OTE detector их пишет)
            _meta = recommendation.metadata or {}
            _imp_high = _meta.get("impulse_high")
            _imp_low  = _meta.get("impulse_low")
            pivot_result = bot.pivot_calculator.get_tp_by_hierarchy(
                direction=direction_val,
                entry_price=entry_price,
                symbol=symbol,
                stop_loss=recommendation.stop_loss,
                min_r=pivot_min_r,
                impulse_high=_imp_high,
                impulse_low=_imp_low,
            )
            if pivot_result:
                pivot_tp, pivot_src = pivot_result
                # ARCH-122 ч.1b (ExitManager): НЕ перетираем TPSelector магнит pivot'ом.
                from core.trading.exit_manager import magnet_tp_locked
                if magnet_tp_locked(recommendation, bot.config):
                    _cur_src = str(getattr(recommendation, "tp_source", "") or "")
                    distance_to_pivot_pct = abs(float(recommendation.take_profit) - entry_price) / entry_price * 100 if recommendation.take_profit else 0.0
                    logger.info("[%s] ExitManager: магнит сохранён (src=%s), pivot override пропущен", symbol, _cur_src)
                else:
                    recommendation.take_profit = pivot_tp
                    recommendation.tp_source = pivot_src
                    distance_to_pivot_pct = abs(pivot_tp - entry_price) / entry_price * 100
                    logger.debug("[%s] Pivot TP (hierarchy): %.6f (%.2f%%, %s, src=%s)", symbol, pivot_tp, distance_to_pivot_pct, direction_val, pivot_src)
            elif bot.config.get("trading.sl_tp.require_pivot_tp", False):
                # Вариант C (п.6): если pivot TP не найден и require_pivot_tp=true → пропуск регистрации
                logger.info("[%s] Пропуск регистрации: require_pivot_tp=true, pivot не найден в 2-20R", symbol)
                if recommendation is not None:
                    recommendation = None  # блокирует is_actionable и should_register

    min_strength = bot.config.get("signal_quality.min_strength", 50)
    min_strength_register = bot.config.get("signal_quality.min_strength_register", 50)

    # DEV-155: дифференцированный порог по режиму/направлению
    # HIGH_VOL=85, LONG_RANGE=75 (avgR по этим комбинациям хронически <0)
    _sym_regime: Optional[str] = None
    try:
        _pair_ctx = getattr(bot, "pair_context", None)
        if _pair_ctx is not None and recommendation is not None:
            _sym_regime = _pair_ctx.get(symbol).regime
    except Exception:
        pass
    if _sym_regime and recommendation is not None:
        _rec_dir155 = getattr(getattr(recommendation, "direction", None), "value", "NEUTRAL")
        _dir_regime_key = f"{_rec_dir155}_{_sym_regime}"
        _by_dir_regime = bot.config.get("signal_quality.min_strength_by_direction_regime") or {}
        _by_regime = bot.config.get("signal_quality.min_strength_by_regime") or {}
        _eff_min_str = int(_by_dir_regime.get(_dir_regime_key,
                            _by_regime.get(_sym_regime, min_strength)))
        if _eff_min_str != min_strength:
            logger.debug("[DEV-155] %s %s/%s eff_min_strength=%d (was %d)",
                         symbol, _rec_dir155, _sym_regime, _eff_min_str, min_strength)
        min_strength = _eff_min_str

    # DEV-156: Circuit Breaker — поднимаем min_strength если WR < 15% за 50 сделок
    try:
        from core.trading.circuit_breaker import CircuitBreaker
        _cb = CircuitBreaker()
        if _cb.strength_floor_bonus:
            min_strength += _cb.strength_floor_bonus
            logger.debug("[DEV-156] CircuitBreaker активен: +%d → min_strength=%d (%s)",
                         _cb.strength_floor_bonus, min_strength, symbol)
    except Exception as _cb_e:
        logger.debug("[DEV-156] CircuitBreaker error: %s", _cb_e)

    _dir_ok = (
        recommendation is not None
        and getattr(recommendation, "action", "WATCH") in ("BUY", "SELL")
        and getattr(recommendation, "direction", None) is not None
        and recommendation.direction.value != "NEUTRAL"
    )
    is_actionable = _dir_ok and recommendation.overall_strength >= min_strength
    should_register = _dir_ok and recommendation.overall_strength >= min_strength_register

    # DEV-203: gate — min_strength / min_strength_register
    if recommendation is not None and _dir_ok:
        _rec_str_val = int(getattr(recommendation, "overall_strength", 0))
        _rec_dir_val = getattr(getattr(recommendation, "direction", None), "value", None)
        _rec_sig_val = getattr(recommendation, "signal_type", signal_type)
        if not should_register:
            asyncio.create_task(decision_trace.record_drop(
                symbol=symbol, gate_name="min_strength_register",
                drop_reason=f"strength={_rec_str_val} < min_register={min_strength_register}",
                signal_type=str(_rec_sig_val) if _rec_sig_val else signal_type,
                direction=_rec_dir_val, strength=_rec_str_val,
            ))
        elif not is_actionable:
            asyncio.create_task(decision_trace.record_drop(
                symbol=symbol, gate_name="min_strength",
                drop_reason=f"strength={_rec_str_val} < min={min_strength} (registered only)",
                signal_type=str(_rec_sig_val) if _rec_sig_val else signal_type,
                direction=_rec_dir_val, strength=_rec_str_val,
            ))

    # WATCH+NEUTRAL — нет торгового решения, не спамим
    if (recommendation is not None
            and getattr(recommendation, "action", "WATCH") in ("WATCH", "HOLD")
            and getattr(recommendation.direction, "value", "NEUTRAL") == "NEUTRAL"):
        logger.info("[%s] Пропущен WATCH+NEUTRAL — нет торгового решения", symbol)
        # DEV-203: gate — watch_neutral
        asyncio.create_task(decision_trace.record_drop(
            symbol=symbol, gate_name="watch_neutral",
            drop_reason=f"action={getattr(recommendation, 'action', 'WATCH')} direction=NEUTRAL",
            signal_type=signal_type, direction="NEUTRAL",
            strength=int(getattr(recommendation, "overall_strength", 0)),
        ))
        return

    # ── DEV-22: WATCH LIST ─────────────────────────────────────────────────────
    # Если action=WATCH и есть чёткое направление — добавить в WL или эскалировать.
    _wl = getattr(bot, "signal_watch_list", None)
    if _wl is not None and recommendation is not None:
        _rec_action = getattr(recommendation, "action", "WATCH")
        _rec_dir = (getattr(recommendation.direction, "value", "NEUTRAL")
                    if recommendation.direction else "NEUTRAL")
        _rec_str = recommendation.overall_strength

        # MTF direction из metadata
        _mtf_ctx = (recommendation.metadata or {}).get("mtf_context", {})
        _mtf_dir = _mtf_ctx.get("direction_bias", "") if isinstance(_mtf_ctx, dict) else ""
        _mtf_aligned = _mtf_ctx.get("aligned_pct", 0) if isinstance(_mtf_ctx, dict) else 0

        # Кол-во дивергенций в supporting_signals
        _div_count = sum(
            1 for s in (recommendation.supporting_signals or [])
            if "divergence" in str(getattr(s, "signal_type", "")).lower()
        )

        if _rec_action == "WATCH" and _rec_dir in ("LONG", "SHORT"):
            # Pivot level для отслеживания пробоя: используем stop_loss (уровень под/над которым идея ломается)
            _pivot_key = getattr(recommendation, "sl_source", "") or ""
            _pivot_level = recommendation.stop_loss or 0.0
            _wl_reason = f"MTF {_mtf_dir} {_mtf_aligned}%" if _mtf_dir else "WATCH"

            if _wl.has(symbol):
                # Уже в WL → проверяем эскалацию
                if _wl.check_escalation(symbol, _rec_str, _rec_action, _mtf_dir, _div_count):
                    # Эскалируем: форсируем BUY/SELL, пересчитываем флаги
                    recommendation.action = "BUY" if _rec_dir == "LONG" else "SELL"
                    _dir_ok = True
                    is_actionable = _rec_str >= min_strength
                    should_register = _rec_str >= min_strength_register
                    raw_text = raw_text.rstrip() + "\n🔔 <i>Эскалация из WATCH — условия улучшились</i>"
                    _wl.add(symbol, _rec_dir, _rec_str, "escalated", _pivot_key, _pivot_level, _div_count)
                    logger.info("[%s] WL: WATCH → %s (score=%.0f)", symbol, recommendation.action, _rec_str)
                # иначе WATCH остаётся WATCH — обновляем div_count если вырос
                elif _div_count > (_wl.get(symbol).div_count if _wl.get(symbol) else 0):
                    _wl.add(symbol, _rec_dir, _rec_str, _wl_reason, _pivot_key, _pivot_level, _div_count)
            else:
                # Добавляем новую запись в WL
                _wl.add(symbol, _rec_dir, _rec_str, _wl_reason, _pivot_key, _pivot_level, _div_count)
    # ── /DEV-22 ────────────────────────────────────────────────────────────────

    # Регистрируем сделку ДО отправки TG — чтобы footer "зарегистрирована" соответствовал реальности
    trade_registered = False
    trade_id = None
    if should_register:
        try:
            extra: dict = {}
            if distance_to_pivot_pct:
                extra["distance_to_pivot_pct"] = distance_to_pivot_pct
            if btc_counter_trend:
                extra["btc_counter_trend"] = True   # shadow: для аналитики WR с/без BTC-фильтра
            try:
                _mtf84x = (recommendation.metadata or {}).get("mtf_context", {})
                _bias84x = _mtf84x.get("direction_bias", "") if isinstance(_mtf84x, dict) else ""
                _bstr84x = float(_mtf84x.get("bias_strength", 0.0)) if isinstance(_mtf84x, dict) else 0.0
                if _bias84x and _bstr84x > 0:
                    extra["mtf_bias"] = _bias84x
                    extra["mtf_bias_strength"] = round(_bstr84x, 3)
            except Exception:
                pass
            # ARCH-78: режим BTC 4h от BTCRegimeProvider (ATR Supertrend) — для ML и аналитики
            _btc_prov_fx = getattr(bot, "btc_regime_provider", None)
            if _btc_prov_fx is not None:
                extra["btc_4h_regime"] = _btc_prov_fx.get_btc_mode()
            # Извлекаем факторы confluence для аналитики WR по каждому фактору
            conf_factors = []
            for sig in (recommendation.supporting_signals or []):
                if getattr(sig, "signal_type", None) and sig.signal_type.value == "confluence":
                    conf_factors = (sig.data or {}).get("factors", [])
                    break
            if conf_factors:
                extra["confluence_factors"] = conf_factors
                # СКЛЕЙКА→ФЛАГИ (12.07, Егор «всё в прозрачную структуру для обучения»): список
                # факторов невидим плоскому майнингу → дискретные булевы conf_f_<фактор>. Не гейт.
                for _cf in conf_factors:
                    extra["conf_f_" + str(_cf).lower()] = 1
            # ARCH-28: FVG+Pivot confluence зоны в features_json
            _fvg_zones = (recommendation.metadata or {}).get("fvg_confluences")
            if _fvg_zones:
                extra["fvg_confluences"] = _fvg_zones
            # DEV-56/58: Weekly Bias shadow data → features_json (для анализа WR до включения gate)
            _meta = recommendation.metadata or {}
            if "weekly_bias" in _meta:
                extra["weekly_bias"] = _meta["weekly_bias"]
                extra["weekly_context_score"] = _meta.get("weekly_context_score", 0)
                extra["weekly_gate_would_block"] = _meta.get("weekly_gate_would_block", False)
                extra["weekly_bias_blocked"] = _meta.get("weekly_gate_would_block", False)  # TR-007 алиас
            # ML-CONTEXT: WT-фичи из supporting signals (CONFLUENCE signal.data)
            for _sig in (recommendation.supporting_signals or []):
                if getattr(_sig, "signal_type", None) and _sig.signal_type.value == "confluence":
                    _sd = _sig.data or {}
                    if "wt_cross_quality" in _sd:
                        extra["wt_cross_quality"] = _sd["wt_cross_quality"]  # "in_zone"/"out_zone"
                    if "div_type" in _sd:
                        extra["wt_div_type"] = _sd["div_type"]  # "regular_bull"/"hidden_bull"/etc.
                    for _k in ("mtf_4h_trend", "mtf_4h_wt", "mtf_4h_zone"):
                        if _k in _sd:
                            extra[_k] = _sd[_k]
                    break
            # ML-CONTEXT: дивергенции из supporting signals
            extra["div_count"] = _div_count  # уже посчитан выше (DIVERGENCE сигналы)
            extra["hidden_div"] = int(any(
                "hidden" in str((_s.data or {}).get("div_type", "")).lower()
                for _s in (recommendation.supporting_signals or [])
            ))
            # ML-CONTEXT: WT значения на entry TF и HTF из pre_fetched_dfs
            if pre_fetched_dfs:
                _entry_tf_key = getattr(recommendation, "timeframe", None) or "15m"
                for _tf_key, _feat_key_wt1, _feat_key_wt2 in [
                    (_entry_tf_key, "wt1_value",   "wt2_value"),
                    ("1h",          "htf_wt1_1h",  "htf_wt2_1h"),
                    ("4h",          "htf_wt1_4h",  "htf_wt2_4h"),
                ]:
                    _df_tf = pre_fetched_dfs.get(_tf_key)
                    if _df_tf is not None and "wt1" in _df_tf.columns and len(_df_tf) > 0:
                        try:
                            _w1 = round(float(_df_tf["wt1"].iloc[-1]), 1)
                            _w2 = round(float(_df_tf["wt2"].iloc[-1]), 1)
                            extra[_feat_key_wt1] = _w1
                            extra[_feat_key_wt2] = _w2
                            if _feat_key_wt1 == "wt1_value":  # только для entry TF
                                extra["wt_zone"] = "OS" if _w1 <= -60 else "OB" if _w1 >= 60 else "N"
                        except Exception:
                            pass
            # ARCH-128 AUGMENT (condition-mining): adx/rsi/n_up/n_down/elliott(фрактал)/fib per 15m/1h/4h.
            # Единый калькулятор (core.indicators.augment_snap) — ТОТ ЖЕ в backtest (инвариант ARCH-118).
            # Считается на регистрации (раз на сделку) → детект Эллиотта не грузит горячий scan-loop.
            if pre_fetched_dfs:
                try:
                    from core.indicators.augment_snap import compute_augment_snap
                    _aug = {}
                    for _atf in ("5m", "15m", "1h", "4h"):
                        _adf = pre_fetched_dfs.get(_atf)
                        if _adf is not None and len(_adf) >= 30:
                            _a = compute_augment_snap(_adf)
                            if _a:
                                _aug[_atf] = _a
                    if _aug:
                        extra["augment"] = _aug
                except Exception:
                    pass
            # NEAR_PIVOT shadow flag — записываем для всех сигналов независимо от confluence.enabled
            _pivot_calc_np = getattr(bot, "pivot_calculator", None)
            if _pivot_calc_np is not None:
                try:
                    _np_price = float(recommendation.entry_price or 0)
                    if _np_price > 0:
                        _np_result = _pivot_calc_np.find_near_pivot(_np_price, symbol)
                        if _np_result:
                            _np_lvl, _np_src = _np_result
                            extra["near_pivot_level"] = round(_np_lvl, 8)
                            extra["near_pivot_pct"] = round(abs(_np_price - _np_lvl) / _np_price * 100, 3)
                            extra["near_pivot_source"] = _np_src
                        else:
                            extra["near_pivot_pct"] = None
                except Exception:
                    pass
            # ═══ DEV-202: ConfirmationAggregator → features_json.confirmations[] ═══
            _conf_agg_m = getattr(bot, "confirmation_aggregator", None)
            _conf_side_m = None
            if _conf_agg_m is not None:
                try:
                    _dir_val = getattr(recommendation.direction, 'value', str(recommendation.direction))
                    _conf_side_m = 'LONG' if 'LONG' in _dir_val.upper() else 'SHORT'
                    _agg_res = _conf_agg_m.aggregate(symbol, _conf_side_m)
                    if _agg_res.get('confirmations'):
                        if extra is None:
                            extra = {}
                        extra['confirmations'] = _agg_res['confirmations']
                        extra['signal_mode'] = _agg_res['signal_mode']
                        extra['strength_breakdown'] = _agg_res['strength_breakdown']
                except Exception as _ca_m_e:
                    logger.debug("[DEV-202] %s confirmation_aggregator error: %s", symbol, _ca_m_e)

            # ═══ DEV-201: confirmations[] для реактивных сигналов (confluence/divergence/pivot_reversal) ═══
            # Не влияет на торговые решения — только записывает в features_json для ML.
            # Выполняется ПОСЛЕ DEV-202: не перезаписывает confirmations от atr_change потока.
            # Безопасно: весь блок в try/except, side-effect только к extra['confirmations'].
            if not (extra or {}).get("confirmations") and signal_type and signal_type not in (
                "atr_change", "atr_change_15m", "atr_change_1h", "atr_change_4h",
            ) and not str(signal_type or "").startswith("atr_change_"):
                try:
                    from core.confirmations.models import Confirmation as _RConf
                    from core.confirmations.registry import get_weight as _rgw
                    _dir_v = getattr(recommendation.direction, "value", str(recommendation.direction))
                    _rsid = "LONG" if "LONG" in _dir_v.upper() else "SHORT"
                    _rconfs = []
                    _no_dup201 = lambda s: not any(c.get("source") == s for c in _rconfs)

                    # ─── Блок A: confluence_factors (основной источник для confluence/wt_b сигналов) ───
                    _cfs_r = (extra or {}).get("confluence_factors") or []
                    if isinstance(_cfs_r, list) and _cfs_r:
                        # WT cross in zone → zone + cross (conf 1.0)
                        if _rsid == "LONG" and "WT_CROSS_IN_OS" in _cfs_r:
                            for _src_cf, _ev_cf in (("zone_OS_1h", {}), ("wt_cross_same_dir", {"wt_cross_quality": "in_zone"})):
                                if _no_dup201(_src_cf):
                                    _w = _rgw(_src_cf, _rsid)
                                    if _w > 0:
                                        _rconfs.append(_RConf(source=_src_cf, symbol=symbol, side=_rsid,
                                            weight=_w, confidence=1.0, tf="15m", evidence=_ev_cf).to_dict())
                        elif _rsid == "SHORT" and "WT_CROSS_IN_OB" in _cfs_r:
                            for _src_cf, _ev_cf in (("zone_OB_1h", {}), ("wt_cross_same_dir", {"wt_cross_quality": "in_zone"})):
                                if _no_dup201(_src_cf):
                                    _w = _rgw(_src_cf, _rsid)
                                    if _w > 0:
                                        _rconfs.append(_RConf(source=_src_cf, symbol=symbol, side=_rsid,
                                            weight=_w, confidence=1.0, tf="15m", evidence=_ev_cf).to_dict())
                        # WT cross out of zone (conf 0.7)
                        _cross_key_r = "WT_CROSS_UP" if _rsid == "LONG" else "WT_CROSS_DOWN"
                        if _cross_key_r in _cfs_r and _no_dup201("wt_cross_same_dir"):
                            _w = _rgw("wt_cross_same_dir", _rsid)
                            if _w > 0:
                                _rconfs.append(_RConf(source="wt_cross_same_dir", symbol=symbol, side=_rsid,
                                    weight=_w, confidence=0.7, tf="15m",
                                    evidence={"wt_cross_quality": "out_zone"}).to_dict())
                        # WT zone без cross (от confluence_scanner: WT_OS / WT_OB)
                        _zone_key_r = "WT_OS" if _rsid == "LONG" else "WT_OB"
                        _zone_src_r = "zone_OS_1h" if _rsid == "LONG" else "zone_OB_1h"
                        if _zone_key_r in _cfs_r and _no_dup201(_zone_src_r):
                            _w = _rgw(_zone_src_r, _rsid)
                            if _w > 0:
                                _rconfs.append(_RConf(source=_zone_src_r, symbol=symbol, side=_rsid,
                                    weight=_w, confidence=0.8, tf="15m").to_dict())
                        # Divergence из confluence_factors
                        if "WT_HIDDEN_DIV" in _cfs_r:
                            _dsrc = "div_hidden_bull_15m" if _rsid == "LONG" else "div_hidden_bear_15m"
                            if _no_dup201(_dsrc):
                                _w = _rgw(_dsrc, _rsid)
                                if _w > 0:
                                    _rconfs.append(_RConf(source=_dsrc, symbol=symbol, side=_rsid,
                                        weight=_w, confidence=0.85, tf="15m",
                                        evidence={"cf_factor": "WT_HIDDEN_DIV"}).to_dict())
                        elif "WT_DIVERGENCE" in _cfs_r:
                            _dsrc = "div_regular_bull_15m" if _rsid == "LONG" else "div_regular_bear_15m"
                            if _no_dup201(_dsrc):
                                _w = _rgw(_dsrc, _rsid)
                                if _w > 0:
                                    _rconfs.append(_RConf(source=_dsrc, symbol=symbol, side=_rsid,
                                        weight=_w, confidence=0.85, tf="15m",
                                        evidence={"cf_factor": "WT_DIVERGENCE"}).to_dict())
                        # Pivot из confluence_factors
                        if ("PIVOT_TOUCH" in _cfs_r or "PIVOT_CONFLUENCE" in _cfs_r) and _no_dup201("pivot_touch_within_03"):
                            _w = _rgw("pivot_touch_within_03", _rsid)
                            if _w > 0:
                                _rconfs.append(_RConf(source="pivot_touch_within_03", symbol=symbol, side=_rsid,
                                    weight=_w, confidence=0.85, tf="15m",
                                    evidence={"cf_factor": "PIVOT_TOUCH"}).to_dict())

                    # ─── Блок B: flat extra keys (fallback / divergence / pivot_reversal) ───
                    # WT zone (OS/OB) из pre_fetched_dfs
                    _wt_zone_r = (extra or {}).get("wt_zone")
                    if _wt_zone_r == "OS" and _rsid == "LONG" and _no_dup201("zone_OS_1h"):
                        _w = _rgw("zone_OS_1h", _rsid)
                        if _w > 0:
                            _rconfs.append(_RConf(source="zone_OS_1h", symbol=symbol, side=_rsid,
                                weight=_w, confidence=1.0, tf="1h").to_dict())
                    elif _wt_zone_r == "OB" and _rsid == "SHORT" and _no_dup201("zone_OB_1h"):
                        _w = _rgw("zone_OB_1h", _rsid)
                        if _w > 0:
                            _rconfs.append(_RConf(source="zone_OB_1h", symbol=symbol, side=_rsid,
                                weight=_w, confidence=1.0, tf="1h").to_dict())
                    # Divergence из wt_div_type (supporting signals)
                    _div_t_r = (extra or {}).get("wt_div_type")
                    _div_src_r = {
                        "regular_bull": "div_regular_bull_15m", "regular_bear": "div_regular_bear_15m",
                        "hidden_bull": "div_hidden_bull_15m",   "hidden_bear": "div_hidden_bear_15m",
                    }.get(_div_t_r)
                    if _div_src_r and _no_dup201(_div_src_r):
                        _w = _rgw(_div_src_r, _rsid)
                        if _w > 0:
                            _rconfs.append(_RConf(source=_div_src_r, symbol=symbol, side=_rsid,
                                weight=_w, confidence=0.9, tf="15m",
                                evidence={"div_type": _div_t_r}).to_dict())
                    # WT cross из wt_cross_quality (supporting signals)
                    _wt_cq_r = (extra or {}).get("wt_cross_quality")
                    if _wt_cq_r and _no_dup201("wt_cross_same_dir"):
                        _w = _rgw("wt_cross_same_dir", _rsid)
                        if _w > 0:
                            _rconfs.append(_RConf(source="wt_cross_same_dir", symbol=symbol, side=_rsid,
                                weight=_w, confidence=1.0 if _wt_cq_r == "in_zone" else 0.7,
                                tf="15m", evidence={"wt_cross_quality": _wt_cq_r}).to_dict())
                    # Pivot touch из near_pivot_pct (pivot_calculator)
                    _near_pct_r = (extra or {}).get("near_pivot_pct")
                    if _near_pct_r is not None and _near_pct_r < 0.5 and _no_dup201("pivot_touch_within_03"):
                        _w = _rgw("pivot_touch_within_03", _rsid)
                        if _w > 0:
                            _rconfs.append(_RConf(source="pivot_touch_within_03", symbol=symbol, side=_rsid,
                                weight=_w, confidence=max(0.5, 1.0 - _near_pct_r * 2),
                                tf="15m", evidence={"near_pivot_pct": _near_pct_r}).to_dict())

                    if _rconfs:
                        if extra is None:
                            extra = {}
                        extra["confirmations"] = _rconfs
                        logger.debug("[DEV-201] %s %s %s: %d confs [%s]",
                                     symbol, signal_type, _rsid, len(_rconfs),
                                     ",".join(c["source"] for c in _rconfs))
                except Exception as _dev201_e:
                    logger.debug("[DEV-201] %s reactive confirmations error: %s", symbol, _dev201_e)

            # ═══ DEV-200 Phase 2: единый helper — observe-fallback + флаг no_trigger ═══
            # Дотягивает буферизованные helper-confs (smc/fvg/sweep/wt_extreme) для
            # no-trigger сигналов и выставляет confirmations_no_trigger по итоговому
            # набору (включая DEV-201 confluence). Gate aggregate() не трогает.
            if _conf_agg_m is not None and _conf_side_m:
                from core.intelligence.signal_aggregator import attach_confirmations as _attach
                extra = _attach(_conf_agg_m, symbol, _conf_side_m, extra)

            # Этап 1.Д (16.05.2026): main path через TradeRouter с per-signal_type source.
            # Откат: config.yaml → signal_router.enabled=false (использует старый путь в else).
            if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
                # Per-signal_type source — каждый тип получает свою policy в config
                _sr_source = signal_type if signal_type else "monitoring"
                # Проверка что policy существует, иначе fallback на "monitoring"
                _known_sources = (
                    bot.config.get("signal_router.source_policies", {}) or {}
                ).keys()
                if _sr_source not in _known_sources:
                    _sr_source = "monitoring"
                try:
                    _sr_result = await bot.trade_router.submit(
                        recommendation, source=_sr_source, extra_features=extra or None,
                    )
                    trade_id = _sr_result.trade_id
                    trade_registered = trade_id is not None
                    if not trade_registered:
                        _hd = ",".join(g for g, _ in _sr_result.hard_drops) or "none"
                        logger.info("[%s] router dropped (%s): %s str=%d",
                                    symbol, _sr_source, _hd, _sr_result.final_strength)
                    else:
                        logger.info(
                            "[%s] router #%d source=%s str=%d->%d soft=%d exch=%s",
                            symbol, trade_id, _sr_source,
                            int(getattr(recommendation, "overall_strength", 0) or 0),
                            _sr_result.final_strength, len(_sr_result.soft_penalties),
                            _sr_result.exchange_order_id or "none",
                        )
                        if hasattr(bot, "ws_feed") and bot.ws_feed.is_alive():
                            bot.ws_feed.update_priority_pairs([symbol])
                except Exception as _sr_e:
                    logger.warning("[%s] router.submit error: %s", symbol, _sr_e, exc_info=True)
                    trade_id = None
                    trade_registered = False
            else:
                # Старый путь (signal_router.enabled=false)
                trade_id = await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector, extra_features=extra or None)
                trade_registered = trade_id is not None
                if not trade_registered:
                    logger.info("[%s] register_trade → None (заблокировано: regime/SL/TP/gate) — сделка НЕ сохранена", symbol)
                else:
                    # DEV-202: сбросить буфер confirmations после успешной регистрации
                    if _conf_agg_m is not None and _conf_side_m is not None:
                        try:
                            _conf_agg_m.clear(symbol, _conf_side_m)
                        except Exception:
                            pass
                    if hasattr(bot, "ws_feed") and bot.ws_feed.is_alive():
                        bot.ws_feed.update_priority_pairs([symbol])
                    # DEV-77: OrderExecutor — VST/LIVE исполнение (SIM_ONLY = только лог)
                    if hasattr(bot, "order_executor") and is_actionable:
                        try:
                            _oe = bot.order_executor
                            _oe_dir = getattr(recommendation.direction, "value", "LONG")
                            _oe_entry = float(recommendation.entry_price or 0)
                            _oe_sl = float(recommendation.stop_loss or 0)
                            _oe_tp1 = float(recommendation.take_profit or 0)
                            _oe_tp2 = float(recommendation.tp1_price or 0) or None
                            # tsl_only сигналы (take_profit=None) → fallback TP = entry ± 15 * sl_dist
                            if _oe_tp1 <= 0 and _oe_entry > 0 and _oe_sl > 0:
                                _sl_dist = abs(_oe_entry - _oe_sl)
                                if _oe_dir == "LONG":
                                    _oe_tp1 = _oe_entry + 15 * _sl_dist
                                else:
                                    _oe_tp1 = _oe_entry - 15 * _sl_dist
                                logger.info("[%s] tsl_only → fallback TP=%.6f (15R safety)", symbol, _oe_tp1)
                            if _oe_entry > 0 and _oe_sl > 0 and _oe_tp1 > 0:
                                _deposit = await _oe.get_available_balance()
                                _risk_pct = float(bot.config.get("trading.risk_pct", 1.0))
                                _leverage = int(bot.config.get("trading.leverage", 5))
                                _qty = bot.position_sizer.calc_qty(
                                    entry_price=_oe_entry,
                                    sl_price=_oe_sl,
                                    deposit=_deposit,
                                    risk_pct=_risk_pct,
                                    leverage=_leverage,
                                )
                                if _qty > 0:
                                    _br = await _oe.open_bracket(
                                        symbol=symbol,
                                        direction=_oe_dir,
                                        entry_price=_oe_entry,
                                        sl=_oe_sl,
                                        tp1=_oe_tp1,
                                        tp2=_oe_tp2,
                                        qty=_qty,
                                        # 22.08: без source per-strategy порог min_sl_dist
                                        # здесь не виден — путь мимо роутера.
                                        source=str(signal_type or "monitoring"),
                                    )
                                    if not _br.success:
                                        if _br.error != "position_already_open":
                                            logger.warning("[%s] OrderExecutor ошибка: %s", symbol, _br.error)
                                        asyncio.create_task(decision_trace.record_drop(
                                            symbol=symbol, gate_name="open_bracket_fail",
                                            drop_reason=_br.error or "unknown",
                                            signal_type=signal_type, direction=_oe_dir,
                                            strength=int(getattr(recommendation, "overall_strength", 0) or 0),
                                        ))
                                    else:
                                        logger.info(
                                            "[%s] [%s] bracket: %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                                            symbol, _br.mode.upper(), _oe_dir, _qty,
                                            _oe_entry, _oe_sl, _oe_tp1, _br.order_id, _br.notional_usdt,
                                        )
                                        if hasattr(bot, "position_manager"):
                                            _pos_dir = "LONG" if _oe_dir == "LONG" else "SHORT"
                                            bot.position_manager.register(
                                                symbol=symbol, side=_pos_dir, qty=_qty,
                                                sim_trade_id=trade_id,
                                                exchange_order_id=_br.order_id,
                                            )
                                        if _br.order_id and trade_id:
                                            bot.trade_simulator.set_exchange_order_id(
                                                trade_id, _br.order_id, qty=_qty,
                                                actual_entry_price=_br.entry_price,
                                            )
                                            _pos_side = "LONG" if _oe_dir == "LONG" else "SHORT"
                                            if _br.tp_order_id:
                                                bot.trade_simulator.set_exchange_tp_order_id(trade_id, _br.tp_order_id)
                                            else:
                                                import asyncio as _asyncio
                                                from core.exchange.tsl_updater import fetch_and_save_tp_order_id
                                                _asyncio.create_task(fetch_and_save_tp_order_id(
                                                    bot, trade_id, symbol, _pos_side))
                                            if _br.sl_order_id:
                                                bot.trade_simulator.set_exchange_sl_order_id(trade_id, _br.sl_order_id)
                                            else:
                                                import asyncio as _asyncio
                                                from core.exchange.tsl_updater import fetch_and_save_sl_order_id
                                                _asyncio.create_task(fetch_and_save_sl_order_id(
                                                    bot, trade_id, symbol, _pos_side))
                                else:
                                    logger.warning("[%s] OrderExecutor: qty=0", symbol)
                                    asyncio.create_task(decision_trace.record_drop(
                                        symbol=symbol, gate_name="qty_zero",
                                        drop_reason=f"qty=0 deposit={_deposit:.2f} risk={_risk_pct:.1f}% entry={_oe_entry:.6g} sl={_oe_sl:.6g}",
                                        signal_type=signal_type, direction=_oe_dir,
                                        strength=int(getattr(recommendation, "overall_strength", 0) or 0),
                                    ))
                            else:
                                _zero = [f for f, v in [("entry", _oe_entry), ("sl", _oe_sl), ("tp", _oe_tp1)] if v <= 0]
                                asyncio.create_task(decision_trace.record_drop(
                                    symbol=symbol, gate_name="order_params_zero",
                                    drop_reason=f"нулевые поля {_zero}: entry={_oe_entry:.6g} sl={_oe_sl:.6g} tp={_oe_tp1:.6g}",
                                    signal_type=signal_type, direction=_oe_dir,
                                    strength=int(getattr(recommendation, "overall_strength", 0) or 0),
                                ))
                        except Exception as _oe_e:
                            logger.warning("[%s] OrderExecutor: %s", symbol, _oe_e)
        except Exception as e:
            logger.warning("TradeSimulator register_trade для %s (%s): %s", symbol, signal_type, e, exc_info=True)

    # Регистрируем сделки остальных стратегий (только в БД, без TG)
    other_recs = (getattr(recommendation, "metadata", None) or {}).get("all_strategy_recs", {})
    if other_recs:
        for strat_name, other_rec in other_recs.items():
            try:
                _dir_ok_other = (
                    getattr(other_rec, "action", "WATCH") in ("BUY", "SELL")
                    and getattr(other_rec, "direction", None) is not None
                    and other_rec.direction.value != "NEUTRAL"
                )
                if _dir_ok_other and other_rec.overall_strength >= min_strength_register:
                    other_rec.metadata = other_rec.metadata or {}
                    other_rec.metadata["strategy_name"] = strat_name
                    # ARCH-58: применяем иерархию пивотов для побочных стратегий
                    if hasattr(bot, "pivot_calculator"):
                        try:
                            _odir = getattr(other_rec.direction, "value", "")
                            _oentry = getattr(other_rec, "entry_price", None) or 0
                            _osl = getattr(other_rec, "stop_loss", None)
                            if _odir in ("LONG", "SHORT") and _oentry > 0 and _osl is not None:
                                _ores = bot.pivot_calculator.get_tp_by_hierarchy(
                                    direction=_odir,
                                    entry_price=_oentry,
                                    symbol=symbol,
                                    stop_loss=_osl,
                                    min_r=bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0),
                                )
                                if _ores:
                                    # ARCH-122 ч.1b (ExitManager): не перетираем магнит (см. main path)
                                    from core.trading.exit_manager import magnet_tp_locked
                                    if not magnet_tp_locked(other_rec, bot.config):
                                        other_rec.take_profit, other_rec.tp_source = _ores
                        except Exception as _e58:
                            logger.debug("[ARCH-58/other_recs] %s '%s': %s", symbol, strat_name, _e58)
                    # DEV-126: передаём weekly_bias + htf_wt из контекста основной рекомендации
                    _or_extra: dict = {}
                    _main_meta = (recommendation.metadata or {}) if recommendation else {}
                    if "weekly_bias" in _main_meta:
                        _or_extra["weekly_bias"] = _main_meta["weekly_bias"]
                        _or_extra["weekly_context_score"] = _main_meta.get("weekly_context_score", 0)
                    if pre_fetched_dfs:
                        for _or_tf, _or_k1, _or_k2 in [
                            ("1h", "htf_wt1_1h", "htf_wt2_1h"),
                            ("4h", "htf_wt1_4h", "htf_wt2_4h"),
                        ]:
                            _or_df = pre_fetched_dfs.get(_or_tf)
                            if _or_df is not None and "wt1" in _or_df.columns and len(_or_df) > 0:
                                try:
                                    _or_extra[_or_k1] = round(float(_or_df["wt1"].iloc[-1]), 1)
                                    _or_extra[_or_k2] = round(float(_or_df["wt2"].iloc[-1]), 1)
                                except Exception:
                                    pass
                    # Этап 1.Д: other_recs через router (source='other_strategy', exchange_enabled=false)
                    if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
                        try:
                            await bot.trade_router.submit(
                                other_rec, source="other_strategy",
                                extra_features=_or_extra or None,
                            )
                        except Exception as _or_sr_e:
                            logger.debug("[%s] router.submit other_strategy '%s' error: %s",
                                         symbol, strat_name, _or_sr_e)
                    else:
                        await bot.trade_simulator.register_trade_async(
                            other_rec, bot.data_collector,
                            extra_features=_or_extra or None,
                        )
                    logger.debug("[%s] Стратегия '%s' зарегистрирована в БД", symbol, strat_name)
            except Exception as e:
                logger.debug("register_trade стратегии '%s' для %s: %s", strat_name, symbol, e)

    text = raw_text
    if recommendation:
        try:
            # Если активная стратегия — MTF_BIAS, используем специальный форматтер
            _mtf_bias_sig = next(
                (s for s in (recommendation.supporting_signals or [])
                 if getattr(s, "signal_type", None) and s.signal_type.value == "mtf_bias"),
                None
            )
            if _mtf_bias_sig is not None:
                from core.mtf.mtf_interpreter import mtf_bias_message
                text = mtf_bias_message(symbol, _mtf_bias_sig)
            else:
                _show_fvg = bot.config.get("signals.show_fvg_confluences", True)
                text = await format_intelligence_message(recommendation, show_fvg_confluences=_show_fvg)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text
        if btc_warning:
            text = text.rstrip() + btc_warning
        # Стандартный footer статуса регистрации — в каждом сообщении
        if is_actionable and trade_registered:
            kelly_line = _get_kelly_footer(bot)
            text = text.rstrip() + "\n─────────────\n💾 <i>Сделка зарегистрирована в симуляторе</i>" + kelly_line
        elif recommendation:
            _reason_parts = []
            if getattr(recommendation, "action", "WATCH") not in ("BUY", "SELL"):
                _reason_parts.append(f"action={getattr(recommendation, 'action', '?')}")
            if recommendation.overall_strength < min_strength_register:
                _reason_parts.append(f"сила={recommendation.overall_strength:.0f}&lt;{min_strength_register}")
            _mtf = (recommendation.metadata or {}).get("mtf_context", {})
            _bias = _mtf.get("direction_bias", "") if isinstance(_mtf, dict) else ""
            _aligned = _mtf.get("aligned_pct") if isinstance(_mtf, dict) else None
            _mtf_str = f" · MTF {_bias} {_aligned}%" if _bias and _aligned else ""
            _reason_str = ", ".join(_reason_parts) if _reason_parts else "WATCH"
            text = text.rstrip() + f"\n─────────────\n❌ <i>Не зарегистрирован: {_reason_str}{_mtf_str}</i>"
            logger.info("[%s] Сделка не зарегистрирована: %s%s", symbol, _reason_str, _mtf_str)

    # ── ARCH-91: Narrative блок в TG ─────────────────────────────────────────
    if recommendation is not None and bot.config.get("trading.narrative.include_in_tg", False):
        try:
            _narr_cfg = bot.config.get("trading.narrative", {}) or {}
            _max_n = int(_narr_cfg.get("max_factors_in_tg", 4))
            _narr_meta = (recommendation.metadata or {}).get("narrative") or {}
            _smc_f = list(_narr_meta.get("smc_factors") or [])
            _key_f = list(_narr_meta.get("key_factors") or [])
            _all_factors = (_smc_f + _key_f)[:_max_n]
            _narr_parts: list[str] = []
            if _all_factors:
                _narr_parts.append("📖 <b>Нарратив:</b>\n" + "\n".join(f"• {f}" for f in _all_factors))
            if _narr_cfg.get("include_past_outcome", True):
                try:
                    from core.intelligence.narrative_builder import _extract_past_outcome_line
                    _pair_bus = getattr(bot, "pair_context", None)
                    _ps = _pair_bus.get(symbol) if _pair_bus else None
                    _past = _extract_past_outcome_line(_ps)
                    if _past:
                        _narr_parts.append(f"📜 {_past}")
                except Exception:
                    pass
            if _narr_parts:
                text = text.rstrip() + "\n─────────────\n" + "\n".join(_narr_parts)
        except Exception as _e_narr_tg:
            logger.debug("[ARCH-91] narrative TG block error: %s", _e_narr_tg)

    # ── DEV-151: Groq AI-комментарий к сигналу ───────────────────────────────
    if recommendation is not None and bot.config.get("trade_analyzer.signal_comment", True):
        try:
            from core.trading.trade_analyzer import TradeAnalyzer
            _ta = TradeAnalyzer(db_path=getattr(bot.trade_simulator, "db_path", "subscriptions.db"))
            if _ta._enabled:
                _ai_comment = await _ta.analyze_signal(recommendation)
                if _ai_comment:
                    text = text.rstrip() + f"\n─────────────\n🤖 <i>{_ai_comment}</i>"
        except Exception as _e_ta:
            logger.debug("[DEV-151] Groq signal comment error: %s", _e_ta)

    # ── Хэштеги для навигации по истории TG (вариант B) ─────────────────────
    _ht_sym = symbol.split("/")[0].split("-")[0].split(":")[0].upper() + "USDT"
    _ht_dir = ""
    if recommendation is not None:
        _ht_dir = getattr(recommendation.direction, "value", "")
    if not _ht_dir:
        _ht_dir = direction.upper() if direction else ""
    _ht_sig = signal_type.replace(".", "_").upper()
    _hashtags = f"#{_ht_sym} #{_ht_dir} #{_ht_sig}" if _ht_dir else f"#{_ht_sym} #{_ht_sig}"
    text = text.rstrip() + f"\n\n{_hashtags}"

    # ── PNG-график (если send_chart: true в config) ───────────────────────────
    png_bytes = None
    if bot.config.get("signals.send_chart", False):
        try:
            from core.ui.chart_builder import build_signal_chart
            chart_tf   = bot.config.get("signals.chart_tf", "1h")
            chart_bars = int(bot.config.get("signals.chart_bars", 300))
            _chart_fvg_all = (getattr(recommendation, "metadata", None) or {}).get("fvg_confluences") or []
            # Только зоны в ±8% от текущей цены — не перегружать чарт дальними уровнями
            _chart_fvg = [z for z in _chart_fvg_all
                          if abs(z.get("distance_pct", 999)) <= 8.0] or None
            png_bytes = await build_signal_chart(
                symbol, tf=chart_tf, bars=chart_bars,
                bot=bot, fvg_zones=_chart_fvg,
            )
        except Exception:
            logger.exception("Ошибка генерации графика для %s", symbol)

    # DEV-222: trade_id передаётся только для зарегистрированных сделок (не WATCH)
    _broadcast_trade_id = trade_id if trade_registered else None
    await broadcast_with_subscription_check(bot, text, signal_type, chart_png=png_bytes, trade_id=_broadcast_trade_id)

    # fallback_rec отключён: analyze_symbol с MTF multiplier — единственный путь регистрации.
    # Старый fallback обходил MTF context → strength 70-100 при bias AGAINST → WR=8.7%.
    if not should_register and not trade_registered and fallback_rec is not None:
        fallback_strength = getattr(fallback_rec, "overall_strength", 0)
        logger.info("[%s] Fallback НЕ регистрируем (MTF bypass fix): str=%.0f, signal=%s",
                    symbol, fallback_strength, signal_type)


_TG_BROADCAST_SEM = asyncio.Semaphore(25)  # DEV-120: Telegram safe rate ~25 msg/sec


def _prepare_photo_caption(text: str, limit: int = 980) -> str:
    """
    Caption для фото с сохранением HTML-разметки (ссылки кликабельны).
    Telegram photo caption limit = 1024 знаков. Берём 980 для безопасности.
    Отправляется с parse_mode="HTML".
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    truncated = text[: limit - 1].rstrip()
    # Если обрезка попала внутрь тега — откатиться до последнего '<'
    last_open = truncated.rfind("<")
    last_close = truncated.rfind(">")
    if last_open > last_close:
        truncated = truncated[:last_open].rstrip()
    truncated += "…"
    return _close_open_html_tags(truncated)


def _close_open_html_tags(text: str) -> str:
    """Закрывает незакрытые HTML-теги после обрезки текста."""
    import re
    open_tags = re.findall(r"<(b|i|u|s|code|pre|a)\b[^>]*>", text, re.IGNORECASE)
    close_tags = re.findall(r"</(b|i|u|s|code|pre|a)>", text, re.IGNORECASE)
    # Считаем незакрытые теги (стек)
    stack = []
    for tag in open_tags:
        stack.append(tag.lower())
    for tag in close_tags:
        tag_lower = tag.lower()
        if tag_lower in stack:
            stack.remove(tag_lower)
    # Закрываем в обратном порядке
    for tag in reversed(stack):
        text += f"</{tag}>"
    return text


async def broadcast_with_subscription_check(bot, text: str, signal_type: str,
                                             chart_png: bytes | None = None,
                                             trade_id: int | None = None):
    if not bot.subscribers:
        logger.warning("Нет подписчиков для отправки сигнала %s", signal_type)
        return

    uids = list(bot.subscribers)
    logger.info("Отправка сигнала %s для %d подписчиков (chart=%s)",
                signal_type, len(uids), chart_png is not None)

    # DEV-222: собираем message_id per user для reply при закрытии
    async def _send_one(uid: int) -> tuple[int, int] | None:
        try:
            if not bot.subscription_manager.can_receive_signal(uid, signal_type):
                logger.debug("Пользователь %s не может получить сигнал %s", uid, signal_type)
                return None
            if not bot.subscription_manager.can_send_signal_today(uid):
                logger.debug("Пользователь %s достиг дневного лимита", uid)
                return None

            async with _TG_BROADCAST_SEM:
                if chart_png:
                    caption = _prepare_photo_caption(text)
                    from aiogram.types import BufferedInputFile
                    msg = await bot.bot.send_photo(
                        chat_id=uid,
                        photo=BufferedInputFile(chart_png, filename="chart.png"),
                        caption=caption,
                        parse_mode="HTML",
                    )
                else:
                    msg = await bot.bot.send_message(
                        chat_id=uid, text=text, disable_web_page_preview=True, parse_mode="HTML"
                    )

            bot.subscription_manager.record_signal_sent(uid, signal_type)
            logger.debug("Сигнал %s отправлен пользователю %s", signal_type, uid)
            return (uid, msg.message_id)
        except Exception:
            logger.exception("Ошибка отправки сообщения %s", uid)
            return None

    # DEV-120: параллельная рассылка всем подписчикам
    results = await asyncio.gather(*[_send_one(uid) for uid in uids])
    sent = [r for r in results if r is not None]
    sent_count = len(sent)

    if sent_count == 0:
        logger.warning("Сигнал %s не отправлен ни одному подписчику", signal_type)
    else:
        logger.info("Сигнал %s отправлен %d/%d подписчикам", signal_type, sent_count, len(uids))

    # DEV-222: сохраняем message_id только для зарегистрированных сделок
    if trade_id and sent:
        try:
            db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
            import sqlite3 as _sqlite3
            with _sqlite3.connect(db_path, timeout=10) as _conn:
                _conn.executemany(
                    "INSERT OR REPLACE INTO tg_messages (trade_id, user_id, message_id) VALUES (?,?,?)",
                    [(trade_id, uid, mid) for uid, mid in sent],
                )
                _conn.commit()
            logger.debug("[DEV-222] Сохранены message_id для trade_id=%d: %d пользователей", trade_id, len(sent))
        except Exception as _e:
            logger.debug("[DEV-222] Ошибка сохранения tg_messages: %s", _e)


async def send_tsl_activated_alert(
    bot,
    trade_id: int,
    symbol: str,
    direction: str,
    current_r: float | None,
    tsl_tf: str,
) -> None:
    """DEV-223: Пуш в TG когда TSL впервые активировался для сделки."""
    try:
        db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
        import sqlite3 as _sqlite3
        with _sqlite3.connect(db_path, timeout=10) as _conn:
            rows = _conn.execute(
                "SELECT user_id, message_id FROM tg_messages WHERE trade_id=?", (trade_id,)
            ).fetchall()

        sym_short = symbol.split("/")[0]
        dir_arrow = "↑ LONG" if direction == "LONG" else "↓ SHORT"
        r_str = f"+{current_r:.2f}R" if current_r else "?"

        text = (
            f"🔒 <b>TSL активирован</b> · <b>{sym_short}</b> {dir_arrow}\n"
            f"Прибыль зафиксирована от {r_str} · TSL следит на {tsl_tf}\n"
            f"<i>Позиция защищена — SL двигается за ценой</i>"
        )

        if rows:
            # Отвечаем reply на сообщение об открытии
            for user_id, message_id in rows:
                try:
                    async with _TG_BROADCAST_SEM:
                        await bot.bot.send_message(
                            chat_id=user_id,
                            text=text,
                            reply_to_message_id=message_id,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                except Exception as _eu:
                    logger.debug("[DEV-223] TSL alert reply error user=%d: %s", user_id, _eu)
        else:
            # Нет message_id (atr_change или старая сделка) — просто broadcast
            uids = list(getattr(bot, "subscribers", []))
            for uid in uids:
                try:
                    async with _TG_BROADCAST_SEM:
                        await bot.bot.send_message(
                            chat_id=uid, text=text, parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                except Exception as _eu:
                    logger.debug("[DEV-223] TSL alert error user=%d: %s", uid, _eu)

        logger.info("[DEV-223] TSL алерт отправлен trade_id=%d %s R=%s tf=%s", trade_id, sym_short, r_str, tsl_tf)
    except Exception as _e:
        logger.debug("[DEV-223] send_tsl_activated_alert error: %s", _e)


async def send_trade_close_reply(
    bot,
    trade_id: int,
    status: str,
    symbol: str,
    direction: str,
    r_multiple: float,
    tsl_activated: int,
    max_r_possible: float | None,
) -> None:
    """DEV-222: Reply на TG-сообщение об открытии при закрытии сделки."""
    try:
        db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
        import sqlite3 as _sqlite3
        with _sqlite3.connect(db_path, timeout=10) as _conn:
            rows = _conn.execute(
                "SELECT user_id, message_id FROM tg_messages WHERE trade_id=?", (trade_id,)
            ).fetchall()

        if not rows:
            return  # WATCH или старая сделка без message_id

        # Формируем текст закрытия
        _status_icons = {"TP": "🎯", "TSL": "💚", "SL": "❌", "EXPIRED": "⏰"}
        _status_labels = {"TP": "Тейк-профит", "TSL": "Трейлинг-стоп", "SL": "Стоп-лосс", "EXPIRED": "Истёк"}
        icon = _status_icons.get(status, "📋")
        label = _status_labels.get(status, status)

        _r_str = f"{r_multiple:+.2f}R" if r_multiple is not None else "?"
        _r_emoji = "🟢" if r_multiple and r_multiple > 0 else "🔴"

        lines = [f"{icon} <b>{label}</b> · {_r_emoji} {_r_str} · <b>{symbol}</b>"]

        if tsl_activated and status == "SL":
            lines.append("⚠️ TSL был активирован, но цена вернулась к SL")
        elif status == "TSL":
            if max_r_possible and max_r_possible > 0:
                _captured = round(r_multiple / max_r_possible * 100) if r_multiple and max_r_possible else 0
                lines.append(f"📊 Захвачено {_captured}% потенциала (пик {max_r_possible:+.2f}R)")
        elif status == "TP":
            lines.append("✅ Цель достигнута")

        # Хэштег закрытия для навигации
        _close_tag = {"TSL": "#TSL_CLOSED", "TP": "#TP_CLOSED", "SL": "#SL_CLOSED", "EXPIRED": "#EXPIRED"}.get(status, "")
        _ht_sym = symbol.split("/")[0].split("-")[0].split(":")[0].upper() + "USDT"
        _ht_dir = direction.upper() if direction else ""
        _close_hashtags = f"#{_ht_sym} #{_ht_dir} {_close_tag}".strip() if _ht_dir else f"#{_ht_sym} {_close_tag}".strip()
        text = "\n".join(lines) + f"\n\n{_close_hashtags}"

        # Шлём reply каждому подписчику
        for user_id, message_id in rows:
            try:
                async with _TG_BROADCAST_SEM:
                    await bot.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_to_message_id=message_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                logger.debug("[DEV-222] Reply отправлен trade_id=%d user=%d status=%s", trade_id, user_id, status)
            except Exception as _eu:
                logger.debug("[DEV-222] Reply error user=%d: %s", user_id, _eu)

        # Чистим запись — reply уже отправлен
        with _sqlite3.connect(db_path, timeout=10) as _conn:
            _conn.execute("DELETE FROM tg_messages WHERE trade_id=?", (trade_id,))
            _conn.commit()

    except Exception as _e:
        logger.debug("[DEV-222] send_trade_close_reply error: %s", _e)


def trade_tracker_loop(bot):
    """Делегирует в bot.loops.trade_tracker (перемещено туда для разбивки монолита)."""
    from bot.loops.trade_tracker import trade_tracker_loop as _loop
    return _loop(bot)


# ---------------------------------------------------------------------------
# Этап 5.3 — Еженедельный отчёт
# ---------------------------------------------------------------------------

def format_weekly_report(stats: dict) -> str:
    lines = [
        "<b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ</b>",
        f"Сделок закрыто: <b>{stats['total']}</b>",
        f"Win rate: <b>{stats['win_rate']}%</b>  •  Avg R: <b>{stats['avg_r']}</b>  •  Best R: <b>{stats['best_r']}</b>",
    ]
    if stats.get("by_signal_type"):
        lines += ["", "<b>По типу сигнала:</b>"]
        for s in stats["by_signal_type"][:5]:
            cnt = s["cnt"] or 0
            wr = round((s["wins"] or 0) / cnt * 100) if cnt else 0
            avg_r = round(s["avg_r"] or 0, 2)
            lines.append(f"• {s['signal_type']}: {cnt} сд., WR {wr}%, Avg R {avg_r}")
    return "\n".join(lines)


async def send_weekly_report(bot) -> None:
    from core.trading.performance_engine import PerformanceEngine
    try:
        pe = PerformanceEngine(bot.trade_simulator.db_path)
        stats = pe.weekly_summary(days_back=7)
        if not stats["total"]:
            logger.info("Еженедельный отчёт: нет закрытых сделок за неделю")
            return
        text = format_weekly_report(stats)
        await broadcast_with_subscription_check(bot, text, "weekly_report")
        logger.info("Еженедельный отчёт отправлен (%d сделок)", stats["total"])
    except Exception:
        logger.exception("Ошибка отправки еженедельного отчёта")


# ---------------------------------------------------------------------------
# DEV-224 — Утренний дайджест 07:00 UTC
# ---------------------------------------------------------------------------

async def send_morning_digest(bot) -> None:
    """Отправляет дайджест за прошедшую ночь: закрытые сделки + открытые позиции."""
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone, timedelta

    db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=8)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with _sqlite3.connect(db_path, timeout=10) as _conn:
            _conn.row_factory = _sqlite3.Row
            # Закрытые за последние 8 часов
            closed = _conn.execute(
                "SELECT symbol, direction, signal_type, status, R_multiple, tsl_activated "
                "FROM simulated_trades WHERE status != 'OPEN' AND closed_at >= ? "
                "ORDER BY closed_at ASC",
                (cutoff_str,),
            ).fetchall()
            # Открытые сейчас
            open_trades = _conn.execute(
                "SELECT id, symbol, direction, signal_type, entry_price, stop_loss, tsl_activated, created_at "
                "FROM simulated_trades WHERE status='OPEN' ORDER BY id DESC LIMIT 10",
            ).fetchall()
    except Exception:
        logger.exception("[DEV-224] morning_digest DB error")
        return

    lines = [f"🌅 <b>Утренний дайджест</b> · {now_utc.strftime('%d.%m %H:%M')} UTC"]

    # ── Закрытые сделки за ночь ──
    if closed:
        total_r = sum(r["R_multiple"] or 0 for r in closed)
        wins = sum(1 for r in closed if (r["R_multiple"] or 0) > 0)
        losses = len(closed) - wins
        tp_cnt  = sum(1 for r in closed if r["status"] == "TP")
        tsl_cnt = sum(1 for r in closed if r["status"] == "TSL")
        sl_cnt  = sum(1 for r in closed if r["status"] == "SL")
        exp_cnt = sum(1 for r in closed if r["status"] == "EXPIRED")

        _r_emoji = "🟢" if total_r >= 0 else "🔴"
        lines.append(f"\n<b>Ночь (8ч):</b> {len(closed)} сделок · {_r_emoji} <b>{total_r:+.2f}R</b>")
        _parts = []
        if tp_cnt:  _parts.append(f"TP×{tp_cnt}")
        if tsl_cnt: _parts.append(f"TSL×{tsl_cnt}")
        if sl_cnt:  _parts.append(f"SL×{sl_cnt}")
        if exp_cnt: _parts.append(f"EXP×{exp_cnt}")
        lines.append(f"W/L: {wins}/{losses} · " + " · ".join(_parts))

        # Топ-3 по |R|
        top3 = sorted(closed, key=lambda r: abs(r["R_multiple"] or 0), reverse=True)[:3]
        for t in top3:
            _sym = t["symbol"].replace("-USDT", "").replace("/USDT", "")
            _dir = "↑" if t["direction"] == "LONG" else "↓"
            _r   = t["R_multiple"] or 0
            _re  = "🟢" if _r > 0 else "🔴"
            _tsl = " 🔒" if t["tsl_activated"] else ""
            lines.append(f"  {_re} {_sym}{_dir} {_r:+.2f}R [{t['status']}]{_tsl}")
    else:
        lines.append("\n<i>Ночью сделок не закрывалось</i>")

    # ── Открытые позиции ──
    if open_trades:
        lines.append(f"\n<b>Открыто сейчас:</b> {len(open_trades)}")
        # Показываем до 5 с TSL-статусом
        for t in open_trades[:5]:
            _sym = t["symbol"].replace("-USDT", "").replace("/USDT", "")
            _dir = "↑" if t["direction"] == "LONG" else "↓"
            _tsl = " 🔒TSL" if t["tsl_activated"] else ""
            lines.append(f"  #{t['id']} {_sym}{_dir}{_tsl}")
        if len(open_trades) > 5:
            lines.append(f"  … ещё {len(open_trades) - 5} · /позиции")
    else:
        lines.append("\n<i>Открытых позиций нет</i>")

    text = "\n".join(lines)
    await broadcast_with_subscription_check(bot, text, "morning_digest")
    logger.info("[DEV-224] Утренний дайджест отправлен: %d закрытых, %d открытых",
                len(closed), len(open_trades))
