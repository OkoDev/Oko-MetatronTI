import logging
from core.indicators.indicators import detect_fvg, calculate_trend, calculate_wt, get_zone, compute_atr
from core.indicators.market_regime import MarketRegimeClassifier as _MRC
try:
    from core.smc.fvg import detect_fvg as _smc_detect_fvg
    from core.smc.confluence import find_fvg_pivot_confluences as _find_fvg_piv_conf
    _FVG_PIVOT_ENABLED = True
except ImportError:
    _smc_detect_fvg = None
    _find_fvg_piv_conf = None
    _FVG_PIVOT_ENABLED = False

logger = logging.getLogger(__name__)


async def check_pivot_level_signal(symbol, data_collector, pivot_calculator):
    """
    Проверяет сигналы ОТ УРОВНЕЙ недельных пивотов.

    Стратегия:
    1. Цена рядом с недельным уровнем (S1, S2, R1, R2, PP) ± 0.5%
    2. WT кросс на 15m в нужном направлении
    3. Тренд на 15m соответствует направлению
    4. БОНУС: FVG на 3m для усиления confidence
    5. SL: swing_low/high (primary, avgR=+0.846) → fallback pivot±0.3%
    6. TP: следующие пивоты (R1→R2→R3 для LONG, S1→S2→S3 для SHORT)

    Данные 15m берутся из кеша (уже загружены scan_one) — нет лишних API-вызовов.

    Returns:
        (True/False, dict с деталями сигнала)
    """
    try:
        # === 1. Недельные пивоты ===
        try:
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(symbol, data_collector)
        except TypeError:
            pivots_data = await pivot_calculator.get_multi_timeframe_pivots(data_collector, symbol)

        if '1W' not in pivots_data:
            return False, None

        weekly_pivots = pivots_data['1W']
        confluence = pivots_data.get('confluence', [])

        # === 2. 15m данные из кеша (загружены scan_one — нет API-запроса) ===
        df_15m = await data_collector.get_ohlcv(symbol, "15m", limit=150)
        if df_15m is None or len(df_15m) < 30:
            return False, None

        # Текущая цена = последняя закрытая свеча 15m (не нужен 1m)
        current_price = float(df_15m['close'].iloc[-1])
        if current_price <= 0:
            return False, None

        # === 3. Близость к уровню ===
        near_level = pivot_calculator.is_near_level(
            current_price, weekly_pivots, threshold_percent=0.5
        )
        if not near_level:
            prev_weekly = pivots_data.get('1W_prev')
            if prev_weekly:
                near_level = pivot_calculator.is_near_level(
                    current_price, prev_weekly, threshold_percent=0.5
                )
                if near_level:
                    near_level["is_prev_period"] = True
        if not near_level:
            return False, None

        level_type = near_level['level_type']
        level_name = near_level['level']
        level_price = near_level['price']

        # === 4. WT + Trend из одного df_15m (не нужен 5m) ===
        df_15m = calculate_wt(df_15m)
        from core.infra.config_loader import config as _cfg_pr
        df_15m = calculate_trend(df_15m,
                                 atr_period=int(_cfg_pr.get("analysis.indicators.trend.atr_period", 43)),
                                 factor=float(_cfg_pr.get("analysis.indicators.trend.factor", 1.0)))

        wt1_curr = float(df_15m['wt1'].iloc[-1])
        wt2_curr = float(df_15m['wt2'].iloc[-1])
        wt1_prev = float(df_15m['wt1'].iloc[-2])
        wt2_prev = float(df_15m['wt2'].iloc[-2])
        zone_15m = get_zone(wt1_curr)

        cross_up   = (wt1_prev < wt2_prev) and (wt1_curr > wt2_curr)
        cross_down = (wt1_prev > wt2_prev) and (wt1_curr < wt2_curr)

        trend_15m      = int(df_15m['trend'].iloc[-1])
        trend_15m_prev = int(df_15m['trend'].iloc[-2])
        trend_changed  = (trend_15m != trend_15m_prev)

        # ── Режим монеты для pivot gates (df_15m уже с trend+wt после шагов 4+) ──
        try:
            _regime = _MRC().classify_from_dataframes(df_15m) or "RANGE"
        except Exception:
            _regime = "RANGE"

        # === 5. ATR — только для fallback, не основной SL ===
        try:
            atr_series = compute_atr(df_15m, period=14)
            atr_val = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) > 0 else None
        except Exception:
            atr_val = None

        # DEV-30 (Вариант A): SL = 0.3% под/над уровнем пивота — fallback
        _pivot_buf = 0.003
        _sl_long_pivot  = level_price * (1 - _pivot_buf)
        _sl_short_pivot = level_price * (1 + _pivot_buf)

        # Swing SL (primary, 17.05.2026): структурный экстремум за последние 30 свечей 15m.
        # avgR(swing_high SL)=+0.846 n=41 vs pivot_buf. Fallback → pivot_buf если нет swing или слишком широкий.
        _swing_sl_long  = None
        _swing_sl_short = None
        try:
            if df_15m is not None and len(df_15m) >= 30:
                _wing = 4
                _rec30 = df_15m.iloc[-30:].reset_index(drop=True)
                _sw_lows, _sw_highs = [], []
                for _si in range(_wing, len(_rec30) - _wing):
                    _lo = float(_rec30["low"].iloc[_si])
                    _hi = float(_rec30["high"].iloc[_si])
                    if (_lo < _rec30["low"].iloc[_si - _wing: _si].min() and
                            _lo < _rec30["low"].iloc[_si + 1: _si + _wing + 1].min() and
                            _lo < current_price):
                        _sw_lows.append(_lo)
                    if (_hi > _rec30["high"].iloc[_si - _wing: _si].max() and
                            _hi > _rec30["high"].iloc[_si + 1: _si + _wing + 1].max() and
                            _hi > current_price):
                        _sw_highs.append(_hi)
                if _sw_lows:
                    _swing_sl_long  = float(min(_sw_lows))
                if _sw_highs:
                    _swing_sl_short = float(max(_sw_highs))
        except Exception:
            pass

        # fallback sl_dist для rr_ratio вычислений (всё ещё нужен в _build_result)
        if atr_val and atr_val > 0:
            sl_dist = max(min(atr_val * 1.5, current_price * 0.04), current_price * 0.01)
        else:
            sl_dist = current_price * 0.02

        # === 6. FVG на 3m — только бонус, не блокирует ===
        df_3m = await data_collector.get_ohlcv(symbol, "3m", limit=20)
        fvg_type = None
        fvg_entry = None
        has_fvg = False
        if df_3m is not None and len(df_3m) >= 3:
            try:
                fvg_type, fvg_entry = detect_fvg(df_3m)
                has_fvg = fvg_type is not None
            except Exception:
                pass

        # ── FVG+Pivot confluence (17.05.2026) ───────────────────────────────────
        # Shadow: пишем в features_json для аккумуляции данных; не блокирует.
        _fvg_pivot_zones = []
        if _FVG_PIVOT_ENABLED and df_3m is not None and len(df_3m) >= 3:
            try:
                _fvg_full = _smc_detect_fvg(df_3m)
                _piv_flat = {}
                for _tf in ("1W", "1D", "1M"):
                    _src = pivots_data.get(_tf, {})
                    if isinstance(_src, dict):
                        for _k, _v in _src.items():
                            if isinstance(_v, (int, float)) and _v > 0 and _k != "confluence":
                                _piv_flat[f"{_tf}_{_k}"] = _v
                if _piv_flat:
                    _fvg_pivot_zones = _find_fvg_piv_conf(
                        _fvg_full, _piv_flat, current_price, tolerance_pct=0.5
                    )
            except Exception:
                pass

        # DEV-188 (shadow): real_touch + volume_z для качества входа от уровня.
        # Не блокирует — пишет в info dict → features_json для shadow-анализа
        # после 50+ закрытых сделок: WR(real_touch=1) vs WR(0).
        try:
            recent_high_15m = float(df_15m["high"].iloc[-3:].max())
            recent_low_15m  = float(df_15m["low"].iloc[-3:].min())
            vol_last_15m    = float(df_15m["volume"].iloc[-1]) if "volume" in df_15m.columns else 0.0
            if "volume" in df_15m.columns and len(df_15m) >= 21:
                vol_avg_20_15m = float(df_15m["volume"].iloc[-21:-1].mean())
            else:
                vol_avg_20_15m = 0.0
            volume_z_15m = round(vol_last_15m / vol_avg_20_15m, 2) if vol_avg_20_15m > 0 else 0.0
        except Exception:
            recent_high_15m = recent_low_15m = 0.0
            volume_z_15m = 0.0

        # Soft penalty от режима — применяется внутри _build_result (closure)
        _regime_str_penalty = 0

        # === Вспомогательные функции ===
        def _strength(wt_ok, trend_changed, has_fvg, fvg_ok, has_confluence):
            s = 60
            if wt_ok:                  s += 10
            if trend_changed:          s += 10
            if has_fvg and fvg_ok:     s += 10
            if has_confluence:         s += 10
            return min(s, 100)

        def _build_result(type_str, direction_label, wt_label, trend_label,
                          stop_loss, tp_levels, has_confluence, sl_source_str='atr_14'):
            fvg_ok = (fvg_type == ("BULL" if "LONG" in type_str else "BEAR")) if has_fvg else True
            wt_ok = cross_up if "LONG" in type_str else cross_down
            actual_sl_dist = abs(current_price - stop_loss)
            tp_distance = abs(tp_levels[0]['price'] - current_price) if tp_levels else 0
            rr_ratio = tp_distance / actual_sl_dist if actual_sl_dist > 0 else 0
            strength = _strength(wt_ok, trend_changed, has_fvg, fvg_ok, has_confluence)
            strength = max(0, strength - _regime_str_penalty)  # мягкий режимный штраф
            # Бонус за FVG+Pivot конфлюэнцию (17.05)
            _has_fvg_piv_conf = bool(_fvg_pivot_zones and _fvg_pivot_zones[0].score >= 25)
            if _has_fvg_piv_conf:
                strength = min(strength + 8, 100)
            # DEV-188 (shadow): real_touch для weekly-pivot пути
            if "LONG" in type_str:
                _real_touch = 1 if recent_low_15m <= level_price * 1.001 else 0
                _close_rejection = 1 if current_price > level_price else 0
            else:
                _real_touch = 1 if recent_high_15m >= level_price * 0.999 else 0
                _close_rejection = 1 if current_price < level_price else 0
            return {
                'symbol': symbol,
                'type': type_str,
                'strategy': f'Вход от недельного {level_name}',
                'level': level_name,
                'level_type': level_type,
                'level_price': level_price,
                'current_price': current_price,
                'distance_to_level': near_level['distance_percent'],
                'wt_signal': f"WT кросс {direction_label} на 15m (WT1={wt1_curr:.1f})",
                'wt_zone': zone_15m,
                'trend_15m': trend_label,
                'trend_changed': trend_changed,
                'has_fvg': has_fvg and fvg_ok,
                'fvg_type': fvg_type,
                'fvg_entry': fvg_entry,
                'has_confluence': has_confluence,
                'confluence_info': [c for c in confluence if c['weekly_level'] == level_name],
                'entry_price': current_price,
                'stop_loss': stop_loss,
                'stop_distance_pct': actual_sl_dist / current_price * 100,
                'atr': atr_val,
                'sl_source': sl_source_str,
                'take_profits': tp_levels,
                'rr_ratio': rr_ratio,
                'strength': strength,
                'confidence': ('VERY_HIGH' if (
                    _has_fvg_piv_conf or (has_confluence and has_fvg and fvg_ok)
                ) else 'HIGH'),
                'weekly_pivots': weekly_pivots,
                'real_touch': _real_touch,
                'close_rejection': _close_rejection,
                'volume_z': volume_z_15m,
                'fvg_pivot_zones': [z.to_dict() for z in _fvg_pivot_zones[:3]],
                'has_fvg_pivot_conf': _has_fvg_piv_conf,
                'regime': _regime,
            }

        # === LONG: у поддержки ===
        if level_type in ['support', 'pivot']:
            # ── Regime soft penalties (17.05.2026, аудит 650 сделок post-v4) ────
            # Не hard block — рынок цикличен, текущие данные из медвежьей фазы.
            # Штраф к strength снижает шанс прохода min_strength в TradeRouter.
            if _regime == "TREND_UP":
                # avgR=-0.523 WR=12% за 9/9 недель — сильный штраф
                _regime_str_penalty = 25
                logger.debug("[PivotReversal] %s LONG+TREND_UP soft_penalty=%d", symbol, _regime_str_penalty)
            elif _regime == "RANGE" and current_price <= level_price:
                # RANGE без rejection: avgR=-0.272 vs -0.044 с rejection
                _regime_str_penalty = 15
                logger.debug("[PivotReversal] %s LONG+RANGE no_rejection soft_penalty=%d", symbol, _regime_str_penalty)
            wt_ok   = cross_up and zone_15m in ['OS', 'N']
            trend_ok = (trend_15m == 1)

            # Swing SL (primary) — не дальше 5% ниже уровня, иначе fallback
            if _swing_sl_long is not None and _swing_sl_long >= level_price * 0.95:
                _sl_long  = _swing_sl_long
                _sl_src_l = f'swing_low:{_swing_sl_long:.6g}'
            else:
                _sl_long  = _sl_long_pivot
                _sl_src_l = f'pivot_{level_name}:0.3%'

            if wt_ok and trend_ok:
                target_levels = ['PP', 'R1', 'R2', 'R3'] if 'S' in level_name else ['R1', 'R2', 'R3']
                tp_levels = [
                    {'level': t, 'price': weekly_pivots[t],
                     'profit_percent': (weekly_pivots[t] - current_price) / current_price * 100,
                     'timeframe': '1W'}
                    for t in target_levels
                    if t in weekly_pivots and weekly_pivots[t] > current_price
                ]
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                return True, _build_result(
                    'PIVOT_LEVEL_LONG', 'вверх', 'UP', 'вверх',
                    _sl_long, tp_levels, has_confluence,
                    sl_source_str=_sl_src_l
                )

        # === SHORT: у сопротивления ===
        elif level_type in ['resistance', 'pivot']:
            # Soft penalties для SHORT pivot_reversal (18.05.2026, n=3136 везде avgR < 0)
            if _regime == "TREND_DOWN" and current_price > weekly_pivots.get('PP', 0):
                # W_DOWN + D_above_PP: avgR=-1.584, n=375 — самый убыточный контекст
                _regime_str_penalty = 40
                logger.debug("[PivotReversal] %s SHORT+TREND_DOWN+above_PP soft_penalty=%d",
                             symbol, _regime_str_penalty)
            elif _regime in ("TREND_DOWN", "RANGE"):
                # SHORT в медвежьем/нейтральном рынке: avgR -0.17..-0.30
                _regime_str_penalty = 20
                logger.debug("[PivotReversal] %s SHORT+%s soft_penalty=%d",
                             symbol, _regime, _regime_str_penalty)
            wt_ok   = cross_down and zone_15m in ['OB', 'N']
            trend_ok = (trend_15m == -1)

            # Swing SL (primary) — не дальше 5% выше уровня, иначе fallback
            if _swing_sl_short is not None and _swing_sl_short <= level_price * 1.05:
                _sl_short  = _swing_sl_short
                _sl_src_s  = f'swing_high:{_swing_sl_short:.6g}'
            else:
                _sl_short  = _sl_short_pivot
                _sl_src_s  = f'pivot_{level_name}:0.3%'

            # DEV-188: wick должен реально достичь уровня (не только close-proximity)
            _real_touch_short = recent_high_15m >= level_price * 0.999
            if not _real_touch_short:
                logger.debug(
                    "[PivotReversal] %s SHORT SKIP no_real_touch: high=%.6g < level=%.6g",
                    symbol, recent_high_15m, level_price,
                )
                return False, None

            # DEV-188: низкий объём → дополнительный штраф
            if 0 < volume_z_15m < 0.8:
                _regime_str_penalty += 10

            if wt_ok and trend_ok:
                target_levels = ['PP', 'S1', 'S2', 'S3'] if 'R' in level_name else ['S1', 'S2', 'S3']
                tp_levels = [
                    {'level': t, 'price': weekly_pivots[t],
                     'profit_percent': (current_price - weekly_pivots[t]) / current_price * 100,
                     'timeframe': '1W'}
                    for t in target_levels
                    if t in weekly_pivots and weekly_pivots[t] < current_price
                ]
                has_confluence = any(c['weekly_level'] == level_name for c in confluence)
                return True, _build_result(
                    'PIVOT_LEVEL_SHORT', 'вниз', 'DOWN', 'вниз',
                    _sl_short, tp_levels, has_confluence,
                    sl_source_str=_sl_src_s
                )

        return False, None

    except Exception:
        logger.exception("Ошибка check_pivot_level_signal для %s", symbol)
        return False, None


def pivot_level_signal_message(symbol: str, info: dict) -> str:
    """Форматирует сообщение о входе от уровня."""
    from core.ui.message_builder import tv_link
    from datetime import datetime

    is_long = "LONG" in info.get("type", "")
    emoji = "🟢" if is_long else "🔴"

    confidence = info.get("confidence", "HIGH")
    conf_emoji = "🔥🔥🔥" if confidence == "VERY_HIGH" else "🔥🔥"
    strength = info.get("strength", 65)

    parts = [
        f"{emoji} <b>ВХОД ОТ НЕДЕЛЬНОГО УРОВНЯ</b> {emoji}",
        f"Пара: {tv_link(symbol, interval=3)}",
        f"Стратегия: <b>{info.get('strategy')}</b>",
        "",
        f"{conf_emoji} <b>Сила:</b> {strength}/100  <b>Уверенность:</b> {confidence}",
    ]

    level = info.get('level')
    level_price = info.get('level_price', 0)
    distance = info.get('distance_to_level', 0)

    parts.append("")
    parts.append(f"📊 <b>Уровень: {level}</b>")
    parts.append(f"Цена уровня: {level_price:.6f}")
    parts.append(f"Расстояние: {distance:.3f}%")

    parts.append("")
    parts.append("<b>✅ Подтверждения:</b>")
    parts.append(f"  • {info.get('wt_signal')} [{info.get('wt_zone')}]")

    trend_15m = info.get('trend_15m', '')
    if info.get('trend_changed'):
        parts.append(f"  • Разворот тренда 15m → {trend_15m}")
    else:
        parts.append(f"  • Тренд 15m: {trend_15m}")

    if info.get('has_fvg'):
        parts.append(f"  • 💎 FVG {info.get('fvg_type')} на 3m!")
        if info.get('fvg_entry'):
            parts.append(f"    Entry: {info.get('fvg_entry'):.6f}")

    if info.get('has_confluence'):
        conf = info.get('confluence_info', [])
        if conf:
            c = conf[0]
            parts.append(f"  • ⭐ КОНФЛЮЭНЦИЯ: 1W {c['weekly_level']} ≈ 1D {c['daily_level']}")

    parts.append("")
    parts.append("<b>🎯 Торговый план:</b>")

    entry = info.get('entry_price', 0)
    sl = info.get('stop_loss', 0)
    stop_pct = info.get('stop_distance_pct', 0)
    tp_levels = info.get('take_profits', [])
    rr = info.get('rr_ratio', 0)
    atr = info.get('atr')

    parts.append(f"📍 Вход: {entry:.6f}")
    atr_str = f"  ATR×1.5={atr * 1.5:.6f}" if atr else ""
    parts.append(f"🛡️ Стоп: {sl:.6f} ({stop_pct:.2f}%) [ATR×1.5]{atr_str}")

    for i, tp in enumerate(tp_levels[:3], 1):
        parts.append(f"🎯 TP{i}: {tp['price']:.6f} (+{tp['profit_percent']:.2f}%) [1W {tp['level']}]")

    if rr > 0:
        parts.append(f"⚖️ R:R = 1:{rr:.1f} {'🔥🔥🔥' if rr >= 5 else '🔥🔥' if rr >= 3 else '🔥'}")

    parts.append("")
    parts.append("<b>💡 Рекомендации:</b>")

    if confidence == "VERY_HIGH" and rr >= 5:
        parts.append("  • 🔥🔥🔥 ОТЛИЧНЫЙ SETUP!")
        parts.append("  • Уровень + WT + тренд + FVG + конфлюэнция")
        parts.append("  • R:R превосходный!")
    elif rr >= 3:
        parts.append("  • 🔥 Хороший setup от недельного уровня")
        parts.append("  • ATR-стоп, отличный R:R")
    else:
        parts.append("  • Сигнал от уровня")
        parts.append("  • Стандартный риск-менеджмент")

    parts.append("  • Частичная фиксация: 33%/33%/34%")
    parts.append("  • Стоп в безубыток после TP1")

    parts.append("")
    parts.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return "\n".join(parts)
