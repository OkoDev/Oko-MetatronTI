"""
WT Specialist — Сфера 3 / CUBE-08.

Вычисляет wt_verdict из готового wt_snap (без API, без OHLCV загрузки).
Подписывается на WT_SNAP_UPDATED → публикует WT_VERDICT в PairContextBus.

Вердикты:
  EXHAUSTION          — несколько TF в OB или OS одновременно
  REVERSAL_SETUP      — WT кросс на 4h/1h при OB/OS зоне
  TREND_CONTINUATION  — atr_trend всех загруженных TF в одном направлении
  UNCLEAR             — недостаточно данных или смешанные сигналы

Формат wt_snap (из scan_loop.py):
  {
    "15m": {"wt1": float, "wt2": float, "zone": "OB"|"OS"|"N",
            "wt_cross": 0|1|-1, "atr_trend": 1|-1|0},
    "1h":  {...},
    "4h":  {...},
    "1d":  {...},
  }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("WTSpecialist")

# Порог для зоны OB/OS (wt1)
_OB_THRESHOLD = 60
_OS_THRESHOLD = -60

# Веса TF для выравнивания трендов (старшие весомее)
_TF_WEIGHT = {"1d": 4, "4h": 3, "1h": 2, "15m": 1, "5m": 1, "3m": 1}


def derive_wt_verdict(wt_snap: Dict[str, Any]) -> Optional[str]:
    """
    Вычисляет wt_verdict из wt_snap.

    Args:
        wt_snap: {tf → {wt1, wt2, zone, wt_cross, atr_trend}}

    Returns:
        "EXHAUSTION" | "REVERSAL_SETUP" | "TREND_CONTINUATION" | "UNCLEAR" | None
    """
    if not wt_snap:
        return None

    tfs = list(wt_snap.keys())
    if len(tfs) < 1:
        return None

    # ── 1. EXHAUSTION: несколько TF одновременно в OB или OS ──────────────
    ob_count = sum(1 for tf, d in wt_snap.items() if d.get("zone") == "OB")
    os_count = sum(1 for tf, d in wt_snap.items() if d.get("zone") == "OS")

    if ob_count >= 2 or os_count >= 2:
        label = "EXHAUSTION"
        direction = "SHORT" if ob_count >= 2 else "LONG"
        logger.debug(
            "WTSpecialist EXHAUSTION: OB=%d OS=%d direction=%s tfs=%s",
            ob_count, os_count, direction, tfs,
        )
        return label

    # ── 2. REVERSAL_SETUP: WT кросс на 4h или 1h при OB/OS зоне ──────────
    for htf in ("4h", "1h"):
        snap_htf = wt_snap.get(htf)
        if snap_htf is None:
            continue
        cross  = snap_htf.get("wt_cross", 0)
        zone   = snap_htf.get("zone", "N")
        if abs(cross) >= 1 and zone in ("OB", "OS"):
            logger.debug(
                "WTSpecialist REVERSAL_SETUP: %s cross=%d zone=%s", htf, cross, zone,
            )
            return "REVERSAL_SETUP"

    # ── 3. TREND_CONTINUATION: тренды всех TF совпадают ─────────────────────
    # wt_snap использует ключ "trend" ('UP'/'DOWN'), не "atr_trend" (int).
    # Shadow mode: вердикт возвращается, но VerdictAggregator его не блокирует
    # пока не накоплено достаточно данных (сейчас n≈48, нужно ≥150).
    trend_sum = 0
    trend_weight = 0
    for tf, d in wt_snap.items():
        t_str = d.get("trend", "")
        t = 1 if t_str == "UP" else -1 if t_str == "DOWN" else 0
        if t != 0:
            w = _TF_WEIGHT.get(tf, 1)
            trend_sum += t * w
            trend_weight += w

    if trend_weight > 0:
        alignment = abs(trend_sum) / trend_weight
        if alignment >= 0.7:
            logger.debug(
                "WTSpecialist TREND_CONTINUATION: alignment=%.2f sum=%d weight=%d",
                alignment, trend_sum, trend_weight,
            )
            return "TREND_CONTINUATION"

    return "UNCLEAR"


def get_wt_exhaustion_direction(wt_snap: Dict[str, Any]) -> str:
    """
    Определяет направление истощения рынка по EXHAUSTION вердикту.

    TR-007 13.04.2026: EXHAUSTION направленно-зависим:
      OB_bias (≥2 TF в OB) + LONG вход → WR=6.2% → WOULD_BLOCK нужен
      OS_bias (≥2 TF в OS) + LONG вход → WR=50% → PASS

    Returns:
        "BEARISH"  — ≥2 TF перекуплены (OB bias), SHORT давление → LONG BLOCK
        "BULLISH"  — ≥2 TF перепроданы (OS bias), LONG давление → SHORT BLOCK
        "NEUTRAL"  — неопределённо
    """
    if not wt_snap:
        return "NEUTRAL"
    ob_count = sum(1 for d in wt_snap.values() if d.get("zone") == "OB")
    os_count = sum(1 for d in wt_snap.values() if d.get("zone") == "OS")
    if ob_count >= 2:
        return "BEARISH"
    if os_count >= 2:
        return "BULLISH"
    return "NEUTRAL"
