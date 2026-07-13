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

from bot.keyboards import main_menu
from core.mtf.mtf_checker import collect_mtf_data
from bot.monitoring import start_monitoring, stop_monitoring

logger = logging.getLogger(__name__)


def build_status_block(bot) -> str:
    """Текущее состояние системы — 4 строки. Используется в /start и заголовках меню."""
    is_mon = "🟢 запущен" if getattr(bot, "is_monitoring", False) else "⏹ остановлен"
    n_pairs = len(getattr(bot, "monitored_pairs", []) or [])

    open_count = "—"
    wr_str = "—"
    avg_r_str = "—"
    try:
        from core.trading.performance_engine import PerformanceEngine
        db = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
        pe = PerformanceEngine(db)
        s = pe.summary() or {}
        open_count = s.get("open_count", 0)
        # WR/avgR за последние 50 закрытых
        recent = pe.recent_closed(limit=50) or []
        if recent:
            rs = [t["R_multiple"] for t in recent if t.get("R_multiple") is not None]
            if rs:
                wins = sum(1 for r in rs if r > 0)
                wr_str = f"{wins / len(rs) * 100:.0f}%"
                avg_r_str = f"{sum(rs) / len(rs):+.2f}"
    except Exception:
        pass

    return (
        f"📊 <b>Статус системы:</b>\n"
        f"• Мониторинг: {is_mon}\n"
        f"• Пар отслеживается: <b>{n_pairs}</b>\n"
        f"• Открытых сделок: <b>{open_count}</b>\n"
        f"• WR за 50 сделок: <b>{wr_str}</b> · avgR: <b>{avg_r_str}</b>"
    )


def build_help_text() -> str:
    """Единая справка — используется и /help, и кнопкой «ℹ️ Помощь»."""
    return (
        "📚 <b>СПРАВКА — Oko MTF Bot</b>\n\n"
        "Бот анализирует крипторынок на 7 таймфреймах, генерирует сигналы и "
        "регистрирует сделки в симуляторе для отслеживания эффективности.\n\n"

        "<b>🔧 Основные команды:</b>\n"
        "/start — главное меню + статус\n"
        "/monitor — запустить/остановить мониторинг\n"
        "/stats — счётчики сигналов и пар\n"
        "/scan — скан рынка (топ-10 по силе)\n"
        "/top — топ-10 пар по объёму\n"
        "/reset — сбросить счётчики\n\n"

        "<b>📊 Анализ пары:</b>\n"
        "🔋 <b>Просто напиши тикер</b> (btc, sol, bonk) — паспорт монеты:\n"
        "   чарт + WT/SMC/Эллиотт/пивоты/OI/магниты/компас из Куба\n"
        "/deep BTC — глубокий разбор (SMC + MTF)\n"
        "/pivots BTC — пивотные уровни\n"
        "/check_pivot BTC — близость к пивотам\n"
        "/mtf — MTF snapshot первой пары\n\n"

        "<b>🔍 Watchlist:</b>\n"
        "/watch add BTC — добавить пару\n"
        "/watch remove BTC — удалить\n"
        "/watchlist — мой watchlist\n"
        "/wl — Signal Watch List (ожидающие)\n"
        "/wlr — детальный отчёт по WL\n\n"

        "<b>🎯 Типы сигналов:</b>\n"
        "🚨 Аномалии — всплески объёма/цены\n"
        "📊 WT — Wavetrend (отскоки от OB/OS)\n"
        "📊 WT_B — WT-кросс в OS/OB + дивергенция на 1h\n"
        "🔄 MTF — мультитаймфрейм-конфлюенция\n"
        "📈 Тренд — мультитаймфрейм-тренд (4h→1h) + откат на 15m/5m\n"
        "💎 Дивергенции — расхождение цены и WT\n"
        "🎯 Развороты от пивотов\n"
        "🧩 Confluence — комбо WT+пивот+SMC\n"
        "📐 SMC — Smart Money Concepts (OB/FVG/BOS)\n\n"

        "<b>📐 Глоссарий:</b>\n"
        "• <b>R</b> — единица риска (1R = расстояние до SL)\n"
        "• <b>WR</b> — % выигрышных сделок\n"
        "• <b>avgR</b> — среднее R по закрытым\n"
        "• <b>TSL</b> — Trailing Stop Loss (защита прибыли)\n"
        "• <b>P1/P2/P3</b> — приоритет входа (Entry Matrix)\n"
        "• <b>SMC</b> — Smart Money Concepts\n\n"

        "<b>📟 Где смотреть результаты:</b>\n"
        "• Дашборд — http://localhost:8000\n"
        "• История сделок — кнопка «📚 История»\n"
        "• Статистика по типам — «📊 Аналитика»\n\n"

        "Используйте меню для навигации ↓"
    )


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

        first = message.from_user.first_name or "трейдер"
        status = build_status_block(bot)

        await message.answer(
            f"👋 Привет, <b>{first}</b>!\n\n"
            f"Я — <b>Oko MTF Bot</b>. Анализирую крипторынок на 7 таймфреймах "
            f"и регистрирую сделки в симуляторе.\n\n"
            f"{status}\n\n"
            f"💡 /help — список команд и глоссарий\n"
            f"Используйте меню ниже ↓",
            reply_markup=main_menu(),
        )

    @router.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(build_help_text(), reply_markup=main_menu())

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
            "anomaly": 0, "wt_signal": 0, "mtf_alert": 0,
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

    # DEV-22: /wl — текущий WATCH LIST (пары ожидающие эскалации)
    @router.message(Command("wl"))
    async def cmd_wl(message: Message):
        wl = getattr(bot, "signal_watch_list", None)
        if wl is None or len(wl) == 0:
            await message.answer("📋 <b>Watch List пуст</b> — нет активных WATCH-наблюдений.")
            return

        entries = wl.get_all()
        dir_emoji = {"LONG": "🟢", "SHORT": "🔴"}
        lines = [f"📋 <b>Watch List</b> ({len(entries)} пар)\n"]
        for e in entries:
            sym_short = e["symbol"].split("/")[0]
            ttl_h = e["ttl_minutes"] // 60
            ttl_m = e["ttl_minutes"] % 60
            pivot_str = f" | {e['pivot_key']}={e['pivot_level']:.4f}" if e["pivot_level"] > 0 else ""
            div_str = f" | div×{e['div_count']}" if e["div_count"] > 0 else ""
            lines.append(
                f"{dir_emoji.get(e['direction'], '⚪')} <b>{sym_short}</b> "
                f"score={e['score']:.0f} · {e['reason']}{pivot_str}{div_str}\n"
                f"   ⏱ TTL: {ttl_h}h {ttl_m}m"
            )

        await message.answer("\n".join(lines), reply_markup=main_menu())

    # DEV-223: /позиции — открытые сделки с текущим P&L
    @router.message(Command("позиции", "positions", "pos"))
    async def cmd_positions(message: Message):
        try:
            import sqlite3 as _sq
            db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
            with _sq.connect(db_path, timeout=10) as _conn:
                rows = _conn.execute(
                    "SELECT id, symbol, direction, signal_type, entry_price, stop_loss, "
                    "take_profit, tsl_activated, tsl_tf, original_sl, created_at "
                    "FROM simulated_trades WHERE status='OPEN' ORDER BY created_at DESC LIMIT 20"
                ).fetchall()
        except Exception as _e:
            await message.answer(f"⚠️ Ошибка чтения БД: {_e}")
            return

        if not rows:
            await message.answer("📭 <b>Нет открытых сделок</b>", parse_mode="HTML")
            return

        lines = [f"📊 <b>Открытые сделки ({len(rows)})</b>\n"]
        ws = getattr(bot, "ws_feed", None)

        for row in rows:
            tid, sym, direction, sig_type, entry, sl, tp, tsl_act, tsl_tf, orig_sl, created_at = row
            entry = float(entry or 0)
            sl_orig = float(orig_sl or sl or 0)
            one_r = abs(entry - sl_orig) if sl_orig and sl_orig != entry else None

            # Текущая цена — сначала WsFeed, потом None
            cur = None
            if ws is not None:
                cur = ws.get_price(sym)

            # R-multiple от текущей цены
            r_str = "—"
            r_emoji = "⚪"
            if cur and one_r and one_r > 0:
                r = (cur - entry) / one_r if direction == "LONG" else (entry - cur) / one_r
                r_str = f"{r:+.2f}R"
                r_emoji = "🟢" if r > 0 else ("🔴" if r < -0.5 else "🟡")

            # Время в позиции
            age_str = ""
            try:
                from datetime import timezone
                _dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                _ago = datetime.now(timezone.utc) - _dt
                _h = int(_ago.total_seconds() // 3600)
                _m = int((_ago.total_seconds() % 3600) // 60)
                age_str = f"{_h}ч {_m}м" if _h else f"{_m}м"
            except Exception:
                pass

            dir_arrow = "↑" if direction == "LONG" else "↓"
            tsl_badge = f" 🔒TSL({tsl_tf or '15m'})" if tsl_act else ""
            sym_short = sym.split("/")[0]
            cur_str = f" | цена {cur:.5g}" if cur else ""

            lines.append(
                f"{r_emoji} <b>#{tid} {sym_short}</b> {dir_arrow} {sig_type}\n"
                f"   вход {entry:.5g}{cur_str} | {r_str}{tsl_badge}\n"
                f"   ⏱ {age_str}"
            )

        await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())

    # Универсальный обработчик кнопок меню — должен быть последним в роутере
    @router.message(F.text)
    async def handle_any_button(message: Message, state: FSMContext):
        await bot.menu_handler.handle_any_button(message, state)

    return router
