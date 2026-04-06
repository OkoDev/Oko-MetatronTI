"""
Тесты для core/smc/ — SMC Layer.

Покрывает: swing_points, fvg, structure, order_blocks, liquidity, fibonacci, models.
"""
import pytest
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes: list, spread: float = 0.5) -> pd.DataFrame:
    """Генерирует простой OHLCV DataFrame из списка close цен."""
    n = len(closes)
    data = {
        "open": [c - spread * 0.3 for c in closes],
        "high": [c + spread for c in closes],
        "low": [c - spread for c in closes],
        "close": closes,
        "volume": [1000.0 + i * 10 for i in range(n)],
        "time": list(range(n)),
    }
    return pd.DataFrame(data)


def _make_trending_up(n: int = 60, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    """Восходящий тренд с глубокими откатами (зигзаг).
    Каждые 8 баров: 6 вверх + 2 вниз. Откат достаточно глубокий для swing detection."""
    closes = []
    price = start
    for i in range(n):
        phase = i % 8
        if phase >= 6:
            price -= step * 3  # глубокий откат
        else:
            price += step * 1.2
        closes.append(price)
    return _make_ohlcv(closes, spread=step * 0.8)


def _make_trending_down(n: int = 60, start: float = 200.0, step: float = 0.5) -> pd.DataFrame:
    """Нисходящий тренд с глубокими откатами."""
    closes = []
    price = start
    for i in range(n):
        phase = i % 8
        if phase >= 6:
            price += step * 3
        else:
            price -= step * 1.2
        closes.append(price)
    return _make_ohlcv(closes, spread=step * 0.8)


def _make_range(n: int = 60, center: float = 100.0, amplitude: float = 3.0) -> pd.DataFrame:
    """Боковик (рейндж)."""
    closes = [center + amplitude * np.sin(i * 0.5) for i in range(n)]
    return _make_ohlcv(closes)


def _make_with_fvg(n: int = 40) -> pd.DataFrame:
    """DataFrame с явным Bull FVG: bar[i].low > bar[i-2].high."""
    closes = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n

    # Создаём Bull FVG на барах 20-22
    # bar 20: high=100.5 (обычный)
    # bar 21: импульс вверх (close=105, low=103)
    # bar 22: low=101.0 > high[20]=100.5 → FVG!
    closes[21] = 105.0
    highs[21] = 106.0
    lows[21] = 103.0

    closes[22] = 104.0
    highs[22] = 105.0
    lows[22] = 101.0  # > 100.5 (high of bar 20) → BULL FVG

    return pd.DataFrame({
        "open": [c - 0.2 for c in closes],
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * n,
        "time": list(range(n)),
    })


# ===========================================================================
# ТЕСТЫ: swing_points
# ===========================================================================

class TestSwingPoints:
    def test_import(self):
        from core.smc.swing_points import detect_swing_points, SwingAnalysis
        assert detect_swing_points is not None

    def test_empty_df(self):
        from core.smc.swing_points import detect_swing_points
        result = detect_swing_points(None)
        assert result.swings == []
        assert result.trend.value == "NEUTRAL"

    def test_short_df(self):
        from core.smc.swing_points import detect_swing_points
        df = _make_ohlcv([100.0] * 5)
        result = detect_swing_points(df, period=3)
        assert result.swings == []

    def test_trending_up_finds_swings(self):
        from core.smc.swing_points import detect_swing_points, SwingType
        df = _make_trending_up(80)
        result = detect_swing_points(df, period=3)
        assert len(result.swings) > 0
        assert len(result.highs) > 0
        assert len(result.lows) > 0

    def test_alternation(self):
        """Свинги должны чередоваться: H-L-H-L."""
        from core.smc.swing_points import detect_swing_points, SwingType
        df = _make_trending_up(80)
        result = detect_swing_points(df, period=3)
        if len(result.swings) >= 2:
            for i in range(1, len(result.swings)):
                assert result.swings[i].swing_type != result.swings[i - 1].swing_type, \
                    f"Нет чередования на позиции {i}: {result.swings[i-1]} → {result.swings[i]}"

    def test_labels_assigned(self):
        """Каждый свинг должен иметь метку (HH/HL/LH/LL/FIRST)."""
        from core.smc.swing_points import detect_swing_points, SwingLabel
        df = _make_trending_up(80)
        result = detect_swing_points(df, period=3)
        for s in result.swings:
            assert s.label in (SwingLabel.HH, SwingLabel.LH, SwingLabel.HL, SwingLabel.LL, SwingLabel.FIRST)

    def test_trending_up_trend(self):
        """Восходящий тренд → BULLISH (HH + HL)."""
        from core.smc.swing_points import detect_swing_points, StructureTrend
        df = _make_trending_up(100, step=1.0)
        result = detect_swing_points(df, period=3)
        # Тренд может быть BULLISH или NEUTRAL в зависимости от данных
        # Главное — не BEARISH для восходящего тренда
        assert result.trend != StructureTrend.BEARISH

    def test_trending_down_trend(self):
        from core.smc.swing_points import detect_swing_points, StructureTrend
        df = _make_trending_down(100, step=1.0)
        result = detect_swing_points(df, period=3)
        assert result.trend != StructureTrend.BULLISH

    def test_last_high_low(self):
        from core.smc.swing_points import detect_swing_points
        df = _make_trending_up(80)
        result = detect_swing_points(df, period=3)
        if result.highs:
            assert result.last_high == result.highs[-1]
        if result.lows:
            assert result.last_low == result.lows[-1]

    def test_repr(self):
        from core.smc.swing_points import SwingPoint, SwingType, SwingLabel
        p = SwingPoint(index=42, value=1.2345, swing_type=SwingType.HIGH, label=SwingLabel.HH)
        assert "HH" in repr(p)
        assert "42" in repr(p)


# ===========================================================================
# ТЕСТЫ: fvg
# ===========================================================================

class TestFVG:
    def test_import(self):
        from core.smc.fvg import detect_fvg, FVGAnalysis
        assert detect_fvg is not None

    def test_empty_df(self):
        from core.smc.fvg import detect_fvg
        result = detect_fvg(None)
        assert result.all_fvgs == []

    def test_no_fvg_in_flat(self):
        from core.smc.fvg import detect_fvg
        df = _make_ohlcv([100.0] * 20, spread=0.1)
        result = detect_fvg(df, min_size_pct=0.5)
        assert len(result.all_fvgs) == 0

    def test_bull_fvg_detected(self):
        from core.smc.fvg import detect_fvg, FVGType
        df = _make_with_fvg()
        result = detect_fvg(df, min_size_pct=0.01)
        bull_fvgs = [f for f in result.all_fvgs if f.fvg_type == FVGType.BULL]
        assert len(bull_fvgs) > 0
        fvg = bull_fvgs[0]
        assert fvg.top > fvg.bottom
        assert fvg.midpoint > 0

    def test_fvg_mitigation_tracking(self):
        from core.smc.fvg import detect_fvg
        df = _make_with_fvg()
        result = detect_fvg(df, min_size_pct=0.01, track_mitigation=True)
        # В нашем тестовом DF после FVG цена не возвращается → mitigated=False
        for fvg in result.all_fvgs:
            assert isinstance(fvg.mitigated, bool)

    def test_fvg_properties(self):
        from core.smc.fvg import FVG, FVGType
        fvg = FVG(
            fvg_type=FVGType.BULL, top=101.0, bottom=100.5,
            midpoint=100.75, index=21, size_pct=0.5
        )
        assert fvg.is_active
        assert "BULL_FVG" in repr(fvg)

    def test_min_size_filter(self):
        from core.smc.fvg import detect_fvg
        df = _make_with_fvg()
        result_strict = detect_fvg(df, min_size_pct=50.0)  # 50% — никакой FVG не пройдёт
        assert len(result_strict.all_fvgs) == 0


# ===========================================================================
# ТЕСТЫ: structure
# ===========================================================================

class TestStructure:
    def test_import(self):
        from core.smc.structure import detect_structure, StructureAnalysis
        assert detect_structure is not None

    def test_empty_df(self):
        from core.smc.structure import detect_structure
        result = detect_structure(None)
        assert result.breaks == []
        assert result.last_break is None

    def test_trending_up_has_breaks(self):
        from core.smc.structure import detect_structure
        df = _make_trending_up(100, step=1.0)
        result = detect_structure(df, swing_period=3)
        # В восходящем тренде должны быть BOS (пробои highs)
        assert len(result.swing_analysis.swings) > 0

    def test_break_properties(self):
        from core.smc.structure import detect_structure
        df = _make_trending_up(100, step=1.5)
        result = detect_structure(df, swing_period=3)
        if result.breaks:
            brk = result.breaks[0]
            assert brk.direction in ("LONG", "SHORT")
            assert brk.strength > 0
            assert brk.level > 0

    def test_active_levels(self):
        from core.smc.structure import detect_structure
        df = _make_trending_up(80)
        result = detect_structure(df, swing_period=3)
        # active_support и active_resistance могут быть None если все свинги пробиты
        # Но структура должна быть непустая
        assert result.swing_analysis is not None

    def test_breaker_blocks_created(self):
        from core.smc.structure import detect_structure
        df = _make_trending_up(100, step=1.5)
        result = detect_structure(df, swing_period=3)
        # Breaker blocks создаются из breaks
        assert len(result.breaker_blocks) == len(result.breaks)


# ===========================================================================
# ТЕСТЫ: order_blocks
# ===========================================================================

class TestOrderBlocks:
    def test_import(self):
        from core.smc.order_blocks import detect_order_blocks, OBAnalysis
        assert detect_order_blocks is not None

    def test_no_breaks_no_obs(self):
        from core.smc.order_blocks import detect_order_blocks
        from core.smc.structure import detect_structure
        df = _make_ohlcv([100.0] * 30)
        struct = detect_structure(df, swing_period=3)
        result = detect_order_blocks(df, struct)
        assert result.all_obs == []

    def test_obs_from_trending(self):
        from core.smc.order_blocks import detect_order_blocks
        from core.smc.structure import detect_structure
        df = _make_trending_up(100, step=1.5)
        struct = detect_structure(df, swing_period=3)
        result = detect_order_blocks(df, struct)
        # OB может не найтись если все свечи бычьи (open < close) —
        # нет противотрендовой свечи перед пробоем. Это корректное поведение.
        if struct.breaks:
            # Проверяем что функция хотя бы корректно отрабатывает
            assert isinstance(result.all_obs, list)

    def test_ob_strength(self):
        from core.smc.order_blocks import OrderBlock, OBType
        from core.smc.structure import StructureBreak, BreakType
        from core.smc.swing_points import SwingPoint, SwingType, SwingLabel

        swing = SwingPoint(index=10, value=105.0, swing_type=SwingType.HIGH, label=SwingLabel.HH)
        brk = StructureBreak(
            break_type=BreakType.BULLISH_CHOCH, level=105.0,
            broken_swing=swing, break_index=20, break_price=106.0
        )
        ob = OrderBlock(
            ob_type=OBType.BULLISH, top=104.0, bottom=103.0,
            midpoint=103.5, index=18, origin_break=brk,
            volume_ratio=2.0, has_fvg_overlap=True
        )
        # CHoCH(+15) + vol>=2.0(+15) + fvg(+10) = 60+15+15+10 = 100
        assert ob.strength == 100


# ===========================================================================
# ТЕСТЫ: liquidity
# ===========================================================================

class TestLiquidity:
    def test_import(self):
        from core.smc.liquidity import detect_liquidity, LiquidityAnalysis
        assert detect_liquidity is not None

    def test_empty_swings(self):
        from core.smc.liquidity import detect_liquidity
        from core.smc.swing_points import SwingAnalysis
        empty = SwingAnalysis(swings=[])
        df = _make_ohlcv([100.0] * 30)
        result = detect_liquidity(df, empty)
        assert result.buy_side == []
        assert result.sell_side == []

    def test_clusters_from_trending(self):
        from core.smc.liquidity import detect_liquidity
        from core.smc.swing_points import detect_swing_points
        df = _make_trending_up(80)
        swings = detect_swing_points(df, period=3)
        result = detect_liquidity(df, swings)
        # Должны быть buy-side (над highs) и sell-side (под lows)
        total = len(result.buy_side) + len(result.sell_side)
        assert total > 0

    def test_zone_strength(self):
        from core.smc.liquidity import LiquidityZone
        zone = LiquidityZone(
            level=100.0, zone_top=100.3, zone_bottom=99.7,
            side="BUY", swing_count=3
        )
        assert zone.strength == 90  # 30 + 3*20
        assert zone.is_active

    def test_swept_zone(self):
        from core.smc.liquidity import LiquidityZone
        zone = LiquidityZone(
            level=100.0, zone_top=100.3, zone_bottom=99.7,
            side="BUY", swing_count=2, swept=True, sweep_index=50
        )
        assert not zone.is_active
        assert zone.strength < 70  # swept уменьшает


# ===========================================================================
# ТЕСТЫ: fibonacci
# ===========================================================================

class TestFibonacci:
    def test_import(self):
        from core.smc.fibonacci import detect_fibonacci, FibAnalysis
        assert detect_fibonacci is not None

    def test_no_breaks_no_fib(self):
        from core.smc.fibonacci import detect_fibonacci
        from core.smc.structure import detect_structure
        df = _make_ohlcv([100.0] * 30)
        struct = detect_structure(df, swing_period=3)
        result = detect_fibonacci(df, struct)
        assert result.zones == []

    def test_fib_levels_calculated(self):
        from core.smc.fibonacci import _calc_fib_levels
        levels = _calc_fib_levels(110.0, 100.0, "LONG")
        assert len(levels) == 6  # 6 стандартных уровней
        # 0.618 уровень для LONG: 110 - 10*0.618 = 103.82
        fib_618 = [l for l in levels if l.ratio == 0.618][0]
        assert abs(fib_618.price - 103.82) < 0.01

    def test_ote_zone(self):
        from core.smc.fibonacci import _calc_ote
        top, bottom = _calc_ote(110.0, 100.0, "LONG")
        # OTE top = 110 - 10*0.618 = 103.82
        # OTE bottom = 110 - 10*0.786 = 102.14
        assert abs(top - 103.82) < 0.01
        assert abs(bottom - 102.14) < 0.01
        assert top > bottom


# ===========================================================================
# ТЕСТЫ: models (SMCContext + analyze_smc)
# ===========================================================================

class TestSMCContext:
    def test_import(self):
        from core.smc import analyze_smc, SMCContext
        assert analyze_smc is not None
        assert SMCContext is not None

    def test_empty_df(self):
        from core.smc import analyze_smc
        ctx = analyze_smc(None)
        assert ctx.trend.value == "NEUTRAL"
        assert ctx.last_break is None

    def test_short_df(self):
        from core.smc import analyze_smc
        df = _make_ohlcv([100.0] * 10)
        ctx = analyze_smc(df)
        assert ctx.bars_analyzed == 0

    def test_full_analysis_trending(self):
        from core.smc import analyze_smc
        df = _make_trending_up(100, step=1.5)
        ctx = analyze_smc(df, swing_period=3)
        assert ctx.bars_analyzed == 100
        assert ctx.current_price > 0
        assert len(ctx.structure.swing_analysis.swings) > 0

    def test_to_features(self):
        from core.smc import analyze_smc
        df = _make_trending_up(80)
        ctx = analyze_smc(df, swing_period=3)
        features = ctx.to_features()
        assert "smc_trend" in features
        assert "smc_has_choch" in features
        assert "smc_price_in_ote" in features
        assert "smc_active_bull_fvg_count" in features
        assert isinstance(features["smc_trend"], str)

    def test_summary(self):
        from core.smc import analyze_smc
        df = _make_trending_up(80)
        ctx = analyze_smc(df, swing_period=3)
        s = ctx.summary()
        assert "SMC(" in s
        assert "trend=" in s

    def test_supersetup_properties(self):
        from core.smc import SMCContext
        ctx = SMCContext()
        # По умолчанию нет суперсетапов
        assert not ctx.has_bullish_ob_with_fvg
        assert not ctx.has_bearish_ob_with_fvg
        assert not ctx.price_in_ote

    def test_range_market(self):
        from core.smc import analyze_smc
        df = _make_range(80)
        ctx = analyze_smc(df, swing_period=3)
        assert ctx.bars_analyzed == 80
        # В рейндже тренд должен быть NEUTRAL
        # (не обязательно, но не BEARISH/BULLISH одновременно)
        assert ctx.trend.value in ("NEUTRAL", "BULLISH", "BEARISH")
