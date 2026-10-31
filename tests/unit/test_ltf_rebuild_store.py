# -*- coding: utf-8 -*-
"""ARCH-153 (31.10): сборка записи — детерминированно (замороженное хранилище) + дым на живом.

Главное правило: собранный ряд НИКОГДА не содержит дыр, а если он отдан — его последний бар текущий
(живой край как у REST). ⚠️ Проверять это на ЖИВОМ хранилище нельзя: у него плавает хвост (замер:
медиана чистого хвоста 9 баров у 3m, 14 у 5m), и тест становится флейки. Поэтому основной тест
подменяет `read_bars` замороженными барами, а живой оставлен дымовым (либо чистый ряд, либо None).

Замер 31.10, ради которого правило введено: после каждого рестарта бота все записи 3m/5m
получали `gap` (последний бар в снимке старше текущего) и сбрасывались — скан просил 600
баров с биржи по ~552 парам на ТФ: [OHLCV-CACHE] 01:47 — «нет записи» 1093, REST 1213 за круг.
"""
import time

import pandas as pd
import pytest

from core.infra import market_store as ms
from core.infra.api_engine import OhlcvCache, _TF_STEP_MS
from core.infra.market_ws_v2 import QueueReaderThread

pytestmark = pytest.mark.skipif(not (ms.ROOT / "bingx" / "15m").exists(),
                                reason="хранилища Сферы 1 нет на этой машине")


def _reader(cache):
    """Читатель без запуска процесса: нужен только ради хука + памяти баров."""
    return QueueReaderThread(q=None, cache=cache, shadow=False, spool_tfs=("3m", "5m", "15m"))


def _check_no_holes(df, tf):
    step = _TF_STEP_MS[tf]
    steps = df["time"].astype("int64").diff().iloc[1:]
    assert (steps == step).all(), f"в собранном ряде {tf} есть дыры"


def _frozen_store(now_bar: int, step: int, n: int, behind: int = 2) -> pd.DataFrame:
    """Замороженный ответ хранилища: n закрытых баров, последний отстаёт на `behind` шагов."""
    times = [now_bar - step * (behind + i) for i in range(n)][::-1]
    idx = pd.DatetimeIndex(pd.to_datetime(times, unit="ms", utc=True), name="ts")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.2, "volume": 5.0}, index=idx)


def test_rebuild_15m_from_frozen_store_is_continuous_and_live(monkeypatch):
    """Хранилище отстало на 2 шага, закрывшийся бар добирает память читателя, живой край — из WS."""
    c = OhlcvCache()
    rd = _reader(c)
    step = _TF_STEP_MS["15m"]
    now_bar = int(time.time() * 1000) // step * step
    key = ("BTC/USDT:USDT", "15m")
    monkeypatch.setattr(ms, "read_bars",
                        lambda base, tf, n=None, **kw: _frozen_store(now_bar, step, n or 200))
    rd._remember_closed(key, {"time": now_bar - step, "open": 1.0, "high": 2.0,
                              "low": 0.5, "close": 1.2, "volume": 5.0})
    rd._last_row[key] = {
        "time": now_bar, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}

    df = c.rebuild(key, 200)
    assert df is not None and len(df) == 200            # глубина ровно запрошенная
    assert int(df["time"].iloc[-1]) == now_bar          # живой край, как у REST
    _check_no_holes(df, "15m")
    assert float(df["close"].iloc[-1]) == 1.5           # текущий бар — из WS, не из хранилища


def test_rebuild_refuses_when_store_tail_too_short(monkeypatch):
    """Молодая/мёртвая пара: хранилище кончилось давно → сборки нет, идём в REST."""
    c = OhlcvCache()
    rd = _reader(c)
    step = _TF_STEP_MS["15m"]
    now_bar = int(time.time() * 1000) // step * step
    key = ("NEWCOIN/USDT:USDT", "15m")
    monkeypatch.setattr(ms, "read_bars",
                        lambda base, tf, n=None, **kw: _frozen_store(now_bar, step, n or 200, behind=40))
    rd._last_row[key] = {
        "time": now_bar, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
    assert c.rebuild(key, 200) is None


def test_rebuild_never_returns_series_with_holes():
    """Дым на ЖИВОМ хранилище: если ряд отдан — он без дыр и с текущим баром; иначе None."""
    c = OhlcvCache()
    rd = _reader(c)
    for tf, base in (("3m", "BTC"), ("5m", "ETH")):
        step = _TF_STEP_MS[tf]
        now_bar = int(time.time() * 1000) // step * step
        key = (f"{base}/USDT:USDT", tf)
        rd._remember_closed(key, {"time": now_bar - step, "open": 1.0, "high": 2.0,
                                  "low": 0.5, "close": 1.2, "volume": 5.0})
        rd._last_row[key] = {
            "time": now_bar, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}
        df = rd._rebuild_from_store(key, 600)
        if df is None:
            continue                                    # законно: данных для склейки нет
        _check_no_holes(df, tf)
        assert int(df["time"].iloc[-1]) == now_bar


def test_rebuild_rejects_stale_store():
    """Монета, у которой хранилище отстало на дни (неликвид) → сборки нет, идём в REST."""
    c = OhlcvCache()
    _reader(c)
    assert c.rebuild(("UNKNOWNCOIN/USDT:USDT", "3m"), 100) is None
    assert c.rebuild_stats["fail"] >= 1


def test_rebuild_skips_synthetic_and_senior_tf():
    c = OhlcvCache()
    _reader(c)
    assert c.rebuild(("NCSKAAA/USDT:USDT", "3m"), 100) is None   # акции BingX — не крипта
    assert c.rebuild(("BTC/USDT:USDT", "1h"), 300) is None       # старшие ТФ — свой путь (HtfStore)
