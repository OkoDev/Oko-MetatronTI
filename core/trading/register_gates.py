# -*- coding: utf-8 -*-
"""core.trading.register_gates — HARD-рубеж регистрации (EXEC-SIM-SPLIT шаг 7, 13.07).

ВТОРОЙ рубеж обороны (не дубль!): первый — SOFT-пайплайн trade_router/gates/* (penalty,
Сфера 9 «логика без блоков»). Данные 7 дней: router блокирует 99% (dedup 27.5K, strength
3.3K...), этот слой ловит остаток ~316 (DEV-44 HIGH_VOL ~260, corr ~29, гонки dedup) —
то, что penalty не остановил. Оба рубежа НАМЕРЕННЫ (defense-in-depth).

Вынесено из register_trade_async (монолит; фасад неизменен). Перенос 1:1 (13.07).
Каждый гейт: (…) → Optional[str] — причина блока (лог внутри) или None (пропуск).
Порядок вызова в register: time/stress/corr → [вычисление regime] → regime_safety/
min_strength/pivot_strength/portfolio_l3.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _rv(recommendation, key):
    from core.trading.trade_simulator import _get_recommendation_value
    return _get_recommendation_value(recommendation, key)


def _dirs(v) -> str:
    from core.trading.trade_simulator import _direction_str
    return _direction_str(v)


def gate_time_of_day(recommendation) -> Optional[str]:
    """DEV-170: Time-of-day gate — блок входов вне торговых сессий.
    09:00–18:00 UTC = avgR+, 23:00–06:00 UTC = avgR−0.3; per-signal overrides."""
    try:
        from core.infra.config_loader import config as _cfg_170
        if _cfg_170:
            _tg = (_cfg_170.get("signal_quality") or {}).get("time_gate") or {}
            if _tg.get("enabled", False):
                _hour_utc = datetime.now(timezone.utc).hour
                _sig_170 = str(_rv(recommendation, "signal_type") or "")
                _overrides = _tg.get("overrides") or {}
                _tg_sig = _overrides.get(_sig_170) or {}
                _start_h = int(_tg_sig.get("start_hour_utc", _tg.get("start_hour_utc", 9)))
                _end_h = int(_tg_sig.get("end_hour_utc", _tg.get("end_hour_utc", 18)))
                if not (_start_h <= _hour_utc < _end_h):
                    _sym_170 = _rv(recommendation, "symbol") or ""
                    logger.info("[DEV-170] %s БЛОК time_gate(%s): hour=%d вне [%d, %d) UTC",
                                _sym_170, _sig_170 or "default", _hour_utc, _start_h, _end_h)
                    return "DEV-170:time_gate"
    except Exception as _e170:
        logger.debug("[DEV-170] time_gate error: %s", _e170)
    return None


def gate_market_stress(sim, recommendation) -> Optional[str]:
    """ARCH-42: Market Stress — блок входов при массовых SL (окно sim._sl_timestamps)."""
    try:
        from core.infra.config_loader import config as _cfg_msg
        _msg = (_cfg_msg.get("trading", {}) or {}).get("market_stress_gate", {}) if _cfg_msg else {}
        if _msg:
            _threshold = int(_msg.get("sl_threshold", 5))
            _window_min = int(_msg.get("window_minutes", 30))
            _now_msg = datetime.now(timezone.utc)
            _window_start_msg = _now_msg - timedelta(minutes=_window_min)
            _recent_sl = [t for t in sim._sl_timestamps if t >= _window_start_msg]
            if len(_recent_sl) >= _threshold:
                _sym_msg = _rv(recommendation, "symbol") or ""
                if _msg.get("enabled"):
                    logger.info("[ARCH-42] %s БЛОК market_stress: %d SL за %d мин",
                                _sym_msg, len(_recent_sl), _window_min)
                    return "ARCH-42:market_stress"
                else:
                    logger.info("[ARCH-42] shadow %s: %d SL за %d мин (gate disabled)",
                                _sym_msg, len(_recent_sl), _window_min)
    except Exception as _e_msg:
        logger.debug("[ARCH-42] stress gate error: %s", _e_msg)
    return None


def gate_correlation(sim, recommendation) -> Optional[str]:
    """DEV-38: Correlation Guard — блок если по коррелированному активу уже открыта сделка."""
    try:
        from core.infra.config_loader import config as _cfg_cg38
        _corr_groups = (_cfg_cg38.get("trading", {}).get("correlation_groups", [])
                        if _cfg_cg38 else [])
        if _corr_groups:
            _new_sym = _rv(recommendation, "symbol") or ""
            _new_base = _new_sym.split("/")[0]
            _open_bases = {t["symbol"].split("/")[0] for t in sim.get_open_trades()}
            for _group in _corr_groups:
                if _new_base in _group:
                    _conflict = _open_bases & set(_group) - {_new_base}
                    if _conflict:
                        logger.info(
                            "[DEV-38] Correlation Guard: блок %s — уже открыта %s из той же группы",
                            _new_sym, _conflict,
                        )
                        return "DEV-38:correlation_guard"
    except Exception as _e:
        logger.debug("[DEV-38] Correlation Guard error: %s", _e)
    return None


def gate_regime_safety(recommendation, regime: Optional[str],
                       extra_features: Optional[dict]) -> Optional[str]:
    """DEV-44 (+64B/133): Safety gate — второй рубеж по свежевычисленному regime.
    Живее всех живых: ~260 блоков HIGH_VOL за 7 дней (router-версия SOFT не останавливает)."""
    if not regime:
        return None
    try:
        from core.infra.config_loader import config as _cfg_44
        if _cfg_44:
            _sym_44 = _rv(recommendation, "symbol") or ""
            _dir_44 = _dirs(_rv(recommendation, "direction"))
            _sig_type_44 = str(_rv(recommendation, "signal_type") or "")
            # fallback на signal_type_override (TradingRecommendation не имеет signal_type)
            if extra_features and extra_features.get("signal_type_override"):
                _sig_type_44 = str(extra_features["signal_type_override"])
            # Guard 1: blocked_regimes (DEV-33 fallback)
            _br_exceptions = _cfg_44.get("trading.blocked_regimes_exceptions") or []
            if regime in (_cfg_44.get("trading.blocked_regimes") or []) and _sig_type_44 not in _br_exceptions:
                logger.info("[DEV-44] %s БЛОК blocked_regime: %s", _sym_44, regime)
                return f"DEV-44:blocked_regime:{regime}"
            # Guard 2: regime_direction_block (DEV-32 fallback)
            _rdb = _cfg_44.get("trading.regime_direction_block") or {}
            if _rdb.get("enabled") and _rdb.get(regime) == _dir_44:
                logger.info("[DEV-44] %s БЛОК regime_direction: %s/%s", _sym_44, regime, _dir_44)
                return f"DEV-44:regime_direction:{regime}/{_dir_44}"
            # Guard 3: signal_regime_block (DEV-64B) — мёртвые signal_type × regime комбинации
            _srb = _cfg_44.get("signal_quality.signal_regime_block") or {}
            if _srb:
                _srb_sig = _srb.get(_sig_type_44) or {}
                if regime in (_srb_sig.get("blocked_regimes") or []):
                    logger.info("[DEV-64B] %s БЛОК signal_regime_block: %s/%s",
                                _sym_44, _sig_type_44, regime)
                    return f"DEV-64B:signal_regime_block:{_sig_type_44}/{regime}"
                # Guard 3B: blocked_combos (DEV-133) — direction × regime, хирургические
                for _combo in (_srb_sig.get("blocked_combos") or []):
                    if regime == _combo.get("regime") and _dir_44 == _combo.get("direction"):
                        logger.info("[DEV-133] %s БЛОК combo: %s/%s/%s",
                                    _sym_44, _sig_type_44, _dir_44, regime)
                        return f"DEV-133:blocked_combo:{_sig_type_44}/{_dir_44}/{regime}"
    except Exception as _e44:
        logger.debug("[DEV-44] Safety gate error: %s", _e44)
    return None


def gate_min_strength_regime(recommendation, regime: Optional[str], symbol: str,
                             extra_features: Optional[dict]) -> Optional[str]:
    """DEV-155: min_strength по режиму/направлению (HIGH_VOL=85...); atr_change — свой порог."""
    if not regime:
        return None
    try:
        from core.infra.config_loader import config as _cfg_155
        if _cfg_155:
            _str155 = int(_rv(recommendation, "overall_strength") or
                          getattr(recommendation, "overall_strength", 0) or 0)
            _sym155 = _rv(recommendation, "symbol") or symbol
            _dir155 = _dirs(_rv(recommendation, "direction"))
            _sig_type_155 = str(_rv(recommendation, "signal_type") or "")
            if extra_features and extra_features.get("signal_type_override"):
                _sig_type_155 = str(extra_features["signal_type_override"])
            _dir_regime_key = f"{_dir155}_{regime}"
            _by_dir_regime = (_cfg_155.get("signal_quality.min_strength_by_direction_regime") or {})
            _by_regime = (_cfg_155.get("signal_quality.min_strength_by_regime") or {})
            if _sig_type_155 == "atr_change":
                _base_min = int(_cfg_155.get("signal_quality.min_strength_atr_change", 15))
            else:
                _base_min = int(_cfg_155.get("signal_quality.min_strength_register", 50))
            _eff_min = _by_dir_regime.get(_dir_regime_key, _by_regime.get(regime, _base_min))
            if _str155 < _eff_min:
                logger.info("[DEV-155] %s БЛОК %s/%s/%s strength=%d < %d",
                            _sym155, _dir155, regime, _sig_type_155 or "?", _str155, _eff_min)
                return f"DEV-155:min_strength:{regime}/{_dir155}:{_str155}<{_eff_min}"
    except Exception as _e155:
        logger.debug("[DEV-155] gate error: %s", _e155)
    return None


def gate_pivot_reversal_strength(recommendation, symbol: str) -> Optional[str]:
    """DEV-98: pivot_reversal strength≥порога → skip (WR=4.5% при strength≥80)."""
    try:
        from core.infra.config_loader import config as _cfg_98
        if _cfg_98:
            _pms = int(_cfg_98.get("signal_quality.pivot_reversal_max_strength", 100))
            _sig98 = str(_rv(recommendation, "signal_type") or "")
            _str98 = int(_rv(recommendation, "overall_strength") or
                         getattr(recommendation, "overall_strength", 0) or 0)
            if _sig98 == "pivot_reversal" and _pms < 100 and _str98 >= _pms:
                _sym98 = _rv(recommendation, "symbol") or symbol
                logger.info("[DEV-98] %s БЛОК pivot_reversal strength=%d >= %d", _sym98, _str98, _pms)
                return f"DEV-98:pivot_reversal_strength:{_str98}>={_pms}"
    except Exception as _e98:
        logger.debug("[DEV-98] gate error: %s", _e98)
    return None


def gate_portfolio_l3(sim, recommendation, symbol: str) -> Optional[str]:
    """DEV-52: L3 портфельные лимиты + риск-экспозиция per-account + margin pre-check.
    SIM-тени НЕ занимают слоты (EXEC-SIM-SPLIT «SIM=снятие лимитов»); equity/available —
    из balance_snapshots (единый источник истины). Shadow-режимы логируют would_block."""
    try:
        from core.infra.config_loader import config as _cfg_52
        _l3 = (_cfg_52.get("trading", {}) or {}).get("l3_checker", {}) if _cfg_52 else {}
        if not _l3:
            return None
        _max_long = _l3.get("max_open_long", 2)
        _max_short = _l3.get("max_open_short", 2)
        _max_total = _l3.get("max_open_total", 4)
        _dir_52 = _dirs(_rv(recommendation, "direction"))
        _sym_52 = _rv(recommendation, "symbol") or symbol
        _open_52 = [t for t in sim.get_open_trades()
                    if str(t.get("execution_mode") or "").upper() != "SIM"]
        _n_long = sum(1 for t in _open_52 if t.get("direction") == "LONG")
        _n_short = sum(1 for t in _open_52 if t.get("direction") == "SHORT")
        _n_total = len(_open_52)
        _blocked_52 = None
        if _dir_52 == "LONG" and _n_long >= _max_long:
            _blocked_52 = f"LONG {_n_long}/{_max_long}"
        elif _dir_52 == "SHORT" and _n_short >= _max_short:
            _blocked_52 = f"SHORT {_n_short}/{_max_short}"
        elif _n_total >= _max_total:
            _blocked_52 = f"TOTAL {_n_total}/{_max_total}"
        if _blocked_52:
            if _l3.get("enabled"):
                logger.info("[DEV-52] %s: портфельный лимит %s", _sym_52, _blocked_52)
                return f"DEV-52:portfolio_limit:{_blocked_52}"
            else:
                logger.info("[DEV-52] shadow %s: портфельный лимит %s (gate disabled)",
                            _sym_52, _blocked_52)

        # ── Кирпичи №1/№2: риск-экспозиция per-account + margin pre-check ──
        _max_risk_pct = _l3.get("max_total_risk_pct")
        _min_avail = _l3.get("min_available_usdt")
        if _max_risk_pct or _min_avail:
            _trd_52 = _cfg_52.get("trading", {}) or {}
            _risk_pct_52 = float(_trd_52.get("risk_pct", 1.0))
            _acc_52 = 1
            _snap52 = None
            try:
                with sim._db_connect() as _cacc52:
                    _rr52 = _cacc52.execute(
                        "SELECT account_id FROM account_routing WHERE symbol=? LIMIT 1",
                        (_sym_52,),
                    ).fetchone()
                    if _rr52 and _rr52[0]:
                        _acc_52 = int(_rr52[0])
                    _snap52 = _cacc52.execute(
                        "SELECT equity, available FROM balance_snapshots WHERE account_id=? "
                        "ORDER BY timestamp DESC LIMIT 1", (_acc_52,),
                    ).fetchone()
            except Exception as _eacc52:
                logger.debug("[DEV-52] acc/balance lookup err: %s", _eacc52)
            _equity_52 = float(_snap52[0]) if (_snap52 and _snap52[0]) else 0.0
            if _equity_52 <= 0:  # нет снапшота → config-номинал (fallback)
                _equity_52 = float(_trd_52.get("deposit_usdt", 1000.0)) or 1000.0
            _avail_52 = float(_snap52[1]) if (_snap52 and _snap52[1] is not None) else None

            # Кирпич №1: риск-экспозиция по стопам (% equity per-account)
            if _max_risk_pct:
                _cur_risk_usdt = 0.0
                for _t52 in _open_52:
                    if _t52.get("execution_mode") != "VST":
                        continue  # только реальный капитал; sim депозит не трогает
                    if int(_t52.get("account_id") or 1) != _acc_52:
                        continue  # риск в РАМКАХ аккаунта новой сделки
                    _q52 = _t52.get("qty"); _e52e = _t52.get("entry_price"); _sl52 = _t52.get("stop_loss")
                    if _q52 and _e52e and _sl52:
                        _cur_risk_usdt += float(_q52) * abs(float(_e52e) - float(_sl52))
                _cur_risk_pct = _cur_risk_usdt / _equity_52 * 100.0
                _proj_risk_pct = _cur_risk_pct + _risk_pct_52
                _risk_shadow = _l3.get("risk_gate_shadow", True)
                if _proj_risk_pct > float(_max_risk_pct):
                    _rb52 = (f"acc{_acc_52} {_cur_risk_pct:.1f}%+{_risk_pct_52:.1f}%="
                             f"{_proj_risk_pct:.1f}% > {_max_risk_pct}% (eq={_equity_52:.0f})")
                    if _l3.get("enabled") and not _risk_shadow:
                        logger.info("[DEV-52][RISK] %s БЛОК риск-экспозиция %s", _sym_52, _rb52)
                        return f"DEV-52:risk_exposure:{_rb52}"
                    else:
                        logger.info("[DEV-52][RISK] shadow %s would_block %s", _sym_52, _rb52)
                else:
                    logger.info("[DEV-52][RISK] %s acc%d exposure=%.1f%% (+new %.1f%% → %.1f%%, cap %s%%, eq=%.0f)",
                                _sym_52, _acc_52, _cur_risk_pct, _risk_pct_52, _proj_risk_pct,
                                _max_risk_pct, _equity_52)

            # Кирпич №2: margin pre-check (доступная маржа per-account)
            if _min_avail and _avail_52 is not None:
                _margin_shadow = _l3.get("margin_gate_shadow", True)
                if _avail_52 < float(_min_avail):
                    _mb52 = f"acc{_acc_52} avail={_avail_52:.1f} < {_min_avail} USDT (eq={_equity_52:.0f})"
                    if _l3.get("enabled") and not _margin_shadow:
                        logger.info("[DEV-52][MARGIN] %s БЛОК низкая маржа %s", _sym_52, _mb52)
                        return f"DEV-52:low_margin:{_mb52}"
                    else:
                        logger.info("[DEV-52][MARGIN] shadow %s would_block %s", _sym_52, _mb52)
                else:
                    logger.info("[DEV-52][MARGIN] %s acc%d available=%.1f USDT (min %s, eq=%.0f)",
                                _sym_52, _acc_52, _avail_52, _min_avail, _equity_52)
    except Exception as _e52:
        logger.debug("[DEV-52] portfolio gate error: %s", _e52)
    return None
