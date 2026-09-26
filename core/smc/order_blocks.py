"""
Order Blocks (OB) — зоны институциональных ордеров.

Order Block — последняя противотрендовая свеча ПЕРЕД импульсным движением
(Break of Structure). Институциональные игроки часто размещают свои ордера
на этих уровнях, и цена возвращается к ним при откате.

Типы:
  Bullish OB: последняя медвежья свеча перед бычьим BOS/CHoCH.
              Зона: [low, high] этой свечи → зона покупки при откате.
  Bearish OB: последняя бычья свеча перед медвежьим BOS/CHoCH.
              Зона: [low, high] этой свечи → зона продажи при откате.

Дополнительные свойства:
  - Volume filter: OB с аномальным объёмом (> 1.5× MA) сильнее
  - Breaker lifecycle: OB из CHoCH > OB из BOS (разворот > продолжение)
  - Mitigation: OB "отработан" когда цена полностью проходит через зону
  - Overlap с FVG: OB + FVG = суперсетап (двойное подтверждение)

Зависит от: structure.py (StructureBreak), swing_points.py.
Используется: models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import pandas as pd

from core.smc.structure import StructureAnalysis, StructureBreak, BreakType

logger = logging.getLogger(__name__)


class OBType(str, Enum):
    BULLISH = "BULLISH"   # зона покупки (последняя медвежья свеча перед BOS вверх)
    BEARISH = "BEARISH"   # зона продажи (последняя бычья свеча перед BOS вниз)


@dataclass
class OrderBlock:
    """Один Order Block."""
    ob_type: OBType
    top: float             # high свечи OB
    bottom: float          # low свечи OB
    midpoint: float        # (top + bottom) / 2 — зона входа
    index: int             # индекс свечи OB в DataFrame
    origin_break: StructureBreak   # какой BOS/CHoCH создал этот OB
    volume_ratio: float = 1.0      # volume / MA(20) — > 1.5 = сильный OB
    mitigated: bool = False
    mitigation_pct: float = 0.0    # 0.0–1.0
    mitigation_index: Optional[int] = None
    has_fvg_overlap: bool = False   # совпадает с FVG

    @property
    def is_active(self) -> bool:
        return not self.mitigated

    @property
    def strength(self) -> int:
        """Сила OB: 0-100."""
        base = 60
        # CHoCH-based OB сильнее (разворот)
        if self.origin_break.is_choch:
            base += 15
        # Аномальный объём
        if self.volume_ratio >= 2.0:
            base += 15
        elif self.volume_ratio >= 1.5:
            base += 10
        # FVG overlap
        if self.has_fvg_overlap:
            base += 10
        return min(100, base)

    def __repr__(self) -> str:
        status = "MIT" if self.mitigated else "ACTIVE"
        return (
            f"{self.ob_type.value}_OB("
            f"{self.bottom:.6g}–{self.top:.6g}, "
            f"vol={self.volume_ratio:.1f}x, "
            f"str={self.strength}, {status}@{self.index})"
        )


@dataclass
class OBAnalysis:
    """Результат анализа Order Blocks."""
    all_obs: List[OrderBlock] = field(default_factory=list)
    active_bull: List[OrderBlock] = field(default_factory=list)
    active_bear: List[OrderBlock] = field(default_factory=list)
    nearest_bull: Optional[OrderBlock] = None
    nearest_bear: Optional[OrderBlock] = None


# ---------------------------------------------------------------------------
# Определение Order Block свечи
# ---------------------------------------------------------------------------

def _find_ob_candle(
    df: pd.DataFrame,
    brk: StructureBreak,
    lookback: int = 10,
) -> Optional[int]:
    """
    Находит последнюю ПРОТИВОТРЕНДОВУЮ свечу перед импульсом.

    Для бычьего пробоя: ищем последнюю медвежью свечу (close < open)
    перед баром пробоя (от свинга до пробоя).

    Для медвежьего пробоя: ищем последнюю бычью свечу (close > open).
    """
    # Зона поиска: от свинга до бара пробоя (не включая сам бар пробоя)
    search_end = brk.break_index
    search_start = max(0, brk.broken_swing.index)

    # Ограничиваем lookback
    search_start = max(search_start, search_end - lookback)

    is_bullish_break = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)

    # Идём назад от бара пробоя, ищем противотрендовую свечу
    for i in range(search_end - 1, search_start - 1, -1):
        bar_open = float(df["open"].iloc[i])
        bar_close = float(df["close"].iloc[i])

        if is_bullish_break:
            # Ищем медвежью свечу (close < open)
            if bar_close < bar_open:
                return i
        else:
            # Ищем бычью свечу (close > open)
            if bar_close > bar_open:
                return i

    return None


# ---------------------------------------------------------------------------
# Volume ratio
# ---------------------------------------------------------------------------

def _compute_volume_ratio(
    df: pd.DataFrame,
    ob_index: int,
    ma_period: int = 20,
) -> float:
    """Объём OB-свечи / MA(20) объёма."""
    if "volume" not in df.columns:
        return 1.0

    ob_vol = float(df["volume"].iloc[ob_index])
    if ob_vol <= 0:
        return 1.0

    start = max(0, ob_index - ma_period)
    vol_slice = df["volume"].iloc[start:ob_index]
    if len(vol_slice) == 0:
        return 1.0

    ma = float(vol_slice.mean())
    return ob_vol / ma if ma > 0 else 1.0


# ---------------------------------------------------------------------------
# Mitigation tracking
# ---------------------------------------------------------------------------

def _track_ob_mitigation(
    obs: List[OrderBlock],
    df: pd.DataFrame,
) -> List[OrderBlock]:
    """
    Проверяет mitigation Order Blocks.

    Bullish OB mitigated: цена опускается НИЖЕ bottom OB (зона пробита).
    Bearish OB mitigated: цена поднимается ВЫШЕ top OB.
    """
    n = len(df)

    for ob in obs:
        gap_size = ob.top - ob.bottom
        if gap_size <= 0:
            ob.mitigated = True
            ob.mitigation_pct = 1.0
            continue

        start = ob.index + 1
        for j in range(start, n):
            bar_low = float(df["low"].iloc[j])
            bar_high = float(df["high"].iloc[j])

            if ob.ob_type == OBType.BULLISH:
                # Bullish OB invalidated если цена ушла ниже зоны
                if bar_low <= ob.top:
                    penetration = ob.top - bar_low
                    pct = min(1.0, penetration / gap_size)
                    if pct > ob.mitigation_pct:
                        ob.mitigation_pct = pct
                        ob.mitigation_index = j
                    if bar_low <= ob.bottom:
                        ob.mitigated = True
                        ob.mitigation_pct = 1.0
                        break
            else:
                # Bearish OB invalidated если цена ушла выше зоны
                if bar_high >= ob.bottom:
                    penetration = bar_high - ob.bottom
                    pct = min(1.0, penetration / gap_size)
                    if pct > ob.mitigation_pct:
                        ob.mitigation_pct = pct
                        ob.mitigation_index = j
                    if bar_high >= ob.top:
                        ob.mitigated = True
                        ob.mitigation_pct = 1.0
                        break

    return obs


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ARCH-137.5: Order Blocks из ЭТАЛОНА (smc_engine.detect_order_blocks → core/structure)
# ---------------------------------------------------------------------------
# Замер 02.09 (16 пар, 1h/400, 343 слома) — это НЕ баг, а два разных определения:
#   · эталон: «спокойная» свеча (размер < 2×ATR200) с ЭКСТРЕМУМОМ
#     в интервале [свинг..пробой];
#   · прежнее (ICT): последняя ПРОТИВОТРЕНДОВАЯ свеча перед пробоем.
#   Одну и ту же свечу выбирают лишь в 13% случаев. Обрезка lookback=10 при этом
#   не влияет вовсе (0 случаев из 343) — проверено отдельно.
#
# 🔑 ПОЧЕМУ ВЫБРАН ЭТАЛОН — не «красивее», а рассинхрон человека и бота:
#   chart_builder.py:297 и web/structure_terminal.py рисуют OB из smc_engine,
#   то есть НА ГРАФИКАХ ВИДЕН ЭТАЛОН. А smc_snapshot (ML-сфера 4) и cascade_tsl
#   (боевой TSL!) работали на прежнем. Совпадение 13% означает: смотрим на одни
#   зоны, торгуем по другим. Тот же класс, что был с FVG на HYPE.
#
# Эффект: активных зон 46 → 107 (прежняя гасила по фитилю, эталон — по close).
# Откат: config.yaml → smc.ob_canon: false

_OB_CANON: Optional[bool] = None


def _use_ob_canon() -> bool:
    global _OB_CANON
    if _OB_CANON is None:
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _OB_CANON = bool((cfg.get("smc") or {}).get("ob_canon", True))
        except Exception:
            _OB_CANON = True
    return _OB_CANON


class _BrkView:
    """Вид слома в терминах эталона: ему нужны только idx / from_idx / direction."""
    __slots__ = ("idx", "from_idx", "direction")

    def __init__(self, idx: int, from_idx: int, direction: str):
        self.idx = idx
        self.from_idx = from_idx
        self.direction = direction


def _obs_from_canon(df: pd.DataFrame, structure: StructureAnalysis,
                    volume_ma_period: int = 20) -> OBAnalysis:
    """smc_engine.detect_order_blocks → OBAnalysis. Контракт сохранён."""
    from core.smc.smc_engine import detect_order_blocks as _canon_ob

    views = []
    by_break_idx = {}
    for b in structure.breaks:
        bull = b.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)
        v = _BrkView(int(b.break_index), int(b.broken_swing.index),
                     "bull" if bull else "bear")
        views.append(v)
        by_break_idx.setdefault(v.idx, b)

    raw = _canon_ob(df, views) or []
    n = len(df)
    _low = df["low"].to_numpy(dtype=float)     # один раз, вместо .iloc в циклах
    _high = df["high"].to_numpy(dtype=float)
    obs: List[OrderBlock] = []

    for r in raw:
        top = float(r.top)
        bottom = float(r.bottom)
        if top <= bottom:
            continue
        idx = int(r.left_idx)
        if not (0 <= idx < n):
            continue
        origin = by_break_idx.get(int(r.break_idx))
        if origin is None:                      # слом эталона без пары — пропуск
            continue
        mit_i = int(getattr(r, "mitigated_idx", -1))
        mitigated = mit_i >= 0
        gap = top - bottom
        end = mit_i if mitigated else n
        # ВЕКТОРНО: цикл с .iloc[j] по барам каждой зоны стоил 41 мс против 5
        # на 1h/400 — см. [[smc_set_b_40x_slower]].
        lo, hi = idx + 1, min(end + 1, n)
        mpct, m_idx = 0.0, None
        if hi > lo:
            pen = (top - _low[lo:hi]) if r.kind == "bull" else (_high[lo:hi] - bottom)
            k = int(pen.argmax())
            best = float(pen[k])
            if best > 0:
                mpct = min(1.0, best / gap)
                m_idx = lo + k
        if mitigated:
            mpct, m_idx = 1.0, mit_i

        obs.append(OrderBlock(
            ob_type=OBType.BULLISH if r.kind == "bull" else OBType.BEARISH,
            top=top,
            bottom=bottom,
            midpoint=(top + bottom) / 2.0,
            index=idx,
            origin_break=origin,
            volume_ratio=_compute_volume_ratio(df, idx, volume_ma_period),
            mitigated=mitigated,
            mitigation_pct=mpct,
            mitigation_index=m_idx,
        ))

    obs.sort(key=lambda x: x.index)
    active_bull = [x for x in obs if x.ob_type == OBType.BULLISH and x.is_active]
    active_bear = [x for x in obs if x.ob_type == OBType.BEARISH and x.is_active]
    cur = float(df["close"].iloc[-1])
    return OBAnalysis(
        all_obs=obs,
        active_bull=active_bull,
        active_bear=active_bear,
        nearest_bull=min(active_bull, key=lambda o: abs(o.midpoint - cur)) if active_bull else None,
        nearest_bear=min(active_bear, key=lambda o: abs(o.midpoint - cur)) if active_bear else None,
    )


def detect_order_blocks(
    df: pd.DataFrame,
    structure: StructureAnalysis,
    volume_ma_period: int = 20,
    ob_lookback: int = 10,
    track_mitigation: bool = True,
) -> OBAnalysis:
    """
    Детектирует Order Blocks на основе структурных пробоев.

    Args:
        df: OHLCV DataFrame.
        structure: результат detect_structure().
        volume_ma_period: период MA для расчёта volume_ratio.
        ob_lookback: максимальный lookback для поиска OB-свечи.
        track_mitigation: отслеживать mitigation.

    Returns:
        OBAnalysis с active/mitigated Order Blocks.

    Пример:
        >>> from core.smc.structure import detect_structure
        >>> struct = detect_structure(df_15m)
        >>> obs = detect_order_blocks(df_15m, struct)
        >>> for ob in obs.active_bull:
        ...     print(f"Bullish OB: {ob.bottom:.4f}–{ob.top:.4f} (str={ob.strength})")
    """
    empty = OBAnalysis()

    if not structure.breaks:
        return empty

    # ARCH-137.5: единый источник зон — эталон. Откат: smc.ob_canon: false
    if _use_ob_canon():
        try:
            return _obs_from_canon(df, structure, volume_ma_period)
        except Exception as e:
            logger.debug("detect_order_blocks canon error: %s", e, exc_info=True)
            # горячий путь падать не должен — идём прежней реализацией

    try:
        obs: List[OrderBlock] = []

        for brk in structure.breaks:
            ob_idx = _find_ob_candle(df, brk, lookback=ob_lookback)
            if ob_idx is None:
                continue

            ob_high = float(df["high"].iloc[ob_idx])
            ob_low = float(df["low"].iloc[ob_idx])
            mid = (ob_high + ob_low) / 2.0

            is_bullish = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)
            ob_type = OBType.BULLISH if is_bullish else OBType.BEARISH

            vol_ratio = _compute_volume_ratio(df, ob_idx, ma_period=volume_ma_period)

            obs.append(OrderBlock(
                ob_type=ob_type,
                top=ob_high,
                bottom=ob_low,
                midpoint=mid,
                index=ob_idx,
                origin_break=brk,
                volume_ratio=vol_ratio,
            ))

        if not obs:
            return empty

        # Mitigation
        if track_mitigation:
            obs = _track_ob_mitigation(obs, df)

        # Разделение
        active_bull = [ob for ob in obs if ob.ob_type == OBType.BULLISH and ob.is_active]
        active_bear = [ob for ob in obs if ob.ob_type == OBType.BEARISH and ob.is_active]

        # Nearest
        current_price = float(df["close"].iloc[-1])
        nearest_bull = min(active_bull, key=lambda o: abs(o.midpoint - current_price)) if active_bull else None
        nearest_bear = min(active_bear, key=lambda o: abs(o.midpoint - current_price)) if active_bear else None

        return OBAnalysis(
            all_obs=obs,
            active_bull=active_bull,
            active_bear=active_bear,
            nearest_bull=nearest_bull,
            nearest_bear=nearest_bear,
        )

    except Exception as e:
        logger.debug("detect_order_blocks error: %s", e, exc_info=True)
        return empty
