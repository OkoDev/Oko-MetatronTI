# -*- coding: utf-8 -*-
"""29.09: WS-бар через пропуск не дописывается в ряд с дырой — запись сбрасывается на REST; снимок с дырой не грузится."""
import pandas as pd

from core.infra.api_engine import OhlcvCache

M15 = 900_000


def _df(times):
    return pd.DataFrame({"time": times, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})


def _row(t):
    return {"time": t, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}


def test_next_bar_appends_gap_drops_entry():
    c = OhlcvCache()
    key = ("BTC/USDT:USDT", "15m")
    c.set(key, _df([0, M15, 2 * M15]), limit=3)
    assert c.merge_dict(key, _row(2 * M15)) == "replace"
    assert c.merge_dict(key, _row(3 * M15)) == "append"
    assert c.merge_dict(key, _row(5 * M15)) == "gap"          # 4*M15 пропущен
    assert key not in c._data and c.gap_drops == 1
    assert c.merge_dict(key, _row(6 * M15)) == "skip_no_cache"  # ждём REST


def test_merge_dataframe_path_same_rule():
    c = OhlcvCache()
    key = ("ETH/USDT:USDT", "15m")
    c.set(key, _df([0, M15]), limit=2)
    assert c.merge(key, _df([3 * M15])) == "gap" and key not in c._data


def test_snapshot_with_hole_not_loaded(tmp_path):
    c = OhlcvCache()
    c.set(("A/USDT:USDT", "15m"), _df([0, M15, 2 * M15]), limit=3)
    c.set(("B/USDT:USDT", "15m"), _df([0, M15, 3 * M15]), limit=3)   # дыра
    path = str(tmp_path / "snap.pkl")
    assert c.save_to_disk(path, min_entries=0) == 2
    fresh = OhlcvCache()
    assert fresh.load_from_disk(path) == 1
    assert ("A/USDT:USDT", "15m") in fresh._data and ("B/USDT:USDT", "15m") not in fresh._data
