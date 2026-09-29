# -*- coding: utf-8 -*-
"""Сфера 1 → бот: сборка старшего ТФ из закрытых баров хранилища + текущий бар из 15m (N15, 29.09)."""
import pandas as pd

from core.infra.htf_from_store import compose, forming_from_15m

H = 3_600_000
M15 = 900_000
NOW = 100 * H + 3 * M15 + 60_000          # 4-й 15m-бар текущего часа идёт 1 минуту


def _df(times, base=10.0):
    return pd.DataFrame({"time": times, "open": [base + i for i in range(len(times))],
                         "high": [base + i + 0.5 for i in range(len(times))],
                         "low": [base + i - 0.5 for i in range(len(times))],
                         "close": [base + i + 0.2 for i in range(len(times))],
                         "volume": [1.0] * len(times)})


def test_forming_bar_aggregates_current_hour():
    df15 = _df([100 * H - M15] + [100 * H + k * M15 for k in range(4)])   # хвост прошлого часа + 4 текущих
    fb = forming_from_15m(df15, "1h", NOW)
    assert fb["time"] == 100 * H
    assert fb["open"] == 11.0 and fb["close"] == 14.2          # первый open / последний close текущего часа
    assert fb["high"] == 14.5 and fb["low"] == 10.5 and fb["volume"] == 4.0


def test_forming_none_on_gap_or_stale_15m():
    gap = _df([100 * H, 100 * H + M15, 100 * H + 3 * M15])                 # нет третьего бара
    stale = _df([100 * H + k * M15 for k in range(3)])                     # нет текущего 15m
    assert forming_from_15m(gap, "1h", NOW) is None
    assert forming_from_15m(stale, "1h", NOW) is None


def test_compose_uses_store_tail_and_forming_bar():
    closed = _df([(100 - k) * H for k in range(10, 0, -1)])                 # закрыт по 99-й час
    df15 = _df([100 * H + k * M15 for k in range(4)])
    out, why = compose(closed, df15, "1h", 5, NOW)
    assert why == "ok" and len(out) == 5
    assert out["time"].tolist() == [96 * H, 97 * H, 98 * H, 99 * H, 100 * H]
    assert str(out["time"].dtype) == "int64" and str(out["close"].dtype) == "float64"


def test_compose_refuses_when_store_behind_or_short():
    df15 = _df([100 * H + k * M15 for k in range(4)])
    behind = _df([(99 - k) * H for k in range(10, 0, -1)])                 # нет 99-го часа
    assert compose(behind, df15, "1h", 5, NOW) == (None, "store_behind")
    short = _df([98 * H, 99 * H])
    assert compose(short, df15, "1h", 5, NOW) == (None, "store_short")


def test_compose_young_coin_returns_whole_history_when_store_exhausted():
    df15 = _df([100 * H + k * M15 for k in range(4)])
    young = _df([98 * H, 99 * H])                                         # вся история монеты — 2 бара
    out, why = compose(young, df15, "1h", 200, NOW, exhausted=True)
    assert why == "ok" and out["time"].tolist() == [98 * H, 99 * H, 100 * H]   # как REST: меньше limit
