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

from core.infra.entry_config import get_primary_entry_tf, get_entry_timeframes
from core.ui.message_builder import (
    anomaly_message, wt_message, wt_b_message as _wt_b_message,
    funding_extreme_message as _funding_message,
    liquidity_sweep_message as _sweep_message,
)
from core.indicators.divergence_detector import divergence_message, mtf_divergence_message
from core.signals.signal_checkers import (
    check_anomaly_signals,
    check_wt_signals as _check_wt_signals,
    check_wt_b_signals as _check_wt_b_signals,
)
from core.signals.signal_models import SignalData, SignalType, SignalDirection
from core.signals.wt_15m_reversal_scanner import scan_wt_15m_reversal, reversal_message as _confluence_message
from core.infra.data_quality import check_ohlcv_quality, MIN_BARS

logger = logging.getLogger(__name__)

# DEV-41: rate-limit для WL breach — не более 3 входов за 30 минут
_wl_breach_timestamps: deque = deque()


def _publish_and_confirm(
    bot, sym: str, event_name: str, *, priority: int, data=None,
    conf_source: str, side: str, tf: str = "", confidence: float = 1.0,
    evidence=None,
) -> None:
    """DEV-200: публикует событие в EventBus И регистрирует Confirmation в агрегаторе.

    Co-located helper (вердикт роя 01.06, исправленный Вариант B): единый mapping
    event→confirmation рядом с существующим publish(), БЕЗ bus-subscriber
    (`bot.event_bus` — приоритетная очередь без subscribe(), не pub/sub).

    Phase 1 = observation-only: confirmation попадает в буфер агрегатора для
    `observe()`/shadow, но gate `aggregate()` (требует trigger) НЕ трогаем.
    Если source отсутствует в registry (weight=0) — только публикуем событие.
    """
    _eb = getattr(bot, "event_bus", None)
    if _eb is not None:
        asyncio.create_task(_eb.publish(sym, event_name, priority=priority, data=data))

    _ca = getattr(bot, "confirmation_aggregator", None)
    if _ca is None or side not in ("LONG", "SHORT") or not conf_source:
        return
    try:
        from core.confirmations.models import Confirmation as _Conf
        from core.confirmations.registry import get_weight as _gw
        _w = _gw(conf_source, side)
        if _w > 0:
            _ca.on_confirmation(_Conf(
                source=conf_source, symbol=sym, side=side,
                weight=_w, confidence=confidence,
                evidence=evidence or {}, tf=tf,
            ))
    except Exception as _e:
        logger.debug("[DEV-200 confirm] %s %s: %s", sym, conf_source, _e)


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
        from core.indicators.market_regime import MarketRegimeClassifier
        regime = MarketRegimeClassifier().classify_from_ohlcv(df_entry)
        if regime == "HIGH_VOL":
            logger.info("[WL-BREACH] %s: пропуск — режим HIGH_VOL", symbol)
            return
    except Exception as e:
        logger.debug("[WL-BREACH] %s: ошибка определения режима — %s", symbol, e)
        regime = None

    # Gate 2: cooldown после SL (per-signal_type: wl_breach может игнорировать SL от других стратегий)
    if hasattr(bot, "trade_simulator") and _is_in_sl_cooldown(bot, symbol, "watch_list_breach"):
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

    # Gate 5: ARCH-78 BTC Market Gate — блок SHORT при BTC BULL
    try:
        _btc_gate_wl = (bot.config.get("trading") or {}).get("btc_market_gate") or {}
        if _btc_gate_wl.get("enabled") and not _btc_gate_wl.get("shadow_mode"):
            _btc_prov_wl = getattr(bot, "btc_regime_provider", None)
            if _btc_prov_wl is not None:
                _btc_mode_wl = _btc_prov_wl.get_btc_mode()
                if (
                    _btc_mode_wl == "BULL"
                    and direction == "SHORT"
                    and _btc_gate_wl.get("block_short_in_uptrend", False)
                ):
                    _ct_min_wl = int(_btc_gate_wl.get("counter_trend_min_strength", 75))
                    if score < _ct_min_wl:
                        logger.info(
                            "[WL-BREACH ARCH-78] %s: пропуск — SHORT при BTC BULL, "
                            "strength=%d < %d",
                            symbol, score, _ct_min_wl,
                        )
                        return
    except Exception as _e_btcwl:
        logger.debug("[WL-BREACH] %s: ошибка ARCH-78 gate — %s", symbol, _e_btcwl)

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
            from core.indicators.indicators import compute_atr as _compute_atr
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
        from core.indicators.indicators import calculate_wt as _calc_wt_wl
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

    # DEV-202: confirmations из агрегатора
    _wl_conf_agg = getattr(bot, "confirmation_aggregator", None)
    if _wl_conf_agg is not None:
        try:
            _wl_side = rec.direction.value if hasattr(rec.direction, 'value') else str(rec.direction)
            _wl_side = 'LONG' if 'LONG' in _wl_side.upper() else 'SHORT'
            _wl_res = _wl_conf_agg.aggregate(rec.symbol, _wl_side)
            _extra_wl['confirmations'] = _wl_res.get('confirmations', [])
            _extra_wl['signal_mode'] = _wl_res.get('signal_mode', 'unknown')
        except Exception:
            _extra_wl['confirmations'] = []

    # tsl_only: tp=None → fallback TP = entry ± 15 * sl_dist (safety valve, TSL закроет раньше)
    # Делаем ДО регистрации, чтобы router/trade_simulator получили валидный TP.
    if tp is None and current_price and sl:
        _sl_dist_wl = abs(current_price - sl)
        if direction == "LONG":
            tp = current_price + 15 * _sl_dist_wl
        else:
            tp = current_price - 15 * _sl_dist_wl
        try:
            rec.take_profit = tp
        except Exception:
            pass
        logger.info("[WL-BREACH] %s tsl_only → fallback TP=%.6f (15R safety)", symbol, tp)

    # Этап 1.В (16.05.2026): WL breach через TradeRouter (source='wl_breach')
    trade_id = None
    if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
        try:
            _sr_result = await bot.trade_router.submit(
                rec, source="wl_breach", extra_features=_extra_wl,
            )
            trade_id = _sr_result.trade_id
            if trade_id:
                logger.info(
                    "[WL-BREACH] router #%d %s %s str=%d->%d soft=%d exch=%s",
                    trade_id, symbol, direction, int(score), _sr_result.final_strength,
                    len(_sr_result.soft_penalties), _sr_result.exchange_order_id or "none",
                )
                _wl_breach_timestamps.append(datetime.now())  # DEV-41 rate-limit
            else:
                _hd = ",".join(g for g, _ in _sr_result.hard_drops) or "none"
                logger.info("[WL-BREACH] router dropped %s %s: %s", symbol, direction, _hd)
                return
        except Exception as e:
            logger.warning("[WL-BREACH] %s: ошибка router.submit — %s", symbol, e)
            return
    else:
        # Старый путь (signal_router.enabled=false)
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
                        logger.info("[WL-BREACH][%s] %s %s qty=%.6f order_id=%s",
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
                            _pos_side_wl = "LONG" if direction == "LONG" else "SHORT"
                            if _br.tp_order_id:
                                bot.trade_simulator.set_exchange_tp_order_id(trade_id, _br.tp_order_id)
                            else:
                                import asyncio as _asyncio_wl
                                from core.exchange.tsl_updater import fetch_and_save_tp_order_id
                                _asyncio_wl.create_task(fetch_and_save_tp_order_id(
                                    bot, trade_id, symbol, _pos_side_wl))
                            if _br.sl_order_id:
                                bot.trade_simulator.set_exchange_sl_order_id(trade_id, _br.sl_order_id)
                            else:
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


def _select_optimal_sl_long(
    entry: float,
    df: "pd.DataFrame",
    trendline: "Optional[float]",
    live_mode: bool = False,
) -> "tuple[float, str]":
    """Выбирает оптимальный SL для ATR change LONG из нескольких кандидатов.

    Кандидаты:
      1. trendup (supertrend линия — согласована с сигналом)
      2. swing_low(20) — структурный минимум последних 20 баров
      3. entry - 2×ATR(14) — быстрый ATR-based уровень

    Фильтр: 0.3% ≤ sl_dist ≤ 10% от entry.
    Выбор: ближайший к цене (tight SL = лучшее R).

    live_mode=True добавляет 0.15% буфер ниже выбранного уровня,
    чтобы компенсировать TSL-касание внутри свечи (vs симуляция = close).
    """
    candidates: list[tuple[float, str]] = []

    # 1. trendup — supertrend линия
    if trendline and 0.0 < trendline < entry:
        candidates.append((trendline, "atr_trendline"))

    # 2. swing_low за последние 20 баров
    try:
        if df is not None and len(df) >= 20 and "low" in df.columns:
            swing_low = float(df["low"].iloc[-20:].min())
            if 0.0 < swing_low < entry:
                candidates.append((swing_low, "swing_low_20"))
    except Exception:
        pass

    # 3. entry - 2×ATR(14) быстрый
    try:
        if df is not None and len(df) >= 15 and "high" in df.columns and "low" in df.columns:
            hl = df["high"] - df["low"]
            atr14 = float(hl.rolling(14).mean().iloc[-1])
            sl_atr = entry - 2.0 * atr14
            if 0.0 < sl_atr < entry:
                candidates.append((sl_atr, "atr14_2x"))
    except Exception:
        pass

    # Фильтр: 0.3% ≤ dist ≤ 10%
    valid: list[tuple[float, str, float]] = []
    rejected: list[tuple[str, float, str]] = []
    for sl_price, src in candidates:
        dist_pct = (entry - sl_price) / entry
        if 0.003 <= dist_pct <= 0.10:
            valid.append((sl_price, src, dist_pct))
        else:
            reason = "dist<0.3%" if dist_pct < 0.003 else "dist>10%"
            rejected.append((src, dist_pct * 100, reason))

    if not valid:
        # fallback — trendup если есть, иначе 5%
        if trendline and 0.0 < trendline < entry:
            final_sl, final_src = trendline, "atr_trendline_fallback"
        else:
            final_sl, final_src = entry * 0.95, "fixed_5pct_fallback"
        if rejected:
            logger.info("[SL_SELECT LONG] entry=%.6f fallback=%s — все кандидаты отброшены: %s",
                        entry, final_src,
                        ", ".join(f"{s}={d:.2f}% ({r})" for s, d, r in rejected))
    else:
        # ближайший к цене (минимум dist_pct)
        valid.sort(key=lambda x: x[2])
        final_sl, final_src, _ = valid[0]
        if rejected:
            logger.info("[SL_SELECT LONG] entry=%.6f выбран=%s dist=%.2f%% | отброшены: %s",
                        entry, final_src, valid[0][2] * 100,
                        ", ".join(f"{s}={d:.2f}% ({r})" for s, d, r in rejected))

    # live_mode: буфер 0.15% ниже уровня (TSL срабатывает при касании, не при close)
    if live_mode:
        final_sl = final_sl * (1.0 - 0.0015)
        final_src += "_buf"

    return final_sl, final_src


def _select_optimal_sl_short(
    entry: float,
    df: "pd.DataFrame",
    trendline: "Optional[float]",
    live_mode: bool = False,
) -> "tuple[float, str]":
    """Зеркало _select_optimal_sl_long для SHORT (DEV-209).

    Кандидаты SL над ценой:
      1. trenddown (supertrend линия — согласована с сигналом)
      2. swing_high(20)
      3. entry + 2×ATR(14)
    Фильтр 0.3-10% от entry. Tight SL = лучше R.
    """
    candidates: list[tuple[float, str]] = []

    if trendline and trendline > entry > 0.0:
        candidates.append((trendline, "atr_trendline"))

    try:
        if df is not None and len(df) >= 20 and "high" in df.columns:
            swing_high = float(df["high"].iloc[-20:].max())
            if swing_high > entry:
                candidates.append((swing_high, "swing_high_20"))
    except Exception:
        pass

    try:
        if df is not None and len(df) >= 15 and "high" in df.columns and "low" in df.columns:
            hl = df["high"] - df["low"]
            atr14 = float(hl.rolling(14).mean().iloc[-1])
            sl_atr = entry + 2.0 * atr14
            if sl_atr > entry:
                candidates.append((sl_atr, "atr14_2x"))
    except Exception:
        pass

    valid: list[tuple[float, str, float]] = []
    rejected: list[tuple[str, float, str]] = []
    for sl_price, src in candidates:
        dist_pct = (sl_price - entry) / entry
        if 0.003 <= dist_pct <= 0.10:
            valid.append((sl_price, src, dist_pct))
        else:
            reason = "dist<0.3%" if dist_pct < 0.003 else "dist>10%"
            rejected.append((src, dist_pct * 100, reason))

    if not valid:
        if trendline and trendline > entry > 0.0:
            final_sl, final_src = trendline, "atr_trendline_fallback"
        else:
            final_sl, final_src = entry * 1.05, "fixed_5pct_fallback"
        if rejected:
            logger.info("[SL_SELECT SHORT] entry=%.6f fallback=%s — все кандидаты отброшены: %s",
                        entry, final_src,
                        ", ".join(f"{s}={d:.2f}% ({r})" for s, d, r in rejected))
    else:
        valid.sort(key=lambda x: x[2])
        final_sl, final_src, _ = valid[0]
        if rejected:
            logger.info("[SL_SELECT SHORT] entry=%.6f выбран=%s dist=%.2f%% | отброшены: %s",
                        entry, final_src, valid[0][2] * 100,
                        ", ".join(f"{s}={d:.2f}% ({r})" for s, d, r in rejected))

    if live_mode:
        final_sl = final_sl * (1.0 + 0.0015)
        final_src += "_buf"

    return final_sl, final_src


async def _execute_atr_change_signal(
    bot, symbol: str, ev, tf: str, df=None, side: str = "LONG",
) -> None:
    """Прямой вход по ATR change на 1h/4h/15m (DEV-209: LONG + SHORT, 15m только в OTE зоне).

    LONG (side='LONG'): SL ниже entry (trendup/swing_low/ATR14×2), TP = entry + 3R.
    SHORT (side='SHORT'): SL выше entry (trenddown/swing_high/ATR14×2), TP = entry - 3R.

    Strength = aggregator.aggregate() — Σ trigger + confirmations
    (atr_change_{tf} + zone_OS/OB_{tf} + ote_zone + другие confluence через per-source window).
    """
    try:
        from core.signals.signal_models import (
            TradingRecommendation, SignalDirection, MarketContext,
        )
        from core.confirmations.registry import get_weight as _gw

        side = side.upper()
        if side not in ("LONG", "SHORT"):
            return

        # Soft фильтр: atr_change режимный (18.05.2026)
        # LONG: штраф к strength (не блок) — рынок цикличен, штраф снизит до min_strength в плохом контексте
        # SHORT: только в TREND_DOWN (avgR=+0.488, WR=78.8% vs RANGE avgR=+0.031)
        _atrc_cfg = bot.config.get("signal_quality.atr_change") or {}
        _atrc_regime = None
        if df is not None and len(df) >= 30:
            try:
                from core.indicators.market_regime import MarketRegimeClassifier
                _atrc_regime = MarketRegimeClassifier().classify_from_ohlcv(df)
            except Exception:
                pass
        _allow_sr = _atrc_cfg.get("allow_short_regimes")
        if side == "SHORT" and _allow_sr and _atrc_regime:
            if _atrc_regime not in _allow_sr:
                logger.info("[ATRChange] %s SHORT пропущен: режим %s не в %s",
                            symbol, _atrc_regime, _allow_sr)
                return

        entry = ev.price
        if entry <= 0:
            return

        # live_mode: биржевой TSL срабатывает при касании → нужен буфер
        _exec_mode = bot.config.get("trading.execution_mode", "simulation")
        _live_mode = _exec_mode in ("vst", "live")

        if side == "LONG":
            sl, sl_source = _select_optimal_sl_long(entry, df, ev.trendline, live_mode=_live_mode)
            sl_dist = entry - sl
            valid_sl = sl > 0 and sl < entry
        else:
            sl, sl_source = _select_optimal_sl_short(entry, df, ev.trendline, live_mode=_live_mode)
            sl_dist = sl - entry
            valid_sl = sl > entry

        if not valid_sl or sl_dist <= 0:
            logger.debug("[ATRChange] %s %s %s: невалидный SL %.6f (entry=%.6f)",
                         symbol, tf, side, sl, entry)
            try:
                from core.observability.decision_trace import record_drop
                asyncio.create_task(record_drop(
                    symbol=symbol, gate_name="invalid_sl",
                    drop_reason=f"atr_change_{tf}/{side}: sl={sl:.6f} entry={entry:.6f} src={sl_source}",
                    signal_type=f"atr_change_{tf}", direction=side, strength=0,
                    features={"trigger_source": f"atr_change_{tf}", "atr_tf": tf,
                              "sl_source": sl_source, "trendline": ev.trendline},
                ))
            except Exception:
                pass
            return

        # DEV-209: strength через aggregator (Σ trigger + confirmations с per-source window)
        # Это включает atr_change_{tf}, zone_OS/OB, ote_zone, cascade pre_1h и т.д.
        _ca = getattr(bot, "confirmation_aggregator", None)
        agg_strength = 0
        agg_res = None
        if _ca:
            try:
                agg_res = _ca.aggregate(symbol, side)
                if agg_res.get("has_trigger"):
                    agg_strength = int(agg_res.get("strength", 0))
            except Exception as _agg_e:
                logger.debug("[ATRChange] %s %s %s: aggregate err: %s",
                             symbol, tf, side, _agg_e)

        # Fallback: если aggregator пуст (cold start) — старая логика trigger + zone
        if agg_strength <= 0:
            agg_strength = _gw(f"atr_change_{tf}", side)
            if side == "LONG" and ev.zone == "OS":
                agg_strength += _gw(f"zone_OS_{tf}", "LONG")
            elif side == "SHORT" and ev.zone == "OB":
                agg_strength += _gw(f"zone_OB_{tf}", "SHORT")

        strength = min(agg_strength, 100)

        # Soft penalty для LONG atr_change (18.05.2026, не блок — рынок цикличен)
        # avgR=-0.711, WR=8.8% (n=80, 7дн) — снижаем strength, TradeRouter отфильтрует слабые
        if side == "LONG":
            _long_penalty = int((_atrc_cfg or {}).get("long_strength_penalty", 0))
            if _long_penalty > 0:
                strength = max(0, strength - _long_penalty)
                logger.debug("[ATRChange] %s LONG soft_penalty=%d → strength=%d",
                             symbol, _long_penalty, strength)


        # A1 (14.05): отдельный порог для atr_change (бэктест: 1h_LONG+0.12 при min=15).
        min_str = int(bot.config.get("signal_quality.min_strength_atr_change",
                      bot.config.get("signal_quality.min_strength_register", 40)))
        if strength < min_str:
            # A2 (14.05): запись в signal_drops для observability.
            logger.debug("[ATRChange] %s %s %s: strength=%d < %d (drop)",
                         symbol, tf, side, strength, min_str)
            try:
                from core.observability.decision_trace import record_drop
                _conf_count = len((agg_res or {}).get("confirmations", []))
                _conf_sources = [c.get("source") for c in (agg_res or {}).get("confirmations", [])]
                asyncio.create_task(record_drop(
                    symbol=symbol,
                    gate_name="strength_too_low",
                    drop_reason=f"atr_change_{tf}/{side}: strength={strength} < min={min_str}",
                    signal_type=f"atr_change_{tf}",
                    direction=side,
                    strength=strength,
                    features={
                        "trigger_source": f"atr_change_{tf}",
                        "atr_tf": tf,
                        "agg_strength": strength,
                        "confirmations_count": _conf_count,
                        "confirmations_sources": _conf_sources,
                        "signal_mode": (agg_res or {}).get("signal_mode"),
                        "strength_breakdown": (agg_res or {}).get("strength_breakdown"),
                        "zone": ev.zone,
                        "wt1": ev.wt1,
                        "entry_price": entry,
                    },
                ))
            except Exception as _rd_e:
                logger.debug("[ATRChange] record_drop failed: %s", _rd_e)
            return

        if side == "LONG":
            tp = entry + sl_dist * 3.0
            action = "BUY"
            direction_enum = SignalDirection.LONG
            confidence = 0.85 if ev.zone == "OS" else 0.65
        else:
            tp = entry - sl_dist * 3.0
            action = "SELL"
            direction_enum = SignalDirection.SHORT
            confidence = 0.85 if ev.zone == "OB" else 0.65

        # Confidence boost от количества confirmations
        if agg_res and agg_res.get("confirmations"):
            _n = len(agg_res["confirmations"])
            if _n >= 4:
                confidence = min(0.95, confidence + 0.10)
            elif _n >= 2:
                confidence = min(0.90, confidence + 0.05)

        logger.info(
            "[ATRChange] %s %s %s: entry=%.4f sl=%.4f (src=%s dist=%.2f%%) tp=%.4f zone=%s str=%d",
            symbol, tf, side, entry, sl, sl_source, 100 * sl_dist / entry, tp, ev.zone, strength,
        )

        rec = TradingRecommendation(
            symbol=symbol,
            action=action,
            direction=direction_enum,
            overall_strength=strength,
            confidence=confidence,
            risk_level="MEDIUM",
            signals_count=1,
            supporting_signals=[],
            conflicting_signals=[],
            market_context=MarketContext(
                symbol=symbol, current_price=entry,
                volume_24h=0.0, volume_change_24h=0.0, price_change_24h=0.0,
            ),
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            sl_source=sl_source,
            tp_source="atr_rr_3.0",
        )

        # DEV-226: Elliott context из кэша scan_loop
        _ell_snap = getattr(bot, "_elliott_snap", {}).get(symbol, {})

        extra = {
            "signal_type_override": "atr_change",
            "trigger_source": f"atr_change_{tf}",
            "atr_tf": tf,
            "zone": ev.zone,
            "wt1": ev.wt1,
            "signal_mode": (agg_res or {}).get("signal_mode", "momentum"),
            "confirmations": (agg_res or {}).get("confirmations", []),
            "strength_breakdown": (agg_res or {}).get("strength_breakdown", {}),
            "trade_mode": "atr_change",  # dedup: разные режимы с wt_sideways не блокируют друг друга
            "elliott_n_down":     _ell_snap.get("elliott_n_down", 0),      # HTF 4h
            "elliott_n_up":       _ell_snap.get("elliott_n_up", 0),
            "elliott_n_down_1h":  _ell_snap.get("elliott_n_down_1h", 0),   # MTF 1h
            "elliott_n_up_1h":    _ell_snap.get("elliott_n_up_1h", 0),
            "elliott_n_down_ltf": _ell_snap.get("elliott_n_down_ltf", 0),  # LTF entry TF
            "elliott_n_up_ltf":   _ell_snap.get("elliott_n_up_ltf", 0),
            "elliott_htf_tf":     _ell_snap.get("htf_tf", "4h"),
        }

        # Этап 1.Б (15.05.2026): pilot atr_change через TradeRouter.
        # Router обходит DEV-155 (min_strength_register=60 блок) — strength_threshold SOFT.
        # Откат: config.yaml → signal_router.enabled=false.
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            _sr_result = await bot.trade_router.submit(
                rec, source="atr_change", extra_features=extra,
            )
            trade_id = _sr_result.trade_id
            if trade_id:
                logger.info(
                    "[ATRChange] %s %s %s router #%d str=%d->%d soft=%d exch=%s sl_src=%s",
                    symbol, tf, side, trade_id, strength, _sr_result.final_strength,
                    len(_sr_result.soft_penalties),
                    _sr_result.exchange_order_id or "none", sl_source,
                )
            else:
                _hd_names = ",".join(g for g, _ in _sr_result.hard_drops) or "none"
                logger.info(
                    "[ATRChange] %s %s %s router dropped: %s str=%d",
                    symbol, tf, side, _hd_names, _sr_result.final_strength,
                )
        else:
            # Старый путь (signal_router.enabled=false)
            trade_id = await bot.trade_simulator.register_trade_async(
                rec, bot.data_collector, extra_features=extra,
            )
            if trade_id:
                logger.info("[ATRChange] %s %s %s → #%d registered str=%d (sl_source=%s)",
                            symbol, tf, side, trade_id, strength, sl_source)
                if _ca:
                    try:
                        _ca.clear(symbol, side)
                    except Exception:
                        pass
                if hasattr(bot, "order_executor") and hasattr(bot, "position_sizer"):
                    try:
                        _oe = bot.order_executor
                        _deposit = await _oe.get_available_balance()
                        _risk_pct = float(bot.config.get("trading.risk_pct", 1.0))
                        _leverage = int(bot.config.get("trading.leverage", 5))
                        _qty = bot.position_sizer.calc_qty(
                            entry_price=entry, sl_price=sl,
                            deposit=_deposit, risk_pct=_risk_pct, leverage=_leverage,
                        )
                        if _qty > 0:
                            _br = await _oe.open_bracket(
                                symbol=symbol, direction=side,
                                entry_price=entry, sl=sl, tp1=tp, tp2=None, qty=_qty,
                            )
                            if not _br.success:
                                if _br.error != "position_already_open":
                                    logger.warning("[ATRChange] %s OrderExecutor: %s", symbol, _br.error)
                            else:
                                logger.info(
                                    "[ATRChange] [%s] bracket: %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                                    _br.mode.upper(), side, _qty, entry, sl, tp, _br.order_id, _br.notional_usdt,
                                )
                                if hasattr(bot, "position_manager"):
                                    bot.position_manager.register(
                                        symbol=symbol, side=side, qty=_qty,
                                        sim_trade_id=trade_id,
                                        exchange_order_id=_br.order_id,
                                    )
                                if _live_mode:
                                    from core.exchange.tsl_updater import fetch_and_save_sl_order_id
                                    asyncio.create_task(fetch_and_save_sl_order_id(bot, trade_id, symbol, side))
                        else:
                            logger.warning("[ATRChange] %s qty=0 (deposit=%.2f risk=%.1f%%)", symbol, _deposit, _risk_pct)
                    except Exception as _oe_e:
                        logger.warning("[ATRChange] %s OrderExecutor exception: %s", symbol, _oe_e)
            else:
                # A2: register_trade_async вернул None — отрезано gate'ами trade_simulator
                # (dedup / sl_cooldown / pair_cooldown_sl_streak / min_volume / ...)
                try:
                    from core.observability.decision_trace import record_drop
                    asyncio.create_task(record_drop(
                        symbol=symbol, gate_name="register_returned_none",
                        drop_reason=f"atr_change_{tf}/{side}: register_trade_async() returned None",
                        signal_type=f"atr_change_{tf}", direction=side, strength=strength,
                        features={"trigger_source": f"atr_change_{tf}", "atr_tf": tf,
                                  "agg_strength": strength, "entry_price": entry, "sl": sl,
                                  "confirmations_count": len((agg_res or {}).get("confirmations", []))},
                    ))
                except Exception:
                    pass

    except Exception as e:
        logger.warning("[ATRChange] %s %s %s execute error: %s", symbol, tf, side, e)
        try:
            from core.observability.decision_trace import record_drop
            asyncio.create_task(record_drop(
                symbol=symbol, gate_name="exception",
                drop_reason=f"atr_change_{tf}/{side}: {type(e).__name__}: {e}",
                signal_type=f"atr_change_{tf}", direction=side, strength=0,
                features={"trigger_source": f"atr_change_{tf}", "atr_tf": tf},
            ))
        except Exception:
            pass


async def _execute_sideways_signal(bot, rec) -> None:
    """Регистрирует wt_sideways сделку и размещает ордер на бирже (VST/LIVE).

    Этап 1.В (16.05.2026): подключено к TradeRouter (source='wt_sideways').
    Откат: config.yaml → signal_router.enabled=false (использует старый путь в else).
    """
    try:
        _meta = getattr(rec, "metadata", {}) or {}
        _extra = {
            "sideways_mode":   True,
            "wt1_at_signal":   _meta.get("wt1"),
            "sideways_bars":   _meta.get("sideways_bars"),
        }
        # DEV-202: добавить confirmations из агрегатора (если есть ATR накопленные)
        _sw_conf_agg = getattr(bot, "confirmation_aggregator", None)
        if _sw_conf_agg is not None:
            try:
                _sw_dir = getattr(rec.direction, 'value', str(rec.direction))
                _sw_side = 'LONG' if 'LONG' in _sw_dir.upper() else 'SHORT'
                _sw_res = _sw_conf_agg.aggregate(rec.symbol, _sw_side)
                _extra['confirmations'] = _sw_res.get('confirmations', [])
                _extra['signal_mode'] = _sw_res.get('signal_mode', 'unknown')
                if _sw_res.get('strength_breakdown'):
                    _extra['strength_breakdown'] = _sw_res['strength_breakdown']
            except Exception:
                _extra['confirmations'] = []

        # Этап 1.В: через TradeRouter (единый узел регистрации)
        if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
            _sr_result = await bot.trade_router.submit(
                rec, source="wt_sideways", extra_features=_extra,
            )
            if _sr_result.trade_id:
                logger.info(
                    "[sideways] router #%d %s %s str=%d->%d soft=%d exch=%s",
                    _sr_result.trade_id, rec.symbol, rec.direction.value,
                    int(getattr(rec, "overall_strength", 0) or 0), _sr_result.final_strength,
                    len(_sr_result.soft_penalties), _sr_result.exchange_order_id or "none",
                )
            else:
                _hd = ",".join(g for g, _ in _sr_result.hard_drops) or "none"
                logger.info(
                    "[sideways] router dropped %s %s: %s str=%d",
                    rec.symbol, rec.direction.value, _hd, _sr_result.final_strength,
                )
            return

        # Старый путь (signal_router.enabled=false)
        trade_id = await bot.trade_simulator.register_trade_async(
            rec, bot.data_collector, extra_features=_extra
        )
        if trade_id is None:
            return
        logger.info("[sideways] #%d %s %s — зарегистрирована", trade_id, rec.symbol, rec.direction.value)

        if not hasattr(bot, "order_executor"):
            return
        try:
            _oe     = bot.order_executor
            _dir    = rec.direction.value
            _entry  = float(rec.entry_price or 0)
            _sl     = float(rec.stop_loss or 0)
            _tp     = float(rec.take_profit or 0)
            if _entry <= 0 or _sl <= 0 or _tp <= 0:
                return
            _deposit  = await _oe.get_available_balance()
            _risk_pct = float(bot.config.get("trading.risk_pct", 1.0))
            _leverage = int(bot.config.get("trading.leverage", 5))
            _qty = bot.position_sizer.calc_qty(
                entry_price=_entry, sl_price=_sl,
                deposit=_deposit, risk_pct=_risk_pct, leverage=_leverage,
            )
            if _qty <= 0:
                logger.warning("[sideways] %s qty=0 (deposit=%.2f risk=%.1f%%)", rec.symbol, _deposit, _risk_pct)
                return
            _br = await _oe.open_bracket(
                symbol=rec.symbol, direction=_dir,
                entry_price=_entry, sl=_sl, tp1=_tp, tp2=None, qty=_qty,
            )
            if not _br.success:
                if _br.error != "position_already_open":
                    logger.warning("[sideways] %s OrderExecutor: %s", rec.symbol, _br.error)
                return
            logger.info(
                "[sideways] [%s] bracket: %s qty=%.6f entry=%.6f SL=%.6f TP=%.6f order_id=%s notional=%.2f",
                _br.mode.upper(), _dir, _qty, _entry, _sl, _tp, _br.order_id, _br.notional_usdt,
            )
            if hasattr(bot, "position_manager"):
                bot.position_manager.register(
                    symbol=rec.symbol, side=_dir, qty=_qty,
                    sim_trade_id=trade_id, exchange_order_id=_br.order_id,
                )
            if _br.order_id:
                bot.trade_simulator.set_exchange_order_id(
                    trade_id, _br.order_id, qty=_qty, actual_entry_price=_br.entry_price,
                )
                if _br.tp_order_id:
                    bot.trade_simulator.set_exchange_tp_order_id(trade_id, _br.tp_order_id)
                else:
                    from core.exchange.tsl_updater import fetch_and_save_tp_order_id
                    asyncio.create_task(fetch_and_save_tp_order_id(bot, trade_id, rec.symbol, _dir))
                if _br.sl_order_id:
                    bot.trade_simulator.set_exchange_sl_order_id(trade_id, _br.sl_order_id)
                else:
                    from core.exchange.tsl_updater import fetch_and_save_sl_order_id
                    asyncio.create_task(fetch_and_save_sl_order_id(bot, trade_id, rec.symbol, _dir))
        except Exception as _oe_e:
            logger.warning("[sideways] %s OrderExecutor: %s", rec.symbol, _oe_e)
    except Exception as _e:
        logger.warning("[sideways] _execute_sideways_signal: %s", _e)


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

                # D-055v2 REVERTED (2026-05-24 17:46 MSK): sequential TF fetch замедлял
                # scan_loop → cascade через 54 мин (raньше 8-9ч). Возврат на parallel.
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
                from core.indicators.indicators import calculate_wt as _calc_wt, calculate_trend as _calc_trend
                from core.infra.config_loader import config as _cfg_scan
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

                # DEV-226: Elliott n_down/n_up на всех TF (HTF/MTF/LTF)
                # n_down=2-3 → Волна 3 SHORT оптимальна; n_down=4+ → STOP SHORT
                try:
                    from core.indicators.indicators import find_swing_highs, find_swing_lows, calculate_n_down, calculate_n_up

                    def _calc_elliott(df_, period=5):
                        if df_ is None or len(df_) < period * 2 + 2:
                            return 0, 0
                        sh = find_swing_highs(df_["high"], period=period)
                        sl = find_swing_lows(df_["low"], period=period)
                        return calculate_n_down(sh), calculate_n_up(sl)

                    _nd_4h, _nu_4h = _calc_elliott(df_4h) if (df_4h is not None and not df_4h.empty) else (0, 0)
                    _nd_1h, _nu_1h = _calc_elliott(df_1h) if (df_1h is not None and not df_1h.empty) else (0, 0)
                    _nd_ltf, _nu_ltf = _calc_elliott(df_entry, period=3)  # LTF — меньший period для 15m

                    if not hasattr(bot, "_elliott_snap"):
                        bot._elliott_snap = {}
                    bot._elliott_snap[sym] = {
                        "elliott_n_down":     _nd_4h,   # HTF (4h) — основной
                        "elliott_n_up":       _nu_4h,
                        "elliott_n_down_1h":  _nd_1h,   # MTF (1h)
                        "elliott_n_up_1h":    _nu_1h,
                        "elliott_n_down_ltf": _nd_ltf,  # LTF (15m/entry)
                        "elliott_n_up_ltf":   _nu_ltf,
                        "htf_tf": "4h" if (df_4h is not None and not df_4h.empty) else "1h",
                    }
                except Exception as _ell_e:
                    logger.debug("[Elliott] %s n_down/n_up error: %s", sym, _ell_e)

                # DEV-108: вычисляем market_regime один раз для всего скана пары
                # Используется в WT/confluence детекторах для dynamic_os в RANGE
                _pair_regime = ""
                try:
                    from core.indicators.market_regime import MarketRegimeClassifier
                    _pair_regime = MarketRegimeClassifier().classify_from_dataframes(
                        df_entry, df_1h
                    ) or ""
                except Exception:
                    pass

                # ═══ КУБ МЕТАТРОНА: публикуем снапы всех сфер в PairContextBus ═══
                _bus = getattr(bot, "pair_context", None)
                if _bus is not None:
                    from core.context.pair_context import SphereEvent

                    # CUBE-08 Шаг 2: Сфера 1 — OHLCV_UPDATED для всех пар (каждый цикл)
                    _bus.publish(sym, SphereEvent.OHLCV_UPDATED, {
                        "tf": _etf, "rows": len(df_entry),
                    })

                    # Сфера 6: Market Regime → bus
                    if _pair_regime:
                        _rev_mode = None
                        try:
                            _mrc = MarketRegimeClassifier()
                            _rev_mode = _mrc.classify_mode(df_entry, df_1h, df_4h) if df_4h is not None else None
                        except Exception:
                            pass
                        _sw_threshold = int((bot.config.get("sideways_mode") or {}).get("min_sideways_bars", 3))
                        _bus.publish(sym, SphereEvent.REGIME_UPDATED, {
                            "regime": _pair_regime,
                            "mode": _rev_mode or "UNCLEAR",
                            "sideways_threshold": _sw_threshold,
                        })

                    # Sideways Mode: параллельный сигнал при RANGE-режиме
                    # Двойной gate: sideways_mode_active (счётчик) И текущий _pair_regime == RANGE
                    _sw_cfg = bot.config.get("sideways_mode") or {}
                    if _sw_cfg.get("enabled", True):
                        _pair_st = _bus.get(sym) if _bus else None
                        _sw_regime_ok = (_pair_regime == "RANGE")
                        if _pair_st is not None and getattr(_pair_st, "sideways_mode_active", False) and _sw_regime_ok:
                            try:
                                from strategies.built_in.wt_sideways_strategy import analyze_sideways
                                _sw_tf  = _sw_cfg.get("timeframe", "30m")
                                _sw_str = int(_sw_cfg.get("min_strength", 60))
                                _df_sw  = await bot.data_collector.get_ohlcv(sym, _sw_tf, limit=200)
                                if _df_sw is not None and not _df_sw.empty:
                                    # DEV-209-ext: передаём df_1h для gate atr_trend_1h_bias (ARCH-95 H6)
                                    _sw_rec = analyze_sideways(sym, _df_sw, min_strength=_sw_str, df_1h=df_1h)
                                    if _sw_rec is not None:
                                        # Добавляем sideways_bars в metadata для features_json
                                        if _sw_rec.metadata is None:
                                            _sw_rec.metadata = {}
                                        _sw_rec.metadata["sideways_bars"] = getattr(_pair_st, "sideways_bars", 0)
                                        asyncio.create_task(
                                            _execute_sideways_signal(bot, _sw_rec)
                                        )
                                        logger.info("[sideways] %s: сигнал %s — запущен execute",
                                                    sym, _sw_rec.direction.value)
                            except Exception as _sw_e:
                                logger.debug("[sideways] %s: ошибка: %s", sym, _sw_e)

                    # Сфера 3/15 (ARCH-117): WT snap → bus через WTService.
                    # Единый источник: zone(±60), wt_cross(сырой, обр.совместимость),
                    # cross_in_zone(строгий — wt1 был в OS/OB ДО кросса).
                    from core.intelligence.wt_service import build_wt_snap
                    _wt_snap_data = build_wt_snap(
                        [(_etf, df_entry), ("1h", df_1h), ("4h", df_4h), ("1d", df_1d)]
                    )
                    if _wt_snap_data:
                        _bus.publish(sym, SphereEvent.WT_SNAP_UPDATED, _wt_snap_data)

                        # CUBE-08 Шаг 1: Сфера 3 — WT Verdict из snap (без API, ~0ms)
                        try:
                            from core.intelligence.wt_specialist import derive_wt_verdict
                            _wt_v = derive_wt_verdict(_wt_snap_data)
                            if _wt_v:
                                _bus.publish(sym, SphereEvent.WT_VERDICT, {
                                    "label": _wt_v, "confidence": 0.6,
                                })
                        except Exception as _wt_e:
                            logger.debug("[CUBE-08] wt_verdict %s: %s", sym, _wt_e)

                    # ARCH-120: Сфера 4 = SMC Sub-куб (единый вход: snapshot + verdict → Bus).
                    # Заменил два раздельных вызова (fast_smc_verdict + build_smc_snapshot).
                    # snap включает OB/FVG-multiTF/BOS/CHoCH/Fib/swing/OTE + liquidity(EQH/EQL).
                    try:
                        from core.smc.sub_cube import get_smc_sub_cube
                        _smc_ohlcv = {}
                        if df_entry is not None and not df_entry.empty:
                            _smc_ohlcv[_etf] = df_entry
                        if df_1h is not None and not df_1h.empty:
                            _smc_ohlcv["1h"] = df_1h
                        if df_4h is not None and not df_4h.empty:
                            _smc_ohlcv["4h"] = df_4h
                        if df_1d is not None and not df_1d.empty:
                            _smc_ohlcv["1d"] = df_1d
                        _smc_snap = get_smc_sub_cube().compute_and_publish(
                            sym, _smc_ohlcv, ctx_bus=_bus, df_1h=df_1h, df_4h=df_4h,
                        )
                        if _smc_snap:
                            # Кешируем для SMC BOS/CHoCH EventBus (ниже по коду)
                            if not hasattr(bot, "_last_smc_snap"):
                                bot._last_smc_snap = {}
                            bot._last_smc_snap[sym] = _smc_snap
                            logger.info(
                                "[SMC_SNAP] %s: OB_bull=%s OB_bear=%s BOS=%s CHoCH=%s in_OTE=%s EQH=%s EQL=%s verdict=%s",
                                sym,
                                bool(_smc_snap.get("nearest_bull_ob")),
                                bool(_smc_snap.get("nearest_bear_ob")),
                                (_smc_snap.get("last_bos") or {}).get("direction"),
                                (_smc_snap.get("last_choch") or {}).get("direction"),
                                _smc_snap.get("price_in_ote"),
                                bool(_smc_snap.get("eqh_level")),
                                bool(_smc_snap.get("eql_level")),
                                _smc_snap.get("smc_verdict"),
                            )
                    except Exception as _smc_snap_e:
                        logger.debug("[ARCH-120] smc_sub_cube %s: %s", sym, _smc_snap_e)

                    # ARCH-123: Сфера 8 = PivotSphere (формализован, + fibonacci_equiv).
                    # Заменил inline-публикацию. Снап: {1W/1D/1M: {PP,S1..R3}} + fib-карта.
                    _pc = getattr(bot, "pivot_calculator", None)
                    if _pc is not None:
                        from core.pivots.pivot_sphere import get_pivot_sphere
                        get_pivot_sphere().compute_and_publish(sym, _pc, ctx_bus=_bus)

                # ═══ КУБ: HTF детекторы → EventBus (trend_change_1h, wt_cross_4h/1d) ═══
                _eb = getattr(bot, "event_bus", None)
                if _eb is not None:
                    _htf_det = getattr(bot, "_htf_detectors", None)
                    if _htf_det is not None:
                        _tc, _wc, _ze, _wxt = _htf_det
                        # Trend change 15m (скальп)
                        if df_entry is not None and not df_entry.empty:
                            _tc_fired, _tc_data = _tc.check(sym, df_entry, "15m")
                            if _tc_fired:
                                asyncio.create_task(_eb.publish(sym, "trend_change_15m", priority=3, data=_tc_data))
                        # Trend change 1h
                        if df_1h is not None and not df_1h.empty:
                            _tc_fired, _tc_data = _tc.check(sym, df_1h, "1h")
                            if _tc_fired:
                                asyncio.create_task(_eb.publish(sym, "trend_change_1h", priority=2, data=_tc_data))
                        # Trend change 4h
                        if df_4h is not None and not df_4h.empty:
                            _tc4h_fired, _tc4h_data = _tc.check(sym, df_4h, "4h")
                            if _tc4h_fired:
                                asyncio.create_task(_eb.publish(sym, "trend_change_4h", priority=1, data=_tc4h_data))
                        # Trend change 1d
                        if df_1d is not None and not df_1d.empty:
                            _tc1d_fired, _tc1d_data = _tc.check(sym, df_1d, "1d")
                            if _tc1d_fired:
                                asyncio.create_task(_eb.publish(sym, "trend_change_1d", priority=1, data=_tc1d_data))
                        # WT cross 15m
                        if df_entry is not None and not df_entry.empty:
                            _wc15_fired, _wc15_data = _wc.check(sym, df_entry, "15m")
                            if _wc15_fired:
                                asyncio.create_task(_eb.publish(sym, "wt_cross_15m", priority=3, data=_wc15_data))
                        # WT cross 1h
                        if df_1h is not None and not df_1h.empty:
                            _wc1h_fired, _wc1h_data = _wc.check(sym, df_1h, "1h")
                            if _wc1h_fired:
                                asyncio.create_task(_eb.publish(sym, "wt_cross_1h", priority=2, data=_wc1h_data))
                        # WT cross 4h
                        if df_4h is not None and not df_4h.empty:
                            _wc_fired, _wc_data = _wc.check(sym, df_4h, "4h")
                            if _wc_fired:
                                asyncio.create_task(_eb.publish(sym, "wt_cross_4h", priority=2, data=_wc_data))
                        # WT cross 1d
                        if df_1d is not None and not df_1d.empty:
                            _wc1d_fired, _wc1d_data = _wc.check(sym, df_1d, "1d")
                            if _wc1d_fired:
                                asyncio.create_task(_eb.publish(sym, "wt_cross_1d", priority=1, data=_wc1d_data))
                        # Zone entry OS/OB — все TF
                        for _ze_df, _ze_tf in [
                            (df_entry, "15m"), (df_1h, "1h"), (df_4h, "4h"), (df_1d, "1d"),
                        ]:
                            if _ze_df is not None and not _ze_df.empty:
                                _ze_fired, _ze_data = _ze.check(sym, _ze_df, _ze_tf)
                                if _ze_fired:
                                    _ze_event = f"zone_enter_{_ze_data['zone'].lower()}"
                                    asyncio.create_task(_eb.publish(sym, _ze_event, priority=2, data=_ze_data))
                        # WT Extreme (< -80 / > +80) — все TF
                        for _wxt_df, _wxt_tf in [
                            (df_entry, "15m"), (df_1h, "1h"), (df_4h, "4h"), (df_1d, "1d"),
                        ]:
                            if _wxt_df is not None and not _wxt_df.empty:
                                _wxt_fired, _wxt_data = _wxt.check(sym, _wxt_df, _wxt_tf)
                                if _wxt_fired:
                                    _publish_and_confirm(
                                        bot, sym, "wt_extreme", priority=1, data=_wxt_data,
                                        conf_source="wt_extreme",
                                        side=(_wxt_data or {}).get("direction", ""),
                                        tf=_wxt_tf, evidence=_wxt_data,
                                    )

                # ═══ КУБ: ATR Trend Change Detector → EventBus + ConfirmationAggregator (DEV-199/202) ═══
                # 1d не публикуется: backtest R8 avgR=-0.4
                # DEV-209: 15m расширен в OTE зоне; LONG+SHORT; auto ote_zone confirmation.
                _atr_det = getattr(bot, "atr_change_detector", None)
                _eb_atr = getattr(bot, "event_bus", None)
                _conf_agg = getattr(bot, "confirmation_aggregator", None)
                # SMC snapshot для OTE проверки (один раз на пару)
                _smc_snap_atr = (getattr(bot, "_last_smc_snap", {}) or {}).get(sym, {}) or {}
                _price_in_ote = bool(_smc_snap_atr.get("price_in_ote"))
                _ote_dir = _smc_snap_atr.get("ote_direction")  # "LONG" | "SHORT" | None
                _ote_tf  = _smc_snap_atr.get("ote_tf")

                if _atr_det is not None and _eb_atr is not None:
                    for _atr_df, _atr_tf in [(df_entry, "15m"), (df_1h, "1h"), (df_4h, "4h")]:
                        try:
                            if _atr_df is None or _atr_df.empty:
                                continue
                            _atr_ev = _atr_det.detect(sym, _atr_tf, _atr_df)
                            if _atr_ev is None:
                                continue
                            _side = 'LONG' if _atr_ev.side == 'UP' else 'SHORT'

                            # Публикация в EventBus (для наблюдения и совместимости)
                            _prio = 2 if _atr_tf == "15m" else 1
                            asyncio.create_task(_eb_atr.publish(
                                sym, f"atr_change_{_atr_tf}", priority=_prio, data=_atr_ev.to_dict()
                            ))

                            # → ConfirmationAggregator: trigger + zone + ote_zone confirmations
                            if _conf_agg is not None:
                                try:
                                    from core.confirmations.models import Confirmation as _Conf
                                    from core.confirmations.registry import get_weight as _gw

                                    _src = f'atr_change_{_atr_tf}'
                                    _conf_agg.on_confirmation(_Conf(
                                        source=_src, symbol=sym, side=_side,
                                        weight=_gw(_src, _side), confidence=1.0,
                                        evidence={'price': _atr_ev.price, 'wt1': _atr_ev.wt1, 'zone': _atr_ev.zone},
                                        tf=_atr_tf,
                                    ))
                                    # Zone OS/OB как дополнительное подтверждение
                                    if _atr_ev.zone == 'OS' and _side == 'LONG':
                                        _zs = f'zone_OS_{_atr_tf}'
                                        _zw = _gw(_zs, _side)
                                        if _zw > 0:
                                            _conf_agg.on_confirmation(_Conf(
                                                source=_zs, symbol=sym, side=_side,
                                                weight=_zw, confidence=1.0,
                                                evidence={'wt1': _atr_ev.wt1}, tf=_atr_tf,
                                            ))
                                    elif _atr_ev.zone == 'OB' and _side == 'SHORT':
                                        _zs = f'zone_OB_{_atr_tf}'
                                        _zw = _gw(_zs, _side)
                                        if _zw > 0:
                                            _conf_agg.on_confirmation(_Conf(
                                                source=_zs, symbol=sym, side=_side,
                                                weight=_zw, confidence=1.0,
                                                evidence={'wt1': _atr_ev.wt1}, tf=_atr_tf,
                                            ))
                                    # DEV-209: AUTO ote_zone confirmation если cross ВНУТРИ OTE
                                    # и направление совпадает с импульсом OTE.
                                    if _price_in_ote and _ote_dir == _side:
                                        _oz_w = _gw('ote_zone', _side)
                                        if _oz_w > 0:
                                            _conf_agg.on_confirmation(_Conf(
                                                source='ote_zone', symbol=sym, side=_side,
                                                weight=_oz_w, confidence=1.0,
                                                evidence={
                                                    'ote_tf': _ote_tf,
                                                    'retracement_pct': _smc_snap_atr.get('current_retracement'),
                                                    'price': _atr_ev.price,
                                                },
                                                tf=_ote_tf or _atr_tf,
                                            ))
                                except Exception as _ca_e:
                                    logger.debug("[ConfAgg] %s %s: %s", sym, _atr_tf, _ca_e)

                            # DEV-209: прямой вход
                            #   1h/4h — всегда (оба side, по R8 SHORT avgR=+0.164/+0.287)
                            #   15m — только когда price_in_ote и направление совпадает с OTE impulse
                            _allow_entry = False
                            if _atr_tf in ('1h', '4h'):
                                _allow_entry = True
                            elif _atr_tf == '15m' and _price_in_ote and _ote_dir == _side:
                                _allow_entry = True
                                logger.info(
                                    "[ATRChange] %s 15m %s в OTE %s — разрешён прямой вход",
                                    sym, _side, _ote_tf,
                                )

                            if _allow_entry:
                                asyncio.create_task(_execute_atr_change_signal(
                                    bot, sym, _atr_ev, _atr_tf, df=_atr_df, side=_side,
                                ))
                        except Exception as _atr_e:
                            logger.debug("[ATRChangeDetector] %s error %s: %s", _atr_tf, sym, _atr_e)

                # ═══ KYB: Режим рынка → regime_change ═══
                _eb2 = getattr(bot, "event_bus", None)
                if _eb2 is not None and _pair_regime:
                    _prev_regimes = getattr(bot, "_prev_regimes", {})
                    if not hasattr(bot, "_prev_regimes"):
                        bot._prev_regimes = {}
                    _old_regime = bot._prev_regimes.get(sym)
                    if _old_regime is not None and _old_regime != _pair_regime:
                        asyncio.create_task(_eb2.publish(sym, "regime_change", priority=3, data={
                            "old": _old_regime, "new": _pair_regime,
                        }))
                        logger.info("[KUB] %s regime_change: %s → %s", sym, _old_regime, _pair_regime)
                    bot._prev_regimes[sym] = _pair_regime

                # ═══ КУБ: SMC BOS/CHoCH → EventBus ═══
                if _eb2 is not None:
                    try:
                        _smc_snap_local = getattr(bot, "_last_smc_snap", {}).get(sym)
                        if _smc_snap_local:
                            _last_bos   = _smc_snap_local.get("last_bos")
                            _last_choch = _smc_snap_local.get("last_choch")
                            _bos_cache  = getattr(bot, "_prev_bos_id", {})
                            _choch_cache = getattr(bot, "_prev_choch_id", {})
                            if not hasattr(bot, "_prev_bos_id"):
                                bot._prev_bos_id, bot._prev_choch_id = {}, {}
                            if _last_bos:
                                # Ключ: (tf, direction) — новый BOS = смена tf или direction
                                _bos_id = (_last_bos.get("tf"), _last_bos.get("direction"))
                                if bot._prev_bos_id.get(sym) != _bos_id:
                                    bot._prev_bos_id[sym] = _bos_id
                                    _bos_tf = _last_bos.get("tf", "")
                                    _bos_side = "LONG" if _last_bos.get("direction") == "UP" else "SHORT"
                                    _publish_and_confirm(
                                        bot, sym, "smc_bos_detected", priority=2, data=_last_bos,
                                        conf_source=f"smc_bos_{_bos_tf}", side=_bos_side, tf=_bos_tf,
                                        evidence=_last_bos,
                                    )
                                    logger.info("[KUB] %s smc_bos_detected: %s tf=%s", sym, _last_bos.get("direction"), _last_bos.get("tf"))
                            if _last_choch:
                                _choch_id = (_last_choch.get("tf"), _last_choch.get("direction"))
                                if bot._prev_choch_id.get(sym) != _choch_id:
                                    bot._prev_choch_id[sym] = _choch_id
                                    _choch_tf = _last_choch.get("tf", "")
                                    _choch_side = "LONG" if _last_choch.get("direction") == "UP" else "SHORT"
                                    _publish_and_confirm(
                                        bot, sym, "smc_choch_detected", priority=1, data=_last_choch,
                                        conf_source=f"smc_choch_{_choch_tf}", side=_choch_side, tf=_choch_tf,
                                        evidence=_last_choch,
                                    )
                                    logger.info("[KUB] %s smc_choch_detected: %s tf=%s", sym, _last_choch.get("direction"), _last_choch.get("tf"))
                            # FVG Touch — цена вошла в открытый Fair Value Gap
                            _cur_price_fvg = float(df_entry["close"].iloc[-1]) if df_entry is not None and not df_entry.empty else 0
                            if _cur_price_fvg > 0:
                                _fvg_fired_key = getattr(bot, "_prev_fvg_touch", {})
                                if not hasattr(bot, "_prev_fvg_touch"):
                                    bot._prev_fvg_touch = {}
                                for _fvg in _smc_snap_local.get("bull_fvg_active", []):
                                    if _fvg.get("top", 0) - _fvg.get("bottom", 0) < 1e-8:
                                        continue  # нулевой FVG — артефакт detect_fvg
                                    if _fvg.get("bottom", 0) <= _cur_price_fvg <= _fvg.get("top", 0):
                                        _fvg_key = (sym, "bull", round(_fvg.get("bottom", 0), 4))
                                        if bot._prev_fvg_touch.get(_fvg_key) != True:
                                            bot._prev_fvg_touch[_fvg_key] = True
                                            _fvg_data = {
                                                "type": "bull", "bottom": _fvg.get("bottom"), "top": _fvg.get("top"),
                                                "tf": _fvg.get("tf", _etf), "price": _cur_price_fvg,
                                            }
                                            _publish_and_confirm(
                                                bot, sym, "fvg_touch", priority=2, data=_fvg_data,
                                                conf_source="fvg_fill", side="LONG",
                                                tf=_fvg.get("tf", _etf), evidence=_fvg_data,
                                            )
                                            logger.info("[KUB] %s fvg_touch: BULL FVG %.4f–%.4f", sym, _fvg.get("bottom"), _fvg.get("top"))
                                    else:
                                        bot._prev_fvg_touch.pop((sym, "bull", round(_fvg.get("bottom", 0), 4)), None)
                                for _fvg in _smc_snap_local.get("bear_fvg_active", []):
                                    if _fvg.get("top", 0) - _fvg.get("bottom", 0) < 1e-8:
                                        continue  # нулевой FVG — артефакт detect_fvg
                                    if _fvg.get("bottom", 0) <= _cur_price_fvg <= _fvg.get("top", 0):
                                        _fvg_key = (sym, "bear", round(_fvg.get("top", 0), 4))
                                        if bot._prev_fvg_touch.get(_fvg_key) != True:
                                            bot._prev_fvg_touch[_fvg_key] = True
                                            _fvg_data = {
                                                "type": "bear", "bottom": _fvg.get("bottom"), "top": _fvg.get("top"),
                                                "tf": _fvg.get("tf", _etf), "price": _cur_price_fvg,
                                            }
                                            _publish_and_confirm(
                                                bot, sym, "fvg_touch", priority=2, data=_fvg_data,
                                                conf_source="fvg_fill", side="SHORT",
                                                tf=_fvg.get("tf", _etf), evidence=_fvg_data,
                                            )
                                            logger.info("[KUB] %s fvg_touch: BEAR FVG %.4f–%.4f", sym, _fvg.get("bottom"), _fvg.get("top"))
                                    else:
                                        bot._prev_fvg_touch.pop((sym, "bear", round(_fvg.get("top", 0), 4)), None)
                    except Exception as _smc_ev_e:
                        logger.debug("[KUB] smc_events %s: %s", sym, _smc_ev_e)

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
                            # Куб: Сфера 7 → bus (ANOMALY + VOLUME_SPIKE)
                            if _bus is not None:
                                _v_ratio = info.get("volume_ratio", 0)
                                _bus.publish(sym, SphereEvent.ANOMALY_DETECTED, {
                                    "volume_ratio": _v_ratio,
                                    "tf": _scan_tf,
                                })
                                # VOLUME_SPIKE в PairContextBus (отдельное событие)
                                _bus.publish(sym, SphereEvent.VOLUME_SPIKE, {
                                    "ratio": _v_ratio, "tf": _scan_tf,
                                })

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
                                # DEV-200: + confirmation eql/eqh_swept по направлению свипа
                                _sw_side = getattr(_sweep_sig.direction, "value", str(_sweep_sig.direction))
                                _sw_src = "smc_eql_swept" if _sw_side == "LONG" else "smc_eqh_swept"
                                _publish_and_confirm(
                                    bot, sym, "liquidity_sweep", priority=1,
                                    conf_source=_sw_src, side=_sw_side,
                                    tf="1h", evidence={"level": getattr(_sweep_sig, "price", None)},
                                )
                        except Exception as _se:
                            logger.debug("[LIQSWEEP] %s error: %s", sym, _se)

                    # 2. WT
                    _pivot_calc = getattr(bot, "pivot_calculator", None)
                    for sig in await _check_wt_signals(sym, _df_tf, df_1h, market_regime=_pair_regime):
                        info = sig.data or {}
                        if _multi_tf:
                            sig.timeframe = _scan_tf  # тегируем ТФ
                        # ARCH-23: апгрейд wt_signal → confluence если цена у пивота (±1%)
                        # DEV-177 24.04: gated по analysis.confluence.enabled — иначе wt_signal утекал в БД
                        # как signal_type=confluence даже при выключенном детекторе.
                        # 16.05.2026 FIX: ключ был "confluence.enabled" (плоский) → None → False.
                        # В config.yaml ключ вложенный analysis.confluence.enabled. Фикс вернул confluence в работу.
                        _conf_enabled = bool(bot.config.get("analysis.confluence.enabled", False))
                        if _conf_enabled and _pivot_calc is not None and not _df_tf.empty:
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
                        # Куб: Сфера 7 → bus
                        if _bus is not None:
                            _bus.publish(sym, SphereEvent.SIGNAL_DETECTED, {
                                "signal_type": "wt_signal", "direction": sig.direction.value,
                                "strength": sig.strength, "tf": _scan_tf,
                            })

                # 3. Confluence: State Machine (ARCH-03) или Lookback Scanner (fallback)
                # DEV-177 24.04: gated по analysis.confluence.enabled — иначе утечка в signal_type=confluence.
                # 16.05.2026 FIX: ключ был "confluence.enabled" → None → False; фикс — analysis.confluence.enabled.
                pivot_cache = getattr(getattr(bot, "pivot_calculator", None), "pivot_cache", {})
                _conf_enabled_block = bool(bot.config.get("analysis.confluence.enabled", False))
                _use_sm = bool(bot.config.get("analysis.confluence.use_state_machine", True))
                _confluence_sigs = []
                if not _conf_enabled_block:
                    _use_sm = False  # пропускаем оба ветки ниже

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
                elif _conf_enabled_block:
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
                    # Куб: Сфера 7 → bus
                    if _bus is not None:
                        _bus.publish(sym, SphereEvent.SIGNAL_DETECTED, {
                            "signal_type": "confluence", "direction": sig.direction.value if sig.direction else "NEUTRAL",
                            "strength": sig.strength, "tf": _etf,
                        })
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
                        # Куб: WT-B → EventBus (prio=1, WR=85%)
                        _eb = getattr(bot, "event_bus", None)
                        if _eb is not None:
                            await _eb.publish(sym, "wt_b_signal", priority=1)

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
                                # Куб: Divergence → EventBus
                                _eb = getattr(bot, "event_bus", None)
                                if _eb is not None:
                                    await _eb.publish(sym, "divergence", priority=3)
                                # Куб: Сфера 7 → bus
                                if _bus is not None:
                                    _bus.publish(sym, SphereEvent.DIVERGENCE_FOUND, {
                                        "type": mtf_info.get("type"), "direction": mtf_info.get("direction"),
                                        "tf": "1h", "strength": mtf_info.get("strength", 60),
                                    })
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
                                        # Куб: Divergence → EventBus
                                        _eb = getattr(bot, "event_bus", None)
                                        if _eb is not None:
                                            await _eb.publish(sym, "divergence", priority=3)
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
                from core.mtf.mtf_interpreter import analyze_context
                from core.mtf.mtf_checker import collect_mtf_data
                _snapshot = await collect_mtf_data(sym, bot.data_collector)
                if _snapshot:
                    _cur_price = float(df_entry['close'].iloc[-1]) if df_entry is not None and len(df_entry) > 0 else 0
                    _wp = getattr(bot.pivot_calculator, "pivot_cache", {}).get(f"{sym}_1W", {})
                    _ctx = analyze_context(_snapshot, _cur_price, _wp, regime=None)
                    if _ctx and _ctx.direction_bias:
                        _bias_dir = getattr(_ctx.direction_bias, "value", str(_ctx.direction_bias))
                        _resolver.set_mtf_bias(sym, _bias_dir, _ctx.aligned_pct)
            except Exception:
                pass  # MTF Bias — бонус, не блокирует работу

            from core.mtf.multi_tf_resolver import TFSignal
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
    try:
        from core.trading.circuit_breaker import CircuitBreaker as _TradingCB
        _tcb_status = _TradingCB().status_text()
    except Exception:
        _tcb_status = "n/a"
    logger.info("Скан: %d пар | кеш=%d api_cb=%s trading_cb=%s",
                len(pairs), stats["cache_size"], stats["cb_state"], _tcb_status)
    # Event loop lag probe: sleep(0) должен вернуться немедленно (<5ms).
    # Задержка >50ms = event loop заблокирован тяжёлым sync-кодом.
    _lag_t0 = _time.monotonic()
    await asyncio.sleep(0)
    _el_lag = _time.monotonic() - _lag_t0
    if _el_lag > 0.05:
        logger.warning("[EventLoop] LAG %.3fs перед scan_gather — event loop был заблокирован!", _el_lag)
    elif _el_lag > 0.01:
        logger.info("[EventLoop] lag %.3fs перед scan_gather", _el_lag)
    await asyncio.gather(*[scan_one(sym) for sym in pairs], return_exceptions=True)
    elapsed = _time.monotonic() - cycle_start
    logger.info("Цикл сканирования завершён: %.1f сек / %d пар", elapsed, len(pairs))
    if elapsed > _slow_cycle:
        logger.warning("⚠️ Цикл превысил %.0f сек — рассмотреть увеличение Semaphore или sleep", _slow_cycle)
    # D-056 (2026-05-24): tracking для дашборда — D-053 detection (когда scan_loop умирает)
    import time as _t_mod
    bot._last_scan = {
        "ts": _t_mod.time(),
        "pairs": len(pairs),
        "elapsed_sec": round(elapsed, 1),
    }


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
            # Куб: Сфера 5 (Cross-Market) → PairContextBus для ВСЕХ пар
            _pcb = getattr(bot, "pair_context", None)
            if _pcb is not None:
                from core.context.pair_context import SphereEvent
                for sym in watchlist[:30]:
                    _pcb.publish(sym, SphereEvent.CROSS_MARKET, {
                        "btc_regime": f"SHOCK_{direction.upper()}",
                        "btc_move_pct": round(move_pct, 2),
                    })
    except Exception as e:
        logger.debug("[ARCH-70] _check_btc_macro_shock error: %s", e)


async def monitor_market(bot) -> None:
    """D-053 fix: Главный цикл мониторинга с автоматическим восстановлением после краша."""
    from bot.monitoring import (
        check_mtf_alerts,
        check_trend_signals,
        check_pivot_reversals,
        check_cascade_divergences,
        check_future_pivot_alerts,
    )
    _mm_restart_count = 0
    while bot.is_monitoring:
        if _mm_restart_count > 0:
            logger.error("[monitor_market] D-053: перезапуск #%d через 10s", _mm_restart_count)
            await asyncio.sleep(10)
            if not bot.is_monitoring:
                break
        _mm_restart_count += 1
        try:
          _last_pivot_day = datetime.utcnow().date()  # уже прогрет в start_monitoring
          _pivot_cycle = 0
          _cascade_4h_cycle = 0
          _div_cycle = 0

          # ARCH-78: принудительный warmup до первого цикла — чтобы gate не видел NEUTRAL
          _btc_prov_warmup = getattr(bot, "btc_regime_provider", None)
          if _btc_prov_warmup is not None:
              try:
                  await _btc_prov_warmup.update(bot.data_collector)
                  logger.info("[ARCH-78] BTCRegimeProvider warmup: mode=%s", _btc_prov_warmup.get_btc_mode())
              except Exception as _e_warmup:
                  logger.warning("[ARCH-78] BTCRegimeProvider warmup failed: %s", _e_warmup)

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

            # ARCH-78: BTCRegimeProvider — обновляем режим (провайдер сам следит за TTL 5 мин)
            _btc_prov = getattr(bot, "btc_regime_provider", None)
            if _btc_prov is not None:
                asyncio.create_task(_btc_prov.update(bot.data_collector))

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
            logger.exception("[monitor_market] D-053: crash в итерации #%d — перезапуск", _mm_restart_count)
