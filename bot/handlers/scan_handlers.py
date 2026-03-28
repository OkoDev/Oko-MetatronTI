"""
Команды /scan (скан рынка), /watch, /watchlist (управление watchlist), /wlr (WL report).
"""
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_menu

logger = logging.getLogger(__name__)

MAX_SCAN = 30  # максимальное кол-во пар в одном скане


def _fmt_p(price: float) -> str:
    """Форматирование цены по величине."""
    if price <= 0:
        return "—"
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.5f}"
    return f"{price:.8f}"


def _resolve_sym(bot, raw: str):
    """Нормализация символа (аналог analysis_handlers._resolve_symbol)."""
    raw = raw.strip().upper()
    if not raw:
        return None
    simple = raw if raw.endswith("USDT") else f"{raw}USDT"
    normalized = bot.data_collector.normalize_symbol(raw)
    base = simple.replace("USDT", "")
    slash = f"{base}/USDT"
    if not bot.monitored_pairs:
        return normalized or slash or None
    for cand in (normalized, slash + ":USDT", slash, simple):
        if cand in bot.monitored_pairs:
            return cand
    for p in bot.monitored_pairs:
        if p.startswith(base + "/USDT"):
            return p
    return normalized if normalized and "/" in normalized else None


async def _build_wlr_message(bot, symbol: str) -> str:
    """Собирает WL Report для символа из всех доступных источников."""
    from core.indicators import calculate_wt, calculate_trend
    from core.market_regime import MarketRegimeClassifier

    lines = [f"📊 <b>{symbol.split('/')[0]}/USDT — WL Report</b>"]

    # ── 1. OHLCV + индикаторы ───────────────────────────────────────────
    try:
        df = await bot.data_collector.get_ohlcv(symbol, "15m", limit=100)
        if df is None or len(df) < 30:
            lines.append("⚠️ Нет данных OHLCV")
        else:
            cfg = bot.config
            wt_cfg  = (cfg.get("analysis.indicators.wavetrend", {}) if cfg else {})
            tr_cfg  = (cfg.get("analysis.indicators.trend",     {}) if cfg else {})
            df = calculate_wt(df, n1=wt_cfg.get("n1", 10), n2=wt_cfg.get("n2", 21))
            df = calculate_trend(df,
                                 atr_period=tr_cfg.get("atr_period", 43),
                                 factor=tr_cfg.get("factor", 1.25))

            last     = df.iloc[-1]
            cur_price = float(last["close"])
            wt1      = float(last.get("wt1", 0))
            wt2      = float(last.get("wt2", 0))
            trend_dir = "UP" if last.get("trend", 0) == 1 else "DOWN"
            atr_val  = float(last.get("atr", 0)) if "atr" in df.columns else 0

            # Режим
            try:
                clf    = MarketRegimeClassifier()
                df_1h  = await bot.data_collector.get_ohlcv(symbol, "1h", limit=60)
                if df_1h is not None and len(df_1h) >= 20:
                    df_1h = calculate_wt(df_1h)
                    df_1h = calculate_trend(df_1h, atr_period=tr_cfg.get("atr_period", 43), factor=tr_cfg.get("factor", 1.0))
                    regime = clf.classify_from_dataframes(df, df_1h) or "?"
                else:
                    regime = clf.classify_from_dataframes(df, df) or "?"
            except Exception:
                regime = "?"

            wt_zone = "OS" if wt1 < -60 else ("OB" if wt1 > 60 else "нейтр")
            atr_pct  = atr_val / cur_price * 100 if cur_price > 0 and atr_val > 0 else 0

            lines.append(
                f"Цена:   <code>{_fmt_p(cur_price)}</code>  "
                f"Режим: <b>{regime}</b>"
            )
            lines.append(
                f"ATR:    <code>{_fmt_p(atr_val)}</code> ({atr_pct:.1f}%)  "
                f"Тренд: <b>{trend_dir}</b>"
            )
            lines.append(
                f"WT1/WT2: <code>{wt1:.1f} / {wt2:.1f}</code> ({wt_zone})"
            )
    except Exception as e:
        lines.append(f"⚠️ Ошибка индикаторов: {e}")
        cur_price = 0

    # ── 2. Ближайшие пивоты ─────────────────────────────────────────────
    if cur_price > 0 and hasattr(bot, "pivot_calculator"):
        piv_lines = []
        for tf, label in [("1D", "Дн"), ("1W", "Нед")]:
            pivots = bot.pivot_calculator.pivot_cache.get(f"{symbol}_{tf}")
            if not pivots:
                continue
            nearest = bot.pivot_calculator.get_nearest_levels(cur_price, pivots, count=1)
            res = nearest.get("resistance", [])
            sup = nearest.get("support", [])
            parts = []
            if res:
                k, p, d = res[0]
                parts.append(f"R {k}={_fmt_p(p)} (+{d:.1f}%)")
            if sup:
                k, p, d = sup[0]
                parts.append(f"S {k}={_fmt_p(p)} (-{d:.1f}%)")
            if parts:
                piv_lines.append(f"  [{label}] " + "  ".join(parts))
        if piv_lines:
            lines.append("Пивоты:\n" + "\n".join(piv_lines))
        else:
            lines.append("Пивоты: нет в кеше (бот только стартовал?)")

    # ── 3. WL запись ────────────────────────────────────────────────────
    wl = getattr(bot, "signal_watch_list", None)
    if wl and wl.has(symbol):
        entry = wl._entries.get(symbol)
        if entry:
            now_utc  = datetime.now(tz=timezone.utc)
            age_min  = int((now_utc - entry.added_at).total_seconds() / 60)
            exp_min  = int((entry.expires_at - now_utc).total_seconds() / 60)
            age_str  = f"{age_min // 60}ч {age_min % 60}м" if age_min >= 60 else f"{age_min}м"
            lines.append(
                f"WL:     <b>{entry.direction}</b>  score={entry.score:.0f}  "
                f"в WL {age_str} назад  TTL {exp_min}м"
            )
            if entry.reason:
                lines.append(f"Причина: {entry.reason}")
            if entry.pivot_key:
                lines.append(f"Пивот WL: {entry.pivot_key} = {_fmt_p(entry.pivot_level)}")
    else:
        lines.append("WL:     нет записи")

    # ── 4. Открытая сделка в БД ─────────────────────────────────────────
    try:
        open_trades = bot.trade_simulator.get_open_trades()
        trade = next(
            (t for t in open_trades
             if t.get("symbol", "").upper() == symbol.upper()
             or t.get("symbol", "").replace("/USDT", "").upper() == symbol.split("/")[0].upper()),
            None,
        )
        if trade:
            entry_p = trade.get("entry_price", 0)
            sl_p    = trade.get("stop_loss", 0)
            tp_p    = trade.get("take_profit", 0)
            direction = trade.get("direction", "?")
            r_cur   = ""
            if cur_price > 0 and entry_p > 0 and sl_p > 0:
                sl_dist = abs(entry_p - sl_p)
                if sl_dist > 0:
                    r_val  = (cur_price - entry_p) / sl_dist if direction == "LONG" else (entry_p - cur_price) / sl_dist
                    r_cur  = f"  R={r_val:+.2f}"
            lines.append(
                f"Сделка: <b>OPEN {direction}</b>  "
                f"entry={_fmt_p(entry_p)}  SL={_fmt_p(sl_p)}  TP={_fmt_p(tp_p)}{r_cur}"
            )
        else:
            lines.append("Сделка: нет открытой")
    except Exception as e:
        lines.append(f"Сделка: ошибка ({e})")

    return "\n".join(lines)


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

    # ------------------------------------------------------------------
    # /wlr SYMBOL — WL Report (TR-009): режим, WT, пивоты, WL-запись, сделка
    # ------------------------------------------------------------------
    @router.message(Command("wlr"))
    async def cmd_wlr(message: Message):
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.answer(
                "Использование: <code>/wlr BTC</code> или <code>/wlr BTC/USDT</code>",
                reply_markup=main_menu(),
            )
            return

        raw = parts[1].strip()
        if not bot.monitored_pairs:
            pairs = await bot.data_collector.load_markets()
            bot.monitored_pairs = pairs or []

        symbol = _resolve_sym(bot, raw)
        if not symbol:
            await message.answer(f"❌ Пара '{raw.upper()}' не найдена.", reply_markup=main_menu())
            return

        wait_msg = await message.answer(f"⏳ Собираю данные по {symbol.split('/')[0]}...")
        try:
            text = await _build_wlr_message(bot, symbol)
        except Exception as e:
            logger.exception("wlr error for %s", symbol)
            text = f"❌ Ошибка: {e}"
        await wait_msg.delete()
        await message.answer(text, reply_markup=main_menu(), parse_mode="HTML")

    return router
