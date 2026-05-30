"""Unit-тесты для SMCSubCube + liquidity в snapshot (ARCH-120, 30.05.2026)."""
import numpy as np
import pandas as pd

from core.smc.sub_cube import SMCSubCube, get_smc_sub_cube
from core.smc.smc_snapshot import build_smc_snapshot


def _synthetic_df(n=120, base=100.0, trend=-0.1, seed=1):
    """Синтетический OHLCV с лёгким трендом вниз + шум."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(trend, 1.0, n))
    close = np.maximum(close, 1.0)
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    op = close + rng.normal(0, 0.3, n)
    vol = np.abs(rng.normal(1000, 200, n))
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": op, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


class TestSnapshotLiquidity:
    def test_snapshot_has_liquidity_keys(self):
        ohlcv = {"1h": _synthetic_df(), "4h": _synthetic_df(seed=2)}
        snap = build_smc_snapshot("TEST", ohlcv)
        assert snap is not None
        # ARCH-120: liquidity ключи присутствуют
        for k in ("eqh_level", "eql_level", "eqh_near", "eql_near", "liq_tf"):
            assert k in snap

    def test_snapshot_has_all_magnet_sources(self):
        """Для ARCH-122: snap должен содержать все источники магнитов."""
        ohlcv = {"1h": _synthetic_df(), "4h": _synthetic_df(seed=2)}
        snap = build_smc_snapshot("TEST", ohlcv)
        assert snap is not None
        for k in ("nearest_bull_ob", "nearest_bear_ob",
                  "bull_fvg_active", "bear_fvg_active",
                  "fib_levels", "swing_high", "swing_low",
                  "eqh_level", "eql_level"):
            assert k in snap, f"missing magnet source: {k}"


class TestSMCSubCube:
    def test_compute_returns_snap_with_verdict(self):
        cube = SMCSubCube()
        ohlcv = {"1h": _synthetic_df(), "4h": _synthetic_df(seed=2)}
        snap = cube.compute_and_publish("TEST", ohlcv, ctx_bus=None)
        assert snap is not None
        assert "smc_verdict" in snap  # вердикт добавлен

    def test_empty_ohlcv_returns_none(self):
        cube = SMCSubCube()
        assert cube.compute_and_publish("TEST", {}, ctx_bus=None) is None

    def test_singleton(self):
        assert get_smc_sub_cube() is get_smc_sub_cube()

    def test_bus_publish_called(self):
        """ctx_bus.publish вызывается при наличии snap."""
        calls = []

        class _FakeBus:
            def publish(self, sym, event, data):
                calls.append((sym, event, data))

        cube = SMCSubCube()
        ohlcv = {"1h": _synthetic_df(), "4h": _synthetic_df(seed=2)}
        snap = cube.compute_and_publish("TEST", ohlcv, ctx_bus=_FakeBus())
        assert snap is not None
        # минимум SMC_SNAP_UPDATED опубликован
        assert any("TEST" == c[0] for c in calls)
        assert len(calls) >= 1
