"""
core/smc/confluence.py — ARCH-28: FVG + Pivot Confluence Map.

Находит зоны где незаполненный FVG совпадает с пивотным уровнем.
Такие зоны — сильнейшие точки притяжения цены (поддержка/сопротивление).

Использование:
    from core.smc.confluence import find_fvg_pivot_confluences
    zones = find_fvg_pivot_confluences(fvg_analysis, pivot_levels, current_price)
    for z in zones:
        print(z["label"], z["price"], z["distance_pct"], z["score"])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.smc.fvg import FVG, FVGAnalysis, FVGType

# ── Скоринг конфлюэнции ──────────────────────────────────────────────────────
_SCORE_FVG_ACTIVE      = 10   # FVG не заполнен
_SCORE_PIVOT_IN_FVG    = 15   # пивотный уровень попадает в FVG зону
_SCORE_SENIOR_TF_BONUS =  5   # пивот старшего ТФ (1W / 1M)

_SENIOR_TF_PREFIXES = ("1W_", "1M_")


# ── Результат одной конфлюэнции ───────────────────────────────────────────────

@dataclass
class FVGPivotConfluence:
    """Одна зона конфлюэнции: FVG + пивотный уровень."""
    fvg: FVG                     # сам FVG объект
    pivot_key: str               # например "1W_S2"
    pivot_price: float           # цена пивота
    distance_pct: float          # дистанция от текущей цены (< 0 = ниже)
    side: str                    # "support" | "resistance"
    score: int                   # итоговый score конфлюэнции
    label: str = field(init=False)

    def __post_init__(self):
        fvg_dir = "Bull" if self.fvg.fvg_type == FVGType.BULL else "Bear"
        self.label = f"{fvg_dir} FVG + {self.pivot_key}"

    def to_dict(self) -> dict:
        return {
            "label":        self.label,
            "fvg_bottom":   self.fvg.bottom,
            "fvg_top":      self.fvg.top,
            "fvg_mid":      self.fvg.midpoint,
            "pivot_key":    self.pivot_key,
            "pivot_price":  self.pivot_price,
            "distance_pct": round(self.distance_pct, 1),
            "side":         self.side,
            "score":        self.score,
            "fill_pct":     round(self.fvg.mitigation_pct, 1),
        }


# ── Основная функция ──────────────────────────────────────────────────────────

def find_fvg_pivot_confluences(
    fvg_analysis: FVGAnalysis,
    pivot_levels: dict,
    current_price: float,
    tolerance_pct: float = 1.0,
) -> List[FVGPivotConfluence]:
    """
    Находит конфлюэнции незаполненного FVG + пивотный уровень.

    Args:
        fvg_analysis:   результат detect_fvg()
        pivot_levels:   плоский dict {"1W_S2": 0.004406, "1D_PP": 0.0065, ...}
        current_price:  текущая цена для расчёта дистанции
        tolerance_pct:  допуск совпадения пивота с FVG зоной (% от цены пивота)

    Returns:
        Список FVGPivotConfluence, отсортированный по дистанции от цены (ближайшие первые).

    Пример (FAI/USDT 4h, 22.03.2026):
        Bull FVG 0.004333–0.004696 + 1W S2 0.004406 → score=30, dist=-17%
    """
    if not current_price or current_price <= 0:
        return []

    active_fvgs = fvg_analysis.active_bull + fvg_analysis.active_bear
    results: List[FVGPivotConfluence] = []

    for fvg in active_fvgs:
        for pivot_key, pivot_price in pivot_levels.items():
            if not pivot_price or pivot_price <= 0:
                continue

            # Пивот внутри FVG зоны (с допуском tolerance_pct)
            tol = pivot_price * tolerance_pct / 100
            in_fvg = (fvg.bottom - tol) <= pivot_price <= (fvg.top + tol)
            if not in_fvg:
                continue

            # Скоринг
            score = _SCORE_FVG_ACTIVE + _SCORE_PIVOT_IN_FVG
            if any(pivot_key.startswith(p) for p in _SENIOR_TF_PREFIXES):
                score += _SCORE_SENIOR_TF_BONUS

            distance_pct = (fvg.midpoint - current_price) / current_price * 100
            side = "support" if fvg.fvg_type == FVGType.BULL else "resistance"

            results.append(FVGPivotConfluence(
                fvg=fvg,
                pivot_key=pivot_key,
                pivot_price=pivot_price,
                distance_pct=distance_pct,
                side=side,
                score=score,
            ))

    # Сортируем по абсолютной дистанции — ближайшие первые
    results.sort(key=lambda z: abs(z.distance_pct))
    return results


# ── Хелпер: форматирование для TG-сообщения ──────────────────────────────────

def format_confluence_zones(zones: List[FVGPivotConfluence], max_zones: int = 3) -> str:
    """
    Форматирует зоны конфлюэнции для вывода в TG-сообщении.

    Пример:
        🟢 Bull FVG + 1W_S2 @ 0.004406  (-17.0%)  score=30
        🔴 Bear FVG + 1D_R1 @ 0.006820  (+25.0%)  score=25
    """
    if not zones:
        return ""
    lines = ["📐 FVG-конфлюэнции:"]
    for z in zones[:max_zones]:
        emoji = "🟢" if z.side == "support" else "🔴"
        lines.append(
            f"  {emoji} {z.label} @ {z.pivot_price:.5g}"
            f"  ({z.distance_pct:+.1f}%)  score={z.score}"
        )
    return "\n".join(lines)
