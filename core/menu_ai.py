"""
Действия меню AI-анализа — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from core.keyboards import ai_analysis_inline_menu

logger = logging.getLogger(__name__)


async def handle_intelligence_analysis(bot, message: Message, state: FSMContext) -> None:
    """Запуск комплексного AI-анализа: переводит в FSM-состояние ввода символа."""
    await message.answer(
        "🧠 <b>Комплексный AI анализ</b>\n\n"
        "Введите символ для анализа (например: BTC, ETH, SOL):"
    )
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol)


async def handle_ml_predictions(bot, message: Message, state: FSMContext) -> None:
    """Запуск ML предсказаний — показывает inline-меню."""
    await message.answer(
        "🤖 <b>ML Предсказания</b>\n\n"
        "Машинное обучение для прогнозирования движения цен.\n"
        "Выберите тип предсказания:",
        reply_markup=ai_analysis_inline_menu()
    )


async def show_statistics(bot, message: Message) -> None:
    """Делегирует показ статистики в cmd_stats."""
    await bot.cmd_stats(message)


async def show_help(bot, message: Message) -> None:
    """Показ справки."""
    help_text = (
        "🤖 <b>Crypto Volume Bot - Справка</b>\n\n"
        "<b>📊 Основные функции:</b>\n"
        "• Мониторинг криптовалютных рынков\n"
        "• 8 типов технических сигналов\n"
        "• AI-анализ с машинным обучением\n"
        "• Управление рисками\n"
        "• Исторический анализ\n\n"
        "<b>🧠 AI Анализ:</b>\n"
        "• Комплексные торговые рекомендации\n"
        "• ML предсказания направления цены\n"
        "• Автоматическое управление рисками\n"
        "• Анализ эффективности\n\n"
        "<b>📈 Типы сигналов:</b>\n"
        "• Аномалии объема\n"
        "• Wavetrend сигналы\n"
        "• MTF анализ\n"
        "• Тренд сигналы\n"
        "• Дивергенции\n"
        "• Пивотные уровни\n\n"
        "<b>💎 Подписки:</b>\n"
        "• Free: 5 сигналов/день\n"
        "• Basic: $9.99/месяц\n"
        "• Premium: $29.99/месяц\n"
        "• Pro: $99.99/месяц\n\n"
        "<b>🔧 Команды:</b>\n"
        "• /start - Главное меню\n"
        "• /intelligence SYMBOL - AI анализ\n"
        "• /pivots - Пивотные уровни\n"
        "• /stats - Статистика\n\n"
        "Используйте меню для навигации по всем функциям!"
    )
    await message.answer(help_text)


async def handle_stop_monitoring(bot, message: Message) -> None:
    """Остановка мониторинга."""
    await bot.stop_monitoring(message)


async def handle_find_pair(bot, message: Message, state: FSMContext) -> None:
    """Поиск пары: переводит в FSM-состояние поиска символа."""
    await message.answer("🔍 Введите символ для поиска (например: BTC):")
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol_search)


async def show_active_signals(bot, message: Message) -> None:
    """Показ активных сигналов из recent_anomalies."""
    if not bot.recent_anomalies:
        await message.answer("📈 Активных сигналов нет")
        return
    lines = ["📈 <b>Активные сигналы</b>"]
    for sym, data in list(bot.recent_anomalies.items())[:10]:
        ts = data.get("timestamp", "N/A")
        lines.append(f"• {sym}: {ts}")
    await message.answer("\n".join(lines))


async def handle_pair_analysis(bot, message: Message, state: FSMContext) -> None:
    """Анализ пары: переводит в FSM-состояние ввода символа."""
    await message.answer("📊 Введите символ для анализа пары (например: BTC, ETH, SOL):")
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol)


async def handle_trading_levels(bot, message: Message, state: FSMContext) -> None:
    """Торговые уровни: переводит в FSM-состояние ввода символа."""
    await message.answer("🎯 Введите символ для расчета торговых уровней (например: BTC, ETH, SOL):")
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol)


async def show_ai_performance(bot, message: Message) -> None:
    """Показ эффективности AI-анализа."""
    ti = bot.trading_intelligence
    if hasattr(ti, "ml_predictor"):
        stats = getattr(ti.ml_predictor, "performance_stats", {})
        lines = ["📈 <b>Эффективность AI</b>"]
        lines.append(f"Точность: {stats.get('accuracy', 'N/A')}")
        lines.append(f"Сигналов обработано: {stats.get('signals_processed', 0)}")
        await message.answer("\n".join(lines))
    else:
        await message.answer("📈 AI модуль не инициализирован")


async def handle_retrain_models(bot, message: Message) -> None:
    """Переобучение ML-моделей."""
    ti = bot.trading_intelligence
    if hasattr(ti, "ml_predictor") and ti.ml_predictor:
        try:
            if hasattr(ti.ml_predictor, "retrain_models"):
                await message.answer("🔄 Начинаю переобучение ML моделей...")
                result = await ti.ml_predictor.retrain_models()
                if result:
                    await message.answer("✅ ML модели успешно переобучены!")
                else:
                    await message.answer("⚠️ Переобучение моделей завершилось с предупреждениями")
            else:
                await message.answer("🔄 ML модуль не поддерживает переобучение. Модели обновляются автоматически при анализе.")
        except Exception:
            logger.exception("Ошибка переобучения ML моделей")
            await message.answer("❌ Ошибка переобучения")
    else:
        await message.answer("🔄 ML модуль не инициализирован")


async def show_ml_statistics(bot, message: Message) -> None:
    """Показ ML-статистики."""
    ti = bot.trading_intelligence
    if hasattr(ti, "ml_predictor"):
        stats = getattr(ti.ml_predictor, "model_stats", {})
        lines = ["📚 <b>ML статистика</b>"]
        for key, val in stats.items():
            lines.append(f"{key}: {val}")
        await message.answer("\n".join(lines) if lines else "📚 ML статистика недоступна")
    else:
        await message.answer("📚 ML модуль не инициализирован")


async def show_ai_settings(bot, message: Message) -> None:
    """Показ настроек AI."""
    await message.answer("⚙️ <b>Настройки AI</b>\n\nИспользуются настройки по умолчанию из config.yaml")
