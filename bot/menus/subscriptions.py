"""
Действия меню подписок — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu

logger = logging.getLogger(__name__)


async def cmd_my_subscription(bot, message: Message) -> None:
    """Показ информации о подписке пользователя."""
    user_id = message.from_user.id
    sub_info = bot.subscription_manager.get_subscription_info(user_id)
    sub_config = bot.config.get_subscription_config()
    current_tier = sub_info["tier"].lower()
    if current_tier in sub_config:
        tier_info = sub_config[current_tier]
        price = tier_info.get("price", 0)
        signals = tier_info.get("signals", [])
    else:
        price = 0
        signals = ["anomaly"]

    signal_names = {
        "anomaly": "🚨 Аномалии", "wt_signal": "📊 WT сигналы",
        "trend_signal": "📈 Тренд-сигналы",
        "divergence": "💎 Дивергенции", "all": "🌟 Все сигналы",
    }
    signal_list = ["🌟 Все доступные сигналы"] if "all" in signals \
        else [signal_names.get(s, s) for s in signals]

    parts = [
        "💎 <b>МОЯ ПОДПИСКА</b>",
        f"Уровень: <b>{sub_info['tier']}</b>",
        f"Статус: {sub_info['status']}",
        f"Цена: ${price}/месяц",
        "",
        "📊 <b>Сигналы сегодня:</b>",
        f"Отправлено: {sub_info['signals_today']}/{sub_info['signals_limit']}",
        "",
        "🎯 <b>Доступные сигналы:</b>",
    ]
    for sig in signal_list:
        parts.append(f"  • {sig}")
    if sub_info.get("expires"):
        parts.append(f"\n⏰ Истекает: {sub_info['expires']}")
    parts.extend(["", "💡 <b>Команды:</b>", "/buy_subscription - купить подписку"])
    await message.answer("\n".join(parts), reply_markup=main_menu())


async def cmd_buy_subscription(bot, message: Message, state: FSMContext) -> None:
    """Покупка подписки — запускает FSM."""
    from bot.states import SubscriptionStates
    parts = [
        "💎 <b>ПОДПИСКИ НА СИГНАЛЫ</b>", "",
        "🆓 <b>БЕСПЛАТНО</b>", "• 5 сигналов в день", "• Только аномалии", "• $0/месяц", "",
        "💎 <b>BASIC - $9.99/месяц</b>", "• 10 сигналов в день", "• Аномалии + WT + MTF", "",
        "🚀 <b>PREMIUM - $29.99/месяц</b>", "• 50 сигналов в день", "• Все типы сигналов", "",
        "👑 <b>PRO - $99.99/месяц</b>", "• Неограниченно", "• Все функции", "",
        "Введите номер подписки (1-3) или 'cancel' для отмены:",
    ]
    await message.answer("\n".join(parts), reply_markup=ReplyKeyboardRemove())
    await state.set_state(SubscriptionStates.waiting_for_payment)


async def cmd_subscribe(bot, message: Message) -> None:
    """Подписка на бесплатные сигналы."""
    user_id = message.from_user.id
    bot.subscription_manager.add_user(
        user_id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
    )
    bot.subscribers.add(user_id)
    await message.answer(
        "✅ Вы подписаны на бесплатные сигналы!\n\n"
        "• 5 сигналов в день\n"
        "• Аномалии объёма/цены\n\n"
        "/buy_subscription — купить подписку",
        reply_markup=main_menu(),
    )


async def cmd_unsubscribe(bot, message: Message) -> None:
    """Отписка от сигналов."""
    bot.subscribers.discard(message.from_user.id)
    await message.answer("✅ Вы отписаны от всех сигналов.", reply_markup=main_menu())


async def show_subscription_limits(bot, message: Message) -> None:
    """Показ лимитов подписки пользователя."""
    user_id = message.from_user.id
    info = bot.subscription_manager.get_subscription_info(user_id)
    lines = [
        "📊 <b>Лимиты подписки</b>",
        f"Уровень: {info['tier']}",
        f"Сигналов сегодня: {info['signals_today']}/{info['signals_limit']}",
    ]
    await message.answer("\n".join(lines))


async def show_usage_statistics(bot, message: Message) -> None:
    """Показ статистики использования подписки."""
    user_id = message.from_user.id
    info = bot.subscription_manager.get_subscription_info(user_id)
    lines = [
        "📈 <b>Статистика использования</b>",
        f"Сигналов получено: {info['signals_today']}",
        f"Лимит: {info['signals_limit']}",
    ]
    await message.answer("\n".join(lines))


async def show_payment_history(bot, message: Message) -> None:
    """Показ истории платежей."""
    user_id = message.from_user.id
    try:
        sub = bot.subscription_manager.get_user_subscription(user_id)
        if sub:
            lines = ["💳 <b>История платежей</b>", f"Текущая подписка: {sub['tier'].upper()}"]
            if sub.get("start_date"):
                lines.append(f"Начало: {sub['start_date']}")
            if sub.get("end_date"):
                lines.append(f"Окончание: {sub['end_date']}")
            if sub.get("payment_id"):
                lines.append(f"ID платежа: {sub['payment_id']}")
            await message.answer("\n".join(lines))
        else:
            await message.answer(
                "💳 <b>История платежей</b>\n\n"
                "У вас нет активных подписок. Используйте /buy_subscription для покупки."
            )
    except Exception:
        logger.exception("Ошибка получения истории платежей")
        await message.answer("💳 История платежей недоступна")


async def show_subscription_settings(bot, message: Message) -> None:
    """Показ настроек подписки."""
    user_id = message.from_user.id
    info = bot.subscription_manager.get_subscription_info(user_id)
    lines = [
        "⚙️ <b>Настройки подписки</b>",
        f"Уровень: {info['tier']}",
        f"Статус: {info['status']}",
    ]
    await message.answer("\n".join(lines))
