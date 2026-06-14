"""
SMCSubCube — Сфера 4 как фрактальный Sub-куб Куба Метатрона (ARCH-120).

Единая точка входа SMC: снаружи = обычная сфера главного Куба, внутри объединяет
внутренние SMC-сферы (OB / FVG / Structure / Liquidity / OTE / Fibonacci) в один
SMCContext-snapshot + вердикт, публикует в SharedContextBus.

Заменяет два раздельных вызова в scan_loop (fast_smc_verdict + build_smc_snapshot).
Полный snap (с ARCH-120 liquidity) — единый источник для ВСЕХ потребителей:
NarrativeBuilder, OutcomePredictor, TPSelector (ARCH-122), Dashboard.

Архитектура (рой 4/4, гибридный подход как WaveService):
  - синхронный вызов в scan_loop (ordering гарантирован)
  - результат → Bus (SMC_SNAP_UPDATED + SMC_VERDICT)
  - данные уже в памяти (df загружены сканом), без API
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd

from core.smc.smc_snapshot import build_smc_snapshot
from core.smc.smc_specialist import fast_smc_verdict

logger = logging.getLogger("SMCSubCube")


class SMCSubCube:
    """Сфера 4 / SMC Sub-куб. compute_and_publish() — единый вход."""

    def compute_and_publish(
        self,
        symbol: str,
        ohlcv_by_tf: Dict[str, pd.DataFrame],
        ctx_bus: Any = None,
        df_1h: Optional[pd.DataFrame] = None,
        df_4h: Optional[pd.DataFrame] = None,
        current_price: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Вычисляет SMC snapshot + verdict, публикует в Bus.

        Args:
            symbol:        пара
            ohlcv_by_tf:   {tf: df} для snapshot (OB/FVG/BOS/CHoCH/Fib/liquidity по TF)
            ctx_bus:       SharedContextBus (publish). None → только вернуть snap.
            df_1h, df_4h:  для fast_smc_verdict (если None — берём из ohlcv_by_tf)
            current_price: текущая цена → кладём в snap ДО publish, чтобы snap был
                           самодостаточен в шине (FvgTouchListener и др. подписчики
                           берут цену из snap, не зависят от scan_loop).

        Returns:
            snap dict (с добавленным 'smc_verdict') либо None.
        """
        snap = None
        try:
            snap = build_smc_snapshot(symbol, ohlcv_by_tf)
        except Exception as e:
            logger.debug("[SMCSubCube] %s build_smc_snapshot error: %s", symbol, e)
            return None
        if not snap:
            return None

        # Вердикт (STRONG_BULL_ZONE / WEAK_* / STRONG_BEAR_ZONE / NEUTRAL)
        _df_1h = df_1h if df_1h is not None else ohlcv_by_tf.get("1h")
        _df_4h = df_4h if df_4h is not None else ohlcv_by_tf.get("4h")
        verdict = None
        try:
            verdict = fast_smc_verdict(_df_1h, _df_4h)
        except Exception as e:
            logger.debug("[SMCSubCube] %s fast_smc_verdict error: %s", symbol, e)
        snap["smc_verdict"] = verdict

        # current_price в snap → самодостаточность для подписчиков шины
        # (FvgTouchListener берёт цену отсюда; подписка не зависит от scan_loop)
        if current_price and current_price > 0:
            snap["_current_price"] = float(current_price)

        # Публикация в Bus (те же события — обратная совместимость)
        if ctx_bus is not None:
            try:
                from core.context.pair_context import SphereEvent
                ctx_bus.publish(symbol, SphereEvent.SMC_SNAP_UPDATED, snap)
                if verdict:
                    ctx_bus.publish(symbol, SphereEvent.SMC_VERDICT, {
                        "label": verdict, "confidence": 0.5,
                    })
            except Exception as e:
                logger.debug("[SMCSubCube] %s bus publish error: %s", symbol, e)

        return snap


# Singleton (как PivotCalculatorFixed) — переиспользуем между парами
_INSTANCE: Optional[SMCSubCube] = None


def get_smc_sub_cube() -> SMCSubCube:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SMCSubCube()
    return _INSTANCE
