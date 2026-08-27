# -*- coding: utf-8 -*-
"""ЭТАЛОН ПРИЧИННОСТИ FVG (13.08.2026).

Закрывает баг: `swing_bridge.etl_fvg` брал `f[0]` = ts_left (ЛЕВЫЙ бар формации, i-2)
вместо `f[4]` = ts_i (бар обнаружения гэпа). Флаг ставился за 2 бара до того, как
формация становится известна → в бэктесте look-ahead (WR 96.3% против честных 43.8%,
PF 52.55 против 0.72), в бою слепота: на текущем баре флага нет.

Реализация `core/smc/smc_engine.detect_fvg` идёт в комбинатор, arch104 и живой путь
(`core/intelligence/feature_snapshot.py`), но НЕ была покрыта ни одним тестом — тесты
в `test_smc_layer.py` проверяют другую реализацию (`core/smc/fvg.py`).

Фиксируем два инварианта:
  1. контракт кортежа detect_fvg: (ts_left, top, bottom, kind, ts_i, mitigated);
  2. флаг из etl_fvg стоит на баре ОБНАРУЖЕНИЯ и виден в реальном времени.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _df_with_bull_fvg() -> pd.DataFrame:
    """Ряд, где на баре 12 образуется bull-FVG: low[12] > high[10]."""
    n = 30
    base = np.full(n, 100.0)
    high = base + 0.5
    low = base - 0.5
    close = base.copy()
    open_ = base.copy()
    # импульс на барах 11-12: гэп между high[10] и low[12]
    close[11], high[11], low[11] = 104.0, 104.5, 100.2
    close[12], high[12], low[12] = 106.0, 106.5, 105.0     # low[12]=105 > high[10]=100.5
    open_[11], open_[12] = 100.0, 104.5
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": np.full(n, 1000.0)}, index=idx)


def test_detect_fvg_tuple_contract():
    """f[0] = ЛЕВЫЙ бар зоны (i-2), f[4] = бар обнаружения (i). Ровно 2 бара разницы."""
    from core.smc.smc_engine import detect_fvg

    df = _df_with_bull_fvg()
    fvgs = detect_fvg(df, threshold=0.1)
    assert fvgs, "bull-FVG на баре 12 не найден — сломан сам детектор"

    for f in fvgs:
        ts_left, ts_i = f[0], f[4]
        i_left = df.index.get_loc(ts_left)
        i_det = df.index.get_loc(ts_i)
        assert i_det - i_left == 2, (
            f"контракт кортежа нарушен: ожидалось ts_i - ts_left = 2, "
            f"получено {i_det - i_left}")


def test_etl_fvg_flag_on_detection_bar():
    """Флаг ставится на бар ОБНАРУЖЕНИЯ (i), а не на левый бар зоны (i-2)."""
    from core.calculators.swing_bridge import etl_fvg

    df = _df_with_bull_fvg()
    out = etl_fvg(df)
    idx = np.flatnonzero(out["bull_fvg"])
    assert len(idx) > 0, "bull_fvg флаг не выставлен"
    assert 12 in idx, (
        f"флаг должен стоять на баре обнаружения 12, стоит на {list(idx)}. "
        f"Если стоит на 10 — вернулся баг f[0] вместо f[4]")
    assert 10 not in idx, "флаг на баре 10 = look-ahead на 2 бара (регрессия f[0])"


def test_fvg_flag_visible_in_realtime():
    """Флаг на баре b виден при расчёте по данным ТОЛЬКО до b включительно.

    Это главный инвариант: то, что нельзя увидеть в реальном времени,
    в бэктесте является знанием будущего.
    """
    from core.calculators.swing_bridge import etl_fvg

    df = _df_with_bull_fvg()
    full = etl_fvg(df)["bull_fvg"]
    bars = np.flatnonzero(full)
    assert len(bars) > 0

    for b in bars:
        partial = etl_fvg(df.iloc[:b + 1])["bull_fvg"]
        assert len(partial) == b + 1
        assert bool(partial[b]), (
            f"флаг на баре {b} НЕ виден при данных до {b} включительно — "
            f"детектор смотрит в будущее")


@pytest.mark.parametrize("cut", [14, 18, 24])
def test_fvg_flags_stable_under_truncation(cut: int):
    """Обрезка будущих баров не должна менять уже выставленные флаги."""
    from core.calculators.swing_bridge import etl_fvg

    df = _df_with_bull_fvg()
    full = etl_fvg(df)["bull_fvg"][:cut]
    part = etl_fvg(df.iloc[:cut])["bull_fvg"]
    # авто-порог threshold считается по всему df, поэтому у самой границы
    # допускается расхождение; ядро окна обязано совпадать
    assert np.array_equal(full[:cut - 3], part[:cut - 3]), (
        "флаги переписываются задним числом при появлении новых баров")
