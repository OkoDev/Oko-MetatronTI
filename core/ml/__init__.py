"""
ML Layer — машинное обучение на торговых данных.

Модули:
  ml_predictor      — OHLCV-based ML (PRICE_DIRECTION, SIGNAL_STRENGTH)
  outcome_predictor — RandomForest на исходах сделок, P(win)
  r_predictor       — предсказание R-multiple
  rl_exit_agent     — RL-агент для управления выходом из позиции
  auto_calibrator   — автокалибровка порогов по статистике

Использование:
  from core.ml import OutcomePredictor
  from core.ml.outcome_predictor import OutcomePredictor
"""
from core.ml.outcome_predictor import OutcomePredictor
from core.ml.ml_predictor import MLPredictor

__all__ = ["OutcomePredictor", "MLPredictor"]
