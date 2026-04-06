"""
MTF WT Specialist — DEV-138 / ARCH-68 Фаза 2.

RandomForest на WaveTrend-снимках 7 таймфреймов.
Предсказывает вероятность TP (win) и возвращает WTVerdict.

Shadow mode: результат пишется в recommendation.metadata["wt_verdict"].
Не влияет на strength/action пока нет 200+ сделок с wt_snap.

Источник данных: features_json["wt_snap"] — пишется trade_simulator-ом.
Если wt_snap отсутствует в записи → строка пропускается при обучении.
"""
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_TRADES = 50  # минимум записей для обучения

# 7 таймфреймов по спеке ARCH-68
_TFS = ["1d", "4h", "1h", "45m", "15m", "5m", "3m"]
_N_FEATURES = len(_TFS) * 5  # 35

_MODEL_FILE = "wt_specialist_model.pkl"

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False
    logger.warning("MTFWTSpecialist: sklearn не установлен — predict вернёт None")


@dataclass
class WTVerdict:
    label: str        # "TREND_CONTINUATION" | "REVERSAL_SETUP" | "EXHAUSTION" | "UNCLEAR"
    confidence: float  # 0.0–1.0 (proba от модели)


def _build_wt_features(wt_snap: Dict[str, Any]) -> Optional[List[float]]:
    """
    Строит вектор из 35 признаков (7 TF × 5).

    Per TF:
      wt1       (float, нормализован /100)
      wt2       (float, нормализован /100)
      zone      (-1=OS / 0=Normal / 1=OB)
      wt_cross  (-1=медвежий / 0=нет / 1=бычий)
      atr_trend (1=UP / -1=DOWN / 0=unknown)

    Возвращает None если wt_snap пуст или не содержит ни одного TF.
    """
    v: List[float] = []
    has_data = False
    for tf in _TFS:
        snap = wt_snap.get(tf) or {}
        wt1 = float(snap.get("wt1", 0.0))
        wt2 = float(snap.get("wt2", 0.0))
        if wt1 != 0.0 or wt2 != 0.0:
            has_data = True
        v.append(wt1 / 100.0)
        v.append(wt2 / 100.0)
        zone = 1 if wt1 > 60 else (-1 if wt1 < -60 else 0)
        v.append(float(zone))
        v.append(float(snap.get("wt_cross", 0) or 0))
        # atr_trend: поддерживаем оба формата — числовой и строковый "UP"/"DOWN"
        raw_trend = snap.get("atr_trend") or snap.get("trend") or 0
        if isinstance(raw_trend, str):
            raw_trend = 1 if raw_trend == "UP" else (-1 if raw_trend == "DOWN" else 0)
        v.append(float(raw_trend))
    if not has_data:
        return None
    return v


def _label_from_proba(p_win: float, wt_snap: Dict[str, Any]) -> str:
    """
    Определяет категориальный label из вероятности и WT-снимка.

    Логика:
      p_win > 0.65  → TREND_CONTINUATION (рынок продолжит тренд)
      p_win < 0.35  → EXHAUSTION         (истощение, стоп ожидать разворота)
      WT 4h/1h в экстремуме + p_win > 0.55 → REVERSAL_SETUP
      иначе         → UNCLEAR
    """
    # Проверяем экстремум на 4h/1h
    wt1_4h = float((wt_snap.get("4h") or {}).get("wt1", 0.0))
    wt1_1h = float((wt_snap.get("1h") or {}).get("wt1", 0.0))
    extreme = abs(wt1_4h) > 60 or abs(wt1_1h) > 60

    if extreme and 0.55 <= p_win <= 0.80:
        return "REVERSAL_SETUP"
    if p_win > 0.65:
        return "TREND_CONTINUATION"
    if p_win < 0.35:
        return "EXHAUSTION"
    return "UNCLEAR"


class MTFWTSpecialist:
    """
    WaveTrend Specialist: RandomForest на 35 признаках (7 TF × 5).

    Использование:
        spec = MTFWTSpecialist()
        spec.fit("subscriptions.db")
        verdict = spec.predict(wt_snap_dict)
        # → WTVerdict(label="REVERSAL_SETUP", confidence=0.62)
    """

    def __init__(self) -> None:
        self._model = None
        self._trained = False
        self._n_samples = 0
        self._cv_score: Optional[float] = None

    # ------------------------------------------------------------------
    def fit(self, db_path: str = "subscriptions.db") -> bool:
        """
        Обучает модель на закрытых сделках с непустым wt_snap.
        Возвращает True если обучение прошло успешно.
        """
        if not _SKLEARN_OK:
            return False
        try:
            rows = self._load_closed_trades(db_path)
            X, y = [], []
            for r in rows:
                try:
                    fj = json.loads(r.get("features_json") or "{}")
                    wt_snap = fj.get("wt_snap")
                    if not wt_snap:
                        continue
                    fv = _build_wt_features(wt_snap)
                    if fv is None:
                        continue
                    X.append(fv)
                    y.append(1 if r["status"] in ("TP", "TSL") else 0)
                except Exception as row_err:
                    logger.debug("MTFWTSpecialist: пропуск строки — %s", row_err)
                    continue

            if len(X) < MIN_TRADES:
                logger.info(
                    "MTFWTSpecialist: недостаточно данных с wt_snap (%d/%d) — пропуск",
                    len(X), MIN_TRADES,
                )
                return False

            # Проверяем что есть оба класса
            if len(set(y)) < 2:
                logger.warning("MTFWTSpecialist: в y только 1 класс — пропуск обучения")
                return False

            model = RandomForestClassifier(
                n_estimators=200,
                max_depth=5,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            )
            try:
                scores = cross_val_score(
                    model, X, y, cv=min(5, len(X) // 10), scoring="roc_auc",
                )
                self._cv_score = float(scores.mean())
            except Exception:
                self._cv_score = None

            model.fit(X, y)
            self._model = model
            self._trained = True
            self._n_samples = len(X)

            model_path = os.path.join(os.path.dirname(db_path) or ".", _MODEL_FILE)
            try:
                import joblib
                joblib.dump(model, model_path)
            except Exception:
                pass

            win_rate = sum(y) / len(y) * 100
            logger.info(
                "MTFWTSpecialist: обучено на %d сделках | win_rate=%.1f%% | CV AUC=%s",
                len(X), win_rate,
                f"{self._cv_score:.3f}" if self._cv_score else "n/a",
            )
            return True

        except Exception as e:
            logger.exception("MTFWTSpecialist.fit: %s", e)
            return False

    # ------------------------------------------------------------------
    def predict(self, wt_snap: Dict[str, Any]) -> Optional[WTVerdict]:
        """
        Возвращает WTVerdict или None если модель не обучена / нет данных.

        wt_snap — dict вида {"4h": {"wt1": -72, "wt2": -68, ...}, ...}
        """
        if not self._trained or self._model is None:
            return None
        if not wt_snap:
            return None
        try:
            fv = _build_wt_features(wt_snap)
            if fv is None:
                return None
            proba = self._model.predict_proba([fv])[0]
            p_win = float(proba[1])
            label = _label_from_proba(p_win, wt_snap)
            return WTVerdict(label=label, confidence=p_win)
        except Exception as e:
            logger.debug("MTFWTSpecialist.predict: %s", e)
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _load_closed_trades(db_path: str) -> List[Dict]:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT status, features_json
                FROM simulated_trades
                WHERE status IN ('TP', 'SL', 'TSL')
                  AND features_json IS NOT NULL
                  AND features_json != '{}'
            """)
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    @property
    def is_trained(self) -> bool:
        return self._trained

    def info(self) -> Dict:
        return {
            "trained": self._trained,
            "n_samples": self._n_samples,
            "cv_auc": self._cv_score,
            "n_features": _N_FEATURES,
        }
