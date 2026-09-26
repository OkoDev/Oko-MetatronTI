"""Зоны и уровни core/structure (фаза 2 чистой переписки, docs/STRUCTURE_KERNEL_SPEC.md).

Охраняют соглашения спецификации, причинность префиксом для полей, которые известны сразу,
и паритет со старыми функциями smc_engine, пока они существуют.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.structure import (equal_levels, fair_value_gaps, label_swings, level_breaks,  # noqa: E402
                            order_blocks, range_zones, two_sided_pivots)


def _walk(n=3000, seed=5):
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 3, 0.05), np.full(n // 3, -0.06), np.full(n - 2 * (n // 3), 0.02)])
    close = 100 + np.cumsum(rng.normal(0, 0.6, n) + drift)
    open_ = np.concatenate(([close[0]], close[:-1]))
    wick = np.abs(rng.normal(0, 0.5, n))
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    volume = rng.lognormal(10, 0.5, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


class TestLevelBreaks:
    def test_close_beyond_level_and_one_per_bar(self):
        d = _walk()
        c = d.close.to_numpy()
        bars = [b.bar for b in level_breaks(d, window=20)]
        assert bars and len(bars) == len(set(bars))
        for b in level_breaks(d, window=20):
            assert (c[b.bar] > b.level) if b.bullish else (c[b.bar] < b.level)

    def test_short_series_has_no_structure(self):
        assert level_breaks(_walk(n=101), window=50) == []

    @pytest.mark.parametrize("k", [700, 1900])
    def test_causal_by_prefix(self, k):
        d = _walk()
        full = level_breaks(d, window=20)
        part = level_breaks(d.iloc[:k], window=20)
        assert part == [b for b in full if b.bar < k]


class TestLabelsAndZones:
    def test_labels_follow_previous_same_kind(self):
        labs = label_swings(_walk(), 20)
        last = {}
        for _, price, tag in labs:
            kind = tag[1]                       # H или L
            prev = last.get(kind)
            if prev is None:
                assert tag in ("HH", "LL")
            elif kind == "H":
                assert tag == ("HH" if price > prev else "LH")
            else:
                assert tag == ("LL" if price < prev else "HL")
            last[kind] = price

    def test_range_zones_are_ordered(self):
        z = range_zones(110.0, 90.0)
        assert z["lower"][0] == 90.0 and z["upper"][1] == 110.0
        assert z["lower"][1] < z["middle"][0] < z["mid"] < z["middle"][1] < z["upper"][0]


class TestZones:
    def test_blocks_come_from_calm_extreme_candle(self):
        d = _walk()
        breaks = level_breaks(d, window=20)
        blocks = order_blocks(d, breaks)
        assert blocks
        by_bar = {b.bar: b for b in breaks}
        for blk in blocks:
            brk = by_bar[blk.break_bar]
            assert min(brk.level_bar, brk.bar) <= blk.origin_bar <= brk.bar
            assert blk.flipped == (blk.gone_bar != -1)
            if blk.gone_bar != -1:
                c = d.close.iloc[blk.gone_bar]
                assert (c < blk.bottom) if blk.bullish else (c > blk.top)

    def test_block_origin_is_causal(self):
        d = _walk()
        k = 1800
        full = [(b.origin_bar, b.top, b.bottom, b.break_bar) for b in order_blocks(d, level_breaks(d, 20))]
        part = [(b.origin_bar, b.top, b.bottom, b.break_bar)
                for b in order_blocks(d.iloc[:k], level_breaks(d.iloc[:k], 20))]
        assert part == [x for x in full if x[3] < k]

    def test_two_sided_pivots_rule(self):
        v = np.array([1, 2, 5, 3, 5, 2, 1, 0, 1, 2], dtype=float)
        # бар 2: слева 1,2 < 5, справа 3,5 ≤ 5 → вершина; бар 4: слева 3,5 — не строго ниже → нет
        assert (2, 5.0) in two_sided_pivots(v, 2, highs=True)
        assert all(b != 4 for b, _ in two_sided_pivots(v, 2, highs=True))

    def test_equal_pairs_are_neighbours_within_tolerance(self):
        d = _walk(seed=9)
        pairs = equal_levels(d, window=3, tolerance=0.5)
        assert pairs
        for p in pairs:
            assert p.first_bar < p.second_bar

    @pytest.mark.parametrize("threshold", [None, 0.0])
    def test_gaps_rule_and_causality(self, threshold):
        d = _walk(seed=13)
        h, l, c = d.high.to_numpy(), d.low.to_numpy(), d.close.to_numpy()
        gaps = fair_value_gaps(d, threshold)
        for g in gaps:
            t = g.bar
            if g.bullish:
                assert l[t] > h[t - 2] and c[t - 1] > h[t - 2]
            else:
                assert h[t] < l[t - 2] and c[t - 1] < l[t - 2]
        k = 2000
        known = [(g.left_bar, g.top, g.bottom, g.bullish, g.bar) for g in gaps if g.bar < k]
        part = [(g.left_bar, g.top, g.bottom, g.bullish, g.bar) for g in fair_value_gaps(d.iloc[:k], threshold)]
        assert part == known


def test_parity_with_reference_while_it_exists():
    ref = pytest.importorskip("core.smc.smc_engine")
    d = _walk(n=4000, seed=17)
    pos = {ts: i for i, ts in enumerate(d.index)}
    old_b, new_b = ref.detect_structure_breaks(d, length=20), level_breaks(d, window=20)
    assert [(b.idx, b.price, b.kind, b.direction == "bull", b.has_volume, b.from_idx) for b in old_b] == \
           [(x.bar, x.level, x.kind, x.bullish, x.heavy_volume, x.level_bar) for x in new_b]
    assert [(o.left_idx, o.top, o.bottom, o.mitigated_idx) for o in ref.detect_order_blocks(d, old_b)] == \
           [(x.origin_bar, x.top, x.bottom, x.gone_bar) for x in order_blocks(d, new_b)]
    assert [(pos[a], p, pos[b], q) for a, p, b, q, _ in ref.detect_equal_levels(d, threshold=0.5)] == \
           [(x.first_bar, x.first_price, x.second_bar, x.second_price) for x in equal_levels(d, tolerance=0.5)]
    assert [(pos[a], t, b_, pos[i]) for a, t, b_, _, i, _ in ref.detect_fvg(d)] == \
           [(g.left_bar, g.top, g.bottom, g.bar) for g in fair_value_gaps(d)]
