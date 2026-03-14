"""
Тесты для RPredictor: Kelly-формулы, feature vector, поведение без обучения.
Обучение модели не тестируется (требует 100+ сделок и sklearn), только пограничные случаи.
"""
import pytest
from core.r_predictor import RPredictor


class TestKellyFraction:
    def test_positive_edge(self):
        # win_rate=0.6, avg_r_win=2.0 → f=(0.6*2 - 0.4)/2 = 0.4
        # max_kelly=1.0 убирает cap, чтобы проверить чистую формулу
        f = RPredictor.kelly_fraction(0.6, 2.0, max_kelly=1.0)
        assert abs(f - 0.4) < 1e-6

    def test_capped_at_max_kelly(self):
        # Очень высокий edge не должен превышать 25%
        f = RPredictor.kelly_fraction(0.9, 5.0, max_kelly=0.25)
        assert f == 0.25

    def test_negative_edge_returns_zero(self):
        # win_rate=0.3, avg_r_win=1.0 → f=(0.3-0.7)/1.0 = -0.4 → clamp 0
        f = RPredictor.kelly_fraction(0.3, 1.0)
        assert f == 0.0

    def test_zero_win_rate_returns_zero(self):
        assert RPredictor.kelly_fraction(0.0, 2.0) == 0.0

    def test_zero_avg_r_returns_zero(self):
        assert RPredictor.kelly_fraction(0.6, 0.0) == 0.0

    def test_breakeven_edge(self):
        # win_rate=0.5, avg_r_win=1.0 → f = (0.5 - 0.5)/1 = 0
        f = RPredictor.kelly_fraction(0.5, 1.0)
        assert f == 0.0

    def test_custom_max_kelly(self):
        f = RPredictor.kelly_fraction(0.8, 3.0, max_kelly=0.10)
        assert f <= 0.10


class TestKellyPositionSize:
    def test_basic(self):
        # deposit=10000, win_rate=0.6, avg_r=2.0 → f=0.4, но cap=0.25 → pos=2500
        pos = RPredictor.kelly_position_size(10000, 0.6, 2.0)
        assert abs(pos - 2500.0) < 1.0

    def test_zero_edge_zero_position(self):
        pos = RPredictor.kelly_position_size(10000, 0.3, 1.0)
        assert pos == 0.0

    def test_capped_at_25pct(self):
        pos = RPredictor.kelly_position_size(10000, 0.95, 10.0)
        assert pos <= 2500.0


class TestBuildFeatureVector:
    def _rp(self):
        return RPredictor()

    def test_returns_list_of_14(self):
        rp = self._rp()
        row = {
            "strength": 70, "confidence": 0.8, "direction": "LONG",
            "signal_type": "wt_signal", "regime": "TREND_UP",
            "features_json": '{"volatility": 3.5, "price_change": 1.2, "distance_to_pivot_pct": 0.5}',
        }
        vec = rp._build_feature_vector(row)
        assert vec is not None
        assert len(vec) == 14

    def test_long_direction_encoding(self):
        rp = self._rp()
        row = {"strength": 60, "confidence": 0.7, "direction": "LONG",
               "signal_type": "trend_signal", "regime": None, "features_json": "{}"}
        vec = rp._build_feature_vector(row)
        # dir_long=vec[2], dir_short=vec[3]
        assert vec[2] == 1.0
        assert vec[3] == 0.0

    def test_short_direction_encoding(self):
        rp = self._rp()
        row = {"strength": 60, "confidence": 0.7, "direction": "SHORT",
               "signal_type": "pivot_reversal", "regime": None, "features_json": "{}"}
        vec = rp._build_feature_vector(row)
        assert vec[2] == 0.0
        assert vec[3] == 1.0

    def test_regime_trend_up_encoding(self):
        rp = self._rp()
        row = {"strength": 60, "confidence": 0.7, "direction": "LONG",
               "signal_type": "wt_signal", "regime": "TREND_UP", "features_json": "{}"}
        vec = rp._build_feature_vector(row)
        # reg_up=vec[10], reg_down=vec[11], reg_range=vec[12], reg_hvol=vec[13]
        assert vec[10] == 1.0
        assert vec[11] == 0.0
        assert vec[12] == 0.0
        assert vec[13] == 0.0

    def test_wt_signal_type_encoding(self):
        rp = self._rp()
        row = {"strength": 50, "confidence": 0.5, "direction": "LONG",
               "signal_type": "wt_signal", "regime": None, "features_json": "{}"}
        vec = rp._build_feature_vector(row)
        # st_pivot=vec[4], st_trend=vec[5], st_wt=vec[6]
        assert vec[4] == 0.0
        assert vec[5] == 0.0
        assert vec[6] == 1.0

    def test_missing_fields_use_defaults(self):
        rp = self._rp()
        vec = rp._build_feature_vector({})
        assert vec is not None
        assert len(vec) == 14
        # strength default = 50
        assert vec[0] == 50.0

    def test_bad_features_json_handled(self):
        rp = self._rp()
        row = {"features_json": "not-json"}
        vec = rp._build_feature_vector(row)
        assert vec is not None  # не падает


class TestUntrainedPredictor:
    def test_predict_returns_none_when_not_trained(self):
        rp = RPredictor()
        result = rp.predict_expected_r({"strength": 70, "confidence": 0.7,
                                        "direction": "LONG", "signal_type": "wt_signal"})
        assert result is None

    def test_info_not_trained(self):
        rp = RPredictor()
        info = rp.info()
        assert info["is_trained"] is False
        assert info["n_samples"] == 0
        assert info["min_samples_needed"] == 75  # снижено с 100 (коммит bddb51b)

    def test_fit_insufficient_data_returns_false(self, tmp_path):
        """Обучение на пустой БД должно вернуть False (недостаточно данных)."""
        import sqlite3 as _sq
        db = str(tmp_path / "empty.db")
        con = _sq.connect(db)
        con.execute("""CREATE TABLE simulated_trades (
            id INTEGER PRIMARY KEY, strength REAL, confidence REAL,
            direction TEXT, signal_type TEXT, regime TEXT,
            max_R_possible REAL, features_json TEXT, status TEXT)""")
        con.commit()
        con.close()

        rp = RPredictor()
        result = rp.fit(db)
        assert result is False
        assert rp.is_trained is False
