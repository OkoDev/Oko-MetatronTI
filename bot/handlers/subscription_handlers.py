"""
Команды подписок: /subscribe, /unsubscribe, /my_subscription, /buy_subscription.
FSM: process_payment.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from core.keyboards import main_menu
from bot.states import SubscriptionStates

logger = logging.getLogger(__name__)


def get_router(bot) -> Router:
    router = Router()

    @router.message(Command("subscribe"))
    async def cmd_subscribe(message: Message):
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
            "📊 <b>Что включено:</b>\n"
            "• 5 сигналов в день\n"
            "• Только аномалии объёма/цены\n\n"
            "💎 <b>Для большего:</b>\n"
            "• /buy_subscription - купить подписку\n"
            "• /my_subscription - моя подписка",
            reply_markup=main_menu(),
        )

    @router.message(Command("unsubscribe"))
    async def cmd_unsubscribe(message: Message):
        bot.subscribers.discard(message.from_user.id)
        await message.answer("✅ Вы отписаны от всех сигналов.", reply_markup=main_menu())

    @router.message(Command("my_subscription"))
    async def cmd_my_subscription(message: Message):
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
            "anomaly": "🚨 Аномалии",
            "wt_signal": "📊 WT сигналы",
            "mtf_signal": "🔄 MTF сигналы",
            "mtf_alert": "🎯 MTF точки разворота",
            "trend_signal": "📈 Тренд-сигналы",
            "divergence": "💎 Дивергенции",
            "all": "🌟 Все сигналы",
        }

        if "all" in signals:
            signal_list = ["🌟 Все доступные сигналы"]
        else:
            signal_list = [signal_names.get(s, s) for s in signals]

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
        for signal in signal_list:
            parts.append(f"  • {signal}")

        if sub_info["expires"]:
            parts.append(f"\n⏰ Истекает: {sub_info['expires']}")

        parts.extend([
            "",
            "💡 <b>Команды:</b>",
            "/buy_subscription - купить подписку",
            "/subscribe - подписаться бесплатно",
        ])
        await message.answer("\n".join(parts), reply_markup=main_menu())

    @router.message(Command("buy_subscription"))
    async def cmd_buy_subscription(message: Message, state: FSMContext):
        parts = [
            "💎 <b>ПОДПИСКИ НА СИГНАЛЫ</b>",
            "",
            "🆓 <b>БЕСПЛАТНО</b>",
            "• 5 сигналов в день",
            "• Только аномалии",
            "• Цена: $0/месяц",
            "",
            "💎 <b>BASIC - $9.99/месяц</b>",
            "• 10 сигналов в день",
            "• Аномалии + WT + MTF",
            "• Уведомления в Telegram",
            "",
            "🚀 <b>PREMIUM - $29.99/месяц</b>",
            "• 50 сигналов в день",
            "• Все типы сигналов",
            "• Приоритетные уведомления",
            "",
            "👑 <b>PRO - $99.99/месяц</b>",
            "• Неограниченно сигналов",
            "• Все функции",
            "• Веб-панель управления",
            "",
            "💳 <b>Для покупки:</b>",
            "1. Выберите уровень подписки",
            "2. Отправьте скриншот оплаты",
            "3. Получите доступ к сигналам",
            "",
            "📞 <b>Контакты для оплаты:</b>",
            "• Telegram: @your_username",
            "• Email: your@email.com",
            "",
            "Введите номер подписки (1-3) или 'cancel' для отмены:",
        ]
        await message.answer("\n".join(parts), reply_markup=ReplyKeyboardRemove())
        await state.set_state(SubscriptionStates.waiting_for_payment)

    @router.message(SubscriptionStates.waiting_for_payment)
    async def process_payment(message: Message, state: FSMContext):
        text = message.text.strip().lower()

        if text == "cancel":
            await message.answer("❌ Покупка отменена.", reply_markup=main_menu())
            await state.clear()
            return

        tier_mapping = {"1": "basic", "2": "premium", "3": "pro"}

        if text in tier_mapping:
            tier = tier_mapping[text]
            user_id = message.from_user.id
            success = bot.subscription_manager.create_subscription(user_id, tier, 30)

            if success:
                await message.answer(
                    f"✅ Подписка {tier.upper()} активирована!\n"
                    f"Срок действия: 30 дней\n\n"
                    f"Теперь вы получаете расширенные сигналы!",
                    reply_markup=main_menu(),
                )
            else:
                await message.answer(
                    "❌ Ошибка активации подписки. Попробуйте позже.",
                    reply_markup=main_menu(),
                )
        else:
            await message.answer(
                "❌ Неверный номер. Введите 1, 2, 3 или 'cancel'",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        await state.clear()

    return router
