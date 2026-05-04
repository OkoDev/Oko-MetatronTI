"""
bot/handlers/deep_analysis_handler.py — ARCH-29: команда /deep SYMBOL [TF].

Глубокий анализ символа: SMC структура + FVG карта + конфлюэнции + два сценария.

Использование:
    /deep FAI         → анализ на дефолтном ТФ (4h)
    /deep BTC 1h      → анализ на 1h
    /deep ETH 15m     → анализ на 15m
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_menu

logger = logging.getLogger(__name__)

_VALID_TFS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}
_DEFAULT_TF = "4h"


def get_router(bot) -> Router:
    router = Router()

    @router.message(Command("deep"))
    async def cmd_deep(message: Message):
        args = message.text.strip().split()[1:]  # [SYMBOL] [TF]

        if not args:
            await message.answer(
                "📊 <b>Глубокий анализ</b>\n\n"
                "Использование: <code>/deep SYMBOL [TF]</code>\n\n"
                "Примеры:\n"
                "  <code>/deep FAI 4h</code>\n"
                "  <code>/deep BTC 1h</code>\n"
                "  <code>/deep ETH 15m</code>\n\n"
                "Таймфреймы: 15m, 1h, 4h (по умолчанию)\n\n"
                "Что показывает:\n"
                "• Структура рынка (SMC: тренд, CHoCH, BOS)\n"
                "• Активные FVG зоны\n"
                "• FVG + Пивот конфлюэнции (score)\n"
                "• Кросс-ТФ пивотные конфлюэнции (1W+1D, 1M+1W)\n"
                "• Тройные конфлюэнции\n"
                "• Два сценария с конкретными уровнями\n"
                "• Текущий сетап",
                reply_markup=main_menu(),
            )
            return

        # Разбираем аргументы
        raw_symbol = args[0].upper()
        tf = _DEFAULT_TF
        if len(args) >= 2:
            tf_arg = args[1].lower()
            if tf_arg in _VALID_TFS:
                tf = tf_arg
            else:
                await message.answer(
                    f"❌ Неверный таймфрейм: <code>{tf_arg}</code>\n"
                    f"Доступные: {', '.join(sorted(_VALID_TFS))}",
                    reply_markup=main_menu(),
                )
                return

        # Резолвим символ
        if not bot.monitored_pairs:
            pairs = await bot.data_collector.load_markets()
            bot.monitored_pairs = pairs or []

        from bot.handlers.analysis_handlers import _resolve_symbol
        target_symbol, display_symbol = _resolve_symbol(bot, raw_symbol)
        if not target_symbol:
            await message.answer(
                f"❌ Пара <b>{raw_symbol}</b> не найдена в списке мониторинга.\n"
                f"Попробуйте: <code>/deep BTC 4h</code>",
                reply_markup=main_menu(),
            )
            return

        # Статус
        wait_msg = await message.answer(
            f"🔍 Анализирую <b>{display_symbol}</b> · {tf}...\n"
            "<i>Собираю SMC структуру и конфлюэнции...</i>",
        )

        try:
            from core.smc.deep_analysis import build_deep_analysis
            from core.ui.chart_builder import build_deep_chart

            text, fvg_zones, cross_pivots, df, daily_piv, weekly_piv, all_fvgs = \
                await build_deep_analysis(target_symbol, tf, bot)

            # Пробуем сгенерировать чарт — df уже загружен, ccxt не нужен
            png_bytes = None
            if bot.config.get("signals.send_chart", True) and df is not None:
                try:
                    import asyncio as _asyncio
                    loop = _asyncio.get_event_loop()
                    png_bytes = await loop.run_in_executor(
                        None,
                        build_deep_chart,
                        df, target_symbol, tf,
                        daily_piv or None,
                        weekly_piv or None,
                        fvg_zones or None,
                        cross_pivots or None,
                        all_fvgs or None,
                    )
                except Exception:
                    logger.exception("cmd_deep: не удалось сгенерировать чарт для %s", target_symbol)

            if png_bytes:
                from aiogram.types import BufferedInputFile
                await wait_msg.delete()
                if len(text) <= 1024:
                    await message.answer_photo(
                        BufferedInputFile(png_bytes, filename="deep.png"),
                        caption=text,
                        reply_markup=main_menu(),
                    )
                else:
                    # Текст длиннее 1024 — фото без caption, текст отдельно
                    await message.answer_photo(
                        BufferedInputFile(png_bytes, filename="deep.png"),
                    )
                    await message.answer(text, reply_markup=main_menu())
            else:
                try:
                    await wait_msg.edit_text(text)
                except Exception:
                    await message.answer(text, reply_markup=main_menu())

        except Exception:
            logger.exception("cmd_deep: ошибка для %s %s", target_symbol, tf)
            try:
                await wait_msg.edit_text(f"❌ Ошибка анализа {display_symbol} {tf}")
            except Exception:
                await message.answer(f"❌ Ошибка анализа {display_symbol} {tf}", reply_markup=main_menu())

    return router
