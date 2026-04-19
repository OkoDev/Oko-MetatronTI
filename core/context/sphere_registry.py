"""
SphereRegistry — Сфера 12 / Self-Diagnostics / Куб Метатрона.

Отслеживает здоровье всех 13 сфер Куба:
  - Когда каждая сфера последний раз публиковала событие
  - Сколько событий от каждой сферы
  - Какие рёбра (подписки) активны

Использование:
  registry = SphereRegistry(pair_context_bus)
  registry.wire_subscriptions(bus)   # подписывается на ВСЕ типы событий
  stats = registry.health_check()    # → dict со статусом каждой сферы
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("SphereRegistry")


# Маппинг: тип события → сфера-источник
_EVENT_TO_SPHERE = {
    "ohlcv_updated":     1,
    "tick_price":        2,
    "volume_spike":      2,
    "wt_verdict":        3,
    "wt_snap_updated":   3,
    "smc_verdict":       4,
    "smc_snap_updated":  4,
    "cross_market":      5,
    "regime_updated":    6,
    "signal_detected":   7,
    "anomaly_detected":  7,
    "divergence_found":  7,
    "pivot_touch":       7,
    "pivot_snap_updated": 8,
    "narrative_built":   9,
    "tsl_moved":         10,
    "tp1_hit":           10,
    "position_closed":   10,
    "trade_closed":      11,
    "cascade_updated":   11,
    "ote_zone_set":      11,
    "sphere_health":     12,
}

SPHERE_NAMES = {
    1: "DataCollector",
    2: "WSFeed",
    3: "MTF WT Specialist",
    4: "MTF SMC Specialist",
    5: "Cross-Market Node",
    6: "Market Regime",
    7: "Signal Detectors",
    8: "Pivot Levels",
    9: "Narrative Builder",
    10: "Exit Manager",
    11: "Post-Trade Analyser",
    12: "Self-Diagnostics",
    0: "Central Hub (EventBus)",
}


class SphereRegistry:
    """Мониторинг здоровья 13 сфер Куба Метатрона."""

    def __init__(self, bus=None) -> None:
        self._bus = bus
        self._sphere_events: Dict[int, int] = {i: 0 for i in range(13)}
        self._sphere_last_update: Dict[int, Optional[datetime]] = {i: None for i in range(13)}
        self._start_time = datetime.now(timezone.utc)

    def wire_subscriptions(self, bus) -> None:
        """Подписывается на ВСЕ типы событий для диагностики."""
        from core.context.pair_context import SphereEvent

        all_events = [
            SphereEvent.OHLCV_UPDATED, SphereEvent.TICK_PRICE, SphereEvent.VOLUME_SPIKE,
            SphereEvent.WT_VERDICT, SphereEvent.WT_SNAP_UPDATED,
            SphereEvent.SMC_VERDICT, SphereEvent.SMC_SNAP_UPDATED,
            SphereEvent.CROSS_MARKET, SphereEvent.REGIME_UPDATED,
            SphereEvent.SIGNAL_DETECTED, SphereEvent.ANOMALY_DETECTED,
            SphereEvent.DIVERGENCE_FOUND, SphereEvent.PIVOT_TOUCH,
            SphereEvent.PIVOT_SNAP_UPDATED, SphereEvent.NARRATIVE_BUILT,
            SphereEvent.TSL_MOVED, SphereEvent.TP1_HIT, SphereEvent.POSITION_CLOSED,
            SphereEvent.TRADE_CLOSED, SphereEvent.CASCADE_UPDATED,
            SphereEvent.OTE_ZONE_SET,
        ]
        for event in all_events:
            bus.subscribe(event, self._on_any_event)

        logger.info("[SphereRegistry] подписан на %d типов событий", len(all_events))

    def _on_any_event(self, symbol: str, data: dict) -> None:
        """Обработчик всех событий — обновляет счётчики сфер."""
        # Определяем сферу по данным или по стеку вызовов
        event_type = data.get("_event_type")  # если передали
        sphere_id = None
        if event_type:
            sphere_id = _EVENT_TO_SPHERE.get(event_type)

        # Fallback: пытаемся определить по содержимому data
        if sphere_id is None:
            if "wt1" in data or "wt_snap" in data:
                sphere_id = 3
            elif "regime" in data:
                sphere_id = 6
            elif "signal_type" in data:
                sphere_id = 7
            elif "trade_id" in data and "status" in data:
                sphere_id = 10
            elif "cascade_count" in data:
                sphere_id = 11
            elif "price" in data:
                sphere_id = 2
            else:
                sphere_id = 0  # Central Hub

        now = datetime.now(timezone.utc)
        self._sphere_events[sphere_id] = self._sphere_events.get(sphere_id, 0) + 1
        self._sphere_last_update[sphere_id] = now

    def health_check(self) -> dict:
        """
        Проверяет здоровье всех сфер.

        Returns:
            {
                "spheres": {1: {"name": ..., "events": N, "last_update": ..., "status": "OK"/"STALE"/"DEAD"}, ...},
                "total_events": N,
                "active_spheres": N,
                "uptime_sec": N,
            }
        """
        now = datetime.now(timezone.utc)
        uptime = (now - self._start_time).total_seconds()
        result = {
            "spheres": {},
            "total_events": sum(self._sphere_events.values()),
            "active_spheres": 0,
            "uptime_sec": int(uptime),
        }

        for sphere_id in range(13):
            events = self._sphere_events.get(sphere_id, 0)
            last = self._sphere_last_update.get(sphere_id)

            if events == 0:
                status = "DEAD"
            elif last is None:
                status = "DEAD"
            else:
                age_sec = (now - last).total_seconds()
                if age_sec < 300:       # < 5 мин
                    status = "OK"
                elif age_sec < 3600:    # < 1 час
                    status = "STALE"
                else:
                    status = "DEAD"

            if status == "OK":
                result["active_spheres"] += 1

            result["spheres"][sphere_id] = {
                "name": SPHERE_NAMES.get(sphere_id, f"Sphere {sphere_id}"),
                "events": events,
                "last_update": last.isoformat() if last else None,
                "status": status,
            }

        return result

    def summary_text(self) -> str:
        """Компактный текст для /status и дашборда."""
        hc = self.health_check()
        lines = [f"Куб Метатрона: {hc['active_spheres']}/13 сфер OK | {hc['total_events']} событий | uptime {hc['uptime_sec']//60}m"]
        for sid in range(13):
            s = hc["spheres"][sid]
            icon = {"OK": "+", "STALE": "~", "DEAD": "x"}[s["status"]]
            lines.append(f"  [{icon}] S{sid:02d} {s['name']}: {s['events']} evt")
        return "\n".join(lines)
