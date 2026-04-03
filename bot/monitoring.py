"""
Фоновый мониторинг рынка: фильтры сигналов, фоновые проверки, broadcast.
Цикл сканирования вынесен в bot/loops/scan_loop.py.
Все функции принимают bot (TradingAlertBot) первым аргументом.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from core.message_builder import anomaly_message, wt_message
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import divergence_message, mtf_divergence_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from core.signal_checkers import check_anomaly_signals, check_wt_signals as _check_wt_signals
from core.entry_config import get_primary_entry_tf
from core.signal_models import SignalData, SignalType, SignalDirection
from bot.keyboards import main_menu

logger = logging.getLogger(__name__)

# Ограничиваем параллельные вызовы analyze_symbol (тяжёлый: ML + 3 OHLCV-фетча)
# Размер задаётся через config: performance.analyze_semaphore_size (default 3)
_analyze_sem: Optional[asyncio.Semaphore] = None


def _get_analyze_sem(bot) -> asyncio.Semaphore:
    """Lazy-инициализация семафора analyze_symbol из конфига (создаётся однократно)."""
    global _analyze_sem
    if _analyze_sem is None:
        size = int(bot.config.get("performance.analyze_semaphore_size", 3))
        _analyze_sem = asyncio.Semaphore(size)
    return _analyze_sem


def _div_passes_filters(div_info: dict, df_15m, pivot_calc, sym: str,
                        proximity_pct: float = 4.0,
                        market_regime: str = "") -> tuple[bool, str]:
    """
    Фильтрация дивергенций: отсеивает шумы, оставляет только подтверждённые сигналы.

    Правило 0 — Режим рынка (Этап 8.4.5):
      Hidden дивергенции в RANGE/HIGH_VOL режиме отклоняются:
      в боковике нет тренда для продолжения, в HIGH_VOL тренды рвутся.

    Правило 1 — WT zone:
      Regular Bullish:  wt1_current < -40 (OS зона, уже встроено в детектор как < -60, дублируем)
      Regular Bearish:  wt1_current > +40 (OB зона, уже встроено в детектор как > +60)
      Hidden Bullish:   wt1_current < 0   (не в перекупленности, тренд вверх но откат)
      Hidden Bearish:   wt1_current > 0   (не в перепроданности, тренд вниз но отскок)

    Правило 2 — Pivot proximity:
      цена должна быть в пределах 2% от ближайшего уровня поддержки (для LONG)
      или сопротивления (для SHORT) из дневных пивотов.
      Если пивоты не в кеше — правило пропускается (не блокируем).

    Returns: (passed: bool, reason: str)
    """
    div_type = div_info.get("type", "")
    is_bullish = "BULLISH" in div_type
    is_bearish = "BEARISH" in div_type
    is_hidden = "HIDDEN" in div_type

    # ── Правило 0: Режим рынка — hidden div только в трендовом рынке ────────
    if is_hidden and market_regime in ("RANGE", "HIGH_VOL"):
        return False, f"Hidden div пропущена: режим {market_regime} (нет тренда для продолжения)"

    # ── Правило 1: WT zone ──────────────────────────────────────────────────
    # wt1_current уже есть в details (вычислен детектором), не нужен df_15m
    details = div_info.get("details") or {}
    wt1_current = details.get("ind_current")

    if wt1_current is not None:
        if is_hidden:
            # Скрытые дивергенции — продолжение тренда: WT не должен быть в противоположной зоне
            if is_bullish and wt1_current > 0:
                return False, f"Hidden Bull: wt1={wt1_current:.1f} выше 0 (OB территория)"
            if is_bearish and wt1_current < 0:
                return False, f"Hidden Bear: wt1={wt1_current:.1f} ниже 0 (OS территория)"
        else:
            # Регулярные дивергенции — разворот: нужна соответствующая зона
            if is_bullish and wt1_current > -40:
                return False, f"Regular Bull: wt1={wt1_current:.1f} не в OS зоне (<-40)"
            if is_bearish and wt1_current < 40:
                return False, f"Regular Bear: wt1={wt1_current:.1f} не в OB зоне (>+40)"

    # ── Правило 2: Pivot proximity (из кеша, без API-запроса) ───────────────
    if pivot_calc is not None:
        daily_pivots = pivot_calc.pivot_cache.get(f"{sym}_1D")
        if daily_pivots:
            try:
                current_price = float(df_15m["close"].iloc[-1]) if df_15m is not None else 0
                if current_price > 0:
                    nearest = pivot_calc.get_nearest_levels(current_price, daily_pivots, count=3)
                    levels = nearest["support"] if is_bullish else nearest["resistance"]
                    closest_dist = levels[0][2] if levels else 999.0  # dist в %
                    if closest_dist > proximity_pct:
                        return False, f"далеко от пивота: {closest_dist:.1f}% (порог {proximity_pct}%)"
            except Exception:
                pass  # ошибка — не блокируем

    return True, ""


def _make_mtf_alert_recommendation(sym: str, signal_type: str, strength: int,
                                    current_price: float, atr: float):
    """Адаптер MTF alert → объект для register_trade (fallback_rec)."""
    is_long = signal_type == "LONG"
    sl_mult = 2.0
    tp_rr = 2.5
    sl = current_price - atr * sl_mult if is_long else current_price + atr * sl_mult
    risk = abs(current_price - sl)
    tp = current_price + risk * tp_rr if is_long else current_price - risk * tp_rr
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="mtf_alert"))
    return SimpleNamespace(
        symbol=sym,
        entry_price=current_price,
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=sl,
        take_profit=tp,
        tp1_price=None,
        overall_strength=strength,
        confidence=0.70,
        timestamp=datetime.now(timezone.utc),  # DEV-49
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source="atr_15m",
        tp_source="rr_2.5",
        metadata={},
    )


def _make_pivot_recommendation(info: dict):
    """Адаптер dict от check_pivot_level_signal → объект для register_trade."""
    is_long = "LONG" in info.get("type", "")
    confidence_str = info.get("confidence", "HIGH")
    conf_float = 0.85 if confidence_str == "VERY_HIGH" else 0.70
    # Динамический strength из детектора (60-100), иначе fallback
    strength = info.get("strength", 80 if confidence_str == "VERY_HIGH" else 65)
    tp_levels = info.get("take_profits", [])
    tp1 = tp_levels[0]["price"] if tp_levels else None
    tp_main = tp_levels[1]["price"] if len(tp_levels) > 1 else tp1  # TP2 как основная цель
    level = info.get("level", "")

    # DEV-59: R:R cap — pivot_reversal обходит calculate_levels(), применяем cap вручную
    _entry = info.get("entry_price")
    _sl    = info.get("stop_loss")
    if _entry and _sl and tp_main:
        try:
            from core.config_loader import config as _cfg59
            _max_rr = float(_cfg59.get("trading.sl_management.max_rr", 6.0))
        except Exception:
            _max_rr = 6.0
        _sl_dist = abs(float(_entry) - float(_sl))
        if _sl_dist > 0:
            _actual_rr = abs(float(tp_main) - float(_entry)) / _sl_dist
            if _actual_rr > _max_rr:
                tp_main = (float(_entry) + _sl_dist * _max_rr) if is_long else (float(_entry) - _sl_dist * _max_rr)
                if tp1 and abs(float(tp1) - float(_entry)) / _sl_dist > _max_rr:
                    tp1 = tp_main
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="pivot_reversal"))
    return SimpleNamespace(
        symbol=info.get("symbol", ""),
        entry_price=info.get("entry_price"),
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=info.get("stop_loss"),
        take_profit=tp_main,
        tp1_price=tp1,
        overall_strength=strength,
        confidence=conf_float,
        timestamp=datetime.now(timezone.utc),  # DEV-49
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source=info.get("sl_source", "atr_14"),
        tp_source=f"pivot_1W_{level}" if level else "pivot_1W",
        metadata={},
    )


async def start_monitoring(bot, message):
    from bot.loops.scan_loop import monitor_market, _prefetch_pivots

    if bot.is_monitoring:
        await message.answer("⚠️ Мониторинг уже запущен.", reply_markup=main_menu())
        return

    user_id = message.from_user.id
    if user_id not in bot.subscribers:
        bot.subscribers.add(user_id)
        bot.subscription_manager.add_user(
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
        )
        logger.info("Пользователь %s добавлен в подписчики при старте мониторинга", user_id)

    min_vol = bot.config.get("signal_quality.min_volume_usd", 0)
    pairs = await bot.data_collector.load_markets(min_volume_usd=min_vol)
    if not pairs:
        await message.answer("❌ Не удалось загрузить пары.", reply_markup=main_menu())
        return

    bot.monitored_pairs = pairs
    bot.is_monitoring = True
    bot.start_time = datetime.now()
    bot.monitor_task = asyncio.create_task(monitor_market(bot))

    asyncio.create_task(_prefetch_pivots(bot))

    await message.answer(
        f"✅ Запущен мониторинг {len(bot.monitored_pairs)} пар.\n"
        f"📡 Отслеживаю: аномалии, WT, MTF, тренд-сигналы и дивергенции\n\n"
        f"💎 <b>Ваша подписка:</b> "
        f"{bot.subscription_manager.get_subscription_info(user_id)['tier']}",
        reply_markup=main_menu(),
    )


async def stop_monitoring(bot, message):
    if not bot.is_monitoring:
        await message.answer("⚠️ Мониторинг не запущен.", reply_markup=main_menu())
        return

    bot.is_monitoring = False
    if bot.monitor_task:
        bot.monitor_task.cancel()
    await bot.data_collector.stop()
    await message.answer("⏹ Мониторинг остановлен.", reply_markup=main_menu())


# _prefetch_pivots перемещена в bot/loops/scan_loop.py


# scan_all_pairs и monitor_market перемещены в bot/loops/scan_loop.py


async def check_anomalies(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=30)
                if df_entry is None or df_entry.empty:
                    return
                signals = await check_anomaly_signals(sym, df_entry)
                for sig in signals:
                    info = sig.data or {}
                    bot.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                    bot.signal_counters["anomaly"] += 1
                    bot.signal_counters["total"] += 1
                    raw_text = anomaly_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "anomaly")
            except Exception:
                logger.exception("Ошибка check_anomalies для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_wt_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=150)
                if df_entry is None or df_entry.empty:
                    return
                df_1h = await bot.data_collector.get_ohlcv(sym, "1h", limit=60)
                signals = await _check_wt_signals(sym, df_entry, df_1h)
                for sig in signals:
                    info = sig.data or {}
                    logger.info("WT сигнал обнаружен для %s", sym)
                    raw_text = wt_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "wt_signal")
                    bot.signal_counters["wt_signal"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_wt_signals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])



def _make_signal_stub(sym: str, signal_type: SignalType, direction_str: str,
                      strength: float = 65, data: dict = None) -> SignalData:
    """Создаёт SignalData-заглушку для передачи как pre_signals в _broadcast_intelligence_alert.
    Нужно чтобы analyze_symbol получил подсказку о сигнале из фоновых функций
    (check_mtf_alerts, check_trend_signals, check_pivot_reversals и др.)
    и не отклонил их из-за min_signals=2.
    """
    d = direction_str.upper() if direction_str else ""
    if "LONG" in d or d == "LONG":
        direction = SignalDirection.LONG
    elif "SHORT" in d or d == "SHORT":
        direction = SignalDirection.SHORT
    else:
        direction = SignalDirection.NEUTRAL
    return SignalData(
        symbol=sym, signal_type=signal_type, direction=direction,
        strength=strength, confidence=0.7, timestamp=datetime.now(timezone.utc), data=data or {},  # DEV-49
    )


async def check_mtf_alerts(bot):
    # DEV-31: mtf_alert убран — 137 сделок WR=4.4%. Отключается через signals.mtf_alert_enabled=false
    if not bot.config.get("signals.mtf_alert_enabled", True):
        return
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                snapshot = await collect_mtf_data(sym, bot.data_collector)
                if not snapshot:
                    return
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    from core.mtf_checker import analyze_mtf_strength
                    strength = analyze_mtf_strength(snapshot, sig)
                    raw_text = mtf_alert_message(sym, snapshot, sig)
                    pre = [_make_signal_stub(sym, SignalType.MTF_ALERT, sig, strength=strength)]
                    # Создаём fallback_rec для регистрации сделки (если включено)
                    mtf_fallback = None
                    if bot.config.get("signals.mtf_alert_register", True):
                        try:
                            _etf = get_primary_entry_tf()
                            df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=30)
                            if df_entry is not None and len(df_entry) >= 14:
                                cur_price = float(df_entry["close"].iloc[-1])
                                atr = float(df_entry["high"].rolling(14).max().iloc[-1]
                                            - df_entry["low"].rolling(14).min().iloc[-1]) / 14
                                if cur_price > 0 and atr > 0:
                                    mtf_fallback = _make_mtf_alert_recommendation(
                                        sym, sig, strength, cur_price, atr)
                        except Exception:
                            logger.debug("[%s] MTF alert fallback_rec: не удалось вычислить", sym)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_alert",
                                                        fallback_rec=mtf_fallback, pre_signals=pre)
                    bot.signal_counters["mtf_alert"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_mtf_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_cascade_divergences(bot, senior_tf: str, junior_tf: str):
    """Проверяет MTF-конфлюэнцию дивергенций (скрытая senior_tf + регулярная junior_tf) для всех пар."""
    if not bot.config.get("signals.cascade_div_enabled", True):
        return
    sem = asyncio.Semaphore(int(bot.config.get("performance.cascade_div_semaphore_size", 5)))

    async def _one(sym):
        async with sem:
            try:
                has_cascade, cascade_info = await bot.divergence_detector.detect_cascade_divergence(
                    sym, bot.data_collector, senior_tf, junior_tf
                )
                if has_cascade:
                    raw_text = mtf_divergence_message(sym, cascade_info)
                    pre = [_make_signal_stub(sym, SignalType.MTF_DIVERGENCE,
                                            cascade_info.get("type", ""),
                                            strength=cascade_info.get("strength", 65),
                                            data=cascade_info)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_divergence", pre_signals=pre)
                    bot.signal_counters["divergence"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Cascade-дивергенция %s→%s: %s (сила %d)",
                                sym, senior_tf, junior_tf, cascade_info.get("type"), cascade_info.get("strength"))
            except Exception:
                logger.exception("Ошибка check_cascade_divergences %s→%s для %s", senior_tf, junior_tf, sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_trend_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                is_sig, info = await check_trend_following_signal(
                    sym, bot.data_collector, bot.divergence_detector, bot.pivot_calculator
                )
                if is_sig:
                    raw_text = trend_signal_message(sym, info)
                    pre = [_make_signal_stub(sym, SignalType.TREND_SIGNAL,
                                            info.get("type", ""),
                                            strength=info.get("strength", 65),
                                            data=info)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "trend_signal", pre_signals=pre)
                    bot.signal_counters["trend_signal"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Тренд-сигнал: %s", sym, info.get("pattern"))
            except Exception:
                logger.exception("Ошибка check_trend_signals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_divergences(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            for tf in (get_primary_entry_tf(), "1h"):
                try:
                    has_div, div_info = await bot.divergence_detector.detect_divergence(
                        sym, bot.data_collector, timeframe=tf
                    )
                    if has_div:
                        raw_text = divergence_message(sym, div_info)
                        pre = [_make_signal_stub(sym, SignalType.DIVERGENCE,
                                                div_info.get("type", ""),
                                                strength=div_info.get("strength", 55),
                                                data=div_info)]
                        await _broadcast_intelligence_alert(bot, sym, raw_text, "divergence", pre_signals=pre)
                        bot.signal_counters["divergence"] += 1
                        bot.signal_counters["total"] += 1
                        logger.info("[%s] Дивергенция на %s: %s", sym, tf, div_info.get("type"))
                        break
                except Exception:
                    logger.exception("Ошибка check_divergences для %s %s", sym, tf)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_pivot_reversals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                has_signal, info = await check_pivot_level_signal(
                    sym, bot.data_collector, bot.pivot_calculator
                )
                if has_signal:
                    raw_text = pivot_level_signal_message(sym, info)
                    pivot_rec = _make_pivot_recommendation(info)
                    stub = _make_signal_stub(sym, SignalType.PIVOT_REVERSAL,
                                            info.get("type", ""),
                                            strength=info.get("strength", 70),
                                            data=info)
                    pre = [stub]
                    # Кешируем для меню "Все сигналы"
                    bot.recent_signals.setdefault(sym, [])
                    bot.recent_signals[sym] = [
                        s for s in bot.recent_signals[sym] if s.signal_type != SignalType.PIVOT_REVERSAL
                    ] + [stub]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "pivot_reversal",
                                                        fallback_rec=pivot_rec, pre_signals=pre)
                    bot.signal_counters["pivot_reversal"] += 1
                    bot.signal_counters["total"] += 1
                    logger.info("[%s] Вход от уровня: %s R:R=%.1f", sym, info.get("level"), info.get("rr_ratio", 0))
            except Exception:
                logger.exception("Ошибка check_pivot_reversals для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_future_pivot_alerts(bot):
    """
    DEV-11: Pre-alert при приближении цены к future pivot уровням.
    Вызывается каждые _bg_n циклов из monitor_market.
    """
    if not bot.config.get("future_pivots.enabled", True):
        return

    pre_alert_pct = float(bot.config.get("future_pivots.pre_alert_pct", 1.0))
    ttl_sec = int(bot.config.get("future_pivots.ttl_sec", 60))
    threshold_pct = float(bot.config.get("future_pivots.confluence_threshold_pct", 0.5))
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))
    pivot_calc = getattr(bot, "pivot_calculator", None)

    if pivot_calc is None:
        return

    from core.confluence_scanner import check_future_classic_confluence

    async def _one(sym):
        async with sem:
            try:
                # Загружаем future пивоты (с TTL-кешем)
                future_daily, future_weekly, future_monthly = await asyncio.gather(
                    pivot_calc.get_future_daily_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                    pivot_calc.get_future_weekly_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                    pivot_calc.get_future_monthly_pivots(sym, bot.data_collector, ttl_sec=ttl_sec),
                )

                future_map = {
                    "future_1D": future_daily,
                    "future_1W": future_weekly,
                    "future_1M": future_monthly,
                }

                # Текущая цена из кеша entry TF
                _etf = get_primary_entry_tf()
                df_entry = await bot.data_collector.get_ohlcv(sym, _etf, limit=5)
                if df_entry is None or df_entry.empty:
                    return
                current_price = float(df_entry["close"].iloc[-1])
                if current_price <= 0:
                    return

                all_levels = ["PP"] + [f"S{i}" for i in range(1, 6)] + [f"R{i}" for i in range(1, 6)]
                alerts = []

                # Проверяем близость цены к каждому future-уровню
                for tf_key, f_pivots in future_map.items():
                    if not f_pivots:
                        continue
                    for lvl in all_levels:
                        price = f_pivots.get(lvl)
                        if not price or price <= 0:
                            continue
                        dist_pct = abs((current_price - price) / price * 100)
                        if dist_pct <= pre_alert_pct:
                            alerts.append({
                                "tf": tf_key,
                                "level": lvl,
                                "price": price,
                                "dist_pct": dist_pct,
                                "current_price": current_price,
                            })

                # Конфлюэнция Future × Classic
                confluence_hits = []
                for tf_key, f_pivots in future_map.items():
                    if not f_pivots:
                        continue
                    # Берём classic кеш (1D, 1W, 1M)
                    classic_tf = tf_key.replace("future_", "")
                    classic_pivots = pivot_calc.pivot_cache.get(f"{sym}_{classic_tf}")
                    if classic_pivots:
                        hits = check_future_classic_confluence(f_pivots, classic_pivots, threshold_pct)
                        confluence_hits.extend(hits)

                if not alerts and not confluence_hits:
                    return

                # Формируем сообщение pre-alert
                lines = [f"⚠️ <b>FUTURE PIVOT ALERT · {sym}</b>"]
                if alerts:
                    lines.append(f"💰 Цена: <code>{current_price:.6f}</code>")
                    for a in sorted(alerts, key=lambda x: x["dist_pct"])[:3]:
                        lines.append(
                            f"  📍 {a['tf'].replace('future_','')} {a['level']}: "
                            f"<code>{a['price']:.6f}</code> "
                            f"({a['dist_pct']:.2f}% от цены)"
                        )
                if confluence_hits:
                    lines.append("🎯 <b>Future × Classic конфлюэнции:</b>")
                    for c in confluence_hits[:2]:
                        lines.append(
                            f"  {c['label']}: <code>{c['price']:.6f}</code> "
                            f"(+{c['strength_bonus']} strength)"
                        )
                lines.append(f"⏰ {datetime.now().strftime('%d.%m %H:%M')}")
                raw_text = "\n".join(lines)

                logger.info("[future_pivots] %s: %d уровней, %d конфлюэнций",
                            sym, len(alerts), len(confluence_hits))
                if bot.config.get("future_pivots.broadcast_tg", False):
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "future_pivot_alert")

            except Exception:
                logger.exception("Ошибка check_future_pivot_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


def _is_in_sl_cooldown(bot, symbol: str) -> bool:
    """Возвращает True если по этой паре было SL-закрытие в течение sl_cooldown_hours."""
    hours = bot.config.get("signal_quality.sl_cooldown_hours", 4)
    if hours <= 0:
        return False
    try:
        db_path = bot.trade_simulator.db_path
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM simulated_trades WHERE symbol=? AND status='SL' AND closed_at>=? LIMIT 1",
                (symbol, cutoff_str),
            ).fetchone()
        if row:
            logger.debug("[%s] Cooldown после SL — сигнал пропущен (%dh)", symbol, hours)
            return True
    except Exception as e:
        logger.debug("sl_cooldown check error для %s: %s", symbol, e)
    return False


def _is_duplicate_signal(bot, symbol: str, signal_type: str, direction: str = "") -> bool:
    """Дедупликация по (пара, тип, направление).
    LONG WT по паре не блокирует SHORT WT по той же паре.
    WT сигнал по паре не блокирует pivot_reversal по той же паре."""
    minutes = bot.config.get("signal_quality.dedup_minutes", 30)
    if minutes <= 0:
        return False
    key = (symbol, signal_type, direction)
    last_ts = bot._last_signal.get(key)
    if last_ts and (datetime.now() - last_ts).total_seconds() < minutes * 60:
        logger.debug("[%s] Дубликат %s/%s — пропущен (%d мин)", symbol, signal_type, direction, minutes)
        return True
    bot._last_signal[key] = datetime.now()
    return False


async def _get_btc_regime(bot):
    """Кешированный режим BTC/USDT (TTL 5 мин)."""
    cache = getattr(bot, "_btc_regime_cache", None)
    now = datetime.now().timestamp()
    if cache and (now - cache["ts"]) < 300:
        return cache["regime"]
    try:
        from core.market_regime import MarketRegimeClassifier
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "1h", limit=50)
        if ohlcv is not None and not ohlcv.empty:
            regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv.values.tolist())
            bot._btc_regime_cache = {"regime": regime, "ts": now}
            return regime
    except Exception as e:
        logger.debug("BTC режим не определён: %s", e)
    return None


async def _get_btc_4h_regime(bot) -> str | None:
    """Кешированный BTC/USDT 4h режим для ARCH-63 market gate (TTL 5 мин)."""
    cache = getattr(bot, "_btc_4h_regime_cache", None)
    now = datetime.now().timestamp()
    if cache and (now - cache["ts"]) < 300:
        return cache["regime"]
    try:
        from core.market_regime import MarketRegimeClassifier
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "4h", limit=50)
        if ohlcv is not None and not ohlcv.empty:
            regime = MarketRegimeClassifier().classify_from_ohlcv(ohlcv.values.tolist())
            bot._btc_4h_regime_cache = {"regime": regime, "ts": now}
            return regime
    except Exception as e:
        logger.debug("[BTC4h] режим не определён: %s", e)
    return None


_kelly_stats_cache: dict = {}  # {"ts": float, "text": str}


def _get_kelly_footer(bot) -> str:
    """Kelly-sizing строка для TG-алерта. Кеш 30 мин. Пустая строка если не готов."""
    import time, sqlite3
    global _kelly_stats_cache
    now = time.time()
    if _kelly_stats_cache and (now - _kelly_stats_cache.get("ts", 0)) < 1800:
        return _kelly_stats_cache["text"]
    try:
        r_pred = getattr(bot, "r_predictor", None)
        if r_pred is None or not r_pred.is_trained:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        db_path = getattr(bot.trade_simulator, "db_path", "subscriptions.db")
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END),
                       AVG(CASE WHEN status IN ('TP','TSL') THEN R_multiple ELSE NULL END)
                FROM simulated_trades WHERE status != 'OPEN'
            """).fetchone()
        if not row or not row[0] or not row[2] or row[2] <= 0:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        total, wins, avg_r = int(row[0]), int(row[1] or 0), float(row[2])
        win_rate = wins / total
        from core.r_predictor import RPredictor
        kelly_f = RPredictor.kelly_fraction(win_rate, avg_r)
        if kelly_f <= 0:
            _kelly_stats_cache = {"ts": now, "text": ""}
            return ""
        text = (f"\n📐 <i>Kelly: {kelly_f*100:.1f}% депозита"
                f" (WR={win_rate*100:.0f}%, R̄={avg_r:.2f})</i>")
        _kelly_stats_cache = {"ts": now, "text": text}
        return text
    except Exception:
        return ""


async def _broadcast_intelligence_alert(bot, symbol: str, raw_text: str, signal_type: str,
                                        fallback_rec=None, pre_signals=None,
                                        pre_fetched_dfs=None):
    # Этап 8.4.4: извлекаем direction из первого pre_signal для точного dedup
    direction = ""
    if pre_signals:
        for _sig in pre_signals:
            _d = getattr(_sig, "direction", None)
            if _d:
                direction = getattr(_d, "value", str(_d))
                break

    # Фильтры качества сигналов (Этап 5.1 + 8.4.4)
    if hasattr(bot, "_last_signal") and _is_duplicate_signal(bot, symbol, signal_type, direction):
        return
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol):
        return

    recommendation = None
    try:
        async with _get_analyze_sem(bot):
            recommendation = await bot.trading_intelligence.analyze_symbol(
                symbol, pre_collected_signals=pre_signals,
                pre_fetched_dfs=pre_fetched_dfs,
            )
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    # ARCH-28: FVG + Pivot Confluence — бонус к strength если цена в зоне конфлюэнции
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        try:
            from core.smc import find_fvg_pivot_confluences
            smc_ctx = getattr(getattr(recommendation, "market_context", None), "smc_context", None)
            if smc_ctx is not None and smc_ctx.fvg is not None:
                # Строим плоский dict пивотов из кеша: {"1W_S2": 0.004406, ...}
                flat_pivots: dict = {}
                sym_pivots = getattr(bot.pivot_calculator, "pivot_cache", {}).get(symbol, {})
                for tf_key, levels in sym_pivots.items():
                    if isinstance(levels, dict):
                        for lk, lv in levels.items():
                            if isinstance(lv, (int, float)) and lv > 0:
                                flat_pivots[f"{tf_key}_{lk}"] = lv

                if flat_pivots:
                    cur_price = recommendation.market_context.current_price or 0
                    zones = find_fvg_pivot_confluences(smc_ctx.fvg, flat_pivots, cur_price)
                    if zones:
                        # Сохраняем все зоны в metadata для features_json
                        if recommendation.metadata is None:
                            recommendation.metadata = {}
                        recommendation.metadata["fvg_confluences"] = [z.to_dict() for z in zones]

                        # Бонус strength: только если цена ВНУТРИ FVG зоны
                        for z in zones:
                            fvg = z.fvg
                            if fvg.bottom <= cur_price <= fvg.top:
                                bonus = z.score
                                old_str = recommendation.overall_strength
                                recommendation.overall_strength = min(100, old_str + bonus)
                                logger.info(
                                    "[ARCH-28] %s: цена в зоне %s (score=%d) → strength %d→%d",
                                    symbol, z.label, bonus, old_str, recommendation.overall_strength,
                                )
                                break  # применяем только за первую (ближайшую) зону
        except Exception:
            logger.debug("[ARCH-28] %s: ошибка FVG confluence", symbol, exc_info=True)

    # Этап 5.2: BTC-корреляционный фильтр (ARCH-09п8)
    # shadow (default): только логирует + btc_counter_trend в features_json, НЕ блокирует
    # block: блокирует слабые контртрендовые сигналы (классическое поведение)
    btc_filter_mode = bot.config.get("signal_quality.btc_filter_mode", "shadow")
    btc_regime = await _get_btc_regime(bot) if bot.config.get("signal_quality.btc_filter_enabled", True) else None
    btc_warning = ""
    btc_counter_trend = False   # флаг для features_json (аналитика WR)
    if btc_regime == "HIGH_VOL":
        btc_warning = "\n⚠️ <i>BTC (1h): высокая волатильность — повышенный риск для любых позиций</i>"
    elif recommendation and btc_regime:
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        strength_val = getattr(recommendation, "overall_strength", 0)
        is_counter_trend = (
            (btc_regime == "TREND_UP" and direction_val == "SHORT") or
            (btc_regime == "TREND_DOWN" and direction_val == "LONG")
        )
        ct_thr = int(bot.config.get("signal_quality.counter_trend_strength_threshold", 70))
        if is_counter_trend:
            btc_counter_trend = True
            if btc_filter_mode == "block" and strength_val < ct_thr:
                logger.info("[%s] BTC %s vs %s, сила %d < %d — пропущен (block mode)",
                            symbol, btc_regime, direction_val, strength_val, ct_thr)
                return
            regime_ru = "восходящем" if btc_regime == "TREND_UP" else "нисходящем"
            dir_ru = "шорт" if direction_val == "SHORT" else "лонг"
            btc_warning = f"\n⚠️ <i>BTC (1h) в {regime_ru} тренде — {dir_ru} против рынка ({strength_val}/100)</i>"
            logger.info("[%s] BTC %s vs %s, сила %d, режим=%s — btc_counter_trend=True",
                        symbol, btc_regime, direction_val, strength_val, btc_filter_mode)

    # Этап 5.3: BTC 4h Market Gate (ARCH-63, DEV-111) — shadow mode
    if recommendation is not None:
        _btc_gate_cfg = (bot.config.get("trading", {}) or {}).get("btc_market_gate", {})
        if _btc_gate_cfg.get("enabled", False):
            _btc_4h = await _get_btc_4h_regime(bot)
            if _btc_4h is not None:
                _dir4h = getattr(recommendation.direction, "value",
                                 str(recommendation.direction))
                _shadow4h = _btc_gate_cfg.get("shadow_mode", True)
                _should_block4h = False
                _reason4h = None

                # Правило 1: BTC 4h TREND_DOWN → блок LONG
                if _btc_4h == "TREND_DOWN" and _dir4h == "LONG":
                    _sig_type = getattr(recommendation, "signal_type", "") or ""
                    _wb = (recommendation.metadata or {}).get("weekly_bias", "UNKNOWN")
                    # Исключение: pivot_reversal с BULLISH weekly bias
                    if not (_sig_type == "pivot_reversal" and _wb == "BULLISH"):
                        _should_block4h = True
                        _reason4h = f"BTC 4h TREND_DOWN блокирует LONG"

                # Правило 2: BTC 4h TREND_UP → блок SHORT (выключено по умолчанию)
                elif (_btc_4h == "TREND_UP" and _dir4h == "SHORT"
                      and _btc_gate_cfg.get("block_short_in_uptrend", False)):
                    _should_block4h = True
                    _reason4h = "BTC 4h TREND_UP блокирует SHORT"

                if _should_block4h:
                    if _shadow4h:
                        logger.info("[%s] ARCH-63 SHADOW WOULD_BLOCK %s btc_4h=%s reason=%s",
                                    symbol, _dir4h, _btc_4h, _reason4h)
                    else:
                        logger.info("[%s] ARCH-63 btc_market_gate: %s→WATCH (%s)",
                                    symbol, recommendation.action, _reason4h)
                        recommendation.action = "WATCH"

    # Этап 5.4: DEV-128 — weekly_bias gate для pivot_reversal RANGE
    # Данные: 62% pivot_reversal RANGE = weekly_bias=NONE, EV=-0.5—0.76R → блок
    # Исключение: BULLISH/BEARISH (aligned с направлением) — пропускаем
    if recommendation is not None:
        try:
            _wb128_cfg = (bot.config.get("signal_quality", {}) or {}).get("weekly_bias_gate", {})
            _wb128_enabled = _wb128_cfg.get("enabled", True)
            _wb128_shadow  = _wb128_cfg.get("shadow_mode", False)
            _wb128_sig = getattr(recommendation, "signal_type", "") or ""
            _wb128_reg = getattr(recommendation, "regime", "") or ""
            if _wb128_sig == "pivot_reversal" and _wb128_reg == "RANGE":
                _wb128_meta = recommendation.metadata or {}
                _wb128_bias = _wb128_meta.get("weekly_bias", "UNKNOWN")
                _wb128_dir  = getattr(recommendation.direction, "value", "NEUTRAL")
                # Блокируем NONE/UNKNOWN — нет контекста, EV отрицательный
                # Исключение: BULLISH+LONG или BEARISH+SHORT — aligned
                _wb128_aligned = (
                    (_wb128_bias == "BULLISH" and _wb128_dir == "LONG") or
                    (_wb128_bias == "BEARISH" and _wb128_dir == "SHORT")
                )
                _wb128_block = not _wb128_aligned  # блок если не aligned
                if _wb128_block:
                    if _wb128_shadow or not _wb128_enabled:
                        logger.info(
                            "[%s] DEV-128 SHADOW pivot_reversal RANGE weekly_bias=%s dir=%s → WOULD_BLOCK",
                            symbol, _wb128_bias, _wb128_dir,
                        )
                    else:
                        logger.info(
                            "[%s] DEV-128 pivot_reversal RANGE weekly_bias=%s dir=%s → WATCH",
                            symbol, _wb128_bias, _wb128_dir,
                        )
                        recommendation.action = "WATCH"
        except Exception as _e128:
            logger.debug("[DEV-128] %s: gate error — %s", symbol, _e128)

    # Этап 6: TP по иерархии пивотов (ARCH-09п5, DEV-75)
    # Порядок: 1D → 1W → confluence(1W+1D) → confluence(1M+1W) → 1M → ATR fallback
    distance_to_pivot_pct: float = 0.0
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        entry_price = recommendation.entry_price or 0
        if direction_val in ("LONG", "SHORT") and entry_price > 0:
            strategy_type = (recommendation.metadata or {}).get("strategy_type", "")
            _rec_regime = getattr(recommendation, "regime", None) or ""
            if _rec_regime == "RANGE":
                # DEV-122: для RANGE берём ближайший пивот (avg TP 5-8R → hit rate 28-41%)
                pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r_range", 1.2)
            elif strategy_type == "reversal":
                pivot_min_r = bot.config.get("trading.sl_tp.tp_reversal_min_r", 2.0)
            elif strategy_type == "trend_following":
                pivot_min_r = bot.config.get("trading.sl_tp.tp_trend_min_r", 1.5)
            else:
                pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0)
            # ARCH-58: извлекаем impulse_high/low из metadata (OTE detector их пишет)
            _meta = recommendation.metadata or {}
            _imp_high = _meta.get("impulse_high")
            _imp_low  = _meta.get("impulse_low")
            pivot_result = bot.pivot_calculator.get_tp_by_hierarchy(
                direction=direction_val,
                entry_price=entry_price,
                symbol=symbol,
                stop_loss=recommendation.stop_loss,
                min_r=pivot_min_r,
                impulse_high=_imp_high,
                impulse_low=_imp_low,
            )
            if pivot_result:
                pivot_tp, pivot_src = pivot_result
                recommendation.take_profit = pivot_tp
                recommendation.tp_source = pivot_src
                distance_to_pivot_pct = abs(pivot_tp - entry_price) / entry_price * 100
                logger.debug("[%s] Pivot TP (hierarchy): %.6f (%.2f%%, %s, src=%s)", symbol, pivot_tp, distance_to_pivot_pct, direction_val, pivot_src)
            elif bot.config.get("trading.sl_tp.require_pivot_tp", False):
                # Вариант C (п.6): если pivot TP не найден и require_pivot_tp=true → пропуск регистрации
                logger.info("[%s] Пропуск регистрации: require_pivot_tp=true, pivot не найден в 2-20R", symbol)
                if recommendation is not None:
                    recommendation = None  # блокирует is_actionable и should_register

    min_strength = bot.config.get("signal_quality.min_strength", 50)
    min_strength_register = bot.config.get("signal_quality.min_strength_register", 50)

    _dir_ok = (
        recommendation is not None
        and getattr(recommendation, "action", "WATCH") in ("BUY", "SELL")
        and getattr(recommendation, "direction", None) is not None
        and recommendation.direction.value != "NEUTRAL"
    )
    is_actionable = _dir_ok and recommendation.overall_strength >= min_strength
    should_register = _dir_ok and recommendation.overall_strength >= min_strength_register

    # WATCH+NEUTRAL — нет торгового решения, не спамим
    if (recommendation is not None
            and getattr(recommendation, "action", "WATCH") in ("WATCH", "HOLD")
            and getattr(recommendation.direction, "value", "NEUTRAL") == "NEUTRAL"):
        logger.info("[%s] Пропущен WATCH+NEUTRAL — нет торгового решения", symbol)
        return

    # ── DEV-22: WATCH LIST ─────────────────────────────────────────────────────
    # Если action=WATCH и есть чёткое направление — добавить в WL или эскалировать.
    _wl = getattr(bot, "signal_watch_list", None)
    if _wl is not None and recommendation is not None:
        _rec_action = getattr(recommendation, "action", "WATCH")
        _rec_dir = (getattr(recommendation.direction, "value", "NEUTRAL")
                    if recommendation.direction else "NEUTRAL")
        _rec_str = recommendation.overall_strength

        # MTF direction из metadata
        _mtf_ctx = (recommendation.metadata or {}).get("mtf_context", {})
        _mtf_dir = _mtf_ctx.get("direction_bias", "") if isinstance(_mtf_ctx, dict) else ""
        _mtf_aligned = _mtf_ctx.get("aligned_pct", 0) if isinstance(_mtf_ctx, dict) else 0

        # Кол-во дивергенций в supporting_signals
        _div_count = sum(
            1 for s in (recommendation.supporting_signals or [])
            if "divergence" in str(getattr(s, "signal_type", "")).lower()
        )

        if _rec_action == "WATCH" and _rec_dir in ("LONG", "SHORT"):
            # Pivot level для отслеживания пробоя: используем stop_loss (уровень под/над которым идея ломается)
            _pivot_key = getattr(recommendation, "sl_source", "") or ""
            _pivot_level = recommendation.stop_loss or 0.0
            _wl_reason = f"MTF {_mtf_dir} {_mtf_aligned}%" if _mtf_dir else "WATCH"

            if _wl.has(symbol):
                # Уже в WL → проверяем эскалацию
                if _wl.check_escalation(symbol, _rec_str, _rec_action, _mtf_dir, _div_count):
                    # Эскалируем: форсируем BUY/SELL, пересчитываем флаги
                    recommendation.action = "BUY" if _rec_dir == "LONG" else "SELL"
                    _dir_ok = True
                    is_actionable = _rec_str >= min_strength
                    should_register = _rec_str >= min_strength_register
                    raw_text = raw_text.rstrip() + "\n🔔 <i>Эскалация из WATCH — условия улучшились</i>"
                    _wl.add(symbol, _rec_dir, _rec_str, "escalated", _pivot_key, _pivot_level, _div_count)
                    logger.info("[%s] WL: WATCH → %s (score=%.0f)", symbol, recommendation.action, _rec_str)
                # иначе WATCH остаётся WATCH — обновляем div_count если вырос
                elif _div_count > (_wl.get(symbol).div_count if _wl.get(symbol) else 0):
                    _wl.add(symbol, _rec_dir, _rec_str, _wl_reason, _pivot_key, _pivot_level, _div_count)
            else:
                # Добавляем новую запись в WL
                _wl.add(symbol, _rec_dir, _rec_str, _wl_reason, _pivot_key, _pivot_level, _div_count)
    # ── /DEV-22 ────────────────────────────────────────────────────────────────

    # Регистрируем сделку ДО отправки TG — чтобы footer "зарегистрирована" соответствовал реальности
    trade_registered = False
    if should_register:
        try:
            extra: dict = {}
            if distance_to_pivot_pct:
                extra["distance_to_pivot_pct"] = distance_to_pivot_pct
            if btc_counter_trend:
                extra["btc_counter_trend"] = True   # shadow: для аналитики WR с/без BTC-фильтра
            # Извлекаем факторы confluence для аналитики WR по каждому фактору
            conf_factors = []
            for sig in (recommendation.supporting_signals or []):
                if getattr(sig, "signal_type", None) and sig.signal_type.value == "confluence":
                    conf_factors = (sig.data or {}).get("factors", [])
                    break
            if conf_factors:
                extra["confluence_factors"] = conf_factors
            # ARCH-28: FVG+Pivot confluence зоны в features_json
            _fvg_zones = (recommendation.metadata or {}).get("fvg_confluences")
            if _fvg_zones:
                extra["fvg_confluences"] = _fvg_zones
            # DEV-56/58: Weekly Bias shadow data → features_json (для анализа WR до включения gate)
            _meta = recommendation.metadata or {}
            if "weekly_bias" in _meta:
                extra["weekly_bias"] = _meta["weekly_bias"]
                extra["weekly_context_score"] = _meta.get("weekly_context_score", 0)
                extra["weekly_gate_would_block"] = _meta.get("weekly_gate_would_block", False)
                extra["weekly_bias_blocked"] = _meta.get("weekly_gate_would_block", False)  # TR-007 алиас
            # ML-CONTEXT: WT-фичи из supporting signals (CONFLUENCE signal.data)
            for _sig in (recommendation.supporting_signals or []):
                if getattr(_sig, "signal_type", None) and _sig.signal_type.value == "confluence":
                    _sd = _sig.data or {}
                    if "wt_cross_quality" in _sd:
                        extra["wt_cross_quality"] = _sd["wt_cross_quality"]  # "in_zone"/"out_zone"
                    if "div_type" in _sd:
                        extra["wt_div_type"] = _sd["div_type"]  # "regular_bull"/"hidden_bull"/etc.
                    for _k in ("mtf_4h_trend", "mtf_4h_wt", "mtf_4h_zone"):
                        if _k in _sd:
                            extra[_k] = _sd[_k]
                    break
            # ML-CONTEXT: дивергенции из supporting signals
            extra["div_count"] = _div_count  # уже посчитан выше (DIVERGENCE сигналы)
            extra["hidden_div"] = int(any(
                "hidden" in str((_s.data or {}).get("div_type", "")).lower()
                for _s in (recommendation.supporting_signals or [])
            ))
            # ML-CONTEXT: WT значения на entry TF и HTF из pre_fetched_dfs
            if pre_fetched_dfs:
                _entry_tf_key = getattr(recommendation, "timeframe", None) or "15m"
                for _tf_key, _feat_key_wt1, _feat_key_wt2 in [
                    (_entry_tf_key, "wt1_value",   "wt2_value"),
                    ("1h",          "htf_wt1_1h",  "htf_wt2_1h"),
                    ("4h",          "htf_wt1_4h",  "htf_wt2_4h"),
                ]:
                    _df_tf = pre_fetched_dfs.get(_tf_key)
                    if _df_tf is not None and "wt1" in _df_tf.columns and len(_df_tf) > 0:
                        try:
                            _w1 = round(float(_df_tf["wt1"].iloc[-1]), 1)
                            _w2 = round(float(_df_tf["wt2"].iloc[-1]), 1)
                            extra[_feat_key_wt1] = _w1
                            extra[_feat_key_wt2] = _w2
                            if _feat_key_wt1 == "wt1_value":  # только для entry TF
                                extra["wt_zone"] = "OS" if _w1 <= -60 else "OB" if _w1 >= 60 else "N"
                        except Exception:
                            pass
            trade_id = await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector, extra_features=extra or None)
            trade_registered = trade_id is not None
            if not trade_registered:
                logger.warning("[%s] register_trade вернул None (нет entry_price/SL/TP?) — сделка НЕ сохранена", symbol)
            else:
                if hasattr(bot, "ws_feed") and bot.ws_feed.is_alive():
                    bot.ws_feed.update_priority_pairs([symbol])
                # DEV-77: OrderExecutor — VST/LIVE исполнение (SIM_ONLY = только лог)
                if hasattr(bot, "order_executor") and is_actionable:
                    try:
                        _oe = bot.order_executor
                        _oe_dir = getattr(recommendation.direction, "value", "LONG")
                        _oe_entry = float(recommendation.entry_price or 0)
                        _oe_sl = float(recommendation.stop_loss or 0)
                        _oe_tp1 = float(recommendation.take_profit or 0)
                        _oe_tp2 = float(recommendation.tp1_price or 0) or None
                        if _oe_entry > 0 and _oe_sl > 0 and _oe_tp1 > 0:
                            # Реальный баланс с биржи (VST) или config (SIM)
                            _deposit = await _oe.get_available_balance()
                            _risk_pct = float(bot.config.get("trading.risk_pct", 1.0))
                            _leverage = int(bot.config.get("trading.leverage", 5))
                            _qty = bot.position_sizer.calc_qty(
                                entry_price=_oe_entry,
                                sl_price=_oe_sl,
                                deposit=_deposit,
                                risk_pct=_risk_pct,
                                leverage=_leverage,
                            )
                            if _qty > 0:
                                _br = await _oe.open_bracket(
                                    symbol=symbol,
                                    direction=_oe_dir,
                                    entry_price=_oe_entry,
                                    sl=_oe_sl,
                                    tp1=_oe_tp1,
                                    tp2=_oe_tp2,
                                    qty=_qty,
                                )
                                if not _br.success:
                                    logger.warning("[%s] OrderExecutor ошибка: %s", symbol, _br.error)
                                else:
                                    logger.info(
                                        "[%s] [%s] bracket: %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                                        symbol, _br.mode.upper(), _oe_dir, _qty,
                                        _oe_entry, _oe_sl, _oe_tp1, _br.order_id, _br.notional_usdt,
                                    )
                                    # Привязываем exchange_order_id — только эти сделки будут синхронизироваться с биржей
                                    if _br.order_id and trade_id:
                                        bot.trade_simulator.set_exchange_order_id(trade_id, _br.order_id)
                                        # Асинхронно получаем и сохраняем SL orderId для TSL cancel+replace
                                        _pos_side = "LONG" if _oe_dir == "LONG" else "SHORT"
                                        import asyncio as _asyncio
                                        from bot.loops.trade_tracker import fetch_and_save_sl_order_id
                                        _asyncio.create_task(fetch_and_save_sl_order_id(
                                            bot, trade_id, symbol, _pos_side))
                            else:
                                logger.warning("[%s] OrderExecutor: qty=0 (deposit=%.2f risk=%.1f%% sl_dist=?)",
                                               symbol, _deposit, _risk_pct)
                    except Exception as _oe_e:
                        logger.warning("[%s] OrderExecutor: %s", symbol, _oe_e)
        except Exception as e:
            logger.warning("TradeSimulator register_trade для %s (%s): %s", symbol, signal_type, e, exc_info=True)

    # Регистрируем сделки остальных стратегий (только в БД, без TG)
    other_recs = (getattr(recommendation, "metadata", None) or {}).get("all_strategy_recs", {})
    if other_recs:
        for strat_name, other_rec in other_recs.items():
            try:
                _dir_ok_other = (
                    getattr(other_rec, "action", "WATCH") in ("BUY", "SELL")
                    and getattr(other_rec, "direction", None) is not None
                    and other_rec.direction.value != "NEUTRAL"
                )
                if _dir_ok_other and other_rec.overall_strength >= min_strength_register:
                    other_rec.metadata = other_rec.metadata or {}
                    other_rec.metadata["strategy_name"] = strat_name
                    # ARCH-58: применяем иерархию пивотов для побочных стратегий
                    if hasattr(bot, "pivot_calculator"):
                        try:
                            _odir = getattr(other_rec.direction, "value", "")
                            _oentry = getattr(other_rec, "entry_price", None) or 0
                            _osl = getattr(other_rec, "stop_loss", None)
                            if _odir in ("LONG", "SHORT") and _oentry > 0 and _osl is not None:
                                _ores = bot.pivot_calculator.get_tp_by_hierarchy(
                                    direction=_odir,
                                    entry_price=_oentry,
                                    symbol=symbol,
                                    stop_loss=_osl,
                                    min_r=bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0),
                                )
                                if _ores:
                                    other_rec.take_profit, other_rec.tp_source = _ores
                        except Exception as _e58:
                            logger.debug("[ARCH-58/other_recs] %s '%s': %s", symbol, strat_name, _e58)
                    # DEV-126: передаём weekly_bias + htf_wt из контекста основной рекомендации
                    _or_extra: dict = {}
                    _main_meta = (recommendation.metadata or {}) if recommendation else {}
                    if "weekly_bias" in _main_meta:
                        _or_extra["weekly_bias"] = _main_meta["weekly_bias"]
                        _or_extra["weekly_context_score"] = _main_meta.get("weekly_context_score", 0)
                    if pre_fetched_dfs:
                        for _or_tf, _or_k1, _or_k2 in [
                            ("1h", "htf_wt1_1h", "htf_wt2_1h"),
                            ("4h", "htf_wt1_4h", "htf_wt2_4h"),
                        ]:
                            _or_df = pre_fetched_dfs.get(_or_tf)
                            if _or_df is not None and "wt1" in _or_df.columns and len(_or_df) > 0:
                                try:
                                    _or_extra[_or_k1] = round(float(_or_df["wt1"].iloc[-1]), 1)
                                    _or_extra[_or_k2] = round(float(_or_df["wt2"].iloc[-1]), 1)
                                except Exception:
                                    pass
                    await bot.trade_simulator.register_trade_async(
                        other_rec, bot.data_collector,
                        extra_features=_or_extra or None,
                    )
                    logger.debug("[%s] Стратегия '%s' зарегистрирована в БД", symbol, strat_name)
            except Exception as e:
                logger.debug("register_trade стратегии '%s' для %s: %s", strat_name, symbol, e)

    text = raw_text
    if recommendation:
        try:
            # Если активная стратегия — MTF_BIAS, используем специальный форматтер
            _mtf_bias_sig = next(
                (s for s in (recommendation.supporting_signals or [])
                 if getattr(s, "signal_type", None) and s.signal_type.value == "mtf_bias"),
                None
            )
            if _mtf_bias_sig is not None:
                from core.mtf_interpreter import mtf_bias_message
                text = mtf_bias_message(symbol, _mtf_bias_sig)
            else:
                _show_fvg = bot.config.get("signals.show_fvg_confluences", True)
                text = await format_intelligence_message(recommendation, show_fvg_confluences=_show_fvg)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text
        if btc_warning:
            text = text.rstrip() + btc_warning
        # Стандартный footer статуса регистрации — в каждом сообщении
        if is_actionable and trade_registered:
            kelly_line = _get_kelly_footer(bot)
            text = text.rstrip() + "\n─────────────\n💾 <i>Сделка зарегистрирована в симуляторе</i>" + kelly_line
        elif recommendation:
            _reason_parts = []
            if getattr(recommendation, "action", "WATCH") not in ("BUY", "SELL"):
                _reason_parts.append(f"action={getattr(recommendation, 'action', '?')}")
            if recommendation.overall_strength < min_strength_register:
                _reason_parts.append(f"сила={recommendation.overall_strength:.0f}&lt;{min_strength_register}")
            _mtf = (recommendation.metadata or {}).get("mtf_context", {})
            _bias = _mtf.get("direction_bias", "") if isinstance(_mtf, dict) else ""
            _aligned = _mtf.get("aligned_pct") if isinstance(_mtf, dict) else None
            _mtf_str = f" · MTF {_bias} {_aligned}%" if _bias and _aligned else ""
            _reason_str = ", ".join(_reason_parts) if _reason_parts else "WATCH"
            text = text.rstrip() + f"\n─────────────\n❌ <i>Не зарегистрирован: {_reason_str}{_mtf_str}</i>"
            logger.info("[%s] Сделка не зарегистрирована: %s%s", symbol, _reason_str, _mtf_str)

    # ── PNG-график (если send_chart: true в config) ───────────────────────────
    png_bytes = None
    if bot.config.get("signals.send_chart", False):
        try:
            from core.chart_builder import build_signal_chart
            chart_tf   = bot.config.get("signals.chart_tf", "1h")
            chart_bars = int(bot.config.get("signals.chart_bars", 300))
            _chart_fvg_all = (getattr(recommendation, "metadata", None) or {}).get("fvg_confluences") or []
            # Только зоны в ±8% от текущей цены — не перегружать чарт дальними уровнями
            _chart_fvg = [z for z in _chart_fvg_all
                          if abs(z.get("distance_pct", 999)) <= 8.0] or None
            png_bytes = await build_signal_chart(
                symbol, tf=chart_tf, bars=chart_bars,
                bot=bot, fvg_zones=_chart_fvg,
            )
        except Exception:
            logger.exception("Ошибка генерации графика для %s", symbol)

    await broadcast_with_subscription_check(bot, text, signal_type, chart_png=png_bytes)

    # fallback_rec отключён: analyze_symbol с MTF multiplier — единственный путь регистрации.
    # Старый fallback обходил MTF context → strength 70-100 при bias AGAINST → WR=8.7%.
    if not should_register and not trade_registered and fallback_rec is not None:
        fallback_strength = getattr(fallback_rec, "overall_strength", 0)
        logger.info("[%s] Fallback НЕ регистрируем (MTF bypass fix): str=%.0f, signal=%s",
                    symbol, fallback_strength, signal_type)


_TG_BROADCAST_SEM = asyncio.Semaphore(25)  # DEV-120: Telegram safe rate ~25 msg/sec


async def broadcast_with_subscription_check(bot, text: str, signal_type: str,
                                             chart_png: bytes | None = None):
    if not bot.subscribers:
        logger.warning("Нет подписчиков для отправки сигнала %s", signal_type)
        return

    uids = list(bot.subscribers)
    logger.info("Отправка сигнала %s для %d подписчиков (chart=%s)",
                signal_type, len(uids), chart_png is not None)

    sent_results = []

    async def _send_one(uid: int) -> bool:
        try:
            if not bot.subscription_manager.can_receive_signal(uid, signal_type):
                logger.debug("Пользователь %s не может получить сигнал %s", uid, signal_type)
                return False
            if not bot.subscription_manager.can_send_signal_today(uid):
                logger.debug("Пользователь %s достиг дневного лимита", uid)
                return False

            async with _TG_BROADCAST_SEM:
                if chart_png:
                    caption = text[:1020] + "…" if len(text) > 1024 else text
                    from aiogram.types import BufferedInputFile
                    await bot.bot.send_photo(
                        chat_id=uid,
                        photo=BufferedInputFile(chart_png, filename="chart.png"),
                        caption=caption,
                        parse_mode="HTML",
                    )
                else:
                    await bot.bot.send_message(
                        chat_id=uid, text=text, disable_web_page_preview=True, parse_mode="HTML"
                    )

            bot.subscription_manager.record_signal_sent(uid, signal_type)
            logger.debug("Сигнал %s отправлен пользователю %s", signal_type, uid)
            return True
        except Exception:
            logger.exception("Ошибка отправки сообщения %s", uid)
            return False

    # DEV-120: параллельная рассылка всем подписчикам
    sent_results = await asyncio.gather(*[_send_one(uid) for uid in uids])
    sent_count = sum(sent_results)

    if sent_count == 0:
        logger.warning("Сигнал %s не отправлен ни одному подписчику", signal_type)
    else:
        logger.info("Сигнал %s отправлен %d/%d подписчикам", signal_type, sent_count, len(uids))


def trade_tracker_loop(bot):
    """Делегирует в bot.loops.trade_tracker (перемещено туда для разбивки монолита)."""
    from bot.loops.trade_tracker import trade_tracker_loop as _loop
    return _loop(bot)


# ---------------------------------------------------------------------------
# Этап 5.3 — Еженедельный отчёт
# ---------------------------------------------------------------------------

def format_weekly_report(stats: dict) -> str:
    lines = [
        "<b>ЕЖЕНЕДЕЛЬНЫЙ ОТЧЁТ</b>",
        f"Сделок закрыто: <b>{stats['total']}</b>",
        f"Win rate: <b>{stats['win_rate']}%</b>  •  Avg R: <b>{stats['avg_r']}</b>  •  Best R: <b>{stats['best_r']}</b>",
    ]
    if stats.get("by_signal_type"):
        lines += ["", "<b>По типу сигнала:</b>"]
        for s in stats["by_signal_type"][:5]:
            cnt = s["cnt"] or 0
            wr = round((s["wins"] or 0) / cnt * 100) if cnt else 0
            avg_r = round(s["avg_r"] or 0, 2)
            lines.append(f"• {s['signal_type']}: {cnt} сд., WR {wr}%, Avg R {avg_r}")
    return "\n".join(lines)


async def send_weekly_report(bot) -> None:
    from core.performance_engine import PerformanceEngine
    try:
        pe = PerformanceEngine(bot.trade_simulator.db_path)
        stats = pe.weekly_summary(days_back=7)
        if not stats["total"]:
            logger.info("Еженедельный отчёт: нет закрытых сделок за неделю")
            return
        text = format_weekly_report(stats)
        await broadcast_with_subscription_check(bot, text, "weekly_report")
        logger.info("Еженедельный отчёт отправлен (%d сделок)", stats["total"])
    except Exception:
        logger.exception("Ошибка отправки еженедельного отчёта")
