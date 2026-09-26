"""Собственные слои OKO (фаза 5, core/structure/layers.py): OTE на ноге, цели по пивотам, ноги DC."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.structure import day_pivots, dc_swings, ote_on_leg, pivot_target, trace_structure, active_leg  # noqa: E402


def _walk(n=2400, seed=4):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n) + np.concatenate([np.full(n // 2, 0.04), np.full(n - n // 2, -0.04)]))
    open_ = np.concatenate(([close[0]], close[:-1]))
    wick = np.abs(rng.normal(0, 0.4, n))
    idx = pd.date_range("2025-03-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick,
                         "low": np.minimum(open_, close) - wick, "close": close}, index=idx)


class TestOte:
    def test_long_and_short_use_project_canon(self):
        from core.smc.fibonacci import OTE_LEVELS, OTE_ZONE
        long_ = ote_on_leg({"trend": "long", "origin": 100.0, "extreme": 200.0})
        assert long_["zone"] == (200 - 100 * OTE_ZONE[0], 200 - 100 * OTE_ZONE[1])
        assert [r for r, _ in long_["levels"]] == list(OTE_LEVELS)
        short = ote_on_leg({"trend": "short", "origin": 200.0, "extreme": 100.0})
        assert short["zone"] == (100 + 100 * OTE_ZONE[1], 100 + 100 * OTE_ZONE[0])

    def test_on_real_leg(self):
        leg = active_leg(trace_structure(_walk()))
        ote = ote_on_leg(leg)
        top, bottom = ote["zone"]
        lo, hi = sorted((leg["origin"], leg["extreme"]))
        assert lo < bottom < top < hi
        assert ote_on_leg(None) is None


class TestPivotTarget:
    P = day_pivots(110.0, 90.0, 100.0)

    def test_egor_rule_walks_up_the_r_levels(self):
        p = self.P
        assert pivot_target(p, p["PP"], True) == ("R1", p["R1"])                 # внутри S1–R1 → R1
        assert pivot_target(p, (p["R1"] + p["R2"]) / 2, True) == ("R2", p["R2"])  # за R1 → R2
        assert pivot_target(p, p["R5"] * 1.01, True) is None                     # выше R5 целей нет
        assert pivot_target(p, p["PP"], False) == ("S1", p["S1"])
        assert pivot_target(p, (p["S1"] + p["S2"]) / 2, False) == ("S2", p["S2"])

    def test_min_distance(self):
        p = self.P
        assert pivot_target(p, p["R1"] / 1.002, True) == ("R2", p["R2"])          # R1 ближе 0.3% — пропуск

    def test_second_mode_matches_live_impulse_fib(self):
        runner = pytest.importorskip("bot.loops.impulse_fib_runner")
        d = _walk()
        daily = d.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        rng = np.random.default_rng(1)
        checked = 0
        for _ in range(60):
            t = d.index[rng.integers(48, len(d))]
            prev = daily[daily.index < t.floor("D")].iloc[-1]
            piv = day_pivots(float(prev.high), float(prev.low), float(prev.close))
            entry = float(d.close.loc[t]) * float(rng.uniform(0.97, 1.03))
            for is_long in (True, False):
                mine = pivot_target(piv, entry, is_long, mode="second")
                live = runner._pivot_2nd(d, t, entry, is_long)
                assert (mine[1] if mine else None) == live
                checked += 1
        assert checked == 120


def test_dc_swings_match_dc_legs():
    from core.smc.dc_legs import enforce_alternation, find_legs
    d = _walk().reset_index(drop=True)
    ref = [(x.ext_i, x.ext_price, x.conf_i, x.up) for x in enforce_alternation(find_legs(d, atr_mult=3.0, atr_len=43))]
    assert dc_swings(d) == ref and len(ref) > 5
    kinds = [up for *_, up in ref]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
