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
    """Сфера 4 / SMC Sub-куб. compute_and_publish() — единый вход.

    🔑 05.10 КЭШ ПО ЗАКРЫТОМУ БАРУ. Замер [SCAN-PERF] трижды показал: SMC — единственный
    настоящий потребитель цикла скана (1.2-1.4 с на пару × 565 пар ≈ 750 с CPU за круг,
    98% блока «детекторы и прочее»). При этом структура (OB / FVG / BOS / CHoCH / OTE)
    строится ПО ЗАКРЫТЫМ БАРАМ: пока новый бар не закрылся, ответ не может измениться.
    А цикл скана идёт 3-7 минут против 15-минутного бара — то есть одно и то же считалось
    по 2-5 раз подряд.
    🔴 Почему кэшировать можно ЦЕЛИКОМ: current_price в расчёте НЕ участвует — он только
    кладётся в готовый snap (ключ _current_price) для подписчиков шины. Поэтому при попадании
    в кэш достаточно подставить свежую цену в копию снимка.
    Тот же приём уже работает в волновом лупе (ctx_seen → «тот же 4h-бар»).
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}     # symbol → (ключ баров, snap без цены)
        self._stats: Dict[str, int] = {}     # hit/miss — видно в логе, а не на словах

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
        # ── кэш по закрытому бару ────────────────────────────────────────────
        _key = self._bars_key(ohlcv_by_tf)
        if _key is not None:
            _hit = getattr(self, "_cache", {}).get(symbol)
            if _hit is not None and _hit[0] == _key:
                self._stats["hit"] = self._stats.get("hit", 0) + 1
                snap = dict(_hit[1])          # копия: подписчики не должны править кэш
                if current_price and current_price > 0:
                    snap["_current_price"] = float(current_price)
                if ctx_bus is not None:
                    self.publish_snap(symbol, snap, ctx_bus)
                return snap
        self._stats["miss"] = self._stats.get("miss", 0) + 1

        snap = None
        try:
            snap = build_smc_snapshot(symbol, ohlcv_by_tf)
        except Exception as e:
            logger.debug("[SMCSubCube] %s build_smc_snapshot error: %s", symbol, e)
            return None
        if not snap:
            return None

        # Вердикт ATR-тренда 1h/4h (ATR_TREND_BULL_STRONG / …_WEAK / ATR_TREND_BEAR_* / ATR_TREND_NONE)
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

        # в кэш кладём БЕЗ текущей цены: она меняется каждый цикл и к структуре не относится
        if _key is not None:
            _store = dict(snap)
            _store.pop("_current_price", None)
            if not hasattr(self, "_cache"):
                self._cache = {}
            self._cache[symbol] = (_key, _store)

        # Публикация в Bus (те же события — обратная совместимость)
        if ctx_bus is not None:
            self.publish_snap(symbol, snap, ctx_bus)

        return snap

    @staticmethod
    def _bars_key(ohlcv_by_tf: Dict[str, pd.DataFrame]):
        """Отпечаток входных данных: время последнего бара КАЖДОГО ТФ.

        Любое обновление любого ТФ меняет ключ и честно инвалидирует кэш. None — если
        данных нет или время бара взять неоткуда: тогда кэш не используется вовсе.

        🔴 13.10.2026 (F01 внешнего аудита): время берётся из колонки `time`. У свечей бота RangeIndex и окно
        фиксированной длины — `df.index[-1]` был НОМЕРОМ СТРОКИ, ключ не менялся, и структура в шине замерзала
        на часы (лог: hit 48 237 / miss 1 087 за 10 ч при 3m-барах на входе). Индекс — только для DatetimeIndex."""
        try:
            parts = []
            for tf in sorted(ohlcv_by_tf or {}):
                df = ohlcv_by_tf.get(tf)
                if df is None or len(df) == 0:
                    continue
                if "time" in df.columns:
                    last = df["time"].iloc[-1]
                elif isinstance(df.index, pd.DatetimeIndex):
                    last = df.index[-1]
                else:
                    return None                  # номер строки временем не считаем — лучше без кэша
                parts.append((tf, int(len(df)), str(last)))
            return tuple(parts) or None
        except Exception:                                        # noqa: BLE001
            return None

    def cache_stats(self) -> Dict[str, int]:
        """hit/miss для лога — чтобы прореживание было видно, а не предполагалось."""
        return dict(getattr(self, "_stats", {}))

    def publish_snap(self, symbol: str, snap: Dict[str, Any], ctx_bus: Any) -> None:
        """Публикация готового snap в Bus — отдельно от расчёта (BOT-LOOP-OFFLOAD 11.07:
        scan_loop считает snap в to_thread с ctx_bus=None, публикует этим методом из
        event loop — подписчики шины не thread-safe)."""
        try:
            from core.context.pair_context import SphereEvent
            ctx_bus.publish(symbol, SphereEvent.SMC_SNAP_UPDATED, snap)
            verdict = snap.get("smc_verdict")
            if verdict:
                ctx_bus.publish(symbol, SphereEvent.SMC_VERDICT, {
                    "label": verdict, "confidence": 0.5,
                })
        except Exception as e:
            logger.debug("[SMCSubCube] %s bus publish error: %s", symbol, e)


# Singleton (как PivotCalculatorFixed) — переиспользуем между парами
_INSTANCE: Optional[SMCSubCube] = None


def get_smc_sub_cube() -> SMCSubCube:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SMCSubCube()
    return _INSTANCE
