"""
Действия меню пивотов — standalone-функции вместо методов MenuHandler.
"""
import asyncio
import logging

from aiogram.types import Message

from core.keyboards import main_menu

logger = logging.getLogger(__name__)


async def show_pivot_reversals(bot, message: Message) -> None:
    """Показ разворотов от пивотов (скан 30 пар)."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    from core.pivot_reversal import check_pivot_level_signal

    symbols = bot.monitored_pairs[:30]
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                has_signal, info = await check_pivot_level_signal(
                    sym, bot.data_collector, bot.pivot_calculator_fixed
                )
                if has_signal:
                    return sym, info
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:5]

    if not found:
        await message.answer("📈 Развороты от пивотов не найдены (скан 30 пар).")
        return
    lines = ["📈 <b>Развороты от пивотов</b>"]
    for sym, info in found:
        lines.append(f"• {sym}: {info.get('direction', 'N/A')} у {info.get('level', 'N/A')}")
    await message.answer("\n".join(lines))


async def show_key_levels(bot, message: Message) -> None:
    """Показ ключевых уровней (конфлюэнции) для первой пары из мониторинга."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    sym = bot.monitored_pairs[0]
    try:
        piv = await bot.pivot_calculator_fixed.get_multi_timeframe_pivots(sym, bot.data_collector)
        if not piv or "confluence" not in piv or not piv["confluence"]:
            await message.answer(f"🎯 Конфлюэнций не найдено для {sym}")
            return
        lines = [f"🎯 <b>Ключевые уровни (конфлюэнции) {sym}</b>"]
        for conf in piv["confluence"][:5]:
            lines.append(
                f"• {conf['weekly_level']} (1W) = {conf['daily_level']} (1D): "
                f"${conf['weekly_price']:.2f} ({conf['strength']})"
            )
        await message.answer("\n".join(lines))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


async def show_pivot_analysis(bot, message: Message) -> None:
    """Комплексный анализ пивотов для первой пары из мониторинга."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    sym = bot.monitored_pairs[0]
    try:
        piv = await bot.pivot_calculator_fixed.get_multi_timeframe_pivots(sym, bot.data_collector)
        if not piv:
            await message.answer(f"❌ Не удалось получить пивоты для {sym}")
            return
        df = await bot.data_collector.get_ohlcv(sym, "1m", limit=1)
        price = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0
        lines = [f"📊 <b>Анализ пивотов {sym}</b>", f"Текущая цена: ${price:.2f}", ""]
        if "1W" in piv:
            lines.append("📅 <b>Недельные:</b>")
            lines.append(f"PP: ${piv['1W']['PP']:.2f}")
        if "1D" in piv:
            lines.append("📅 <b>Дневные:</b>")
            lines.append(f"PP: ${piv['1D']['PP']:.2f}")
        if "confluence" in piv and piv["confluence"]:
            lines.append(f"\n🎯 Конфлюэнций: {len(piv['confluence'])}")
        await message.answer("\n".join(lines))
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
