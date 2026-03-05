"""
Команды /scan (скан рынка) и /watch, /watchlist (управление watchlist).
"""
import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.keyboards import main_menu

logger = logging.getLogger(__name__)

MAX_SCAN = 30  # максимальное кол-во пар в одном скане


def get_router(bot) -> Router:
    router = Router()

    # ------------------------------------------------------------------
    # /scan — скан рынка, топ-10 по composite-силе сигнала
    # ------------------------------------------------------------------
    @router.message(Command("scan"))
    async def cmd_scan(message: Message):
        if not bot.monitored_pairs:
            pairs = await bot.data_collector.load_markets()
            bot.monitored_pairs = pairs or []
        if not bot.monitored_pairs:
            await message.answer("⚠️ Нет пар для скана. Запустите мониторинг.", reply_markup=main_menu())
            return

        user_id = message.from_user.id
        watchlist = bot.watchlist_manager.get(user_id)
        watchlist_set = set(watchlist)
        other = [s for s in bot.monitored_pairs if s not in watchlist_set]
        candidates = watchlist + other[:max(0, MAX_SCAN - len(watchlist))]

        await message.answer(
            f"🔍 Сканирую {len(candidates)} пар...\n"
            f"⭐ Watchlist: {len(watchlist)} | Рынок: {len(other[:MAX_SCAN - len(watchlist)])}",
            reply_markup=main_menu(),
        )

        semaphore = asyncio.Semaphore(5)

        async def scan_one(sym):
            try:
                async with semaphore:
                    rec = await bot.trading_intelligence.analyze_symbol(sym)
                    if rec and rec.strength > 0:
                        return sym, rec
            except Exception:
                pass
            return None

        results_raw = await asyncio.gather(*[scan_one(s) for s in candidates])
        results = [r for r in results_raw if r]
        results.sort(key=lambda x: x[1].strength, reverse=True)

        top = results[:10]
        if not top:
            await message.answer("🔍 Значимых сигналов не найдено.", reply_markup=main_menu())
            return

        lines = ["🔍 <b>Топ сигналов рынка</b>"]
        for sym, rec in top:
            star = "⭐ " if sym in watchlist_set else ""
            base = sym.split("/")[0] if "/" in sym else sym.replace("USDT", "")
            direction_str = str(rec.direction).upper()
            if direction_str in ("LONG", "BUY"):
                d_icon = "📈"
            elif direction_str in ("SHORT", "SELL"):
                d_icon = "📉"
            else:
                d_icon = "↔️"
            lines.append(
                f"{star}{d_icon} <b>{base}</b> — {rec.action}"
                f" | Сила: {rec.strength:.2f} | Уверен.: {rec.confidence:.0%}"
            )
        lines.append("\n<i>Используйте /intelligence SYMBOL для полного анализа</i>")
        await message.answer("\n".join(lines), reply_markup=main_menu())

    # ------------------------------------------------------------------
    # /watchlist — показать список избранных пар
    # ------------------------------------------------------------------
    @router.message(Command("watchlist"))
    async def cmd_watchlist(message: Message):
        user_id = message.from_user.id
        symbols = bot.watchlist_manager.get(user_id)
        if not symbols:
            await message.answer(
                "⭐ <b>Watchlist пуст</b>\n\n"
                "Добавьте пары:\n"
                "<code>/watch add BTC</code>",
                reply_markup=main_menu(),
            )
            return
        lines = [f"⭐ <b>Ваш Watchlist</b> ({len(symbols)} пар)"]
        for i, s in enumerate(symbols, 1):
            base = s.split("/")[0] if "/" in s else s.replace("USDT", "")
            lines.append(f"{i}. {base}")
        lines.append("\n<code>/watch add BTC</code> — добавить")
        lines.append("<code>/watch remove BTC</code> — удалить")
        await message.answer("\n".join(lines), reply_markup=main_menu())

    # ------------------------------------------------------------------
    # /watch [add|remove|list] [SYMBOL] — управление watchlist
    # ------------------------------------------------------------------
    @router.message(Command("watch"))
    async def cmd_watch(message: Message):
        user_id = message.from_user.id
        parts = message.text.strip().split()

        # /watch или /watch list
        if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == "list"):
            await cmd_watchlist(message)
            return

        action = parts[1].lower() if len(parts) >= 2 else ""
        raw_symbol = parts[2].upper() if len(parts) >= 3 else ""

        if action not in ("add", "remove") or not raw_symbol:
            await message.answer(
                "Использование:\n"
                "<code>/watch add BTC</code>\n"
                "<code>/watch remove BTC</code>\n"
                "<code>/watch list</code>",
                reply_markup=main_menu(),
            )
            return

        # Нормализуем символ
        if not raw_symbol.endswith("USDT"):
            raw_symbol = f"{raw_symbol}USDT"
        if not bot.monitored_pairs:
            pairs = await bot.data_collector.load_markets()
            bot.monitored_pairs = pairs or []

        normalized = bot.data_collector.normalize_symbol(raw_symbol)
        base_only = raw_symbol.replace("USDT", "")
        slash_usdt = f"{base_only}/USDT"
        target = None
        for cand in (normalized, slash_usdt + ":USDT", slash_usdt, raw_symbol):
            if cand in bot.monitored_pairs:
                target = cand
                break
        if not target:
            for p in bot.monitored_pairs:
                if p.startswith(base_only + "/USDT"):
                    target = p
                    break

        if not target:
            await message.answer(
                f"❌ Пара '{raw_symbol}' не найдена на бирже.",
                reply_markup=main_menu(),
            )
            return

        base_display = target.split("/")[0] if "/" in target else target.replace("USDT", "")

        if action == "add":
            if bot.watchlist_manager.count(user_id) >= 20:
                await message.answer(
                    "❌ Максимум 20 пар в watchlist.",
                    reply_markup=main_menu(),
                )
                return
            ok = bot.watchlist_manager.add(user_id, target)
            if ok:
                await message.answer(f"⭐ <b>{base_display}</b> добавлен в watchlist.", reply_markup=main_menu())
            else:
                await message.answer("❌ Ошибка при добавлении.", reply_markup=main_menu())

        elif action == "remove":
            ok = bot.watchlist_manager.remove(user_id, target)
            if ok:
                await message.answer(f"✅ <b>{base_display}</b> удалён из watchlist.", reply_markup=main_menu())
            else:
                await message.answer("❌ Ошибка при удалении.", reply_markup=main_menu())

    return router
