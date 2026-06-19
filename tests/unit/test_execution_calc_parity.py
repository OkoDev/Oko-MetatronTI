"""Parity-тесты core.execution.calc — гарантия «один калькулятор» (Ф3.1 EXECUTION-REBUILD).

Цель: ExecutionCalc НЕ дублирует формулы, а переиспользует существующие источники, и
порт guards/leverage-клампов из order_manager.open_bracket воспроизводит поведение 1:1.
Дрейф формулы → тест падает. Дизайн: docs/EXECUTION_SPHERE_DESIGN.md §4.
"""
import math

import pytest

from core.execution import calc
from core.execution.domain import ExecMode
from core.exchange.bingx_client import ExecutionMode
from core.trading.position_sizer import PositionSizer, MIN_NOTIONAL_USDT


# ── 1. ExecMode не дрейфует от ExecutionMode (один смысл — одни значения) ──────
class TestExecModeParity:
    def test_values_match_execution_mode(self):
        assert ExecMode.SIM.value == ExecutionMode.SIM_ONLY.value
        assert ExecMode.VST.value == ExecutionMode.VST.value
        assert ExecMode.LIVE.value == ExecutionMode.LIVE.value

    def test_min_notional_default_matches_sizer(self):
        assert calc.DEFAULT_MIN_NOTIONAL == MIN_NOTIONAL_USDT


# ── 2. size_position == PositionSizer.calc_qty (делегирование, не копия) ───────
class TestSizingParity:
    GRID = [
        # entry,    sl,      deposit, risk_pct, leverage
        (100.0,    95.0,    1000.0,  1.0,      5),
        (83000.0,  80000.0, 10000.0, 1.0,      10),
        (0.5,      0.49,    500.0,   0.5,      50),
        (1.2345,   1.2000,  300.0,   2.0,      20),
        (100.0,    99.99,   1000.0,  1.0,      5),   # узкий SL → notional-cap путь
    ]

    @pytest.mark.parametrize("entry,sl,deposit,risk,lev", GRID)
    def test_matches_position_sizer(self, entry, sl, deposit, risk, lev):
        expected = PositionSizer(None).calc_qty(
            entry_price=entry, sl_price=sl, deposit=deposit, risk_pct=risk, leverage=lev,
        )
        got = calc.size_position(entry, sl, deposit, risk, lev)
        assert got == expected

    def test_invalid_inputs_zero(self):
        assert calc.size_position(0, 95, 1000, 1, 5) == 0.0
        assert calc.size_position(100, 100, 1000, 1, 5) == 0.0   # sl==entry
        assert calc.size_position(100, 95, 0, 1, 5) == 0.0       # deposit 0


# ── 3. validate_entry воспроизводит guards open_bracket:403-440 ───────────────
class TestValidateEntry:
    def test_ok_long(self):
        ok, err = calc.validate_entry("LONG", 100.0, 95.0, qty=1.0)
        assert ok and err is None

    def test_ok_short(self):
        ok, err = calc.validate_entry("SHORT", 100.0, 105.0, qty=1.0)
        assert ok and err is None

    def test_qty_zero(self):
        ok, err = calc.validate_entry("LONG", 100.0, 95.0, qty=0.0)
        assert not ok and "qty" in err

    def test_sl_too_close(self):
        # sl_dist 0.05% < min 0.1% (DEV-164)
        ok, err = calc.validate_entry("LONG", 100.0, 99.95, qty=1.0)
        assert not ok and "too close" in err

    def test_sl_wrong_direction_long(self):
        # LONG со стопом ВЫШЕ входа (DEV-159)
        ok, err = calc.validate_entry("LONG", 100.0, 105.0, qty=1.0)
        assert not ok and "direction" in err

    def test_sl_wrong_direction_short(self):
        ok, err = calc.validate_entry("SHORT", 100.0, 95.0, qty=1.0)
        assert not ok and "direction" in err

    def test_notional_below_min(self):
        # qty×entry = 0.01 < MIN_NOTIONAL (sl-guard проходит: dist 5%)
        ok, err = calc.validate_entry("LONG", 100.0, 95.0, qty=0.0001)
        assert not ok and "notional" in err


# ── 4. clamp_leverage воспроизводит open_bracket:469-487 ──────────────────────
class TestClampLeverage:
    def test_no_clamp_when_safe(self):
        # SL 5% → safe ~ int(1/(0.05+0.005))=18; pair_max None; req 5 < 18
        lev, reason = calc.clamp_leverage(5, 100.0, 95.0, pair_max=None)
        assert lev == 5 and reason is None

    def test_pair_max_clamp(self):
        lev, reason = calc.clamp_leverage(50, 100.0, 95.0, pair_max=20)
        # SL 5% safe=18 < 20 → итог 18, но reason содержит и cap пары
        assert lev == 18
        assert "cap пары" in reason and "SL-safety" in reason

    def test_pair_max_only(self):
        # широкий SL 20% → safe=int(1/(0.2+0.005))=4 ... проверим что pair_max доминирует когда safe выше
        lev, reason = calc.clamp_leverage(50, 100.0, 90.0, pair_max=10, liq_safety_enabled=False)
        assert lev == 10 and "cap пары" in reason

    def test_sl_safety_popcat_case(self):
        # POPCAT-кейс: 50×, SL 2.75% → safe = int(1/(0.0275+0.005)) = int(30.7) = 30
        lev, reason = calc.clamp_leverage(50, 100.0, 97.25, pair_max=None)
        assert lev == 30 and "SL-safety" in reason

    def test_safety_disabled(self):
        lev, reason = calc.clamp_leverage(50, 100.0, 97.25, pair_max=None, liq_safety_enabled=False)
        assert lev == 50 and reason is None

    def test_formula_matches_inline(self):
        # Точная сверка с формулой order_manager.open_bracket:478-487 на сетке
        for req in (5, 20, 50):
            for sl_pct in (0.5, 1.0, 2.75, 5.0, 10.0):
                for buf in (0.0, 0.5):
                    entry, sl = 100.0, 100.0 * (1 - sl_pct / 100)
                    lev, _ = calc.clamp_leverage(req, entry, sl, pair_max=None,
                                                 liq_safety_enabled=True, liq_buffer_pct=buf)
                    # инлайн-эталон
                    sl_frac = abs(entry - sl) / entry
                    denom = sl_frac + buf / 100.0
                    safe = max(1, int(1.0 / denom)) if denom > 0 else req
                    expected = min(req, safe)
                    assert lev == expected, f"req={req} sl%={sl_pct} buf={buf}"
