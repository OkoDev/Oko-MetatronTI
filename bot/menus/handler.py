"""
Обработчик расширенного меню бота.
Тонкий диспетчер — делегирует действия в доменные модули menu_*.
"""
import logging

from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.keyboards import (
    main_menu, monitoring_menu, ai_analysis_menu, signals_menu,
    pivots_menu, risk_management_menu, history_menu,
    subscriptions_menu, settings_menu,
)
from bot.menus.ai import (
    handle_intelligence_analysis, handle_ml_predictions, show_statistics,
    show_help, handle_find_pair, show_active_signals,
    handle_pair_analysis, handle_trading_levels, show_ai_performance,
    handle_retrain_models, show_ml_statistics, show_ai_settings,
)
from bot.menus.signals import (
    show_anomaly_signals, show_wt_signals,
    show_trend_signals, show_divergence_signals, show_pivot_signals,
    show_all_signals, handle_signal_search,
)
from bot.menus.pivots import (
    show_pivot_reversals, show_key_levels, show_pivot_analysis,
    show_pivots_request, show_check_pivot_request,
)
from bot.menus.risk import (
    show_risk_profile, show_active_positions, show_position_sizes,
    show_risk_reward_ratio, show_risk_warnings,
    show_risk_statistics, show_risk_settings,
)
from bot.menus.history import (
    show_performance_analysis, show_performance_trend, show_analysis_by_type,
    show_signal_history, show_improvement_recommendations, show_detailed_statistics,
    export_history_data,
)
from bot.menus.subscriptions import (
    show_subscription_limits, show_usage_statistics,
    show_payment_history, show_subscription_settings,
    cmd_my_subscription, cmd_buy_subscription, cmd_subscribe, cmd_unsubscribe,
)
from bot.menus.settings import (
    show_general_settings, show_analysis_settings,
)

logger = logging.getLogger(__name__)


class MenuHandler:
    """Тонкий диспетчер расширенного меню."""

    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.current_menu = "main"
        self.menu_stack = []

        self.menu_handlers = {
            "main": self.handle_main_menu_buttons,
            "monitoring": self.handle_monitoring_menu_buttons,
            "ai_analysis": self.handle_ai_analysis_menu_buttons,
            "signals": self.handle_signals_menu_buttons,
            "pivots": self.handle_pivots_menu_buttons,
            "risk_management": self.handle_risk_management_menu_buttons,
            "history": self.handle_history_menu_buttons,
            "subscriptions": self.handle_subscriptions_menu_buttons,
            "settings": self.handle_settings_menu_buttons,
        }

    # ------------------------------------------------------------------
    # Диспетчеры меню
    # ------------------------------------------------------------------

    async def handle_main_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок главного меню."""
        text = message.text
        username = message.from_user.username or "Unknown"
        logger.info("🔍 [MENU] Главное меню - %s нажал: '%s'", username, text)
        try:
            if text == "🟢 Мониторинг":
                await self._show_monitoring_menu(message)
            elif text == "🧠 AI Анализ":
                await self._show_ai_analysis_menu(message)
            elif text == "📊 Статистика":
                await show_statistics(self.bot, message)
            elif text == "📈 Сигналы":
                await self._show_signals_menu(message)
            elif text == "🎯 Пивоты":
                await self._show_pivots_menu(message)
            elif text == "🛡️ Риски":
                await self._show_risk_management_menu(message)
            elif text == "📚 История":
                await self._show_history_menu(message)
            elif text == "💎 Подписки":
                await self._show_subscriptions_menu(message)
            elif text == "⚙️ Настройки":
                await self._show_settings_menu(message)
            elif text == "📟 Дашборд":
                await self._show_dashboard(message)
            elif text == "ℹ️ Помощь":
                await show_help(self.bot, message)
            else:
                logger.warning("[MENU] Неизвестная кнопка главного меню: '%s' от %s", text, username)
                await message.answer("Неизвестная команда. Используйте меню.")
        except Exception:
            logger.exception("[MENU] Ошибка в обработке главного меню для %s", username)
            await message.answer("Произошла ошибка при обработке команды. Попробуйте еще раз.")

    async def handle_monitoring_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню мониторинга."""
        from bot.monitoring import start_monitoring, stop_monitoring
        text = message.text
        username = message.from_user.username or "Unknown"
        logger.info("🔍 [MENU] Мониторинг - %s нажал: '%s'", username, text)
        try:
            if text == "🟢 Запустить мониторинг":
                await start_monitoring(self.bot, message)
            elif text == "⏹ Остановить мониторинг":
                await stop_monitoring(self.bot, message)
            elif text == "📊 Статистика мониторинга":
                await show_statistics(self.bot, message)
            elif text == "🏆 ТОП-10 по объему":
                await self._show_top_volume(message)
            elif text == "🔍 Найти пару":
                await handle_find_pair(self.bot, message, state)
            elif text == "📈 Активные сигналы":
                await show_active_signals(self.bot, message)
            elif text == "⬅️ Назад в главное меню":
                await self._show_main_menu(message)
            else:
                logger.warning("[MENU] Неизвестная кнопка мониторинга: '%s' от %s", text, username)
                await message.answer("Неизвестная команда в меню мониторинга.")
        except Exception:
            logger.exception("[MENU] Ошибка в обработке мониторинга для %s", username)
            await message.answer("Произошла ошибка при обработке команды мониторинга.")

    async def handle_ai_analysis_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню AI анализа."""
        text = message.text
        if text == "🧠 Комплексный анализ":
            await handle_intelligence_analysis(self.bot, message, state)
        elif text == "🤖 ML предсказания":
            await handle_ml_predictions(self.bot, message, state)
        elif text == "📊 Анализ пары":
            await handle_pair_analysis(self.bot, message, state)
        elif text == "🎯 Торговые уровни":
            await handle_trading_levels(self.bot, message, state)
        elif text == "📈 Эффективность":
            await show_ai_performance(self.bot, message)
        elif text == "🔄 Обновить модели":
            await handle_retrain_models(self.bot, message)
        elif text == "📚 ML статистика":
            await show_ml_statistics(self.bot, message)
        elif text == "⚙️ Настройки AI":
            await show_ai_settings(self.bot, message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню AI анализа.")

    async def handle_signals_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню сигналов."""
        text = message.text
        if text == "🚨 Аномалии":
            await show_anomaly_signals(self.bot, message)
        elif text == "📊 WT сигналы":
            await show_wt_signals(self.bot, message)
        elif text == "📈 Тренд сигналы":
            await show_trend_signals(self.bot, message)
        elif text == "💎 Дивергенции":
            await show_divergence_signals(self.bot, message)
        elif text == "🎯 Пивот сигналы":
            await show_pivot_signals(self.bot, message)
        elif text == "📊 Все сигналы":
            await show_all_signals(self.bot, message)
        elif text == "🔍 Поиск сигналов":
            await handle_signal_search(self.bot, message, state)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню сигналов.")

    async def handle_pivots_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню пивотов."""
        text = message.text
        if text == "📊 Пивоты пары":
            await show_pivots_request(self.bot, message, state)
        elif text == "🔍 Проверить пивоты":
            await show_check_pivot_request(self.bot, message, state)
        elif text == "📈 Развороты от пивотов":
            await show_pivot_reversals(self.bot, message)
        elif text == "🎯 Ключевые уровни":
            await show_key_levels(self.bot, message)
        elif text == "📊 Анализ пивотов":
            await show_pivot_analysis(self.bot, message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню пивотов.")

    async def handle_risk_management_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню управления рисками."""
        text = message.text
        if text == "🛡️ Профиль риска":
            await show_risk_profile(self.bot, message)
        elif text == "📊 Позиции":
            await show_active_positions(self.bot, message)
        elif text == "💰 Размер позиций":
            await show_position_sizes(self.bot, message)
        elif text == "📈 Соотношение риск/прибыль":
            await show_risk_reward_ratio(self.bot, message)
        elif text == "⚠️ Предупреждения":
            await show_risk_warnings(self.bot, message)
        elif text == "📊 Статистика рисков":
            await show_risk_statistics(self.bot, message)
        elif text == "⚙️ Настройки рисков":
            await show_risk_settings(self.bot, message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню управления рисками.")

    async def handle_history_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню исторического анализа."""
        text = message.text
        if text == "📊 Эффективность":
            await show_performance_analysis(self.bot, message)
        elif text == "📈 Тренд производительности":
            await show_performance_trend(self.bot, message)
        elif text == "🎯 Анализ по типам":
            await show_analysis_by_type(self.bot, message)
        elif text == "📚 История сигналов":
            await show_signal_history(self.bot, message)
        elif text == "💡 Рекомендации":
            await show_improvement_recommendations(self.bot, message)
        elif text == "📊 Детальная статистика":
            await show_detailed_statistics(self.bot, message)
        elif text == "📤 Экспорт данных":
            await export_history_data(self.bot, message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню исторического анализа.")

    async def handle_subscriptions_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню подписок."""
        text = message.text
        if text == "💎 Моя подписка":
            await cmd_my_subscription(self.bot, message)
        elif text == "🛒 Купить подписку":
            await cmd_buy_subscription(self.bot, message, state)
        elif text == "✅ Подписаться":
            await cmd_subscribe(self.bot, message)
        elif text == "❌ Отписаться":
            await cmd_unsubscribe(self.bot, message)
        elif text == "📊 Лимиты":
            await show_subscription_limits(self.bot, message)
        elif text == "📈 Статистика использования":
            await show_usage_statistics(self.bot, message)
        elif text == "💳 История платежей":
            await show_payment_history(self.bot, message)
        elif text == "⚙️ Настройки подписки":
            await show_subscription_settings(self.bot, message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню подписок.")

    async def handle_settings_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню настроек."""
        text = message.text
        if text == "⚙️ Общие настройки":
            await show_general_settings(self.bot, message)
        elif text == "📊 Параметры анализа":
            await show_analysis_settings(self.bot, message)
        elif text == "🤖 AI настройки":
            await show_ai_settings(self.bot, message)
        elif text == "🛡️ Настройки рисков":
            await show_risk_settings(self.bot, message)
        elif text == "🔔 Уведомления":
            from core.notifications.notif_config import notif_config
            from bot.handlers.notif_handlers import _main_text, _main_keyboard
            await message.answer(_main_text(), reply_markup=_main_keyboard(), parse_mode="HTML")
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню настроек.")

    # ------------------------------------------------------------------
    # Переходы между меню
    # ------------------------------------------------------------------

    async def _show_top_volume(self, message: Message):
        """Топ-10 пар по последнему объёму."""
        from bot.keyboards import main_menu as _main_menu
        if not self.bot.is_monitoring:
            await message.answer("⚠️ Мониторинг не запущен.", reply_markup=_main_menu())
            return
        volumes = {}
        for sym in self.bot.monitored_pairs:
            vhist = self.bot.data_collector.volume_history.get(sym, [])
            if vhist:
                volumes[sym] = vhist[-1]
        sorted_vols = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        lines = ["📊 <b>ТОП-10 пар по объёму</b>"]
        for i, (sym, vol) in enumerate(sorted_vols[:10], 1):
            lines.append(f"{i}. {sym}: {vol:.2f}")
        await message.answer("\n".join(lines), reply_markup=_main_menu())

    async def _show_main_menu(self, message: Message):
        from bot.handlers.core_handlers import build_status_block
        status = build_status_block(self.bot)
        await message.answer(
            f"🏠 <b>Главное меню</b>\n\n{status}\n\nВыберите раздел ↓",
            reply_markup=main_menu()
        )
        self.current_menu = "main"

    async def _show_monitoring_menu(self, message: Message):
        await message.answer(
            "📊 <b>Мониторинг рынков</b>\n\nУправление мониторингом криптовалютных пар:",
            reply_markup=monitoring_menu()
        )
        self.current_menu = "monitoring"

    async def _show_ai_analysis_menu(self, message: Message):
        await message.answer(
            "🧠 <b>AI Анализ и ML</b>\n\nИскусственный интеллект для анализа рынков:",
            reply_markup=ai_analysis_menu()
        )
        self.current_menu = "ai_analysis"

    async def _show_signals_menu(self, message: Message):
        await message.answer(
            "📈 <b>Торговые сигналы</b>\n\nРазличные типы технических сигналов:",
            reply_markup=signals_menu()
        )
        self.current_menu = "signals"

    async def _show_pivots_menu(self, message: Message):
        await message.answer(
            "🎯 <b>Пивотные уровни</b>\n\nАнализ ключевых уровней поддержки и сопротивления:",
            reply_markup=pivots_menu()
        )
        self.current_menu = "pivots"

    async def _show_risk_management_menu(self, message: Message):
        await message.answer(
            "🛡️ <b>Управление рисками</b>\n\nКонтроль рисков и управление позициями:",
            reply_markup=risk_management_menu()
        )
        self.current_menu = "risk_management"

    async def _show_history_menu(self, message: Message):
        await message.answer(
            "📚 <b>Исторический анализ</b>\n\nАнализ эффективности и производительности:",
            reply_markup=history_menu()
        )
        self.current_menu = "history"

    async def _show_subscriptions_menu(self, message: Message):
        await message.answer(
            "💎 <b>Подписки</b>\n\nУправление подписками и лимитами:",
            reply_markup=subscriptions_menu()
        )
        self.current_menu = "subscriptions"

    async def _show_settings_menu(self, message: Message):
        await message.answer(
            "⚙️ <b>Настройки</b>\n\nКонфигурация системы и параметров:",
            reply_markup=settings_menu()
        )
        self.current_menu = "settings"

    async def _show_dashboard(self, message: Message):
        from bot.menus.dashboard import dashboard_status_text, dashboard_main_kb
        text = dashboard_status_text(self.bot)
        await message.answer(text, reply_markup=dashboard_main_kb())

    # ------------------------------------------------------------------
    # Универсальный обработчик
    # ------------------------------------------------------------------

    async def handle_any_button(self, message: Message, state: FSMContext):
        """Универсальный обработчик для всех кнопок."""
        text = message.text
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"

        logger.info("🔍 [UNIVERSAL] Получено сообщение от %s (%s): '%s'", username, user_id, text)
        logger.debug(
            "📝 [DEBUG] Детали: user_id=%s, username=%s, text='%s', message_id=%s",
            user_id, username, text, message.message_id,
        )

        try:
            current_state = await state.get_state()
            if current_state:
                logger.info("🔄 [FSM] %s в состоянии %s, пропускаем обработку меню", username, current_state)
                return

            menu_type = self._detect_menu_type(text)
            logger.info("🎯 [MENU] Определен тип меню: %s для кнопки '%s'", menu_type, text)

            if menu_type in self.menu_handlers:
                await self.menu_handlers[menu_type](message, state)
            else:
                logger.warning("[MENU] Неизвестный тип меню: %s для '%s' от %s", menu_type, text, username)
                await message.answer(f"Неизвестная команда: '{text}'\n\nИспользуйте меню для навигации.")

        except Exception:
            logger.exception("[UNIVERSAL] Критическая ошибка при обработке кнопки '%s' от %s", text, username)
            await message.answer("Произошла критическая ошибка. Попробуйте еще раз или обратитесь к администратору.")

    def _detect_menu_type(self, text: str) -> str:
        """Определяет тип меню по тексту кнопки."""
        if text in {
            "🟢 Мониторинг", "🧠 AI Анализ", "📊 Статистика",
            "📈 Сигналы", "🎯 Пивоты", "🛡️ Риски", "📚 История",
            "💎 Подписки", "⚙️ Настройки", "📟 Дашборд", "ℹ️ Помощь",
            "Мониторинг", "AI Анализ", "Статистика",
            "Сигналы", "Пивоты", "Риски", "История", "Подписки", "Настройки", "Дашборд", "Помощь",
        }:
            return "main"

        if text in {
            "🟢 Запустить мониторинг", "⏹ Остановить мониторинг", "📊 Статистика мониторинга",
            "🏆 ТОП-10 по объему", "🔍 Найти пару", "📈 Активные сигналы", "⬅️ Назад в главное меню",
            "Запустить мониторинг", "Остановить мониторинг", "Статистика мониторинга",
            "ТОП-10 по объему", "Найти пару", "Активные сигналы", "Назад в главное меню",
        }:
            return "monitoring"

        if text in {
            "🧠 Комплексный анализ", "🤖 ML предсказания", "📊 Анализ пары",
            "🎯 Торговые уровни", "📈 Эффективность", "🔄 Обновить модели",
            "📚 ML статистика", "⚙️ Настройки AI", "⬅️ Назад в главное меню",
            "Комплексный анализ", "ML предсказания", "Анализ пары",
            "Торговые уровни", "Эффективность", "Обновить модели",
            "ML статистика", "Настройки AI", "Назад в главное меню",
        }:
            return "ai_analysis"

        if text in {
            "🚨 Аномалии", "📊 WT сигналы", "📈 Тренд сигналы",
            "💎 Дивергенции", "🎯 Пивот сигналы", "📊 Все сигналы", "🔍 Поиск сигналов",
            "⬅️ Назад в главное меню", "Аномалии", "WT сигналы", "Тренд сигналы",
            "Дивергенции", "Пивот сигналы", "Все сигналы", "Поиск сигналов", "Назад в главное меню",
        }:
            return "signals"

        if text in {
            "📊 Пивоты пары", "🔍 Проверить пивоты",
            "📈 Развороты от пивотов", "🎯 Ключевые уровни", "📊 Анализ пивотов",
            "⬅️ Назад в главное меню", "Пивоты пары", "Проверить пивоты",
            "Развороты от пивотов", "Ключевые уровни", "Анализ пивотов", "Назад в главное меню",
        }:
            return "pivots"

        if text in {
            "🛡️ Профиль риска", "📊 Позиции", "💰 Размер позиций",
            "📈 Соотношение риск/прибыль", "⚠️ Предупреждения", "📊 Статистика рисков",
            "⚙️ Настройки рисков", "⬅️ Назад в главное меню", "Профиль риска", "Позиции",
            "Размер позиций", "Соотношение риск/прибыль", "Предупреждения",
            "Статистика рисков", "Настройки рисков", "Назад в главное меню",
        }:
            return "risk_management"

        if text in {
            "📊 Эффективность", "📈 Тренд производительности", "🎯 Анализ по типам",
            "📚 История сигналов", "💡 Рекомендации", "📊 Детальная статистика",
            "📤 Экспорт данных", "⬅️ Назад в главное меню",
            "Эффективность", "Тренд производительности", "Анализ по типам",
            "История сигналов", "Рекомендации", "Детальная статистика",
            "Экспорт данных", "Назад в главное меню",
        }:
            return "history"

        if text in {
            "💎 Моя подписка", "🛒 Купить подписку", "✅ Подписаться", "❌ Отписаться",
            "📊 Лимиты", "📈 Статистика использования", "💳 История платежей",
            "⚙️ Настройки подписки", "⬅️ Назад в главное меню", "Моя подписка", "Купить подписку",
            "Подписаться", "Отписаться", "Лимиты", "Статистика использования",
            "История платежей", "Настройки подписки", "Назад в главное меню",
        }:
            return "subscriptions"

        if text in {
            "⚙️ Общие настройки", "📊 Параметры анализа",
            "🤖 AI настройки", "🛡️ Настройки рисков",
            "🔔 Уведомления",
            "⬅️ Назад в главное меню",
            "Общие настройки", "Параметры анализа",
            "AI настройки", "Настройки рисков",
            "Назад в главное меню",
        }:
            return "settings"

        return "unknown"
