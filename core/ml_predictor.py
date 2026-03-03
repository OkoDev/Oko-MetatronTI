"""
Модуль машинного обучения для улучшения торговых прогнозов
Использует различные ML алгоритмы для анализа паттернов и предсказания движения цен
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import joblib
import os

# Попытка импорта ML библиотек
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    from sklearn.neural_network import MLPClassifier
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    # Заглушки для случаев, когда ML библиотеки недоступны
    class RandomForestClassifier:
        def __init__(self, **kwargs): pass
        def fit(self, X, y): return self
        def predict(self, X): return np.zeros(len(X))
        def predict_proba(self, X): return np.ones((len(X), 2)) * 0.5
    
    class GradientBoostingClassifier:
        def __init__(self, **kwargs): pass
        def fit(self, X, y): return self
        def predict(self, X): return np.zeros(len(X))
        def predict_proba(self, X): return np.ones((len(X), 2)) * 0.5
    
    class LogisticRegression:
        def __init__(self, **kwargs): pass
        def fit(self, X, y): return self
        def predict(self, X): return np.zeros(len(X))
        def predict_proba(self, X): return np.ones((len(X), 2)) * 0.5
    
    class StandardScaler:
        def fit(self, X): return self
        def transform(self, X): return X
        def fit_transform(self, X): return X
    
    def train_test_split(X, y, test_size=0.2, random_state=42):
        split_idx = int(len(X) * (1 - test_size))
        return X[:split_idx], X[split_idx:], y[:split_idx], y[split_idx:]
    
    def accuracy_score(y_true, y_pred): return 0.5
    def precision_score(y_true, y_pred, average='weighted'): return 0.5
    def recall_score(y_true, y_pred, average='weighted'): return 0.5
    def f1_score(y_true, y_pred, average='weighted'): return 0.5

logger = logging.getLogger(__name__)

class PredictionType(Enum):
    """Типы предсказаний"""
    PRICE_DIRECTION = "price_direction"  # Направление движения цены
    SIGNAL_STRENGTH = "signal_strength"  # Сила сигнала
    VOLATILITY = "volatility"  # Волатильность
    VOLUME_ANOMALY = "volume_anomaly"  # Аномалии объема

@dataclass
class MLPrediction:
    """Результат ML предсказания"""
    prediction_type: PredictionType
    predicted_value: float
    confidence: float
    features_used: List[str]
    model_name: str
    timestamp: datetime
    metadata: Dict[str, Any] = None

@dataclass
class ModelPerformance:
    """Производительность ML модели"""
    model_name: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    training_samples: int
    last_trained: datetime
    features_importance: Dict[str, float] = None

class MLPredictor:
    """
    Основной класс для машинного обучения в торговой системе
    """
    
    def __init__(self, data_collector, config: Dict = None):
        self.data_collector = data_collector
        self.config = config or {}
        
        # Проверяем доступность ML библиотек
        if not ML_AVAILABLE:
            logger.warning("ML библиотеки недоступны. Используются заглушки.")
        
        # Модели для разных типов предсказаний
        self.models = {
            PredictionType.PRICE_DIRECTION: {
                'random_forest': RandomForestClassifier(n_estimators=100, random_state=42),
                'gradient_boosting': GradientBoostingClassifier(n_estimators=100, random_state=42),
                'logistic_regression': LogisticRegression(random_state=42, max_iter=1000),
                'neural_network': MLPClassifier(hidden_layer_sizes=(100, 50), random_state=42, max_iter=1000)
            },
            PredictionType.SIGNAL_STRENGTH: {
                'random_forest': RandomForestClassifier(n_estimators=100, random_state=42),
                'gradient_boosting': GradientBoostingClassifier(n_estimators=100, random_state=42)
            },
            PredictionType.VOLATILITY: {
                'random_forest': RandomForestClassifier(n_estimators=100, random_state=42),
                'gradient_boosting': GradientBoostingClassifier(n_estimators=100, random_state=42)
            },
            PredictionType.VOLUME_ANOMALY: {
                'random_forest': RandomForestClassifier(n_estimators=100, random_state=42),
                'logistic_regression': LogisticRegression(random_state=42, max_iter=1000)
            }
        }
        
        # Скалеры для нормализации данных
        self.scalers = {
            prediction_type: StandardScaler() 
            for prediction_type in PredictionType
        }
        
        # Производительность моделей
        self.model_performance: Dict[str, ModelPerformance] = {}
        
        # Кэш для предсказаний
        self.prediction_cache: Dict[str, Tuple[datetime, MLPrediction]] = {}
        self.cache_ttl = 300  # 5 минут
        
        # Путь для сохранения моделей
        self.models_dir = self.config.get('models_dir', 'models')
        os.makedirs(self.models_dir, exist_ok=True)
    
    async def predict_price_direction(self, symbol: str, timeframe: str = "1h") -> Optional[MLPrediction]:
        """Предсказывает направление движения цены"""
        try:
            # Проверяем кэш
            cache_key = f"{symbol}_{timeframe}_price_direction"
            cached = self._get_cached_prediction(cache_key)
            if cached:
                return cached
            
            # Получаем данные
            df = await self.data_collector.get_ohlcv(symbol, timeframe, limit=200)
            if df is None or len(df) < 50:
                return None
            
            # Извлекаем признаки
            features = self._extract_price_features(df)
            if not features:
                return None
            
            # Нормализуем признаки
            features_scaled = self.scalers[PredictionType.PRICE_DIRECTION].transform([features])
            
            # Получаем предсказания от всех моделей
            predictions = []
            confidences = []
            
            for model_name, model in self.models[PredictionType.PRICE_DIRECTION].items():
                try:
                    pred = model.predict(features_scaled)[0]
                    proba = model.predict_proba(features_scaled)[0]
                    confidence = max(proba)
                    
                    predictions.append(pred)
                    confidences.append(confidence)
                except Exception as e:
                    logger.warning(f"Ошибка предсказания {model_name}: {e}")
                    continue
            
            if not predictions:
                return None
            
            # Усредняем предсказания
            avg_prediction = np.mean(predictions)
            avg_confidence = np.mean(confidences)
            
            # Определяем направление
            direction = 1 if avg_prediction > 0.5 else 0  # 1 = вверх, 0 = вниз
            
            prediction = MLPrediction(
                prediction_type=PredictionType.PRICE_DIRECTION,
                predicted_value=float(direction),
                confidence=float(avg_confidence),
                features_used=list(features.keys()),
                model_name="ensemble",
                timestamp=datetime.now(),
                metadata={
                    "individual_predictions": predictions,
                    "individual_confidences": confidences,
                    "timeframe": timeframe
                }
            )
            
            # Кэшируем результат
            self._cache_prediction(cache_key, prediction)
            
            return prediction
            
        except Exception as e:
            logger.exception(f"Ошибка предсказания направления цены для {symbol}: {e}")
            return None
    
    async def predict_signal_strength(self, symbol: str, signal_data: Dict[str, Any]) -> Optional[MLPrediction]:
        """Предсказывает силу торгового сигнала"""
        try:
            cache_key = f"{symbol}_signal_strength_{hash(str(signal_data))}"
            cached = self._get_cached_prediction(cache_key)
            if cached:
                return cached
            
            # Извлекаем признаки из данных сигнала
            features = self._extract_signal_features(signal_data)
            if not features:
                return None
            
            # Нормализуем признаки
            features_scaled = self.scalers[PredictionType.SIGNAL_STRENGTH].transform([features])
            
            # Получаем предсказания
            predictions = []
            confidences = []
            
            for model_name, model in self.models[PredictionType.SIGNAL_STRENGTH].items():
                try:
                    pred = model.predict(features_scaled)[0]
                    proba = model.predict_proba(features_scaled)[0]
                    confidence = max(proba)
                    
                    predictions.append(pred)
                    confidences.append(confidence)
                except Exception as e:
                    logger.warning(f"Ошибка предсказания силы сигнала {model_name}: {e}")
                    continue
            
            if not predictions:
                return None
            
            # Усредняем предсказания
            avg_prediction = np.mean(predictions)
            avg_confidence = np.mean(confidences)
            
            prediction = MLPrediction(
                prediction_type=PredictionType.SIGNAL_STRENGTH,
                predicted_value=float(avg_prediction),
                confidence=float(avg_confidence),
                features_used=list(features.keys()),
                model_name="ensemble",
                timestamp=datetime.now(),
                metadata={
                    "signal_data": signal_data,
                    "individual_predictions": predictions
                }
            )
            
            self._cache_prediction(cache_key, prediction)
            return prediction
            
        except Exception as e:
            logger.exception(f"Ошибка предсказания силы сигнала для {symbol}: {e}")
            return None
    
    def _extract_price_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Извлекает признаки для предсказания направления цены"""
        try:
            if len(df) < 20:
                return {}
            
            features = {}
            
            # Технические индикаторы
            features['rsi'] = self._calculate_rsi(df['close'], 14)
            features['macd'] = self._calculate_macd(df['close'])
            features['bb_position'] = self._calculate_bollinger_position(df['close'])
            features['volume_ratio'] = df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
            
            # Ценовые паттерны
            features['price_change_1h'] = (df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2]
            features['price_change_4h'] = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
            features['price_change_24h'] = (df['close'].iloc[-1] - df['close'].iloc[-24]) / df['close'].iloc[-24]
            
            # Волатильность
            features['volatility'] = df['close'].pct_change().rolling(20).std().iloc[-1]
            
            # Объемные индикаторы
            features['volume_trend'] = df['volume'].rolling(5).mean().iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
            
            # Паттерны свечей
            features['doji'] = self._is_doji(df.iloc[-1])
            features['hammer'] = self._is_hammer(df.iloc[-1])
            features['shooting_star'] = self._is_shooting_star(df.iloc[-1])
            
            return features
            
        except Exception as e:
            logger.exception(f"Ошибка извлечения признаков цены: {e}")
            return {}
    
    def _extract_signal_features(self, signal_data: Dict[str, Any]) -> Dict[str, float]:
        """Извлекает признаки из данных сигнала"""
        try:
            features = {}
            
            # Базовые признаки сигнала
            features['strength'] = signal_data.get('strength', 0) / 100.0
            features['confidence'] = signal_data.get('confidence', 0)
            features['age'] = signal_data.get('age', 0) / 3600.0  # В часах
            
            # Контекстные признаки
            features['volume_24h'] = signal_data.get('volume_24h', 0) / 1000000.0
            features['price_change_24h'] = signal_data.get('price_change_24h', 0) / 100.0
            features['volatility'] = signal_data.get('volatility', 0) / 100.0
            
            # Признаки типа сигнала
            signal_type = signal_data.get('signal_type', 'unknown')
            features['is_mtf'] = 1.0 if 'mtf' in signal_type.lower() else 0.0
            features['is_pivot'] = 1.0 if 'pivot' in signal_type.lower() else 0.0
            features['is_divergence'] = 1.0 if 'divergence' in signal_type.lower() else 0.0
            
            return features
            
        except Exception as e:
            logger.exception(f"Ошибка извлечения признаков сигнала: {e}")
            return {}
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Рассчитывает RSI"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1] if not rsi.empty else 50.0
        except:
            return 50.0
    
    def _calculate_macd(self, prices: pd.Series) -> float:
        """Рассчитывает MACD"""
        try:
            ema_12 = prices.ewm(span=12).mean()
            ema_26 = prices.ewm(span=26).mean()
            macd = ema_12 - ema_26
            return macd.iloc[-1] if not macd.empty else 0.0
        except:
            return 0.0
    
    def _calculate_bollinger_position(self, prices: pd.Series) -> float:
        """Рассчитывает позицию цены относительно полос Боллинджера"""
        try:
            sma = prices.rolling(20).mean()
            std = prices.rolling(20).std()
            upper_band = sma + (std * 2)
            lower_band = sma - (std * 2)
            
            current_price = prices.iloc[-1]
            upper = upper_band.iloc[-1]
            lower = lower_band.iloc[-1]
            
            if upper != lower:
                return (current_price - lower) / (upper - lower)
            return 0.5
        except:
            return 0.5
    
    def _is_doji(self, candle: pd.Series) -> float:
        """Проверяет, является ли свеча доджи"""
        try:
            body_size = abs(candle['close'] - candle['open'])
            total_range = candle['high'] - candle['low']
            return 1.0 if body_size < (total_range * 0.1) else 0.0
        except:
            return 0.0
    
    def _is_hammer(self, candle: pd.Series) -> float:
        """Проверяет, является ли свеча молотом"""
        try:
            body_size = abs(candle['close'] - candle['open'])
            lower_shadow = min(candle['open'], candle['close']) - candle['low']
            upper_shadow = candle['high'] - max(candle['open'], candle['close'])
            
            return 1.0 if (lower_shadow > body_size * 2 and upper_shadow < body_size) else 0.0
        except:
            return 0.0
    
    def _is_shooting_star(self, candle: pd.Series) -> float:
        """Проверяет, является ли свеча падающей звездой"""
        try:
            body_size = abs(candle['close'] - candle['open'])
            lower_shadow = min(candle['open'], candle['close']) - candle['low']
            upper_shadow = candle['high'] - max(candle['open'], candle['close'])
            
            return 1.0 if (upper_shadow > body_size * 2 and lower_shadow < body_size) else 0.0
        except:
            return 0.0
    
    def _get_cached_prediction(self, cache_key: str) -> Optional[MLPrediction]:
        """Получает кэшированное предсказание"""
        if cache_key in self.prediction_cache:
            timestamp, prediction = self.prediction_cache[cache_key]
            if (datetime.now() - timestamp).seconds < self.cache_ttl:
                return prediction
            else:
                del self.prediction_cache[cache_key]
        return None
    
    def _cache_prediction(self, cache_key: str, prediction: MLPrediction):
        """Кэширует предсказание"""
        self.prediction_cache[cache_key] = (datetime.now(), prediction)
    
    async def train_models(self, training_data: List[Dict[str, Any]]):
        """Обучает модели на исторических данных"""
        if not ML_AVAILABLE:
            logger.warning("ML библиотеки недоступны. Обучение пропущено.")
            return
        
        try:
            logger.info("Начинаем обучение ML моделей...")
            
            # Подготавливаем данные для каждого типа предсказания
            for prediction_type in PredictionType:
                X, y = self._prepare_training_data(training_data, prediction_type)
                
                if len(X) < 10:  # Минимум 10 образцов для обучения
                    logger.warning(f"Недостаточно данных для обучения {prediction_type.value}")
                    continue
                
                # Разделяем на обучающую и тестовую выборки
                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
                
                # Нормализуем данные
                X_train_scaled = self.scalers[prediction_type].fit_transform(X_train)
                X_test_scaled = self.scalers[prediction_type].transform(X_test)
                
                # Обучаем каждую модель
                for model_name, model in self.models[prediction_type].items():
                    try:
                        # Обучаем модель
                        model.fit(X_train_scaled, y_train)
                        
                        # Тестируем модель
                        y_pred = model.predict(X_test_scaled)
                        
                        # Рассчитываем метрики
                        accuracy = accuracy_score(y_test, y_pred)
                        precision = precision_score(y_test, y_pred, average='weighted', zero_division=0)
                        recall = recall_score(y_test, y_pred, average='weighted', zero_division=0)
                        f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)
                        
                        # Сохраняем производительность
                        perf_key = f"{prediction_type.value}_{model_name}"
                        self.model_performance[perf_key] = ModelPerformance(
                            model_name=model_name,
                            accuracy=accuracy,
                            precision=precision,
                            recall=recall,
                            f1_score=f1,
                            training_samples=len(X_train),
                            last_trained=datetime.now()
                        )
                        
                        logger.info(f"Модель {perf_key} обучена. Точность: {accuracy:.3f}")
                        
                        # Сохраняем модель
                        model_path = os.path.join(self.models_dir, f"{perf_key}.joblib")
                        joblib.dump(model, model_path)
                        
                    except Exception as e:
                        logger.exception(f"Ошибка обучения модели {model_name} для {prediction_type.value}: {e}")
            
            logger.info("Обучение ML моделей завершено")
            
        except Exception as e:
            logger.exception(f"Ошибка обучения моделей: {e}")
    
    def _prepare_training_data(self, training_data: List[Dict[str, Any]], 
                              prediction_type: PredictionType) -> Tuple[List[List[float]], List[float]]:
        """Подготавливает данные для обучения"""
        X = []
        y = []
        
        for data_point in training_data:
            try:
                if prediction_type == PredictionType.PRICE_DIRECTION:
                    features = self._extract_price_features(data_point.get('df', pd.DataFrame()))
                    target = data_point.get('price_direction', 0)  # 0 или 1
                elif prediction_type == PredictionType.SIGNAL_STRENGTH:
                    features = self._extract_signal_features(data_point.get('signal_data', {}))
                    target = data_point.get('signal_strength', 0) / 100.0  # Нормализуем до 0-1
                elif prediction_type == PredictionType.VOLATILITY:
                    features = self._extract_price_features(data_point.get('df', pd.DataFrame()))
                    target = data_point.get('volatility', 0) / 100.0
                elif prediction_type == PredictionType.VOLUME_ANOMALY:
                    features = self._extract_signal_features(data_point.get('signal_data', {}))
                    target = data_point.get('volume_anomaly', 0)  # 0 или 1
                else:
                    continue
                
                if features and target is not None:
                    X.append(list(features.values()))
                    y.append(target)
                    
            except Exception as e:
                logger.warning(f"Ошибка подготовки данных для обучения: {e}")
                continue
        
        return X, y
    
    def get_model_performance(self) -> Dict[str, ModelPerformance]:
        """Возвращает производительность всех моделей"""
        return self.model_performance
    
    def clear_cache(self):
        """Очищает кэш предсказаний"""
        self.prediction_cache.clear()
        logger.info("Кэш ML предсказаний очищен")
