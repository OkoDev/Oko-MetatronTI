"""Unit-тесты для core.intelligence.wt_service (ARCH-117 Phase 1, 30.05.2026).

Проверяет единый источник правды WaveTrend:
  - wt_cross      = сырой кросс (обратная совместимость с WTSpecialist)
  - cross_in_zone = строгий: wt1 был в OS/OB ДО кросса (combinator-стиль)
  - zone          = текущая зона по wt1 (±60, стандарт WaveTrend)
"""
import pandas as pd

from core.intelligence.wt_service import (
    build_wt_snap_entry, build_wt_snap, WT_OS, WT_OB,
)


def _mk(wt1_prev, wt2_prev, wt1_cur, wt2_cur, trend=1):
    """3-барный df: [filler, prev, cur]."""
    return pd.DataFrame({
        "wt1":   [0.0, wt1_prev, wt1_cur],
        "wt2":   [0.0, wt2_prev, wt2_cur],
        "trend": [trend, trend, trend],
    })


class TestThresholds:
    def test_standard_levels(self):
        assert WT_OS == -60.0
        assert WT_OB == 60.0


class TestWtCrossRaw:
    def test_bull_cross_detected(self):
        snap = build_wt_snap_entry(_mk(-25, -20, -5, -10), "1h")
        assert snap["wt_cross"] == 1

    def test_bear_cross_detected(self):
        snap = build_wt_snap_entry(_mk(25, 20, 5, 10), "1h")
        assert snap["wt_cross"] == -1

    def test_no_cross(self):
        snap = build_wt_snap_entry(_mk(-50, -55, -52, -56), "1h")
        assert snap["wt_cross"] == 0


class TestCrossInZone:
    def test_bull_cross_from_os(self):
        # wt1_prev=-72 (< -60, в OS), кросс вверх → cross_in_zone=1
        snap = build_wt_snap_entry(_mk(-72, -65, -55, -60), "1h")
        assert snap["wt_cross"] == 1
        assert snap["cross_in_zone"] == 1

    def test_bull_cross_not_in_zone(self):
        # wt1_prev=-25 (НЕ в OS), кросс есть, но cross_in_zone=0
        snap = build_wt_snap_entry(_mk(-25, -20, -5, -10), "1h")
        assert snap["wt_cross"] == 1
        assert snap["cross_in_zone"] == 0

    def test_bear_cross_from_ob(self):
        snap = build_wt_snap_entry(_mk(72, 65, 55, 60), "1h")
        assert snap["wt_cross"] == -1
        assert snap["cross_in_zone"] == -1

    def test_bear_cross_not_in_zone(self):
        snap = build_wt_snap_entry(_mk(25, 20, 5, 10), "1h")
        assert snap["wt_cross"] == -1
        assert snap["cross_in_zone"] == 0

    def test_boundary_exactly_below_os(self):
        # wt1_prev=-61 < -60 → в зоне
        snap = build_wt_snap_entry(_mk(-61, -55, -58, -60), "1h")
        assert snap["cross_in_zone"] == 1

    def test_zone_before_cross_not_current(self):
        # КЛЮЧЕВОЙ кейс: wt1 вышел из OS в момент кросса.
        # zone текущая = N (wt1_cur=-55 > -60), но cross_in_zone=1 (был -72 ДО)
        snap = build_wt_snap_entry(_mk(-72, -65, -55, -60), "1h")
        assert snap["zone"] == "N"          # текущая зона
        assert snap["cross_in_zone"] == 1   # но кросс из зоны


class TestZone:
    def test_zone_os(self):
        snap = build_wt_snap_entry(_mk(-72, -65, -70, -68), "1h")
        assert snap["zone"] == "OS"

    def test_zone_ob(self):
        snap = build_wt_snap_entry(_mk(72, 65, 70, 68), "1h")
        assert snap["zone"] == "OB"

    def test_zone_neutral(self):
        snap = build_wt_snap_entry(_mk(0, 5, 10, 8), "1h")
        assert snap["zone"] == "N"


class TestBackwardCompat:
    """WTSpecialist читает wt_cross + zone + trend + atr_trend — должны присутствовать."""
    def test_all_legacy_fields_present(self):
        snap = build_wt_snap_entry(_mk(-72, -65, -55, -60, trend=1), "1h")
        assert set(snap) >= {"wt1", "wt2", "zone", "wt_cross", "trend", "atr_trend"}
        assert snap["trend"] == "UP"
        assert snap["atr_trend"] == 1

    def test_trend_down(self):
        snap = build_wt_snap_entry(_mk(-72, -65, -55, -60, trend=-1), "1h")
        assert snap["trend"] == "DOWN"
        assert snap["atr_trend"] == -1


class TestBuildSnap:
    def test_skips_invalid_tf(self):
        valid = _mk(-72, -65, -55, -60)
        snap = build_wt_snap([("1h", valid), ("4h", None), ("15m", pd.DataFrame())])
        assert "1h" in snap
        assert "4h" not in snap
        assert "15m" not in snap

    def test_missing_wt_columns(self):
        bad = pd.DataFrame({"close": [1, 2, 3]})
        assert build_wt_snap_entry(bad, "1h") is None
