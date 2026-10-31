# -*- coding: utf-8 -*-
"""ARCH-153 (31.10): сборка записи из РЕАЛЬНОГО хранилища Сферы 1 (офлайн, без биржи).

Проверяет главное правило: собранный ряд НИКОГДА не содержит дыр, а если он отдан — его
последний бар текущий (живой край как у REST). Пропускается, если хранилища нет на машине.

Замер 31.10, ради которого правило введено: после каждого рестарта бота все записи 3m/5m
получали `gap` (последний бар в снимке старше текущего) и сбрасывались — скан просил 600
баров с биржи по ~552 парам на ТФ: [OHLCV-CACHE] 01:47 — «нет записи» 1093, REST 1213 за круг.
"""
import time

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


def test_rebuild_15m_from_store_is_continuous_and_live():
    """15m — единственный ТФ, где хранилище чистое (замер: 600/610 монет без дыр)."""
    c = OhlcvCache()
    rd = _reader(c)
    step = _TF_STEP_MS["15m"]
    now_bar = int(time.time() * 1000) // step * step
    key = ("BTC/USDT:USDT", "15m")
    # как в бою: закрывшийся бар держит память читателя (хранилище пишет с задержкой до 2 шагов)
    rd._remember_closed(key, {"time": now_bar - step, "open": 1.0, "high": 2.0,
                              "low": 0.5, "close": 1.2, "volume": 5.0})
    rd._last_row[key] = {
        "time": now_bar, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}

    df = c.rebuild(key, 200)
    assert df is not None and len(df) >= 100
    assert int(df["time"].iloc[-1]) == now_bar          # живой край, как у REST
    _check_no_holes(df, "15m")
    assert float(df["close"].iloc[-1]) == 1.5           # текущий бар — из WS, не из хранилища


def test_rebuild_never_returns_series_with_holes():
    """3m/5m в хранилище с дырами — тогда либо чистый хвост, либо None (идём в REST)."""
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
