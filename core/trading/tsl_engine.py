"""
tsl_engine.py — единая точка для всех вычислений TSL.

Консолидирует логику, ранее размазанную по:
  - core/trading/trade_simulator.py (floor, BE, side check, min_move)
  - core/exchange/tsl_updater.py (нет валидации перед place_sl_order)
  - core/intelligence/recommendation_generator.py (SL на входе = TSL-линия)
  - strategies/built_in/{reversal,confluence}_scanner_strategy.py (SL на входе)

Принципы:
  - Все функции pure — без I/O, без async, без БД.
  - Симметрия LONG/SHORT — никаких min() где должен быть max().
  - Явный тип direction: "LONG" | "SHORT".

Инциденты, которые движок предотвращает:
  - REAL #7264 (19.04.2026): SHORT TSL floor был min(tsl, entry+0.3%) вместо
    max(tsl, entry+0.3%) → SL записывался НИЖЕ entry, биржа отвергала ордер.
  - REPAIR-SL слал перевёрнутый SL на биржу (не было side-check).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

Direction = Literal["LONG", "SHORT"]

# ── Константы по умолчанию (берутся из config при интеграции) ────────────
DEFAULT_FLOOR_PCT = 0.003    # 0.3% — буфер чтобы wick не выбил позицию
DEFAULT_BE_BUFFER = 0.001    # 0.1% — смещение SL при breakeven
DEFAULT_MIN_MOVE_PCT = 0.15  # 0.15% — порог чтобы не слать cancel+replace


def _norm_direction(direction: str) -> Direction:
    d = (direction or "").upper()
    if d not in ("LONG", "SHORT"):
        raise ValueError(f"direction must be LONG|SHORT, got {direction!r}")
    return d  # type: ignore[return-value]


@dataclass(frozen=True)
class TSLDecision:
    """Результат расчёта TSL. new_sl=None — значит TSL не применим."""
    new_sl: Optional[float]
    triggered: bool          # текущая цена пересекла TSL → закрыть позицию
    floored: bool            # сработал ли floor guard
    side_valid: bool         # SL на правильной стороне от цены
    reason: str


# ═══════════════════════════════════════════════════════════════════════
# Pure helpers
# ═══════════════════════════════════════════════════════════════════════

def apply_floor(
    direction: str,
    entry: float,
    raw_sl: float,
    floor_pct: float = DEFAULT_FLOOR_PCT,
    current_price: Optional[float] = None,
) -> Tuple[float, bool]:
    """
    Гарантирует минимальный зазор между SL и reference — защита от wick.

    LONG:  floor = entry * (1 - floor_pct).  SL ≥ floor → max(raw_sl, floor).
           entry-based floor корректен: trendup в профите выше entry, max выбирает raw_tsl.
    SHORT: floor = current_price * (1 + floor_pct)  [DEV-191 fix].
           current_price-based критичен: trenddown в большом профите ниже entry,
           entry-based floor застревал у entry → TSL не следовал за ценой.
           Если current_price не передан — fallback на entry (обратная совместимость).

    Важно: для SHORT тоже max(), не min(). Исторически здесь был min() → REAL #7264.

    Returns: (sl_after_floor, was_floored)
    """
    d = _norm_direction(direction)
    if d == "LONG":
        floor = entry * (1 - floor_pct)
    else:  # SHORT — DEV-191: floor от current_price, не от entry
        ref = current_price if (current_price is not None and current_price > 0) else entry
        floor = ref * (1 + floor_pct)
    result = max(raw_sl, floor)
    return result, result != raw_sl


def breakeven_sl(
    direction: str,
    entry: float,
    buffer_pct: float = DEFAULT_BE_BUFFER,
) -> float:
    """
    SL на breakeven с микро-буфером.

    LONG:  entry * (1 + buffer_pct)  — чуть выше entry, фиксирует +buffer%
    SHORT: entry * (1 - buffer_pct)  — чуть ниже entry, фиксирует +buffer%
    """
    d = _norm_direction(direction)
    return entry * (1 + buffer_pct) if d == "LONG" else entry * (1 - buffer_pct)


def is_side_valid(direction: str, sl: float, reference_price: float) -> bool:
    """
    Проверка что SL на корректной стороне от цены.

    LONG:  sl < reference_price (SL ниже цены — иначе мгновенный hit)
    SHORT: sl > reference_price (SL выше цены — иначе мгновенный hit)

    Используется перед place_sl_order чтобы не слать перевёрнутый SL на биржу.
    """
    d = _norm_direction(direction)
    if sl is None or sl <= 0 or reference_price is None or reference_price <= 0:
        return False
    return sl < reference_price if d == "LONG" else sl > reference_price


def is_tsl_triggered(direction: str, current_price: float, sl: float) -> bool:
    """TSL сработал когда цена пересекла SL."""
    d = _norm_direction(direction)
    return current_price <= sl if d == "LONG" else current_price >= sl


def is_tighter(direction: str, candidate_sl: float, current_sl: float) -> bool:
    """
    TSL candidate ТЕСНЕЕ текущего (ближе к цене, крепче защищает прибыль).

    LONG:  SL ниже цены. Тесней = ВЫШЕ (ближе к цене снизу). → candidate > current
    SHORT: SL выше цены. Тесней = НИЖЕ (ближе к цене сверху). → candidate < current
    """
    d = _norm_direction(direction)
    return candidate_sl > current_sl if d == "LONG" else candidate_sl < current_sl


def should_update(
    old_sl: float,
    new_sl: float,
    min_move_pct: float = DEFAULT_MIN_MOVE_PCT,
) -> bool:
    """Фильтр мелких движений — не слать cancel+replace если SL не двинулся ≥ min_move_pct."""
    if not old_sl or old_sl <= 0 or new_sl is None:
        return False
    move_pct = abs(new_sl - old_sl) / old_sl * 100
    return move_pct >= min_move_pct


# ═══════════════════════════════════════════════════════════════════════
# Главная функция: единая точка вычисления TSL
# ═══════════════════════════════════════════════════════════════════════

def compute_tsl(
    direction: str,
    entry: float,
    current_price: float,
    raw_tsl: Optional[float],
    floor_pct: float = DEFAULT_FLOOR_PCT,
) -> TSLDecision:
    """
    Вычисляет TSL из сырого значения (trend_info["tsl"]).

    Args:
        direction: LONG | SHORT
        entry: цена входа в сделку
        current_price: текущая рыночная цена
        raw_tsl: значение из indicators.get_trend_info()["tsl"]
                 (для LONG = trendup, для SHORT = trenddown)
        floor_pct: минимальный зазор SL↔entry (по умолчанию 0.3%)

    Returns: TSLDecision. new_sl=None → TSL не применим (нет raw_tsl).
    """
    d = _norm_direction(direction)
    if raw_tsl is None or raw_tsl <= 0:
        return TSLDecision(
            new_sl=None, triggered=False, floored=False,
            side_valid=False, reason="no_raw_tsl",
        )

    new_sl, floored = apply_floor(d, entry, raw_tsl, floor_pct, current_price=current_price)
    side_valid = is_side_valid(d, new_sl, current_price)
    triggered = is_tsl_triggered(d, current_price, new_sl)

    if not side_valid:
        # SL оказался не на своей стороне — это значит цена УЖЕ прошла SL.
        # triggered=True выше уже это отражает.
        reason = "tsl_triggered_wrong_side"
    elif floored:
        reason = "floor_applied"
    else:
        reason = "ok"

    return TSLDecision(
        new_sl=new_sl, triggered=triggered, floored=floored,
        side_valid=side_valid, reason=reason,
    )


# ═══════════════════════════════════════════════════════════════════════
# SL при входе в сделку (используется стратегиями)
# ═══════════════════════════════════════════════════════════════════════

def get_entry_sl(
    direction: str,
    entry: float,
    tsl_line: Optional[float],
    buffer_pct: float = 0.001,
    fallback_pct: float = 0.015,
) -> Tuple[float, str]:
    """
    Вычисляет SL при входе в сделку.

    Приоритет:
      1. TSL-линия (tsl_trendup для LONG, tsl_trenddown для SHORT) с buffer_pct
         запасом от неё в сторону цены.
      2. Fallback: entry ± fallback_pct (обычно ATR-based или фиксированный %).

    Контракт: для LONG возвращает SL НИЖЕ entry, для SHORT ВЫШЕ entry.
    При неподходящем tsl_line (на неверной стороне) — сразу fallback.

    Returns: (sl, source)  source: "tsl_line" | "fallback_pct"
    """
    d = _norm_direction(direction)

    if tsl_line is not None and tsl_line > 0:
        if d == "LONG" and tsl_line < entry:
            # TSL-линия ниже entry — валидный SL для LONG.
            return tsl_line * (1 - buffer_pct), "tsl_line"
        if d == "SHORT" and tsl_line > entry:
            # TSL-линия выше entry — валидный SL для SHORT.
            return tsl_line * (1 + buffer_pct), "tsl_line"

    # Fallback — процентный отступ от entry.
    if d == "LONG":
        return entry * (1 - fallback_pct), "fallback_pct"
    return entry * (1 + fallback_pct), "fallback_pct"


# ═══════════════════════════════════════════════════════════════════════
# Re-export каскадных gate-функций из core/trading/cascade_tsl.py
# ═══════════════════════════════════════════════════════════════════════
# Каскадный TSL (эскалация 15m→1h→4h и де-эскалация) требует I/O — не вписывается
# в pure-engine. Но gate-функции (без I/O) реэкспортируются здесь чтобы весь TSL
# был в одной точке: `from core.trading.tsl_engine import check_r_gradient_drop`.
from core.trading.cascade_tsl import (  # noqa: E402
    check_r_gradient_drop,
    get_cascade_cap_tf,
    should_skip_degradation,
)

__all__ = [
    "TSLDecision",
    "DEFAULT_BE_BUFFER",
    "DEFAULT_FLOOR_PCT",
    "DEFAULT_MIN_MOVE_PCT",
    "apply_floor",
    "breakeven_sl",
    "check_r_gradient_drop",
    "compute_tsl",
    "compute_hybrid_tsl",
    "get_cascade_cap_tf",
    "get_entry_sl",
    "is_side_valid",
    "is_tighter",
    "is_tsl_triggered",
    "should_skip_degradation",
    "should_update",
]


# ═══════════════════════════════════════════════════════════════════════
# DS-321: Гибридный TSL — коробка передач (v1/v2/v3)
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TSLProfile:
    """Per-strategy Gear-пороги для hybrid TSL (TSL-PROFILE, 08.06.2026).

    Рой 5-6/6: движок универсален, Gear-параметры задаёт СТРАТЕГИЯ.
    DS добавляет profile param, Claude задаёт OTE-профиль.

    Дефолт = текущие значения (DS-321 backtest +1.95R).
    """
    gear1_be_atr: float = 1.0  # MFE >= N ATR → активировать BE (breakeven)
    gear2_atr: float = 2.0     # MFE >= N ATR → Gear 2 (wide)
    gear3_atr: float = 4.0     # MFE >= N ATR → Gear 3 (tight lock)
    gear3_hours: float = 12.0  # или > N часов → Gear 3

# ── Профили стратегий ──
TSL_PROFILES: dict = {
    # Дефолт (arch104, wt_signal, pivot_reversal, etc.)
    "default": TSLProfile(gear2_atr=2.0, gear3_atr=4.0, gear3_hours=12.0),
    # OTE long-runner: дышит дольше (target 8-22R)
    "ote_nested": TSLProfile(gear1_be_atr=1.5, gear2_atr=3.0, gear3_atr=8.0, gear3_hours=24.0),
    # wt_sideways: средний горизонт
    "wt_sideways": TSLProfile(gear2_atr=2.5, gear3_atr=5.0, gear3_hours=16.0),
}


def compute_hybrid_tsl(
    direction: str,
    entry: float,
    current_price: float,
    original_sl: float,
    duration_minutes: float = 0.0,
    mfe_atr: Optional[float] = None,
    floor_pct: float = DEFAULT_FLOOR_PCT,
    profile: Optional[TSLProfile] = None,
) -> TSLDecision:
    """
    Гибридная коробка передач TSL (DS-321 + TSL-PROFILE).

    Переключается между режимами по ходу сделки:
      Gear 1 (protect): MFE < gear2_atr — защита, BE при 1 ATR
      Gear 2 (wide):    MFE >= gear2_atr — расширение, дать дышать
      Gear 3 (lock):    MFE >= gear3_atr или >gear3_hours — фиксация

    Args:
        direction: LONG или SHORT
        entry: цена входа
        current_price: текущая цена
        original_sl: исходный SL
        duration_minutes: сколько минут в сделке
        mfe_atr: MFE в ATR (если None — вычисляется из current_price)
        floor_pct: буфер для floor guard
        profile: per-strategy профиль (дефолт = TSLProfile())
    """
    if profile is None:
        profile = TSL_PROFILES["default"]

    d = _norm_direction(direction)
    sl_dist = abs(entry - original_sl)
    if sl_dist <= 0:
        return TSLDecision(new_sl=None, triggered=False, floored=False,
                          side_valid=False, reason="no_sl_dist")

    # Оценка ATR из SL (SL ≈ 1.5 ATR)
    entry_atr = sl_dist / 1.5

    # MFE в ATR
    if mfe_atr is None:
        if d == "LONG":
            mfe_atr = (current_price - entry) / entry_atr
        else:
            mfe_atr = (entry - current_price) / entry_atr

    # ── Gear selection (per-profile thresholds) ──
    if mfe_atr >= profile.gear3_atr or duration_minutes > profile.gear3_hours * 60:
        gear = 3  # tight — фиксация
    elif mfe_atr >= profile.gear2_atr:
        gear = 2  # wide — дать дышать
    else:
        gear = 1  # protect — защита

    # ── BE ──
    be_price = breakeven_sl(direction, entry)
    new_sl = original_sl

    if mfe_atr >= profile.gear1_be_atr:
        if d == "LONG":
            new_sl = max(new_sl, be_price)
        else:
            new_sl = min(new_sl, be_price)

    # ── TSL distance per gear ──
    if mfe_atr > 0.5:
        if gear == 1:
            tsl_atr_dist = max(0.3, 0.8 - mfe_atr * 0.15)
            tsl_atr = entry_atr
        elif gear == 2:
            htf_atr_est = entry_atr * 1.5
            effective_atr = max(entry_atr, htf_atr_est * 0.3)
            tsl_atr_dist = max(0.4, 1.0 - mfe_atr * 0.2) * 1.5
            tsl_atr = effective_atr
        else:  # gear == 3
            tsl_atr_dist = max(0.1, 0.3 - (mfe_atr - profile.gear3_atr) * 0.03)
            tsl_atr = entry_atr

        tsl_distance = tsl_atr_dist * tsl_atr

        if d == "LONG":
            tsl_level = max(entry, current_price - tsl_distance)
            new_sl = max(new_sl, tsl_level)
        else:
            tsl_level = min(entry, current_price + tsl_distance)
            new_sl = min(new_sl, tsl_level)

    # ── Floor guard ──
    new_sl, was_floored = apply_floor(direction, entry, new_sl, floor_pct, current_price)

    # ── Trigger check ──
    triggered = is_tsl_triggered(direction, current_price, new_sl)

    # ── Side validity ──
    side_ok = is_side_valid(direction, new_sl, current_price)

    return TSLDecision(
        new_sl=new_sl,
        triggered=triggered,
        floored=was_floored,
        side_valid=side_ok,
        reason=f"hybrid_gear{gear}_mfe{mfe_atr:.1f}atr",
    )
