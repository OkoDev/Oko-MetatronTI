"""
Обработчики callback_query (inline-кнопки).
"""
import logging

from aiogram import Router
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


def get_router(bot) -> Router:
    router = Router()

    @router.callback_query()
    async def handle_callback_query(callback_query: CallbackQuery):
        user_id = callback_query.from_user.id
        username = callback_query.from_user.username or "Unknown"
        data = callback_query.data

        logger.info("🔍 [CALLBACK] Получен callback от %s (%s): '%s'", username, user_id, data)

        try:
            logger.debug(
                "📝 [CALLBACK] Детали: user_id=%s, username=%s, data='%s', message_id=%s",
                user_id, username, data, callback_query.message.message_id,
            )

            if data.startswith("ai_"):
                await _handle_ai_callback(callback_query)
            elif data.startswith("signal_"):
                await _handle_signal_callback(callback_query)
            elif data.startswith("risk_"):
                await _handle_risk_callback(callback_query)
            elif data.startswith("history_"):
                await _handle_history_callback(callback_query)
            elif data.startswith("sub_"):
                await _handle_subscription_callback(callback_query)
            elif data.startswith("select_symbol_"):
                await _handle_symbol_selection_callback(callback_query)
            elif data.startswith("timeframe_"):
                await _handle_timeframe_callback(callback_query)
            elif data.startswith("confirm_") or data.startswith("cancel_"):
                await _handle_confirmation_callback(callback_query)
            else:
                logger.warning("❌ [CALLBACK] Неизвестный callback: '%s' от %s", data, username)
                await callback_query.answer("❌ Неизвестная команда")

        except Exception:
            logger.exception("💥 [CALLBACK] Ошибка при обработке callback '%s' от %s", data, username)
            await callback_query.answer("❌ Произошла ошибка при обработке команды")

    return router


async def _handle_ai_callback(callback_query: CallbackQuery):
    data = callback_query.data
    username = callback_query.from_user.username or "Unknown"
    logger.info("🧠 [AI_CALLBACK] Обработка AI callback '%s' для %s", data, username)

    messages = {
        "ai_intelligence": ("🧠 Запуск комплексного анализа...", "🧠 <b>Комплексный AI анализ</b>\n\nВведите символ для анализа (например: BTC, ETH, SOL):"),
        "ai_ml_predictions": ("🤖 Запуск ML предсказаний...", "🤖 <b>ML Предсказания</b>\n\nМашинное обучение для прогнозирования движения цен."),
        "ai_performance": ("📊 Анализ эффективности AI...", "📊 <b>Эффективность AI</b>\n\nАнализ производительности машинного обучения..."),
        "ai_retrain": ("🔄 Обновление ML моделей...", "🔄 <b>Обновление моделей</b>\n\nПереобучение ML моделей на новых данных..."),
        "ai_ml_stats": ("📚 ML статистика...", "📚 <b>ML Статистика</b>\n\nСтатистика работы машинного обучения..."),
        "ai_settings": ("⚙️ Настройки AI...", "⚙️ <b>Настройки AI</b>\n\nКонфигурация параметров машинного обучения..."),
    }
    if data in messages:
        toast, text = messages[data]
        await callback_query.answer(toast)
        await callback_query.message.answer(text)
    else:
        await callback_query.answer("❌ Неизвестная AI команда")


async def _handle_signal_callback(callback_query: CallbackQuery):
    data = callback_query.data
    logger.info("📈 [SIGNAL_CALLBACK] Обработка '%s' для %s", data, callback_query.from_user.username or "Unknown")
    await callback_query.answer(f"📈 Обработка сигнала: {data}")


async def _handle_risk_callback(callback_query: CallbackQuery):
    data = callback_query.data
    logger.info("🛡️ [RISK_CALLBACK] Обработка '%s' для %s", data, callback_query.from_user.username or "Unknown")
    await callback_query.answer(f"🛡️ Управление рисками: {data}")


async def _handle_history_callback(callback_query: CallbackQuery):
    data = callback_query.data
    logger.info("📚 [HISTORY_CALLBACK] Обработка '%s' для %s", data, callback_query.from_user.username or "Unknown")
    await callback_query.answer(f"📚 Исторический анализ: {data}")


async def _handle_subscription_callback(callback_query: CallbackQuery):
    data = callback_query.data
    logger.info("💎 [SUBSCRIPTION_CALLBACK] Обработка '%s' для %s", data, callback_query.from_user.username or "Unknown")
    await callback_query.answer(f"💎 Подписка: {data}")


async def _handle_symbol_selection_callback(callback_query: CallbackQuery):
    symbol = callback_query.data.replace("select_symbol_", "")
    logger.info("🎯 [SYMBOL_CALLBACK] Выбран символ '%s' для %s", symbol, callback_query.from_user.username or "Unknown")
    await callback_query.answer(f"🎯 Выбран символ: {symbol}")


async def _handle_timeframe_callback(callback_query: CallbackQuery):
    timeframe = callback_query.data.replace("timeframe_", "")
    logger.info("⏰ [TIMEFRAME_CALLBACK] Выбран таймфрейм '%s'", timeframe)
    await callback_query.answer(f"⏰ Выбран таймфрейм: {timeframe}")


async def _handle_confirmation_callback(callback_query: CallbackQuery):
    data = callback_query.data
    logger.info("✅ [CONFIRMATION_CALLBACK] Обработка '%s'", data)
    await callback_query.answer(f"✅ Подтверждение: {data}")
