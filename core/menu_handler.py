"""
Обработчик расширенного меню бота
Обеспечивает навигацию по всем функциям системы
"""

import logging
import asyncio
from typing import Dict, Any, Optional
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from core.keyboards import (
    main_menu, monitoring_menu, ai_analysis_menu, signals_menu, 
    pivots_menu, risk_management_menu, history_menu, 
    subscriptions_menu, settings_menu,
    ai_analysis_inline_menu, signal_types_inline_menu,
    risk_management_inline_menu, history_analysis_inline_menu,
    symbol_selection_menu, timeframe_selection_menu,
    confirmation_menu, pagination_menu
)

logger = logging.getLogger(__name__)

class MenuHandler:
    """
    Обработчик расширенного меню
    """
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.current_menu = "main"
        self.menu_stack = []
        
        # Словарь для быстрого поиска обработчиков
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
    
    async def handle_main_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок главного меню"""
        text = message.text
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        
        logger.info(f"🔍 [MENU] Главное меню - пользователь {username} ({user_id}) нажал: '{text}'")
        
        try:
            if text == "🟢 Мониторинг":
                logger.info(f"📊 [MENU] Переход в меню мониторинга для {username}")
                await self._show_monitoring_menu(message)
            elif text == "⏹ Остановить":
                logger.info(f"⏹ [MENU] Остановка мониторинга для {username}")
                await self._handle_stop_monitoring(message)
            elif text == "🧠 AI Анализ":
                logger.info(f"🧠 [MENU] Переход в AI анализ для {username}")
                await self._show_ai_analysis_menu(message)
            elif text == "📊 Статистика":
                logger.info(f"📊 [MENU] Показ статистики для {username}")
                await self._show_statistics(message)
            elif text == "📈 Сигналы":
                logger.info(f"📈 [MENU] Переход в меню сигналов для {username}")
                await self._show_signals_menu(message)
            elif text == "🎯 Пивоты":
                logger.info(f"🎯 [MENU] Переход в меню пивотов для {username}")
                await self._show_pivots_menu(message)
            elif text == "🛡️ Риски":
                logger.info(f"🛡️ [MENU] Переход в управление рисками для {username}")
                await self._show_risk_management_menu(message)
            elif text == "📚 История":
                logger.info(f"📚 [MENU] Переход в исторический анализ для {username}")
                await self._show_history_menu(message)
            elif text == "💎 Подписки":
                logger.info(f"💎 [MENU] Переход в меню подписок для {username}")
                await self._show_subscriptions_menu(message)
            elif text == "⚙️ Настройки":
                logger.info(f"⚙️ [MENU] Переход в настройки для {username}")
                await self._show_settings_menu(message)
            elif text == "ℹ️ Помощь":
                logger.info(f"ℹ️ [MENU] Показ справки для {username}")
                await self._show_help(message)
            else:
                logger.warning(f"[MENU] Неизвестная кнопка главного меню: '{text}' от {username}")
                await message.answer("Неизвестная команда. Используйте меню.")
        except Exception as e:
            logger.error(f"[MENU] Ошибка в обработке главного меню для {username}: {e}")
            await message.answer("Произошла ошибка при обработке команды. Попробуйте еще раз.")
    
    async def handle_monitoring_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню мониторинга"""
        text = message.text
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        
        logger.info(f"🔍 [MENU] Мониторинг - пользователь {username} ({user_id}) нажал: '{text}'")
        
        try:
            if text == "🟢 Запустить мониторинг":
                logger.info(f"🟢 [MENU] Запуск мониторинга для {username}")
                await self.bot.cmd_monitor(message)
            elif text == "⏹ Остановить мониторинг":
                logger.info(f"⏹ [MENU] Остановка мониторинга для {username}")
                await self.bot.cmd_monitor(message)
            elif text == "📊 Статистика мониторинга":
                logger.info(f"📊 [MENU] Показ статистики мониторинга для {username}")
                await self.bot.cmd_stats(message)
            elif text == "🏆 ТОП-10 по объему":
                logger.info(f"🏆 [MENU] Показ ТОП-10 для {username}")
                await self.bot.cmd_top(message)
            elif text == "🔍 Найти пару":
                logger.info(f"🔍 [MENU] Поиск пары для {username}")
                await self._handle_find_pair(message, state)
            elif text == "📈 Активные сигналы":
                logger.info(f"📈 [MENU] Показ активных сигналов для {username}")
                await self._show_active_signals(message)
            elif text == "⬅️ Назад в главное меню":
                logger.info(f"⬅️ [MENU] Возврат в главное меню для {username}")
                await self._show_main_menu(message)
            else:
                logger.warning(f"[MENU] Неизвестная кнопка мониторинга: '{text}' от {username}")
                await message.answer("Неизвестная команда в меню мониторинга.")
        except Exception as e:
            logger.error(f"[MENU] Ошибка в обработке мониторинга для {username}: {e}")
            await message.answer("Произошла ошибка при обработке команды мониторинга.")
    
    async def handle_ai_analysis_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню AI анализа"""
        text = message.text
        
        if text == "🧠 Комплексный анализ":
            await self._handle_intelligence_analysis(message, state)
        elif text == "🤖 ML предсказания":
            await self._handle_ml_predictions(message, state)
        elif text == "📊 Анализ пары":
            await self._handle_pair_analysis(message, state)
        elif text == "🎯 Торговые уровни":
            await self._handle_trading_levels(message, state)
        elif text == "📈 Эффективность":
            await self._show_ai_performance(message)
        elif text == "🔄 Обновить модели":
            await self._handle_retrain_models(message)
        elif text == "📚 ML статистика":
            await self._show_ml_statistics(message)
        elif text == "⚙️ Настройки AI":
            await self._show_ai_settings(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню AI анализа.")
    
    async def handle_signals_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню сигналов"""
        text = message.text
        
        if text == "🚨 Аномалии":
            await self._show_anomaly_signals(message)
        elif text == "📊 WT сигналы":
            await self._show_wt_signals(message)
        elif text == "🔄 MTF анализ":
            await self._show_mtf_signals(message)
        elif text == "📈 Тренд сигналы":
            await self._show_trend_signals(message)
        elif text == "💎 Дивергенции":
            await self._show_divergence_signals(message)
        elif text == "🎯 Пивот сигналы":
            await self._show_pivot_signals(message)
        elif text == "📊 Все сигналы":
            await self._show_all_signals(message)
        elif text == "🔍 Поиск сигналов":
            await self._handle_signal_search(message, state)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню сигналов.")
    
    async def handle_pivots_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню пивотов"""
        text = message.text
        
        if text == "📊 Недельные пивоты":
            await self.bot.cmd_request_pivots(message, state)
        elif text == "📅 Дневные пивоты":
            await self.bot.cmd_request_pivots(message, state)
        elif text == "🔍 Проверить пивоты":
            await self.bot.cmd_request_check(message, state)
        elif text == "📈 Развороты от пивотов":
            await self._show_pivot_reversals(message)
        elif text == "🎯 Ключевые уровни":
            await self._show_key_levels(message)
        elif text == "📊 Анализ пивотов":
            await self._show_pivot_analysis(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню пивотов.")
    
    async def handle_risk_management_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню управления рисками"""
        text = message.text
        
        if text == "🛡️ Профиль риска":
            await self._show_risk_profile(message)
        elif text == "📊 Позиции":
            await self._show_active_positions(message)
        elif text == "💰 Размер позиций":
            await self._show_position_sizes(message)
        elif text == "🎯 Стоп-лоссы":
            await self._show_stop_losses(message)
        elif text == "📈 Соотношение риск/прибыль":
            await self._show_risk_reward_ratio(message)
        elif text == "⚠️ Предупреждения":
            await self._show_risk_warnings(message)
        elif text == "📊 Статистика рисков":
            await self._show_risk_statistics(message)
        elif text == "⚙️ Настройки рисков":
            await self._show_risk_settings(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню управления рисками.")
    
    async def handle_history_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню исторического анализа"""
        text = message.text
        
        if text == "📊 Эффективность":
            await self._show_performance_analysis(message)
        elif text == "📈 Тренд производительности":
            await self._show_performance_trend(message)
        elif text == "🎯 Анализ по типам":
            await self._show_analysis_by_type(message)
        elif text == "📚 История сигналов":
            await self._show_signal_history(message)
        elif text == "💡 Рекомендации":
            await self._show_improvement_recommendations(message)
        elif text == "📊 Детальная статистика":
            await self._show_detailed_statistics(message)
        elif text == "🔄 Обновить данные":
            await self._refresh_history_data(message)
        elif text == "📤 Экспорт данных":
            await self._export_history_data(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню исторического анализа.")
    
    async def handle_subscriptions_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню подписок"""
        text = message.text
        
        if text == "💎 Моя подписка":
            await self.bot.cmd_my_subscription(message)
        elif text == "🛒 Купить подписку":
            await self.bot.cmd_buy_subscription(message)
        elif text == "✅ Подписаться":
            await self.bot.cmd_subscribe(message)
        elif text == "❌ Отписаться":
            await self.bot.cmd_unsubscribe(message)
        elif text == "📊 Лимиты":
            await self._show_subscription_limits(message)
        elif text == "📈 Статистика использования":
            await self._show_usage_statistics(message)
        elif text == "💳 История платежей":
            await self._show_payment_history(message)
        elif text == "⚙️ Настройки подписки":
            await self._show_subscription_settings(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню подписок.")
    
    async def handle_settings_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню настроек"""
        text = message.text
        
        if text == "⚙️ Общие настройки":
            await self._show_general_settings(message)
        elif text == "🔔 Уведомления":
            await self._show_notification_settings(message)
        elif text == "📊 Параметры анализа":
            await self._show_analysis_settings(message)
        elif text == "🎯 Настройки сигналов":
            await self._show_signal_settings(message)
        elif text == "🤖 AI настройки":
            await self._show_ai_settings(message)
        elif text == "🛡️ Настройки рисков":
            await self._show_risk_settings(message)
        elif text == "📱 Интерфейс":
            await self._show_interface_settings(message)
        elif text == "🔧 Дополнительно":
            await self._show_advanced_settings(message)
        elif text == "⬅️ Назад в главное меню":
            await self._show_main_menu(message)
        else:
            await message.answer("❌ Неизвестная команда в меню настроек.")
    
    # Вспомогательные методы для отображения меню
    async def _show_main_menu(self, message: Message):
        """Показать главное меню"""
        await message.answer(
            "🏠 <b>Главное меню</b>\n\n"
            "Выберите раздел для работы:",
            reply_markup=main_menu()
        )
        self.current_menu = "main"
    
    async def _show_monitoring_menu(self, message: Message):
        """Показать меню мониторинга"""
        await message.answer(
            "📊 <b>Мониторинг рынков</b>\n\n"
            "Управление мониторингом криптовалютных пар:",
            reply_markup=monitoring_menu()
        )
        self.current_menu = "monitoring"
    
    async def _show_ai_analysis_menu(self, message: Message):
        """Показать меню AI анализа"""
        await message.answer(
            "🧠 <b>AI Анализ и ML</b>\n\n"
            "Искусственный интеллект для анализа рынков:",
            reply_markup=ai_analysis_menu()
        )
        self.current_menu = "ai_analysis"
    
    async def _show_signals_menu(self, message: Message):
        """Показать меню сигналов"""
        await message.answer(
            "📈 <b>Торговые сигналы</b>\n\n"
            "Различные типы технических сигналов:",
            reply_markup=signals_menu()
        )
        self.current_menu = "signals"
    
    async def _show_pivots_menu(self, message: Message):
        """Показать меню пивотов"""
        await message.answer(
            "🎯 <b>Пивотные уровни</b>\n\n"
            "Анализ ключевых уровней поддержки и сопротивления:",
            reply_markup=pivots_menu()
        )
        self.current_menu = "pivots"
    
    async def _show_risk_management_menu(self, message: Message):
        """Показать меню управления рисками"""
        await message.answer(
            "🛡️ <b>Управление рисками</b>\n\n"
            "Контроль рисков и управление позициями:",
            reply_markup=risk_management_menu()
        )
        self.current_menu = "risk_management"
    
    async def _show_history_menu(self, message: Message):
        """Показать меню исторического анализа"""
        await message.answer(
            "📚 <b>Исторический анализ</b>\n\n"
            "Анализ эффективности и производительности:",
            reply_markup=history_menu()
        )
        self.current_menu = "history"
    
    async def _show_subscriptions_menu(self, message: Message):
        """Показать меню подписок"""
        await message.answer(
            "💎 <b>Подписки</b>\n\n"
            "Управление подписками и лимитами:",
            reply_markup=subscriptions_menu()
        )
        self.current_menu = "subscriptions"
    
    async def _show_settings_menu(self, message: Message):
        """Показать меню настроек"""
        await message.answer(
            "⚙️ <b>Настройки</b>\n\n"
            "Конфигурация системы и параметров:",
            reply_markup=settings_menu()
        )
        self.current_menu = "settings"
    
    # Методы обработки конкретных функций
    async def _handle_intelligence_analysis(self, message: Message, state: FSMContext):
        """Обработка комплексного анализа"""
        await message.answer(
            "🧠 <b>Комплексный AI анализ</b>\n\n"
            "Введите символ для анализа (например: BTC, ETH, SOL):"
        )
        # Импортируем состояние из основного файла
        from bot_with_subscriptions import AIAnalysisStates
        await state.set_state(AIAnalysisStates.waiting_for_symbol)
    
    async def _handle_ml_predictions(self, message: Message, state: FSMContext):
        """Обработка ML предсказаний"""
        await message.answer(
            "🤖 <b>ML Предсказания</b>\n\n"
            "Машинное обучение для прогнозирования движения цен.\n"
            "Выберите тип предсказания:",
            reply_markup=ai_analysis_inline_menu()
        )
    
    async def _show_statistics(self, message: Message):
        """Показать статистику"""
        await self.bot.cmd_stats(message)
    
    async def _show_help(self, message: Message):
        """Показать справку"""
        help_text = """
🤖 <b>Crypto Volume Bot - Справка</b>

<b>📊 Основные функции:</b>
• Мониторинг криптовалютных рынков
• 8 типов технических сигналов
• AI-анализ с машинным обучением
• Управление рисками
• Исторический анализ

<b>🧠 AI Анализ:</b>
• Комплексные торговые рекомендации
• ML предсказания направления цены
• Автоматическое управление рисками
• Анализ эффективности

<b>📈 Типы сигналов:</b>
• Аномалии объема
• Wavetrend сигналы
• MTF анализ
• Тренд сигналы
• Дивергенции
• Пивотные уровни

<b>💎 Подписки:</b>
• Free: 5 сигналов/день
• Basic: $9.99/месяц
• Premium: $29.99/месяц
• Pro: $99.99/месяц

<b>🔧 Команды:</b>
• /start - Главное меню
• /intelligence SYMBOL - AI анализ
• /pivots - Пивотные уровни
• /stats - Статистика

Используйте меню для навигации по всем функциям!
        """
        await message.answer(help_text)
    
    # Заглушки для остальных методов (будут реализованы)
    async def _handle_stop_monitoring(self, message: Message):
        """Остановка мониторинга"""
        await self.bot.stop_monitoring(message)
    
    async def _handle_find_pair(self, message: Message, state: FSMContext):
        await message.answer("🔍 Введите символ для поиска (например: BTC):")
        # Импортируем состояние из основного файла
        from bot_with_subscriptions import AIAnalysisStates
        await state.set_state(AIAnalysisStates.waiting_for_symbol_search)
    
    async def _show_active_signals(self, message: Message):
        """Показ активных сигналов из последних аномалий"""
        if not self.bot.recent_anomalies:
            await message.answer("📈 Активных сигналов нет")
            return
        lines = ["📈 <b>Активные сигналы</b>"]
        for sym, data in list(self.bot.recent_anomalies.items())[:10]:
            ts = data.get('timestamp', 'N/A')
            lines.append(f"• {sym}: {ts}")
        await message.answer("\n".join(lines))
    
    # Добавьте остальные методы-заглушки по аналогии...
    async def _handle_pair_analysis(self, message: Message, state: FSMContext):
        await message.answer("📊 Введите символ для анализа пары (например: BTC, ETH, SOL):")
        # Импортируем состояние из основного файла
        from bot_with_subscriptions import AIAnalysisStates
        await state.set_state(AIAnalysisStates.waiting_for_symbol)
    
    async def _handle_trading_levels(self, message: Message, state: FSMContext):
        await message.answer("🎯 Введите символ для расчета торговых уровней (например: BTC, ETH, SOL):")
        # Импортируем состояние из основного файла
        from bot_with_subscriptions import AIAnalysisStates
        await state.set_state(AIAnalysisStates.waiting_for_symbol)
    
    async def _show_ai_performance(self, message: Message):
        """Показ эффективности AI анализа"""
        ti = self.bot.trading_intelligence
        if hasattr(ti, 'ml_predictor'):
            stats = getattr(ti.ml_predictor, 'performance_stats', {})
            lines = ["📈 <b>Эффективность AI</b>"]
            lines.append(f"Точность: {stats.get('accuracy', 'N/A')}")
            lines.append(f"Сигналов обработано: {stats.get('signals_processed', 0)}")
            await message.answer("\n".join(lines))
        else:
            await message.answer("📈 AI модуль не инициализирован")
    
    async def _handle_retrain_models(self, message: Message):
        """Обновление ML моделей"""
        ti = self.bot.trading_intelligence
        if hasattr(ti, 'ml_predictor') and ti.ml_predictor:
            try:
                # Пытаемся переобучить модели
                if hasattr(ti.ml_predictor, 'retrain_models'):
                    await message.answer("🔄 Начинаю переобучение ML моделей...")
                    result = await ti.ml_predictor.retrain_models()
                    if result:
                        await message.answer("✅ ML модели успешно переобучены!")
                    else:
                        await message.answer("⚠️ Переобучение моделей завершилось с предупреждениями")
                else:
                    await message.answer("🔄 ML модуль не поддерживает переобучение. Модели обновляются автоматически при анализе.")
            except Exception as e:
                logger.exception("Ошибка переобучения ML моделей")
                await message.answer(f"❌ Ошибка переобучения: {str(e)}")
        else:
            await message.answer("🔄 ML модуль не инициализирован")
    
    async def _show_ml_statistics(self, message: Message):
        """Показ ML статистики"""
        ti = self.bot.trading_intelligence
        if hasattr(ti, 'ml_predictor'):
            stats = getattr(ti.ml_predictor, 'model_stats', {})
            lines = ["📚 <b>ML статистика</b>"]
            for key, val in stats.items():
                lines.append(f"{key}: {val}")
            await message.answer("\n".join(lines) if lines else "📚 ML статистика недоступна")
        else:
            await message.answer("📚 ML модуль не инициализирован")
    
    async def _show_ai_settings(self, message: Message):
        """Показ настроек AI"""
        await message.answer("⚙️ <b>Настройки AI</b>\n\nИспользуются настройки по умолчанию из config.yaml")
    
    # Добавьте остальные методы-заглушки...
    async def _show_anomaly_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        found = []
        for sym in self.bot.monitored_pairs[:100]:
            try:
                is_anom, info = self.bot.detector.check_spike(sym, self.bot.data_collector)
                if is_anom:
                    found.append((sym, info))
                    if len(found) >= 30:
                        break
            except Exception:
                continue
        if not found:
            await message.answer("🚨 Аномалий не найдено на первых 100 парах.")
            return
        lines = ["🚨 <b>Последние аномалии</b>"]
        for sym, inf in found:
            lines.append(f"• {sym} — ΔV≈{inf.get('volume_change', 0):.1f}% ΔP≈{inf.get('price_change', 0):.2f}%")
        await message.answer("\n".join(lines))
    
    async def _show_wt_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        symbols = self.bot.monitored_pairs[:80]
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    is_sig, info = await self.bot.detector.check_wt_signal(sym, self.bot.data_collector)
                    if is_sig:
                        return sym, info
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        found = [r for r in raw_results if r][:10]

        if not found:
            await message.answer("📊 WT сигналов не найдено (скан 80 пар).")
            return
        lines = ["📊 <b>WT сигналы</b>"]
        for sym, inf in found:
            lines.append(f"• {sym} — WT1={inf.get('wt1', 0):.1f} WT2={inf.get('wt2', 0):.1f} зона={inf.get('zone','')}")
        await message.answer("\n".join(lines))
    
    async def _show_mtf_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        symbols = self.bot.monitored_pairs[:60]
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    is_sig, info = await self.bot.detector.check_mtf_signal(sym, self.bot.data_collector)
                    if is_sig:
                        return sym, info
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        found = [r for r in raw_results if r][:8]

        if not found:
            await message.answer("🔄 MTF сигналов не найдено (скан 60 пар).")
            return
        lines = ["🔄 <b>MTF сигналы</b>"]
        for sym, inf in found:
            lines.append(f"• {sym} — {inf.get('pattern','signal')}")
        await message.answer("\n".join(lines))
    
    async def _show_trend_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        symbols = self.bot.monitored_pairs[:60]
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    try:
                        is_sig, info = await self.bot.trading_intelligence.check_trend_following_signal(  # type: ignore
                            sym, self.bot.data_collector, self.bot.divergence_detector, self.bot.pivot_calculator
                        )
                    except AttributeError:
                        from core.trend_signals import check_trend_following_signal
                        is_sig, info = await check_trend_following_signal(
                            sym, self.bot.data_collector, self.bot.divergence_detector, self.bot.pivot_calculator
                        )
                    if is_sig:
                        return sym, info
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        found = [r for r in raw_results if r][:8]

        if not found:
            await message.answer("📈 Тренд-сигналов не найдено (скан 60 пар).")
            return
        lines = ["📈 <b>Трендовые сигналы</b>"]
        for sym, inf in found:
            lines.append(f"• {sym} — {inf.get('pattern','signal')}")
        await message.answer("\n".join(lines))
    
    async def _show_divergence_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        timeframes = ["15m", "1h"]
        symbols = self.bot.monitored_pairs[:60]
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    for tf in timeframes:
                        try:
                            has_div, div_info = await self.bot.divergence_detector.detect_divergence(
                                sym, self.bot.data_collector, timeframe=tf
                            )
                            if has_div:
                                return sym, tf, div_info
                        except Exception:
                            continue
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        found = [r for r in raw_results if r][:8]

        if not found:
            await message.answer("💎 Дивергенций не найдено (скан 60 пар).")
            return
        lines = ["💎 <b>Дивергенции</b>"]
        for sym, tf, d in found:
            lines.append(f"• {sym} {tf} — {d.get('type','divergence')}")
        await message.answer("\n".join(lines))
    
    async def _show_pivot_signals(self, message: Message):
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        # Используем уже инициализированный калькулятор с кэшем
        calc = self.bot.pivot_calculator_fixed
        symbols = self.bot.monitored_pairs[:40]

        # Ограничиваем количество одновременных запросов к бирже
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    piv = await calc.get_multi_timeframe_pivots(sym, self.bot.data_collector)
                    if not piv or '1W' not in piv:
                        return None
                    df = await self.bot.data_collector.get_ohlcv(sym, "1m", limit=1)
                    if df is None or df.empty:
                        return None
                    price = float(df['close'].iloc[-1])
                    near = calc.is_near_level(price, piv['1W'], 0.7)
                    if near:
                        return sym, near
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        results = [r for r in raw_results if r][:8]

        if not results:
            await message.answer("🎯 Пивот-сигналы: рядом с уровнями ничего не найдено (скан 40 пар).")
            return
        lines = ["🎯 <b>Цена у недельных уровней</b>"]
        for sym, near in results:
            lines.append(f"• {sym}: {near['level']} {near['level_type']} Δ={near['distance_percent']:.2f}%")
        await message.answer("\n".join(lines))
    
    async def _show_all_signals(self, message: Message):
        await self._show_anomaly_signals(message)
        await self._show_wt_signals(message)
        await self._show_mtf_signals(message)
        await self._show_trend_signals(message)
        await self._show_divergence_signals(message)
        await self._show_pivot_signals(message)
    
    async def _handle_signal_search(self, message: Message, state: FSMContext):
        await message.answer("🔍 Введите символ для поиска сигналов (например: BTC, ETH)")
        from bot_with_subscriptions import AIAnalysisStates
        await state.set_state(AIAnalysisStates.waiting_for_symbol_search)
    
    # Реализация функций пивотов
    async def _handle_daily_pivots(self, message: Message):
        """Показ дневных пивотов для первой пары из мониторинга"""
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        sym = self.bot.monitored_pairs[0]
        try:
            piv = await self.bot.pivot_calculator_fixed.get_daily_pivots(sym, self.bot.data_collector)
            if not piv:
                await message.answer(f"❌ Не удалось получить дневные пивоты для {sym}")
                return
            df = await self.bot.data_collector.get_ohlcv(sym, "1m", limit=1)
            price = float(df['close'].iloc[-1]) if df is not None and not df.empty else 0
            lines = [f"📅 <b>Дневные пивоты {sym}</b>", f"Цена: ${price:.2f}", ""]
            lines.append(f"PP: ${piv['PP']:.2f}")
            for i in range(1, 6):
                lines.append(f"S{i}: ${piv[f'S{i}']:.2f} | R{i}: ${piv[f'R{i}']:.2f}")
            await message.answer("\n".join(lines))
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    async def _show_pivot_reversals(self, message: Message):
        """Показ разворотов от пивотов"""
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        from core.pivot_reversal import check_pivot_level_signal

        symbols = self.bot.monitored_pairs[:30]
        semaphore = asyncio.Semaphore(10)

        async def process_symbol(sym: str):
            try:
                async with semaphore:
                    has_signal, info = await check_pivot_level_signal(
                        sym, self.bot.data_collector, self.bot.pivot_calculator_fixed
                    )
                    if has_signal:
                        return sym, info
            except Exception:
                return None

        tasks = [process_symbol(sym) for sym in symbols]
        raw_results = await asyncio.gather(*tasks)
        found = [r for r in raw_results if r][:5]

        if not found:
            await message.answer("📈 Развороты от пивотов не найдены (скан 30 пар).")
            return
        lines = ["📈 <b>Развороты от пивотов</b>"]
        for sym, info in found:
            lines.append(f"• {sym}: {info.get('direction', 'N/A')} у {info.get('level', 'N/A')}")
        await message.answer("\n".join(lines))
    
    async def _show_key_levels(self, message: Message):
        """Показ ключевых уровней (конфлюэнции)"""
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        sym = self.bot.monitored_pairs[0]
        try:
            piv = await self.bot.pivot_calculator_fixed.get_multi_timeframe_pivots(sym, self.bot.data_collector)
            if not piv or 'confluence' not in piv or not piv['confluence']:
                await message.answer(f"🎯 Конфлюэнций не найдено для {sym}")
                return
            lines = [f"🎯 <b>Ключевые уровни (конфлюэнции) {sym}</b>"]
            for conf in piv['confluence'][:5]:
                lines.append(f"• {conf['weekly_level']} (1W) = {conf['daily_level']} (1D): ${conf['weekly_price']:.2f} ({conf['strength']})")
            await message.answer("\n".join(lines))
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    async def _show_pivot_analysis(self, message: Message):
        """Комплексный анализ пивотов"""
        if not self.bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return
        sym = self.bot.monitored_pairs[0]
        try:
            piv = await self.bot.pivot_calculator_fixed.get_multi_timeframe_pivots(sym, self.bot.data_collector)
            if not piv:
                await message.answer(f"❌ Не удалось получить пивоты для {sym}")
                return
            df = await self.bot.data_collector.get_ohlcv(sym, "1m", limit=1)
            price = float(df['close'].iloc[-1]) if df is not None and not df.empty else 0
            lines = [f"📊 <b>Анализ пивотов {sym}</b>", f"Текущая цена: ${price:.2f}", ""]
            if '1W' in piv:
                lines.append("📅 <b>Недельные:</b>")
                lines.append(f"PP: ${piv['1W']['PP']:.2f}")
            if '1D' in piv:
                lines.append("📅 <b>Дневные:</b>")
                lines.append(f"PP: ${piv['1D']['PP']:.2f}")
            if 'confluence' in piv and piv['confluence']:
                lines.append(f"\n🎯 Конфлюэнций: {len(piv['confluence'])}")
            await message.answer("\n".join(lines))
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
    
    # Методы управления рисками
    async def _show_risk_profile(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("🛡️ Менеджер рисков недоступен")
            return
        summary = rm.get_risk_summary()
        recs = rm.get_risk_recommendations()
        lines = [
            "🛡️ <b>Профиль риска портфеля</b>",
            f"Капитал: ${summary['base_capital']:.2f}",
            f"Экспозиция: ${summary['total_exposure']:.2f} ({summary['exposure_percent']:.1f}%)",
            f"Суммарный риск: ${summary['total_risk']:.2f} ({summary['risk_percent']:.2f}%)",
            f"Активных позиций: {summary['active_positions']}",
            f"Профилей риска: {summary['risk_profiles']}",
            "",
            "💡 <b>Рекомендации:</b>"
        ]
        for r in recs:
            lines.append(f"• {r}")
        await message.answer("\n".join(lines))
    
    async def _show_active_positions(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm or not rm.active_positions:
            await message.answer("📊 Активных позиций нет")
            return
        lines = ["📊 <b>Активные позиции</b>"]
        for sym, pos in list(rm.active_positions.items())[:10]:
            lines.append(f"• {sym}: size={pos.position_size:.4f}, entry={pos.entry_price:.4f}, SL={pos.stop_loss:.4f}, TP={pos.take_profit:.4f}")
        await message.answer("\n".join(lines))
    
    async def _show_position_sizes(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("💰 Менеджер рисков недоступен")
            return
        lines = ["💰 <b>Шкала размеров позиций</b>"]
        for name, pct in rm.position_sizes.items():
            lines.append(f"• {name.value}: {pct*100:.2f}% от капитала")
        await message.answer("\n".join(lines))
    
    async def _show_stop_losses(self, message: Message):
        await message.answer("🎯 Для расчета SL/TP используйте команду /intelligence SYMBOL — уровни предлагаются в рекомендациях анализа.")
    
    async def _show_risk_reward_ratio(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("📈 Менеджер рисков недоступен")
            return
        summary = rm.get_risk_summary()
        lines = [
            "📈 <b>Общая оценка риск/прибыль</b>",
            f"Дневных сделок: {summary['daily_trades']}",
            f"Дневной PnL: ${summary['daily_pnl']:.2f}",
            f"Макс. просадка: ${summary['max_drawdown']:.2f}",
        ]
        await message.answer("\n".join(lines))
    
    async def _show_risk_warnings(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("⚠️ Менеджер рисков недоступен")
            return
        ok, warnings = True, []
        for pos in rm.active_positions.values():
            ok, w = rm.check_risk_limits(pos.symbol, pos)
            warnings.extend(w)
        if not warnings:
            await message.answer("✅ Нарушений риск-правил не обнаружено")
            return
        lines = ["⚠️ <b>Предупреждения</b>"]
        for w in warnings[:10]:
            lines.append(f"• {w}")
        await message.answer("\n".join(lines))
    
    async def _show_risk_statistics(self, message: Message):
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("📊 Менеджер рисков недоступен")
            return
        s = rm.get_risk_summary()
        lines = [
            "📊 <b>Статистика рисков</b>",
            f"Экспозиция: ${s['total_exposure']:.2f} ({s['exposure_percent']:.1f}%)",
            f"Суммарный риск: ${s['total_risk']:.2f} ({s['risk_percent']:.2f}%)",
            f"Дневной PnL: ${s['daily_pnl']:.2f}",
            f"Серий убытков: {s['consecutive_losses']}",
        ]
        await message.answer("\n".join(lines))
    
    async def _show_risk_settings(self, message: Message):
        """Показ настроек рисков"""
        rm = getattr(self.bot.trading_intelligence, "risk_manager", None)
        if not rm:
            await message.answer("⚙️ Менеджер рисков недоступен")
            return
        settings = getattr(rm, 'settings', {})
        lines = ["⚙️ <b>Настройки рисков</b>"]
        for key, val in settings.items():
            lines.append(f"{key}: {val}")
        await message.answer("\n".join(lines) if lines else "⚙️ Настройки по умолчанию")
    
    # Методы исторического анализа
    async def _show_performance_analysis(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("📊 Исторический анализатор недоступен")
            return
        m = ha.calculate_performance_metrics()
        lines = [
            "📊 <b>Эффективность за всё время</b>",
            f"Сигналов: {m.total_signals}",
            f"Win rate: {m.win_rate:.1%}",
            f"Success rate: {m.success_rate:.1%}",
            f"Profit Factor: {m.profit_factor:.2f}",
            f"Max DD: {m.max_drawdown:.2f}%",
        ]
        await message.answer("\n".join(lines))
    
    async def _show_performance_trend(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("📈 Исторический анализатор недоступен")
            return
        trend = ha.get_performance_trend(days=7)
        if not trend:
            await message.answer("📈 Недостаточно данных для тренда (7д)")
            return
        lines = ["📈 <b>Тренд (7д)</b>"]
        for d, v in list(trend.items())[-7:]:
            lines.append(f"• {d}: SR={v['success_rate']:.1%} PF={v['profit_factor']:.2f} N={v['total_signals']}")
        await message.answer("\n".join(lines))
    
    async def _show_analysis_by_type(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("🎯 Исторический анализатор недоступен")
            return
        by_type = ha.get_performance_by_signal_type()
        if not by_type:
            await message.answer("🎯 Нет данных по типам сигналов")
            return
        lines = ["🎯 <b>По типам сигналов</b>"]
        for t, m in by_type.items():
            lines.append(f"• {t}: SR={m.success_rate:.1%} PF={m.profit_factor:.2f} N={m.total_signals}")
        await message.answer("\n".join(lines))
    
    async def _show_signal_history(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("📚 Исторический анализатор недоступен")
            return
        sigs = ha.get_signals(limit=10)
        if not sigs:
            await message.answer("📚 История пуста")
            return
        lines = ["📚 <b>Последние сигналы</b>"]
        for s in sigs[:10]:
            lines.append(f"• {s.timestamp:%Y-%m-%d %H:%M} {s.symbol} {s.signal_type} → {s.outcome.value}")
        await message.answer("\n".join(lines))
    
    async def _show_improvement_recommendations(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("💡 Исторический анализатор недоступен")
            return
        recs = ha.get_recommendations_for_improvement()
        lines = ["💡 <b>Рекомендации</b>"]
        for r in recs:
            lines.append(f"• {r}")
        await message.answer("\n".join(lines))
    
    async def _show_detailed_statistics(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("📊 Исторический анализатор недоступен")
            return
        m = ha.calculate_performance_metrics()
        lines = [
            "📊 <b>Детальная статистика</b>",
            f"Всего сигналов: {m.total_signals}",
            f"Успешные/Неуспешные/Частичные: {m.successful_signals}/{m.failed_signals}/{m.partial_signals}",
            f"Win rate: {m.win_rate:.1%}",
            f"Avg Profit: {m.average_profit:.2f} | Avg Loss: {m.average_loss:.2f}",
            f"Profit Factor: {m.profit_factor:.2f} | Sharpe: {m.sharpe_ratio:.2f}",
        ]
        await message.answer("\n".join(lines))
    
    async def _refresh_history_data(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("🔄 Исторический анализатор недоступен")
            return
        ok = ha.cleanup_old_data()
        await message.answer("✅ Данные обновлены" if ok else "❌ Не удалось обновить данные")
    
    async def _export_history_data(self, message: Message):
        ha = getattr(self.bot.trading_intelligence, "historical_analyzer", None)
        if not ha:
            await message.answer("📤 Исторический анализатор недоступен")
            return
        m = ha.calculate_performance_metrics()
        ok = ha.save_performance_metrics(m)
        await message.answer("📤 Метрики сохранены в базу" if ok else "❌ Ошибка сохранения метрик")
    
    # Методы подписок
    async def _show_subscription_limits(self, message: Message):
        """Показ лимитов подписки"""
        user_id = message.from_user.id
        info = self.bot.subscription_manager.get_subscription_info(user_id)
        lines = ["📊 <b>Лимиты подписки</b>"]
        lines.append(f"Уровень: {info['tier']}")
        lines.append(f"Сигналов сегодня: {info['signals_today']}/{info['signals_limit']}")
        await message.answer("\n".join(lines))
    
    async def _show_usage_statistics(self, message: Message):
        """Показ статистики использования"""
        user_id = message.from_user.id
        info = self.bot.subscription_manager.get_subscription_info(user_id)
        lines = ["📈 <b>Статистика использования</b>"]
        lines.append(f"Сигналов получено: {info['signals_today']}")
        lines.append(f"Лимит: {info['signals_limit']}")
        await message.answer("\n".join(lines))
    
    async def _show_payment_history(self, message: Message):
        """Показ истории платежей"""
        user_id = message.from_user.id
        try:
            # Получаем информацию о подписке
            sub = self.bot.subscription_manager.get_user_subscription(user_id)
            if sub:
                lines = ["💳 <b>История платежей</b>"]
                lines.append(f"Текущая подписка: {sub['tier'].upper()}")
                if sub.get('start_date'):
                    lines.append(f"Начало: {sub['start_date']}")
                if sub.get('end_date'):
                    lines.append(f"Окончание: {sub['end_date']}")
                if sub.get('payment_id'):
                    lines.append(f"ID платежа: {sub['payment_id']}")
                await message.answer("\n".join(lines))
            else:
                await message.answer("💳 <b>История платежей</b>\n\nУ вас нет активных подписок. Используйте /buy_subscription для покупки.")
        except Exception as e:
            logger.exception("Ошибка получения истории платежей")
            await message.answer("💳 История платежей недоступна")
    
    async def _show_subscription_settings(self, message: Message):
        """Показ настроек подписки"""
        user_id = message.from_user.id
        info = self.bot.subscription_manager.get_subscription_info(user_id)
        lines = ["⚙️ <b>Настройки подписки</b>"]
        lines.append(f"Уровень: {info['tier']}")
        lines.append(f"Статус: {info['status']}")
        await message.answer("\n".join(lines))
    
    # Методы настроек
    async def _show_general_settings(self, message: Message):
        try:
            from core.config_loader import config
            cfg = config.get_all()
            lines = ["⚙️ <b>Общие настройки</b>"]
            lines.append(f"Биржа: {cfg.get('exchanges',{}).get('default','bingx')}")
            lvl = cfg.get('analysis',{}).get('volume_multiplier')
            if lvl is not None:
                lines.append(f"Множитель объема: {lvl}")
            lines.append(f"Логирование: {cfg.get('logging',{}).get('level','INFO')}")
            await message.answer("\n".join(lines))
        except Exception:
            await message.answer("⚙️ Настройки недоступны")
    
    async def _show_notification_settings(self, message: Message):
        await message.answer("🔔 Уведомления отправляются подписчикам согласно лимитам уровня подписки.")
    
    async def _show_analysis_settings(self, message: Message):
        from core.config_loader import config
        a = config.get('analysis',{})
        lines = ["📊 <b>Параметры анализа</b>"]
        lines.append(f"volume_multiplier={a.get('volume_multiplier','-')}")
        lines.append(f"price_threshold={a.get('price_threshold','-')}")
        await message.answer("\n".join(lines))
    
    async def _show_signal_settings(self, message: Message):
        lines = ["🎯 <b>Типы сигналов</b>", "Аномалии, WT, MTF, Тренд, Дивергенции, Пивоты"]
        await message.answer("\n".join(lines))
    
    async def _show_interface_settings(self, message: Message):
        await message.answer("📱 Интерфейс: кнопочное меню + inline-кнопки. Язык: RU.")
    
    async def _show_advanced_settings(self, message: Message):
        await message.answer("🔧 Дополнительно: включена защита от дублей (PID lock), UTF-8 логирование.")
    
    # ==============================
    # Универсальный обработчик
    # ==============================
    
    async def handle_any_button(self, message: Message, state: FSMContext):
        """Универсальный обработчик для всех кнопок с глубоким логированием"""
        text = message.text
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        
        logger.info(f"🔍 [UNIVERSAL] Получено сообщение от {username} ({user_id}): '{text}'")
        
        # Логируем все детали сообщения
        logger.debug(f"📝 [DEBUG] Детали сообщения: user_id={user_id}, username={username}, text='{text}', message_id={message.message_id}")
        
        try:
            # Проверяем FSM состояние - если пользователь вводит данные, не обрабатываем как кнопку меню
            current_state = await state.get_state()
            if current_state:
                logger.info(f"🔄 [FSM] Пользователь {username} в состоянии {current_state}, пропускаем обработку меню")
                return  # Позволяем FSM обработчику обработать сообщение
            
            # Определяем тип меню по тексту кнопки
            menu_type = self._detect_menu_type(text)
            logger.info(f"🎯 [MENU] Определен тип меню: {menu_type} для кнопки '{text}'")
            
            if menu_type in self.menu_handlers:
                logger.info(f"✅ [MENU] Вызов обработчика {menu_type} для {username}")
                await self.menu_handlers[menu_type](message, state)
            else:
                logger.warning(f"[MENU] Неизвестный тип меню: {menu_type} для кнопки '{text}' от {username}")
                await message.answer(f"Неизвестная команда: '{text}'\n\nИспользуйте меню для навигации.")
                
        except Exception as e:
            logger.error(f"[UNIVERSAL] Критическая ошибка при обработке кнопки '{text}' от {username}: {e}")
            logger.exception("Полная трассировка ошибки:")
            await message.answer("Произошла критическая ошибка. Попробуйте еще раз или обратитесь к администратору.")
    
    def _detect_menu_type(self, text: str) -> str:
        """Определяет тип меню по тексту кнопки"""
        # Главное меню (с эмодзи и без)
        if text in ["🟢 Мониторинг", "⏹ Остановить", "🧠 AI Анализ", "📊 Статистика", 
                   "📈 Сигналы", "🎯 Пивоты", "🛡️ Риски", "📚 История", 
                   "💎 Подписки", "⚙️ Настройки", "ℹ️ Помощь",
                   "Мониторинг", "Остановить", "AI Анализ", "Статистика",
                   "Сигналы", "Пивоты", "Риски", "История",
                   "Подписки", "Настройки", "Помощь"]:
            return "main"
        
        # Мониторинг (с эмодзи и без)
        elif text in ["🟢 Запустить мониторинг", "⏹ Остановить мониторинг", "📊 Статистика мониторинга",
                     "🏆 ТОП-10 по объему", "🔍 Найти пару", "📈 Активные сигналы", "⬅️ Назад в главное меню",
                     "Запустить мониторинг", "Остановить мониторинг", "Статистика мониторинга",
                     "ТОП-10 по объему", "Найти пару", "Активные сигналы", "Назад в главное меню"]:
            return "monitoring"
        
        # AI Анализ (с эмодзи и без)
        elif text in ["🧠 Комплексный анализ", "🤖 ML предсказания", "📊 Анализ пары",
                     "🎯 Торговые уровни", "📈 Эффективность", "🔄 Обновить модели",
                     "📚 ML статистика", "⚙️ Настройки AI", "⬅️ Назад в главное меню",
                     "Комплексный анализ", "ML предсказания", "Анализ пары",
                     "Торговые уровни", "Эффективность", "Обновить модели",
                     "ML статистика", "Настройки AI", "Назад в главное меню"]:
            return "ai_analysis"
        
        # Сигналы (с эмодзи и без)
        elif text in ["🚨 Аномалии", "📊 WT сигналы", "🔄 MTF анализ", "📈 Тренд сигналы",
                     "💎 Дивергенции", "🎯 Пивот сигналы", "📊 Все сигналы", "🔍 Поиск сигналов",
                     "⬅️ Назад в главное меню", "Аномалии", "WT сигналы", "MTF анализ", "Тренд сигналы",
                     "Дивергенции", "Пивот сигналы", "Все сигналы", "Поиск сигналов",
                     "Назад в главное меню"]:
            return "signals"
        
        # Пивоты (с эмодзи и без)
        elif text in ["📊 Недельные пивоты", "📅 Дневные пивоты", "🔍 Проверить пивоты",
                     "📈 Развороты от пивотов", "🎯 Ключевые уровни", "📊 Анализ пивотов",
                     "⬅️ Назад в главное меню", "Недельные пивоты", "Дневные пивоты", "Проверить пивоты",
                     "Развороты от пивотов", "Ключевые уровни", "Анализ пивотов", "Назад в главное меню"]:
            return "pivots"
        
        # Управление рисками (с эмодзи и без)
        elif text in ["🛡️ Профиль риска", "📊 Позиции", "💰 Размер позиций", "🎯 Стоп-лоссы",
                     "📈 Соотношение риск/прибыль", "⚠️ Предупреждения", "📊 Статистика рисков",
                     "⚙️ Настройки рисков", "⬅️ Назад в главное меню", "Профиль риска", "Позиции",
                     "Размер позиций", "Стоп-лоссы", "Соотношение риск/прибыль", "Предупреждения",
                     "Статистика рисков", "Настройки рисков", "Назад в главное меню"]:
            return "risk_management"
        
        # История (с эмодзи и без)
        elif text in ["📊 Эффективность", "📈 Тренд производительности", "🎯 Анализ по типам",
                     "📚 История сигналов", "💡 Рекомендации", "📊 Детальная статистика",
                     "🔄 Обновить данные", "📤 Экспорт данных", "⬅️ Назад в главное меню",
                     "Эффективность", "Тренд производительности", "Анализ по типам",
                     "История сигналов", "Рекомендации", "Детальная статистика",
                     "Обновить данные", "Экспорт данных", "Назад в главное меню"]:
            return "history"
        
        # Подписки (с эмодзи и без)
        elif text in ["💎 Моя подписка", "🛒 Купить подписку", "✅ Подписаться", "❌ Отписаться",
                     "📊 Лимиты", "📈 Статистика использования", "💳 История платежей",
                     "⚙️ Настройки подписки", "⬅️ Назад в главное меню", "Моя подписка", "Купить подписку",
                     "Подписаться", "Отписаться", "Лимиты", "Статистика использования",
                     "История платежей", "Настройки подписки", "Назад в главное меню"]:
            return "subscriptions"
        
        # Настройки (с эмодзи и без)
        elif text in ["⚙️ Общие настройки", "🔔 Уведомления", "📊 Параметры анализа",
                     "🎯 Настройки сигналов", "🤖 AI настройки", "🛡️ Настройки рисков",
                     "📱 Интерфейс", "🔧 Дополнительно", "⬅️ Назад в главное меню",
                     "Общие настройки", "Уведомления", "Параметры анализа",
                     "Настройки сигналов", "AI настройки", "Настройки рисков",
                     "Интерфейс", "Дополнительно", "Назад в главное меню"]:
            return "settings"
        
        # Неизвестная кнопка
        else:
            return "unknown"
