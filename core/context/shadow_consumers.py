# -*- coding: utf-8 -*-
"""Теневые потребители шины Куба: ребро «режим ↔ WT» (28.09.2026, решение Егора: вместо заглушек —
реализация потребителей; эти два — в тени).

Потребитель реагирует на событие и ЗАПИСЫВАЕТ своё решение, но торговлю не трогает. Причина — замеры
проекта: метка режима разделяет результат на 0.16 п.п. (аудит 04.09, C7a), WT-схема хуже шума на 25 из 25
суррогатов, ML-сфера WT хуже монетки. Поэтому сначала журнал, потом замер форварда от момента реакции
против случайного момента, и только потом решение о бое.

Решение считается СИНХРОННО в publish() — на том состоянии пары, что было в момент события (async-подписчик
видел бы уже следующий шаг скана: сразу после WT_SNAP_UPDATED публикуется WT_VERDICT). В фон уходит только
запись. Пишется лишь ВОЗНИКНОВЕНИЕ условия по паре (было ложно → стало истинно); первое наблюдение после
старта не считается возникновением — иначе каждый рестарт засорял бы журнал.

Журнал: oko_feed/external_data.db::cube_reactions_shadow
  ts (UTC, с) · symbol · consumer · event · decision · px (цена пары в шине в этот момент) · ctx_json
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Hashable, Optional

logger = logging.getLogger("CubeShadow")

DB = Path(__file__).resolve().parents[2] / "oko_feed" / "external_data.db"
WT_EXTREME = 60          # |wt1| 4h — граница зон OB/OS WT (та же, что в заглушке 12.04)


def _write(db: Path, row: tuple) -> None:
    c = sqlite3.connect(str(db), timeout=10)
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS cube_reactions_shadow (
            ts INTEGER NOT NULL, symbol TEXT NOT NULL, consumer TEXT NOT NULL, event TEXT,
            decision TEXT, px REAL, ctx_json TEXT)""")
        c.execute("INSERT INTO cube_reactions_shadow VALUES (?,?,?,?,?,?,?)", row)
        c.commit()
    finally:
        c.close()


class Onset:
    """True только на переходе ложно → истинно; первое наблюдение ключа — не переход."""

    def __init__(self) -> None:
        self._last: Dict[Hashable, bool] = {}

    def __call__(self, key: Hashable, cond: bool) -> bool:
        was = self._last.get(key)
        self._last[key] = cond
        return bool(cond) and was is False


def wire(bus: Any, db: Optional[Path] = None) -> int:
    """Подписать теневые потребители на шину. Возврат: сколько подписок добавлено."""
    from core.context.pair_context import SphereEvent

    db = db or DB
    onset = Onset()

    def _record(symbol: str, consumer: str, event: str, decision: str, ctx: Dict[str, Any]) -> None:
        row = (int(time.time()), symbol, consumer, event, decision,
               bus.get(symbol).tick_price, json.dumps(ctx, ensure_ascii=False, default=str))
        try:
            asyncio.get_running_loop().run_in_executor(None, _write, db, row)
        except RuntimeError:                      # нет цикла (скрипт/тест) — пишем сразу
            _write(db, row)
        logger.info("[CubeShadow] %s %s: %s", consumer, symbol, decision)

    def _wt4(state) -> Optional[float]:
        snap = (state.wt_snap or {}).get("4h") or {}
        return snap.get("wt1")

    # ── Сфера 6 → Сфера 3: режим перешёл в REVERSAL, а WT-вердикт всё ещё «продолжение тренда»
    def on_regime_for_wt(symbol: str, data: Dict[str, Any]) -> None:
        st = bus.get(symbol)
        cond = data.get("mode") == "REVERSAL" and st.wt_verdict == "TREND_CONTINUATION"
        if onset(("regime→wt", symbol), cond):
            _record(symbol, "regime→wt", SphereEvent.REGIME_UPDATED,
                    "WT-вердикт TREND_CONTINUATION устарел: режим перешёл в REVERSAL",
                    {"regime": data.get("regime"), "mode": data.get("mode"),
                     "wt_verdict": st.wt_verdict, "wt_confidence": st.wt_confidence,
                     "wt1_4h_prev_cycle": _wt4(st)})

    # ── Сфера 3 → Сфера 6: WT 4h ушёл в экстремум, а режим не REVERSAL
    def on_wt_for_regime(symbol: str, data: Dict[str, Any]) -> None:
        st = bus.get(symbol)
        wt1 = (data.get("4h") or {}).get("wt1")
        cond = wt1 is not None and abs(float(wt1)) > WT_EXTREME and st.reversal_mode != "REVERSAL"
        if onset(("wt→regime", symbol), cond):
            _record(symbol, "wt→regime", SphereEvent.WT_SNAP_UPDATED,
                    f"кандидат REVERSAL: WT 4h {float(wt1):+.0f} при режиме {st.reversal_mode}",
                    {"wt1_4h": wt1, "zone_4h": (data.get("4h") or {}).get("zone"),
                     "regime": st.regime, "reversal_mode": st.reversal_mode})

    bus.subscribe(SphereEvent.REGIME_UPDATED, on_regime_for_wt)
    bus.subscribe(SphereEvent.WT_SNAP_UPDATED, on_wt_for_regime)
    return 2
