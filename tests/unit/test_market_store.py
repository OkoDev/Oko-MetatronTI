# -*- coding: utf-8 -*-
"""Сфера 1 — хранилище закрытых баров (core/infra/market_store.py, BACKLOG N15)."""
import importlib

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OKO_MARKET_STORE", str(tmp_path))
    import core.infra.market_store as ms
    return importlib.reload(ms)


def _bars(start: str, n: int, freq: str = "4h", base_px: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq=freq, tz="UTC", name="ts")
    px = base_px + np.arange(n, dtype=float)
    return pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px + 0.5, "volume": 10.0}, index=idx)


def test_roundtrip_across_months(store):
    df = _bars("2026-01-25", 60)                                   # 10 дней 4h → два месяца
    assert store.append_bars("SOLV/USDT:USDT", "4h", df) == 60
    assert len(list((store.ROOT / "bingx" / "4h" / "SOLV").glob("*.parquet"))) == 2
    out = store.read_bars("SOLV", "4h")
    pd.testing.assert_frame_equal(out, df, check_freq=False, check_names=False)


def test_append_is_idempotent_and_updates(store):
    df = _bars("2026-03-01", 10)
    store.append_bars("BTC", "4h", df)
    assert store.append_bars("BTC", "4h", df) == 0                 # повтор — ни одной новой строки
    fix = df.iloc[-1:].copy()
    fix["close"] = 999.0
    assert store.append_bars("BTC", "4h", fix) == 0
    assert store.read_bars("BTC", "4h").close.iloc[-1] == 999.0    # совпавшее время перезаписывается
    more = _bars("2026-03-02 12:00", 5)                            # пересекается на 1 бар (последний 12:00)
    assert store.append_bars("BTC", "4h", more) == 4


def test_read_n_since_and_last_time(store):
    df = _bars("2026-02-20", 100)
    store.append_bars("ETH", "4h", df)
    assert len(store.read_bars("ETH", "4h", n=7)) == 7
    assert store.read_bars("ETH", "4h", n=7).index[-1] == df.index[-1]
    since = int(df.index[40].value // 1_000_000)
    assert store.read_bars("ETH", "4h", since_ms=since).index[0] == df.index[40]
    assert store.last_time("ETH", "4h") == int(df.index[-1].value // 1_000_000)
    assert store.last_time("NONE", "4h") is None
    assert store.read_bars("NONE", "4h").empty


def test_exchange_is_a_parameter(store):
    store.append_bars("BTC", "1h", _bars("2026-04-01", 5, "1h"), exchange="binance")
    assert store.read_bars("BTC", "1h").empty
    assert len(store.read_bars("BTC", "1h", exchange="binance")) == 5


def test_synthetic_and_base(store):
    assert store.is_synthetic("NCSKMU2USD") and not store.is_synthetic("SOL")
    assert store.base_of("1000PEPE/USDT:USDT") == store.base_of("1000pepe-USDT") == "1000PEPE"
