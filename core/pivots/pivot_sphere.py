"""
PivotSphere — Сфера 8 Куба Метатрона (ARCH-123).

Формализует публикацию pivot-уровней в SharedContextBus. Снаружи = сфера Куба,
внутри = обёртка над PivotCalculatorFixed (Singleton + кэш уже есть).

Заменяет inline-блок в scan_loop. Добавляет `fibonacci_equiv` — карту
соответствия pivot-уровней Fibonacci-уровням (ENCYCLOPEDIA Сфера 8):
R2/S2 ≈ 0.618 = OTE зоны, R3/S3 ≈ 1.0 extension, R1/S1 ≈ 0.382, PP ≈ 0.5.

Потребители читают `bus.get(sym).pivot_snap` вместо прямого pivot_cache.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("PivotSphere")

# Pivot-уровень → Fibonacci-эквивалент (прокси от дневного диапазона).
# R2/S2 = OTE зоны (0.618), R3/S3 = extension (1.0). См. ENCYCLOPEDIA Сфера 8.
FIB_EQUIV: Dict[str, float] = {
    "R3": 1.000,   # extension вверх (цель волны 3 → экстремум)
    "R2": 0.618,   # OTE зона вверх (цель LONG)
    "R1": 0.382,
    "PP": 0.500,   # центр равновесия дня
    "S1": 0.382,
    "S2": 0.618,   # OTE зона вниз (цель SHORT)
    "S3": 1.000,   # extension вниз
}

_PIVOT_KEYS = ("PP", "S1", "S2", "S3", "R1", "R2", "R3")
_TFS = ("1W", "1D", "1M")


class PivotSphere:
    """Сфера 8. compute_and_publish() — единый вход публикации пивотов в Bus."""

    def compute_and_publish(
        self,
        symbol: str,
        pivot_calc: Any,
        ctx_bus: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Собирает pivot_snap из кэша PivotCalculatorFixed и публикует в Bus.

        Args:
            symbol:     пара
            pivot_calc: экземпляр PivotCalculatorFixed (с прогретым pivot_cache)
            ctx_bus:    SharedContextBus. None → только вернуть snap.

        Returns:
            pivot_snap {tf: {PP,S1..R3}} + ключ 'fibonacci_equiv', либо None.
        """
        if pivot_calc is None:
            return None
        raw = getattr(pivot_calc, "pivot_cache", None)
        if not raw:
            return None

        snap: Dict[str, Any] = {}
        for tf in _TFS:
            key = f"{symbol}_{tf}"
            if key in raw:
                lvls = raw[key]
                # Берём только числовые pivot-уровни (без period_label и пр.)
                snap[tf] = {k: lvls[k] for k in _PIVOT_KEYS if k in lvls}

        if not snap:
            return None

        snap["fibonacci_equiv"] = FIB_EQUIV

        if ctx_bus is not None:
            try:
                from core.context.pair_context import SphereEvent
                ctx_bus.publish(symbol, SphereEvent.PIVOT_SNAP_UPDATED, snap)
            except Exception as e:
                logger.debug("[PivotSphere] %s bus publish error: %s", symbol, e)

        return snap


_INSTANCE: Optional[PivotSphere] = None


def get_pivot_sphere() -> PivotSphere:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PivotSphere()
    return _INSTANCE
