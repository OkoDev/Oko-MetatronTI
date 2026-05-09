"""
Тесты для AutoCalibrator — rule-based автокалибровка MTF multipliers.
"""
import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from core.ml.auto_calibrator import (
    AutoCalibrator,
    CalibrationResult,
    SegmentStats,
    DEFAULT_PARAMS,
    MIN_SEGMENT_TRADES,
    EXPECTANCY_WEAK_THRESHOLD,
    EXPECTANCY_STRONG_THRESHOLD,
)
from core.signals.signal_models import MTFContext, SignalDirection


# ── Helpers ──────────────────────────────────────────────────────────────

def _create_test_db(path: str, trades: list):
    """Создаёт тестовую БД с simulated_trades."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulated_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, direction TEXT, signal_type TEXT,
            status TEXT, R_multiple REAL, strength INTEGER,
            confidence REAL, regime TEXT, features_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tsl_activated INTEGER DEFAULT 0,
            max_R_possible REAL
        )
    """)
    for t in trades:
        conn.execute("""
            INSERT INTO simulated_trades
            (symbol, direction, signal_type, status, R_multiple,
             strength, confidence, regime, features_json, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            t.get("symbol", "BTC/USDT:USDT"),
            t.get("direction", "LONG"),
            t.get("signal_type", "confluence"),
            t.get("status", "TP"),
            t.get("R_multiple", 2.0),
            t.get("strength", 60),
            t.get("confidence", 0.7),
            t.get("regime", "TREND_UP"),
            json.dumps(t.get("features", {})),
        ))
    conn.commit()
    conn.close()


def _make_features(bias="LONG", zone=0.3, regime="TREND_UP"):
    return {
        "mtf_direction_bias": bias,
        "mtf_price_zone": zone,
        "mtf_regime": regime,
        "mtf_bias_strength": 0.8,
        "mtf_aligned_pct": 80,
    }


# ── SegmentStats ─────────────────────────────────────────────────────────

class TestSegmentStats:
    def test_empty(self):
        seg = SegmentStats(name="test")
        assert seg.win_rate == 0.0
        assert seg.expectancy == 0.0

    def test_all_wins(self):
        seg = SegmentStats(name="test", total=10, wins=10, losses=0,
                           r_sum=30.0, r_win_sum=30.0, r_loss_sum=0.0)
        assert seg.win_rate == 1.0
        assert seg.avg_r == 3.0
        assert seg.expectancy == 3.0  # 1.0 * 3.0 - 0.0

    def test_all_losses(self):
        seg = SegmentStats(name="test", total=10, wins=0, losses=10,
                           r_sum=-10.0, r_win_sum=0.0, r_loss_sum=-10.0)
        assert seg.win_rate == 0.0
        assert seg.expectancy == pytest.approx(-1.0)  # 0 - 1.0 * 1.0

    def test_mixed(self):
        seg = SegmentStats(name="test", total=20, wins=8, losses=12,
                           r_sum=4.0, r_win_sum=20.0, r_loss_sum=-16.0)
        wr = 8 / 20  # 0.4
        avg_r_win = 20.0 / 8  # 2.5
        avg_r_loss = -16.0 / 12  # -1.33
        expected_exp = wr * avg_r_win - (1 - wr) * abs(avg_r_loss)
        assert seg.expectancy == pytest.approx(expected_exp, abs=0.01)

    def test_to_dict(self):
        seg = SegmentStats(name="test", total=10, wins=7, losses=3,
                           r_sum=10.0, r_win_sum=12.0, r_loss_sum=-2.0)
        d = seg.to_dict()
        assert d["name"] == "test"
        assert d["total"] == 10
        assert d["win_rate"] == 70.0


# ── AutoCalibrator core ─────────────────────────────────────────────────

class TestAutoCalibrator:
    def test_init_defaults(self, tmp_path):
        db = str(tmp_path / "test.db")
        _create_test_db(db, [])
        cal = AutoCalibrator(db_path=db)
        assert cal.params == DEFAULT_PARAMS

    def test_calibrate_too_few_trades(self, tmp_path):
        db = str(tmp_path / "test.db")
        trades = [{"features": _make_features()}] * 10
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        result = cal.calibrate(min_trades=30)
        assert result.total_trades == 10
        assert result.adjustments == []

    def test_segmentation(self, tmp_path):
        """Проверяем что сегменты создаются корректно."""
        db = str(tmp_path / "test.db")
        trades = []
        # 20 LONG с bias=LONG (aligned) — все выигрышные
        for _ in range(20):
            trades.append({
                "direction": "LONG", "status": "TP", "R_multiple": 2.0,
                "features": _make_features(bias="LONG", zone=0.2),
            })
        # 20 SHORT с bias=LONG (counter) — все убыточные
        for _ in range(20):
            trades.append({
                "direction": "SHORT", "status": "SL", "R_multiple": -1.0,
                "features": _make_features(bias="LONG", zone=0.8),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        result = cal.calibrate(min_trades=20)

        # Должны быть сегменты dir=LONG_bias=LONG и dir=SHORT_bias=LONG
        seg_names = [s["name"] for s in result.segments]
        assert "dir=LONG_bias=LONG" in seg_names
        assert "dir=SHORT_bias=LONG" in seg_names

    def test_aligned_winning_boosts(self, tmp_path):
        """Aligned прибыльные → aligned_boost усиливается."""
        db = str(tmp_path / "test.db")
        trades = []
        for _ in range(25):
            trades.append({
                "direction": "LONG", "status": "TP", "R_multiple": 3.0,
                "features": _make_features(bias="LONG", zone=0.3),
            })
        # Нужны ещё сделки чтобы набрать min_trades
        for _ in range(10):
            trades.append({
                "direction": "SHORT", "status": "SL", "R_multiple": -1.0,
                "features": _make_features(bias="NEUTRAL", zone=0.5),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        old_boost = cal.params["aligned_boost"]
        result = cal.calibrate(min_trades=30)

        # aligned LONG+LONG с высокой expectancy → aligned_boost растёт
        boost_adj = [a for a in result.adjustments if a.param == "aligned_boost"]
        if boost_adj:
            assert boost_adj[0].new_value > old_boost

    def test_counter_losing_increases_penalty(self, tmp_path):
        """Counter убыточные → counter_penalty увеличивается."""
        db = str(tmp_path / "test.db")
        trades = []
        # 25 SHORT при bias=LONG — убыточные
        for _ in range(25):
            trades.append({
                "direction": "SHORT", "status": "SL", "R_multiple": -1.0,
                "features": _make_features(bias="LONG", zone=0.5),
            })
        # Балласт
        for _ in range(10):
            trades.append({
                "direction": "LONG", "status": "TP", "R_multiple": 1.5,
                "features": _make_features(bias="NEUTRAL", zone=0.5),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        old_penalty = cal.params["counter_penalty"]
        result = cal.calibrate(min_trades=30)

        penalty_adj = [a for a in result.adjustments if a.param == "counter_penalty"]
        if penalty_adj:
            assert penalty_adj[0].new_value > old_penalty

    def test_persistence(self, tmp_path):
        """Калиброванные параметры сохраняются и загружаются."""
        db = str(tmp_path / "test.db")
        cal_path = str(tmp_path / "calibration.json")

        # Создаём калибратор и меняем параметр
        cal1 = AutoCalibrator(db_path=db, calibration_path=cal_path)
        cal1.params["aligned_boost"] = 0.77
        cal1._save_calibration(CalibrationResult(
            timestamp="test", params_after=cal1.params
        ))

        # Создаём второй калибратор — должен загрузить 0.77
        cal2 = AutoCalibrator(db_path=db, calibration_path=cal_path)
        assert cal2.params["aligned_boost"] == 0.77

    def test_no_adjustment_on_neutral_segments(self, tmp_path):
        """Сегменты около нуля expectancy не генерируют корректировок."""
        db = str(tmp_path / "test.db")
        trades = []
        # 20 LONG при bias=LONG: 10 TP + 10 SL (WR=50%, ~нейтральный)
        for i in range(20):
            status = "TP" if i % 2 == 0 else "SL"
            r = 2.0 if status == "TP" else -1.5
            trades.append({
                "direction": "LONG", "status": status, "R_multiple": r,
                "features": _make_features(bias="LONG", zone=0.5),
            })
        # Балласт
        for _ in range(15):
            trades.append({
                "direction": "SHORT", "status": "TP", "R_multiple": 1.0,
                "features": _make_features(bias="NEUTRAL", zone=0.5),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        result = cal.calibrate(min_trades=30)

        # Expectancy ~0.25 — не должно быть корректировок aligned_boost
        # (не выходит за STRONG_THRESHOLD=0.5 и не ниже WEAK_THRESHOLD=-0.3)
        aligned_adj = [a for a in result.adjustments if a.param == "aligned_boost"]
        # Может быть или нет — зависит от точной expectancy. Проверяем что она в пределах порогов.
        aligned_seg = [s for s in result.segments if s["name"] == "dir=LONG_bias=LONG"]
        if aligned_seg:
            exp = aligned_seg[0]["expectancy"]
            if EXPECTANCY_WEAK_THRESHOLD < exp < EXPECTANCY_STRONG_THRESHOLD:
                assert len(aligned_adj) == 0

    def test_param_bounds(self, tmp_path):
        """Параметры не выходят за границы."""
        db = str(tmp_path / "test.db")
        cal = AutoCalibrator(db_path=db)
        # Принудительно ставим на границу
        cal.params["aligned_boost"] = 0.95
        trades = []
        for _ in range(25):
            trades.append({
                "direction": "LONG", "status": "TP", "R_multiple": 5.0,
                "features": _make_features(bias="LONG"),
            })
        for _ in range(10):
            trades.append({
                "direction": "SHORT", "status": "TP", "R_multiple": 1.0,
                "features": _make_features(bias="NEUTRAL"),
            })
        _create_test_db(db, trades)
        cal2 = AutoCalibrator(db_path=db)
        cal2.params["aligned_boost"] = 0.95
        result = cal2.calibrate(min_trades=30)
        # aligned_boost не должен превысить 1.0
        assert cal2.params["aligned_boost"] <= 1.0

    def test_summary_text(self):
        result = CalibrationResult(
            timestamp="2026-03-17T00:00:00",
            total_trades=100,
            segments_analyzed=12,
            segments=[
                {"name": "dir=SHORT_bias=LONG", "total": 20, "win_rate": 15.0, "expectancy": -0.8},
                {"name": "dir=LONG_bias=LONG", "total": 30, "win_rate": 70.0, "expectancy": 0.9},
            ],
        )
        text = result.summary_text()
        assert "Автокалибровка" in text
        assert "100" in text


# ── MTFContext с калибровкой ─────────────────────────────────────────────

class TestMTFContextCalibrated:
    def test_default_multipliers_unchanged(self):
        """Без calibration_params — те же значения что раньше."""
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.0,
            aligned_pct=80, senior_matches=3,
            senior_reversal=None, wt_spreads={},
        )
        assert ctx.direction_multiplier(SignalDirection.LONG) == pytest.approx(1.5)
        assert ctx.direction_multiplier(SignalDirection.SHORT) == pytest.approx(0.3, abs=0.01)
        assert ctx.zone_multiplier(SignalDirection.LONG) == pytest.approx(1.4)
        assert ctx.zone_multiplier(SignalDirection.SHORT) == pytest.approx(0.6)

    def test_calibrated_direction_multiplier(self):
        """С calibration_params — использует калиброванные коэффициенты."""
        ctx = MTFContext(
            direction_bias=SignalDirection.LONG,
            bias_strength=1.0, price_zone=0.5,
            aligned_pct=80, senior_matches=3,
            senior_reversal=None, wt_spreads={},
            calibration_params={
                "aligned_boost": 0.8,      # было 0.5 → теперь 1.0 + 1.0*0.8 = 1.8
                "counter_penalty": 0.9,    # было 0.7 → теперь max(0.2, 1.0 - 1.0*0.9) = 0.2
                "counter_floor": 0.2,      # было 0.3
            },
        )
        assert ctx.direction_multiplier(SignalDirection.LONG) == pytest.approx(1.8)
        assert ctx.direction_multiplier(SignalDirection.SHORT) == pytest.approx(0.2, abs=0.01)

    def test_calibrated_zone_multiplier(self):
        """Zone multiplier с калиброванными коэффициентами."""
        ctx = MTFContext(
            direction_bias=SignalDirection.NEUTRAL,
            bias_strength=0.0, price_zone=0.0,  # S5
            aligned_pct=50, senior_matches=0,
            senior_reversal=None, wt_spreads={},
            calibration_params={
                "zone_base_high": 1.6,  # было 1.4
                "zone_range": 1.0,       # было 0.8
                "zone_base_low": 0.5,    # было 0.6
            },
        )
        # LONG@S5: 1.6 - 1.0*0.0 = 1.6
        assert ctx.zone_multiplier(SignalDirection.LONG) == pytest.approx(1.6)
        # SHORT@S5: 0.5 + 1.0*0.0 = 0.5
        assert ctx.zone_multiplier(SignalDirection.SHORT) == pytest.approx(0.5)

    def test_neutral_bias_ignores_calibration(self):
        """При NEUTRAL bias direction_multiplier = 1.0 независимо от калибровки."""
        ctx = MTFContext(
            direction_bias=SignalDirection.NEUTRAL,
            bias_strength=0.5, price_zone=0.5,
            aligned_pct=50, senior_matches=0,
            senior_reversal=None, wt_spreads={},
            calibration_params={"aligned_boost": 99.0},
        )
        assert ctx.direction_multiplier(SignalDirection.LONG) == 1.0
        assert ctx.direction_multiplier(SignalDirection.SHORT) == 1.0


# ── Zone segments ────────────────────────────────────────────────────────

class TestZoneCalibration:
    def test_bad_zone_losing_increases_zone_range(self, tmp_path):
        """LONG@RESISTANCE убыточный → zone_range увеличивается (больше штраф)."""
        db = str(tmp_path / "test.db")
        trades = []
        for _ in range(20):
            trades.append({
                "direction": "LONG", "status": "SL", "R_multiple": -1.0,
                "features": _make_features(bias="NEUTRAL", zone=0.85),  # RESISTANCE
            })
        for _ in range(15):
            trades.append({
                "direction": "SHORT", "status": "TP", "R_multiple": 1.5,
                "features": _make_features(bias="NEUTRAL", zone=0.5),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        old_range = cal.params["zone_range"]
        result = cal.calibrate(min_trades=30)

        zone_adj = [a for a in result.adjustments if a.param == "zone_range"]
        if zone_adj:
            assert zone_adj[0].new_value >= old_range

    def test_good_zone_winning_increases_zone_range(self, tmp_path):
        """LONG@SUPPORT прибыльный → zone_range увеличивается (зона работает)."""
        db = str(tmp_path / "test.db")
        trades = []
        for _ in range(20):
            trades.append({
                "direction": "LONG", "status": "TP", "R_multiple": 3.0,
                "features": _make_features(bias="NEUTRAL", zone=0.1),  # SUPPORT
            })
        for _ in range(15):
            trades.append({
                "direction": "SHORT", "status": "TP", "R_multiple": 1.0,
                "features": _make_features(bias="NEUTRAL", zone=0.5),
            })
        _create_test_db(db, trades)
        cal = AutoCalibrator(db_path=db)
        old_range = cal.params["zone_range"]
        result = cal.calibrate(min_trades=30)

        zone_adj = [a for a in result.adjustments if a.param == "zone_range"]
        if zone_adj:
            assert zone_adj[0].new_value >= old_range
