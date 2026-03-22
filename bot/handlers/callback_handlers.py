"""
Обработчики callback_query (inline-кнопки).
"""
import logging

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

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

            if data.startswith("dash:"):
                await _handle_dashboard_callback(callback_query, bot)
            elif data.startswith("ai_"):
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


async def _handle_dashboard_callback(callback_query: CallbackQuery, bot):
    """Обработчик всех dash:* callback-ов."""
    from bot.menus.dashboard import (
        dashboard_status_text, dashboard_main_kb,
        dashboard_toggles_text, dashboard_toggles_kb,
        dashboard_params_text, dashboard_params_kb,
        _TOGGLES,
    )
    data = callback_query.data
    msg = callback_query.message

    if data == "dash:main" or data == "dash:refresh":
        text = dashboard_status_text(bot)
        kb = dashboard_main_kb()
        try:
            await msg.edit_text(text, reply_markup=kb)
        except Exception:
            await msg.answer(text, reply_markup=kb)
        await callback_query.answer("Обновлено" if data == "dash:refresh" else "")

    elif data == "dash:toggles":
        text = dashboard_toggles_text(bot)
        kb = dashboard_toggles_kb(bot)
        await msg.edit_text(text, reply_markup=kb)
        await callback_query.answer()

    elif data == "dash:params":
        text = dashboard_params_text(bot)
        kb = dashboard_params_kb(bot)
        await msg.edit_text(text, reply_markup=kb)
        await callback_query.answer()

    elif data.startswith("dash:t:"):
        # Toggle boolean config key
        key = data[7:]  # after "dash:t:"
        from bot.menus.dashboard import _TOGGLE_DEFAULTS
        current = bot.config.get(key, _TOGGLE_DEFAULTS.get(key, False))
        new_val = not current
        bot.config.set(key, new_val)
        try:
            bot.config.save()
        except Exception:
            pass
        text = dashboard_toggles_text(bot)
        kb = dashboard_toggles_kb(bot)
        await msg.edit_text(text, reply_markup=kb)
        label = key.split(".")[-1]
        await callback_query.answer(f"{label} = {'ON' if new_val else 'OFF'}")

    elif data.startswith("dash:btc:"):
        mode = data[9:]  # after "dash:btc:"
        if mode in ("shadow", "block", "off"):
            bot.config.set("signal_quality.btc_filter_mode", mode)
            try:
                bot.config.save()
            except Exception:
                pass
        text = dashboard_toggles_text(bot)
        kb = dashboard_toggles_kb(bot)
        await msg.edit_text(text, reply_markup=kb)
        await callback_query.answer(f"BTC filter = {mode}")

    elif data.startswith("dash:p:"):
        # Param adjust: dash:p:key:+step or dash:p:key:-step
        parts = data[7:].rsplit(":", 1)  # key, delta
        if len(parts) == 2:
            key, delta_str = parts
            try:
                delta = int(delta_str)
            except ValueError:
                delta = float(delta_str)
            current = bot.config.get(key, 0)
            new_val = current + delta
            # Clamp
            from bot.menus.dashboard import _PARAMS
            for pk, pl, pd, pmn, pmx, ps in _PARAMS:
                if pk == key:
                    new_val = max(pmn, min(pmx, new_val))
                    break
            bot.config.set(key, type(current)(new_val) if isinstance(current, int) else new_val)
            try:
                bot.config.save()
            except Exception:
                pass
        text = dashboard_params_text(bot)
        kb = dashboard_params_kb(bot)
        await msg.edit_text(text, reply_markup=kb)
        await callback_query.answer(f"{key.split('.')[-1]} = {new_val}")

    elif data == "dash:diag":
        await callback_query.answer("Запуск диагностики...")
        try:
            from core.selftest import run_selftest
            report = await run_selftest(config=bot.config, bot=bot)
            text = report.summary_text()
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Перезапустить", callback_data="dash:diag")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="dash:main")],
            ])
            try:
                await msg.edit_text(text, reply_markup=kb)
            except Exception:
                await msg.answer(text, reply_markup=kb)
        except Exception as e:
            await msg.edit_text(
                f"❌ Ошибка диагностики: {e}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="dash:main")],
                ]),
            )

    elif data == "dash:noop":
        await callback_query.answer()


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
