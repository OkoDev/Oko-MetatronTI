# -*- coding: utf-8 -*-
"""Ошибка проверки перед входом ЗАПРЕЩАЕТ вход (13.10.2026, находка F03 внешнего аудита).

До правки `_run_gate_safe` при исключении возвращал `passed=True`: проверка, которая упала, пропускала сделку.
Егор 13.10: «"Да" на запрет входа при ошибке проверки».
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.trading import trade_router as tr
from core.trading.gates.base import Gate, GateType


class _Boom(Gate):
    name = "boom"

    def __init__(self, gate_type):
        self.gate_type = gate_type

    async def check(self, ctx):
        raise RuntimeError("нет данных")


class _Fine(Gate):
    name = "fine"
    gate_type = GateType.SOFT

    async def check(self, ctx):
        return self._penalty(7, "штраф")


def test_exception_in_hard_gate_blocks():
    res = asyncio.run(tr._run_gate_safe(_Boom(GateType.HARD), ctx=None))
    assert res.passed is False and "нет данных" in res.reason
    assert res.features.get("gate_exception") == "нет данных"


def test_exception_in_soft_gate_blocks_too():
    res = asyncio.run(tr._run_gate_safe(_Boom(GateType.SOFT), ctx=None))
    assert res.passed is False


def test_healthy_gate_result_is_untouched():
    res = asyncio.run(tr._run_gate_safe(_Fine(), ctx=None))
    assert res.passed is True and res.strength_penalty == 7


def _router(soft_gate, monkeypatch):
    """Роутер без инициализации: до гейтов нужны только политика источника, режим и снимок открытых сделок."""
    r = object.__new__(tr.TradeRouter)
    r.config, r.bot = {}, None
    r._hard_gates, r._soft_gates = [], {soft_gate.name: soft_gate}
    r._snapshot_open_trades = lambda: []
    calls = {"drop": [], "published": []}

    async def _record_drop(ctx, res):
        calls["drop"].append((res.gate_name, res.reason))

    async def _publish(ctx, hard, soft):
        calls["published"].append(list(hard))

    async def _regime(bot, symbol):
        return None

    r._record_drop, r._publish_position_dropped = _record_drop, _publish
    policy = SimpleNamespace(soft_gates_enabled=[soft_gate.name], min_strength=0, trade_mode=None)
    monkeypatch.setattr(tr.SourcePolicy, "from_config", staticmethod(lambda config, source: policy))
    monkeypatch.setattr(tr, "_safe_regime", _regime)
    return r, calls


def test_submit_drops_trade_when_soft_gate_crashes(monkeypatch):
    """Сквозной путь: упавшая МЯГКАЯ проверка раньше давала вход без штрафа — теперь сделки нет, отказ записан."""
    r, calls = _router(_Boom(GateType.SOFT), monkeypatch)
    rec = SimpleNamespace(symbol="TEST/USDT:USDT", direction="LONG", signal_type="x", overall_strength=80,
                          supporting_signals=[])
    out = asyncio.run(r.submit(rec, source="unit"))
    assert out.is_registered is False and out.trade_id is None
    assert out.hard_drops and out.hard_drops[0][0] == "boom"
    assert calls["drop"] and calls["published"], "отказ обязан попасть в журнал и в шину"
