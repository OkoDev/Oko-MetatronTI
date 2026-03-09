"""
Команды пивотов: /pivots, /check_pivot.
FSM: process_show_pivots, process_check_pivot.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu
from core.message_builder import tv_link
from bot.states import PivotStates

logger = logging.getLogger(__name__)


def _find_pair(bot, ticker: str) -> str:
    ticker = ticker.upper().strip()
    if ticker in bot.monitored_pairs:
        return ticker
    for pair in bot.monitored_pairs:
        if pair.startswith(ticker + "/"):
            return pair
    for pair in bot.monitored_pairs:
        if ticker in pair:
            return pair
    return None


def get_router(bot) -> Router:
    router = Router()

    @router.message(Command("pivots"))
    async def cmd_request_pivots(message: Message, state: FSMContext):
        if not bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return

        examples = "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]])
        await message.answer(
            f"📊 <b>НЕДЕЛЬНЫЕ И ДНЕВНЫЕ ПИВОТЫ</b>\n\n"
            f"💬 Введите тиккер монеты:\n\n"
            f"<i>Примеры:</i>\n{examples}\n\n"
            f"<code>Или просто: BTC, ETH, SOL...</code>",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(PivotStates.waiting_for_pivots)
        logger.info("Пользователь %s запросил пивоты", message.from_user.id)

    @router.message(Command("check_pivot"))
    async def cmd_request_check(message: Message, state: FSMContext):
        if not bot.monitored_pairs:
            await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
            return

        examples = "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]])
        await message.answer(
            f"🔍 <b>ПРОВЕРКА БЛИЗОСТИ К ПИВОТАМ</b>\n\n"
            f"💬 Введите тиккер монеты для проверки:\n\n"
            f"<i>Примеры:</i>\n{examples}\n\n"
            f"<code>Или просто: BTC, ETH, SOL...</code>",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.set_state(PivotStates.waiting_for_check)
        logger.info("Пользователь %s запросил проверку пивотов", message.from_user.id)

    @router.message(PivotStates.waiting_for_pivots)
    async def process_show_pivots(message: Message, state: FSMContext):
        user_input = message.text.strip().upper()
        logger.info("Получен тиккер для пивотов: %s", user_input)

        target = _find_pair(bot, user_input)
        if not target:
            await message.answer(
                f"❌ Пара '{user_input}' не найдена.\n\n"
                "Попробуйте из списка:\n"
                + "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]]),
                reply_markup=main_menu(),
            )
            await state.clear()
            return

        await message.answer(f"⏳ Расчет недельных и дневных пивотов для {target}...")

        try:
            pivots_data = await bot.pivot_calculator.get_multi_timeframe_pivots(
                target, bot.data_collector
            )
            if not pivots_data:
                await message.answer(
                    f"❌ Не удалось рассчитать пивоты для {target}", reply_markup=main_menu()
                )
                await state.clear()
                return

            ticker = await bot.data_collector.get_ticker(target)
            current_price = float(ticker.get("last") or 0) if ticker else 0
            if not current_price:
                df = await bot.data_collector.get_ohlcv(target, "15m", limit=1)
                current_price = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0

            msg = bot.pivot_calculator.format_pivot_message(target, pivots_data, current_price)
            await message.answer(msg, disable_web_page_preview=True, reply_markup=main_menu())
            logger.info("Пивоты отправлены для %s", target)

        except Exception:
            logger.exception("Ошибка в process_show_pivots для %s", target)
            await message.answer(f"❌ Ошибка при расчете пивотов", reply_markup=main_menu())

        await state.clear()

    @router.message(PivotStates.waiting_for_check)
    async def process_check_pivot(message: Message, state: FSMContext):
        user_input = message.text.strip().upper()
        logger.info("Получен тиккер для проверки: %s", user_input)

        target = _find_pair(bot, user_input)
        if not target:
            await message.answer(
                f"❌ Пара '{user_input}' не найдена.\n\n"
                "Попробуйте из списка:\n"
                + "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]]),
                reply_markup=main_menu(),
            )
            await state.clear()
            return

        await message.answer(f"⏳ Проверка близости к пивотам для {target}...")

        try:
            pivots_data = await bot.pivot_calculator.get_multi_timeframe_pivots(
                target, bot.data_collector
            )
            if not pivots_data or "1W" not in pivots_data:
                await message.answer(
                    f"❌ Не удалось рассчитать пивоты для {target}", reply_markup=main_menu()
                )
                await state.clear()
                return

            weekly_pivots = pivots_data["1W"]
            confluence = pivots_data.get("confluence", [])

            ticker = await bot.data_collector.get_ticker(target)
            current_price = float(ticker.get("last") or 0) if ticker else 0
            if not current_price:
                df = await bot.data_collector.get_ohlcv(target, "15m", limit=1)
                current_price = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0
            if not current_price:
                await message.answer(
                    f"❌ Не удалось получить цену для {target}", reply_markup=main_menu()
                )
                await state.clear()
                return
            near_level = bot.pivot_calculator.is_near_level(
                current_price, weekly_pivots, threshold_percent=1.0
            )

            has_confluence = False
            if near_level and confluence:
                for c in confluence:
                    if c["weekly_level"] == near_level["level"]:
                        has_confluence = True
                        break

            parts = [
                "🎯 <b>ЦЕНА У НЕДЕЛЬНОГО ПИВОТА!</b>" if near_level else "🔍 <b>ПРОВЕРКА БЛИЗОСТИ К ПИВОТАМ</b>",
                f"Пара: {tv_link(target, interval=240)}",
                f"Цена: {current_price:.6f}",
                "",
            ]

            if near_level:
                parts += [
                    f"<b>Уровень: {near_level['level']}</b>",
                    f"Тип: {near_level['level_type']}",
                    f"Цена уровня: {near_level['price']:.6f}",
                    f"Расстояние: {near_level['distance_percent']:.3f}%",
                ]
                if has_confluence:
                    parts += ["", "⭐️ <b>БОНУС: Есть конфлюэнция с дневным!</b>"]

                parts += ["", "<b>🎯 ТОРГОВЫЙ ПЛАН:</b>"]
                if near_level["level_type"] == "support":
                    parts += [
                        "", "📈 <b>Сценарий LONG (от поддержки):</b>",
                        "  • Ждём подтверждения разворота",
                        "  • Вход после пробоя локального максимума",
                        "  • Стоп за уровень поддержки",
                    ]
                elif near_level["level_type"] == "resistance":
                    parts += [
                        "", "📉 <b>Сценарий SHORT (от сопротивления):</b>",
                        "  • Ждём подтверждения разворота",
                        "  • Вход после пробоя локального минимума",
                        "  • Стоп за уровень сопротивления",
                    ]
                else:
                    parts += [
                        "", "⚡️ <b>Цена у PIVOT POINT - ключевой уровень!</b>",
                        "  • Ждём пробоя в любую сторону",
                        "  • Вход по направлению пробоя",
                        "  • Стоп за противоположную сторону",
                    ]
            else:
                parts += [
                    "✅ Цена далеко от пивотных уровней",
                    "Ближайший уровень >1% от текущей цены",
                ]

            await message.answer("\n".join(parts), disable_web_page_preview=True, reply_markup=main_menu())
            logger.info("Проверка близости отправлена для %s", target)

        except Exception:
            logger.exception("Ошибка в process_check_pivot для %s", target)
            await message.answer("❌ Ошибка при проверке", reply_markup=main_menu())

        await state.clear()

    return router
