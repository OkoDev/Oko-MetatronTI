"""
Регрессия FIX-STOPS (28.08.2026): ЧАСТИЧНЫЙ ФИЛЛ ЛИМИТКИ не должен замораживать qty.

Воспроизводится сделка MOVR #58528 по реальному WS-логу: заявка на 389.9879 контрактов
залилась ТРЕМЯ порциями (14.32 → 157.42 → 389.99) по одной и той же цене 0.70290000.
Защита от pa-глюка BingX (`qty-скачок >×2.5 при неизменном ep = мусор`) писалась под
MARKET-вход, где добор двигает среднюю цену. У лимитки цена не двигается вовсе, поэтому
защита срабатывала на ЗАКОННОМ росте: store замерзал на 14.32, биржа держала 389.99.

Последствия, которые ловят тесты ниже:
  · CR-DELTA восстанавливал цену выхода от 14.32 → «exit=1.4138 / −101% / −15R»
    вместо реальных ap=0.7286 / ≈−1.2R;
  · `sphere.close()` закрыл бы 14.32 из 389.99.

🔴 Защита от НАСТОЯЩЕГО pa-глюка (LAB 13.07: 52.2→522.0 без филлов) обязана уцелеть —
это `test_pa_glitch_beyond_order_size_still_blocked`.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.execution.domain import Fill, FillEvent, Position, PositionEvent   # noqa: E402
from core.execution.position_store import PositionStore                      # noqa: E402

SYM = "MOVR/USDT:USDT"
ACC = 1
EP = 0.70290000
ORDER_QTY = 389.98790000


def _pos(pa, entry=EP, cr=None):
    return PositionEvent(ACC, Position(symbol=SYM, side="SHORT", qty=abs(pa), account=ACC,
                                       entry=entry or None, cum_realized=cr))


def _open_fill(order_qty=ORDER_QTY, ap=EP):
    """SELL+SHORT LIMIT FILLED = открывающий филл. BingX не шлёт `z`, поэтому
    total_qty = `q` = размер ЗАЯВКИ (одинаков на каждой порции)."""
    return FillEvent(ACC, Fill(
        symbol=SYM, side="SELL", pos_side="SHORT", order_id="2092725484489019392",
        order_type="LIMIT", status="FILLED", is_reduce_only=False,
        avg_price=ap, last_qty=14.3225, total_qty=order_qty))


def test_partial_fill_growth_is_accepted():
    """🔴 ГЛАВНЫЙ ТЕСТ: три порции по одной цене → store держит РЕАЛЬНЫЙ размер."""
    s = PositionStore()
    s.apply_position(_pos(14.3225))
    s.apply_fill(_open_fill())                 # заявка 389.99 известна с первой порции
    s.apply_position(_pos(157.4249))
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(157.4249)
    s.apply_position(_pos(ORDER_QTY))
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(ORDER_QTY)


def test_account_update_before_fill_event():
    """WS-порядок непостоянен: у MOVR ACCOUNT_UPDATE приходил и до, и после ORDER.
    Граница заявки известна с ПЕРВОГО филла, поэтому поздние доборы проходят."""
    s = PositionStore()
    s.apply_position(_pos(14.3225))
    s.apply_fill(_open_fill())
    s.apply_position(_pos(ORDER_QTY))          # ×27 разом — но в пределах заявки
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(ORDER_QTY)


def test_pa_glitch_beyond_order_size_still_blocked():
    """🔴 НЕГАТИВНЫЙ: pa-глюк BingX ×10 ЗА пределами заявки — по-прежнему отбивается."""
    s = PositionStore()
    s.apply_position(_pos(52.2))
    s.apply_fill(_open_fill(order_qty=52.2))   # заявка была 52.2
    s.apply_position(_pos(522.0))              # ×10 при том же ep, заявку превышает
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(52.2), "pa-глюк просочился"


def test_pa_glitch_without_any_fill_still_blocked():
    """Глюк до единого филла (границы заявки нет) — старое поведение сохраняется."""
    s = PositionStore()
    s.apply_position(_pos(52.2))
    s.apply_position(_pos(522.0))
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(52.2)


def test_order_qty_cleared_on_flat():
    """Цикл позиции завершён → граница заявки не должна течь в следующий цикл."""
    s = PositionStore()
    s.apply_position(_pos(14.3225))
    s.apply_fill(_open_fill())
    s.apply_position(_pos(0.0))
    s.apply_position(_pos(52.2))
    s.apply_position(_pos(522.0))              # новая позиция, филлов не было
    assert s.get(ACC, SYM, "SHORT").qty == pytest.approx(52.2)


def test_movr_exit_price_reconstructed_correctly():
    """Сквозной: с исправленным qty CR-DELTA даёт реальную цену выхода, а не 1.4138.

    Биржа показала ap=0.72864418 при Δcr=−10.18 USDT. Проверяем саму формулу
    восстановления (`entry + d·Δcr/qty`) на правильном и на отравленном qty.
    """
    delta = -10.18
    d = -1.0                                    # SHORT
    good = EP + d * delta / ORDER_QTY
    poisoned = EP + d * delta / 14.3225
    assert good == pytest.approx(0.7290, abs=1e-3), "правильный qty не даёт цену биржи"
    assert poisoned > 1.4, "воспроизведение отравленного расчёта сломалось"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
