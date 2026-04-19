"""
ARCH-78 / DEV-172: Entry Priority Matrix — shadow mode.

Оценивает качество входа по трём критериям:
  1. bias_ok   — ATR Trend на 1h согласован с направлением
  2. zone_ok   — цена в OS/OB зоне на 1h или 4h (структурная зона)
  3. trigger   — WT кросс на 15m в правильном направлении

Матрица приоритетов:
  P1 (лучший): все три критерия выполнены
  P2:           два из трёх (включая trigger)
  P3:           только trigger (без bias и zone)
  None:         нет trigger (вход не по структуре)

Модуль ТОЛЬКО ПИШЕТ в metadata/features_json. Никакой блокировки входов.
После 200+ сделок — анализируем WR по приоритетам.

Вызывается из: core/trading/trade_simulator.py → register_trade_async()
"""

from __future__ import annotations
from typing import Any, Dict, Optional


def evaluate_entry_priority(
    direction: str,
    wt_snap: Optional[Dict[str, Any]],
    atr_trend_1h_bias: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Оценить приоритет входа по матрице.

    Args:
        direction:           "LONG" | "SHORT"
        wt_snap:             {tf: {wt1, wt2, zone, wt_cross, atr_trend}}
                             zone: "OS"|"OB"|"N"
                             wt_cross: 1 (кросс вверх), -1 (вниз), 0 (нет)
                             atr_trend: 1 (вверх), -1 (вниз), 0 (нет)
        atr_trend_1h_bias:   "UP" | "DOWN" | None — из DEV-169 features_json

    Returns:
        {"priority": 1|2|3|None, "reason": str, "bias_ok": bool, "zone_ok": bool, "trigger": bool}
    """
    result = {"priority": None, "reason": "no_wt_snap", "bias_ok": False, "zone_ok": False, "trigger": False}

    if not wt_snap or not direction:
        return result

    is_long = direction.upper() == "LONG"

    # ── 1. bias_ok: ATR Trend на 1h согласован с направлением ──────────────────
    snap_1h = wt_snap.get("1h") or {}
    atr_1h = snap_1h.get("atr_trend", 0)

    bias_from_atr = (is_long and atr_1h == 1) or (not is_long and atr_1h == -1)
    bias_from_feature = (is_long and atr_trend_1h_bias == "UP") or \
                        (not is_long and atr_trend_1h_bias == "DOWN")
    bias_ok = bias_from_atr or bias_from_feature

    # ── 2. zone_ok: цена в OS/OB зоне на 1h или 4h ─────────────────────────────
    expected_zone = "OS" if is_long else "OB"
    zone_1h = snap_1h.get("zone", "N")
    snap_4h = wt_snap.get("4h") or {}
    zone_4h = snap_4h.get("zone", "N")
    zone_ok = zone_1h == expected_zone or zone_4h == expected_zone

    # ── 3. trigger: WT кросс на 15m в правильном направлении ───────────────────
    snap_15m = wt_snap.get("15m") or {}
    cross_15m = snap_15m.get("wt_cross", 0)
    zone_15m = snap_15m.get("zone", "N")

    # Кросс считается валидным если он в нужную сторону И (желательно) в зоне
    cross_dir_ok = (is_long and cross_15m == 1) or (not is_long and cross_15m == -1)
    trigger = cross_dir_ok  # сам факт кросса в нужном направлении

    result["bias_ok"] = bias_ok
    result["zone_ok"] = zone_ok
    result["trigger"] = trigger

    # ── Матрица приоритетов ─────────────────────────────────────────────────────
    if bias_ok and zone_ok and trigger:
        result["priority"] = 1
        result["reason"] = "bias+zone+trigger"
    elif trigger and (bias_ok or zone_ok):
        result["priority"] = 2
        parts = []
        if bias_ok:
            parts.append("bias")
        if zone_ok:
            parts.append("zone")
        result["reason"] = "trigger+" + "+".join(parts)
    elif trigger:
        result["priority"] = 3
        result["reason"] = "trigger_only"
        # Дополнительная проверка: кросс в зоне OS/OB на 15m повышает ценность P3
        if zone_15m == expected_zone:
            result["reason"] = "trigger_in_zone"
    elif bias_ok or zone_ok:
        result["priority"] = None
        result["reason"] = "no_trigger"
    else:
        result["priority"] = None
        result["reason"] = "no_signal"

    return result
