"""
ARCH-113: TPSelector — Intelligent TP Gravity Engine.

Исследование 25.05.2026: 156K уровней, 20 пар, 2.4 года.
score = gravity / dist_pct^1.5 (alpha=1.5 доказан → top10% = 83% reach)
FVG <0.3R = 73-86% reach за 24h. Cluster 2+ sources: +14-21% lift.

Возвращает:
  TP1 = ближайший кластер dist <1R (LTF быстрый выход)
  TP2 = максимальный score dist >1R (HTF основная позиция, пирамидинг)
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Веса источников (из исследования 156K уровней) ──────────────────────────
_WEIGHTS: Dict[str, float] = {
    "fvg_5m":  2.0,
    "fvg_15m": 3.0,
    "fvg_1h":  4.0,
    "fvg_4h":  5.0,
    "pdh":     3.0,   # prev day high (R1 1D proxy)
    "pdl":     3.0,
    "pwh":     4.0,   # prev week high (R1 1W proxy)
    "pwl":     4.0,
    "psycho":  2.0,   # round psychological levels
    "swing":   2.5,   # swing high/low
    "std_r1":  2.0,
    "std_r2":  1.0,
    "std_s1":  2.0,
    "std_s2":  1.0,
}


@dataclass
class _Magnet:
    price: float
    source: str     # 'fvg_1h', 'psycho', 'pdh', ...
    weight: float


@dataclass
class TPCandidate:
    price: float
    gravity: float
    dist_pct: float   # % от entry
    dist_R: float     # в единицах SL-дистанции
    score: float      # gravity / dist_pct^alpha
    sources: List[str] = field(default_factory=list)
    label: str = ""   # для tp_source в БД: 'fvg_1h+psycho@47200'


class TPSelector:
    """Выбирает TP1 (LTF) и TP2 (HTF) через gravity scoring кластеров."""

    EPS_PCT   = 0.5   # ±% для кластеризации
    ALPHA     = 1.5   # score = gravity / dist^alpha
    MAX_DIST  = 15.0  # % — дальше не смотрим
    MIN_SCORE = 0.0   # фильтр

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        self.eps     = float(cfg.get("tp_selector_eps_pct",     self.EPS_PCT))
        self.alpha   = float(cfg.get("tp_selector_alpha",       self.ALPHA))
        self.max_dist= float(cfg.get("tp_selector_max_dist_pct",self.MAX_DIST))
        # Shadow diagnostics — заполняется в select() для последующей записи в features_json
        self.last_diagnostics: Dict[str, Any] = {}

    def select(
        self,
        entry: float,
        direction: str,        # 'LONG' | 'SHORT'
        sl_dist_pct: float,    # % SL от entry (для R-расчёта)
        market_context: Any,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[TPCandidate], Optional[TPCandidate]]:
        """
        Возвращает (tp1, tp2). При ошибке или отсутствии уровней — (None, None).
        tp1 = ближайший кластер dist <1R
        tp2 = максимальный score dist >1R (HTF, для пирамидинга)
        """
        _t0 = time.monotonic()
        self.last_diagnostics = {
            "magnets_count": 0, "clusters_count": 0,
            "tp1_found": False, "tp2_found": False,
            "skip_reason": None, "elapsed_ms": 0,
        }
        if not entry or entry <= 0 or sl_dist_pct <= 0:
            self.last_diagnostics["skip_reason"] = "invalid_input"
            self.last_diagnostics["elapsed_ms"] = round((time.monotonic() - _t0) * 1000, 1)
            return None, None

        try:
            magnets = self._collect_magnets(entry, direction, market_context)
        except Exception as e:
            logger.debug("[TPSelector] _collect_magnets failed: %s", e)
            self.last_diagnostics["skip_reason"] = f"collect_error:{type(e).__name__}"
            self.last_diagnostics["elapsed_ms"] = round((time.monotonic() - _t0) * 1000, 1)
            return None, None

        self.last_diagnostics["magnets_count"] = len(magnets)
        if not magnets:
            self.last_diagnostics["skip_reason"] = "no_magnets"
            self.last_diagnostics["elapsed_ms"] = round((time.monotonic() - _t0) * 1000, 1)
            logger.debug("[TPSelector] нет магнитов для %s", getattr(market_context, "symbol", "?"))
            return None, None

        clusters = self._cluster(magnets, entry)
        self.last_diagnostics["clusters_count"] = len(clusters)
        if not clusters:
            self.last_diagnostics["skip_reason"] = "no_clusters"
            self.last_diagnostics["elapsed_ms"] = round((time.monotonic() - _t0) * 1000, 1)
            return None, None

        # Считаем dist_R и score для каждого кластера
        for c in clusters:
            c.dist_R = c.dist_pct / sl_dist_pct if sl_dist_pct > 0 else 0.0
            c.score  = self._score(c.gravity, c.dist_pct)

        clusters = [c for c in clusters if c.score > self.MIN_SCORE]
        clusters.sort(key=lambda c: c.dist_pct)

        tp1 = self._pick_tp1(clusters)
        tp2 = self._pick_tp2(clusters, tp1)

        self.last_diagnostics["tp1_found"] = tp1 is not None
        self.last_diagnostics["tp2_found"] = tp2 is not None
        self.last_diagnostics["elapsed_ms"] = round((time.monotonic() - _t0) * 1000, 1)

        if tp1:
            logger.info("[ARCH-113] TP1=%.6g dist=%.2f%% (%.2fR) score=%.3f src=%s",
                        tp1.price, tp1.dist_pct, tp1.dist_R, tp1.score, tp1.label)
        if tp2:
            logger.info("[ARCH-113] TP2=%.6g dist=%.2f%% (%.2fR) score=%.3f src=%s",
                        tp2.price, tp2.dist_pct, tp2.dist_R, tp2.score, tp2.label)

        return tp1, tp2

    # ── Сбор магнитов ─────────────────────────────────────────────────────────

    def _collect_magnets(self, entry: float, direction: str, ctx: Any) -> List[_Magnet]:
        magnets: List[_Magnet] = []
        is_long = direction == "LONG"

        symbol = getattr(ctx, "symbol", "")

        # 1. FVG из smc_context
        smc = getattr(ctx, "smc_context", None)
        if smc is not None:
            fvg_analysis = getattr(smc, "fvg", None)
            if fvg_analysis is not None:
                # LONG ищет Bear FVG ВЫШЕ цены (магнит заполнения)
                # SHORT ищет Bull FVG НИЖЕ цены
                fvg_list = (
                    getattr(fvg_analysis, "active_bear", []) if is_long
                    else getattr(fvg_analysis, "active_bull", [])
                )
                for fvg in (fvg_list or []):
                    mid = getattr(fvg, "midpoint", None)
                    if mid and mid > 0:
                        if (is_long and mid > entry) or (not is_long and mid < entry):
                            magnets.append(_Magnet(mid, "fvg_1h", _WEIGHTS["fvg_1h"]))

        # 2. Swing high/low
        if is_long:
            sw = getattr(ctx, "swing_high", None)
            if sw and sw > entry:
                magnets.append(_Magnet(sw, "swing", _WEIGHTS["swing"]))
        else:
            sw = getattr(ctx, "swing_low", None)
            if sw and 0 < sw < entry:
                magnets.append(_Magnet(sw, "swing", _WEIGHTS["swing"]))

        # 3. Pivot cache — PDH(R1_1D), PWH(R1_1W), R2_1D
        pivot_cache = getattr(ctx, "pivot_cache_1d_1w", {}) or {}
        piv_1d = pivot_cache.get(f"{symbol}_1D") or {}
        piv_1w = pivot_cache.get(f"{symbol}_1W") or {}

        if is_long:
            # PDH proxy = R1 1D (выше entry)
            r1_1d = piv_1d.get("R1")
            if r1_1d and r1_1d > entry:
                magnets.append(_Magnet(r1_1d, "pdh", _WEIGHTS["pdh"]))
            r2_1d = piv_1d.get("R2")
            if r2_1d and r2_1d > entry:
                magnets.append(_Magnet(r2_1d, "std_r2", _WEIGHTS["std_r2"]))
            # PWH proxy = R1 1W
            r1_1w = piv_1w.get("R1")
            if r1_1w and r1_1w > entry:
                magnets.append(_Magnet(r1_1w, "pwh", _WEIGHTS["pwh"]))
        else:
            s1_1d = piv_1d.get("S1")
            if s1_1d and 0 < s1_1d < entry:
                magnets.append(_Magnet(s1_1d, "pdl", _WEIGHTS["pdl"]))
            s2_1d = piv_1d.get("S2")
            if s2_1d and 0 < s2_1d < entry:
                magnets.append(_Magnet(s2_1d, "std_s2", _WEIGHTS["std_s2"]))
            s1_1w = piv_1w.get("S1")
            if s1_1w and 0 < s1_1w < entry:
                magnets.append(_Magnet(s1_1w, "pwl", _WEIGHTS["pwl"]))

        # 4. Психологические уровни
        for lvl in self._psycho_levels(entry, direction):
            magnets.append(_Magnet(lvl, "psycho", _WEIGHTS["psycho"]))

        # Фильтр по MAX_DIST
        result = []
        for m in magnets:
            dist = abs(m.price - entry) / entry * 100
            if 0.05 < dist <= self.max_dist:
                result.append(m)

        return result

    # ── Психологические уровни ────────────────────────────────────────────────

    def _psycho_levels(self, price: float, direction: str) -> List[float]:
        """Круглые уровни выше (LONG) или ниже (SHORT) entry."""
        if price <= 0:
            return []
        is_long = direction == "LONG"
        try:
            mag = 10 ** int(math.log10(price))
        except (ValueError, OverflowError):
            return []

        levels = set()
        for step in [mag, mag / 2, mag / 5, mag / 10]:
            if step <= 0:
                continue
            if is_long:
                lvl = math.ceil(price / step) * step
                if lvl > price * 1.001:
                    levels.add(round(lvl, 8))
            else:
                lvl = math.floor(price / step) * step
                if lvl < price * 0.999:
                    levels.add(round(lvl, 8))

        return sorted(levels)[:4]

    # ── Кластеризация ±eps% ───────────────────────────────────────────────────

    def _cluster(self, magnets: List[_Magnet], entry: float) -> List[TPCandidate]:
        if not magnets:
            return []

        magnets = sorted(magnets, key=lambda m: m.price)
        clusters: List[TPCandidate] = []
        used = [False] * len(magnets)

        for i, m in enumerate(magnets):
            if used[i]:
                continue
            group = [m]
            used[i] = True
            for j in range(i + 1, len(magnets)):
                if used[j]:
                    continue
                if abs(magnets[j].price - m.price) / m.price * 100 <= self.eps:
                    group.append(magnets[j])
                    used[j] = True

            # Центр кластера — взвешенное среднее
            total_w = sum(g.weight for g in group)
            center   = sum(g.price * g.weight for g in group) / total_w
            gravity  = total_w
            dist_pct = abs(center - entry) / entry * 100
            sources  = [g.source for g in group]
            label    = "+".join(sorted(set(sources))) + f"@{center:.6g}"

            clusters.append(TPCandidate(
                price=center,
                gravity=gravity,
                dist_pct=dist_pct,
                dist_R=0.0,  # будет заполнено позже
                score=0.0,
                sources=sources,
                label=label,
            ))

        return clusters

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(self, gravity: float, dist_pct: float) -> float:
        if dist_pct <= 0:
            return 0.0
        return gravity / (dist_pct ** self.alpha)

    # ── Выбор TP1 и TP2 ──────────────────────────────────────────────────────

    def _pick_tp1(self, clusters: List[TPCandidate]) -> Optional[TPCandidate]:
        """TP1: ближайший кластер с dist <1R и score > 0."""
        candidates = [c for c in clusters if c.dist_R < 1.0 and c.score > 0]
        if not candidates:
            # расширяем до <2R если ничего нет
            candidates = [c for c in clusters if c.dist_R < 2.0 and c.score > 0]
        if not candidates:
            return None
        # Ближайший с весом > 1 источника — предпочтительно кластер
        multi = [c for c in candidates if len(c.sources) >= 2]
        return (min(multi, key=lambda c: c.dist_pct) if multi
                else min(candidates, key=lambda c: c.dist_pct))

    def _pick_tp2(
        self,
        clusters: List[TPCandidate],
        tp1: Optional[TPCandidate],
    ) -> Optional[TPCandidate]:
        """TP2: максимальный score среди кластеров дальше TP1 (dist >1R)."""
        tp1_dist = tp1.dist_pct if tp1 else 0.0
        # Минимум 1.5x дальше TP1 для чёткого разделения (lift +20.9% из исследования)
        min_dist = max(tp1_dist * 1.5, tp1_dist + 1.0) if tp1_dist > 0 else 2.0
        candidates = [c for c in clusters if c.dist_pct >= min_dist and c.score > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.score)
