"""
Действия меню сигналов — standalone-функции вместо методов MenuHandler.
"""
import asyncio
import logging

from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu

logger = logging.getLogger(__name__)


async def show_anomaly_signals(bot, message: Message) -> None:
    """Показ аномалий объема по всем парам."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                is_anom, info = bot.detector.check_spike(sym, bot.data_collector)
                if is_anom:
                    return sym, info
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:30]

    if not found:
        await message.answer(f"🚨 Аномалий не найдено (скан {len(symbols)} пар).")
        return
    lines = ["🚨 <b>Последние аномалии</b>"]
    for sym, inf in found:
        lines.append(f"• {sym} — ΔV≈{inf.get('volume_change', 0):.1f}% ΔP≈{inf.get('price_change', 0):.2f}%")
    await message.answer("\n".join(lines))


async def show_wt_signals(bot, message: Message) -> None:
    """Показ Wavetrend-сигналов по всем парам."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                is_sig, info = await bot.detector.check_wt_signal(sym, bot.data_collector)
                if is_sig:
                    return sym, info
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:10]

    if not found:
        await message.answer(f"📊 WT сигналов не найдено (скан {len(symbols)} пар).")
        return
    lines = ["📊 <b>WT сигналы</b>"]
    for sym, inf in found:
        lines.append(f"• {sym} — WT1={inf.get('wt1', 0):.1f} WT2={inf.get('wt2', 0):.1f} зона={inf.get('zone','')}")
    await message.answer("\n".join(lines))


async def show_mtf_signals(bot, message: Message) -> None:
    """Показ MTF-сигналов по всем парам."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                is_sig, info = await bot.detector.check_mtf_signal(sym, bot.data_collector)
                if is_sig:
                    return sym, info
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:8]

    if not found:
        await message.answer(f"🔄 MTF сигналов не найдено (скан {len(symbols)} пар).")
        return
    lines = ["🔄 <b>MTF сигналы</b>"]
    for sym, inf in found:
        lines.append(f"• {sym} — {inf.get('pattern','signal')}")
    await message.answer("\n".join(lines))


async def show_trend_signals(bot, message: Message) -> None:
    """Показ трендовых сигналов по всем парам."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                try:
                    is_sig, info = await bot.trading_intelligence.check_trend_following_signal(  # type: ignore
                        sym, bot.data_collector, bot.divergence_detector, bot.pivot_calculator
                    )
                except AttributeError:
                    from core.trend_signals import check_trend_following_signal
                    is_sig, info = await check_trend_following_signal(
                        sym, bot.data_collector, bot.divergence_detector, bot.pivot_calculator
                    )
                if is_sig:
                    return sym, info
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:8]

    if not found:
        await message.answer(f"📈 Тренд-сигналов не найдено (скан {len(symbols)} пар).")
        return
    lines = ["📈 <b>Трендовые сигналы</b>"]
    for sym, inf in found:
        lines.append(f"• {sym} — {inf.get('pattern','signal')}")
    await message.answer("\n".join(lines))


async def show_divergence_signals(bot, message: Message) -> None:
    """Показ дивергенций по всем парам."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    timeframes = ["15m", "1h"]
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                for tf in timeframes:
                    try:
                        has_div, div_info = await bot.divergence_detector.detect_divergence(
                            sym, bot.data_collector, timeframe=tf
                        )
                        if has_div:
                            return sym, tf, div_info
                    except Exception:
                        continue
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    found = [r for r in raw_results if r][:8]

    if not found:
        await message.answer(f"💎 Дивергенций не найдено (скан {len(symbols)} пар).")
        return
    lines = ["💎 <b>Дивергенции</b>"]
    for sym, tf, d in found:
        lines.append(f"• {sym} {tf} — {d.get('type','divergence')}")
    await message.answer("\n".join(lines))


async def show_pivot_signals(bot, message: Message) -> None:
    """Показ пар, цена которых рядом с недельными пивотами (все пары)."""
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return
    calc = bot.pivot_calculator
    symbols = bot.monitored_pairs
    semaphore = asyncio.Semaphore(10)

    async def process_symbol(sym: str):
        try:
            async with semaphore:
                piv = await calc.get_multi_timeframe_pivots(sym, bot.data_collector)
                if not piv or "1W" not in piv:
                    return None
                df = await bot.data_collector.get_ohlcv(sym, "1m", limit=1)
                if df is None or df.empty:
                    return None
                price = float(df["close"].iloc[-1])
                near = calc.is_near_level(price, piv["1W"], 0.7)
                if near:
                    return sym, near
        except Exception:
            return None

    raw_results = await asyncio.gather(*[process_symbol(sym) for sym in symbols])
    results = [r for r in raw_results if r][:8]

    if not results:
        await message.answer(f"🎯 Пивот-сигналы: рядом с уровнями ничего не найдено (скан {len(symbols)} пар).")
        return
    lines = ["🎯 <b>Цена у недельных уровней</b>"]
    for sym, near in results:
        lines.append(f"• {sym}: {near['level']} {near['level_type']} Δ={near['distance_percent']:.2f}%")
    await message.answer("\n".join(lines))


async def show_all_signals(bot, message: Message) -> None:
    """Показ всех типов сигналов последовательно."""
    await show_anomaly_signals(bot, message)
    await show_wt_signals(bot, message)
    await show_mtf_signals(bot, message)
    await show_trend_signals(bot, message)
    await show_divergence_signals(bot, message)
    await show_pivot_signals(bot, message)


async def handle_signal_search(bot, message: Message, state: FSMContext) -> None:
    """Поиск сигналов по символу: переводит в FSM-состояние."""
    await message.answer("🔍 Введите символ для поиска сигналов (например: BTC, ETH)")
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol_search)
