"""
Фоновый мониторинг рынка: цикл проверок и рассылка сигналов.
Все функции принимают bot (TradingAlertBot) первым аргументом.
"""
import asyncio
import logging
from datetime import datetime

from core.message_builder import anomaly_message, wt_message, mtf_message
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import divergence_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from core.keyboards import main_menu

logger = logging.getLogger(__name__)


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

    pairs = await bot.data_collector.load_markets()
    if not pairs:
        await message.answer("❌ Не удалось загрузить пары.", reply_markup=main_menu())
        return

    bot.monitored_pairs = pairs
    bot.is_monitoring = True
    bot.start_time = datetime.now()
    bot.monitor_task = asyncio.create_task(monitor_market(bot))

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
    found = []
    for sym in bot.monitored_pairs:
        try:
            is_anom, info = bot.detector.check_spike(sym, bot.data_collector)
            if is_anom:
                found.append((sym, info))
                bot.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                bot.signal_counters["anomaly"] += 1
                bot.signal_counters["total"] += 1
        except Exception:
            logger.exception("Ошибка check_spike для %s", sym)
    for sym, info in found:
        raw_text = anomaly_message(sym, info)
        await _broadcast_intelligence_alert(bot, sym, raw_text, "anomaly")


async def check_wt_signals(bot):
    for sym in bot.monitored_pairs:
        try:
            is_sig, info = await bot.detector.check_wt_signal(sym, bot.data_collector)
            if is_sig:
                logger.info("WT сигнал обнаружен для %s: %s", sym, info.get("type", "N/A"))
                info["volume_details"] = list(bot.data_collector.volume_history.get(sym, []))[-5:]
                raw_text = wt_message(sym, info)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "wt_signal")
                bot.signal_counters["wt_signal"] += 1
                bot.signal_counters["total"] += 1
        except Exception:
            logger.exception("Ошибка check_wt_signal для %s", sym)


async def check_mtf_signals(bot):
    for sym in bot.monitored_pairs:
        try:
            is_sig, info = await bot.detector.check_mtf_signal(sym, bot.data_collector)
            if is_sig:
                info["volume_details"] = list(bot.data_collector.volume_history.get(sym, []))[-5:]
                raw_text = mtf_message(sym, info)
                await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_signal")
                bot.signal_counters["mtf_signal"] += 1
                bot.signal_counters["total"] += 1
        except Exception:
            logger.exception("Ошибка check_mtf_signal для %s", sym)


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
                await _broadcast_intelligence_alert(bot, sym, raw_text, "pivot_reversal")
                bot.signal_counters["pivot_reversal"] += 1
                bot.signal_counters["total"] += 1
                logger.info("[%s] Вход от уровня: %s R:R=%.1f", sym, info.get("level"), info.get("rr_ratio", 0))
        except Exception:
            logger.exception("Ошибка check_pivot_reversals для %s", sym)


async def _broadcast_intelligence_alert(bot, symbol: str, raw_text: str, signal_type: str):
    recommendation = None
    try:
        recommendation = await bot.trading_intelligence.analyze_symbol(symbol)
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    text = raw_text
    if recommendation:
        try:
            text = format_intelligence_message(recommendation)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text

    await broadcast_with_subscription_check(bot, text, signal_type)

    if recommendation:
        try:
            await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector)
        except Exception as e:
            logger.debug("TradeSimulator register_trade для %s (%s): %s", symbol, signal_type, e)


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
    while True:
        try:
            await asyncio.sleep(300)
            closed = await bot.trade_simulator.check_open_trades(bot.data_collector)
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("TradeSimulator loop: %s", e)
