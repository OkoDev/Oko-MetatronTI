# bot/keyboards.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> ReplyKeyboardMarkup:
    """
    Главное меню бота с поддержкой всех функций
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🟢 Мониторинг"),
                KeyboardButton(text="⏹ Остановить")
            ],
            [
                KeyboardButton(text="🧠 AI Анализ"),
                KeyboardButton(text="📊 Статистика")
            ],
            [
                KeyboardButton(text="📈 Сигналы"),
                KeyboardButton(text="🎯 Пивоты")
            ],
            [
                KeyboardButton(text="🛡️ Риски"),
                KeyboardButton(text="📚 История")
            ],
            [
                KeyboardButton(text="💎 Подписки"),
                KeyboardButton(text="⚙️ Настройки")
            ],
            [
                KeyboardButton(text="📟 Дашборд"),
                KeyboardButton(text="ℹ️ Помощь")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…"
    )


def monitoring_menu() -> ReplyKeyboardMarkup:
    """
    Меню мониторинга
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🟢 Запустить мониторинг"),
                KeyboardButton(text="⏹ Остановить мониторинг")
            ],
            [
                KeyboardButton(text="📊 Статистика мониторинга"),
                KeyboardButton(text="🏆 ТОП-10 по объему")
            ],
            [
                KeyboardButton(text="🔍 Найти пару"),
                KeyboardButton(text="📈 Активные сигналы")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Управление мониторингом…"
    )


def ai_analysis_menu() -> ReplyKeyboardMarkup:
    """
    Меню AI анализа
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🧠 Комплексный анализ"),
                KeyboardButton(text="🤖 ML предсказания")
            ],
            [
                KeyboardButton(text="📊 Анализ пары"),
                KeyboardButton(text="🎯 Торговые уровни")
            ],
            [
                KeyboardButton(text="📈 Эффективность"),
                KeyboardButton(text="🔄 Обновить модели")
            ],
            [
                KeyboardButton(text="📚 ML статистика"),
                KeyboardButton(text="⚙️ Настройки AI")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="AI анализ и ML…"
    )


def signals_menu() -> ReplyKeyboardMarkup:
    """
    Меню сигналов
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🚨 Аномалии"),
                KeyboardButton(text="📊 WT сигналы")
            ],
            [
                KeyboardButton(text="📈 Тренд сигналы"),
                KeyboardButton(text="💎 Дивергенции")
            ],
            [
                KeyboardButton(text="🎯 Пивот сигналы"),
                KeyboardButton(text="📊 Все сигналы")
            ],
            [
                KeyboardButton(text="🔍 Поиск сигналов"),
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Типы сигналов…"
    )


def pivots_menu() -> ReplyKeyboardMarkup:
    """
    Меню пивотов
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Недельные пивоты"),
                KeyboardButton(text="📅 Дневные пивоты")
            ],
            [
                KeyboardButton(text="🔍 Проверить пивоты"),
                KeyboardButton(text="📈 Развороты от пивотов")
            ],
            [
                KeyboardButton(text="🎯 Ключевые уровни"),
                KeyboardButton(text="📊 Анализ пивотов")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Пивотные уровни…"
    )


def risk_management_menu() -> ReplyKeyboardMarkup:
    """
    Меню управления рисками
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🛡️ Профиль риска"),
                KeyboardButton(text="📊 Позиции")
            ],
            [
                KeyboardButton(text="💰 Размер позиций"),
                KeyboardButton(text="🎯 Стоп-лоссы")
            ],
            [
                KeyboardButton(text="📈 Соотношение риск/прибыль"),
                KeyboardButton(text="⚠️ Предупреждения")
            ],
            [
                KeyboardButton(text="📊 Статистика рисков"),
                KeyboardButton(text="⚙️ Настройки рисков")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Управление рисками…"
    )


def history_menu() -> ReplyKeyboardMarkup:
    """
    Меню исторического анализа
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Эффективность"),
                KeyboardButton(text="📈 Тренд производительности")
            ],
            [
                KeyboardButton(text="🎯 Анализ по типам"),
                KeyboardButton(text="📚 История сигналов")
            ],
            [
                KeyboardButton(text="💡 Рекомендации"),
                KeyboardButton(text="📊 Детальная статистика")
            ],
            [
                KeyboardButton(text="🔄 Обновить данные"),
                KeyboardButton(text="📤 Экспорт данных")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Исторический анализ…"
    )


def subscriptions_menu() -> ReplyKeyboardMarkup:
    """
    Меню подписок
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💎 Моя подписка"),
                KeyboardButton(text="🛒 Купить подписку")
            ],
            [
                KeyboardButton(text="✅ Подписаться"),
                KeyboardButton(text="❌ Отписаться")
            ],
            [
                KeyboardButton(text="📊 Лимиты"),
                KeyboardButton(text="📈 Статистика использования")
            ],
            [
                KeyboardButton(text="💳 История платежей"),
                KeyboardButton(text="⚙️ Настройки подписки")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Управление подписками…"
    )


def settings_menu() -> ReplyKeyboardMarkup:
    """
    Меню настроек
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="⚙️ Общие настройки"),
                KeyboardButton(text="🔔 Уведомления")
            ],
            [
                KeyboardButton(text="📊 Параметры анализа"),
                KeyboardButton(text="🎯 Настройки сигналов")
            ],
            [
                KeyboardButton(text="🤖 AI настройки"),
                KeyboardButton(text="🛡️ Настройки рисков")
            ],
            [
                KeyboardButton(text="📱 Интерфейс"),
                KeyboardButton(text="🔧 Дополнительно")
            ],
            [
                KeyboardButton(text="⬅️ Назад в главное меню")
            ]
        ],
        resize_keyboard=True,
        input_field_placeholder="Настройки системы…"
    )


def subscription_menu() -> InlineKeyboardMarkup:
    """
    Меню выбора подписки
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🆓 Бесплатно", callback_data="sub_free"),
                InlineKeyboardButton(text="💎 Basic $9.99", callback_data="sub_basic")
            ],
            [
                InlineKeyboardButton(text="🚀 Premium $29.99", callback_data="sub_premium"),
                InlineKeyboardButton(text="👑 Pro $99.99", callback_data="sub_pro")
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="sub_cancel")
            ]
        ]
    )


def payment_menu() -> InlineKeyboardMarkup:
    """
    Меню оплаты
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💳 Оплатить", callback_data="payment_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="payment_cancel")
            ]
        ]
    )


def ai_analysis_inline_menu() -> InlineKeyboardMarkup:
    """
    Inline меню для AI анализа
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧠 Комплексный анализ", callback_data="ai_intelligence"),
                InlineKeyboardButton(text="🤖 ML предсказания", callback_data="ai_ml_predictions")
            ],
            [
                InlineKeyboardButton(text="📊 Анализ эффективности", callback_data="ai_performance"),
                InlineKeyboardButton(text="🔄 Обновить модели", callback_data="ai_retrain")
            ],
            [
                InlineKeyboardButton(text="📚 ML статистика", callback_data="ai_ml_stats"),
                InlineKeyboardButton(text="⚙️ Настройки AI", callback_data="ai_settings")
            ]
        ]
    )


def signal_types_inline_menu() -> InlineKeyboardMarkup:
    """
    Inline меню для типов сигналов
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚨 Аномалии", callback_data="signal_anomaly"),
                InlineKeyboardButton(text="📊 WT сигналы", callback_data="signal_wt")
            ],
            [
                InlineKeyboardButton(text="📈 Тренд", callback_data="signal_trend")
            ],
            [
                InlineKeyboardButton(text="💎 Дивергенции", callback_data="signal_divergence"),
                InlineKeyboardButton(text="🎯 Пивоты", callback_data="signal_pivot")
            ],
            [
                InlineKeyboardButton(text="📊 Все сигналы", callback_data="signal_all"),
                InlineKeyboardButton(text="🔍 Поиск", callback_data="signal_search")
            ]
        ]
    )


def risk_management_inline_menu() -> InlineKeyboardMarkup:
    """
    Inline меню для управления рисками
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛡️ Профиль риска", callback_data="risk_profile"),
                InlineKeyboardButton(text="📊 Активные позиции", callback_data="risk_positions")
            ],
            [
                InlineKeyboardButton(text="💰 Размер позиций", callback_data="risk_position_size"),
                InlineKeyboardButton(text="🎯 Стоп-лоссы", callback_data="risk_stop_loss")
            ],
            [
                InlineKeyboardButton(text="📈 Соотношение риск/прибыль", callback_data="risk_reward_ratio"),
                InlineKeyboardButton(text="⚠️ Предупреждения", callback_data="risk_warnings")
            ],
            [
                InlineKeyboardButton(text="📊 Статистика рисков", callback_data="risk_stats"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="risk_settings")
            ]
        ]
    )


def history_analysis_inline_menu() -> InlineKeyboardMarkup:
    """
    Inline меню для исторического анализа
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Общая эффективность", callback_data="history_performance"),
                InlineKeyboardButton(text="📈 Тренд", callback_data="history_trend")
            ],
            [
                InlineKeyboardButton(text="🎯 По типам сигналов", callback_data="history_by_type"),
                InlineKeyboardButton(text="📚 История сигналов", callback_data="history_signals")
            ],
            [
                InlineKeyboardButton(text="💡 Рекомендации", callback_data="history_recommendations"),
                InlineKeyboardButton(text="📊 Детальная статистика", callback_data="history_detailed")
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить данные", callback_data="history_refresh"),
                InlineKeyboardButton(text="📤 Экспорт", callback_data="history_export")
            ]
        ]
    )


def symbol_selection_menu(symbols: list, callback_prefix: str = "select_symbol") -> InlineKeyboardMarkup:
    """
    Меню выбора символа
    """
    buttons = []
    for i in range(0, len(symbols), 2):
        row = []
        for j in range(2):
            if i + j < len(symbols):
                symbol = symbols[i + j]
                row.append(InlineKeyboardButton(
                    text=symbol,
                    callback_data=f"{callback_prefix}_{symbol}"
                ))
        buttons.append(row)

    # Добавляем кнопку "Показать все"
    buttons.append([InlineKeyboardButton(text="📊 Показать все", callback_data=f"{callback_prefix}_all")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def timeframe_selection_menu() -> InlineKeyboardMarkup:
    """
    Меню выбора таймфрейма
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1m", callback_data="timeframe_1m"),
                InlineKeyboardButton(text="5m", callback_data="timeframe_5m"),
                InlineKeyboardButton(text="15m", callback_data="timeframe_15m")
            ],
            [
                InlineKeyboardButton(text="1h", callback_data="timeframe_1h"),
                InlineKeyboardButton(text="4h", callback_data="timeframe_4h"),
                InlineKeyboardButton(text="1d", callback_data="timeframe_1d")
            ],
            [
                InlineKeyboardButton(text="1w", callback_data="timeframe_1w"),
                InlineKeyboardButton(text="1M", callback_data="timeframe_1M")
            ]
        ]
    )


def confirmation_menu(action: str) -> InlineKeyboardMarkup:
    """
    Меню подтверждения действия
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_{action}")
            ]
        ]
    )


def pagination_menu(current_page: int, total_pages: int, callback_prefix: str) -> InlineKeyboardMarkup:
    """
    Меню пагинации
    """
    buttons = []

    # Кнопки навигации
    nav_buttons = []
    if current_page > 1:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"{callback_prefix}_page_{current_page-1}"))

    nav_buttons.append(InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="page_info"))

    if current_page < total_pages:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"{callback_prefix}_page_{current_page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    return InlineKeyboardMarkup(inline_keyboard=buttons)
