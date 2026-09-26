"""Структурное ядро core/structure (фаза 1 чистой переписки, docs/STRUCTURE_KERNEL_SPEC.md).

Тесты охраняют:
  · соглашения спецификации (чередование, приоритет вершины, начальное состояние, один слом — один масштаб);
  · причинность префиксом — закон проекта: детектор не видит будущего;
  · отсутствие кода и имён порта LuxAlgo в новом пакете;
  · паритет со старым каноном, пока он существует (регрессия на время миграции).
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.structure import MAJOR, MINOR, active_leg, confirmed_pivots, trace_structure  # noqa: E402


def _frame(high, low=None, close=None):
    high = np.asarray(high, dtype=float)
    low = high - 1.0 if low is None else np.asarray(low, dtype=float)
    close = (high + low) / 2 if close is None else np.asarray(close, dtype=float)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close})


def _walk(n=3000, seed=7):
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 3, 0.04), np.full(n // 3, -0.05), np.full(n - 2 * (n // 3), 0.01)])
    close = 100 + np.cumsum(rng.normal(0, 0.5, n) + drift)
    wick = np.abs(rng.normal(0, 0.4, n))
    return _frame(close + wick, close - wick, close)


class TestPivots:
    def test_first_pivot_is_low_by_convention(self):
        # явная вершина на баре 2, впадина на баре 6
        high = [1, 2, 9, 3, 2, 2, 1.5, 3, 4, 5]
        low = [0, 1, 8, 2, 1, 1, 0.5, 2, 3, 4]
        pts = confirmed_pivots(high, low, 2)
        assert pts, "должна быть хотя бы одна точка"
        assert pts[0].is_high is False            # вершина до первой впадины не фиксируется

    def test_alternation_skips_repeated_highs(self):
        high = [5, 4, 3, 1, 3, 6, 4, 3, 7, 5, 4, 3, 2]
        low = [4, 3, 2, 0, 2, 5, 3, 2, 6, 4, 3, 2, 1]
        pts = confirmed_pivots(high, low, 2)
        kinds = [p.is_high for p in pts]
        assert all(a != b for a, b in zip(kinds, kinds[1:])), "виды обязаны чередоваться"

    def test_confirmation_is_window_bars_later(self):
        for p in confirmed_pivots(*_walk().pipe(lambda d: (d.high, d.low)), 5):
            assert p.confirmed_at == p.bar + 5

    def test_pivot_beats_whole_right_window(self):
        d = _walk()
        for p in confirmed_pivots(d.high, d.low, 5):
            right = d.high.values[p.bar + 1:p.bar + 6] if p.is_high else d.low.values[p.bar + 1:p.bar + 6]
            assert (p.price > right.max()) if p.is_high else (p.price < right.min())

    def test_short_series(self):
        assert confirmed_pivots([1, 2, 3], [0, 1, 2], 5) == []


class TestTrace:
    def test_break_crosses_level_by_close(self):
        d = _walk()
        tr = trace_structure(d)
        c = d.close.values
        assert tr.breaks, "на ряду с трендами должны быть сломы"
        for b in tr.breaks:
            if b.bullish:
                assert c[b.bar - 1] <= b.level < c[b.bar]
            else:
                assert c[b.bar - 1] >= b.level > c[b.bar]

    def test_reversal_means_against_previous_direction(self):
        tr = trace_structure(_walk())
        for scale in (MAJOR, MINOR):
            direction = 0
            for b in (x for x in tr.breaks if x.scale == scale):
                assert b.reversal == (direction == (-1 if b.bullish else 1))
                direction = 1 if b.bullish else -1

    def test_minor_break_never_duplicates_major_level_on_same_bar(self):
        tr = trace_structure(_walk(seed=3), major=20, minor=5)
        major = {(b.bar, b.level) for b in tr.breaks if b.scale == MAJOR}
        minor = {(b.bar, b.level) for b in tr.breaks if b.scale == MINOR}
        assert not (major & minor)

    def test_leg_orientation(self):
        tr = trace_structure(_walk(), keep_legs=True)
        legs = [g for g in tr.legs if g]
        assert legs
        for g in legs:
            assert (g["origin"] < g["extreme"]) if g["trend"] == "long" else (g["origin"] > g["extreme"])
        assert tr.legs[0] is None and len(tr.legs) == 3000

    @pytest.mark.parametrize("k", [400, 1111, 2500])
    def test_causal_by_prefix(self, k):
        d = _walk()
        full = trace_structure(d, keep_legs=True)
        part = trace_structure(d.iloc[:k].reset_index(drop=True), keep_legs=True)
        assert part.breaks == [b for b in full.breaks if b.bar < k]
        assert part.legs == full.legs[:k]
        assert active_leg(part) == full.legs[k - 1]


def test_no_port_identifiers_in_new_package():
    forbidden = re.compile(r"luxalgo|trail_up|trail_dn|itop|ibtm|\bos_?\b|top_cross|Strong High|Weak Low|"
                           r"Internal Structure|Swing Structure|\bswings\(|ob_coord|parsed_?high|parsed_?low",
                           re.IGNORECASE)
    for path in (ROOT / "core" / "structure").glob("*.py"):
        hits = forbidden.findall(path.read_text(encoding="utf-8"))
        assert not hits, f"{path.name}: {hits}"


def test_no_legacy_names_in_production():
    """После фазы 4 прежних имён порта нет ни в боевом коде, ни в двух фасадах."""
    legacy = re.compile(r"_swings_luxalgo|\.(trail_up|trail_dn|itrend|top_y|btm_y)\b|\b_swings\b|"
                        r"\b(trail_up|trail_dn|top_y|btm_y)\s*=")
    hits = []
    for folder in ("core", "bot", "web"):
        for path in (ROOT / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if legacy.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{n}")
    assert not hits, hits


def test_parity_with_reference_while_it_exists():
    reference = pytest.importorskip("core.smc.oko_sm_engine")
    d = _walk(n=4000, seed=21)
    for major, minor in ((50, 5), (15, 4)):
        st = reference.run_structure(d, swing_len=major, internal_len=minor, record_legs=True)
        tr = trace_structure(d, major=major, minor=minor, keep_legs=True)
        assert [(e.i, e.kind, e.bull, e.level, e.internal, e.level_i) for e in st.events] == \
               [(b.bar, b.kind, b.bullish, b.level, b.scale == MINOR, b.level_bar) for b in tr.breaks]
        assert st.leg_history == tr.legs
