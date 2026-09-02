"""
Fair Value Gaps (FVG) — ценовые дисбалансы.

FVG — это gap между свечой i-2 и свечой i, где свеча i-1 (импульсная)
оставляет незаполненную зону. Институциональные игроки часто возвращают
цену в эту зону для заполнения (mitigation).

Типы:
  BULL FVG: low[i] > high[i-2]  — бычий импульс, gap вверху
  BEAR FVG: high[i] < low[i-2]  — медвежий импульс, gap внизу

Дополнительные возможности:
  - Mitigation tracking: отслеживание заполнения FVG последующими барами
  - Объединение consecutive FVG: два FVG подряд → расширенная зона
  - Процент заполнения: 0% (нетронут) → 100% (полностью mitigated)
  - Фильтр по размеру: минимальный gap в % от цены

Используется: order_blocks.py (FVG + OB = суперсетап), models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_MIN_BARS = 5


class FVGType(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"


@dataclass
class FVG:
    """Одна Fair Value Gap."""
    fvg_type: FVGType
    top: float            # верхняя граница gap
    bottom: float         # нижняя граница gap
    midpoint: float       # (top + bottom) / 2 — зона входа
    index: int            # индекс импульсной свечи (средней из трёх)
    size_pct: float       # размер gap в % от midpoint
    mitigated: bool = False       # полностью заполнен?
    mitigation_pct: float = 0.0   # 0.0–1.0, степень заполнения
    mitigation_index: Optional[int] = None  # бар, на котором произошла mitigation

    @property
    def is_active(self) -> bool:
        """FVG всё ещё не заполнен (< 100%)."""
        return not self.mitigated

    def __repr__(self) -> str:
        status = "MIT" if self.mitigated else f"{self.mitigation_pct:.0%}"
        return (
            f"{self.fvg_type.value}_FVG("
            f"{self.bottom:.6g}–{self.top:.6g}, "
            f"{self.size_pct:.2f}%, {status}@{self.index})"
        )


@dataclass
class FVGAnalysis:
    """Результат анализа FVG."""
    all_fvgs: List[FVG] = field(default_factory=list)
    active_bull: List[FVG] = field(default_factory=list)   # незаполненные бычьи
    active_bear: List[FVG] = field(default_factory=list)   # незаполненные медвежьи
    nearest_bull: Optional[FVG] = None  # ближайший к текущей цене бычий FVG
    nearest_bear: Optional[FVG] = None  # ближайший к текущей цене медвежий FVG


# ---------------------------------------------------------------------------
# Детекция FVG
# ---------------------------------------------------------------------------

def _detect_raw_fvgs(
    df: pd.DataFrame,
    min_size_pct: float = 0.05,
) -> List[FVG]:
    """
    Находит все FVG в DataFrame.

    Bull FVG: low[i] > high[i-2]  → gap = (high[i-2], low[i])
    Bear FVG: high[i] < low[i-2]  → gap = (high[i], low[i-2])

    Args:
        df: OHLCV DataFrame.
        min_size_pct: минимальный размер gap в % от цены (фильтр шума).
    """
    fvgs: List[FVG] = []
    n = len(df)

    for i in range(2, n):
        high_i = float(df["high"].iloc[i])
        low_i = float(df["low"].iloc[i])
        high_i2 = float(df["high"].iloc[i - 2])
        low_i2 = float(df["low"].iloc[i - 2])

        # Bull FVG: gap between bar i-2 high and bar i low
        if low_i > high_i2:
            bottom = high_i2
            top = low_i
            mid = (top + bottom) / 2.0
            size_pct = (top - bottom) / mid * 100.0 if mid > 0 else 0.0
            if size_pct >= min_size_pct:
                fvgs.append(FVG(
                    fvg_type=FVGType.BULL,
                    top=top,
                    bottom=bottom,
                    midpoint=mid,
                    index=i - 1,  # импульсная свеча
                    size_pct=size_pct,
                ))

        # Bear FVG: gap between bar i high and bar i-2 low
        if high_i < low_i2:
            top = low_i2
            bottom = high_i
            mid = (top + bottom) / 2.0
            size_pct = (top - bottom) / mid * 100.0 if mid > 0 else 0.0
            if size_pct >= min_size_pct:
                fvgs.append(FVG(
                    fvg_type=FVGType.BEAR,
                    top=top,
                    bottom=bottom,
                    midpoint=mid,
                    index=i - 1,
                    size_pct=size_pct,
                ))

    return fvgs


# ---------------------------------------------------------------------------
# Mitigation tracking
# ---------------------------------------------------------------------------

def _track_mitigation(
    fvgs: List[FVG],
    df: pd.DataFrame,
) -> List[FVG]:
    """
    Проверяет каждый FVG на заполнение последующими барами.

    Bull FVG mitigated когда цена опускается В зону gap (low <= top).
    Bear FVG mitigated когда цена поднимается В зону gap (high >= bottom).

    Степень заполнения:
      Bull: min(1.0, (top - min_low_after) / (top - bottom))
      Bear: min(1.0, (max_high_after - bottom) / (top - bottom))
    """
    for fvg in fvgs:
        gap_size = fvg.top - fvg.bottom
        if gap_size <= 0:
            fvg.mitigated = True
            fvg.mitigation_pct = 1.0
            continue

        # Проверяем бары ПОСЛЕ FVG (index = импульсная свеча, index+1 = бар закрывающий FVG)
        start_bar = fvg.index + 1  # +1: первая свеча, способная зайти в FVG
        if start_bar >= len(df):
            continue

        for j in range(start_bar, len(df)):
            bar_low = float(df["low"].iloc[j])
            bar_high = float(df["high"].iloc[j])

            if fvg.fvg_type == FVGType.BULL:
                # Цена опустилась в зону FVG?
                if bar_low <= fvg.top:
                    penetration = fvg.top - bar_low
                    pct = min(1.0, penetration / gap_size)
                    if pct > fvg.mitigation_pct:
                        fvg.mitigation_pct = pct
                        fvg.mitigation_index = j
                    if bar_low <= fvg.bottom:
                        fvg.mitigated = True
                        fvg.mitigation_pct = 1.0
                        break
            else:
                # Bear: цена поднялась в зону FVG?
                if bar_high >= fvg.bottom:
                    penetration = bar_high - fvg.bottom
                    pct = min(1.0, penetration / gap_size)
                    if pct > fvg.mitigation_pct:
                        fvg.mitigation_pct = pct
                        fvg.mitigation_index = j
                    if bar_high >= fvg.top:
                        fvg.mitigated = True
                        fvg.mitigation_pct = 1.0
                        break

    return fvgs


# ---------------------------------------------------------------------------
# Объединение consecutive FVG
# ---------------------------------------------------------------------------

def _join_consecutive(fvgs: List[FVG], max_gap_bars: int = 3) -> List[FVG]:
    """
    Объединяет два FVG одного типа, если они рядом (≤ max_gap_bars баров)
    и перекрываются или смежны.

    Результат: расширенная зона с объединёнными границами.
    """
    if len(fvgs) < 2:
        return fvgs

    merged: List[FVG] = [fvgs[0]]

    for fvg in fvgs[1:]:
        prev = merged[-1]

        same_type = fvg.fvg_type == prev.fvg_type
        close_enough = abs(fvg.index - prev.index) <= max_gap_bars
        overlapping = fvg.bottom <= prev.top and fvg.top >= prev.bottom

        if same_type and close_enough and overlapping:
            # Объединяем: расширяем границы
            merged[-1] = FVG(
                fvg_type=prev.fvg_type,
                top=max(prev.top, fvg.top),
                bottom=min(prev.bottom, fvg.bottom),
                midpoint=(max(prev.top, fvg.top) + min(prev.bottom, fvg.bottom)) / 2.0,
                index=prev.index,  # сохраняем индекс первого
                size_pct=prev.size_pct + fvg.size_pct,  # суммарный размер
                mitigated=prev.mitigated and fvg.mitigated,
                mitigation_pct=min(prev.mitigation_pct, fvg.mitigation_pct),
            )
        else:
            merged.append(fvg)

    return merged


# ---------------------------------------------------------------------------
# Поиск ближайших FVG к текущей цене
# ---------------------------------------------------------------------------

def _find_nearest(
    active: List[FVG],
    current_price: float,
) -> Optional[FVG]:
    """Ближайший активный FVG к текущей цене (по midpoint)."""
    if not active:
        return None
    return min(active, key=lambda f: abs(f.midpoint - current_price))


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ARCH-137.5: зоны из ЭТАЛОНА (smc_engine.detect_fvg, LuxAlgo-порт)
# ---------------------------------------------------------------------------
# Замер 02.09 (16 пар, 1h/400) разложил расхождение двух реализаций на причины:
#   · условие close импульсной свечи — 1 зона из 1292 (0%), не влияет;
#   · MITIGATION: эталон гасит по CLOSE за дальней границей, здешняя — по фитилю.
#     Расходятся на 9% зон, согласие 91%;
#   · 🔑 ПОРОГ ЗНАЧИМОСТИ — главная причина. Эталон: адаптивный (средний |gap%|
#     по всем барам × 2). Здешний: ФИКСИРОВАННЫЙ 0.05%. Эталон отсекает 578 зон,
#     здешний — 187, то есть строже втрое.
# Почему верен адаптивный: 0.05% на BTC и на мем-коине — величины разной
# значимости; фиксированный порог не знает волатильности инструмента. Это ровно
# закон проекта об ОТНОСИТЕЛЬНОМ пороге ([[law_relative_threshold_and_permutation]]).
# Откат: config.yaml → smc.fvg_canon: false

_FVG_CANON: Optional[bool] = None


def _use_fvg_canon() -> bool:
    global _FVG_CANON
    if _FVG_CANON is None:
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _FVG_CANON = bool((cfg.get("smc") or {}).get("fvg_canon", True))
        except Exception:
            _FVG_CANON = True
    return _FVG_CANON


def _fvg_from_canon(df: pd.DataFrame) -> FVGAnalysis:
    """smc_engine.detect_fvg → FVGAnalysis. Контракт сохранён полностью."""
    from core.smc.smc_engine import detect_fvg as _canon_fvg

    raw = _canon_fvg(df) or []
    # позиция бара по метке индекса — эталон отдаёт ts, потребителям нужен int
    pos = {ts: k for k, ts in enumerate(df.index)}
    n = len(df)
    _low = df["low"].to_numpy(dtype=float)     # один раз, вместо .iloc в циклах
    _high = df["high"].to_numpy(dtype=float)
    fvgs: List[FVG] = []

    for ts_left, top, bottom, kind, ts_i, mit in raw:
        top = float(top)
        bottom = float(bottom)
        if top <= bottom:
            continue
        mid = (top + bottom) / 2.0
        i = pos.get(ts_i, None)
        if i is None:
            continue
        gap = top - bottom
        mitigated = mit is not None
        # Степень захода в зону — ВЕКТОРНО. Раньше здесь стоял цикл с .iloc[j]
        # по каждому бару каждой зоны: на 1h/400 это давало 21 мс против 3.
        # Ровно та поэлементная работа, из-за которой прежний набор был в 42 раза
        # медленнее эталона ([[smc_set_b_40x_slower]]) — не повторять её здесь.
        end = pos.get(mit, n) if mitigated else n
        lo, hi = i + 1, min(end + 1, n)
        mpct = 0.0
        m_idx = None
        if hi > lo:
            pen = (top - _low[lo:hi]) if kind == "bull" else (_high[lo:hi] - bottom)
            k = int(pen.argmax())
            best = float(pen[k])
            if best > 0:
                mpct = min(1.0, best / gap)
                m_idx = lo + k
        if mitigated:
            mpct = 1.0
            m_idx = pos.get(mit, m_idx)

        fvgs.append(FVG(
            fvg_type=FVGType.BULL if kind == "bull" else FVGType.BEAR,
            top=top,
            bottom=bottom,
            midpoint=mid,
            index=max(0, i - 1),          # импульсная свеча — как в прежней реализации
            size_pct=gap / mid * 100.0 if mid > 0 else 0.0,
            mitigated=mitigated,
            mitigation_pct=mpct,
            mitigation_index=m_idx,
        ))

    fvgs.sort(key=lambda f: f.index)
    active_bull = [f for f in fvgs if f.fvg_type == FVGType.BULL and f.is_active]
    active_bear = [f for f in fvgs if f.fvg_type == FVGType.BEAR and f.is_active]
    cur = float(df["close"].iloc[-1])
    return FVGAnalysis(
        all_fvgs=fvgs,
        active_bull=active_bull,
        active_bear=active_bear,
        nearest_bull=_find_nearest(active_bull, cur),
        nearest_bear=_find_nearest(active_bear, cur),
    )


def detect_fvg(
    df: pd.DataFrame,
    min_size_pct: float = 0.05,
    max_join_bars: int = 3,
    track_mitigation: bool = True,
) -> FVGAnalysis:
    """
    Полный анализ Fair Value Gaps.

    Args:
        df: OHLCV DataFrame.
        min_size_pct: минимальный размер gap в % от цены.
        max_join_bars: максимальное расстояние для объединения consecutive FVG.
        track_mitigation: отслеживать заполнение FVG.

    Returns:
        FVGAnalysis с active/mitigated FVG и ближайшими к цене.

    Пример:
        >>> analysis = detect_fvg(df_15m, min_size_pct=0.1)
        >>> for fvg in analysis.active_bull:
        ...     print(f"Bull FVG: {fvg.bottom:.4f}–{fvg.top:.4f}")
        >>> if analysis.nearest_bull:
        ...     print(f"Ближайший BULL FVG midpoint: {analysis.nearest_bull.midpoint:.4f}")
    """
    empty = FVGAnalysis()

    if df is None or len(df) < _MIN_BARS:
        return empty

    # ARCH-137.5: единый источник зон — эталон. Откат: smc.fvg_canon: false
    if _use_fvg_canon():
        try:
            return _fvg_from_canon(df)
        except Exception as e:
            logger.debug("detect_fvg canon error: %s", e, exc_info=True)
            # падать нельзя — потребители в горячем пути; идём прежним путём

    try:
        # 1. Найти все FVG
        fvgs = _detect_raw_fvgs(df, min_size_pct=min_size_pct)
        if not fvgs:
            return empty

        # 2. Объединить consecutive
        fvgs = _join_consecutive(fvgs, max_gap_bars=max_join_bars)

        # 3. Mitigation tracking
        if track_mitigation:
            fvgs = _track_mitigation(fvgs, df)

        # 4. Разделить на active bull/bear
        active_bull = [f for f in fvgs if f.fvg_type == FVGType.BULL and f.is_active]
        active_bear = [f for f in fvgs if f.fvg_type == FVGType.BEAR and f.is_active]

        # 5. Ближайшие к текущей цене
        current_price = float(df["close"].iloc[-1])
        nearest_bull = _find_nearest(active_bull, current_price)
        nearest_bear = _find_nearest(active_bear, current_price)

        return FVGAnalysis(
            all_fvgs=fvgs,
            active_bull=active_bull,
            active_bear=active_bear,
            nearest_bull=nearest_bull,
            nearest_bear=nearest_bear,
        )

    except Exception as e:
        logger.debug("detect_fvg error: %s", e, exc_info=True)
        return empty
