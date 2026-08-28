"""
Регрессия смены детектора импульса на ЭКСТРЕМУМЫ (28.08.2026, команда Егора
«детектор на экстремумы менять! это важно!»).

Ключевое, что охраняют тесты: `amp_mode="extremes"` и `MAX_RETR=0.32` —
ПАРНЫЕ. Врозь их менять нельзя.

`max_retr` сравнивает контр-откат (всегда по H/L) с ХОДОМ. Пока ход мерился по
close, 0.35 означало одну строгость. Ход по экстремумам больше медианно в 1.18× →
то же число стало СЛАБЕЕ и впустило рваные движения. Замер на 1h: смена режима
без перекалибровки дала PF 2.90 → 1.67, хрупкость +117 → −180. С 0.32 поток
совпадает с прежним и PF возвращается к 2.17.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.smc.impulse_fib import (          # noqa: E402
    MAX_RETR, MIN_ATR, _atr, find_impulses, impulse_points)


def _synthetic(n=600, seed=3):
    """Ряд с настоящими тенями — по close и по экстремумам ход РАЗНЫЙ."""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.35, n))
    wick = np.abs(rng.normal(0, 0.45, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close, "close": close,
                         "high": close + wick, "low": close - wick,
                         "volume": 100.0}, index=idx)


def test_constants_are_paired():
    """🔴 ГЛАВНЫЙ: 0.32 идёт в комплекте с extremes, 0.35 — со старым close."""
    assert MAX_RETR == pytest.approx(0.32), (
        "MAX_RETR разошёлся с режимом амплитуды — смысл порога изменился молча")
    import inspect
    sig = inspect.signature(find_impulses)
    assert sig.parameters["amp_mode"].default == "extremes"
    assert sig.parameters["max_retr"].default == pytest.approx(MAX_RETR)


def test_extremes_measures_wicks_close_does_not():
    """Ход по экстремумам обязан быть НЕ МЕНЬШЕ хода по close на тех же барах."""
    df = _synthetic()
    H, L, C = df.high.values, df.low.values, df.close.values
    bigger = same = 0
    for a, b, up in [(10, 40, True), (50, 90, False), (100, 150, True)]:
        _, _, amp_c = impulse_points(H, L, C, a, b, up, "close")
        _, _, amp_e = impulse_points(H, L, C, a, b, up, "extremes")
        assert amp_e >= amp_c - 1e-12, "экстремумы дали ход МЕНЬШЕ, чем close"
        bigger += int(amp_e > amp_c)
        same += int(amp_e == amp_c)
    assert bigger >= 1, "на ряде с тенями хотя бы один ход обязан вырасти"


def test_extremes_endpoints_are_actual_extremes():
    """Концы хода обязаны совпадать с реальными low/high баров, а не с close."""
    df = _synthetic()
    H, L, C = df.high.values, df.low.values, df.close.values
    p_a, p_b, _ = impulse_points(H, L, C, 20, 60, True, "extremes")
    assert p_a == pytest.approx(L[20]), "начало восходящего хода не на low"
    assert p_b == pytest.approx(H[60]), "конец восходящего хода не на high"
    p_a, p_b, _ = impulse_points(H, L, C, 20, 60, False, "extremes")
    assert p_a == pytest.approx(H[20]) and p_b == pytest.approx(L[60])


def test_retr_gate_still_bites():
    """🔴 НЕГАТИВНЫЙ: фильтр чистоты хода обязан РЕЗАТЬ, а не пропускать всё."""
    df = _synthetic()
    H, L, C = df.high.values, df.low.values, df.close.values
    atr = _atr(df).values
    loose = len(find_impulses(H, L, C, atr, len(df), max_retr=0.35))
    tight = len(find_impulses(H, L, C, atr, len(df), max_retr=0.20))
    assert tight < loose, "ужесточение max_retr не уменьшило выборку — гейт мёртв"


def test_min_atr_is_not_the_bottleneck():
    """
    Замер 28.08: min_atr 3.0→3.54 меняет выборку на ~2.6%, а режим — на 87%.
    Тест фиксирует, что узкое место НЕ здесь: иначе следующий, кто станет
    калибровать, снова потратит время не на тот параметр.
    """
    df = _synthetic()
    H, L, C = df.high.values, df.low.values, df.close.values
    atr = _atr(df).values
    base = len(find_impulses(H, L, C, atr, len(df), min_atr=MIN_ATR))
    up = len(find_impulses(H, L, C, atr, len(df), min_atr=MIN_ATR * 1.18))
    if base:
        assert abs(base - up) / base < 0.35, (
            "подъём min_atr на 18% радикально меняет выборку — предпосылка замера неверна")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
