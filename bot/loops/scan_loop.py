"""
Основной цикл сканирования рынка: monitor_market, scan_all_pairs, scan_one, _prefetch_pivots.
Импортирует фильтры и broadcast из bot.monitoring — circular import исключён через lazy import
в start_monitoring (bot.monitoring не импортирует этот модуль на уровне модуля).
"""
import asyncio
import logging
import time as _time
from collections import deque
from datetime import datetime

from core.message_builder import anomaly_message, wt_message, mtf_message
from core.divergence_detector import divergence_message, mtf_divergence_message
from core.signal_checkers import (
    check_anomaly_signals,
    check_wt_signals as _check_wt_signals,
    check_mtf_signals as _check_mtf_signals,
)
from core.signal_models import SignalData, SignalType, SignalDirection
from core.confluence_scanner import scan_confluence, confluence_message as _confluence_message
from core.data_quality import check_ohlcv_quality, MIN_BARS

logger = logging.getLogger(__name__)


async def _prefetch_pivots(bot) -> None:
    """Прогревает кеш пивотов для всех пар параллельно.
    Semaphore намеренно маленький — не конкурируем со сканом за ApiEngine.Semaphore(20)."""
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


async def scan_all_pairs(bot, check_divergences: bool = True) -> None:
    """Один проход по всем парам: для каждой пары все проверки подряд,
    затем broadcast СНАРУЖИ семафора — analyze_symbol не блокирует OHLCV-слоты."""
    from bot.monitoring import _broadcast_intelligence_alert, _div_passes_filters

    scan_sem_size = int(bot.config.get("performance.scan_semaphore_size", 20))
    sem = asyncio.Semaphore(scan_sem_size)
    cycle_start = _time.monotonic()

    # Лимит confluence-сигналов за один цикл — защита от Telegram flood control
    _confluence_max_per_cycle = int(bot.config.get("analysis.confluence.max_per_cycle", 3))
    _confluence_sent = 0
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


async def monitor_market(bot) -> None:
    """Главный цикл мониторинга: запускает скан каждые N сек + фоновые задачи."""
    from bot.monitoring import (
        check_mtf_alerts,
        check_trend_signals,
        check_pivot_reversals,
        check_cascade_divergences,
    )
    try:
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
