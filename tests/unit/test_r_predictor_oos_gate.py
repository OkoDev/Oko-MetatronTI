"""Тесты OOS-gate RPredictor (#7 BACKLOG — фикс data-leak).

_evaluate_oos: честная forward-оценка (TimeSeriesSplit) + порог baseline. Модель активируется
ТОЛЬКО если бьёт naive predict-mean на forward-CV. Шум → не проходит; обучаемый сигнал → проходит.
"""
import numpy as np
import pytest

pytest.importorskip("sklearn")
from sklearn.ensemble import GradientBoostingRegressor
from core.ml.r_predictor import _evaluate_oos


def _model():
    return GradientBoostingRegressor(n_estimators=50, max_depth=3, learning_rate=0.05,
                                     subsample=0.8, random_state=42)


class TestOOSGate:
    def test_pure_noise_fails_gate(self):
        # y не зависит от X → модель не должна бить baseline (predict-mean) на forward-CV
        rng = np.random.RandomState(0)
        X = rng.randn(400, 6)
        y = rng.randn(400) * 2.0 + 1.0
        rmse, r2, baseline, passed = _evaluate_oos(_model(), X, y)
        assert passed is False           # шум → НЕ активировать
        assert rmse >= baseline          # хуже/не лучше наивного среднего
        assert r2 < 0.3                  # нет реальной объясняющей силы

    def test_learnable_signal_passes_gate(self):
        # y = устойчивая функция X (стационарная во времени) → модель бьёт baseline
        rng = np.random.RandomState(1)
        X = rng.randn(600, 6)
        y = 3.0 * X[:, 0] - 2.0 * X[:, 1] + 0.5 * X[:, 2] + rng.randn(600) * 0.1
        rmse, r2, baseline, passed = _evaluate_oos(_model(), X, y)
        assert passed is True            # есть сигнал → активировать
        assert rmse < baseline           # бьёт наивный baseline
        assert r2 > 0.5

    def test_returns_four_values(self):
        rng = np.random.RandomState(2)
        X, y = rng.randn(200, 4), rng.randn(200)
        out = _evaluate_oos(_model(), X, y)
        assert len(out) == 4 and isinstance(out[3], bool)
