"""
Действия меню подписок — standalone-функции вместо методов MenuHandler.
"""
import logging

from aiogram.types import Message

logger = logging.getLogger(__name__)


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
