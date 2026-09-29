# -*- coding: utf-8 -*-
"""Сфера 1, шаг 2: очередь закрытых баров WS → хранилище; лечение дыр 3m/5m (29.09)."""
import time

import pandas as pd

from core.infra import market_spool, market_store as ms

M3 = 180_000


def test_put_flush_and_completed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(market_spool, "SPOOL", tmp_path / "_spool")
    market_spool.put("BTC/USDT:USDT", "3m", {"time": 3 * M3, "open": 1.5, "high": 2.0, "low": 1.0,
                                              "close": 1.75, "volume": 10.0})
    market_spool.put("NCSKNU2USD/USDT:USDT", "3m", {"time": 3 * M3, "open": 1, "high": 1, "low": 1,
                                                     "close": 1, "volume": 1})           # синтетика — мимо
    assert market_spool.flush() == 1
    files = list((tmp_path / "_spool").glob("*.csv"))
    assert len(files) == 1 and files[0].read_text(encoding="utf-8").startswith("BTC,3m,540000,1.5,2.0,1.0,1.75,10.0")
    assert market_spool.completed_files() == []                         # текущую минуту не отдаём
    assert market_spool.completed_files(now=time.time() + 120) == files


def test_numpy_values_written_as_plain_numbers(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(market_spool, "SPOOL", tmp_path / "_spool")
    market_spool.put("ETH/USDT:USDT", "5m", pd.Series({"time": np.int64(0), "open": np.float64(0.323),
                                                        "high": np.float64(0.4), "low": np.float64(0.3),
                                                        "close": np.float64(0.35), "volume": np.float64(7.0)}))
    market_spool.flush()
    txt = next((tmp_path / "_spool").glob("*.csv")).read_text(encoding="utf-8")
    assert txt == "ETH,5m,0,0.323,0.4,0.3,0.35,7.0\n"                 # не «np.float64(0.323)»


def test_first_hole_inside_tail_and_none(tmp_path, monkeypatch):
    from scripts import market_store_service as svc
    monkeypatch.setattr(ms, "ROOT", tmp_path)
    now = int(pd.Timestamp("2026-09-29 12:00:30", tz="UTC").value // 1_000_000)
    last_closed = now // M3 * M3 - M3
    full = [last_closed - k * M3 for k in range(30, -1, -1)]

    def _store(base, times):
        ms.append_bars(base, "3m", pd.DataFrame({"time": times, "open": 1.0, "high": 1.0, "low": 1.0,
                                                 "close": 1.0, "volume": 1.0}))
    _store("OK", full)
    _store("HOLE", [t for t in full if t != full[10]])
    _store("TAIL", full[:-5])
    assert svc.first_hole("OK", "3m", now) is None
    assert svc.first_hole("HOLE", "3m", now) == full[10]                 # дыра внутри — last_time её не видит
    assert svc.first_hole("TAIL", "3m", now) == full[-5]
