"""
Команды AI-анализа: /intelligence.
FSM: process_symbol_input, process_symbol_search.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from bot.keyboards import main_menu
from core.trading_intelligence import format_intelligence_message
from bot.states import AIAnalysisStates

logger = logging.getLogger(__name__)


def _resolve_symbol(bot, symbol: str):
    """Преобразует ввод пользователя в символ биржи. Возвращает (target, display)."""
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) < 2:
        return None, symbol or "?"
    simple_usdt = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
    normalized = bot.data_collector.normalize_symbol(symbol)
    slash_usdt = f"{simple_usdt.replace('USDT', '')}/USDT"
    if not bot.monitored_pairs:
        return None, symbol
    for cand in (normalized, slash_usdt + ":USDT", slash_usdt, simple_usdt):
        if cand in bot.monitored_pairs:
            return cand, symbol
    base = simple_usdt.replace("USDT", "")
    for p in bot.monitored_pairs:
        if p.startswith(base + "/USDT"):
            return p, symbol
    # Символ не мониторируется (отфильтрован по объёму), но может существовать на бирже.
    # Возвращаем нормализованный символ — analyze_symbol сам вернёт None если данных нет.
    if normalized and "/" in normalized:
        return normalized, symbol
    return None, symbol


def _fmt_p(price: float) -> str:
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    return f"{price:.8f}"


def _build_pivot_summary(bot, symbol: str, current_price: float) -> str:
    """Краткая сводка ближайших пивотных уровней из кеша (не делает API-запросов)."""
    if not hasattr(bot, "pivot_calculator") or current_price <= 0:
        return ""
    lines = []
    for tf, label in [("1D", "Дн"), ("1W", "Нед"), ("1M", "Мес")]:
        pivots = bot.pivot_calculator.pivot_cache.get(f"{symbol}_{tf}")
        if not pivots:
            continue
        nearest = bot.pivot_calculator.get_nearest_levels(current_price, pivots, count=1)
        res = nearest.get("resistance", [])
        sup = nearest.get("support", [])
        parts = []
        if res:
            key, price, dist = res[0]
            parts.append(f"⬆️ {key}={_fmt_p(price)} (+{dist:.1f}%)")
        if sup:
            key, price, dist = sup[0]
            parts.append(f"⬇️ {key}={_fmt_p(price)} (-{dist:.1f}%)")
        if parts:
            lines.append(f"  [{label}] " + "  ".join(parts))
    if not lines:
        return ""
    return "<b>📍 Ближайшие пивоты:</b>\n" + "\n".join(lines)


async def _run_intelligence_analysis(bot, message: Message, target_symbol: str, display_symbol: str, user_id: int):
    analysis_msg = await message.answer(
        f"🔍 <b>Анализирую {display_symbol}...</b>\n"
        "Собираю данные и выполняю комплексный анализ...",
        reply_markup=main_menu(),
    )
    try:
        recommendation = await bot.trading_intelligence.analyze_symbol(target_symbol, manual_request=True)
        if not recommendation:
            # Диагностика: пробуем понять причину
            reason = "нет торгового сигнала"
            try:
                df = await bot.data_collector.get_ohlcv(target_symbol, "15m", limit=10)
                if df is None or df.empty:
                    reason = "пара не торгуется на бирже или нет данных"
                elif len(df) < 50:
                    reason = f"мало исторических данных ({len(df)} свечей, нужно 50+)"
                else:
                    ticker = await bot.data_collector.get_ticker(target_symbol)
                    vol = (ticker or {}).get("quoteVolume") or 0
                    if vol < 500_000:
                        reason = f"низкий объём торгов (${vol/1e6:.2f}M за 24ч, нужно >$0.5M)"
            except Exception:
                pass
            error_text = f"❌ Нет анализа для {display_symbol}.\n<i>Причина: {reason}</i>"
            try:
                await analysis_msg.edit_text(error_text)
            except Exception:
                await message.answer(error_text, reply_markup=main_menu())
            return

        # Pivot TP — применяем ДО форматирования, чтобы пользователь видел реальный TP
        distance_to_pivot_pct = 0.0
        if hasattr(bot, "pivot_calculator"):
            direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
            entry_price = recommendation.entry_price or 0
            if direction_val in ("LONG", "SHORT") and entry_price > 0:
                pivot_result = bot.pivot_calculator.get_pivot_tp_with_source(
                    direction=direction_val,
                    entry_price=entry_price,
                    symbol=target_symbol,
                    stop_loss=recommendation.stop_loss,
                    min_r=1.5,
                )
                if pivot_result:
                    pivot_tp, pivot_src = pivot_result
                    recommendation.take_profit = pivot_tp
                    recommendation.tp_source = pivot_src
                    distance_to_pivot_pct = abs(pivot_tp - entry_price) / entry_price * 100

        intelligence_message = await format_intelligence_message(recommendation)

        # Ближайшие пивотные уровни (из кеша, без API)
        current_price = recommendation.market_context.current_price
        pivot_summary = _build_pivot_summary(bot, target_symbol, current_price)
        if pivot_summary:
            intelligence_message += "\n\n" + pivot_summary

        try:
            await analysis_msg.edit_text(intelligence_message)
        except Exception:
            await message.answer(intelligence_message, reply_markup=main_menu())

        try:
            await message.answer("Выберите действие:", reply_markup=main_menu())
        except Exception:
            pass

        # История сделок по паре
        try:
            from core.trading.performance_engine import PerformanceEngine
            pe = PerformanceEngine(bot.trade_simulator.db_path)
            history = pe.pair_history(target_symbol, limit=5)
            if history:
                lines = [f"📚 <b>История по {display_symbol}</b>:"]
                for h in history:
                    icon = "✅" if h["status"] == "TP" else "❌" if h["status"] == "SL" else "⏰"
                    r = h["R_multiple"] or 0
                    lines.append(f"{icon} {h['signal_type']} {h['direction']} R={r:.2f}")
                await message.answer("\n".join(lines))
        except Exception:
            pass

        bot.subscription_manager.increment_signal_count(user_id, "intelligence")
        bot.signal_counters["total"] += 1

        try:
            extra = {"distance_to_pivot_pct": distance_to_pivot_pct} if distance_to_pivot_pct else None
            await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector, extra_features=extra)
        except Exception as e:
            logger.debug("TradeSimulator register_trade: %s", e)

    except Exception:
        logger.exception("Ошибка комплексного анализа для %s", display_symbol)
        error_text = f"❌ Ошибка анализа {display_symbol}"
        try:
            await analysis_msg.edit_text(error_text)
        except Exception:
            await message.answer(error_text, reply_markup=main_menu())
        await message.answer("Попробуйте другой символ", reply_markup=main_menu())


def get_router(bot) -> Router:
    router = Router()

    @router.message(Command("intelligence"))
    async def cmd_intelligence(message: Message):
        user_id = message.from_user.id

        if not bot.subscription_manager.can_receive_signal(user_id, "intelligence"):
            await message.answer(
                "❌ Превышен лимит сигналов для вашей подписки.\n"
                "💎 Обновите подписку для получения большего количества сигналов.",
                reply_markup=main_menu(),
            )
            return

        text = message.text.strip()
        if len(text.split()) < 2:
            await message.answer(
                "🤖 <b>Комплексный анализ</b>\n\n"
                "Использование: <code>/intelligence BTCUSDT</code>\n\n"
                "Эта команда выполняет комплексный анализ символа, объединяя:\n"
                "• Аномалии объема\n"
                "• Wavetrend сигналы\n"
                "• Мультитаймфреймовый анализ\n"
                "• Трендовые сигналы\n"
                "• Дивергенции\n"
                "• Пивотные уровни\n\n"
                "Результат: единая торговая рекомендация с оценкой силы и риска.",
                reply_markup=main_menu(),
            )
            return

        symbol = text.split()[1].upper()
        if not bot.monitored_pairs:
            pairs = await bot.data_collector.load_markets()
            bot.monitored_pairs = pairs or []

        target_symbol, display_symbol = _resolve_symbol(bot, symbol)
        if not target_symbol:
            examples = "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]])
            await message.answer(
                f"❌ Пара '{display_symbol}' не найдена.\n\n"
                f"Попробуйте из списка:\n{examples}\n\n"
                f"<code>Или просто: BTC, ETH, SOL...</code>",
                reply_markup=main_menu(),
            )
            return

        await _run_intelligence_analysis(bot, message, target_symbol, display_symbol, user_id)

    @router.message(AIAnalysisStates.waiting_for_symbol)
    async def process_symbol_input(message: Message, state: FSMContext):
        symbol = message.text.strip().upper()
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        logger.info("🧠 [AI] Обработка символа '%s' от %s", symbol, username)

        try:
            if len(symbol) < 2 or len(symbol) > 15:
                await message.answer(
                    "❌ Неверный формат символа. Введите корректный тикер (например: BTC, ETH, SOL).",
                    reply_markup=main_menu(),
                )
                await state.clear()
                return

            if not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"

            if not bot.subscription_manager.can_receive_signal(user_id, "intelligence"):
                await message.answer(
                    "❌ Превышен лимит сигналов для вашей подписки.\n"
                    "💎 Обновите подписку для получения большего количества сигналов.",
                    reply_markup=main_menu(),
                )
                await state.clear()
                return

            if not bot.monitored_pairs:
                pairs = await bot.data_collector.load_markets()
                bot.monitored_pairs = pairs or []

            target_symbol, display_symbol = _resolve_symbol(bot, symbol)
            if not target_symbol:
                examples = "\n".join([f"  • {p.split('/')[0]}" for p in bot.monitored_pairs[:10]])
                await message.answer(
                    f"❌ Пара '{display_symbol}' не найдена.\n\n"
                    f"Попробуйте из списка:\n{examples}\n\n"
                    f"<code>Или просто: BTC, ETH, SOL...</code>",
                    reply_markup=main_menu(),
                )
                await state.clear()
                return

            await _run_intelligence_analysis(bot, message, target_symbol, display_symbol, user_id)
            await state.clear()

        except Exception:
            logger.exception("💥 [AI] Ошибка при обработке символа '%s' от %s", symbol, username)
            await message.answer("❌ Произошла ошибка при анализе. Попробуйте еще раз.", reply_markup=main_menu())
            await state.clear()

    @router.message(AIAnalysisStates.waiting_for_symbol_search)
    async def process_symbol_search(message: Message, state: FSMContext):
        symbol = message.text.strip().upper()
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        logger.info("🔍 [SEARCH] Поиск символа '%s' от %s", symbol, username)

        try:
            if len(symbol) < 2 or len(symbol) > 10:
                await message.answer("❌ Неверный формат символа. Введите корректный тикер (например: BTC, ETH, SOL)")
                return

            if not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"

            await message.answer(f"🔍 Ищу информацию о {symbol}...")

            normalized = bot.data_collector.normalize_symbol(symbol)
            ticker = await bot.data_collector.get_ticker(normalized)

            if not ticker:
                await message.answer(f"❌ Не удалось получить данные по {symbol}", reply_markup=main_menu())
                await state.clear()
                return

            last = float(ticker.get("last") or ticker.get("close") or 0)
            base_volume = float(ticker.get("baseVolume") or 0)
            quote_volume = float(ticker.get("quoteVolume") or 0)
            percentage = ticker.get("percentage")
            if percentage is None:
                try:
                    open_p = float(ticker.get("open") or 0)
                    if open_p:
                        percentage = (last - open_p) / open_p * 100.0
                except Exception:
                    percentage = 0.0

            def fmt_money(v: float) -> str:
                try:
                    if v >= 1_000_000_000:
                        return f"${v/1_000_000_000:.2f}B"
                    if v >= 1_000_000:
                        return f"${v/1_000_000:.2f}M"
                    if v >= 1_000:
                        return f"${v/1_000:.2f}K"
                    return f"${v:.4f}"
                except Exception:
                    return str(v)

            vol_text = fmt_money(quote_volume or base_volume)
            price_text = f"${last:.6f}" if last < 1 else f"${last:.2f}"
            pct_text = f"{float(percentage):+.2f}%" if percentage is not None else "N/A"

            await message.answer(
                f"🔍 <b>Результаты поиска для {symbol}</b>\n\n"
                f"📊 Найдена информация о паре\n"
                f"📈 Текущая цена: {price_text}\n"
                f"📊 Объем 24ч: {vol_text}\n"
                f"📈 Изменение 24ч: {pct_text}",
                reply_markup=main_menu(),
            )
            await state.clear()

        except Exception:
            logger.exception("💥 [SEARCH] Ошибка при поиске символа '%s' от %s", symbol, username)
            await message.answer("❌ Произошла ошибка при поиске. Попробуйте еще раз.", reply_markup=main_menu())
            await state.clear()

    return router
