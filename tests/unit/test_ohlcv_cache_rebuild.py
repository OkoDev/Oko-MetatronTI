# -*- coding: utf-8 -*-
"""ARCH-153 (31.10): дыра/потеря записи собирается ЛОКАЛЬНО из хранилища Сферы 1, а не REST.

Замер, ради которого правило введено: после каждого рестарта бота все записи 3m/5m получали
`gap` (последний бар в снимке старше текущего) и сбрасывались — скан просил 600 баров с биржи
по ~552 парам на ТФ: [OHLCV-CACHE] 01:47 — «нет записи» 1093, REST 1213 за круг, hit 65%/56%.
"""
import pandas as pd

from core.infra.api_engine import OhlcvCache

M3 = 180_000


def _df(times, px=1.0):
    return pd.DataFrame({"time": times, "open": px, "high": px, "low": px, "close": px, "volume": px})


def _row(t, px=2.0):
    return {"time": t, "open": px, "high": px, "low": px, "close": px, "volume": px}


def test_gap_rebuilt_locally_not_dropped():
    """Дыра: хук собрал запись → сброса нет, входящий бар просто дописывается."""
    c = OhlcvCache()
    key = ("BTC/USDT:USDT", "3m")
    c.set(key, _df([0, M3, 2 * M3]), limit=3)
    calls = []

    def hook(k, limit):
        calls.append((k, limit))
        return _df([2 * M3, 3 * M3, 4 * M3])       # хранилище догнало до 4*M3

    c.rebuild_hook = hook
    assert c.merge_dict(key, _row(5 * M3)) == "rebuild_append"
    assert c.gap_drops == 0 and key in c._data
    assert calls and calls[0][0] == key
    assert int(c._data[key]["df"]["time"].iloc[-1]) == 5 * M3
    assert c.rebuild_stats["ok"] == 1


def test_gap_without_rebuild_still_drops():
    """Хук не смог (мёртвая пара / нет хранилища) → прежнее поведение: сброс на REST."""
    c = OhlcvCache()
    key = ("ETH/USDT:USDT", "3m")
    c.set(key, _df([0, M3]), limit=2)
    c.rebuild_hook = lambda k, limit: None
    assert c.merge_dict(key, _row(5 * M3)) == "gap"
    assert key not in c._data and c.gap_drops == 1
    assert c.rebuild_stats["fail"] == 1


def test_hook_exception_falls_back_to_rest():
    """Падение хука не должно ломать merge: та же дыра, тот же сброс, исключение не пробрасывается."""
    c = OhlcvCache()
    key = ("SOL/USDT:USDT", "3m")
    c.set(key, _df([0, M3]), limit=2)

    def boom(k, limit):
        raise RuntimeError("паркет занят")

    c.rebuild_hook = boom
    assert c.merge_dict(key, _row(5 * M3)) == "gap"
    assert key not in c._data
    assert c.rebuild_stats["fail"] == 1


def test_rebuild_disabled_by_flag():
    """config market_store.ltf_rebuild: off → хук не зовётся вовсе."""
    c = OhlcvCache()
    key = ("BNB/USDT:USDT", "3m")
    c.set(key, _df([0, M3]), limit=2)
    c.rebuild_enabled = False
    c.rebuild_hook = lambda k, limit: _df([1 * M3, 2 * M3])
    assert c.rebuild(key, 3) is None
    assert c.merge_dict(key, _row(5 * M3)) == "gap"


def test_rebuild_fills_missing_entry_for_get():
    """Записи нет вовсе (skip_no_cache/вытеснение) → rebuild кладёт её, get отдаёт без REST."""
    c = OhlcvCache()
    key = ("XRP/USDT:USDT", "3m")
    c.rebuild_hook = lambda k, limit: _df([M3, 2 * M3, 3 * M3])
    assert c.get(key, 3, ttl=180) is None
    assert c.rebuild(key, 3) is not None
    got = c.get(key, 3, ttl=180)
    assert got is not None and len(got) == 3 and int(got["time"].iloc[-1]) == 3 * M3
