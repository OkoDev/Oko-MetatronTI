"""
Фоновый мониторинг рынка: цикл проверок и рассылка сигналов.
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
from core.divergence_detector import divergence_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from core.signal_checkers import check_anomaly_signals, check_wt_signals as _check_wt_signals, check_mtf_signals as _check_mtf_signals
from bot.keyboards import main_menu

logger = logging.getLogger(__name__)


def _make_pivot_recommendation(info: dict):
    """Адаптер dict от check_pivot_level_signal → объект для register_trade."""
    is_long = "LONG" in info.get("type", "")
    confidence_str = info.get("confidence", "HIGH")
    conf_float = 0.85 if confidence_str == "VERY_HIGH" else 0.70
    strength = 80 if confidence_str == "VERY_HIGH" else 65
    tp_levels = info.get("take_profits", [])
    tp1 = tp_levels[0]["price"] if tp_levels else None
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="pivot_reversal"))
    return SimpleNamespace(
        symbol=info.get("symbol", ""),
        entry_price=info.get("entry_price"),
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=info.get("stop_loss"),
        take_profit=tp1,
        overall_strength=strength,
        confidence=conf_float,
        timestamp=datetime.now(),
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        metadata={},
    )


async def start_monitoring(bot, message):
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


async def _prefetch_pivots(bot):
    """Прогревает кеш пивотов для всех пар параллельно (≤20 одновременно)."""
    pairs = bot.monitored_pairs
    sem = asyncio.Semaphore(20)

    async def _fetch_one(sym):
        async with sem:
            try:
                await bot.pivot_calculator.get_multi_timeframe_pivots(sym, bot.data_collector)
            except Exception:
                pass

    logger.info("Прогрев кеша пивотов для %d пар...", len(pairs))
    await asyncio.gather(*[_fetch_one(sym) for sym in pairs])
    logger.info("Кеш пивотов прогрет.")


async def monitor_market(bot):
    try:
        asyncio.create_task(bot.data_collector.fetch_candles())
        while bot.is_monitoring:
            await check_anomalies(bot)
            await check_wt_signals(bot)
            await check_mtf_signals(bot)
            await check_mtf_alerts(bot)
            await check_trend_signals(bot)
            await check_divergences(bot)
            await check_pivot_reversals(bot)
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("Мониторинг остановлен")
        raise
    except Exception:
        logger.exception("Ошибка в monitor_market")


async def check_anomalies(bot):
    for sym in bot.monitored_pairs:
        try:
            df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=30)
            if df_15m is None or df_15m.empty:
                continue
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


async def check_wt_signals(bot):
    for sym in bot.monitored_pairs:
        try:
            df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=150)
            if df_15m is None or df_15m.empty:
                continue
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


async def check_mtf_signals(bot):
    for sym in bot.monitored_pairs:
        try:
            df_1h  = await bot.data_collector.get_ohlcv(sym, "1h",  limit=100)
            df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=100)
            df_3m  = await bot.data_collector.get_ohlcv(sym, "3m",  limit=100)
            if df_1h is None or df_1h.empty or df_15m is None or df_15m.empty:
                continue
            signals = await _check_mtf_signals(sym, df_1h, df_15m, df_3m)
            for sig in signals:
                info = sig.data or {}
                raw_text = mtf_message(sym, info)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_signal")
                bot.signal_counters["mtf_signal"] += 1
                bot.signal_counters["total"] += 1
        except Exception:
            logger.exception("Ошибка check_mtf_signals для %s", sym)


async def check_mtf_alerts(bot):
    for sym in bot.monitored_pairs:
        try:
            snapshot = await collect_mtf_data(sym, bot.data_collector)
            if not snapshot:
                continue
            is_alert, sig = check_mtf_alert(snapshot)
            if is_alert:
                raw_text = mtf_alert_message(sym, snapshot, sig)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_alert")
                bot.signal_counters["mtf_alert"] += 1
                bot.signal_counters["total"] += 1
        except Exception:
            logger.exception("Ошибка check_mtf_alerts для %s", sym)


async def check_trend_signals(bot):
    for sym in bot.monitored_pairs:
        try:
            is_sig, info = await check_trend_following_signal(
                sym, bot.data_collector, bot.divergence_detector, bot.pivot_calculator
            )
            if is_sig:
                raw_text = trend_signal_message(sym, info)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "trend_signal")
                bot.signal_counters["trend_signal"] += 1
                bot.signal_counters["total"] += 1
                logger.info("[%s] Тренд-сигнал: %s", sym, info.get("pattern"))
        except Exception:
            logger.exception("Ошибка check_trend_signals для %s", sym)


async def check_divergences(bot):
    for sym in bot.monitored_pairs:
        for tf in ("15m", "1h"):
            try:
                has_div, div_info = await bot.divergence_detector.detect_divergence(
                    sym, bot.data_collector, timeframe=tf
                )
                if has_div:
                    raw_text = divergence_message(sym, div_info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "divergence")
                    bot.signal_counters["divergence"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Дивергенция на %s: %s", sym, tf, div_info.get("type"))
                    break
            except Exception:
                logger.exception("Ошибка check_divergences для %s %s", sym, tf)


async def check_pivot_reversals(bot):
    for sym in bot.monitored_pairs:
        try:
            has_signal, info = await check_pivot_level_signal(
                sym, bot.data_collector, bot.pivot_calculator
            )
            if has_signal:
                raw_text = pivot_level_signal_message(sym, info)
                pivot_rec = _make_pivot_recommendation(info)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "pivot_reversal", fallback_rec=pivot_rec)
                bot.signal_counters["pivot_reversal"] += 1
                bot.signal_counters["total"] += 1
                logger.info("[%s] Вход от уровня: %s R:R=%.1f", sym, info.get("level"), info.get("rr_ratio", 0))
        except Exception:
            logger.exception("Ошибка check_pivot_reversals для %s", sym)


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


def _is_duplicate_signal(bot, symbol: str, signal_type: str) -> bool:
    """Возвращает True если тот же signal_type по той же паре уже был < dedup_minutes назад."""
    minutes = bot.config.get("signal_quality.dedup_minutes", 30)
    if minutes <= 0:
        return False
    key = (symbol, signal_type)
    last_ts = bot._last_signal.get(key)
    if last_ts and (datetime.now() - last_ts).total_seconds() < minutes * 60:
        logger.debug("[%s] Дубликат %s — пропущен (%d мин)", symbol, signal_type, minutes)
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


async def _broadcast_intelligence_alert(bot, symbol: str, raw_text: str, signal_type: str, fallback_rec=None):
    # Фильтры качества сигналов (Этап 5.1)
    if hasattr(bot, "_last_signal") and _is_duplicate_signal(bot, symbol, signal_type):
        return
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol):
        return

    recommendation = None
    try:
        recommendation = await bot.trading_intelligence.analyze_symbol(symbol)
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    # Этап 5.2: BTC-корреляционный фильтр
    btc_regime = await _get_btc_regime(bot)
    if btc_regime == "HIGH_VOL":
        logger.info("[%s] Фильтр BTC HIGH_VOL — сигнал пропущен", symbol)
        return
    if recommendation and btc_regime:
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        if btc_regime == "TREND_UP" and direction_val == "SHORT":
            logger.info("[%s] Фильтр BTC TREND_UP vs SHORT — пропущен", symbol)
            return
        if btc_regime == "TREND_DOWN" and direction_val == "LONG":
            logger.info("[%s] Фильтр BTC TREND_DOWN vs LONG — пропущен", symbol)
            return

    min_strength = bot.config.get("signal_quality.min_strength", 40)
    is_actionable = (
        recommendation is not None
        and recommendation.overall_strength >= min_strength
        and getattr(recommendation, "action", "WATCH") in ("BUY", "SELL")
        and getattr(recommendation, "direction", None) is not None
        and recommendation.direction.value != "NEUTRAL"
    )

    text = raw_text
    if recommendation:
        try:
            text = format_intelligence_message(recommendation)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text
        if is_actionable:
            text = text.rstrip() + "\n─────────────\n💾 <i>Сделка зарегистрирована в симуляторе</i>"

    await broadcast_with_subscription_check(bot, text, signal_type)

    if is_actionable:
        try:
            await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector)
        except Exception as e:
            logger.debug("TradeSimulator register_trade для %s (%s): %s", symbol, signal_type, e)
    elif recommendation:
        reason = []
        if recommendation.overall_strength < min_strength:
            reason.append(f"strength={recommendation.overall_strength:.1f}<{min_strength}")
        if getattr(recommendation, "action", "WATCH") not in ("BUY", "SELL"):
            reason.append(f"action={getattr(recommendation, 'action', '?')}")
        if getattr(recommendation, "direction", None) is None or recommendation.direction.value == "NEUTRAL":
            reason.append("direction=NEUTRAL")
        logger.info("[%s] Сделка не зарегистрирована: %s", symbol, ", ".join(reason))
    elif fallback_rec is not None:
        try:
            await bot.trade_simulator.register_trade_async(fallback_rec, bot.data_collector)
            logger.info("TradeSimulator fallback: зарегистрирован %s из pivot info", symbol)
        except Exception as e:
            logger.debug("TradeSimulator fallback для %s: %s", symbol, e)


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


async def trade_tracker_loop(bot):
    # Параметры TSL из конфига
    use_tsl = bot.config.get("trading.use_tsl", True)
    tsl_activation_r = bot.config.get("trading.tsl_activation_r", 1.0)

    while True:
        try:
            await asyncio.sleep(300)
            closed = await bot.trade_simulator.check_open_trades_with_tsl(
                bot.data_collector,
                use_tsl=use_tsl,
                tsl_activation_r=tsl_activation_r
            )
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("TradeSimulator loop: %s", e)


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
