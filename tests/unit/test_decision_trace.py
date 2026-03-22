"""
Тесты DEV-12 (Этап 8.4.6): Decision Trace — аудит принятия решений.

Проверяем:
  1. DecisionTrace — создание, заполнение, сериализация
  2. add_signal, add_mtf_multiplier, add_filter, set_ml_adjustment
  3. to_dict / to_json — корректная сериализация
  4. summary — человекочитаемый формат
  5. Интеграция: trace записывается в recommendation.metadata
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.intelligence.decision_trace import DecisionTrace, create_trace


# ── DecisionTrace creation ──

class TestDecisionTraceCreation:

    def test_create_trace_sets_symbol_and_timestamp(self):
        """[01] create_trace заполняет symbol и timestamp."""
        trace = create_trace("BTCUSDT")
        assert trace.symbol == "BTCUSDT"
        assert trace.timestamp != ""
        # Парсится как дата
        datetime.strptime(trace.timestamp, "%Y-%m-%d %H:%M:%S")

    def test_empty_trace_defaults(self):
        """[02] Пустой trace — все списки пусты, значения по умолчанию."""
        trace = create_trace("ETHUSDT")
        assert trace.raw_signals == []
        assert trace.mtf_multipliers == []
        assert trace.filters == []
        assert trace.strategy_candidates == []
        assert trace.ml_adjustment is None
        assert trace.final_action == ""
        assert trace.signal_count == 0


# ── add_signal ──

class TestAddSignal:

    def test_add_signal_from_object(self):
        """[03] add_signal извлекает поля из объекта сигнала."""
        trace = create_trace("SYM")
        sig = SimpleNamespace(
            signal_type=SimpleNamespace(value="wt_signal"),
            direction=SimpleNamespace(value="LONG"),
            strength=75,
            confidence=0.75,
            timeframe="15m",
        )
        trace.add_signal(sig)
        assert len(trace.raw_signals) == 1
        assert trace.raw_signals[0]["type"] == "wt_signal"
        assert trace.raw_signals[0]["direction"] == "LONG"
        assert trace.raw_signals[0]["strength"] == 75

    def test_add_multiple_signals(self):
        """[04] Несколько сигналов добавляются корректно."""
        trace = create_trace("SYM")
        for i in range(3):
            sig = SimpleNamespace(
                signal_type=f"sig_{i}", direction="LONG",
                strength=50 + i * 10, confidence=0.5, timeframe="15m",
            )
            trace.add_signal(sig)
        assert len(trace.raw_signals) == 3

    def test_add_signal_handles_bad_object(self):
        """[05] Некорректный объект не крашит, просто не добавляет."""
        trace = create_trace("SYM")
        trace.add_signal(None)  # не должен крашить
        assert len(trace.raw_signals) == 0


# ── add_mtf_multiplier ──

class TestAddMtfMultiplier:

    def test_add_multiplier(self):
        """[06] add_mtf_multiplier записывает все параметры."""
        trace = create_trace("SYM")
        trace.add_mtf_multiplier(
            signal_type="confluence", direction="SHORT",
            original_strength=70, dir_mult=0.4, zone_mult=0.8,
            combined=0.52, new_strength=36,
        )
        assert len(trace.mtf_multipliers) == 1
        m = trace.mtf_multipliers[0]
        assert m["original_strength"] == 70
        assert m["new_strength"] == 36
        assert m["dir_mult"] == 0.4

    def test_multiple_multipliers(self):
        """[07] Несколько сигналов — несколько записей."""
        trace = create_trace("SYM")
        for i in range(3):
            trace.add_mtf_multiplier(f"sig_{i}", "LONG", 60, 1.3, 1.0, 1.21, 73)
        assert len(trace.mtf_multipliers) == 3


# ── add_filter ──

class TestAddFilter:

    def test_add_filter_passed(self):
        """[08] Фильтр passed=True."""
        trace = create_trace("SYM")
        trace.add_filter("min_signals", True, "3 >= 2")
        assert len(trace.filters) == 1
        assert trace.filters[0]["passed"] is True

    def test_add_filter_blocked(self):
        """[09] Фильтр passed=False с reason."""
        trace = create_trace("SYM")
        trace.add_filter("confidence_gate", False, "0.45 < 0.55 → WATCH")
        assert trace.filters[0]["passed"] is False
        assert "WATCH" in trace.filters[0]["reason"]

    def test_filter_with_details(self):
        """[10] Фильтр с дополнительными деталями."""
        trace = create_trace("SYM")
        trace.add_filter("btc_filter", True, "aligned", mode="shadow")
        assert trace.filters[0]["details"]["mode"] == "shadow"


# ── set_ml_adjustment ──

class TestSetMlAdjustment:

    def test_ml_adjustment(self):
        """[11] set_ml_adjustment записывает 3 значения."""
        trace = create_trace("SYM")
        trace.set_ml_adjustment(0.65, 0.72, 0.671)
        assert trace.ml_adjustment is not None
        assert trace.ml_adjustment["original_confidence"] == 0.65
        assert trace.ml_adjustment["win_prob"] == 0.72
        assert abs(trace.ml_adjustment["blended_confidence"] - 0.671) < 0.001


# ── set_strategy_candidates ──

class TestSetStrategyCandidates:

    def test_set_candidates(self):
        """[12] set_strategy_candidates записывает результаты стратегий."""
        trace = create_trace("SYM")
        rec1 = SimpleNamespace(action="BUY", confidence=0.7, overall_strength=65, direction="LONG")
        rec2 = SimpleNamespace(action="WATCH", confidence=0.4, overall_strength=35, direction="SHORT")
        trace.set_strategy_candidates({"reversal": rec1, "trend": rec2, "empty": None})
        assert len(trace.strategy_candidates) == 2  # None пропущен

    def test_empty_candidates(self):
        """[13] Пустой dict → пустой список."""
        trace = create_trace("SYM")
        trace.set_strategy_candidates({})
        assert trace.strategy_candidates == []


# ── set_final ──

class TestSetFinal:

    def test_set_final(self):
        """[14] set_final записывает финальный результат."""
        trace = create_trace("SYM")
        trace.set_final("BUY", 0.72, 68, "LONG")
        assert trace.final_action == "BUY"
        assert trace.final_confidence == 0.72
        assert trace.final_strength == 68
        assert trace.final_direction == "LONG"


# ── Serialization ──

class TestSerialization:

    def _filled_trace(self) -> DecisionTrace:
        trace = create_trace("BTCUSDT")
        sig = SimpleNamespace(
            signal_type=SimpleNamespace(value="wt_signal"),
            direction=SimpleNamespace(value="LONG"),
            strength=75, confidence=0.75, timeframe="15m",
        )
        trace.add_signal(sig)
        trace.signal_count = 1
        trace.mtf_context = {"direction_bias": "LONG", "price_zone": 0.3}
        trace.add_mtf_multiplier("wt_signal", "LONG", 75, 1.3, 1.1, 1.24, 93)
        trace.set_ml_adjustment(0.75, 0.68, 0.729)
        trace.add_filter("min_signals", True, "1 >= 1")
        trace.add_filter("confidence_gate", True, "0.73 >= 0.55")
        trace.set_final("BUY", 0.729, 93, "LONG")
        trace.strategy_name = "reversal"
        return trace

    def test_to_dict(self):
        """[15] to_dict возвращает полный словарь."""
        trace = self._filled_trace()
        d = trace.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert len(d["raw_signals"]) == 1
        assert len(d["mtf_multipliers"]) == 1
        assert d["ml_adjustment"]["win_prob"] == 0.68
        assert d["final_action"] == "BUY"

    def test_to_json(self):
        """[16] to_json возвращает валидный JSON."""
        trace = self._filled_trace()
        j = trace.to_json()
        parsed = json.loads(j)
        assert parsed["symbol"] == "BTCUSDT"
        assert parsed["strategy_name"] == "reversal"

    def test_to_json_roundtrip(self):
        """[17] JSON → parse → все поля на месте."""
        trace = self._filled_trace()
        parsed = json.loads(trace.to_json())
        assert parsed["final_strength"] == 93
        assert parsed["mtf_context"]["direction_bias"] == "LONG"
        assert len(parsed["filters"]) == 2

    def test_empty_trace_to_json(self):
        """[18] Пустой trace сериализуется без ошибок."""
        trace = create_trace("EMPTY")
        j = trace.to_json()
        parsed = json.loads(j)
        assert parsed["symbol"] == "EMPTY"
        assert parsed["raw_signals"] == []


# ── summary ──

class TestSummary:

    def test_summary_contains_key_info(self):
        """[19] summary содержит ключевую информацию."""
        trace = create_trace("BTCUSDT")
        trace.signal_count = 3
        trace.mtf_context = {"direction_bias": "LONG", "price_zone": 0.3}
        trace.set_final("BUY", 0.72, 68, "LONG")
        trace.strategy_name = "reversal"
        s = trace.summary()
        assert "BTCUSDT" in s
        assert "BUY" in s
        assert "signals=3" in s
        assert "bias=LONG" in s

    def test_summary_shows_blocked_filters(self):
        """[20] summary показывает заблокированные фильтры."""
        trace = create_trace("SYM")
        trace.add_filter("confidence_gate", False, "blocked")
        trace.set_final("WATCH", 0.45, 30, "SHORT")
        s = trace.summary()
        assert "blocked=" in s
        assert "confidence_gate" in s

    def test_summary_shows_ml(self):
        """[21] summary показывает ML adjustment."""
        trace = create_trace("SYM")
        trace.set_ml_adjustment(0.65, 0.72, 0.671)
        trace.set_final("BUY", 0.671, 60, "LONG")
        s = trace.summary()
        assert "ml=" in s

    def test_summary_shows_mtf_adj(self):
        """[22] summary показывает MTF adjustments."""
        trace = create_trace("SYM")
        trace.add_mtf_multiplier("confluence", "SHORT", 70, 0.4, 0.8, 0.52, 36)
        trace.set_final("WATCH", 0.36, 36, "SHORT")
        s = trace.summary()
        assert "mtf_adj=" in s
        assert "70→36" in s
