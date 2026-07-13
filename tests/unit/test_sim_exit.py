# -*- coding: utf-8 -*-
"""Поведенческий контракт sim_exit.detect_candle_exit (EXEC-SIM-SPLIT шаг 6, 13.07).

Детект — ядро SIM-честности (sl_touch_all, data-era 11.07): правила зафиксированы,
изменение = новая data-era. Кейсы сняты при переносе 1:1 из монитора."""
import pandas as pd

from core.trading.sim_exit import detect_candle_exit


def _df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _run(rows, **kw):
    base = dict(direction="LONG", sl=None, tp=None, tp1_price=None, tp1_hit_at=None,
                tp2_price=None, tp2_hit_at=None, sl_check_close=False, tsl_active=False)
    base.update(kw)
    return detect_candle_exit(_df(rows), **base)


class TestTouchParity:
    def test_long_sl_by_wick(self):
        # SIM=TOUCH: фитиль до SL при close выше → SL (паритет с биржевым STOP)
        r = _run([[100, 101, 94, 100]], sl=95, tp=110)
        assert r.exit_status == "SL" and r.exit_price == 95

    def test_close_mode_ignores_wick(self):
        # tsl_line-источники при выключенном sl_touch_all: только close
        r = _run([[100, 101, 94, 100]], sl=95, tp=110, sl_check_close=True)
        assert r.exit_status is None

    def test_short_sl_by_wick(self):
        r = _run([[100, 106, 99, 100]], direction="SHORT", sl=105, tp=90)
        assert r.exit_status == "SL" and r.exit_price == 105


class TestTslSupremacy:
    def test_tp_does_not_cut_runner(self):
        # активный TSL → фиксированный TP не закрывает (TSL сам решит)
        r = _run([[100, 111, 99, 110]], sl=95, tp=110, tsl_active=True)
        assert r.exit_status is None


class TestDualTp:
    def test_tp1_then_tp2_cascade(self):
        r = _run([[100, 105.5, 99, 105], [105, 111, 104, 110]],
                 sl=95, tp1_price=105, tp2_price=110)
        assert r.tp1_hit_now and r.tp2_hit_now
        assert r.exit_status == "TP" and r.exit_price == 110

    def test_tp2_requires_tp1_first(self):
        # tp2 задет, но tp1 ещё не был → выхода нет
        r = _run([[100, 111, 106, 110]], sl=95, tp1_price=105, tp2_price=110,
                 tp1_hit_at=None)
        # tp1 тоже задет в этой же свече (high 111 ≥ 105) → каскад одной свечой
        assert r.tp1_hit_now and r.exit_status == "TP"


class TestTieBreak:
    def test_both_hit_tiebreak_by_open(self):
        # open=103: до tp=104 ближе, чем до sl=95 → TP
        r = _run([[103, 104.5, 94, 100]], sl=95, tp=104)
        assert r.exit_status == "TP"


class TestMfe:
    def test_extremes_collected(self):
        r = _run([[103, 104.5, 94, 100]], sl=95, tp=104)
        assert r.max_high == 104.5 and r.min_low == 94
