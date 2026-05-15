"""
HARD gate: dedup по уже открытым позициям.

Блокирует если по символу уже есть открытая сделка с тем же trade_mode.
Если trade_mode пустой — блокирует любую открытую сделку по символу
(старая логика trade_simulator.py:290-333 — bounce_mode для SWING+SCALP).

Использует ctx.open_trades (snapshot) — не запрашивает БД повторно.
"""
from __future__ import annotations

import json

from core.trading.gates.base import Gate, GateContext, GateResult, GateType


class DedupOpenGate(Gate):
    name = "dedup_open"
    gate_type = GateType.HARD

    async def check(self, ctx: GateContext) -> GateResult:
        if not ctx.open_trades:
            return self._pass()

        new_mode = ctx.policy.trade_mode or ""

        for tr in ctx.open_trades:
            if tr.get("symbol") != ctx.symbol:
                continue
            ex_features = {}
            raw_fjson = tr.get("features_json")
            if raw_fjson:
                try:
                    ex_features = json.loads(raw_fjson)
                except Exception:
                    ex_features = {}
            ex_mode = ex_features.get("trade_mode", "")

            if new_mode and ex_mode == new_mode:
                return self._drop(
                    f"open trade #{tr.get('id')} с trade_mode={new_mode}",
                    features={"existing_trade_id": tr.get("id"), "existing_mode": ex_mode},
                )
            if not new_mode:
                return self._drop(
                    f"open trade #{tr.get('id')} (без trade_mode)",
                    features={"existing_trade_id": tr.get("id")},
                )
            # new_mode задан и ex_mode другой → допускаем bounce (SWING+SCALP)

        return self._pass()
