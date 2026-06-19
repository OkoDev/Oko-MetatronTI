"""
R-Predictor — предсказывает max_R_possible для входящей сделки.
Использует GradientBoostingRegressor, обученный на реальных исходах.

Требования:
  - минимум 100 закрытых сделок с max_R_possible IS NOT NULL
  - те же 12 признаков что у OutcomePredictor + distance_to_pivot_pct

Этап 7: Kelly-sizing
  kelly_f = (win_rate * avg_r_win - (1 - win_rate)) / avg_r_win
  position_size = deposit * min(kelly_f, 0.25)
"""
import logging
import sqlite3
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MIN_SAMPLES = 75  # минимум сделок для обучения (84 есть → активируем)

try:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score, TimeSeriesSplit
    import numpy as np
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False
    GradientBoostingRegressor = None
    TimeSeriesSplit = None
    np = None


def _evaluate_oos(model, X, y, n_splits: int = 5):
    """Честная forward-оценка + OOS-gate (#7 BACKLOG, фикс data-leak).

    TimeSeriesSplit (train=прошлое, test=будущее) вместо KFold (мешал прошлое/будущее = leak).
    Возвращает (ts_rmse, ts_r2, baseline_rmse, passed). passed=True ТОЛЬКО если модель бьёт
    наивный baseline (predict train-mean) на forward-фолдах — иначе модель = шум, не активируем.
    Данные ДОЛЖНЫ быть упорядочены по времени (ORDER BY id в _load_dataset).
    """
    tss = TimeSeriesSplit(n_splits=n_splits)
    rmse = float((-cross_val_score(model, X, y, cv=tss,
                                   scoring="neg_root_mean_squared_error")).mean())
    r2 = float(cross_val_score(model, X, y, cv=tss, scoring="r2").mean())
    base_errs = [float(np.sqrt(np.mean((y[te] - y[tr].mean()) ** 2)))
                 for tr, te in tss.split(y)]
    baseline_rmse = float(np.mean(base_errs))
    return rmse, r2, baseline_rmse, (rmse < baseline_rmse)


class RPredictor:
    """
    Предсказывает ожидаемый R (max_R_possible) для новой сделки.
    """

    def __init__(self):
        self.model: Optional[Any] = None
        self.is_trained = False
        self._n_samples = 0
        self._cv_rmse: Optional[float] = None        # честный TimeSeriesSplit RMSE
        self._cv_r2: Optional[float] = None
        self._baseline_rmse: Optional[float] = None  # naive predict-mean (порог OOS-gate)
        self._oos_passed: Optional[bool] = None

    # ------------------------------------------------------------------
    # Обучение
    # ------------------------------------------------------------------

    def fit(self, db_path: str) -> bool:
        """Обучает модель на закрытых сделках. Возвращает True при успехе."""
        if not _SKLEARN_OK:
            logger.warning("RPredictor: scikit-learn недоступен")
            return False
        try:
            X, y = self._load_dataset(db_path)
            if X is None or len(y) < MIN_SAMPLES:
                logger.info(
                    "RPredictor: недостаточно данных (%d < %d), пропускаю",
                    len(y) if y is not None else 0, MIN_SAMPLES
                )
                return False

            model = GradientBoostingRegressor(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                random_state=42,
            )
            # #7: честная forward-оценка (TimeSeriesSplit) + OOS-gate. Старый cv=5 (KFold)
            # мешал прошлое/будущее → оптимистичный leak. Аудит: на TS R²<0, модель проигрывала
            # naive baseline → активировать НЕЛЬЗЯ (predict_expected_r был бы шумом).
            ts_rmse, ts_r2, baseline_rmse, passed = _evaluate_oos(model, X, y)
            self._cv_rmse = ts_rmse
            self._cv_r2 = ts_r2
            self._baseline_rmse = baseline_rmse
            self._oos_passed = passed
            self._n_samples = len(y)
            if not passed:
                # OOS-GATE: модель не бьёт baseline на forward-CV → НЕ деплоим (честность > видимость)
                self.model = None
                self.is_trained = False
                logger.warning(
                    "RPredictor: НЕ активирован — не обобщает (TimeSeriesSplit RMSE=%.3f >= "
                    "baseline=%.3f, R²=%.3f, n=%d). predict_expected_r вернёт None.",
                    ts_rmse, baseline_rmse, ts_r2, self._n_samples,
                )
                return False
            model.fit(X, y)
            self.model = model
            self.is_trained = True
            logger.info(
                "RPredictor: активирован (бьёт baseline) n=%d TS RMSE=%.3f baseline=%.3f R²=%.3f",
                self._n_samples, ts_rmse, baseline_rmse, ts_r2,
            )
            return True
        except Exception:
            logger.exception("RPredictor.fit: ошибка обучения")
            return False

    def _load_dataset(self, db_path: str):
        """Загружает и готовит обучающую выборку."""
        if not _SKLEARN_OK:
            return None, []
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT strength, confidence, direction, signal_type, regime,
                           max_R_possible, features_json
                    FROM simulated_trades
                    WHERE status != 'OPEN'
                      AND max_R_possible IS NOT NULL
                      AND max_R_possible > 0
                    ORDER BY id ASC
                """).fetchall()

            if not rows:
                return None, []

            X, y = [], []
            for row in rows:
                feat = self._build_feature_vector(dict(row))
                if feat is not None:
                    X.append(feat)
                    y.append(float(row["max_R_possible"]))

            return np.array(X, dtype=float), np.array(y, dtype=float)
        except Exception:
            logger.exception("RPredictor._load_dataset: ошибка")
            return None, []

    def _build_feature_vector(self, row: dict):
        """12 базовых + 1 дополнительный признак (distance_to_pivot_pct)."""
        try:
            import json

            strength = float(row.get("strength") or 50)
            confidence = float(row.get("confidence") or 0.5)

            direction = str(row.get("direction") or "NEUTRAL").upper()
            dir_long = 1.0 if direction == "LONG" else 0.0
            dir_short = 1.0 if direction == "SHORT" else 0.0

            st = str(row.get("signal_type") or "").lower()
            st_pivot = 1.0 if "pivot" in st else 0.0
            st_trend = 1.0 if "trend" in st else 0.0
            st_wt = 1.0 if "wt" in st else 0.0

            # Из features_json
            features_raw = row.get("features_json") or "{}"
            try:
                feats = json.loads(features_raw)
            except Exception:
                feats = {}
            volatility = float(feats.get("volatility") or 5.0)
            price_change = float(feats.get("price_change") or 0.0)
            distance_to_pivot_pct = float(feats.get("distance_to_pivot_pct") or 0.0)

            regime = str(row.get("regime") or "").upper()
            reg_up = 1.0 if regime == "TREND_UP" else 0.0
            reg_down = 1.0 if regime == "TREND_DOWN" else 0.0
            reg_range = 1.0 if regime == "RANGE" else 0.0
            reg_hvol = 1.0 if regime == "HIGH_VOL" else 0.0

            return [
                strength, confidence,
                dir_long, dir_short,
                st_pivot, st_trend, st_wt,
                volatility, price_change,
                distance_to_pivot_pct,
                reg_up, reg_down, reg_range, reg_hvol,
            ]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Предсказание
    # ------------------------------------------------------------------

    def predict_expected_r(self, features: dict) -> Optional[float]:
        """
        Предсказывает ожидаемый max_R_possible.
        features — тот же dict что передаётся в _build_feature_vector.
        """
        if not self.is_trained or self.model is None:
            return None
        try:
            vec = self._build_feature_vector(features)
            if vec is None:
                return None
            pred = float(self.model.predict([vec])[0])
            return max(pred, 0.0)
        except Exception:
            logger.exception("RPredictor.predict_expected_r: ошибка")
            return None

    # ------------------------------------------------------------------
    # Kelly-sizing (Этап 7)
    # ------------------------------------------------------------------

    @staticmethod
    def kelly_fraction(win_rate: float, avg_r_win: float, max_kelly: float = 0.25) -> float:
        """
        Формула Kelly: f = (win_rate * avg_r_win - loss_rate) / avg_r_win
        Ограничена max_kelly (по умолчанию 25%) для защиты от чрезмерного риска.
        """
        if avg_r_win <= 0 or win_rate <= 0:
            return 0.0
        loss_rate = 1.0 - win_rate
        f = (win_rate * avg_r_win - loss_rate) / avg_r_win
        return max(0.0, min(f, max_kelly))

    @staticmethod
    def kelly_position_size(deposit: float, win_rate: float, avg_r_win: float) -> float:
        """Position (USDT) = deposit * kelly_f"""
        f = RPredictor.kelly_fraction(win_rate, avg_r_win)
        return deposit * f

    # ------------------------------------------------------------------
    # Диагностика
    # ------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {
            "is_trained": self.is_trained,
            "n_samples": self._n_samples,
            "cv_rmse": self._cv_rmse,            # честный TimeSeriesSplit
            "cv_r2": self._cv_r2,
            "baseline_rmse": self._baseline_rmse,
            "oos_passed": self._oos_passed,      # прошёл ли OOS-gate (бьёт baseline)
            "min_samples_needed": MIN_SAMPLES,
            "sklearn_available": _SKLEARN_OK,
        }
