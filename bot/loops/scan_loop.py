"""
Основной цикл сканирования рынка: monitor_market, scan_all_pairs, scan_one, _prefetch_pivots.
Импортирует фильтры и broadcast из bot.monitoring — circular import исключён через lazy import
в start_monitoring (bot.monitoring не импортирует этот модуль на уровне модуля).
"""
import asyncio
import logging
import random
import time as _time
from collections import deque
from datetime import datetime, timezone

from core.entry_config import get_primary_entry_tf, get_entry_timeframes
from core.message_builder import (
    anomaly_message, wt_message, wt_b_message as _wt_b_message,
    funding_extreme_message as _funding_message,
    liquidity_sweep_message as _sweep_message,
)
from core.divergence_detector import divergence_message, mtf_divergence_message
from core.signal_checkers import (
    check_anomaly_signals,
    check_wt_signals as _check_wt_signals,
    check_wt_b_signals as _check_wt_b_signals,
)
from core.signal_models import SignalData, SignalType, SignalDirection
from core.wt_15m_reversal_scanner import scan_wt_15m_reversal, reversal_message as _confluence_message
from core.data_quality import check_ohlcv_quality, MIN_BARS

logger = logging.getLogger(__name__)

# DEV-41: rate-limit для WL breach — не более 3 входов за 30 минут
_wl_breach_timestamps: deque = deque()


async def _send_wl_alert(bot, symbol: str, text: str) -> None:
    """Отправляет короткое WL-уведомление всем подписчикам."""
    try:
        from bot.monitoring import broadcast_with_subscription_check
        await broadcast_with_subscription_check(bot, text, "wl_alert")
    except Exception as e:
        logger.debug("[WL] Ошибка отправки алерта %s: %s", symbol, e)


async def _handle_wl_breach_entry(bot, symbol: str, wl_entry, current_price: float, df_entry) -> None:
    """
    DEV-WL-BREACH: обработка пробоя пивота В НАПРАВЛЕНИИ — открыть сделку.

    Проверяет gates (regime, cooldown), строит рекомендацию и регистрирует в БД.
    """
    from types import SimpleNamespace
    from bot.monitoring import _is_in_sl_cooldown

    direction = wl_entry.direction  # "LONG" | "SHORT"
    pivot_level = wl_entry.pivot_level
    score = wl_entry.score

    # Gate 0: min_strength guard — WL breach не проверял strength (DOGE str=18 баг 25.03)
    # DEV-69: отдельный порог для WL breach (45) — ниже мониторинга (75), т.к. касание уровня = контекст
    _min_str_wl = int(bot.config.get("signal_quality.min_strength_wl_breach",
                      bot.config.get("signal_quality.min_strength_register", 75)))
    if score < _min_str_wl:
        logger.info("[WL-BREACH] %s: пропуск — strength=%d < min_strength_wl_breach=%d", symbol, score, _min_str_wl)
        return

    # DEV-41: Rate-limit — не более 3 WL breach входов за 30 минут
    _now = datetime.now()
    _rate_window = 30 * 60  # секунд
    _rate_limit = 3
    while _wl_breach_timestamps and (_now - _wl_breach_timestamps[0]).total_seconds() > _rate_window:
        _wl_breach_timestamps.popleft()
    if len(_wl_breach_timestamps) >= _rate_limit:
        logger.info("[WL-BREACH] %s: пропуск — rate limit (%d входов за 30 мин)", symbol, _rate_limit)
        return

    # Gate 1: режим HIGH_VOL — не входим
    try:
        from core.market_regime import MarketRegimeClassifier
        regime = MarketRegimeClassifier().classify_from_ohlcv(df_entry)
        if regime == "HIGH_VOL":
            logger.info("[WL-BREACH] %s: пропуск — режим HIGH_VOL", symbol)
            return
    except Exception as e:
        logger.debug("[WL-BREACH] %s: ошибка определения режима — %s", symbol, e)
        regime = None

    # Gate 2: cooldown после SL
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol):
        logger.info("[WL-BREACH] %s: пропуск — SL cooldown", symbol)
        return

    # DEV-41 Фикс 1: Gate 3 — DEV-32 regime_direction_block bypass fix
    # WL breach обходил этот guard, теперь применяем явно
    try:
        _rdb = bot.config.get("trading", {}).get("regime_direction_block", {})
        if _rdb.get("enabled", False) and regime:
            _blocked_dir = _rdb.get(regime)  # e.g. TREND_DOWN → "LONG"
            if _blocked_dir and direction == _blocked_dir:
                logger.info("[WL-BREACH] %s: пропуск — DEV-41/DEV-32 %s блокирует %s", symbol, regime, direction)
                return
    except Exception as _e32:
        logger.debug("[WL-BREACH] %s: ошибка DEV-32 gate — %s", symbol, _e32)

    # Gate 4: DEV-58 Weekly Bias Filter (production gate, enabled: false по умолчанию)
    try:
        _wbcfg_58 = (bot.config.get("trading") or {}).get("weekly_bias_filter") or {}
        if _wbcfg_58.get("enabled"):
            _pc_58 = getattr(bot, "pivot_calculator", None)
            if _pc_58 is not None:
                _wp58 = await _pc_58.get_weekly_pivots(symbol, bot.data_collector)
                _wpp58 = float((_wp58 or {}).get("PP") or 0) or None
                if _wpp58 and current_price:
                    _bias58 = "BULLISH" if current_price > _wpp58 else "BEARISH"
                    _dp58 = await _pc_58.get_daily_pivots(symbol, bot.data_collector)
                    _mp58 = await _pc_58.get_monthly_pivots(symbol, bot.data_collector)
                    _dpp58 = float((_dp58 or {}).get("PP") or 0) or None
                    _mpp58 = float((_mp58 or {}).get("PP") or 0) or None
                    _ctx58 = sum([
                        bool(_mpp58 and current_price < _mpp58),
                        bool(_wpp58 and current_price < _wpp58),
                        bool(_dpp58 and current_price < _dpp58),
                    ])
                    _conflict58 = (
                        (direction == "LONG" and _bias58 == "BEARISH") or
                        (direction == "SHORT" and _bias58 == "BULLISH")
                    )
                    _hard_ctx58 = int(_wbcfg_58.get("hard_block_ctx_score", 3))
                    if _conflict58 and _ctx58 >= _hard_ctx58:
                        logger.info(
                            "[WL-BREACH DEV-58] %s: hard_block %s/%s ctx=%d",
                            symbol, direction, _bias58, _ctx58,
                        )
                        return
    except Exception as _e58:
        logger.debug("[WL-BREACH] %s: ошибка DEV-58 gate — %s", symbol, _e58)

    # SL = пробитый пивот ± 0.5% буфер (уровень стал support/resistance)
    sl_buffer_pct = float(bot.config.get("signal_quality.wl_sl_buffer_pct", 0.5)) / 100
    if direction == "LONG":
        sl = pivot_level * (1.0 - sl_buffer_pct)
    else:
        sl = pivot_level * (1.0 + sl_buffer_pct)

    # TP = следующий пивот в направлении ≤5% от entry, через иерархию
    tp = None
    tp_source = "tsl_only"
    pivot_calc = getattr(bot, "pivot_calculator", None)
    if pivot_calc is not None:
        try:
            result = pivot_calc.get_tp_by_hierarchy(
                direction=direction,
                entry_price=current_price,
                symbol=symbol,
                stop_loss=sl,
                min_r=1.5,
            )
            if result:
                tp_candidate, tp_src = result
                max_tp_dist = current_price * 0.05  # 5% от entry
                if abs(tp_candidate - current_price) <= max_tp_dist:
                    tp = tp_candidate
                    tp_source = tp_src
                else:
                    logger.info("[WL-BREACH] %s: TP=%.6f далеко (>5%%) — TSL-only", symbol, tp_candidate)
        except Exception as e:
            logger.debug("[WL-BREACH] %s: ошибка get_tp_by_hierarchy — %s", symbol, e)

    # DEV-41 Фикс 2: fallback ATR-based TP если get_tp_by_hierarchy вернул None
    if tp is None and sl is not None and current_price > 0:
        try:
            from core.indicators import compute_atr as _compute_atr
            _atr = _compute_atr(df_entry, period=14)
            if _atr and _atr > 0:
                _sign = 1.0 if direction == "LONG" else -1.0
                _tp_atr = current_price + _sign * _atr * 2.5
                _risk = abs(current_price - sl)
                _reward = abs(_tp_atr - current_price)
                if _risk > 0 and _reward / _risk >= 1.5:
                    tp = _tp_atr
                    tp_source = "atr_fallback"  # ARCH-58
                    logger.info("[WL-BREACH] %s: ATR fallback TP=%.6f (ATR=%.6f, R:R=%.2f)",
                                symbol, tp, _atr, _reward / _risk)
                else:
                    logger.info("[WL-BREACH] %s: ATR fallback R:R=%.2f < 1.5 — TSL-only", symbol,
                                _reward / _risk if _risk > 0 else 0)
        except Exception as _e_atr:
            logger.debug("[WL-BREACH] %s: ошибка ATR fallback — %s", symbol, _e_atr)

    # DEV-64A: global + regime R:R cap (max_rr из sl_tp, enforce для всех режимов)
    if tp is not None and sl is not None and current_price > 0:
        _risk = abs(current_price - sl)
        _reward = abs(tp - current_price)
        if _risk > 0:
            _rr = _reward / _risk
            _sl_tp_cfg = bot.config.get("trading", {}).get("sl_tp", {})
            try:
                if regime == "RANGE":
                    _max_rr = float(_sl_tp_cfg.get("max_rr_range", 2.5))
                else:
                    _max_rr = float(_sl_tp_cfg.get("max_rr", 3.0))
            except Exception:
                _max_rr = 3.0
            if _rr > _max_rr:
                _sign = 1.0 if direction == "LONG" else -1.0
                tp = current_price + _sign * _risk * _max_rr
                tp_source = f"{tp_source}|capped_rr_{_max_rr}"
                logger.info("[WL-BREACH DEV-64A] %s: R:R=%.2f → cap %.1fx TP=%.6f (regime=%s)",
                            symbol, _rr, _max_rr, tp, regime or "?")

    # Проверка min R:R = 1.5
    if tp is not None and sl and pivot_level > 0:
        risk = abs(current_price - sl)
        reward = abs(tp - current_price)
        if risk > 0 and reward / risk < 1.5:
            logger.info("[WL-BREACH] %s: пропуск — R:R=%.2f < 1.5", symbol, reward / risk)
            return

    # Строим рекомендацию
    _sig = SimpleNamespace(signal_type=SimpleNamespace(value="watch_list_breach"))
    rec = SimpleNamespace(
        symbol=symbol,
        action="BUY" if direction == "LONG" else "SELL",
        entry_price=current_price,
        direction=SimpleNamespace(value=direction),
        stop_loss=sl,
        take_profit=tp,
        tp1_price=None,
        overall_strength=int(score),
        confidence=0.65,
        timestamp=datetime.now(timezone.utc),  # DEV-49
        market_context=None,
        supporting_signals=[_sig],
        conflicting_signals=[],
        sl_source=f"wl_pivot_{wl_entry.pivot_key or 'level'}",
        tp_source=tp_source,
        metadata={"signal_type": "watch_list_breach", "wl_reason": wl_entry.reason},
    )

    # DEV-126: собираем полный extra_features для WL breach — weekly_bias + htf_wt
    _extra_wl: dict = {"wl_pivot_key": wl_entry.pivot_key, "wl_score": score}
    try:
        _pc_wl = getattr(bot, "pivot_calculator", None)
        if _pc_wl is not None:
            _wp_wl = await _pc_wl.get_weekly_pivots(symbol, bot.data_collector)
            _wpp_wl = float((_wp_wl or {}).get("PP") or 0) or None
            if _wpp_wl and current_price:
                _extra_wl["weekly_bias"] = "BULLISH" if current_price > _wpp_wl else "BEARISH"
            else:
                _extra_wl["weekly_bias"] = "UNKNOWN"
        else:
            _extra_wl["weekly_bias"] = "UNKNOWN"
    except Exception:
        _extra_wl["weekly_bias"] = "UNKNOWN"
    try:
        from core.indicators import calculate_wt as _calc_wt_wl
        _df_1h_wl = await bot.data_collector.get_ohlcv(symbol, "1h", limit=30)
        if _df_1h_wl is not None and len(_df_1h_wl) >= 10:
            _df_1h_wl = _calc_wt_wl(_df_1h_wl)  # DEV-126: raw OHLCV не имеет wt1
            if "wt1" in _df_1h_wl.columns:
                _extra_wl["htf_wt1_1h"] = round(float(_df_1h_wl["wt1"].iloc[-1]), 1)
                _extra_wl["htf_wt2_1h"] = round(float(_df_1h_wl["wt2"].iloc[-1]), 1)
    except Exception:
        pass
    # entry-TF WT (df_entry уже прошёл _calc_wt в scan_one)
    try:
        if df_entry is not None and "wt1" in df_entry.columns and len(df_entry) > 0:
            _extra_wl["wt1_value"] = round(float(df_entry["wt1"].iloc[-1]), 1)
            _extra_wl["wt2_value"] = round(float(df_entry["wt2"].iloc[-1]), 1)
            _w1e = _extra_wl["wt1_value"]
            _extra_wl["wt_zone"] = "OS" if _w1e <= -60 else "OB" if _w1e >= 60 else "N"
    except Exception:
        pass

    # Регистрируем сделку (dedup по открытым сделкам — внутри register_trade)
    trade_id = None
    if hasattr(bot, "trade_simulator"):
        try:
            trade_id = await bot.trade_simulator.register_trade_async(
                rec, bot.data_collector,
                extra_features=_extra_wl,
            )
        except Exception as e:
            logger.warning("[WL-BREACH] %s: ошибка register_trade — %s", symbol, e)

    if trade_id is None:
        logger.info("[WL-BREACH] %s: сделка не зарегистрирована (дубль или нет SL/TP)", symbol)
        return

    # DEV-41: фиксируем время успешного входа для rate-limit
    _wl_breach_timestamps.append(datetime.now())

    # VST/LIVE: открываем реальный ордер на бирже
    if hasattr(bot, "order_executor") and hasattr(bot, "position_sizer") and tp is not None:
        try:
            _oe = bot.order_executor
            _deposit = await _oe.get_available_balance()
            _risk_pct = float(bot.config.get("trading.risk_pct", 1.0))
            _leverage = int(bot.config.get("trading.leverage", 5))
            _qty = bot.position_sizer.calc_qty(
                entry_price=current_price, sl_price=sl,
                deposit=_deposit, risk_pct=_risk_pct, leverage=_leverage,
            )
            if _qty > 0:
                _br = await _oe.open_bracket(
                    symbol=symbol, direction=direction,
                    entry_price=current_price, sl=sl, tp1=tp, qty=_qty,
                )
                if _br.success:
                    logger.info("[WL-BREACH][%s] ✅ %s %s qty=%.6f order_id=%s",
                                _br.mode.upper(), symbol, direction, _qty, _br.order_id)
                    # Записываем в live_orders для трекинга
                    if hasattr(bot, "position_manager"):
                        _pos_dir_wl = "LONG" if direction == "LONG" else "SHORT"
                        bot.position_manager.register(
                            symbol=symbol, side=_pos_dir_wl, qty=_qty,
                            sim_trade_id=trade_id,
                            exchange_order_id=_br.order_id,
                        )
                    # Привязываем exchange_order_id — только эти сделки будут синхронизироваться с биржей
                    if _br.order_id and trade_id:
                        bot.trade_simulator.set_exchange_order_id(trade_id, _br.order_id, qty=_qty)
                        # Асинхронно получаем и сохраняем SL orderId для TSL cancel+replace
                        _pos_side_wl = "LONG" if direction == "LONG" else "SHORT"
                        import asyncio as _asyncio_wl
                        from core.exchange.tsl_updater import fetch_and_save_sl_order_id
                        _asyncio_wl.create_task(fetch_and_save_sl_order_id(
                            bot, trade_id, symbol, _pos_side_wl))
                elif _br.error != "position_already_open":
                    logger.warning("[WL-BREACH] OrderExecutor error: %s", _br.error)
        except Exception as _oe_e:
            logger.warning("[WL-BREACH] OrderExecutor exception: %s", _oe_e)

    # TG-алерт
    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    tp_str = f"{tp:.6f}" if tp else "TSL"
    text = (
        f"{dir_emoji} <b>WL BREACH:</b> {symbol.split('/')[0]}\n"
        f"Вход: {current_price:.6f} | SL: {sl:.6f} | TP: {tp_str}\n"
        f"Score: {int(score)} | Pivot: {wl_entry.pivot_key or 'level'} | "
        f"Режим: {regime or '?'}\n"
        f"<i>Сделка #{trade_id} зарегистрирована</i>"
    )
    await _send_wl_alert(bot, symbol, text)
    logger.info("[WL-BREACH] %s %s: сделка #%d entry=%.6f SL=%.6f TP=%s",
                symbol, direction, trade_id, current_price, sl, tp_str)


async def _prefetch_pivots(bot) -> None:
    """Прогревает кеш пивотов для всех пар параллельно.
    Semaphore намеренно маленький — не конкурируем со сканом за ApiEngine.Semaphore(20).
    После прогрева — самодиагностика: отчёт в лог + Telegram."""
    pairs = bot.monitored_pairs
    pfx_sem_size = int(bot.config.get("performance.prefetch_pivots_semaphore_size", 2))
    sem = asyncio.Semaphore(pfx_sem_size)

    # Результаты диагностики
    ok_weekly = []
    fail_weekly = []
    ok_daily = []
    fail_daily = []
    ok_monthly = []
    fail_monthly = []

    async def _fetch_one(sym):
        async with sem:
            try:
                result = await bot.pivot_calculator.get_multi_timeframe_pivots(sym, bot.data_collector)
                if result.get("1W"):
                    ok_weekly.append(sym)
                else:
                    fail_weekly.append(sym)
                if result.get("1D"):
                    ok_daily.append(sym)
                else:
                    fail_daily.append(sym)
                if result.get("1M"):
                    ok_monthly.append(sym)
                else:
                    fail_monthly.append(sym)
            except Exception as e:
                fail_weekly.append(sym)
                fail_daily.append(sym)
                fail_monthly.append(sym)
                logger.debug("Prefetch pivots error %s: %s", sym, e)
            # Микропауза между парами — защита от rate-limit при массовом прогреве
            await asyncio.sleep(0.15)

    logger.info("Прогрев кеша пивотов для %d пар...", len(pairs))
    await asyncio.gather(*[_fetch_one(sym) for sym in pairs])

    # ── Самодиагностика ──
    total = len(pairs)
    w_ok, w_fail = len(ok_weekly), len(fail_weekly)
    d_ok, d_fail = len(ok_daily), len(fail_daily)
    m_ok, m_fail = len(ok_monthly), len(fail_monthly)

    logger.info(
        "Кеш пивотов прогрет: Monthly %d/%d OK, Weekly %d/%d OK, Daily %d/%d OK",
        m_ok, total, w_ok, total, d_ok, total,
    )

    # Отчёт в Telegram админу
    diag_lines = [f"📊 <b>Pivot Diagnostics</b>"]
    diag_lines.append(f"Monthly: {m_ok}/{total} ✅  {m_fail} ❌")
    diag_lines.append(f"Weekly:  {w_ok}/{total} ✅  {w_fail} ❌")
    diag_lines.append(f"Daily:   {d_ok}/{total} ✅  {d_fail} ❌")

    if fail_monthly:
        short = [s.split("/")[0] for s in fail_monthly[:15]]
        diag_lines.append(f"\n⚠️ Без Monthly ({m_fail}):")
        diag_lines.append(", ".join(short))
        if len(fail_monthly) > 15:
            diag_lines.append(f"... и ещё {len(fail_monthly) - 15}")

    if fail_weekly:
        short = [s.split("/")[0] for s in fail_weekly[:15]]
        diag_lines.append(f"\n⚠️ Без Weekly ({w_fail}):")
        diag_lines.append(", ".join(short))
        if len(fail_weekly) > 15:
            diag_lines.append(f"... и ещё {len(fail_weekly) - 15}")

    if not fail_monthly and not fail_weekly and not fail_daily:
        diag_lines.append("\n✅ Все пивоты рассчитаны успешно!")

    diag_text = "\n".join(diag_lines)

    try:
        admin_id = bot.config.get("telegram.admin_id")
        if admin_id:
            await bot.bot.send_message(int(admin_id), diag_text, parse_mode="HTML")
    except Exception as e:
        logger.debug("Pivot diagnostics TG send error: %s", e)


async def scan_all_pairs(bot, check_divergences: bool = True) -> None:
    """Один проход по всем парам: для каждой пары все проверки подряд,
    затем broadcast СНАРУЖИ семафора — analyze_symbol не блокирует OHLCV-слоты."""
    from bot.monitoring import _broadcast_intelligence_alert, _div_passes_filters

    scan_sem_size = int(bot.config.get("performance.scan_semaphore_size", 20))
    sem = asyncio.Semaphore(scan_sem_size)
    cycle_start = _time.monotonic()

    # Лимиты сигналов за один цикл — защита от Telegram flood control
    _confluence_max_per_cycle = int(bot.config.get("analysis.confluence.max_per_cycle", 3))
    _confluence_sent = 0
    _anomaly_max_per_cycle = int(bot.config.get("analysis.anomaly.max_per_cycle", 5))
    _anomaly_sent = 0
    _div_proximity_pct = bot.config.get("analysis.divergence.pivot_proximity_pct", 4.0)
    _etf = get_primary_entry_tf(bot.config)  # Primary entry TF (default "15m")
    _entry_tfs = get_entry_timeframes(bot.config)  # Все entry TF (может быть ["5m", "15m", "1h"])
    _multi_tf = len(_entry_tfs) > 1
    _resolver = getattr(bot, "multi_tf_resolver", None)
    _ohlcv_limit = int(bot.config.get("performance.ohlcv_scan_limit", 160))
    _slow_ohlcv  = float(bot.config.get("performance.ohlcv_slow_threshold_sec", 5.0))
    _slow_div    = float(bot.config.get("performance.divergence_slow_threshold_sec", 3.0))
    _slow_pair   = float(bot.config.get("performance.pair_slow_threshold_sec", 10.0))
    _slow_cycle  = float(bot.config.get("performance.scan_cycle_warning_threshold_sec", 55.0))

    async def scan_one(sym):
        nonlocal _confluence_sent, _anomaly_sent
        signals_to_broadcast = []  # [(sig_type, raw_text, fallback_rec), ...]
        all_scan_signals = []      # SignalData от детекторов — для pre_collected_signals

        async with sem:
            # Этап 8.4.2: единый snapshot_time для всей пары — все данные привязаны к нему
            snapshot_time = datetime.now()
            t_enter = _time.monotonic()
            try:
                # Горячий путь: грузим только TF, которые реально нужны самому scan_loop.
                # 3m/1d оставляем ленивыми — они нужны в analyze_symbol только для пар с сигналом.
                _fetch_plan: list[tuple[str, int]] = []
                _seen_fetches: set[tuple[str, int]] = set()

                def _add_fetch(tf: str, limit: int) -> None:
                    key = (tf, limit)
                    if key not in _seen_fetches:
                        _seen_fetches.add(key)
                        _fetch_plan.append(key)

                for tf in _entry_tfs:
                    _add_fetch(tf, _ohlcv_limit)
                _add_fetch("1h", _ohlcv_limit)
                _add_fetch("4h", 60)

                _fetched = await asyncio.gather(*[
                    bot.data_collector.get_ohlcv(sym, tf, limit=limit)
                    for tf, limit in _fetch_plan
                ])
                _fetched_map = {
                    (tf, limit): df for (tf, limit), df in zip(_fetch_plan, _fetched)
                }
                _entry_dfs = {
                    tf: _fetched_map.get((tf, _ohlcv_limit))
                    for tf in _entry_tfs
                }
                df_1h = _fetched_map.get(("1h", _ohlcv_limit))
                df_4h = _fetched_map.get(("4h", 60))
                df_3m = None
                df_1d = None
                # Primary entry для совместимости (используется в divergence, confluence, etc.)
                _primary = _entry_dfs.get(_etf)
                df_entry = _primary if _primary is not None else next((v for v in _entry_dfs.values() if v is not None), None)

                logger.debug("[scan] %s snapshot=%s tfs=%s", sym, snapshot_time.strftime("%H:%M:%S"),
                             ",".join(_entry_tfs))
                t_ohlcv = _time.monotonic()
                if (t_ohlcv - t_enter) > _slow_ohlcv:
                    logger.warning("[scan] OHLCV медленно %s: %.1fs", sym, t_ohlcv - t_enter)
                if df_entry is None or df_entry.empty:
                    return

                # ARCH-18: pre-compute индикаторы один раз на все основные TF.
                # Детекторы проверяют наличие колонок и пропускают пересчёт.
                from core.indicators import calculate_wt as _calc_wt, calculate_trend as _calc_trend
                from core.config_loader import config as _cfg_scan
                _scan_atr_p = int(_cfg_scan.get("analysis.indicators.trend.atr_period", 43))
                _scan_factor = float(_cfg_scan.get("analysis.indicators.trend.factor", 1.0))
                df_entry = _calc_wt(df_entry)
                df_entry = _calc_trend(df_entry, atr_period=_scan_atr_p, factor=_scan_factor)
                if df_1h is not None and not df_1h.empty:
                    df_1h = _calc_wt(df_1h)
                    df_1h = _calc_trend(df_1h, atr_period=_scan_atr_p, factor=_scan_factor)
                if df_3m is not None and not df_3m.empty:
                    df_3m = _calc_wt(df_3m)
                    df_3m = _calc_trend(df_3m, atr_period=_scan_atr_p, factor=_scan_factor)
                if df_4h is not None and not df_4h.empty:
                    df_4h = _calc_wt(df_4h)
                    df_4h = _calc_trend(df_4h, atr_period=_scan_atr_p, factor=_scan_factor)
                if df_1d is not None and not df_1d.empty:
                    df_1d = _calc_wt(df_1d)
                    df_1d = _calc_trend(df_1d, atr_period=_scan_atr_p, factor=_scan_factor)

                # DEV-108: вычисляем market_regime один раз для всего скана пары
                # Используется в WT/confluence детекторах для dynamic_os в RANGE
                _pair_regime = ""
                try:
                    from core.market_regime import MarketRegimeClassifier
                    _pair_regime = MarketRegimeClassifier().classify_from_dataframes(
                        df_entry, df_1h
                    ) or ""
                except Exception:
                    pass

                # Проверка качества OHLCV: глубина, свежесть, NaN-пробелы
                ok, reason = check_ohlcv_quality(
                    df_entry,
                    timeframe=_etf,
                    min_bars=MIN_BARS["divergence"],  # 160 — самый строгий детектор
                    symbol=sym,
                )
                if not ok:
                    logger.info("[scan] Пропускаем %s: %s", sym, reason)
                    return

                # DEV-22: проверяем пробой/разворот для пар в WATCH LIST
                _wl = getattr(bot, "signal_watch_list", None)
                if _wl is not None and _wl.has(sym) and len(df_entry) > 0:
                    _cur_price = float(df_entry["close"].iloc[-1])
                    _breach_pct = float(bot.config.get("signal_quality.watch_list_breach_pct", 1.0))
                    if _wl.check_breach(sym, _cur_price, breach_pct=_breach_pct):
                        # Пробой ПРОТИВ направления → идея провалилась, удаляем
                        _wl.remove(sym, f"пробой pivot price={_cur_price:.4f}")
                        asyncio.create_task(
                            _send_wl_alert(bot, sym, f"🔴 <b>WL:</b> пробой уровня для {sym.split('/')[0]} — идея отменена")
                        )
                    elif _wl.check_breach_entry_direction(sym, _cur_price, breach_pct=_breach_pct):
                        # DEV-WL-BREACH: пробой В направлении → открываем сделку
                        _wl_entry = _wl.get(sym)  # сохраняем до удаления
                        _wl.remove(sym, f"breach_entry price={_cur_price:.6f}")
                        asyncio.create_task(
                            _handle_wl_breach_entry(bot, sym, _wl_entry, _cur_price, df_entry)
                        )

                # Обновляем price/volume history из уже загруженных данных
                # (заменяет fetch_candles: нет лишних API-вызовов)
                if len(df_entry) >= 2:
                    dc = bot.data_collector
                    prev_c = df_entry["close"].iloc[-2] or 0.0
                    last_c = df_entry["close"].iloc[-1] or 0.0
                    pct = ((last_c - prev_c) / prev_c * 100) if prev_c else 0.0
                    dc.price_history.setdefault(sym, deque(maxlen=dc.history_size)).append(pct)
                    dc.volume_history.setdefault(sym, deque(maxlen=dc.history_size)).append(
                        float(df_entry["volume"].iloc[-1] or 0.0)
                    )

                # === Multi-TF signal collection ===
                # Для каждого entry TF собираем сигналы (anomaly, WT, MTF)
                _scan_tfs = _entry_tfs if _multi_tf else [_etf]
                for _scan_tf in _scan_tfs:
                    _df_tf = _entry_dfs.get(_scan_tf, df_entry)
                    if _df_tf is None or _df_tf.empty:
                        continue

                    # 1. Anomalies (только primary TF — аномалии не зависят от entry)
                    if _scan_tf == _etf:
                        for sig in await check_anomaly_signals(sym, _df_tf):
                            info = sig.data or {}
                            bot.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                            bot.signal_counters["anomaly"] += 1
                            bot.signal_counters["total"] += 1
                            all_scan_signals.append(sig)
                            if _anomaly_sent < _anomaly_max_per_cycle:
                                signals_to_broadcast.append(("anomaly", anomaly_message(sym, info), None))
                                _anomaly_sent += 1
                            else:
                                logger.debug("[anomaly] %s: лимит %d/цикл достигнут, пропуск TG",
                                             sym, _anomaly_max_per_cycle)
                            # ARCH-70: EventBus — anomaly запускает Full CALL
                            _eb = getattr(bot, "event_bus", None)
                            if _eb is not None:
                                asyncio.create_task(_eb.publish(sym, "anomaly_volume", priority=4))

                    # 1a. DEV-81: FUNDING_EXTREME (shadow mode — только лог, не в TG)
                    if _scan_tf == _etf:
                        try:
                            from core.signals.funding_detector import detect_funding_extreme
                            _fr = await bot.data_collector.get_funding_rate(sym)
                            if _fr is not None:
                                _funding_sig = detect_funding_extreme(sym, _df_tf, _fr, bot.config)
                                if _funding_sig is not None:
                                    all_scan_signals.append(_funding_sig)
                                    bot.signal_counters["funding_extreme"] = (
                                        bot.signal_counters.get("funding_extreme", 0) + 1
                                    )
                                    bot.signal_counters["total"] += 1
                                    # shadow mode: не отправляем в TG, только лог
                                    logger.info(
                                        "[DEV-81 shadow] %s funding=%.6f dir=%s str=%d",
                                        sym, _fr, _funding_sig.direction.value, _funding_sig.strength,
                                    )
                                    # ARCH-70: EventBus — funding_extreme запускает Full CALL
                                    _eb = getattr(bot, "event_bus", None)
                                    if _eb is not None:
                                        asyncio.create_task(_eb.publish(sym, "funding_extreme", priority=2))
                        except Exception as _fe:
                            logger.debug("[FUNDING] %s error: %s", sym, _fe)

                    # 1b. DEV-82 v2: LIQUIDITY_SWEEP — 1h TF (значимые флипы, period=10 свинги)
                    # Изменено: 15m→1h, period=5→10, min_bars=30→50. Запускаем один раз (не в loop по TF).
                    if _scan_tf == _etf:
                        try:
                            from core.signals.liquidity_sweep_detector import detect_liquidity_sweep
                            _pc = getattr(getattr(bot, "pivot_calculator", None), "pivot_cache", {})
                            _sweep_sig = detect_liquidity_sweep(sym, df_1h, _pc, bot.config)
                            if _sweep_sig is not None:
                                all_scan_signals.append(_sweep_sig)
                                bot.signal_counters["liquidity_sweep"] = (
                                    bot.signal_counters.get("liquidity_sweep", 0) + 1
                                )
                                bot.signal_counters["total"] += 1
                                signals_to_broadcast.append(
                                    ("liquidity_sweep", _sweep_message(sym, _sweep_sig), None)
                                )
                                # ARCH-70: EventBus — liquidity_sweep запускает Full CALL (prio=1)
                                _eb = getattr(bot, "event_bus", None)
                                if _eb is not None:
                                    asyncio.create_task(_eb.publish(sym, "liquidity_sweep", priority=1))
                        except Exception as _se:
                            logger.debug("[LIQSWEEP] %s error: %s", sym, _se)

                    # 2. WT
                    _pivot_calc = getattr(bot, "pivot_calculator", None)
                    for sig in await _check_wt_signals(sym, _df_tf, df_1h, market_regime=_pair_regime):
                        info = sig.data or {}
                        if _multi_tf:
                            sig.timeframe = _scan_tf  # тегируем ТФ
                        # ARCH-23: апгрейд wt_signal → confluence если цена у пивота (±1%)
                        if _pivot_calc is not None and not _df_tf.empty:
                            _price = float(_df_tf["close"].iloc[-1])
                            _near = _pivot_calc.find_near_pivot(_price, sym)
                            if _near:
                                _lvl, _src = _near
                                sig.signal_type = SignalType.CONFLUENCE
                                sig.strength = min(95, sig.strength + 20)
                                sig.data["near_pivot"] = True
                                sig.data["pivot_level"] = _lvl
                                sig.data["pivot_source"] = _src
                                info = sig.data  # обновляем info после апгрейда
                                logger.info(
                                    "ARCH-23 [%s]: WT → CONFLUENCE (пивот %s=%.6f, dist=%.2f%%)",
                                    sym, _src, _lvl, abs(_price - _lvl) / _price * 100,
                                )
                        logger.info("WT сигнал обнаружен для %s [%s]", sym, _scan_tf)
                        bot.signal_counters["wt_signal"] += 1
                        bot.signal_counters["total"] += 1
                        signals_to_broadcast.append(("wt_signal", wt_message(sym, info), None))
                        all_scan_signals.append(sig)

                # 3. Confluence: State Machine (ARCH-03) или Lookback Scanner (fallback)
                pivot_cache = getattr(getattr(bot, "pivot_calculator", None), "pivot_cache", {})
                _use_sm = bool(bot.config.get("analysis.confluence.use_state_machine", True))
                _confluence_sigs = []

                # DEV-127: SMC контекст для SMC None gate (shadow) в wt_15m_reversal_scanner
                _smc_ctx_scan = None
                try:
                    from core.smc import analyze_smc as _analyze_smc
                    if df_entry is not None and len(df_entry) >= 30:
                        _smc_ctx_scan = _analyze_smc(df_entry)
                except Exception:
                    pass

                if _use_sm and hasattr(bot, "confluence_sm"):
                    try:
                        _confluence_sigs = bot.confluence_sm.update(
                            sym, df_entry, df_1h, pivot_cache, cfg=bot.config
                        )
                    except Exception as _sm_e:
                        logger.debug("[confluence_sm] %s error: %s", sym, _sm_e)
                        _confluence_sigs = scan_wt_15m_reversal(
                            sym, df_entry, df_1h, pivot_cache, cfg=bot.config, df_4h=df_4h,
                            market_regime=_pair_regime, smc_context=_smc_ctx_scan,
                        )
                else:
                    _confluence_sigs = scan_wt_15m_reversal(
                        sym, df_entry, df_1h, pivot_cache, cfg=bot.config, df_4h=df_4h,
                        market_regime=_pair_regime, smc_context=_smc_ctx_scan,
                    )

                for sig in _confluence_sigs:
                    bot.signal_counters["confluence"] = bot.signal_counters.get("confluence", 0) + 1
                    bot.signal_counters["total"] += 1
                    all_scan_signals.append(sig)
                    if _confluence_sent < _confluence_max_per_cycle:
                        signals_to_broadcast.append(("confluence", _confluence_message(sym, sig), None))
                        _confluence_sent += 1
                    else:
                        logger.debug("[confluence] %s: лимит %d/цикл достигнут, пропуск TG",
                                     sym, _confluence_max_per_cycle)
                    # ARCH-70: EventBus — wt_confluence запускает Full CALL
                    _eb = getattr(bot, "event_bus", None)
                    if _eb is not None:
                        asyncio.create_task(_eb.publish(sym, "wt_confluence", priority=3))
                    break  # Один confluence Full CALL на пару за цикл достаточно

                # 5. WT-B Signal (1h): адаптивный OS/OB + дивергенция, WR=85%
                # df_1h уже в кеше — не фетчим повторно
                if df_1h is not None and not df_1h.empty:
                    _wt_b_sigs = await _check_wt_b_signals(sym, df_1h)
                    for sig in _wt_b_sigs:
                        bot.signal_counters["wt_b"] = bot.signal_counters.get("wt_b", 0) + 1
                        bot.signal_counters["total"] += 1
                        all_scan_signals.append(sig)
                        signals_to_broadcast.append(("wt_b", _wt_b_message(sym, sig), None))
                        logger.info("[wt_b] %s: %s str=%d", sym, sig.direction.value, sig.strength)

                # 6. MTF alerts — вынесены в check_mtf_alerts (каждые 5 мин),
                # т.к. collect_mtf_data фетчит 7 TF (5m, 45m, 4h, 1d не в кеше)

                # 7. Trend following — вынесен в check_trend_signals (каждые 5 мин),
                # т.к. check_trend_following_signal фетчит 4h+5m (не в кеше)

                # 8. Divergences: каждые 3 цикла (180 сек — медленный сигнал)
                t_before_div = _time.monotonic()
                div_found = False
                if check_divergences:
                    pivot_calc = getattr(bot, "pivot_calculator", None)
                    # Этап 8.4.5: режим пары — скрытые дивергенции отклоняем в RANGE/HIGH_VOL
                    # _pair_regime уже вычислен выше (DEV-108, один раз на пару)
                    try:
                        has_mtf, mtf_info = await bot.divergence_detector.detect_mtf_divergence(
                            sym, bot.data_collector
                        )
                        if has_mtf:
                            passed, reason = _div_passes_filters(
                                mtf_info, df_entry, pivot_calc, sym, _div_proximity_pct,
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
                                    timestamp=datetime.now(timezone.utc), data=dict(mtf_info, timeframe="1h"), timeframe="1h",  # DEV-49
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
                        for tf in (_etf, "1h"):
                            try:
                                has_div, div_info = await bot.divergence_detector.detect_divergence(
                                    sym, bot.data_collector, timeframe=tf
                                )
                                if has_div:
                                    passed, reason = _div_passes_filters(
                                        div_info, df_entry, pivot_calc, sym, _div_proximity_pct,
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
                                            timestamp=datetime.now(timezone.utc), data=div_info, timeframe=tf,  # DEV-49
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

        # === Multi-TF Resolver (ARCH-13) ===
        # В multi-TF режиме фильтруем конфликтные/дублирующие сигналы через Resolver.
        # Передаём MTF Bias для разрешения неопределённостей при равном TF приоритете.
        if _multi_tf and _resolver and all_scan_signals:
            # Получаем MTF Bias из уже имеющихся сигналов (MTF_BIAS генерируется в analyze_symbol,
            # но мы можем быстро получить direction из старших TF snapshot)
            try:
                from core.mtf_interpreter import analyze_context
                from core.mtf_checker import collect_mtf_data
                _snapshot = await collect_mtf_data(sym, bot.data_collector)
                if _snapshot:
                    _cur_price = float(df_entry['close'].iloc[-1]) if df_entry is not None and len(df_entry) > 0 else 0
                    _wp = getattr(bot.pivot_calculator, "pivot_cache", {}).get(sym, {}).get("1W", {})
                    _ctx = analyze_context(_snapshot, _cur_price, _wp, regime=None)
                    if _ctx and _ctx.direction_bias:
                        _bias_dir = getattr(_ctx.direction_bias, "value", str(_ctx.direction_bias))
                        _resolver.set_mtf_bias(sym, _bias_dir, _ctx.aligned_pct)
            except Exception:
                pass  # MTF Bias — бонус, не блокирует работу

            from core.multi_tf_resolver import TFSignal
            for sig in all_scan_signals:
                _dir = getattr(sig.direction, "value", str(sig.direction)) if sig.direction else ""
                if _dir in ("LONG", "SHORT"):
                    _resolver.add_signal(TFSignal(
                        symbol=sym,
                        timeframe=getattr(sig, "timeframe", _etf) or _etf,
                        direction=_dir,
                        signal_type=sig.signal_type.value if hasattr(sig.signal_type, "value") else str(sig.signal_type),
                        strength=getattr(sig, "strength", 50),
                    ))
            decision = _resolver.resolve_and_clear(sym)
            if decision.action == "REJECT":
                logger.info("[%s] MultiTF Resolver: REJECT — %s", sym, decision.reason)
                signals_to_broadcast = []  # Блокируем все broadcast
                all_scan_signals = []
            elif decision.action == "UPGRADE":
                logger.info("[%s] MultiTF Resolver: UPGRADE — %s", sym, decision.reason)
            elif decision.action == "SPLIT":
                # ARCH-15: SPLIT → broadcast ОБА: тренд (SWING) + отскок (SCALP)
                logger.info("[%s] MultiTF Resolver: SPLIT — %s", sym, decision.reason)
                # Помечаем bounce_signal для регистрации с trade_mode=scalp
                if decision.bounce_signal:
                    decision.bounce_signal._trade_mode = "scalp"
            # ACCEPT — проходит как есть

        # СНАРУЖИ семафора: broadcast как fire-and-forget задачи
        # (analyze_symbol может занимать 30-60 сек — не блокируем asyncio.gather)
        # pre_signals передаём только в первый broadcast — analyze_symbol закеширует результат
        pre = all_scan_signals if all_scan_signals else None
        # Передаём все уже загруженные df — analyze_symbol использует их напрямую (нет повторных fetch)
        if signals_to_broadcast:
            # Ленивая догрузка: дорогие 3m/1d нужны только для дальнейшего intelligence-анализа.
            if df_3m is None:
                df_3m = await bot.data_collector.get_ohlcv(sym, "3m", limit=100)
            if df_1d is None:
                df_1d = await bot.data_collector.get_ohlcv(sym, "1d", limit=60)

        _pre_dfs = {
            _etf: df_entry,
            "1h": df_1h,
            "3m": df_3m,
            "4h": df_4h,
            "1d": df_1d,
        }
        # DEV-118: выбираем ОДИН лучший сигнал на пару за цикл.
        # Все сигналы остаются в pre_signals как контекст для analyze_symbol.
        # Это устраняет дублирование analyze_symbol (~27+19 сек CPU зря на DYDX).
        _SIGNAL_PRIORITY = {
            "confluence":      100,
            "wt_b":             90,
            "wt_signal":        80,
            "liquidity_sweep":  70,
            "anomaly":          50,
        }
        if signals_to_broadcast:
            best = max(signals_to_broadcast, key=lambda x: _SIGNAL_PRIORITY.get(x[0], 0))
            if len(signals_to_broadcast) > 1:
                skipped = [s[0] for s in signals_to_broadcast if s is not best]
                logger.info("[%s] DEV-118: best=%s пропущены=%s (один analyze_symbol)", sym, best[0], skipped)
            sig_type, raw_text, fallback_rec = best
            asyncio.create_task(
                _broadcast_intelligence_alert(bot, sym, raw_text, sig_type,
                                             fallback_rec=fallback_rec, pre_signals=pre,
                                             pre_fetched_dfs=_pre_dfs)
            )

    pairs = list(bot.monitored_pairs)
    random.shuffle(pairs)  # равный шанс для всех пар, убирает алфавитный bias у confluence лимита
    stats = bot.data_collector._engine.cache_stats()
    logger.info("Скан: %d пар | кеш=%d CB=%s", len(pairs), stats["cache_size"], stats["cb_state"])
    await asyncio.gather(*[scan_one(sym) for sym in pairs])
    elapsed = _time.monotonic() - cycle_start
    logger.info("Цикл сканирования завершён: %.1f сек / %d пар", elapsed, len(pairs))
    if elapsed > _slow_cycle:
        logger.warning("⚠️ Цикл превысил %.0f сек — рассмотреть увеличение Semaphore или sleep", _slow_cycle)


_btc_macro_prev_close: float | None = None  # последняя известная close BTC/15m


async def _check_btc_macro_shock(bot) -> None:
    """
    ARCH-70: btc_macro_shock — публикует в EventBus если BTC/USDT 15m свеча >2.5%.
    Вызывается в начале каждого цикла monitor_market.
    Публикует для ВСЕХ мониторируемых пар (BTC shock = рыночный стресс).
    """
    global _btc_macro_prev_close
    _eb = getattr(bot, "event_bus", None)
    if _eb is None:
        return
    threshold_pct = float(bot.config.get("event_bus.btc_macro_shock_pct", 2.5))
    try:
        ohlcv = await bot.data_collector.get_ohlcv("BTC/USDT:USDT", "15m", limit=3)
        if ohlcv is None or ohlcv.empty or len(ohlcv) < 2:
            return
        last_row  = ohlcv.iloc[-1]
        prev_row  = ohlcv.iloc[-2]
        last_open  = float(prev_row["close"])    # открытие последней свечи ≈ закрытие предыдущей
        last_close = float(last_row["close"])
        if last_open <= 0:
            return
        move_pct = abs(last_close - last_open) / last_open * 100

        # Дедупликация: публикуем только если это новая свеча (close изменился)
        if _btc_macro_prev_close is not None and abs(last_close - _btc_macro_prev_close) < 0.00001:
            return  # та же свеча — пропускаем
        _btc_macro_prev_close = last_close

        if move_pct >= threshold_pct:
            direction = "up" if last_close > last_open else "down"
            logger.info(
                "[ARCH-70] BTC macro shock: %.2f%% %s → publish btc_macro для всех пар",
                move_pct, direction,
            )
            # Публикуем для всех мониторируемых пар (они реагируют на BTC)
            watchlist = list(getattr(bot, "monitored_pairs", None) or [])
            published = 0
            for sym in watchlist[:30]:  # лимит: не бомбардировать очередь
                ok = await _eb.publish(
                    sym, "btc_macro", priority=4,
                    data={"btc_move_pct": round(move_pct, 2), "direction": direction},
                )
                if ok:
                    published += 1
            logger.info("[ARCH-70] btc_macro_shock опубликован для %d пар", published)
    except Exception as e:
        logger.debug("[ARCH-70] _check_btc_macro_shock error: %s", e)


async def monitor_market(bot) -> None:
    """Главный цикл мониторинга: запускает скан каждые N сек + фоновые задачи."""
    from bot.monitoring import (
        check_mtf_alerts,
        check_trend_signals,
        check_pivot_reversals,
        check_cascade_divergences,
        check_future_pivot_alerts,
    )
    try:
        _last_pivot_day = datetime.utcnow().date()  # уже прогрет в start_monitoring
        _pivot_cycle = 0
        _cascade_4h_cycle = 0
        _div_cycle = 0
        while bot.is_monitoring:
            # Читаем цикловые интервалы из конфига (hot-reload)
            # DEV-103: пропустить цикл если биржа DOWN
            if getattr(bot, "exchange_health", "HEALTHY") == "DOWN":
                logger.warning("[scan] биржа DOWN — пропуск цикла скана")
                await asyncio.sleep(60)
                continue

            _div_n      = int(bot.config.get("monitoring.check_intervals.divergences_every_n_cycles", 3))
            _bg_n       = int(bot.config.get("monitoring.check_intervals.background_every_n_cycles", 5))
            _cascade_n  = int(bot.config.get("monitoring.check_intervals.cascade_div_every_n_cycles", 60))

            # Фоновый пересчёт пивотов при смене дня/недели/месяца
            today = datetime.utcnow().date()
            if _last_pivot_day != today:
                _last_pivot_day = today
                asyncio.create_task(_prefetch_pivots(bot))
                logger.info("Новый день (%s) — фоновый пересчёт пивотов запущен параллельно со сканером", today)

            # ARCH-70: btc_macro_shock — проверяем BTC 15m каждый цикл
            asyncio.create_task(_check_btc_macro_shock(bot))

            _div_cycle += 1
            _check_div = (_div_cycle % _div_n == 0)
            await scan_all_pairs(bot, check_divergences=_check_div)

            # Тяжёлые проверки (некешируемые TF) — раз в N циклов в фоне
            _pivot_cycle += 1
            if _pivot_cycle >= _bg_n:
                _pivot_cycle = 0
                asyncio.create_task(check_mtf_alerts(bot))         # 7 TF включая 5m, 45m, 4h, 1d
                asyncio.create_task(check_trend_signals(bot))      # 4h + 5m
                asyncio.create_task(check_pivot_reversals(bot))    # 1m + 5m
                asyncio.create_task(check_future_pivot_alerts(bot))  # DEV-11: future pivots pre-alert

            # MTF-дивергенция 4h→1h — раз в N циклов (4h свеча обновляется медленно)
            _cascade_4h_cycle += 1
            if _cascade_4h_cycle >= _cascade_n:
                _cascade_4h_cycle = 0
                asyncio.create_task(check_cascade_divergences(bot, "4h", "1h"))

            # DEV-22: очищаем истёкшие WL-записи каждый цикл
            _wl = getattr(bot, "signal_watch_list", None)
            if _wl is not None:
                _wl.cleanup_expired()

            await asyncio.sleep(bot.config.get("analysis.check_interval", 60))
    except asyncio.CancelledError:
        logger.info("Мониторинг остановлен")
        raise
    except Exception:
        logger.exception("Ошибка в monitor_market")
