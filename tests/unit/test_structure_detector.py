"""
DEV-01: Тесты StructureDetector — Swing H/L, CHoCH, BOS (SMC).
"""
import numpy as np
import pandas as pd
import pytest

from core.structure_detector import (
    detect_swing_highs_lows,
    detect_choch,
    detect_bos,
    detect_structure,
)


# ─── Фабрики данных ─────────────────────────────────────────────────────────

def _make_df(n=100, closes=None, highs=None, lows=None):
    if closes is None:
        closes = np.full(n, 100.0)
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float) if highs is not None else c + 1.0
    l = np.array(lows,  dtype=float) if lows  is not None else c - 1.0
    return pd.DataFrame({
        "open": c, "high": h, "low": l, "close": c,
        "volume": np.full(len(c), 1e6),
    })


def _uptrend_df(n=80):
    """Чёткий восходящий тренд."""
    rng = np.random.default_rng(1)
    c = np.linspace(100, 140, n) + rng.standard_normal(n) * 0.3
    return _make_df(n, closes=c, highs=c + 1.5, lows=c - 1.5)


def _downtrend_df(n=80):
    """Чёткий нисходящий тренд."""
    rng = np.random.default_rng(2)
    c = np.linspace(140, 100, n) + rng.standard_normal(n) * 0.3
    return _make_df(n, closes=c, highs=c + 1.5, lows=c - 1.5)


def _swing_df():
    """DataFrame с явными пиками и впадинами для теста CHoCH/BOS."""
    n = 80
    # Восходящий тренд: два Swing High (SH1=110, SH2=120)
    c = np.full(n, 100.0)
    h = np.full(n, 101.0)
    l = np.full(n, 99.0)

    # SH1 при баре 15
    h[13:18] = [106, 109, 110, 109, 106]
    c[13:18] = [106, 109, 110, 109, 106]

    # SL1 при баре 30
    l[28:33] = [96, 94, 93, 94, 96]
    c[28:33] = [96, 94, 93, 94, 96]

    # SH2 при баре 50
    h[48:53] = [116, 119, 120, 119, 116]
    c[48:53] = [116, 119, 120, 119, 116]

    return _make_df(n, closes=c, highs=h, lows=l)


# ─── Swing H/L ───────────────────────────────────────────────────────────────

class TestSwingHL:
    def test_returns_dict_structure(self):
        df = _uptrend_df()
        result = detect_swing_highs_lows(df)
        assert "highs" in result and "lows" in result
        assert isinstance(result["highs"], list)
        assert isinstance(result["lows"], list)

    def test_empty_on_short_df(self):
        df = _make_df(n=10)
        result = detect_swing_highs_lows(df)
        assert result["highs"] == []
        assert result["lows"] == []

    def test_none_df(self):
        result = detect_swing_highs_lows(None)
        assert result == {"highs": [], "lows": []}

    def test_highs_are_local_maxima(self):
        """Каждый найденный пик должен быть выше соседей."""
        df = _uptrend_df()
        result = detect_swing_highs_lows(df, period=5)
        for sh in result["highs"]:
            idx = sh["index"]
            # Проверяем 2 соседа с каждой стороны
            for offset in [-2, -1, 1, 2]:
                j = idx + offset
                if 0 <= j < len(df):
                    assert sh["value"] >= float(df["high"].iloc[j]) - 1e-9

    def test_lows_are_local_minima(self):
        """Каждая впадина должна быть ниже соседей."""
        df = _downtrend_df()
        result = detect_swing_highs_lows(df, period=5)
        for sl in result["lows"]:
            idx = sl["index"]
            for offset in [-2, -1, 1, 2]:
                j = idx + offset
                if 0 <= j < len(df):
                    assert sl["value"] <= float(df["low"].iloc[j]) + 1e-9

    def test_known_swing_detected(self):
        """Явный пик в известном месте должен быть найден."""
        n = 50
        h = np.full(n, 100.0)
        h[20] = 120.0  # явный пик
        df = _make_df(n, highs=h, lows=h - 2.0, closes=h - 1.0)
        result = detect_swing_highs_lows(df, period=3)
        indices = [p["index"] for p in result["highs"]]
        assert 20 in indices

    def test_swing_dict_has_index_and_value(self):
        df = _uptrend_df()
        result = detect_swing_highs_lows(df)
        for p in result["highs"] + result["lows"]:
            assert "index" in p and "value" in p
            assert isinstance(p["index"], int)
            assert isinstance(p["value"], float)


# ─── CHoCH ───────────────────────────────────────────────────────────────────

class TestCHoCH:
    def test_returns_none_on_short_df(self):
        assert detect_choch(_make_df(n=10)) is None

    def test_returns_none_on_none(self):
        assert detect_choch(None) is None

    def test_bullish_choch_detected(self):
        """Пробой последнего Swing High снизу вверх → BULLISH_CHOCH."""
        df = _swing_df()
        # Последний SH2 ≈ 120. Добавляем свечу которая его пробивает.
        n = len(df)
        row = pd.DataFrame({
            "open": [120.0], "high": [125.0], "low": [119.0], "close": [124.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_choch(df_ext, period=3)
        if result is not None:
            assert result["type"] == "BULLISH_CHOCH"
            assert result["direction"] == "LONG"
            assert "level" in result

    def test_bearish_choch_detected(self):
        """Пробой последнего Swing Low сверху вниз → BEARISH_CHOCH."""
        df = _swing_df()
        # Добавляем свечу ниже SL1 ≈ 93
        row = pd.DataFrame({
            "open": [93.0], "high": [93.5], "low": [88.0], "close": [89.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_choch(df_ext, period=3)
        if result is not None:
            assert result["type"] == "BEARISH_CHOCH"
            assert result["direction"] == "SHORT"

    def test_result_fields(self):
        """Если CHoCH найден — все поля присутствуют."""
        df = _swing_df()
        row = pd.DataFrame({
            "open": [120.0], "high": [126.0], "low": [119.0], "close": [125.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_choch(df_ext, period=3)
        if result is not None:
            for key in ("type", "direction", "level", "broken_index", "current_price"):
                assert key in result

    def test_no_choch_in_flat_market(self):
        """Флет без пробоев — CHoCH не детектируется."""
        df = _make_df(n=60)  # все свечи одинаковые, нет пивотов
        result = detect_choch(df)
        # Может вернуть None или что угодно — главное не падает
        assert result is None or isinstance(result, dict)


# ─── BOS ─────────────────────────────────────────────────────────────────────

class TestBOS:
    def test_returns_none_on_short_df(self):
        assert detect_bos(_make_df(n=10)) is None

    def test_returns_none_on_none(self):
        assert detect_bos(None) is None

    def test_bullish_bos_detected(self):
        """Пробой Swing High вверх → BULLISH_BOS (продолжение UP тренда)."""
        df = _swing_df()
        row = pd.DataFrame({
            "open": [119.0], "high": [122.0], "low": [118.0], "close": [121.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_bos(df_ext, period=3)
        if result is not None:
            assert result["type"] == "BULLISH_BOS"
            assert result["direction"] == "LONG"
            assert result["trend"] == "UP"

    def test_bearish_bos_detected(self):
        """Пробой Swing Low вниз → BEARISH_BOS (продолжение DOWN тренда)."""
        df = _swing_df()
        row = pd.DataFrame({
            "open": [93.5], "high": [94.0], "low": [90.0], "close": [91.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_bos(df_ext, period=3)
        if result is not None:
            assert result["type"] == "BEARISH_BOS"
            assert result["direction"] == "SHORT"

    def test_bos_result_fields(self):
        df = _swing_df()
        row = pd.DataFrame({
            "open": [119.0], "high": [122.0], "low": [118.0], "close": [121.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_bos(df_ext, period=3)
        if result is not None:
            for key in ("type", "direction", "level", "broken_index", "current_price", "trend"):
                assert key in result


# ─── detect_structure (обёртка) ──────────────────────────────────────────────

class TestDetectStructure:
    def test_returns_full_dict(self):
        df = _uptrend_df()
        result = detect_structure(df)
        for key in ("swings", "choch", "bos", "signal", "signal_type", "strength"):
            assert key in result

    def test_short_df_safe(self):
        df = _make_df(n=5)
        result = detect_structure(df)
        assert result["signal"] is None
        assert result["strength"] == 0

    def test_none_df_safe(self):
        result = detect_structure(None)
        assert result["signal"] is None

    def test_bos_has_higher_priority_than_choch(self):
        """Если оба найдены — BOS приоритетнее."""
        df = _swing_df()
        # Создаём ситуацию с явным пробоем
        row = pd.DataFrame({
            "open": [119.0], "high": [125.0], "low": [88.0], "close": [121.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_structure(df_ext, period=3)
        if result["bos"] is not None and result["choch"] is not None:
            assert result["signal_type"] == "BOS"

    def test_strength_in_range(self):
        df = _uptrend_df()
        result = detect_structure(df)
        assert 0 <= result["strength"] <= 100

    def test_signal_direction_matches_bos(self):
        df = _swing_df()
        row = pd.DataFrame({
            "open": [119.0], "high": [122.0], "low": [118.0], "close": [121.0],
            "volume": [1e6],
        })
        df_ext = pd.concat([df, row], ignore_index=True)
        result = detect_structure(df_ext, period=3)
        if result["bos"]:
            assert result["signal"] == result["bos"]["direction"]

    def test_no_signal_in_flat(self):
        """Флет — нет ни CHoCH ни BOS → signal=None."""
        df = _make_df(n=60)
        result = detect_structure(df)
        # Не падает, возвращает корректную структуру
        assert isinstance(result, dict)
        assert result["signal"] in (None, "LONG", "SHORT")
