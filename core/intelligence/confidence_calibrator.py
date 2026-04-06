"""
DEV-12 (Этап 8.4.7): Confidence Calibrator — калибровка уверенности по реальным исходам.

Строит reliability curve: predicted confidence vs actual win rate.
Применяет isotonic regression для маппинга nominal confidence → calibrated probability.

Использование:
    cal = ConfidenceCalibrator()
    cal.fit("subscriptions.db")
    p = cal.calibrate(0.72)         # → реальная вероятность TP
    curve = cal.reliability_curve() # → для дашборда

Зачем нужно:
    Если бот говорит confidence=0.75 а реальный WR=55% — бот переоценивает уверенность.
    Калибратор исправляет это смещение.
    ECE (Expected Calibration Error) < 0.05 — хорошо откалиброван.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Минимум закрытых сделок для обучения калибратора
MIN_SAMPLES = 20
# Минимум в бине для включения в reliability curve
MIN_BIN_SAMPLES = 5

try:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False


class ConfidenceCalibrator:
    """
    Калибрует nominal confidence → true win probability.

    Методы:
      - "isotonic" (default): isotonic regression — монотонная, без предположений
      - "platt": logistic regression — сглаженная, требует линейной зависимости
      - fallback (без sklearn): bin-based линейная интерполяция
    """

    def __init__(self, method: str = "isotonic"):
        self._method = method
        self._model = None
        self._fitted = False
        self._n_samples = 0
        self._bins: List[Dict] = []
        self._ece: Optional[float] = None

    # ── Public API ────────────────────────────────────────────────────────

    def fit(self, db_path: str = "subscriptions.db") -> bool:
        """Обучает калибратор на закрытых сделках из БД."""
        try:
            rows = self._load_trades(db_path)
            if len(rows) < MIN_SAMPLES:
                logger.info(
                    "ConfidenceCalibrator: мало данных (%d/%d) — пропуск",
                    len(rows), MIN_SAMPLES,
                )
                return False

            confs = [float(r["confidence"]) for r in rows if r["confidence"] is not None]
            labels = [
                1 if r["status"] in ("TP", "TSL") else 0
                for r in rows if r["confidence"] is not None
            ]

            if len(confs) < MIN_SAMPLES:
                return False

            # Fit
            if _SKLEARN_OK and self._method == "isotonic":
                model = IsotonicRegression(out_of_bounds="clip")
                model.fit(confs, labels)
                self._model = model
            elif _SKLEARN_OK and self._method == "platt":
                import numpy as np
                model = LogisticRegression(max_iter=1000)
                model.fit(np.array(confs).reshape(-1, 1), labels)
                self._model = model
            else:
                # Fallback без sklearn
                self._model = self._fit_bin_dict(confs, labels)

            self._fitted = True
            self._n_samples = len(confs)
            self._bins = self._compute_reliability_curve(confs, labels)
            self._ece = self._compute_ece(confs, labels)

            actual_wr = sum(labels) / len(labels) * 100
            logger.info(
                "ConfidenceCalibrator: обучено на %d сделках | WR=%.1f%% | ECE=%.3f | метод=%s",
                self._n_samples, actual_wr, self._ece or 0, self._method,
            )
            return True

        except Exception as e:
            logger.exception("ConfidenceCalibrator.fit: %s", e)
            return False

    def calibrate(self, raw_confidence: float) -> float:
        """
        Возвращает откалиброванную вероятность TP.
        Если не обучен — возвращает raw_confidence без изменений.
        """
        if not self._fitted or self._model is None:
            return raw_confidence

        try:
            c = min(max(float(raw_confidence), 0.0), 1.0)

            if _SKLEARN_OK and self._method == "isotonic":
                return float(self._model.predict([c])[0])

            elif _SKLEARN_OK and self._method == "platt":
                import numpy as np
                proba = self._model.predict_proba(np.array([[c]]))[0]
                return float(proba[1])

            else:
                return self._interpolate_bin_dict(c)

        except Exception as e:
            logger.debug("ConfidenceCalibrator.calibrate: %s", e)
            return raw_confidence

    def reliability_curve(self) -> List[Dict]:
        """
        Reliability curve по бинам — для отображения на дашборде.

        Каждый элемент:
            bin_lo, bin_hi   — границы бина
            mean_conf        — средний confidence в бине
            actual_wr        — реальный win rate
            n                — кол-во сделок
            gap              — actual_wr - mean_conf (>0 = недооценка, <0 = переоценка)
        """
        return self._bins

    def calibration_error(self) -> Optional[float]:
        """ECE (Expected Calibration Error). Ниже = лучше."""
        return self._ece

    def summary_text(self) -> str:
        """Краткий текст для TG/лога."""
        if not self._fitted:
            return "ConfidenceCalibrator: не обучен"
        lines = [
            f"📊 <b>Confidence Calibration</b>",
            f"Сделок: {self._n_samples} | ECE: {self._ece:.3f}",
            "",
        ]
        # Топ-3 перекоса
        sorted_bins = sorted(self._bins, key=lambda b: abs(b["gap"]), reverse=True)
        for b in sorted_bins[:3]:
            direction = "переоценка" if b["gap"] < 0 else "недооценка"
            lines.append(
                f"  conf {b['bin_lo']:.0%}–{b['bin_hi']:.0%}: "
                f"WR={b['actual_wr']:.0%} ({direction} {abs(b['gap']):.0%})"
            )
        return "\n".join(lines)

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def info(self) -> Dict:
        return {
            "fitted": self._fitted,
            "method": self._method,
            "n_samples": self._n_samples,
            "ece": self._ece,
            "bins": len(self._bins),
        }

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_trades(db_path: str) -> List[Dict]:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("""
                SELECT confidence, status
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND confidence IS NOT NULL
            """)
            return [dict(r) for r in cur.fetchall()]

    def _compute_reliability_curve(
        self,
        confs: List[float],
        labels: List[int],
        n_bins: int = 10,
    ) -> List[Dict]:
        step = 1.0 / n_bins
        result = []
        for i in range(n_bins):
            lo, hi = i * step, (i + 1) * step
            pairs = [(c, l) for c, l in zip(confs, labels) if lo <= c < hi]
            if len(pairs) < MIN_BIN_SAMPLES:
                continue
            mean_conf = sum(c for c, _ in pairs) / len(pairs)
            actual_wr = sum(l for _, l in pairs) / len(pairs)
            result.append({
                "bin_lo": round(lo, 2),
                "bin_hi": round(hi, 2),
                "mean_conf": round(mean_conf, 3),
                "actual_wr": round(actual_wr, 3),
                "n": len(pairs),
                "gap": round(actual_wr - mean_conf, 3),
            })
        return result

    def _compute_ece(self, confs: List[float], labels: List[int], n_bins: int = 10) -> float:
        n = len(confs)
        if n == 0:
            return 0.0
        step = 1.0 / n_bins
        ece = 0.0
        for i in range(n_bins):
            lo, hi = i * step, (i + 1) * step
            pairs = [(c, l) for c, l in zip(confs, labels) if lo <= c < hi]
            if not pairs:
                continue
            acc = sum(l for _, l in pairs) / len(pairs)
            conf_mean = sum(c for c, _ in pairs) / len(pairs)
            ece += (len(pairs) / n) * abs(acc - conf_mean)
        return round(ece, 4)

    def _fit_bin_dict(self, confs: List[float], labels: List[int]) -> Dict[float, float]:
        """Fallback без sklearn: dict mean_conf → actual_wr."""
        curve = self._compute_reliability_curve(confs, labels, n_bins=10)
        return {b["mean_conf"]: b["actual_wr"] for b in curve}

    def _interpolate_bin_dict(self, c: float) -> float:
        if not isinstance(self._model, dict) or not self._model:
            return c
        keys = sorted(self._model.keys())
        if c <= keys[0]:
            return self._model[keys[0]]
        if c >= keys[-1]:
            return self._model[keys[-1]]
        for i in range(len(keys) - 1):
            if keys[i] <= c <= keys[i + 1]:
                t = (c - keys[i]) / (keys[i + 1] - keys[i])
                return self._model[keys[i]] + t * (self._model[keys[i + 1]] - self._model[keys[i]])
        return c
