"""
Действия меню AI-анализа — standalone-функции вместо методов MenuHandler.
"""
import logging
from datetime import datetime

from aiogram.types import Message
from aiogram.fsm.context import FSMContext


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
    """ML предсказания: статус моделей + P(win) из OutcomePredictor."""
    ti = bot.trading_intelligence
    lines = ["🤖 <b>ML Предсказания</b>\n"]

    # MLPredictor — точность моделей
    if hasattr(ti, "ml_predictor") and ti.ml_predictor:
        perf = ti.ml_predictor.get_model_performance()
        if perf:
            lines.append("<b>📊 Модели направления цены:</b>")
            for k, v in sorted(perf.items()):
                lines.append(f"  {k}: acc={v.accuracy:.3f} f1={v.f1_score:.3f} (n={v.training_samples})")
        else:
            lines.append("⚠️ MLPredictor: модели не обучены")
    else:
        lines.append("⚠️ MLPredictor не инициализирован")

    lines.append("")

    # OutcomePredictor — P(win)
    if hasattr(ti, "outcome_predictor") and ti.outcome_predictor:
        info = ti.outcome_predictor.info() if hasattr(ti.outcome_predictor, "info") else {}
        if info.get("trained"):
            lines.append("<b>🎯 P(win) модель (OutcomePredictor):</b>")
            lines.append(f"  CV AUC: {info.get('cv_auc', 'N/A'):.3f}")
            lines.append(f"  Обучена на: {info.get('n_samples', '?')} сделках")
            lines.append(f"  Классов: {info.get('n_classes', '?')}")
        else:
            lines.append("⚠️ OutcomePredictor: недостаточно данных (нужно 20+ закрытых сделок)")
    else:
        lines.append("⚠️ OutcomePredictor не инициализирован")

    lines.append("")

    # Адаптивные веса сигналов
    if hasattr(ti, "signal_weights") and ti.signal_weights:
        lines.append("<b>⚖️ Адаптивные веса сигналов:</b>")
        base = getattr(ti, "_base_signal_weights", {})
        for sig, w in sorted(ti.signal_weights.items(), key=lambda x: -x[1]):
            base_w = base.get(sig, w)
            delta = w - base_w
            sign = f"+{delta:.3f}" if delta >= 0 else f"{delta:.3f}"
            lines.append(f"  {sig}: {w:.3f} ({sign})")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def show_statistics(bot, message: Message) -> None:
    """Показ статистики бота."""
    uptime = "N/A"
    if hasattr(bot, "start_time") and bot.start_time:
        delta = datetime.now() - bot.start_time
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        uptime = f"{delta.days}д {hours}ч {minutes}м"
    user_id = message.from_user.id
    sub_info = bot.subscription_manager.get_subscription_info(user_id)
    lines = [
        "📊 <b>СТАТИСТИКА БОТА</b>",
        "",
        f"{'✅ Активен' if bot.is_monitoring else '⏹ Остановлен'}",
        f"⏱ Время работы: {uptime}",
        "",
        "<b>📈 Мониторинг:</b>",
        f"• Отслеживаемых пар: {len(bot.monitored_pairs)}",
        f"• Подписчиков: {len(bot.subscribers)}",
        "",
        "<b>💎 Ваша подписка:</b>",
        f"• Уровень: {sub_info['tier']}",
        f"• Сигналов сегодня: {sub_info['signals_today']}/{sub_info['signals_limit']}",
        "",
        "<b>🎯 Обнаружено сигналов:</b>",
        f"• 🚨 Аномалий: {bot.signal_counters['anomaly']}",
        f"• 📊 WT: {bot.signal_counters['wt_signal']}",
        f"• 🔄 MTF: {bot.signal_counters['mtf_signal']}",
        f"• 📈 Тренд: {bot.signal_counters['trend_signal']}",
        f"• 💎 Дивергенций: {bot.signal_counters['divergence']}",
        f"• 🔄 Разворотов: {bot.signal_counters['pivot_reversal']}",
        f"• <b>📌 Всего: {bot.signal_counters['total']}</b>",
    ]
    await message.answer("\n".join(lines))


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
    from bot.monitoring import stop_monitoring
    await stop_monitoring(bot, message)


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
            await message.answer("🔄 Запускаю переобучение ML моделей (30 дней истории)...")
            result = await ti.train_ml_models(training_period_days=30)
            if result:
                perf = ti.ml_predictor.get_model_performance()
                lines = ["✅ <b>ML модели переобучены</b>"]
                for k, v in sorted(perf.items()):
                    if "price_direction" in k:
                        lines.append(f"  {k.split('_')[-1]}: acc={v.accuracy:.3f}")
                await message.answer("\n".join(lines), parse_mode="HTML")
            else:
                await message.answer("⚠️ Переобучение не выполнено (недостаточно данных)")
        except Exception:
            logger.exception("Ошибка переобучения ML моделей")
            await message.answer("❌ Ошибка переобучения")
    else:
        await message.answer("🔄 ML модуль не инициализирован")


async def show_ml_statistics(bot, message: Message) -> None:
    """Показ ML-статистики."""
    ti = bot.trading_intelligence
    if hasattr(ti, "ml_predictor") and ti.ml_predictor:
        perf = ti.ml_predictor.get_model_performance()
        if perf:
            lines = ["📚 <b>ML статистика</b>"]
            for k, v in sorted(perf.items()):
                lines.append(f"<b>{k}</b>: acc={v.accuracy:.3f} f1={v.f1_score:.3f} (n={v.training_samples})")
            await message.answer("\n".join(lines), parse_mode="HTML")
        else:
            await message.answer("📚 ML модели ещё не обучены. Используйте '🔄 Обновить модели'.")
    else:
        await message.answer("📚 ML модуль не инициализирован")


async def show_ai_settings(bot, message: Message) -> None:
    """Показ настроек AI."""
    await message.answer("⚙️ <b>Настройки AI</b>\n\nИспользуются настройки по умолчанию из config.yaml")
