"""
Действия меню сигналов.

Стратегия:
1. Сначала читаем bot.recent_signals (события из последнего скана — редкие).
2. Если пусто — делаем live "state scan" с мягкими условиями (текущее состояние рынка).
   State scan использует OHLCV кеш (данные уже в памяти после скана бота).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from core.entry_config import get_primary_entry_tf

from bot.keyboards import main_menu
from core.signal_models import SignalType

logger = logging.getLogger(__name__)

_SIGNAL_TTL_MINUTES = 60   # события из скана живут 1 час


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_cached(bot, signal_type: SignalType, limit: int) -> list:
    """Возвращает сигналы из кеша recent_signals не старше TTL."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_SIGNAL_TTL_MINUTES)
    found = []
    for sym, signals in getattr(bot, "recent_signals", {}).items():
        for sig in signals:
            ts = sig.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if sig.signal_type == signal_type and ts >= cutoff:
                found.append((sym, sig))
    found.sort(key=lambda x: x[1].strength, reverse=True)
    return found[:limit]


async def _state_scan(bot, check_fn, limit: int, sem_size: int = 20) -> list:
    """
    Быстрый live state scan — только по парам с прогретым OHLCV кешем.
    Не делает новых API запросов: данные уже в памяти после скана.
    Если кеш пустой — берёт первые 100 пар.
    """
    # Только пары из OHLCV кеша (tuple-ключи вида (symbol, timeframe, limit))
    cache_data = getattr(getattr(bot.data_collector, '_engine', None), '_cache', None)
    if cache_data is not None:
        cached_symbols = {k[0] for k in getattr(cache_data, '_data', {}).keys()
                         if isinstance(k, tuple) and len(k) >= 1}
        symbols = [s for s in bot.monitored_pairs if s in cached_symbols] or bot.monitored_pairs[:100]
    else:
        symbols = bot.monitored_pairs[:100]

    sem = asyncio.Semaphore(sem_size)
    results = []

    async def _one(sym):
        try:
            async with sem:
                r = await check_fn(sym, bot.data_collector)
                if r:
                    return sym, r
        except Exception:
            pass
        return None

    raw = await asyncio.gather(*[_one(sym) for sym in symbols])
    for r in raw:
        if r:
            results.append(r)
            if len(results) >= limit:
                break
    return results


# ---------------------------------------------------------------------------
# Live state checkers (мягкие условия — состояние, не событие)
# ---------------------------------------------------------------------------

async def _wt_state(sym: str, dc) -> dict | None:
    """WT: пара сейчас в зоне OB (>50) или OS (<-50)."""
    try:
        from core.indicators import calculate_wt
        df = await dc.get_ohlcv(sym, get_primary_entry_tf(), limit=100)
        if df is None or len(df) < 50:
            return None
        df_wt = calculate_wt(df, n1=10, n2=21)
        if "wt1" not in df_wt.columns:
            return None
        wt1 = float(df_wt["wt1"].iloc[-1])
        wt2 = float(df_wt["wt2"].iloc[-1])
        if wt1 < -50:
            return {"wt1": wt1, "wt2": wt2, "zone": "OS", "direction": "LONG", "strength": min(int(abs(wt1)), 95)}
        if wt1 > 50:
            return {"wt1": wt1, "wt2": wt2, "zone": "OB", "direction": "SHORT", "strength": min(int(abs(wt1)), 95)}
    except Exception:
        pass
    return None


async def _anomaly_state(sym: str, dc) -> dict | None:
    """Аномалия: объём текущего бара > 1.5× MA20."""
    try:
        df = await dc.get_ohlcv(sym, get_primary_entry_tf(), limit=50)
        if df is None or len(df) < 25:
            return None
        vol_ma = df["volume"].rolling(20).mean().iloc[-1]
        vol_cur = float(df["volume"].iloc[-1])
        ratio = vol_cur / vol_ma if vol_ma > 0 else 1.0
        if ratio > 1.5:
            price_chg = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
            return {
                "volume_ratio": ratio,
                "price_change": price_chg,
                "direction": "LONG" if price_chg >= 0 else "SHORT",
                "strength": min(int(ratio * 10), 80),
            }
    except Exception:
        pass
    return None


async def _trend_state(sym: str, dc) -> dict | None:
    """Тренд: пара устойчиво в UP или DOWN тренде (последние 5 баров)."""
    try:
        from core.indicators import calculate_trend
        df = await dc.get_ohlcv(sym, "1h", limit=100)
        if df is None or len(df) < 60:
            return None
        df_t = calculate_trend(df, atr_period=43, factor=1.0)
        if "trend" not in df_t.columns:
            return None
        last5 = df_t["trend"].iloc[-5:]
        if all(v == 1 for v in last5):
            return {"direction": "LONG", "bars": 5, "strength": 65}
        if all(v == -1 for v in last5):
            return {"direction": "SHORT", "bars": 5, "strength": 65}
    except Exception:
        pass
    return None


async def _pivot_state(sym: str, dc) -> dict | None:
    """Пивот: цена рядом с локальным уровнем поддержки/сопротивления (< 1.5%)."""
    try:
        from core.indicators import calculate_trend
        df = await dc.get_ohlcv(sym, "1h", limit=150)
        if df is None or len(df) < 50:
            return None
        price = float(df["close"].iloc[-1])
        highs = df["high"].rolling(20, center=True).max()
        lows  = df["low"].rolling(20, center=True).min()
        res_levels = highs[highs == df["high"]].dropna().iloc[-5:]
        sup_levels = lows[lows == df["low"]].dropna().iloc[-5:]
        for level in res_levels:
            d = abs(price - level) / price * 100
            if d < 1.5:
                return {"level": level, "pivot_type": "resistance", "distance": d, "direction": "SHORT"}
        for level in sup_levels:
            d = abs(price - level) / price * 100
            if d < 1.5:
                return {"level": level, "pivot_type": "support", "distance": d, "direction": "LONG"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Menu handlers
# ---------------------------------------------------------------------------

async def show_anomaly_signals(bot, message: Message) -> None:
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return

    found = _get_cached(bot, SignalType.ANOMALY, 30)
    if found:
        lines = ["🚨 <b>Аномалии объёма (события)</b>"]
        for sym, sig in found:
            d = sig.data or {}
            lines.append(
                f"• {sym} {sig.direction.value}"
                f" ΔV×{d.get('volume_ratio', 0):.1f}"
                f" ΔP={d.get('price_change', 0):+.2f}%"
                f" сила={sig.strength:.0f}"
            )
        await message.answer("\n".join(lines))
        return

    # Fallback: live state scan
    results = await _state_scan(bot, _anomaly_state, limit=15)
    if not results:
        await message.answer(f"🚨 Аномалий не найдено (скан {len(bot.monitored_pairs)} пар).")
        return
    results.sort(key=lambda x: x[1].get("strength", 0), reverse=True)
    lines = ["🚨 <b>Аномалии объёма (текущие)</b>"]
    for sym, d in results:
        lines.append(
            f"• {sym} {d['direction']}"
            f" ΔV×{d['volume_ratio']:.1f}"
            f" ΔP={d['price_change']:+.2f}%"
        )
    await message.answer("\n".join(lines))


async def show_wt_signals(bot, message: Message) -> None:
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return

    found = _get_cached(bot, SignalType.WT_SIGNAL, 10)
    if found:
        lines = ["📊 <b>WT сигналы (пересечения)</b>"]
        for sym, sig in found:
            d = sig.data or {}
            lines.append(
                f"• {sym} {sig.direction.value}"
                f" WT1={d.get('wt1', 0):.1f} зона={d.get('zone', '')}"
                f" сила={sig.strength:.0f}"
            )
        await message.answer("\n".join(lines))
        return

    # Fallback: live state scan — пары в зоне OB/OS прямо сейчас
    results = await _state_scan(bot, _wt_state, limit=10)
    if not results:
        await message.answer(f"📊 WT сигналов не найдено (скан {len(bot.monitored_pairs)} пар).")
        return
    results.sort(key=lambda x: x[1].get("strength", 0), reverse=True)
    lines = ["📊 <b>WT зоны (текущие)</b>"]
    for sym, d in results:
        lines.append(f"• {sym} {d['direction']} WT1={d['wt1']:.1f} зона={d['zone']}")
    await message.answer("\n".join(lines))



async def show_trend_signals(bot, message: Message) -> None:
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return

    found = _get_cached(bot, SignalType.TREND_SIGNAL, 8)
    if found:
        lines = ["📈 <b>Трендовые сигналы (смены)</b>"]
        for sym, sig in found:
            d = sig.data or {}
            lines.append(f"• {sym} — {sig.direction.value} сила={sig.strength:.0f} {d.get('pattern', '')}")
        await message.answer("\n".join(lines))
        return

    # Fallback: live state scan — пары в устойчивом тренде 1h
    results = await _state_scan(bot, _trend_state, limit=10)
    if not results:
        await message.answer(f"📈 Тренд-сигналов не найдено (скан {len(bot.monitored_pairs)} пар).")
        return
    longs  = [(s, d) for s, d in results if d["direction"] == "LONG"]
    shorts = [(s, d) for s, d in results if d["direction"] == "SHORT"]
    lines = ["📈 <b>Тренды (текущие, 1h × 5 баров)</b>"]
    if longs:
        lines.append("🟢 LONG:")
        for sym, _ in longs[:5]:
            lines.append(f"  • {sym}")
    if shorts:
        lines.append("🔴 SHORT:")
        for sym, _ in shorts[:5]:
            lines.append(f"  • {sym}")
    await message.answer("\n".join(lines))


async def show_divergence_signals(bot, message: Message) -> None:
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return

    found = _get_cached(bot, SignalType.DIVERGENCE, 8)
    if not found:
        await message.answer(f"💎 Дивергенций не найдено (скан {len(bot.monitored_pairs)} пар).")
        return
    lines = ["💎 <b>Дивергенции</b>"]
    for sym, sig in found:
        d = sig.data or {}
        lines.append(f"• {sym} {d.get('timeframe', sig.timeframe)} — {d.get('type', sig.direction.value)}")
    await message.answer("\n".join(lines))


async def show_pivot_signals(bot, message: Message) -> None:
    if not bot.monitored_pairs:
        await message.answer("⚠️ Сначала запустите мониторинг /monitor", reply_markup=main_menu())
        return

    found = _get_cached(bot, SignalType.PIVOT_REVERSAL, 8)
    if found:
        lines = ["🎯 <b>Пивот-сигналы (события)</b>"]
        for sym, sig in found:
            d = sig.data or {}
            lines.append(
                f"• {sym}: {d.get('level_type', d.get('pivot_type', 'уровень'))}"
                f" Δ={d.get('distance_pct', d.get('distance', 0)):.2f}%"
                f" ({sig.direction.value})"
            )
        await message.answer("\n".join(lines))
        return

    # Fallback: live state scan — цена рядом с уровнем прямо сейчас
    results = await _state_scan(bot, _pivot_state, limit=8)
    if not results:
        await message.answer(f"🎯 Пивот-сигналы: рядом с уровнями ничего не найдено (скан {len(bot.monitored_pairs)} пар).")
        return
    lines = ["🎯 <b>Цена у уровней (текущие)</b>"]
    for sym, d in results:
        lines.append(
            f"• {sym}: {d['pivot_type']} {d['level']:.4g}"
            f" Δ={d['distance']:.2f}% ({d['direction']})"
        )
    await message.answer("\n".join(lines))


async def show_all_signals(bot, message: Message) -> None:
    """Показ всех типов сигналов последовательно."""
    await show_anomaly_signals(bot, message)
    await show_wt_signals(bot, message)
    await show_trend_signals(bot, message)
    await show_divergence_signals(bot, message)
    await show_pivot_signals(bot, message)


async def handle_signal_search(bot, message: Message, state: FSMContext) -> None:
    """Поиск сигналов по символу: переводит в FSM-состояние."""
    await message.answer("🔍 Введите символ для поиска сигналов (например: BTC, ETH)")
    from bot.states import AIAnalysisStates
    await state.set_state(AIAnalysisStates.waiting_for_symbol_search)
