"""
Фоновый мониторинг рынка: цикл проверок и рассылка сигналов.
Все функции принимают bot (TradingAlertBot) первым аргументом.
"""
import asyncio
import logging
import sqlite3
import time as _time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.message_builder import anomaly_message, wt_message, mtf_message
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import divergence_message, mtf_divergence_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.trading_intelligence import format_intelligence_message
from collections import deque
from core.signal_checkers import check_anomaly_signals, check_wt_signals as _check_wt_signals, check_mtf_signals as _check_mtf_signals
from core.signal_models import SignalData, SignalType, SignalDirection
from core.confluence_scanner import scan_confluence, confluence_message as _confluence_message
from core.data_quality import check_ohlcv_quality, MIN_BARS
from bot.keyboards import main_menu

logger = logging.getLogger(__name__)

# Ограничиваем параллельные вызовы analyze_symbol (тяжёлый: ML + 3 OHLCV-фетча)
# Размер задаётся через config: performance.analyze_semaphore_size (default 3)
_analyze_sem: asyncio.Semaphore | None = None


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


def _make_pivot_recommendation(info: dict):
    """Адаптер dict от check_pivot_level_signal → объект для register_trade."""
    is_long = "LONG" in info.get("type", "")
    confidence_str = info.get("confidence", "HIGH")
    conf_float = 0.85 if confidence_str == "VERY_HIGH" else 0.70
    strength = 80 if confidence_str == "VERY_HIGH" else 65
    tp_levels = info.get("take_profits", [])
    tp1 = tp_levels[0]["price"] if tp_levels else None
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="pivot_reversal"))
    return SimpleNamespace(
        symbol=info.get("symbol", ""),
        entry_price=info.get("entry_price"),
        direction=SimpleNamespace(value="LONG" if is_long else "SHORT"),
        stop_loss=info.get("stop_loss"),
        take_profit=tp1,
        overall_strength=strength,
        confidence=conf_float,
        timestamp=datetime.now(),
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        metadata={},
    )


async def start_monitoring(bot, message):
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


async def _prefetch_pivots(bot):
    """Прогревает кеш пивотов для всех пар параллельно.
    Semaphore(5) — намеренно медленно, чтобы не конкурировать со сканом за ApiEngine.Semaphore(20)."""
    pairs = bot.monitored_pairs
    pfx_sem_size = int(bot.config.get("performance.prefetch_pivots_semaphore_size", 2))
    sem = asyncio.Semaphore(pfx_sem_size)

    async def _fetch_one(sym):
        async with sem:
            try:
                await bot.pivot_calculator.get_multi_timeframe_pivots(sym, bot.data_collector)
            except Exception:
                pass

    logger.info("Прогрев кеша пивотов для %d пар...", len(pairs))
    await asyncio.gather(*[_fetch_one(sym) for sym in pairs])
    logger.info("Кеш пивотов прогрет.")


async def scan_all_pairs(bot, check_divergences: bool = True):
    """Один проход по всем парам: для каждой пары делаем все 7 проверок подряд,
    затем broadcast СНАРУЖИ семафора — analyze_symbol не блокирует OHLCV-слоты."""
    scan_sem_size = int(bot.config.get("performance.scan_semaphore_size", 20))
    sem = asyncio.Semaphore(scan_sem_size)
    cycle_start = _time.monotonic()
    # Лимит confluence-сигналов за один цикл — защита от Telegram flood control
    _confluence_max_per_cycle = int(bot.config.get("analysis.confluence.max_per_cycle", 3))
    _confluence_sent = 0   # счётчик, разделяемый между scan_one через nonlocal
    _div_proximity_pct = bot.config.get("analysis.divergence.pivot_proximity_pct", 4.0)
    _ohlcv_limit = int(bot.config.get("performance.ohlcv_scan_limit", 160))
    _slow_ohlcv  = float(bot.config.get("performance.ohlcv_slow_threshold_sec", 5.0))
    _slow_div    = float(bot.config.get("performance.divergence_slow_threshold_sec", 3.0))
    _slow_pair   = float(bot.config.get("performance.pair_slow_threshold_sec", 10.0))
    _slow_cycle  = float(bot.config.get("performance.scan_cycle_warning_threshold_sec", 55.0))

    async def scan_one(sym):
        signals_to_broadcast = []  # [(sig_type, raw_text, fallback_rec), ...]
        all_scan_signals = []      # SignalData от детекторов — для pre_collected_signals

        async with sem:
            t_enter = _time.monotonic()
            try:
                # Параллельная загрузка всех TF (limit из конфига для cache-hit в detect_divergence)
                df_15m, df_1h, df_3m = await asyncio.gather(
                    bot.data_collector.get_ohlcv(sym, "15m", limit=_ohlcv_limit),
                    bot.data_collector.get_ohlcv(sym, "1h", limit=_ohlcv_limit),
                    bot.data_collector.get_ohlcv(sym, "3m", limit=100),
                )
                t_ohlcv = _time.monotonic()
                if (t_ohlcv - t_enter) > _slow_ohlcv:
                    logger.warning("[scan] OHLCV медленно %s: %.1fs", sym, t_ohlcv - t_enter)
                if df_15m is None or df_15m.empty:
                    return

                # Проверка качества OHLCV: глубина, свежесть, NaN-пробелы
                ok, reason = check_ohlcv_quality(
                    df_15m,
                    timeframe="15m",
                    min_bars=MIN_BARS["divergence"],  # 160 — самый строгий детектор
                    symbol=sym,
                )
                if not ok:
                    logger.info("[scan] Пропускаем %s: %s", sym, reason)
                    return

                # Обновляем price/volume history из уже загруженных данных
                # (заменяет fetch_candles: нет лишних API-вызовов)
                if len(df_15m) >= 2:
                    dc = bot.data_collector
                    prev_c = df_15m["close"].iloc[-2] or 0.0
                    last_c = df_15m["close"].iloc[-1] or 0.0
                    pct = ((last_c - prev_c) / prev_c * 100) if prev_c else 0.0
                    dc.price_history.setdefault(sym, deque(maxlen=dc.history_size)).append(pct)
                    dc.volume_history.setdefault(sym, deque(maxlen=dc.history_size)).append(
                        float(df_15m["volume"].iloc[-1] or 0.0)
                    )

                # 1. Anomalies
                for sig in await check_anomaly_signals(sym, df_15m):
                    info = sig.data or {}
                    bot.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                    bot.signal_counters["anomaly"] += 1
                    bot.signal_counters["total"] += 1
                    signals_to_broadcast.append(("anomaly", anomaly_message(sym, info), None))
                    all_scan_signals.append(sig)

                # 2. WT (15m и 1h из кеша для последующих вызовов)
                for sig in await _check_wt_signals(sym, df_15m, df_1h):
                    info = sig.data or {}
                    logger.info("WT сигнал обнаружен для %s", sym)
                    bot.signal_counters["wt_signal"] += 1
                    bot.signal_counters["total"] += 1
                    signals_to_broadcast.append(("wt_signal", wt_message(sym, info), None))
                    all_scan_signals.append(sig)

                # 3. MTF signals (15m, 1h из кеша)
                for sig in await _check_mtf_signals(sym, df_1h, df_15m, df_3m):
                    info = sig.data or {}
                    bot.signal_counters["mtf_signal"] += 1
                    bot.signal_counters["total"] += 1
                    signals_to_broadcast.append(("mtf_signal", mtf_message(sym, info), None))
                    all_scan_signals.append(sig)

                # 4. Confluence scanner (lookback по df_15m + df_1h + кеш пивотов)
                nonlocal _confluence_sent
                pivot_cache = getattr(getattr(bot, "pivot_calculator", None), "pivot_cache", {})
                for sig in scan_confluence(sym, df_15m, df_1h, pivot_cache, cfg=bot.config):
                    bot.signal_counters["confluence"] = bot.signal_counters.get("confluence", 0) + 1
                    bot.signal_counters["total"] += 1
                    all_scan_signals.append(sig)
                    if _confluence_sent < _confluence_max_per_cycle:
                        signals_to_broadcast.append(("confluence", _confluence_message(sym, sig), None))
                        _confluence_sent += 1
                    else:
                        logger.debug("[confluence] %s: лимит %d/цикл достигнут, пропуск TG",
                                     sym, _confluence_max_per_cycle)

                # 5. MTF alerts — вынесены в check_mtf_alerts (каждые 5 мин),
                # т.к. collect_mtf_data фетчит 7 TF (5m, 45m, 4h, 1d не в кеше)

                # 6. Trend following — вынесен в check_trend_signals (каждые 5 мин),
                # т.к. check_trend_following_signal фетчит 4h+5m (не в кеше)

                # 7. Divergences: каждые 3 цикла (180 сек — медленный сигнал)
                t_before_div = _time.monotonic()
                div_found = False
                if check_divergences:
                    pivot_calc = getattr(bot, "pivot_calculator", None)
                    # Этап 8.4.5: режим пары — скрытые дивергенции отклоняем в RANGE/HIGH_VOL
                    _pair_regime = ""
                    try:
                        from core.market_regime import MarketRegimeClassifier
                        _pair_regime = MarketRegimeClassifier().classify_from_ohlcv(
                            df_15m.values.tolist()
                        ) or ""
                    except Exception:
                        pass
                    try:
                        has_mtf, mtf_info = await bot.divergence_detector.detect_mtf_divergence(
                            sym, bot.data_collector
                        )
                        if has_mtf:
                            passed, reason = _div_passes_filters(
                                mtf_info, df_15m, pivot_calc, sym, _div_proximity_pct,
                                market_regime=_pair_regime,
                            )
                            if passed:
                                div_found = True
                                bot.signal_counters["divergence"] += 1
                                bot.signal_counters["total"] += 1
                                logger.info("[%s] MTF-дивергенция 1h+15m: %s", sym, mtf_info.get("type"))
                                signals_to_broadcast.append(("mtf_divergence", mtf_divergence_message(sym, mtf_info), None))
                                _dir = SignalDirection.LONG if mtf_info.get("direction") == "LONG" else SignalDirection.SHORT
                                # Кешируем для меню "Дивергенции" без влияния на pre_signals analyze_symbol
                                _div_stub = SignalData(
                                    symbol=sym, signal_type=SignalType.DIVERGENCE, direction=_dir,
                                    strength=mtf_info.get("strength", 60), confidence=0.75,
                                    timestamp=datetime.now(), data=dict(mtf_info, timeframe="1h"), timeframe="1h",
                                )
                                bot.recent_signals.setdefault(sym, [])
                                bot.recent_signals[sym] = [
                                    s for s in bot.recent_signals[sym]
                                    if s.signal_type != SignalType.DIVERGENCE
                                ] + [_div_stub]
                            else:
                                logger.debug("[%s] MTF-дивергенция отфильтрована: %s", sym, reason)
                    except Exception:
                        logger.exception("Ошибка check_mtf_divergence для %s", sym)

                    if not div_found:
                        for tf in ("15m", "1h"):
                            try:
                                has_div, div_info = await bot.divergence_detector.detect_divergence(
                                    sym, bot.data_collector, timeframe=tf
                                )
                                if has_div:
                                    passed, reason = _div_passes_filters(
                                        div_info, df_15m, pivot_calc, sym, _div_proximity_pct,
                                        market_regime=_pair_regime,
                                    )
                                    if passed:
                                        bot.signal_counters["divergence"] += 1
                                        bot.signal_counters["total"] += 1
                                        logger.info("[%s] Дивергенция на %s: %s", sym, tf, div_info.get("type"))
                                        signals_to_broadcast.append(("divergence", divergence_message(sym, div_info), None))
                                        _dir = SignalDirection.LONG if div_info.get("direction") == "LONG" else SignalDirection.SHORT
                                        # Кешируем для меню "Дивергенции" без влияния на pre_signals analyze_symbol
                                        _div_stub = SignalData(
                                            symbol=sym, signal_type=SignalType.DIVERGENCE, direction=_dir,
                                            strength=div_info.get("strength", 50), confidence=0.7,
                                            timestamp=datetime.now(), data=div_info, timeframe=tf,
                                        )
                                        bot.recent_signals.setdefault(sym, [])
                                        bot.recent_signals[sym] = [
                                            s for s in bot.recent_signals[sym]
                                            if s.signal_type != SignalType.DIVERGENCE
                                        ] + [_div_stub]
                                        break
                                    else:
                                        logger.debug("[%s] Дивергенция %s отфильтрована: %s", sym, tf, reason)
                            except Exception:
                                logger.exception("Ошибка check_divergences для %s %s", sym, tf)

                # 7. Pivot reversals — выполняем в отдельном цикле (check_pivot_reversals),
                # т.к. check_pivot_level_signal фетчит 1m+5m данные (не в кеше) и замедляет скан

                t_done = _time.monotonic()
                if (t_done - t_before_div) > _slow_div:
                    logger.warning("[scan] Divergence медленно %s: %.1fs", sym, t_done - t_before_div)
                if (t_done - t_enter) > _slow_pair:
                    logger.warning("[scan] Пара медленно %s: total=%.1fs ohlcv=%.1fs div=%.1fs",
                                   sym, t_done - t_enter, t_ohlcv - t_enter, t_done - t_before_div)
            except Exception:
                logger.exception("Ошибка scan_one для %s", sym)

        # Кешируем все сигналы по паре для меню "Все сигналы"
        if all_scan_signals:
            bot.recent_signals[sym] = all_scan_signals

        # СНАРУЖИ семафора: broadcast как fire-and-forget задачи
        # (analyze_symbol может занимать 30-60 сек — не блокируем asyncio.gather)
        # pre_signals передаём только в первый broadcast — analyze_symbol закеширует результат
        pre = all_scan_signals if all_scan_signals else None
        for sig_type, raw_text, fallback_rec in signals_to_broadcast:
            asyncio.create_task(
                _broadcast_intelligence_alert(bot, sym, raw_text, sig_type,
                                             fallback_rec=fallback_rec, pre_signals=pre)
            )

    pairs = list(bot.monitored_pairs)
    stats = bot.data_collector._engine.cache_stats()
    logger.info("Скан: %d пар | кеш=%d CB=%s", len(pairs), stats["cache_size"], stats["cb_state"])
    await asyncio.gather(*[scan_one(sym) for sym in pairs])
    elapsed = _time.monotonic() - cycle_start
    logger.info("Цикл сканирования завершён: %.1f сек / %d пар", elapsed, len(pairs))
    if elapsed > _slow_cycle:
        logger.warning("⚠️ Цикл превысил %.0f сек — рассмотреть увеличение Semaphore или sleep", _slow_cycle)


async def monitor_market(bot):
    try:
        # fetch_candles убран: price_history/volume_history обновляются в scan_one
        # из уже загруженных df_15m — нет дополнительных 398 API-вызовов каждые 60 сек
        _last_pivot_day = datetime.utcnow().date()  # уже прогрет в start_monitoring
        _pivot_cycle = 0
        _cascade_4h_cycle = 0
        _div_cycle = 0
        while bot.is_monitoring:
            # Читаем цикловые интервалы из конфига (hot-reload)
            _div_n      = int(bot.config.get("monitoring.check_intervals.divergences_every_n_cycles", 3))
            _bg_n       = int(bot.config.get("monitoring.check_intervals.background_every_n_cycles", 5))
            _cascade_n  = int(bot.config.get("monitoring.check_intervals.cascade_div_every_n_cycles", 60))

            # Фоновый пересчёт пивотов при смене дня/недели/месяца
            today = datetime.utcnow().date()
            if _last_pivot_day != today:
                _last_pivot_day = today
                asyncio.create_task(_prefetch_pivots(bot))
                logger.info("Новый день (%s) — фоновый пересчёт пивотов запущен параллельно со сканером", today)

            _div_cycle += 1
            _check_div = (_div_cycle % _div_n == 0)
            await scan_all_pairs(bot, check_divergences=_check_div)

            # Тяжёлые проверки (некешируемые TF) — раз в N циклов в фоне
            _pivot_cycle += 1
            if _pivot_cycle >= _bg_n:
                _pivot_cycle = 0
                asyncio.create_task(check_mtf_alerts(bot))      # 7 TF включая 5m, 45m, 4h, 1d
                asyncio.create_task(check_trend_signals(bot))   # 4h + 5m
                asyncio.create_task(check_pivot_reversals(bot)) # 1m + 5m

            # MTF-дивергенция 4h→1h — раз в N циклов (4h свеча обновляется медленно)
            _cascade_4h_cycle += 1
            if _cascade_4h_cycle >= _cascade_n:
                _cascade_4h_cycle = 0
                asyncio.create_task(check_cascade_divergences(bot, "4h", "1h"))

            await asyncio.sleep(bot.config.get("analysis.check_interval", 60))
    except asyncio.CancelledError:
        logger.info("Мониторинг остановлен")
        raise
    except Exception:
        logger.exception("Ошибка в monitor_market")


async def check_anomalies(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=30)
                if df_15m is None or df_15m.empty:
                    return
                signals = await check_anomaly_signals(sym, df_15m)
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
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=150)
                if df_15m is None or df_15m.empty:
                    return
                df_1h = await bot.data_collector.get_ohlcv(sym, "1h", limit=60)
                signals = await _check_wt_signals(sym, df_15m, df_1h)
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


async def check_mtf_signals(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                df_1h  = await bot.data_collector.get_ohlcv(sym, "1h",  limit=100)
                df_15m = await bot.data_collector.get_ohlcv(sym, "15m", limit=100)
                df_3m  = await bot.data_collector.get_ohlcv(sym, "3m",  limit=100)
                if df_1h is None or df_1h.empty or df_15m is None or df_15m.empty:
                    return
                signals = await _check_mtf_signals(sym, df_1h, df_15m, df_3m)
                for sig in signals:
                    info = sig.data or {}
                    raw_text = mtf_message(sym, info)
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_signal")
                    bot.signal_counters["mtf_signal"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_mtf_signals для %s", sym)

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
        strength=strength, confidence=0.7, timestamp=datetime.now(), data=data or {},
    )


async def check_mtf_alerts(bot):
    sem = asyncio.Semaphore(int(bot.config.get("performance.background_check_semaphore_size", 10)))

    async def _one(sym):
        async with sem:
            try:
                snapshot = await collect_mtf_data(sym, bot.data_collector)
                if not snapshot:
                    return
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    raw_text = mtf_alert_message(sym, snapshot, sig)
                    pre = [_make_signal_stub(sym, SignalType.MTF_ALERT, sig)]
                    await _broadcast_intelligence_alert(bot, sym, raw_text, "mtf_alert", pre_signals=pre)
                    bot.signal_counters["mtf_alert"] += 1
                    bot.signal_counters["total"] += 1
            except Exception:
                logger.exception("Ошибка check_mtf_alerts для %s", sym)

    await asyncio.gather(*[_one(sym) for sym in bot.monitored_pairs])


async def check_cascade_divergences(bot, senior_tf: str, junior_tf: str):
    """Проверяет MTF-конфлюэнцию дивергенций (скрытая senior_tf + регулярная junior_tf) для всех пар."""
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
            for tf in ("15m", "1h"):
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
                                        fallback_rec=None, pre_signals=None):
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
                symbol, pre_collected_signals=pre_signals
            )
    except Exception:
        logger.exception("Ошибка AI-анализа для %s при сигнале %s", symbol, signal_type)

    # Этап 5.2: BTC-корреляционный фильтр
    # Слабые контртрендовые сигналы (strength < 70) — блокируем
    # Сильные (strength >= 70) — доставляем с предупреждением
    btc_regime = await _get_btc_regime(bot) if bot.config.get("signal_quality.btc_filter_enabled", True) else None
    btc_warning = ""
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
            if strength_val < ct_thr:
                logger.info("[%s] BTC %s vs %s, сила %d < %d — пропущен",
                            symbol, btc_regime, direction_val, strength_val, ct_thr)
                return
            # Сила >= ct_thr — доставляем с предупреждением
            regime_ru = "восходящем" if btc_regime == "TREND_UP" else "нисходящем"
            dir_ru = "шорт" if direction_val == "SHORT" else "лонг"
            btc_warning = f"\n⚠️ <i>BTC (1h) в {regime_ru} тренде — {dir_ru} против рынка, сигнал сильный ({strength_val}/100)</i>"
            logger.info("[%s] BTC %s vs %s, сила %d >= %d — предупреждение",
                        symbol, btc_regime, direction_val, strength_val, ct_thr)

    # Этап 6: заменяем fixed TP на ближайший пивот с R >= tp_pivot_min_r (из конфига)
    distance_to_pivot_pct: float = 0.0
    if recommendation is not None and hasattr(bot, "pivot_calculator"):
        direction_val = getattr(recommendation.direction, "value", "NEUTRAL")
        entry_price = recommendation.entry_price or 0
        if direction_val in ("LONG", "SHORT") and entry_price > 0:
            pivot_min_r = bot.config.get("trading.sl_tp.tp_pivot_min_r", 2.0)
            pivot_result = bot.pivot_calculator.get_pivot_tp_with_source(
                direction=direction_val,
                entry_price=entry_price,
                symbol=symbol,
                stop_loss=recommendation.stop_loss,
                min_r=pivot_min_r,
            )
            if pivot_result:
                pivot_tp, pivot_src = pivot_result
                recommendation.take_profit = pivot_tp
                recommendation.tp_source = pivot_src
                distance_to_pivot_pct = abs(pivot_tp - entry_price) / entry_price * 100
                logger.debug("[%s] Pivot TP: %.6f (%.2f%%, %s, src=%s)", symbol, pivot_tp, distance_to_pivot_pct, direction_val, pivot_src)

    min_strength = bot.config.get("signal_quality.min_strength", 50)
    min_strength_register = bot.config.get("signal_quality.min_strength_register", 40)

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

    text = raw_text
    if recommendation:
        try:
            text = await format_intelligence_message(recommendation)
        except Exception:
            logger.exception("Ошибка форматирования AI-сообщения для %s", symbol)
            text = raw_text
        if btc_warning:
            text = text.rstrip() + btc_warning
        if is_actionable:
            kelly_line = _get_kelly_footer(bot)
            text = text.rstrip() + "\n─────────────\n💾 <i>Сделка зарегистрирована в симуляторе</i>" + kelly_line

    await broadcast_with_subscription_check(bot, text, signal_type)

    if should_register:
        try:
            extra = {"distance_to_pivot_pct": distance_to_pivot_pct} if distance_to_pivot_pct else None
            await bot.trade_simulator.register_trade_async(recommendation, bot.data_collector, extra_features=extra)
        except Exception as e:
            logger.debug("TradeSimulator register_trade для %s (%s): %s", symbol, signal_type, e)
    elif recommendation:
        reason = []
        if recommendation.overall_strength < min_strength_register:
            reason.append(f"strength={recommendation.overall_strength:.1f}<{min_strength_register}")
        if getattr(recommendation, "action", "WATCH") not in ("BUY", "SELL"):
            reason.append(f"action={getattr(recommendation, 'action', '?')}")
        if getattr(recommendation, "direction", None) is None or recommendation.direction.value == "NEUTRAL":
            reason.append("direction=NEUTRAL")
        logger.info("[%s] Сделка не зарегистрирована: %s", symbol, ", ".join(reason))
    elif fallback_rec is not None:
        fallback_strength = getattr(fallback_rec, "overall_strength", 0)
        if fallback_strength >= min_strength_register:
            try:
                await bot.trade_simulator.register_trade_async(fallback_rec, bot.data_collector)
                logger.info("TradeSimulator fallback: зарегистрирован %s str=%.0f", symbol, fallback_strength)
            except Exception as e:
                logger.debug("TradeSimulator fallback для %s: %s", symbol, e)
        else:
            logger.info("[%s] Fallback не зарегистрирован: strength=%.0f < %d", symbol, fallback_strength, min_strength_register)


async def broadcast_with_subscription_check(bot, text: str, signal_type: str):
    if not bot.subscribers:
        logger.warning("Нет подписчиков для отправки сигнала %s", signal_type)
        return

    logger.info("Отправка сигнала %s для %d подписчиков", signal_type, len(bot.subscribers))
    sent_count = 0
    for uid in list(bot.subscribers):
        try:
            if not bot.subscription_manager.can_receive_signal(uid, signal_type):
                logger.debug("Пользователь %s не может получить сигнал %s", uid, signal_type)
                continue
            if not bot.subscription_manager.can_send_signal_today(uid):
                logger.debug("Пользователь %s достиг дневного лимита", uid)
                continue
            await bot.bot.send_message(chat_id=uid, text=text, disable_web_page_preview=True)
            sent_count += 1
            logger.info("Сигнал %s отправлен пользователю %s", signal_type, uid)
            bot.subscription_manager.record_signal_sent(uid, signal_type)
        except Exception:
            logger.exception("Ошибка отправки сообщения %s", uid)

    if sent_count == 0:
        logger.warning("Сигнал %s не отправлен ни одному подписчику", signal_type)
    else:
        logger.info("Сигнал %s отправлен %d подписчикам", signal_type, sent_count)


async def trade_tracker_loop(bot):
    # Параметры TSL из конфига
    use_tsl = bot.config.get("trading.use_tsl", True)
    tsl_activation_r = bot.config.get("trading.tsl_activation_r", 1.0)

    while True:
        try:
            await asyncio.sleep(300)
            closed = await bot.trade_simulator.check_open_trades_with_tsl(
                bot.data_collector,
                use_tsl=use_tsl,
                tsl_activation_r=tsl_activation_r
            )
            if closed > 0:
                logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("TradeSimulator loop: %s", e)


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
