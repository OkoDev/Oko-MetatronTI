"""
DEV-190 (26.04.2026): Effective Status helper — single source of truth для
классификации исхода сделки с учётом B2 (status='SL' для VST скрывает TSL exits).

Контекст:
  Бот не размещает TRAILING_STOP_MARKET ордера на BingX. Когда симулятор двигает
  TSL и stop срабатывает — биржа возвращает type='STOP_MARKET'. position_sync
  пишет status='SL', хотя фактически это был TSL exit с прибылью.

  Из 369 VST с tsl_activated=1: 120 (32%) реально закрылись TSL'ом с R>0.
  Без этого helper'а вся аналитика, ML и дашборд считают эти сделки поражениями.

Используется во всех местах где нужна классификация TP/SL/TSL:
  - core/trading/performance_engine.py
  - core/ml/outcome_predictor.py / rl_exit_agent.py / mtf_*_specialist.py
  - core/intelligence/confidence_calibrator.py
  - web/dashboard_server.py

Откат: установить EFFECTIVE_STATUS_ENABLED=False в config:
    trading.effective_status_enabled: false
В этом случае effective_status() = status (raw, прежнее поведение).
"""
from __future__ import annotations
from typing import Optional, Mapping, Any


# Пороги для переклассификации SL → effective_status
TSL_HIDDEN_WIN_R_MIN = 0.10    # R > 0.1 при tsl_activated=1 + status='SL' = скрытый TSL exit
BE_AREA_R_LOW = -0.20          # -0.2 ≤ R ≤ +0.1 при tsl_act=1 + 'SL' = BE area (выбит на околобезубытке)
BE_AREA_R_HIGH = 0.10
# Чистый безубыток (be_activated=1 БЕЗ TSL): SL перенесён в entry±0.1% (DEV-40), выход по be_sl =
# нейтрал, net≈0 после комиссии. R-метка может быть >0.1 — это артефакт тугого SL (one_r мал),
# а не выигрыш (стоп не тянулся). Верх 0.35 шире TSL-BE: buffer 0.1% / sl_frac до ~0.3% → R≤~0.35;
# выше = fake-R фантом (R>MFE, см. bug_phantom_exit_resolve), не BE.
BE_AREA_BE_R_HIGH = 0.35
SL_SLIPPED_R = -1.05           # R < -1.05 = катастрофический slippage (DEV-185)


def effective_status(
    status: Optional[str],
    r_multiple: Optional[float],
    tsl_activated: Optional[int] = None,
    be_activated: Optional[int] = None,
) -> str:
    """
    Возвращает скорректированный статус сделки с учётом скрытых TSL exits и безубытка.

    Args:
        status: raw status из БД ('OPEN'|'TP'|'SL'|'TSL'|'EXPIRED'|'UNKNOWN'|None)
        r_multiple: R_multiple сделки (None для OPEN)
        tsl_activated: 1 если TSL активировался (стоп двигался), 0/None иначе
        be_activated: 1 если сработал безубыток (DEV-40, SL→entry±0.1%), 0/None иначе

    Returns:
        eff_status: один из:
            'OPEN'           — сделка открыта
            'TP'             — закрыта по TP
            'TSL_native'     — статус 'TSL' пришёл от симулятора (SIM сделки)
            'TSL_hidden_win' — status='SL' но R>0.1 + tsl_act=1 (VST скрытый TSL exit)
            'BE_area'        — нейтрал (net≈0): либо TSL выбит на BE (tsl_act=1, R∈[-0.2,+0.1]),
                               либо ЧИСТЫЙ безубыток (be_act=1 без TSL, R∈[-0.2,+0.35])
            'SL_slipped'     — status='SL' с R < -1.05 (catastrophic slippage)
            'SL_clean'       — status='SL' с R в [-1.05, -0.2] (чистый стоп)
            'EXPIRED'        — закрыта по таймауту
            'UNKNOWN'        — нет данных
            'OTHER'          — нераспознанный статус
    """
    if status is None or status == 'OPEN':
        return 'OPEN'
    if status == 'TP':
        return 'TP'
    if status == 'TSL':
        return 'TSL_native'
    if status == 'EXPIRED':
        return 'EXPIRED'
    if status == 'UNKNOWN':
        return 'UNKNOWN'
    if status == 'SL':
        r = r_multiple if r_multiple is not None else 0.0
        if tsl_activated and r > TSL_HIDDEN_WIN_R_MIN:
            return 'TSL_hidden_win'
        if tsl_activated and BE_AREA_R_LOW <= r <= BE_AREA_R_HIGH:
            return 'BE_area'
        # Чистый безубыток без TSL: выход по be_sl = нейтрал (net≈0), даже при R>0.1 (артефакт тугого SL)
        if be_activated and not tsl_activated and BE_AREA_R_LOW <= r <= BE_AREA_BE_R_HIGH:
            return 'BE_area'
        if r < SL_SLIPPED_R:
            return 'SL_slipped'
        return 'SL_clean'
    return 'OTHER'


def effective_status_from_row(row: Mapping[str, Any]) -> str:
    """Удобный wrapper: классификация из dict-like row БД."""
    return effective_status(
        status=row.get('status'),
        r_multiple=row.get('R_multiple'),
        tsl_activated=row.get('tsl_activated'),
        be_activated=row.get('be_activated'),
    )


# Категории для агрегаций
WIN_STATUSES = frozenset({'TP', 'TSL_native', 'TSL_hidden_win'})
LOSS_STATUSES = frozenset({'SL_clean', 'SL_slipped'})
NEUTRAL_STATUSES = frozenset({'BE_area', 'EXPIRED', 'UNKNOWN', 'OTHER'})
CLOSED_STATUSES = WIN_STATUSES | LOSS_STATUSES | NEUTRAL_STATUSES   # всё кроме OPEN


def is_win(status: Optional[str], r_multiple: Optional[float], tsl_activated: Optional[int] = None,
           be_activated: Optional[int] = None) -> bool:
    """ML-friendly: True для целевой переменной обучения 'выиграла ли сделка'.
    BE_area (включая чистый безубыток) — НЕ win (нейтрал, net≈0)."""
    return effective_status(status, r_multiple, tsl_activated, be_activated) in WIN_STATUSES


def is_win_from_row(row: Mapping[str, Any]) -> bool:
    return is_win(row.get('status'), row.get('R_multiple'), row.get('tsl_activated'), row.get('be_activated'))


def is_closed(status: Optional[str]) -> bool:
    return status not in (None, 'OPEN')


# SQL-fragment для CASE expression — для аналитики прямо в SQL без Python-loop
SQL_EFFECTIVE_STATUS_CASE = """
CASE
    WHEN status IS NULL OR status = 'OPEN' THEN 'OPEN'
    WHEN status = 'TP' THEN 'TP'
    WHEN status = 'TSL' THEN 'TSL_native'
    WHEN status = 'EXPIRED' THEN 'EXPIRED'
    WHEN status = 'UNKNOWN' THEN 'UNKNOWN'
    WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple > 0.10 THEN 'TSL_hidden_win'
    WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple BETWEEN -0.20 AND 0.10 THEN 'BE_area'
    WHEN status = 'SL' AND COALESCE(tsl_activated,0) = 0 AND be_activated = 1 AND R_multiple BETWEEN -0.20 AND 0.35 THEN 'BE_area'
    WHEN status = 'SL' AND R_multiple < -1.05 THEN 'SL_slipped'
    WHEN status = 'SL' THEN 'SL_clean'
    ELSE 'OTHER'
END
"""

SQL_IS_WIN_CASE = """
CASE
    WHEN status = 'TP' THEN 1
    WHEN status = 'TSL' THEN 1
    WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple > 0.10 THEN 1
    ELSE 0
END
"""

# SQL-fragment: 1 если сделка = BE_area (нейтрал, net≈0) → исключать из знаменателя win_rate
# (как EXPIRED). Покрывает TSL-выбитый-на-BE и чистый безубыток (be_activated без TSL).
SQL_IS_BE_NEUTRAL_CASE = """
CASE
    WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple BETWEEN -0.20 AND 0.10 THEN 1
    WHEN status = 'SL' AND COALESCE(tsl_activated,0) = 0 AND be_activated = 1 AND R_multiple BETWEEN -0.20 AND 0.35 THEN 1
    ELSE 0
END
"""
