"""
OutcomePredictor — ML-модель, обученная на реальных исходах симулированных сделок.

Читает закрытые записи из simulated_trades (TP=win, SL=loss),
обучает RandomForest и возвращает P(win) для новых сигналов.

Использование:
    op = OutcomePredictor()
    op.fit("subscriptions.db")            # обучить / переобучить
    p = op.predict_win_prob("pivot_reversal", "LONG", 70, 0.75, {}, "TREND_UP")
    # → 0.61  (61% вероятность TP)
"""
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Минимум закрытых сделок для обучения
MIN_TRADES = 30

# ARCH-21: скользящее окно — по умолчанию None (вся история)
DEFAULT_TRAINING_WINDOW = None

# Маппинг signal_type → one-hot позиция (DEV-13: реальные типы из БД)
# anomaly=34, confluence=1301, mtf_alert=137, mtf_bias=5,
# pivot_reversal=445, trend_signal=45, wt_signal=476
_SIG_ORDER = ["pivot_reversal", "trend_signal", "wt_signal",
              "confluence", "anomaly", "mtf_alert", "mtf_bias"]

# Маппинг режима → one-hot позиция
_REGIME_ORDER = ["TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOL"]

# Имя файла для сохранения модели
_MODEL_FILE = "outcome_model.pkl"

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False
    logger.warning("OutcomePredictor: sklearn не установлен — predict_win_prob вернёт None")


def _build_feature_vector(
    signal_type: str,
    direction: str,
    strength: float,
    confidence: float,
    features_dict: Dict[str, Any],
    regime: Optional[str],
) -> List[float]:
    """Строит вектор из 16 признаков."""
    # 1-2: strength, confidence
    v = [
        min(max((strength or 50.0) / 100.0, 0.0), 1.0),
        min(max(confidence or 0.5, 0.0), 1.0),
    ]
    # 3: direction one-hot (LONG=1, SHORT=0)
    v.append(1.0 if str(direction).upper() == "LONG" else 0.0)
    # 4-6: signal_type one-hot
    v += [1.0 if signal_type == s else 0.0 for s in _SIG_ORDER]
    # 7: volatility (normalized)
    vol = features_dict.get("volatility") or 0.0
    v.append(min(float(vol) / 100.0, 3.0))
    # 8: price_change_24h (normalized)
    pc = features_dict.get("price_change_24h") or 0.0
    v.append(min(max(float(pc) / 10.0, -3.0), 3.0))
    # 9-12: regime one-hot
    v += [1.0 if (regime or "") == r else 0.0 for r in _REGIME_ORDER]
    return v


class OutcomePredictor:
    """
    Предсказывает вероятность TP (выигрыша) для сигнала на основе
    исторических исходов из simulated_trades.
    """

    def __init__(self):
        self._model = None
        self._trained = False
        self._n_features = 16
        self._n_samples = 0
        self._cv_score: Optional[float] = None
        # DEV-12 (8.4.7): Confidence Calibrator
        try:
            from core.intelligence.confidence_calibrator import ConfidenceCalibrator
            self._calibrator: Optional[object] = ConfidenceCalibrator()
        except Exception:
            self._calibrator = None

    # ------------------------------------------------------------------
    def fit(self, db_path: str = "subscriptions.db", training_window: Optional[int] = None) -> bool:
        """
        Обучает модель на закрытых сделках (status IN ('TP','SL')).

        training_window — ARCH-21: если задан, берём только последние N записей
        (скользящее окно). Позволяет адаптироваться к смене рынка без накопления
        старого bias. Рекомендуется N=500-1000 при наличии 1000+ чистых записей.

        Returns True если обучение прошло успешно, False иначе.
        """
        if not _SKLEARN_OK:
            return False
        try:
            rows = self._load_closed_trades(db_path)

            # ARCH-21: скользящее окно — берём только последние N записей
            if training_window and len(rows) > training_window:
                logger.info(
                    "OutcomePredictor: sliding window %d → %d (из %d)",
                    len(rows), training_window, len(rows),
                )
                rows = rows[-training_window:]

            if len(rows) < MIN_TRADES:
                logger.info(
                    "OutcomePredictor: недостаточно данных (%d/%d) — пропуск обучения",
                    len(rows), MIN_TRADES,
                )
                return False

            X, y = [], []
            for r in rows:
                try:
                    fj = json.loads(r["features_json"] or "{}")
                    fv = _build_feature_vector(
                        r["signal_type"] or "",
                        r["direction"] or "",
                        r["strength"] or 50.0,
                        r["confidence"] or 0.5,
                        fj,
                        r["regime"],
                    )
                    X.append(fv)
                    y.append(1 if r["status"] in ("TP", "TSL") else 0)
                except Exception as row_err:
                    logger.debug("OutcomePredictor: пропуск строки — %s", row_err)
                    continue

            if len(X) < MIN_TRADES:
                logger.info("OutcomePredictor: после фильтрации %d строк — пропуск", len(X))
                return False

            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=6,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            )
            # Кросс-валидация для оценки качества
            try:
                scores = cross_val_score(model, X, y, cv=min(5, len(X) // 10), scoring="roc_auc")
                self._cv_score = float(scores.mean())
            except Exception:
                self._cv_score = None

            model.fit(X, y)
            self._model = model
            self._trained = True
            self._n_samples = len(X)

            # Сохраняем рядом с БД
            model_path = os.path.join(os.path.dirname(db_path) or ".", _MODEL_FILE)
            try:
                import joblib
                joblib.dump(model, model_path)
            except Exception:
                pass  # joblib может отсутствовать — не критично

            win_rate = sum(y) / len(y) * 100
            logger.info(
                "OutcomePredictor: обучено на %d сделках | win_rate=%.1f%% | CV AUC=%s",
                len(X),
                win_rate,
                f"{self._cv_score:.3f}" if self._cv_score else "n/a",
            )

            # DEV-12 (8.4.7): обучаем калибратор вместе с основной моделью
            if self._calibrator is not None:
                try:
                    self._calibrator.fit(db_path)
                except Exception as cal_err:
                    logger.debug("ConfidenceCalibrator.fit: %s", cal_err)

            return True

        except Exception as e:
            logger.exception("OutcomePredictor.fit: %s", e)
            return False

    # ------------------------------------------------------------------
    def predict_win_prob(
        self,
        signal_type: str,
        direction: str,
        strength: float,
        confidence: float,
        features_dict: Dict[str, Any],
        regime: Optional[str],
    ) -> Optional[float]:
        """
        Возвращает P(TP) — вероятность выигрыша (0.0–1.0).
        Возвращает None если модель не обучена или sklearn недоступен.
        """
        if not self._trained or self._model is None:
            return None
        try:
            fv = _build_feature_vector(
                signal_type, direction, strength, confidence, features_dict, regime
            )
            proba = self._model.predict_proba([fv])[0]
            # proba[1] — вероятность класса 1 (TP)
            return float(proba[1])
        except Exception as e:
            logger.debug("OutcomePredictor.predict_win_prob: %s", e)
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _load_closed_trades(db_path: str) -> List[Dict]:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT signal_type, direction, strength, confidence,
                       regime, status, features_json
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND signal_type IS NOT NULL
                  AND direction IS NOT NULL
            """)
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    def calibrate_confidence(self, raw_confidence: float) -> float:
        """DEV-12 (8.4.7): Возвращает откалиброванный confidence.

        Если калибратор не обучен — возвращает raw_confidence без изменений.
        """
        if self._calibrator is None or not getattr(self._calibrator, "is_fitted", False):
            return raw_confidence
        try:
            return self._calibrator.calibrate(raw_confidence)
        except Exception:
            return raw_confidence

    # ------------------------------------------------------------------
    @property
    def is_trained(self) -> bool:
        return self._trained

    def info(self) -> Dict:
        cal_info = {}
        if self._calibrator is not None:
            try:
                cal_info = self._calibrator.info()
            except Exception:
                pass
        return {
            "trained": self._trained,
            "n_samples": self._n_samples,
            "cv_auc": self._cv_score,
            "calibrator": cal_info,
        }
