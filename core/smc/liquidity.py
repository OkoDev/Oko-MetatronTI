"""
Liquidity — зоны скопления ликвидности (стоп-ордера).

Ликвидность скапливается:
  - Над Swing Highs (стопы шортистов) → buy-side liquidity
  - Под Swing Lows (стопы лонгистов) → sell-side liquidity

Институциональные игроки "охотятся" за этой ликвидностью — цена выносит
стопы (sweep), собирает объём и разворачивается.

Кластеры:
  Несколько свингов на близком уровне (±0.3%) образуют кластер ликвидности.
  Чем больше свингов в кластере — тем больше стопов — тем сильнее зона.

Swept tracking:
  После sweep (цена проходит через уровень) ликвидность "собрана".
  Swept liquidity = зона отработана, новые стопы ещё не накопились.

Зависит от: swing_points.py.
Используется: models.py (SMCContext).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from core.smc.swing_points import SwingAnalysis, SwingPoint, SwingType

logger = logging.getLogger(__name__)


@dataclass
class LiquidityZone:
    """Одна зона ликвидности (кластер свингов)."""
    level: float              # средний уровень кластера
    zone_top: float           # верхняя граница (level + tolerance)
    zone_bottom: float        # нижняя граница (level - tolerance)
    side: str                 # "BUY" (над highs) или "SELL" (под lows)
    swing_count: int          # количество свингов в кластере
    swing_indices: List[int] = field(default_factory=list)
    swept: bool = False       # ликвидность собрана?
    sweep_index: Optional[int] = None  # бар sweep'а

    @property
    def strength(self) -> int:
        """Сила зоны: больше свингов → больше стопов → сильнее."""
        base = min(100, 30 + self.swing_count * 20)
        if self.swept:
            base = max(10, base - 40)  # swept = отработана
        return base

    @property
    def is_active(self) -> bool:
        return not self.swept

    def __repr__(self) -> str:
        status = "SWEPT" if self.swept else "ACTIVE"
        return (
            f"{self.side}_LIQ("
            f"{self.zone_bottom:.6g}–{self.zone_top:.6g}, "
            f"n={self.swing_count}, str={self.strength}, {status})"
        )


@dataclass
class LiquidityAnalysis:
    """Результат анализа ликвидности."""
    buy_side: List[LiquidityZone] = field(default_factory=list)   # над highs
    sell_side: List[LiquidityZone] = field(default_factory=list)  # под lows
    nearest_buy: Optional[LiquidityZone] = None    # ближайшая зона выше цены
    nearest_sell: Optional[LiquidityZone] = None   # ближайшая зона ниже цены


# ---------------------------------------------------------------------------
# Кластеризация свингов
# ---------------------------------------------------------------------------

def _cluster_swings(
    swings: List[SwingPoint],
    tolerance_pct: float = 0.3,
) -> List[LiquidityZone]:
    """
    Группирует свинги в кластеры по близости уровней.

    Два свинга в одном кластере если |a - b| / a < tolerance_pct%.
    """
    if not swings:
        return []

    # Сортируем по value
    sorted_swings = sorted(swings, key=lambda s: s.value)

    clusters: List[List[SwingPoint]] = []
    current_cluster: List[SwingPoint] = [sorted_swings[0]]

    for s in sorted_swings[1:]:
        prev_val = current_cluster[-1].value
        if prev_val > 0 and abs(s.value - prev_val) / prev_val * 100 <= tolerance_pct:
            current_cluster.append(s)
        else:
            clusters.append(current_cluster)
            current_cluster = [s]

    clusters.append(current_cluster)

    # Конвертируем в LiquidityZone
    zones: List[LiquidityZone] = []
    for cluster in clusters:
        values = [s.value for s in cluster]
        level = sum(values) / len(values)
        tolerance = level * tolerance_pct / 100.0

        side = "BUY" if cluster[0].swing_type == SwingType.HIGH else "SELL"

        zones.append(LiquidityZone(
            level=level,
            zone_top=level + tolerance,
            zone_bottom=level - tolerance,
            side=side,
            swing_count=len(cluster),
            swing_indices=[s.index for s in cluster],
        ))

    return zones


# ---------------------------------------------------------------------------
# Sweep tracking
# ---------------------------------------------------------------------------

def _track_sweeps(
    zones: List[LiquidityZone],
    df: pd.DataFrame,
) -> List[LiquidityZone]:
    """
    Проверяет: была ли зона ликвидности swept (цена прошла через неё)?

    BUY-side swept: high бара > zone_top (стопы шортистов сработали).
    SELL-side swept: low бара < zone_bottom (стопы лонгистов сработали).
    """
    n = len(df)
    # ВЕКТОРНО (02.09.2026). Раньше здесь стоял цикл по барам с df["high"].iloc[j]
    # для КАЖДОЙ зоны: профиль дал 45 780 обращений к pandas за 20 прогонов и
    # 42 мс на вызов — самый дорогой детектор после перевода остальных на эталон.
    # Тот же класс проблемы, что в _detect_breaks старого набора ([[smc_set_b_40x_slower]]).
    # argmax по булевой маске находит ПЕРВЫЙ бар, пробивший границу, за один проход C-кодом.
    _high = df["high"].to_numpy(dtype=float)
    _low = df["low"].to_numpy(dtype=float)

    for zone in zones:
        # Начинаем проверку после последнего свинга в кластере
        start = max(zone.swing_indices) + 1 if zone.swing_indices else 0
        if start >= n:
            continue

        if zone.side == "BUY":
            hit = _high[start:] > zone.zone_top
        else:
            hit = _low[start:] < zone.zone_bottom

        if hit.any():
            zone.swept = True
            zone.sweep_index = start + int(hit.argmax())   # argmax = первый True

    return zones


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def detect_liquidity(
    df: pd.DataFrame,
    swing_analysis: SwingAnalysis,
    cluster_tolerance_pct: float = 0.3,
    track_sweeps: bool = True,
) -> LiquidityAnalysis:
    """
    Анализ зон ликвидности на основе свингов.

    Args:
        df: OHLCV DataFrame.
        swing_analysis: результат detect_swing_points().
        cluster_tolerance_pct: допуск для кластеризации свингов (%).
        track_sweeps: отслеживать sweep'ы.

    Returns:
        LiquidityAnalysis с buy-side и sell-side зонами.

    Пример:
        >>> from core.smc.swing_points import detect_swing_points
        >>> swings = detect_swing_points(df_15m)
        >>> liq = detect_liquidity(df_15m, swings)
        >>> for zone in liq.buy_side:
        ...     print(f"Buy-side liquidity: {zone.level:.4f} (n={zone.swing_count})")
    """
    empty = LiquidityAnalysis()

    if not swing_analysis.highs and not swing_analysis.lows:
        return empty

    try:
        # 1. Кластеризация highs (buy-side liquidity)
        buy_zones = _cluster_swings(swing_analysis.highs, tolerance_pct=cluster_tolerance_pct)
        for z in buy_zones:
            z.side = "BUY"

        # 2. Кластеризация lows (sell-side liquidity)
        sell_zones = _cluster_swings(swing_analysis.lows, tolerance_pct=cluster_tolerance_pct)
        for z in sell_zones:
            z.side = "SELL"

        # 3. Sweep tracking
        if track_sweeps and df is not None:
            buy_zones = _track_sweeps(buy_zones, df)
            sell_zones = _track_sweeps(sell_zones, df)

        # 4. Nearest (active only)
        current_price = float(df["close"].iloc[-1]) if df is not None and len(df) > 0 else 0.0
        active_buy = [z for z in buy_zones if z.is_active and z.level > current_price]
        active_sell = [z for z in sell_zones if z.is_active and z.level < current_price]

        nearest_buy = min(active_buy, key=lambda z: z.level - current_price) if active_buy else None
        nearest_sell = max(active_sell, key=lambda z: z.level) if active_sell else None

        return LiquidityAnalysis(
            buy_side=buy_zones,
            sell_side=sell_zones,
            nearest_buy=nearest_buy,
            nearest_sell=nearest_sell,
        )

    except Exception as e:
        logger.debug("detect_liquidity error: %s", e, exc_info=True)
        return empty


# ---------------------------------------------------------------------------
# DEV-140 / ARCH-68: Equal Highs / Equal Lows
# ---------------------------------------------------------------------------

_EQ_CANON: Optional[bool] = None


def _use_eq_canon() -> bool:
    global _EQ_CANON
    if _EQ_CANON is None:
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[2] / "config.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _EQ_CANON = bool((cfg.get("smc") or {}).get("eq_canon", True))
        except Exception:
            _EQ_CANON = True
    return _EQ_CANON


def _eq_from_canon(df: pd.DataFrame, threshold_pct: float = 0.01,
                   lookback: int = 50) -> dict:
    """Сводка EQH/EQL поверх эталонных уровней smc_engine.detect_equal_levels.

    Контракт (6 ключей) сохранён. Смысл полей:
      *_level — уровень, БЛИЖАЙШИЙ к текущей цене;
      *_near  — этот уровень в радиусе threshold_pct от цены;
      *_count — сколько эталонных пар уровней попало в кластер (раньше здесь были
                сотни «пар баров» — величина без смысла; поле никем не читается).

    🔴 `lookback` НЕ фильтрует уровни по возрасту, и это осознанно. Первая редакция
    резала их окном в 50 баров — как делала прежняя логика, где сравнивались все
    бары подряд. Для ПИВОТНЫХ уровней окно в 50 баров пусто почти всегда: замер
    дал eqh_near=0% на 1h (16 пар из 16). По канону зона ликвидности живёт, пока
    её не сняли, а не N баров; релевантность обеспечивает сам признак `*_near`.
    Параметр оставлен в сигнатуре ради совместимости вызовов.
    """
    from core.smc.smc_engine import detect_equal_levels

    out = {"eqh_near": False, "eql_near": False,
           "eqh_level": None, "eql_level": None,
           "eqh_count": 0, "eql_count": 0}

    pairs = detect_equal_levels(df) or []
    if not pairs:
        return out

    cur = float(df["close"].iloc[-1])
    if cur <= 0:
        return out

    # Радиус «рядом» масштабируется волатильностью ТФ, а threshold_pct служит ПОЛОМ.
    # Замер 02.09: на 1h ближайшие эталонные уровни лежат в 10–25% от цены (400 часов
    # хода), и фиксированный 1% давал eqh_near=False на всех 16 парах — признак мёртв
    # с другой стороны. На 15m те же уровни в 0.04–0.94%. Один и тот же радиус
    # не может обслуживать оба ТФ: та же логика, что с порогом FVG.
    radius = threshold_pct
    try:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                       axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        if atr == atr and atr > 0:
            radius = max(threshold_pct, atr / cur)
    except Exception:
        pass

    # Отсев СНЯТЫХ уровней — как в web/structure_terminal.py:1040, где эта логика
    # уже была: EQH живёт, пока цена не прошла ВЫШЕ него, EQL — пока не ушла НИЖЕ.
    # Снятая ликвидность отработана, и терминал такие уровни не рисует. Без этого
    # флаг из снапа противоречил бы картинке: терминал берёт eqh_near из шины,
    # а уровни рисует своим отсевом (structure_terminal.py:1070).
    hi = df["high"].values
    lo = df["low"].values
    n = len(df)
    pos = {ts: k for k, ts in enumerate(df.index)}

    for lab, key in (("EQH", "eqh"), ("EQL", "eql")):
        levels = []
        for ts1, p1, ts2, p2, l in pairs:
            if l != lab:
                continue
            lvl = (float(p1) + float(p2)) / 2.0
            i2 = pos.get(ts2)
            if i2 is None:
                continue
            tail = slice(min(i2 + 1, n), n)
            swept = bool((hi[tail] > lvl).any()) if lab == "EQH" else bool((lo[tail] < lvl).any())
            if swept:
                continue
            levels.append(lvl)
        if not levels:
            continue
        best = min(levels, key=lambda v: abs(v - cur))
        # сколько уровней собралось вокруг найденного — это и есть плотность зоны
        cnt = sum(1 for v in levels if abs(v - best) / best <= radius) if best > 0 else 0
        out[f"{key}_level"] = round(best, 8)
        out[f"{key}_count"] = cnt
        out[f"{key}_near"] = abs(best - cur) / cur <= radius

    return out


def detect_equal_highs_lows(
    df: pd.DataFrame,
    threshold_pct: float = 0.01,  # 1% = "equal"
    lookback: int = 50,
) -> dict:
    """
    DEV-140: Детектор Equal Highs (EQH) и Equal Lows (EQL).

    EQH — два или более Swing High на одном уровне (±threshold_pct).
    EQL — два или более Swing Low на одном уровне.

    EQH/EQL — зоны скопления ликвидности (стоп-ордера трейдеров).
    Цена часто выходит за них (liquidity sweep), после чего разворачивается.

    Args:
        df: OHLCV DataFrame (минимум 10 баров).
        threshold_pct: допуск в долях (0.01 = 1%).
        lookback: количество последних баров для поиска.

    Returns:
        dict с ключами:
          eqh_near  (bool)         — EQH в радиусе threshold_pct от текущей цены
          eql_near  (bool)         — EQL в радиусе threshold_pct от текущей цены
          eqh_level (float | None) — уровень EQH (среднее двух high)
          eql_level (float | None) — уровень EQL (среднее двух low)
          eqh_count (int)          — сколько high совпало
          eql_count (int)          — сколько low совпало
    """
    result = {
        "eqh_near": False, "eql_near": False,
        "eqh_level": None, "eql_level": None,
        "eqh_count": 0,    "eql_count": 0,
    }

    if df is None or len(df) < 10:
        return result

    # ── ARCH-137.5: уровни берём у ЭТАЛОНА ──────────────────────────────────
    # Прежняя логика ниже сравнивала ВСЕ high с ВСЕМИ в окне 50 баров при
    # ФИКСИРОВАННОМ допуске 1% — то есть спрашивала не «есть ли равные вершины»,
    # а «ходила ли цена в коридоре 1%». Замер 02.09 (16 пар): eqh_near=True
    # у 75% пар на 1h и у 100% на 15m, «плотность кластера» 320 и 906 пар баров.
    # Признак был вырожден — как CHoCH до ARCH-137.5.
    # Эталон detect_equal_levels сравнивает соседние ПИВОТЫ с допуском 0.1×ATR
    # (адаптивным) и даёт 4.4 пары уровней на 1h — осмысленную величину.
    # На нём же стоят боевой IMPULSE-FIB, chart_builder и structure_terminal.
    # threshold_pct здесь остаётся радиусом «рядом с ценой», а равенство самих
    # уровней определяет эталон. Откат: config.yaml → smc.eq_canon: false
    if _use_eq_canon():
        try:
            return _eq_from_canon(df, threshold_pct=threshold_pct, lookback=lookback)
        except Exception as e:
            logger.debug("detect_equal_highs_lows canon error: %s", e, exc_info=True)
            # горячий путь падать не должен — идём прежней реализацией

    try:
        n = len(df)
        start = max(0, n - lookback)
        window = df.iloc[start:]
        current_price = float(df["close"].iloc[-1])

        highs = window["high"].tolist()
        lows  = window["low"].tolist()

        # ── Equal Highs ───────────────────────────────────────────────────────
        eqh_clusters: list = []
        for i in range(len(highs)):
            for j in range(i + 1, len(highs)):
                h_i, h_j = highs[i], highs[j]
                if h_i > 0 and abs(h_i - h_j) / h_i <= threshold_pct:
                    # Нашли пару равных high
                    level = (h_i + h_j) / 2
                    # Добавляем в кластер или создаём новый
                    merged = False
                    for cluster in eqh_clusters:
                        if abs(cluster["level"] - level) / cluster["level"] <= threshold_pct:
                            cluster["count"] += 1
                            cluster["level"] = (cluster["level"] + level) / 2
                            merged = True
                            break
                    if not merged:
                        eqh_clusters.append({"level": level, "count": 2})

        if eqh_clusters:
            # Берём самый "плотный" кластер
            best_eqh = max(eqh_clusters, key=lambda c: c["count"])
            result["eqh_level"] = round(best_eqh["level"], 8)
            result["eqh_count"] = best_eqh["count"]
            # near = уровень в радиусе threshold_pct от текущей цены
            if current_price > 0:
                result["eqh_near"] = (
                    abs(best_eqh["level"] - current_price) / current_price <= threshold_pct
                )

        # ── Equal Lows ────────────────────────────────────────────────────────
        eql_clusters: list = []
        for i in range(len(lows)):
            for j in range(i + 1, len(lows)):
                l_i, l_j = lows[i], lows[j]
                if l_i > 0 and abs(l_i - l_j) / l_i <= threshold_pct:
                    level = (l_i + l_j) / 2
                    merged = False
                    for cluster in eql_clusters:
                        if abs(cluster["level"] - level) / cluster["level"] <= threshold_pct:
                            cluster["count"] += 1
                            cluster["level"] = (cluster["level"] + level) / 2
                            merged = True
                            break
                    if not merged:
                        eql_clusters.append({"level": level, "count": 2})

        if eql_clusters:
            best_eql = max(eql_clusters, key=lambda c: c["count"])
            result["eql_level"] = round(best_eql["level"], 8)
            result["eql_count"] = best_eql["count"]
            if current_price > 0:
                result["eql_near"] = (
                    abs(best_eql["level"] - current_price) / current_price <= threshold_pct
                )

    except Exception as e:
        logger.debug("detect_equal_highs_lows error: %s", e)

    return result
