# -*- coding: utf-8 -*-
"""Резолвер теней: исход = что случилось РАНЬШЕ (09.10 — раньше цель засчитывалась и после стопа)."""
import scripts.shadow_resolve as R

H = 3600
LONG = {"symbol": "TEST", "direction": "LONG", "entry": 100.0, "sl": 95.0, "tp1": 105.0, "ts": 0, "src": "bingx"}
OTE = {"symbol": "TEST", "direction": "LONG", "entry": 100.0, "sl": 95.0, "tp1r": 105.0, "tp_ext": 110.0,
       "ts": 0, "src": "bingx"}


class Row(dict):
    def keys(self):
        return super().keys()


def run(monkeypatch, row, bars, table="method_shadow", age_h=1000):
    # bars: [(high, low, close)] — по часу от момента сигнала
    kl = [(i * H * 1000, hi, lo, cl) for i, (hi, lo, cl) in enumerate(bars)]
    monkeypatch.setattr(R, "klines_after", lambda *a, **k: kl)
    return R.resolve_row(Row(row), R.SPECS[table], now_ts=age_h * H)


def test_stop_before_target_is_sl(monkeypatch):
    out, px, cols = run(monkeypatch, LONG, [(101, 94, 96), (106, 96, 105.5)])
    assert (out, px, cols["pct_1r"]) == ("SL", 95.0, -5.0)


def test_target_before_stop_is_tp(monkeypatch):
    out, px, cols = run(monkeypatch, LONG, [(106, 99, 105.5), (101, 94, 96)])
    assert (out, px, cols["pct_1r"]) == ("TP", 105.0, 5.0)


def test_same_bar_is_sl(monkeypatch):
    out, _, cols = run(monkeypatch, LONG, [(106, 94, 100)])
    assert out == "SL" and cols["pct_1r"] == -5.0


def test_short_stop_first(monkeypatch):
    row = {**LONG, "direction": "SHORT", "sl": 105.0, "tp1": 95.0}
    out, _, cols = run(monkeypatch, row, [(106, 99, 104), (104, 94, 95)])
    assert out == "SL" and cols["pct_1r"] == -5.0


def test_expired_uses_last_close_inside_ttl(monkeypatch):
    # TTL method_shadow = 96 ч; бар №96 и дальше — вне срока и не должен влиять
    bars = [(101, 99, 100.5)] * 96 + [(120, 80, 120)]
    out, px, cols = run(monkeypatch, LONG, bars)
    assert (out, px, cols["pct_1r"]) == ("EXPIRED", 100.5, 0.5)


def test_early_without_events_waits(monkeypatch):
    assert run(monkeypatch, LONG, [(101, 99, 100)], age_h=5) is None


def test_far_target_waits_then_stop(monkeypatch):
    # первая цель взята, дальняя ещё нет, срок не вышел → ждём; потом стоп → дальняя = стоп
    assert run(monkeypatch, OTE, [(106, 99, 105)], table="ote_cell_shadow", age_h=5) is None
    out, _, cols = run(monkeypatch, OTE, [(106, 99, 105), (104, 94, 95)], table="ote_cell_shadow", age_h=5)
    assert out == "TP" and cols == {"pct_1r": 5.0, "pct_ext": -5.0}
