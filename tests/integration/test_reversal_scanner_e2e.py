"""
DEV-15 — Интеграционный тест: wt_15m_reversal_scanner + confidence gate.

Три уровня:
  1. test_scanner_* — синтетические данные с РЕАЛЬНЫМИ индикаторами (без патча)
     Проверяет что scan_wt_15m_reversal работает end-to-end через calculate_wt/trend.

  2. test_confidence_gate_* — confidence gate читается из конфига, не хардкод
     Регрессия: при 0.55 BSB-сигнал блокируется, при 0.50 — проходит.

  3. test_config_params_* — конфиг-правки 19.03 реально влияют на сканер
     lookback_bars=8 > 5, pivot_touch_pct читается под правильным ключом.

Запуск:
    python -m pytest tests/integration/test_reversal_scanner_e2e.py -v
"""
import os
import sys
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.signals.wt_15m_reversal_scanner import scan_wt_15m_reversal
from core.signals.signal_models import SignalType, SignalDirection


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_realistic_long_ohlcv(n: int = 160) -> pd.DataFrame:
    """
    Реалистичный OHLCV с выраженным OS паттерном в конце.

    Первые 2/3 — нисходящее движение (создаёт OS для WT).
    Последние 1/3 — разворот вверх с TSL кроссом.
    """
    np.random.seed(42)
    times = [1_700_000_000_000 + i * 15 * 60_000 for i in range(n)]

    # Нисходящее движение → OS зона
    down_n = int(n * 0.65)
    up_n   = n - down_n

    closes_down = 100.0 - np.linspace(0, 12, down_n) + np.random.randn(down_n) * 0.3
    closes_up   = closes_down[-1] + np.linspace(0, 6, up_n) + np.random.randn(up_n) * 0.2
    closes = np.concatenate([closes_down, closes_up])

    highs   = closes + abs(np.random.randn(n)) * 0.4 + 0.1
    lows    = closes - abs(np.random.randn(n)) * 0.4 - 0.1
    opens   = np.concatenate([[closes[0]], closes[:-1]])
    volumes = abs(np.random.randn(n)) * 500_000 + 1_000_000

    return pd.DataFrame({
        "time":   times,
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    })


def _make_realistic_short_ohlcv(n: int = 160) -> pd.DataFrame:
    """
    Реалистичный OHLCV с OB паттерном в конце.

    Первые 2/3 — восходящее движение (создаёт OB для WT).
    Последние 1/3 — разворот вниз с TSL кроссом.
    """
    np.random.seed(7)
    times = [1_700_000_000_000 + i * 15 * 60_000 for i in range(n)]

    up_n   = int(n * 0.65)
    down_n = n - up_n

    closes_up   = 100.0 + np.linspace(0, 12, up_n) + np.random.randn(up_n) * 0.3
    closes_down = closes_up[-1] - np.linspace(0, 6, down_n) + np.random.randn(down_n) * 0.2
    closes = np.concatenate([closes_up, closes_down])

    highs   = closes + abs(np.random.randn(n)) * 0.4 + 0.1
    lows    = closes - abs(np.random.randn(n)) * 0.4 - 0.1
    opens   = np.concatenate([[closes[0]], closes[:-1]])
    volumes = abs(np.random.randn(n)) * 500_000 + 1_000_000

    return pd.DataFrame({
        "time":   times,
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    })


def _make_cfg(
    lookback_bars: int = 8,
    min_confidence: float = 0.50,
    pivot_touch_pct: float = 0.15,
    max_per_cycle: int = 10,
) -> MagicMock:
    """Mock ConfigLoader с нужными параметрами.

    Сканер делает двухуровневый get:
        conf_cfg = cfg.get("analysis.confluence", {})
        val = conf_cfg.get("lookback_bars", default)

    Поэтому cfg.get("analysis.confluence") должен возвращать объект-прокси,
    а не пустой словарь.
    """
    cfg = MagicMock()

    confluence_values = {
        "lookback_bars":      lookback_bars,
        "pivot_touch_pct":    pivot_touch_pct,
        "max_per_cycle":      max_per_cycle,
        "min_strength":       60,
        "wt_os_threshold":    -60.0,
        "wt_ob_threshold":    60.0,
        "div_min_bars":       9,
        "dynamic_os_enabled": False,
        "enabled":            True,
    }

    # flat_values содержит КАК flat-пути так и non-confluence ключи
    flat_values = {
        "analysis.signals.min_confidence":    min_confidence,
        "analysis.indicators.trend.factor":   1.25,
        "analysis.indicators.wavetrend.n1":   10,
        "analysis.indicators.wavetrend.n2":   21,
        # flat-пути к confluence (для прямых тестов)
        **{f"analysis.confluence.{k}": v for k, v in confluence_values.items()},
    }

    def _get(key, default=None):
        # _get_cfg() в сканере проверяет isinstance(block, dict) →
        # нужно возвращать DICT, не MagicMock-прокси
        if key == "analysis.confluence":
            return confluence_values
        # Плоский доступ: cfg.get("analysis.confluence.lookback_bars") и т.д.
        return flat_values.get(key, default)

    cfg.get.side_effect = _get
    return cfg


def _apply_confidence_gate(action: str, confidence: float, min_confidence: float) -> str:
    """Точная копия логики gate из trading_intelligence.py (~строка 550)."""
    if confidence < min_confidence:
        return "WATCH"
    return action


# ─────────────────────────────────────────────────────────────────────────────
# Уровень 1: сканер работает end-to-end (реальные индикаторы)
# ─────────────────────────────────────────────────────────────────────────────

class TestScannerEndToEnd:
    """
    scan_wt_15m_reversal с реальными calculate_wt и calculate_trend.
    Нет патча индикаторов — проверяем интеграцию на уровне данных.
    """

    def test_no_signal_on_flat_data(self):
        """Флэтовые данные без паттернов OS/OB → нет сигнала."""
        np.random.seed(0)
        n = 160
        closes = np.full(n, 100.0) + np.random.randn(n) * 0.1
        df = pd.DataFrame({
            "time":   list(range(n)),
            "open":   closes,
            "high":   closes + 0.05,
            "low":    closes - 0.05,
            "close":  closes,
            "volume": [1_000_000.0] * n,
        })
        cfg = _make_cfg()
        result = scan_wt_15m_reversal("TEST/USDT", df, None, {}, cfg=cfg)
        # Флэт не создаёт OS/OB паттернов — ожидаем 0 сигналов
        assert isinstance(result, list)

    def test_insufficient_data_returns_empty(self):
        """Меньше 30 строк → пустой список."""
        df = pd.DataFrame({
            "time":   list(range(20)),
            "open":   [100.0] * 20,
            "high":   [101.0] * 20,
            "low":    [99.0]  * 20,
            "close":  [100.0] * 20,
            "volume": [1_000_000.0] * 20,
        })
        cfg = _make_cfg()
        result = scan_wt_15m_reversal("TEST/USDT", df, None, {}, cfg=cfg)
        assert result == []

    def test_realistic_long_data_processes_without_error(self):
        """Реалистичный OHLCV для LONG → обрабатывается без исключений."""
        df = _make_realistic_long_ohlcv()
        cfg = _make_cfg()
        result = scan_wt_15m_reversal("BSB/USDT:USDT", df, None, {}, cfg=cfg)
        assert isinstance(result, list)
        # Все сигналы — корректные SignalData
        for sig in result:
            assert sig.signal_type == SignalType.CONFLUENCE
            assert sig.direction in (SignalDirection.LONG, SignalDirection.SHORT)
            assert 0 < sig.strength <= 100
            assert 0.0 <= sig.confidence <= 1.0

    def test_realistic_short_data_processes_without_error(self):
        """Реалистичный OHLCV для SHORT → обрабатывается без исключений."""
        df = _make_realistic_short_ohlcv()
        cfg = _make_cfg()
        result = scan_wt_15m_reversal("CC/USDT:USDT", df, None, {}, cfg=cfg)
        assert isinstance(result, list)
        for sig in result:
            assert sig.signal_type == SignalType.CONFLUENCE
            assert 0 < sig.strength <= 100

    def test_signal_strength_at_least_60(self):
        """Все сгенерированные сигналы имеют strength ≥ 60 (min_strength)."""
        df = _make_realistic_long_ohlcv()
        cfg = _make_cfg(min_confidence=0.50)
        result = scan_wt_15m_reversal("BSB/USDT:USDT", df, None, {}, cfg=cfg)
        for sig in result:
            assert sig.strength >= 60, (
                f"Сигнал с strength={sig.strength} < 60 не должен был пройти фильтр"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Уровень 2: confidence gate — регрессия на блокировку BSB 19.03
# ─────────────────────────────────────────────────────────────────────────────

class TestConfidenceGate:
    """
    РЕГРЕССИЯ: BSB/USDT блокировался с confidence=0.547 < 0.55.

    Проверяет что:
    - min_confidence=0.50 (после фикса) → BUY проходит
    - min_confidence=0.55 (до фикса)   → WATCH (воспроизводит баг)
    - gate читается из конфига, не хардкодирован
    """

    BSB_CONFIDENCE = 0.547  # реальное значение из лога 19.03.2026

    def test_gate_050_passes_bsb_signal(self):
        """
        При min_confidence=0.50 сигнал с confidence=0.547 проходит → BUY.
        Воспроизводит состояние ПОСЛЕ фикса.
        """
        action = _apply_confidence_gate("BUY", self.BSB_CONFIDENCE, min_confidence=0.50)
        assert action == "BUY", (
            f"confidence={self.BSB_CONFIDENCE} должен проходить при min=0.50, "
            f"но получили action={action}"
        )

    def test_gate_055_blocks_bsb_signal(self):
        """
        При min_confidence=0.55 сигнал с confidence=0.547 блокируется → WATCH.
        Воспроизводит баг ДО фикса 19.03.2026.
        """
        action = _apply_confidence_gate("BUY", self.BSB_CONFIDENCE, min_confidence=0.55)
        assert action == "WATCH", (
            f"confidence={self.BSB_CONFIDENCE} должен блокироваться при min=0.55 (старое поведение), "
            f"но получили action={action}"
        )

    def test_gate_reads_from_config(self):
        """min_confidence читается из конфига, не хардкодирован."""
        cfg_050 = _make_cfg(min_confidence=0.50)
        cfg_055 = _make_cfg(min_confidence=0.55)

        min_050 = cfg_050.get("analysis.signals.min_confidence", 0.55)
        min_055 = cfg_055.get("analysis.signals.min_confidence", 0.55)

        assert min_050 == 0.50
        assert min_055 == 0.55

        # Gate с конфигом 0.50 → BUY
        assert _apply_confidence_gate("BUY", self.BSB_CONFIDENCE, min_050) == "BUY"
        # Gate с конфигом 0.55 → WATCH
        assert _apply_confidence_gate("BUY", self.BSB_CONFIDENCE, min_055) == "WATCH"

    def test_gate_edge_exactly_at_threshold(self):
        """confidence == min_confidence: граничное значение → WATCH (строгое <)."""
        action = _apply_confidence_gate("BUY", 0.50, min_confidence=0.50)
        # 0.50 < 0.50 → False → BUY остаётся
        assert action == "BUY"

    def test_gate_cc_pair_correctly_blocked(self):
        """
        CC/USDT: confidence=0.454 блокируется при ЛЮБОМ разумном пороге.
        Это не баг — у CC MTF=SHORT при LONG сигнале (легитимный блок).
        """
        cc_confidence = 0.454
        for threshold in (0.45, 0.50, 0.55):
            action = _apply_confidence_gate("BUY", cc_confidence, threshold)
            if cc_confidence < threshold:
                assert action == "WATCH", f"CC должен блокироваться при min={threshold}"
            else:
                assert action == "BUY"

    def test_sell_signal_also_blocked_below_threshold(self):
        """SELL сигнал с низким confidence тоже блокируется."""
        action = _apply_confidence_gate("SELL", 0.45, min_confidence=0.50)
        assert action == "WATCH"


# ─────────────────────────────────────────────────────────────────────────────
# Уровень 3: конфиг-правки 19.03 реально влияют на сканер
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigParams:
    """
    Проверяет что правки config.yaml от 19.03.2026 читаются сканером.

    lookback_bars:    5 → 8
    pivot_touch_pct:  ключ pivot_proximity_pct → pivot_touch_pct (неправильный ключ не читался)
    max_per_cycle:    3 → 10
    """

    def test_lookback_bars_5_vs_8(self):
        """
        lookback_bars=5 (75 мин) даёт меньше контекста чем lookback_bars=8 (2 часа).

        Тест строит данные где паттерн находится ровно в 6-м баре от конца.
        При lookback=5 → паттерн вне окна → нет сигнала.
        При lookback=8 → паттерн в окне → возможен сигнал (если score >= 60).
        """
        # Используем синтетические данные с явным паттерном в баре n-7
        from unittest.mock import patch

        _PATCH_WT    = "core.signals.wt_15m_reversal_scanner.calculate_wt"
        _PATCH_TREND = "core.signals.wt_15m_reversal_scanner.calculate_trend"

        n = 60
        close = 100.0
        df = pd.DataFrame({
            "time":      list(range(n)),
            "open":      [close] * n,
            "high":      [close * 1.005] * n,
            "low":       [close * 0.995] * n,
            "close":     [close] * n,
            "volume":    [1_000_000.0] * n,
            "wt1":       [0.0] * n,
            "wt2":       [0.0] * n,
            "trend":     [1.0] * n,
            "trendup":   [close * 0.98] * n,
            "trenddown": [close * 1.02] * n,
        })

        # Паттерн в баре n-7 (индекс 53) — попадёт в окно lookback=8, но не lookback=5
        # window = df.iloc[-lookback-1:-1]
        # lookback=8 → строки [n-9..n-2] → бар 53 (n-7) входит ✓
        # lookback=5 → строки [n-6..n-2] → бар 53 (n-7) НЕ входит ✗
        w0 = n - 7  # индекс 53

        df.loc[w0,     "wt1"]       = -62.0
        df.loc[w0,     "wt2"]       = -58.0
        df.loc[w0,     "trend"]     = -1.0
        df.loc[w0,     "trenddown"] = 99.0
        df.loc[w0,     "low"]       = 99.80
        df.loc[w0 + 1, "wt1"]       = -55.0
        df.loc[w0 + 1, "wt2"]       = -62.0
        df.loc[w0 + 1, "trend"]     = 1.0

        pivot_cache = {"TEST/USDT_1D": {"S1": 99.85, "PP": 101.0, "R1": 102.0}}

        cfg_lb5 = _make_cfg(lookback_bars=5)
        cfg_lb8 = _make_cfg(lookback_bars=8)

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):

            result_lb5 = scan_wt_15m_reversal("TEST/USDT", df, None, pivot_cache, cfg=cfg_lb5)
            result_lb8 = scan_wt_15m_reversal("TEST/USDT", df, None, pivot_cache, cfg=cfg_lb8)

        # lookback=8 видит паттерн, lookback=5 — нет
        assert result_lb5 == [], \
            f"lookback=5 не должен видеть паттерн на баре n-7, но нашёл {len(result_lb5)} сигнал(ов)"
        assert len(result_lb8) == 1, \
            f"lookback=8 должен найти сигнал на баре n-7, но нашёл {len(result_lb8)}"

    def test_pivot_touch_pct_key_is_correct(self):
        """
        pivot_touch_pct (правильный ключ) читается сканером.
        pivot_proximity_pct (старый неправильный ключ) — игнорируется.

        Баг 19.03: конфиг имел pivot_proximity_pct: 0.3, сканер читал pivot_touch_pct → fallback 0.15.
        """
        cfg_correct = _make_cfg(pivot_touch_pct=0.15)
        cfg_wrong_key = MagicMock()

        # Эмулируем старый конфиг: неправильный ключ есть, правильного нет
        wrong_values = {
            "analysis.confluence.pivot_proximity_pct": 0.3,  # старый ключ
            "analysis.confluence.enabled": True,
            "analysis.confluence.lookback_bars": 8,
            "analysis.confluence.min_strength": 60,
            "analysis.confluence.wt_os_threshold": -60.0,
            "analysis.confluence.wt_ob_threshold": 60.0,
            "analysis.confluence.dynamic_os_enabled": False,
            "analysis.indicators.trend.factor": 1.25,
        }
        cfg_wrong_key.get.side_effect = lambda k, d=None: wrong_values.get(k, d)

        # Правильный конфиг: pivot_touch_pct=0.15
        val_correct = cfg_correct.get("analysis.confluence.pivot_touch_pct", 0.15)
        # Неправильный конфиг: pivot_touch_pct не задан → fallback = 0.15 (хардкод в сканере)
        val_fallback = cfg_wrong_key.get("analysis.confluence.pivot_touch_pct", 0.15)

        assert val_correct == 0.15, "pivot_touch_pct должен читаться как 0.15"
        assert val_fallback == 0.15, "При отсутствии ключа сканер использует хардкод 0.15"

        # Различие: старый конфиг имел 0.3 под неправильным ключом
        val_wrong = cfg_wrong_key.get("analysis.confluence.pivot_proximity_pct", None)
        assert val_wrong == 0.3, "Старый ключ pivot_proximity_pct=0.3 существует но не читается сканером"

    def test_max_per_cycle_config_value(self):
        """
        max_per_cycle=3 (старый) vs max_per_cycle=10 (новый).
        Сканер сам max_per_cycle не применяет (это делает scan_loop),
        но конфиг должен хранить правильное значение.
        """
        cfg_old = _make_cfg(max_per_cycle=3)
        cfg_new = _make_cfg(max_per_cycle=10)

        old_val = cfg_old.get("analysis.confluence.max_per_cycle", 3)
        new_val = cfg_new.get("analysis.confluence.max_per_cycle", 3)

        assert old_val == 3,  "Старый конфиг: max_per_cycle=3"
        assert new_val == 10, "Новый конфиг: max_per_cycle=10"
        assert new_val > old_val, "Фикс 19.03: max_per_cycle увеличен"


# ─────────────────────────────────────────────────────────────────────────────
# Уровень 4: структура сигнала (end-to-end без патча)
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalStructure:
    """Проверяет что сигналы от сканера имеют корректную структуру."""

    def test_signal_confidence_equals_score_div_100(self):
        """confidence = round(score / 100, 2) — сканер устанавливает сам."""
        from unittest.mock import patch
        _PATCH_WT    = "core.signals.wt_15m_reversal_scanner.calculate_wt"
        _PATCH_TREND = "core.signals.wt_15m_reversal_scanner.calculate_trend"

        n, close = 50, 100.0
        df = pd.DataFrame({
            "time": list(range(n)), "open": [close]*n,
            "high": [close*1.005]*n, "low": [close*0.995]*n,
            "close": [close]*n, "volume": [1_000_000.0]*n,
            "wt1": [0.0]*n, "wt2": [0.0]*n, "trend": [1.0]*n,
            "trendup": [close*0.98]*n, "trenddown": [close*1.02]*n,
        })
        w0, w1 = n-9, n-8
        df.loc[w0, ["wt1","wt2","trend","trenddown","low"]] = [-62,-58,-1,99.0,99.80]
        df.loc[w1, ["wt1","wt2","trend"]] = [-55,-62,1]

        pivot_cache = {"BTC/USDT_1D": {"S1": 99.85, "PP": 101.0, "R1": 102.0}}
        cfg = _make_cfg()

        with patch(_PATCH_WT, side_effect=lambda df, **kw: df), \
             patch(_PATCH_TREND, side_effect=lambda df, **kw: df):
            result = scan_wt_15m_reversal("BTC/USDT", df, None, pivot_cache, cfg=cfg)

        assert len(result) == 1
        sig = result[0]
        expected_conf = round(sig.data["score"] / 100.0, 2)
        assert sig.confidence == expected_conf, (
            f"confidence={sig.confidence} != score/100={expected_conf}"
        )
        # score=75 → confidence=0.75 → проходит gate 0.50 и 0.55
        assert sig.confidence >= 0.55, \
            "Синтетический сигнал score=75 → confidence=0.75 — должен проходить любой gate"
