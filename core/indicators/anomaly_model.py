"""
DEV-17: Isolation Forest — ML-based anomaly detector.

Обучается на нормальном поведении пары (последние N баров OHLCV).
Аномалия = отклонение от learned distribution.

Преимущество над rule-based: адаптивные пороги под каждую пару.
Тихий дамп на стейбле с низким volume_ratio=2.5 может быть аномалией,
а pump-&-dump на мем-монете с ratio=4.0 — норма.

Использование:
    am = AnomalyModel()
    am.fit(df)              # обучение на N последних барах
    score = am.score(df)    # -1.0..+1.0 (чем ниже — тем аномальнее)
    strength = am.anomaly_strength(score)   # 0..100
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Минимум баров для обучения
MIN_TRAIN_BARS = 50
# Окно обучения (последние N баров = "нормальное поведение")
DEFAULT_TRAIN_WINDOW = 200
# Contamination: ожидаемая доля аномалий в обучающей выборке
CONTAMINATION = 0.05

try:
    from sklearn.ensemble import IsolationForest
    _IF_OK = True
except ImportError:
    _IF_OK = False
    logger.warning("AnomalyModel: sklearn не установлен — используется rule-based fallback")


def _extract_features(df: pd.DataFrame, window: int = 20) -> Optional[np.ndarray]:
    """Извлекает признаки для Isolation Forest из OHLCV DataFrame.

    Признаки (все нормализованы, масштаб-инвариантны):
      0: volume_zscore        — (vol - mean) / std за window баров
      1: price_change_pct     — % изменение close
      2: price_volatility     — rolling std доходностей за window
      3: high_low_spread_pct  — (high - low) / close * 100 (внутрибаровая волатильность)
      4: volume_ma_ratio      — volume / rolling_mean (аналог volume_ratio)
    """
    if df is None or len(df) < window + 2:
        return None
    try:
        close = df["close"].values.astype(float)
        vol   = df["volume"].values.astype(float)
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)

        # returns: процентные изменения цены
        returns = np.diff(close) / close[:-1] * 100
        # выровняем длину (первый элемент = 0)
        returns = np.concatenate([[0.0], returns])

        # volume z-score (rolling window)
        vol_mean = pd.Series(vol).rolling(window).mean().values
        vol_std  = pd.Series(vol).rolling(window).std().values
        vol_std  = np.where(vol_std < 1e-10, 1e-10, vol_std)
        vol_zscore = (vol - vol_mean) / vol_std

        # price volatility (rolling std of returns)
        price_vol = pd.Series(returns).rolling(window).std().values

        # high-low spread %
        hl_spread = (high - low) / np.where(close < 1e-10, 1e-10, close) * 100

        # volume MA ratio (safe: заменяем нули в знаменателе до деления,
        # иначе np.where всё равно вычисляет vol/vol_mean → RuntimeWarning)
        safe_vol_mean = np.where(vol_mean < 1e-10, 1.0, vol_mean)
        vol_ma = np.where(vol_mean < 1e-10, 1.0, vol / safe_vol_mean)

        # Собираем матрицу признаков
        features = np.column_stack([
            np.nan_to_num(vol_zscore, nan=0.0, posinf=5.0, neginf=-5.0),
            np.nan_to_num(returns,    nan=0.0, posinf=10.0, neginf=-10.0),
            np.nan_to_num(price_vol,  nan=0.0, posinf=5.0),
            np.nan_to_num(hl_spread,  nan=0.0, posinf=10.0),
            np.nan_to_num(vol_ma,     nan=1.0, posinf=10.0),
        ])
        return features
    except Exception as e:
        logger.debug("AnomalyModel._extract_features: %s", e)
        return None


class AnomalyModel:
    """Per-pair Isolation Forest anomaly detector.

    Обучается на последних DEFAULT_TRAIN_WINDOW барах OHLCV.
    Не требует внешних меток — обучение самонаблюдаемое.
    Легковесен: n_estimators=50, обучение < 10 мс.
    """

    def __init__(self, train_window: int = DEFAULT_TRAIN_WINDOW,
                 contamination: float = CONTAMINATION):
        self.train_window = train_window
        self.contamination = contamination
        self._model: Optional["IsolationForest"] = None
        self._trained = False
        self._feature_window = 20  # окно для z-score / volatility

    # ------------------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> bool:
        """Обучает модель на последних train_window барах.

        Returns True если обучение успешно.
        """
        if not _IF_OK:
            return False
        train_df = df.tail(self.train_window) if len(df) > self.train_window else df
        features = _extract_features(train_df, window=self._feature_window)
        if features is None or len(features) < MIN_TRAIN_BARS:
            return False
        # Убираем строки с NaN (первые ~window баров из rolling)
        valid_mask = ~np.isnan(features).any(axis=1)
        features = features[valid_mask]
        if len(features) < MIN_TRAIN_BARS:
            return False
        try:
            model = IsolationForest(
                n_estimators=50,
                contamination=self.contamination,
                random_state=42,
                n_jobs=1,
            )
            model.fit(features)
            self._model = model
            self._trained = True
            return True
        except Exception as e:
            logger.debug("AnomalyModel.fit: %s", e)
            return False

    def score(self, df: pd.DataFrame) -> Optional[float]:
        """Возвращает anomaly score для последнего бара.

        Score range: -1.0 (очень аномально) .. +0.5 (норма).
        Threshold обычно ~-0.0 (decision_function).

        Returns None если модель не обучена или ошибка.
        """
        if not self._trained or self._model is None:
            return None
        features = _extract_features(df, window=self._feature_window)
        if features is None or len(features) == 0:
            return None
        try:
            last_row = features[[-1]]  # последний бар
            score = float(self._model.decision_function(last_row)[0])
            return score
        except Exception as e:
            logger.debug("AnomalyModel.score: %s", e)
            return None

    def is_anomaly(self, df: pd.DataFrame) -> bool:
        """True если последний бар является аномалией по IF."""
        if not self._trained or self._model is None:
            return False
        features = _extract_features(df, window=self._feature_window)
        if features is None:
            return False
        try:
            pred = self._model.predict(features[[-1]])[0]
            return pred == -1  # IsolationForest: -1 = аномалия
        except Exception:
            return False

    def anomaly_strength(self, score: float, base_strength: int = 50) -> int:
        """Конвертирует IF score в strength 0–100.

        Более отрицательный score → выше strength.
        Нормальные бары (score > -0.1) → strength < 30 → не триггерят min_strength=50.
        """
        # score range примерно [-0.5 .. +0.3]
        # Нормализуем: score=-0.3 → ~80, score=-0.1 → ~40, score=0 → ~20
        normalized = max(0.0, -score)  # [-score] = [0 .. +0.5]
        strength = int(normalized * 200)  # 0.5 * 200 = 100
        strength = max(0, min(100, strength))
        return strength

    @property
    def is_trained(self) -> bool:
        return self._trained
