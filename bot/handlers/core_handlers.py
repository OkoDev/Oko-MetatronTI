"""
Основные команды бота: /start, /help, /stats, /top, /reset, /monitor, MTF snapshot.
Универсальный обработчик кнопок меню (F.text catch-all).
"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from core.keyboards import main_menu
from core.mtf_checker import collect_mtf_data
from bot.monitoring import start_monitoring, stop_monitoring

logger = logging.getLogger(__name__)


def get_router(bot) -> Router:
    router = Router()

    @router.message(Command("start"))
    async def cmd_start(message: Message):
        user_id = message.from_user.id
        bot.subscription_manager.add_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        bot.subscribers.add(user_id)
        await message.answer(
            "👋 <b>Добро пожаловать в Crypto Volume Bot!</b>\n\n"
            "🚀 <b>Я анализирую криптовалюты и отправляю торговые сигналы:</b>\n"
            "• 🚨 Аномалии объёма и цены\n"
            "• 📊 WT сигналы (Wavetrend)\n"
            "• 🔄 MTF анализ (мультитаймфрейм)\n"
            "• 💎 Дивергенции\n"
            "• 📊 Пивотные уровни\n\n"
            "💎 <b>Подписки:</b>\n"
            "• Бесплатно: 5 сигналов/день\n"
            "• Premium: 50 сигналов/день\n\n"
            "Выберите действие:",
            reply_markup=main_menu(),
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "📚 <b>СПРАВКА ПО КОМАНДАМ</b>\n\n"
            "<b>🔧 Основные:</b>\n"
            "/start - Главное меню\n"
            "/monitor - Запуск/остановка мониторинга\n"
            "/stats - Статистика бота\n"
            "/top - Топ-10 по объёму\n"
            "/reset - Сбросить счетчики\n\n"
            "<b>💎 Подписки:</b>\n"
            "/subscribe - Подписаться бесплатно\n"
            "/unsubscribe - Отписаться\n"
            "/my_subscription - Моя подписка\n"
            "/buy_subscription - Купить подписку\n\n"
            "<b>📊 Анализ:</b>\n"
            "/pivots - Недельные и дневные пивоты\n"
            "/check_pivot - Проверка близости к пивотам\n\n"
            "<b>🔍 Скан и Watchlist:</b>\n"
            "/scan - Скан рынка (топ-10 по силе сигнала)\n"
            "/watch add BTC - Добавить пару в watchlist\n"
            "/watch remove BTC - Удалить пару из watchlist\n"
            "/watchlist - Показать ваш watchlist\n\n"
            "<b>🎯 Типы сигналов:</b>\n"
            "🚨 Аномалии - всплески объёма/цены\n"
            "📊 WT - сигналы по Wavetrend\n"
            "🔄 MTF - мультитаймфрейм анализ\n"
            "🎯 MTF Точки разворота - продвинутый анализ\n"
            "📈 Тренд-сигналы - работа по тренду\n"
            "💎 Дивергенции - расхождения цены и индикатора\n"
            "📊 Пивоты - уровни поддержки/сопротивления\n"
            "🔄 Развороты от пивотов - недельные уровни + FVG",
            reply_markup=main_menu(),
        )

    @router.message(Command("monitor"))
    async def cmd_monitor(message: Message):
        if bot.is_monitoring:
            await stop_monitoring(bot, message)
        else:
            await start_monitoring(bot, message)

    @router.message(Command("stats"))
    async def cmd_stats(message: Message):
        uptime = "N/A"
        if hasattr(bot, "start_time") and bot.start_time:
            delta = datetime.now() - bot.start_time
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            uptime = f"{delta.days}д {hours}ч {minutes}м"

        user_id = message.from_user.id
        sub_info = bot.subscription_manager.get_subscription_info(user_id)

        stats = [
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
            f"• 📊 WT сигналов: {bot.signal_counters['wt_signal']}",
            f"• 🔄 MTF базовых: {bot.signal_counters['mtf_signal']}",
            f"• 🎯 MTF точек разворота: {bot.signal_counters['mtf_alert']}",
            f"• 📈 Тренд-сигналов: {bot.signal_counters['trend_signal']}",
            f"• 💎 Дивергенций: {bot.signal_counters['divergence']}",
            f"• 🔄 Разворотов от пивотов: {bot.signal_counters['pivot_reversal']}",
            f"• 📊 Пивот-алертов: {bot.signal_counters['pivot_alert']}",
            f"• <b>📌 Всего: {bot.signal_counters['total']}</b>",
            "",
            f"💾 Сохранено аномалий в кэше: {len(bot.recent_anomalies)}",
        ]
        await message.answer("\n".join(stats), reply_markup=main_menu())

    @router.message(Command("top"))
    async def cmd_top(message: Message):
        if not bot.is_monitoring:
            await message.answer("⚠️ Мониторинг не запущен.", reply_markup=main_menu())
            return

        volumes = {}
        for sym in bot.monitored_pairs:
            vhist = bot.data_collector.volume_history.get(sym, [])
            if vhist:
                volumes[sym] = vhist[-1]

        sorted_volumes = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        lines = ["📊 <b>ТОП-10 пар по объёму</b>"]
        for i, (sym, vol) in enumerate(sorted_volumes[:10], 1):
            lines.append(f"{i}. {sym}: {vol:.2f}")

        await message.answer("\n".join(lines), reply_markup=main_menu())

    @router.message(Command("reset"))
    async def cmd_reset_stats(message: Message):
        bot.signal_counters = {
            "anomaly": 0, "wt_signal": 0, "mtf_signal": 0, "mtf_alert": 0,
            "trend_signal": 0, "divergence": 0, "pivot_reversal": 0,
            "pivot_alert": 0, "total": 0,
        }
        bot.recent_anomalies = {}
        if hasattr(bot, "start_time"):
            bot.start_time = datetime.now()
        await message.answer("✅ Счетчики статистики сброшены!", reply_markup=main_menu())

    @router.message(Command("mtf"))
    async def cmd_mtf_snapshot(message: Message):
        if not bot.monitored_pairs:
            await message.answer("Нет загруженных пар — запустите мониторинг.", reply_markup=main_menu())
            return

        target = bot.monitored_pairs[0]
        snapshot = await collect_mtf_data(target, bot.data_collector)
        if not snapshot:
            await message.answer("Нет данных для snapshot.", reply_markup=main_menu())
            return

        order = ["3m", "5m", "15m", "45m", "1h", "4h", "1d"]
        available = [tf for tf in order if tf in snapshot]
        lines = [f"📊 <b>MTF Snapshot</b> — {target}", "<pre>TF   Trend  WT1/WT2    Zone</pre>"]
        for tf in available:
            d = snapshot[tf]
            lines.append(f"{tf:>3}  {d['trend']:^5}  {d['wt1']:.1f}/{d['wt2']:.1f}    {d['zone']}")

        await message.answer("\n".join(lines), reply_markup=main_menu())

    # Универсальный обработчик кнопок меню — должен быть последним в роутере
    @router.message(F.text)
    async def handle_any_button(message: Message, state: FSMContext):
        await bot.menu_handler.handle_any_button(message, state)

    return router
