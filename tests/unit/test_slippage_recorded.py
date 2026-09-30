"""Проскальзывание должно попадать в live_orders, иначе кост неизмерим.

Повод (30.09.2026): колонка `slip_pct` живёт с апреля, но роутер звал `position_manager.register()`
без неё — и в 20 436 ордерах за полгода стоял ноль. Из-за этого фактический кост неизвестен, а в
замерах и в выводах «косты съели эдж» используются записанные 0.35%, из которых подтверждена
только комиссия 0.09% (taker 0.045 × 2). Остальное было оценкой.

Здесь фиксируем ФОРМУЛУ и её знак: плюс = исполнились ХУЖЕ сигнала.
"""
from __future__ import annotations

import pytest

from core.trading.position_manager import PositionManager


def _slip(sig_px: float, fill_px: float, side: str) -> float:
    """Та же арифметика, что в trade_router: знак нормирован по направлению сделки."""
    s = (fill_px - sig_px) / sig_px * 100
    return round(s if side == "LONG" else -s, 4)


@pytest.mark.parametrize("side,sig,fill,expect_sign", [
    ("LONG", 100.0, 100.5, +1),    # купили дороже сигнала — хуже
    ("LONG", 100.0, 99.5, -1),     # купили дешевле — лучше
    ("SHORT", 100.0, 99.5, +1),    # продали дешевле сигнала — хуже
    ("SHORT", 100.0, 100.5, -1),   # продали дороже — лучше
])
def test_sign_means_worse_is_positive(side, sig, fill, expect_sign):
    v = _slip(sig, fill, side)
    assert (v > 0) == (expect_sign > 0), f"{side}: знак проскальзывания перепутан ({v})"
    assert abs(abs(v) - 0.5) < 1e-9


def test_zero_when_filled_at_signal():
    assert _slip(100.0, 100.0, "LONG") == 0.0
    assert _slip(100.0, 100.0, "SHORT") == 0.0


def test_register_stores_slippage(tmp_path):
    """Значение обязано долетать до БД — до 30.09 оно терялось в дефолте."""
    db = tmp_path / "t.db"
    pm = PositionManager(str(db))
    oid = pm.register(symbol="BTC/USDT:USDT", side="LONG", qty=1.0,
                      sim_trade_id=1, exchange_order_id="x1", slip_pct=0.1234)
    import sqlite3
    with sqlite3.connect(db) as c:
        got = c.execute("SELECT slip_pct FROM live_orders WHERE id=?", (oid,)).fetchone()[0]
    assert got == pytest.approx(0.1234), "проскальзывание не записалось"


def test_default_is_zero_not_none(tmp_path):
    """Без явного значения — 0.0, чтобы колонка оставалась числовой."""
    pm = PositionManager(str(tmp_path / "t2.db"))
    oid = pm.register(symbol="ETH/USDT:USDT", side="SHORT", qty=1.0)
    import sqlite3
    with sqlite3.connect(tmp_path / "t2.db") as c:
        got = c.execute("SELECT slip_pct FROM live_orders WHERE id=?", (oid,)).fetchone()[0]
    assert got == 0.0
