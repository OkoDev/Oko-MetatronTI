"""Unit-тесты для PivotSphere (ARCH-123, 30.05.2026)."""
from core.pivots.pivot_sphere import (
    PivotSphere, get_pivot_sphere, FIB_EQUIV,
)


class _FakeCalc:
    def __init__(self, cache):
        self.pivot_cache = cache


def _cache(sym="BTC"):
    return {
        f"{sym}_1D": {"PP": 100, "S1": 98, "S2": 96, "S3": 94,
                      "R1": 102, "R2": 104, "R3": 106, "period_label": "2026-05-30"},
        f"{sym}_1W": {"PP": 95, "S1": 90, "R1": 100, "period_label": "2026-W22"},
    }


class TestFibEquiv:
    def test_ote_levels(self):
        # R2/S2 = OTE (0.618), R3/S3 = extension (1.0)
        assert FIB_EQUIV["R2"] == 0.618
        assert FIB_EQUIV["S2"] == 0.618
        assert FIB_EQUIV["R3"] == 1.0
        assert FIB_EQUIV["PP"] == 0.5


class TestPivotSphere:
    def test_snap_structure(self):
        sph = PivotSphere()
        snap = sph.compute_and_publish("BTC", _FakeCalc(_cache()), ctx_bus=None)
        assert snap is not None
        assert "1D" in snap and "1W" in snap
        assert "fibonacci_equiv" in snap
        # period_label отфильтрован, остались только pivot-уровни
        assert "period_label" not in snap["1D"]
        assert snap["1D"]["PP"] == 100
        assert snap["1D"]["R2"] == 104

    def test_only_numeric_keys(self):
        sph = PivotSphere()
        snap = sph.compute_and_publish("BTC", _FakeCalc(_cache()), ctx_bus=None)
        for k in snap["1D"]:
            assert k in ("PP", "S1", "S2", "S3", "R1", "R2", "R3")

    def test_none_calc(self):
        assert PivotSphere().compute_and_publish("BTC", None, ctx_bus=None) is None

    def test_empty_cache(self):
        assert PivotSphere().compute_and_publish("BTC", _FakeCalc({}), ctx_bus=None) is None

    def test_no_match_symbol(self):
        # Кэш есть, но для другого символа
        assert PivotSphere().compute_and_publish("ETH", _FakeCalc(_cache("BTC")), ctx_bus=None) is None

    def test_singleton(self):
        assert get_pivot_sphere() is get_pivot_sphere()

    def test_bus_publish_called(self):
        calls = []

        class _Bus:
            def publish(self, sym, event, data):
                calls.append((sym, event, data))

        snap = PivotSphere().compute_and_publish("BTC", _FakeCalc(_cache()), ctx_bus=_Bus())
        assert snap is not None
        assert len(calls) == 1
        assert calls[0][0] == "BTC"
        assert "fibonacci_equiv" in calls[0][2]
