"""
Фоновый мониторинг рынка: фильтры сигналов, фоновые проверки, broadcast.
Цикл сканирования вынесен в bot/loops/scan_loop.py.
Все функции принимают bot (TradingAlertBot) первым аргументом.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.message_builder import anomaly_message, wt_message, mtf_message
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import divergence_message, mtf_divergence_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from core.signal_checkers import check_anomaly_signals, check_wt_signals as _check_wt_signals, check_mtf_signals as _check_mtf_signals
from core.signal_models import SignalData, SignalType, SignalDirection
from bot.keyboards import main_menu

logger = logging.getLogger(__name__)

# Ограничиваем параллельные вызовы analyze_symbol (тяжёлый: ML + 3 OHLCV-фетча)
# Размер задаётся через config: performance.analyze_semaphore_size (default 3)
_analyze_sem: asyncio.Semaphore | None = None


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
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="pivot_reversal"))
    return SimpleNamespace(
        symbol=info.get("symbol", ""),
        entry_price=info.get("entry_price"),
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=info.get("stop_loss"),
        take_profit=tp_main,
        tp1_price=tp1,
        overall_strength=strength,
        confidence=conf_float,
        timestamp=datetime.now(),
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source=info.get("sl_source", "atr_14"),
        tp_source=f"pivot_1W_{level}" if level else "pivot_1W",
        metadata={},
    )


async def start_monitoring(bot, message):
    from bot.loops.scan_loop import monitor_market, _prefetch_pivots

    if bot.is_monitoring:
        await message.answer("⚠️ Мониторинг уже запущен.", reply_markup=main_menu())
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
        await message.answer("❌ Не удалось загрузить пары.", reply_markup=main_menu())
        return

    bot.monitored_pairs = pairs
    bot.is_monitoring = True
    bot.start_time = datetime.now()
    bot.monitor_task = asyncio.create_task(monitor_market(bot))

    asyncio.create_task(_prefetch_pivots(bot))

    await message.answer(
        f"✅ Запущен мониторинг {len(bot.monitored_pairs)} пар.\n"
        f"📡 Отслеживаю: аномалии, WT, MTF, тренд-сигналы и дивергенции\n\n"
        f"💎 <b>Ваша подписка:</b> "
        f"{bot.subscription_manager.get_subscription_info(user_id)['tier']}",
        reply_markup=main_menu(),
    )


async def stop_monitoring(bot, message):
    if not bot.is_monitoring:
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
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=30)
                if df_15m is None or df_15m.empty:
                    return
                signals = await check_anomaly_signals(sym, df_15m)
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
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=150)
                if df_15m is None or df_15m.empty:
                    return
                df_1h = await bot.data_collector.get_ohlcv(sym, "1h", limit=60)
                signals = await _check_wt_signals(sym, df_15m, df_1h)
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


async def check_mtf_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                df_1h  = await bot.data_collector.get_ohlcv(sym, "1h",  limit=100)
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=100)
                df_3m  = await bot.data_collector.get_ohlcv(sym, "3m",  limit=100)
                if df_1h is None or df_1h.empty or df_15m is None or df_15m.empty:
                    return
                signals = await _check_mtf_signals(sym, df_1h, df_15m, df_3m)
                for sig in signals:
                    info = sig.data or {}
                    raw_text = mtf_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_signal")
                    bot.signal_counters["mtf_signal"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_mtf_signals для %s", sym)

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
        strength=strength, confidence=0.7, timestamp=datetime.now(), data=data or {},
    )


async def check_mtf_alerts(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                snapshot = await collect_mtf_data(sym, bot.data_collector)
                if not snapshot:
                    return
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    raw_text = mtf_alert_message(sym, snapshot, sig)
                    pre = [_make_signal_stub(sym, SignalType.MTF_ALERT, sig)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_alert", pre_signals=pre)
                    bot.signal_counters["mtf_alert"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_mtf_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_cascade_divergences(bot, senior_tf: str, junior_tf: str):
    """Проверяет MTF-конфлюэнцию дивергенций (скрытая senior_tf + регулярная junior_tf) для всех пар."""
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
            except Exception:
                logger.exception("Ошибка check_trend_signals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_divergences(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            for tf in ("15m", "1h"):
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
                    # Кешируем для меню "Все сигналы"
                    bot.recent_signals.setdefault(sym, [])
                    bot.recent_signals[sym] = [
                        s for s in bot.recent_signals[sym] if s.signal_type != SignalType.PIVOT_REVERSAL
                    ] + [stub]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "pivot_reversal",
                                                        fallback_rec=pivot_rec, pre_signals=pre)
                    bot.signal_counters["pivot_reversal"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Вход от уровня: %s R:R=%.1f", sym, info.get("level"), info.get("rr_ratio", 0))
            except Exception:
                logger.exception("Ошибка check_pivot_reversals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


def _is_in_sl_cooldown(bot, symbol: str) -> bool:
    """Возвращает True если по этой паре было SL-закрытие в течение sl_cooldown_hours."""
    hours = bot.config.get("signal_quality.sl_cooldown_hours", 4)
    if hours <= 0:
        return False
    try:
        db_path = bot.trade_simulator.db_path
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status='SL' AND closed_at>=? LIMIT 1",
                (symbol, cutoff_str),
            ).fetchone()
        if row:
            logger.debug("[%s] Cooldown после SL — сигнал пропущен (%dh)", symbol, hours)
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
        from core.market_regime import MarketRegimeClassifier
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "1h", limit=50)
        if ohlcv is not None and not ohlcv.empty:
            regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv.values.tolist())
            bot._btc_regime_cache = {"regime": regime, "ts": now}
            return regime
    except Exception as e:
        logger.debug("BTC режим не определён: %s", e)
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
        from core.r_predictor import RPredictor
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
                                        fallback_rec=None, pre_signals=None):
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
        return
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol):
        return

    recommendation = None
    try:
        async with _get_analyze_sem(bot):
            recommendation = await bot.trading_intelligence.analyze_symbol(
                symbol, pre_collected_signals=pre_signals
            )
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    # Этап 5.2: BTC-корреляционный фильтр
    # Слабые контртрендовые сигналы (strength < 70) — блокируем
    # Сильные (strength >= 70) — доставляем с предупреждением
    btc_regime = await _get_btc_regime(bot) if bot.config.get("signal_quality.btc_filter_enabled", True) else None
    btc_warning = ""
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
            if strength_val < ct_thr:
                logger.info("[%s] BTC %s vs %s, сила %d < %d — пропущен",
                            symbol, btc_regime, direction_val, strength_val, ct_thr)
                return
            # Сила >= ct_thr — доставляем с предупреждением
            regime_ru = "восходящем" if btc_regime == "TREND_UP" else "нисходящем"
            dir_ru = "шорт" if direction_val == "SHORT" else "лонг"
            btc_warning = f"\n⚠️ <i>BTC (1h) в {regime_ru} тренде — {dir_ru} против рынка, сигнал сильный ({strength_val}/100)</i>"
            logger.info("[%s] BTC %s vs %s, сила %d >= %d — предупреждение",
                        symbol, btc_regime, direction_val, strength_val, ct_thr)

    # Этап 6: заменяем fixed TP на ближайший пивот с R >= tp_pivot_min_r (из конфига)
    distance_to_pivot_pct: float = 0.0
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        entry_price = recommendation.entry_price or 0
        if direction_val in ("LONG", "SHORT") and entry_price > 0:
            pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0)
            pivot_result = bot.pivot_calculator.get_pivot_tp_with_source(
                direction=direction_val,
                entry_price=entry_price,
                symbol=symbol,
                stop_loss=recommendation.stop_loss,
                min_r=pivot_min_r,
            )
            if pivot_result:
                pivot_tp, pivot_src = pivot_result
                recommendation.take_profit = pivot_tp
                recommendation.tp_source = pivot_src
                distance_to_pivot_pct = abs(pivot_tp - entry_price) / entry_price * 100
                logger.debug("[%s] Pivot TP: %.6f (%.2f%%, %s, src=%s)", symbol, pivot_tp, distance_to_pivot_pct, direction_val, pivot_src)

    min_strength = bot.config.get("signal_quality.min_strength", 50)
    min_strength_register = bot.config.get("signal_quality.min_strength_register", 50)

    _dir_ok = (
        recommendation is not None
        and getattr(recommendation, "action", "WATCH") in ("BUY", "SELL")
        and getattr(recommendation, "direction", None) is not None
        and recommendation.direction.value != "NEUTRAL"
    )
    is_actionable = _dir_ok and recommendation.overall_strength >= min_strength
    should_register = _dir_ok and recommendation.overall_strength >= min_strength_register

    # WATCH+NEUTRAL — нет торгового решения, не спамим
    if (recommendation is not None
            and getattr(recommendation, "action", "WATCH") in ("WATCH", "HOLD")
            and getattr(recommendation.direction, "value", "NEUTRAL") == "NEUTRAL"):
        logger.info("[%s] Пропущен WATCH+NEUTRAL — нет торгового решения", symbol)
        return

    # Регистрируем сделку ДО отправки TG — чтобы footer "зарегистрирована" соответствовал реальности
    trade_registered = False
    if should_register:
        try:
            extra: dict = {}
            if distance_to_pivot_pct:
                extra["distance_to_pivot_pct"] = distance_to_pivot_pct
            # Извлекаем факторы confluence для аналитики WR по каждому фактору
            conf_factors = []
            for sig in (recommendation.supporting_signals or []):
                if getattr(sig, "signal_type", None) and sig.signal_type.value == "confluence":
                    conf_factors = (sig.data or {}).get("factors", [])
                    break
            if conf_factors:
                extra["confluence_factors"] = conf_factors
            trade_id = await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector, extra_features=extra or None)
            trade_registered = trade_id is not None
            if not trade_registered:
                logger.warning("[%s] register_trade вернул None (нет entry_price/SL/TP?) — сделка НЕ сохранена", symbol)
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
                    await bot.trade_simulator.register_trade_async(other_rec, bot.data_collector)
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
                from core.mtf_interpreter import mtf_bias_message
                text = mtf_bias_message(symbol, _mtf_bias_sig)
            else:
                text = await format_intelligence_message(recommendation)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text
        if btc_warning:
            text = text.rstrip() + btc_warning
        if is_actionable and trade_registered:
            kelly_line = _get_kelly_footer(bot)
            text = text.rstrip() + "\n─────────────\n💾 <i>Сделка зарегистрирована в симуляторе</i>" + kelly_line

    await broadcast_with_subscription_check(bot, text, signal_type)

    if should_register:
        pass  # уже зарегистрировано выше
    elif recommendation:
        reason = []
        if recommendation.overall_strength < min_strength_register:
            reason.append(f"strength={recommendation.overall_strength:.1f}<{min_strength_register}")
        if getattr(recommendation, "action", "WATCH") not in ("BUY", "SELL"):
            reason.append(f"action={getattr(recommendation, 'action', '?')}")
        if getattr(recommendation, "direction", None) is None or recommendation.direction.value == "NEUTRAL":
            reason.append("direction=NEUTRAL")
        logger.info("[%s] Сделка не зарегистрирована: %s", symbol, ", ".join(reason))
    elif fallback_rec is not None:
        fallback_strength = getattr(fallback_rec, "overall_strength", 0)
        if fallback_strength >= min_strength_register:
            try:
                await bot.trade_simulator.register_trade_async(fallback_rec, bot.data_collector)
                logger.info("TradeSimulator fallback: зарегистрирован %s str=%.0f", symbol, fallback_strength)
            except Exception as e:
                logger.debug("TradeSimulator fallback для %s: %s", symbol, e)
        else:
            logger.info("[%s] Fallback не зарегистрирован: strength=%.0f < %d", symbol, fallback_strength, min_strength_register)


async def broadcast_with_subscription_check(bot, text: str, signal_type: str):
    if not bot.subscribers:
        logger.warning("Нет подписчиков для отправки сигнала %s", signal_type)
        return

    logger.info("Отправка сигнала %s для %d подписчиков", signal_type, len(bot.subscribers))
    sent_count = 0
    for uid in list(bot.subscribers):
        try:
            if not bot.subscription_manager.can_receive_signal(uid, signal_type):
                logger.debug("Пользователь %s не может получить сигнал %s", uid, signal_type)
                continue
            if not bot.subscription_manager.can_send_signal_today(uid):
                logger.debug("Пользователь %s достиг дневного лимита", uid)
                continue
            await bot.bot.send_message(chat_id=uid, text=text, disable_web_page_preview=True)
            sent_count += 1
            logger.info("Сигнал %s отправлен пользователю %s", signal_type, uid)
            bot.subscription_manager.record_signal_sent(uid, signal_type)
        except Exception:
            logger.exception("Ошибка отправки сообщения %s", uid)

    if sent_count == 0:
        logger.warning("Сигнал %s не отправлен ни одному подписчику", signal_type)
    else:
        logger.info("Сигнал %s отправлен %d подписчикам", signal_type, sent_count)


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
    from core.performance_engine import PerformanceEngine
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
