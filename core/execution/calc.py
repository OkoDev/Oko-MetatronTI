"""core.execution.calc — ExecutionCalc: чистые функции исполнения (ОДИН калькулятор).

Дизайн: docs/EXECUTION_SPHERE_DESIGN.md §4. Принцип [[principle_reuse_not_duplication]]:
sizing и R-математика УЖЕ централизованы — переиспользуем, НЕ дублируем:
  - sizing  → core.trading.position_sizer.PositionSizer.calc_qty
  - R-math  → core.trading.r_math (compute_one_r / compute_r / clamp_r_smart)

Здесь СОБИРАЕМ то, что сейчас размазано инлайном в order_manager.open_bracket:403-487:
  - guards входа (min_sl_dist / sl_direction / min_notional)
  - leverage-клампы (кламп к max пары + SL-safety кап «ликвидация дальше SL»)

Функции чистые (без сайд-эффектов/IO) → parity-тест ловит дрейф формулы.
Различие SIM↔VST в ExecutionCalc НЕТ — один и тот же расчёт (различие = «трогаем ли биржу»,
это решает ExecutionSphere.open, а не calc).
"""
from __future__ import annotations

from typing import Optional

# Reuse — единственные источники sizing / R-math (НЕ копировать формулы сюда)
from core.trading.position_sizer import PositionSizer, MIN_NOTIONAL_USDT
from core.trading.r_math import compute_one_r, compute_r, clamp_r_smart  # noqa: F401 (re-export)

# Значения по умолчанию = текущие конфиг-дефолты order_manager.open_bracket / PositionSizer.
DEFAULT_MIN_SL_DIST_PCT = 0.1      # trading.min_sl_dist_pct (open_bracket:409)
DEFAULT_MIN_NOTIONAL = MIN_NOTIONAL_USDT
DEFAULT_LIQ_BUFFER_PCT = 1.5       # trading.liq_safety_buffer_pct (set-to-max 27.06: запас под maint+slip+funding)


# ── Сайзинг (делегирует в единый PositionSizer) ───────────────────────────────
def size_position(entry_price: float, sl_price: float, deposit: float,
                  risk_pct: float, leverage: int = 1, config=None) -> float:
    """qty по риск-менеджменту. Тонкая обёртка над PositionSizer.calc_qty (reuse).

    Существует чтобы у ExecutionSphere была ОДНА точка входа в сайзинг, но формула —
    ровно PositionSizer (включая OTE-RBUG notional-cap). Дрейфа нет (parity-тест)."""
    return PositionSizer(config).calc_qty(
        entry_price=entry_price, sl_price=sl_price,
        deposit=deposit, risk_pct=risk_pct, leverage=leverage,
    )


# ── Guards входа (порт open_bracket:403-440, поведение 1:1) ────────────────────
def validate_entry(direction: str, entry_price: float, sl: float, qty: float,
                   min_sl_dist_pct: float = DEFAULT_MIN_SL_DIST_PCT,
                   min_notional: float = DEFAULT_MIN_NOTIONAL) -> tuple[bool, Optional[str]]:
    """Проверки перед place. Возвращает (ok, error|None).

    Порядок и пороги = order_manager.open_bracket:
      1. qty > 0
      2. sl_dist >= min_sl_dist_pct (DEV-164)
      3. SL в правильную сторону (DEV-159): LONG sl<entry, SHORT sl>entry
      4. notional >= min_notional
    """
    direction = (direction or "").upper()
    if qty <= 0:
        return False, f"qty={qty} <= 0"

    if entry_price > 0 and sl > 0:
        sl_dist_pct = abs(entry_price - sl) / entry_price * 100
        if sl_dist_pct < min_sl_dist_pct:
            return False, (f"DEV-164 SL too close: {sl_dist_pct:.4f}% < {min_sl_dist_pct:.2f}% "
                           f"(entry={entry_price:.6g} sl={sl:.6g})")

    sl_direction_ok = (sl < entry_price) if direction == "LONG" else (sl > entry_price)
    if not sl_direction_ok:
        return False, f"SL direction error: {direction} entry={entry_price:.6g} sl={sl:.6g}"

    notional = qty * entry_price
    if notional < min_notional:
        return False, f"notional={notional:.2f} < {min_notional} min"

    return True, None


# ── Leverage-клампы (порт open_bracket:469-487, поведение 1:1) ─────────────────
def clamp_leverage(requested: int, entry_price: float, sl: float,
                   pair_max: Optional[int] = None,
                   liq_safety_enabled: bool = True,
                   liq_buffer_pct: float = DEFAULT_LIQ_BUFFER_PCT,
                   set_to_max: bool = False) -> tuple[int, Optional[str]]:
    """Финальное плечо от SL. Возвращает (leverage, reason|None). ЕДИНЫЙ калькулятор плеча —
    зовут order_manager (боевой), ExecutionSphere (cutover), RiskIntelligence Сфера 3 (shadow).

    Плечо НЕ влияет на риск (qty=f(risk_pct,SL) в PositionSizer.calc_qty) — только на маржу.
    SL-safety: ликвидация (~1/leverage) ДОЛЖНА быть дальше SL → leverage ≤ 1/(sl_frac + buffer).

    Два режима:
      - set_to_max=False (cap-down, дефолт): ТОЛЬКО снижает (requested>safe → safe). Лечит
        POPCAT 50× SL 2.75% > liq 1.9%. requested сидит как есть если он уже безопасен.
      - set_to_max=True (27.06): целимся в МАКС безопасное плечо = min(1/(sl+buf), pair_max),
        игнорируя requested. Меньше маржи/сделку → 2-4× параллельных позиций при том же риске.
    Кламп к max пары применяется в обоих режимах (биржа отвергает выше → откат на стейл).
    """
    leverage = int(requested)
    reasons: list[str] = []

    if liq_safety_enabled and entry_price > 0 and sl > 0:
        sl_frac = abs(entry_price - sl) / entry_price
        buf = (liq_buffer_pct or 0) / 100.0
        denom = sl_frac + buf
        if denom > 0:
            safe_lev = max(1, int(1.0 / denom))
            if set_to_max:
                target = min(safe_lev, pair_max) if (pair_max and pair_max > 0) else safe_lev
                if target != leverage:
                    reasons.append(f"set-to-max {leverage}→{target} "
                                   f"(sl_dist={sl_frac * 100:.2f}% buf={buf * 100:.2f}% pair_max={pair_max})")
                    leverage = target
                return leverage, ("; ".join(reasons) if reasons else None)
            # cap-down: сперва max пары, затем SL-safety (только вниз)
            if pair_max and pair_max > 0 and leverage > pair_max:
                reasons.append(f"cap пары {leverage}→{pair_max}")
                leverage = pair_max
            if safe_lev < leverage:
                reasons.append(f"SL-safety {leverage}→{safe_lev} "
                               f"(sl_dist={sl_frac * 100:.2f}% buf={buf * 100:.2f}%)")
                leverage = safe_lev
            return leverage, ("; ".join(reasons) if reasons else None)

    # liq_safety выкл / нет цены → хотя бы кап к max пары
    if pair_max and pair_max > 0 and leverage > pair_max:
        reasons.append(f"cap пары {leverage}→{pair_max}")
        leverage = pair_max

    return leverage, ("; ".join(reasons) if reasons else None)
