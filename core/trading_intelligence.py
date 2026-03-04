"""
Trading Intelligence Layer - система объединения и анализа сигналов
Объединяет все типы сигналов в комплексные торговые рекомендации
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np

# Модели данных
from core.signal_models import (
    SignalType, SignalDirection, SignalStrength,
    SignalData, MarketContext, TradingRecommendation,
)

# Проверки сигналов
from core.signal_checkers import (
    check_anomaly_signals, check_wt_signals, check_mtf_signals,
    check_trend_signals, check_divergence_signals, check_pivot_signals,
)

# Форматтер рекомендаций
from core.intelligence_formatter import format_intelligence_message  # noqa: F401 — re-export

try:
    from core.indicators import calculate_trend, calculate_wt, get_zone, detect_fvg
except ImportError:
    def calculate_trend(df, atr_period=43, factor=1.0):
        df = df.copy(); df["trend"] = 1; return df

    def calculate_wt(df, n1=10, n2=21):
        df = df.copy(); df["wt1"] = 0; df["wt2"] = 0; return df

    def get_zone(wt_value):
        return "OS" if wt_value < -50 else ("OB" if wt_value > 50 else "N")

    def detect_fvg(df):
        return "NONE", 0

# Импорт ML модуля
try:
    from core.ml_predictor import MLPredictor, MLPrediction, PredictionType
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    MLPredictor = None
    MLPrediction = None
    PredictionType = None

# Импорт исторического анализатора
try:
    from core.historical_analyzer import HistoricalAnalyzer, HistoricalSignal, SignalOutcome, PerformanceMetrics
    HISTORICAL_AVAILABLE = True
except ImportError:
    HISTORICAL_AVAILABLE = False
    HistoricalAnalyzer = None
    HistoricalSignal = None
    SignalOutcome = None
    PerformanceMetrics = None

# Импорт риск-менеджера
try:
    from core.risk_manager import RiskManager, RiskProfile, PositionRisk, RiskLevel, PositionSize
    RISK_MANAGER_AVAILABLE = True
except ImportError:
    RISK_MANAGER_AVAILABLE = False
    RiskManager = None
    RiskProfile = None
    PositionRisk = None
    RiskLevel = None
    PositionSize = None

logger = logging.getLogger(__name__)

class TradingIntelligence:
    """
    Основной класс для анализа и объединения торговых сигналов
    """
    
    # Маппинг строки из simulated_trades → SignalType enum для адаптивных весов
    _SIGNAL_TYPE_MAP = {
        "pivot_reversal": None,  # заполняется после объявления класса
        "trend_signal":   None,
        "wt_signal":      None,
        "anomaly":        None,
        "divergence":     None,
        "mtf_signal":     None,
    }

    def __init__(self, data_collector, config: Dict = None, db_path: str = "subscriptions.db"):
        self.data_collector = data_collector
        self.config = config or {}
        self._db_path = db_path

        # Динамические веса для разных типов сигналов (адаптируются к эффективности)
        self.signal_weights = {
            SignalType.MTF_SIGNAL: 0.25,
            SignalType.MTF_ALERT: 0.30,
            SignalType.PIVOT_REVERSAL: 0.20,
            SignalType.DIVERGENCE: 0.15,
            SignalType.WT_SIGNAL: 0.10,
            SignalType.TREND_SIGNAL: 0.10,
            SignalType.ANOMALY: 0.05,
            SignalType.PIVOT_ALERT: 0.15
        }
        # Исходные веса сохраняем отдельно — чтобы не накапливать корректировки
        self._base_signal_weights = dict(self.signal_weights)
        
        # Адаптивные пороги для принятия решений
        self.thresholds = {
            "min_signals": 2,  # Минимум сигналов для рекомендации
            "min_strength": 40,  # Минимальная сила сигнала
            "min_confidence": 0.6,  # Минимальная уверенность
            "conflict_threshold": 0.3,  # Порог конфликтующих сигналов
            "volume_threshold": 100000,  # Минимальный объем для анализа (снижен с 1M)
            "volatility_threshold": 50.0  # Максимальная волатильность (увеличен с 20)
        }
        
        # История сигналов для анализа
        self.signal_history: Dict[str, List[SignalData]] = {}
        self.recommendation_history: Dict[str, List[TradingRecommendation]] = {}
        
        # Статистика эффективности сигналов
        self.signal_performance: Dict[SignalType, Dict[str, float]] = {}
        self._initialize_performance_tracking()
        
        # Кэш для оптимизации
        self.analysis_cache: Dict[str, Tuple[datetime, TradingRecommendation]] = {}
        self.cache_ttl = 300  # 5 минут
        
        # ML модуль для улучшения предсказаний
        self.ml_predictor = None
        if ML_AVAILABLE:
            try:
                self.ml_predictor = MLPredictor(data_collector, config)
                logger.info("ML модуль инициализирован")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать ML модуль: {e}")
                self.ml_predictor = None
        else:
            logger.warning("ML модуль недоступен")
        
        # Исторический анализатор для отслеживания эффективности
        self.historical_analyzer = None
        if HISTORICAL_AVAILABLE:
            try:
                self.historical_analyzer = HistoricalAnalyzer()
                logger.info("Исторический анализатор инициализирован")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать исторический анализатор: {e}")
                self.historical_analyzer = None
        else:
            logger.warning("Исторический анализатор недоступен")
        
        # Риск-менеджер для управления рисками
        self.risk_manager = None
        if RISK_MANAGER_AVAILABLE:
            try:
                self.risk_manager = RiskManager(config)
                logger.info("Риск-менеджер инициализирован")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать риск-менеджер: {e}")
                self.risk_manager = None
        else:
            logger.warning("Риск-менеджер недоступен")

        # OutcomePredictor — ML на реальных исходах симулированных сделок
        self.outcome_predictor = None
        try:
            from core.outcome_predictor import OutcomePredictor
            op = OutcomePredictor()
            op.fit(db_path)
            self.outcome_predictor = op
            logger.info("OutcomePredictor: %s", op.info())
        except Exception as e:
            logger.warning("OutcomePredictor не инициализирован: %s", e)

        # Адаптивные веса из реальной статистики (синхронно, sqlite3)
        self.update_signal_weights()

    def update_signal_weights(self, db_path: str = None) -> None:
        """
        Обновляет self.signal_weights на основе avg_R по типам сигналов из simulated_trades.
        Вызывается при старте и после переобучения.
        Минимум 20 закрытых сделок на тип — иначе вес не меняется.
        """
        _MIN_TRADES = 20
        db = db_path or self._db_path
        # Заполняем маппинг здесь, после объявления SignalType
        _map = {
            "pivot_reversal": SignalType.PIVOT_REVERSAL,
            "trend_signal":   SignalType.TREND_SIGNAL,
            "wt_signal":      SignalType.WT_SIGNAL,
            "anomaly":        SignalType.ANOMALY,
            "divergence":     SignalType.DIVERGENCE,
            "mtf_signal":     SignalType.MTF_SIGNAL,
        }
        try:
            from core.performance_engine import PerformanceEngine
            rows = PerformanceEngine(db).by_signal_type()
            changed = []
            for row in rows:
                st = _map.get(row["signal_type"])
                if st is None:
                    continue
                closed = (row["wins"] or 0) + (row["losses"] or 0)
                if closed < _MIN_TRADES:
                    continue
                avg_r = row["avg_r"] or 0.0
                # factor: avg_r=0 → 1.0, +1R → 1.4, -1R → 0.6, clamped [0.5, 2.0]
                factor = max(0.5, min(2.0, 1.0 + avg_r * 0.4))
                base = self._base_signal_weights.get(st, 0.1)
                new_w = round(base * factor, 4)
                old_w = self.signal_weights.get(st, base)
                self.signal_weights[st] = new_w
                if abs(new_w - old_w) > 0.001:
                    changed.append(
                        f"{row['signal_type']}: {old_w:.3f}→{new_w:.3f} "
                        f"(avg_R={avg_r:.2f}, n={closed})"
                    )
            if changed:
                logger.info("Adaptive weights updated: %s", " | ".join(changed))
            else:
                logger.debug("Adaptive weights: нет изменений (мало данных или изменения незначительны)")
        except Exception as e:
            logger.warning("update_signal_weights: %s", e)

    def _initialize_performance_tracking(self):
        """Инициализирует отслеживание производительности сигналов"""
        for signal_type in SignalType:
            self.signal_performance[signal_type] = {
                "total_signals": 0,
                "successful_signals": 0,
                "accuracy": 0.0,
                "avg_strength": 0.0,
                "avg_confidence": 0.0,
                "last_updated": datetime.now()
            }
    
    def _update_signal_performance(self, signal: SignalData, success: bool):
        """Обновляет статистику производительности сигнала"""
        perf = self.signal_performance[signal.signal_type]
        perf["total_signals"] += 1
        if success:
            perf["successful_signals"] += 1
        
        # Пересчитываем точность
        perf["accuracy"] = perf["successful_signals"] / perf["total_signals"] if perf["total_signals"] > 0 else 0.0
        
        # Обновляем средние значения
        perf["avg_strength"] = (perf["avg_strength"] * (perf["total_signals"] - 1) + signal.strength) / perf["total_signals"]
        perf["avg_confidence"] = (perf["avg_confidence"] * (perf["total_signals"] - 1) + signal.confidence) / perf["total_signals"]
        perf["last_updated"] = datetime.now()
    
    def _get_cached_analysis(self, symbol: str) -> Optional[TradingRecommendation]:
        """Получает кэшированный анализ если он еще актуален"""
        if symbol in self.analysis_cache:
            timestamp, recommendation = self.analysis_cache[symbol]
            if (datetime.now() - timestamp).seconds < self.cache_ttl:
                return recommendation
            else:
                del self.analysis_cache[symbol]
        return None
    
    def _cache_analysis(self, symbol: str, recommendation: TradingRecommendation):
        """Кэширует результат анализа"""
        self.analysis_cache[symbol] = (datetime.now(), recommendation)
        
    async def analyze_symbol(self, symbol: str) -> Optional[TradingRecommendation]:
        """
        Комплексный анализ символа и генерация рекомендации
        """
        import asyncio
        start_time = datetime.now()
        
        try:
            # Проверяем кэш
            cached_result = self._get_cached_analysis(symbol)
            if cached_result:
                logger.debug(f"Используем кэшированный анализ для {symbol}")
                return cached_result
            
            # Добавляем таймаут для всего анализа (30 секунд)
            try:
                # Собираем все доступные сигналы с таймаутом
                signals = await asyncio.wait_for(
                    self._collect_all_signals(symbol),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при сборе сигналов для {symbol}")
                return None
            
            if not signals:
                logger.warning(f"Не найдено сигналов для {symbol}")
                return None
            
            # Фильтруем сигналы по качеству
            filtered_signals = self._filter_signals_by_quality(signals)
            
            # Снижаем требования для популярных пар
            min_signals = self.thresholds["min_signals"]
            top_pairs = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'DOT', 'MATIC', 'AVAX']
            symbol_base = symbol.split('/')[0] if '/' in symbol else symbol.replace('USDT', '').replace(':USDT', '')
            if symbol_base in top_pairs:
                min_signals = 1  # Для топ-пар достаточно 1 сигнала
            
            if len(filtered_signals) < min_signals:
                logger.warning(f"Недостаточно качественных сигналов для {symbol}: {len(filtered_signals)} < {min_signals}")
                # Для топ-пар все равно продолжаем анализ
                if symbol_base not in top_pairs:
                    return None
                
            # Получаем контекст рынка с таймаутом
            try:
                market_context = await asyncio.wait_for(
                    self._get_market_context(symbol),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при получении контекста для {symbol}")
                return None
            
            # Проверяем минимальные требования к рынку
            if not self._validate_market_context(market_context):
                logger.warning(f"Рыночный контекст не подходит для анализа {symbol} (объем: {market_context.volume_24h}, цена: {market_context.current_price})")
                # Для топ-пар все равно продолжаем, даже если контекст не идеален
                if symbol_base not in top_pairs:
                    return None
            
            # Анализируем сигналы с учетом производительности
            analysis = self._analyze_signals_advanced(filtered_signals, market_context)
            
            # Улучшаем анализ с помощью ML (с таймаутом)
            if self.ml_predictor:
                try:
                    analysis = await asyncio.wait_for(
                        self._enhance_analysis_with_ml(symbol, analysis, market_context),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут ML анализа для {symbol}, продолжаем без ML")
                except Exception as e:
                    logger.warning(f"Ошибка ML анализа для {symbol}: {e}, продолжаем без ML")
            
            # Генерируем рекомендацию
            recommendation = self._generate_recommendation(
                symbol, filtered_signals, analysis, market_context
            )
            
            # Улучшаем рекомендацию риск-менеджментом
            try:
                recommendation = self.enhance_with_risk_management(recommendation)
            except Exception as e:
                logger.warning(f"Ошибка риск-менеджмента для {symbol}: {e}, продолжаем без него")
            
            # Кэшируем результат
            self._cache_analysis(symbol, recommendation)
            
            # Сохраняем в историю
            if symbol not in self.recommendation_history:
                self.recommendation_history[symbol] = []
            self.recommendation_history[symbol].append(recommendation)
            
            # Обновляем статистику сигналов
            self._update_signal_statistics(filtered_signals, recommendation)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Анализ {symbol} завершен за {elapsed:.2f} секунд")
            
            return recommendation
            
        except asyncio.TimeoutError:
            logger.error(f"Общий таймаут анализа для {symbol}")
            return None
        except Exception as e:
            logger.exception(f"Ошибка анализа {symbol}: {e}")
            return None
    
    async def _collect_all_signals(self, symbol: str) -> List[SignalData]:
        """Собирает все доступные сигналы для символа"""
        signals = []
        try:
            df_1h = await self.data_collector.get_ohlcv(symbol, "1h", limit=100)
            df_15m = await self.data_collector.get_ohlcv(symbol, "15m", limit=100)
            df_3m = await self.data_collector.get_ohlcv(symbol, "3m", limit=100)

            if df_1h is None or df_1h.empty:
                return signals

            signals.extend(await check_anomaly_signals(symbol, df_1h))
            signals.extend(await check_wt_signals(symbol, df_15m))
            signals.extend(await check_mtf_signals(symbol, df_1h, df_15m, df_3m))
            signals.extend(await check_trend_signals(symbol, df_1h))
            signals.extend(await check_divergence_signals(symbol, df_1h))
            signals.extend(await check_pivot_signals(symbol, df_1h))
        except Exception as e:
            logger.exception(f"Ошибка сбора сигналов для {symbol}: {e}")
        return signals
    
    def _filter_signals_by_quality(self, signals: List[SignalData]) -> List[SignalData]:
        """
        Оставляет сигналы по актуальности. Слабые/низкоуверенные не отбрасываются —
        их вклад учитывается весом (quality_score) при агрегации.
        """
        filtered = []
        max_age_seconds = 3600  # 1 час
        for signal in signals:
            if (datetime.now() - signal.timestamp).total_seconds() < max_age_seconds:
                filtered.append(signal)
        return filtered
    
    def _validate_market_context(self, market_context: MarketContext) -> bool:
        """Проверяет, подходит ли рыночный контекст для анализа"""
        # Проверяем, что цена не равна нулю (критично)
        if market_context.current_price <= 0:
            logger.warning(f"Нулевая цена для {market_context.symbol}")
            return False
        
        # Проверяем минимальный объем (снижаем порог для популярных пар)
        volume_threshold = self.thresholds["volume_threshold"]
        # Для BTC, ETH, BNB и других топ-пар снижаем порог
        top_pairs = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'DOT', 'MATIC', 'AVAX']
        symbol_base = market_context.symbol.split('/')[0] if '/' in market_context.symbol else market_context.symbol.replace('USDT', '')
        if symbol_base in top_pairs:
            volume_threshold = volume_threshold / 10  # Снижаем порог в 10 раз для топ-пар
        
        if market_context.volume_24h < volume_threshold:
            logger.debug(f"Низкий объем для {market_context.symbol}: {market_context.volume_24h} < {volume_threshold}")
            # Не блокируем анализ, только предупреждаем
            # return False
        
        # Проверяем максимальную волатильность (только предупреждение, не блокируем)
        if (market_context.volatility and 
            market_context.volatility > self.thresholds["volatility_threshold"]):
            logger.debug(f"Высокая волатильность для {market_context.symbol}: {market_context.volatility}")
            # Не блокируем анализ из-за волатильности
        
        return True
    
    def _analyze_signals_advanced(self, signals: List[SignalData], 
                                 market_context: MarketContext) -> Dict[str, Any]:
        """Продвинутый анализ сигналов с учетом исторической производительности"""
        
        if not signals:
            return {"strength": 0, "confidence": 0, "direction": SignalDirection.NEUTRAL}
        
        # Группируем сигналы по направлению
        long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
        short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]
        
        # Рассчитываем взвешенную силу с учетом исторической производительности
        long_strength = self._calculate_adaptive_weighted_strength(long_signals)
        short_strength = self._calculate_adaptive_weighted_strength(short_signals)
        
        # Модель конфликта: если разница между long и short мала — считаем рынок конфликтным
        total_strength = long_strength + short_strength
        conflict_threshold = self.thresholds.get("conflict_threshold", 0.3)
        dominant = max(long_strength, short_strength)
        conflict_ratio = (abs(long_strength - short_strength) / dominant) if dominant > 0 else 1.0

        if long_strength > short_strength:
            direction = SignalDirection.LONG
            strength = long_strength
            supporting_signals = long_signals
            conflicting_signals = short_signals
        elif short_strength > long_strength:
            direction = SignalDirection.SHORT
            strength = short_strength
            supporting_signals = short_signals
            conflicting_signals = long_signals
        else:
            direction = SignalDirection.NEUTRAL
            strength = max(long_strength, short_strength)
            supporting_signals = []
            conflicting_signals = signals

        # При конфликте (разница < порога) — NEUTRAL и снижаем уверенность
        if dominant > 0 and conflict_ratio < conflict_threshold:
            direction = SignalDirection.NEUTRAL
            supporting_signals = []
            conflicting_signals = signals

        # Уверенность: по поддерживающим сигналам + штраф за конфликт (не по всем подряд)
        confidence = self._calculate_advanced_confidence(
            supporting_signals, conflicting_signals, market_context
        )
        if dominant > 0 and conflict_ratio < conflict_threshold:
            confidence *= 0.6
        
        return {
            "strength": strength,
            "confidence": confidence,
            "direction": direction,
            "supporting_signals": supporting_signals,
            "conflicting_signals": conflicting_signals,
            "total_signals": len(signals)
        }
    
    def _calculate_adaptive_weighted_strength(self, signals: List[SignalData]) -> int:
        """
        Взвешенная сила: вклад сигнала = weight по quality_score (strength * confidence).
        Слабые сигналы учитываются, но с меньшим весом. Адаптивность по accuracy отключена,
        пока нет реального outcome tracking (successful_signals).
        """
        if not signals:
            return 0

        total_weighted_strength = 0.0
        total_weight = 0.0

        for signal in signals:
            base_weight = self.signal_weights.get(signal.signal_type, 0.1)
            # Вес по качеству: слабые/низкоуверенные вносят меньший вклад, но не нулевой
            quality = (signal.strength / 100.0) * signal.confidence
            effective_weight = base_weight * max(quality, 0.05)
            total_weighted_strength += signal.strength * effective_weight
            total_weight += effective_weight

        if total_weight <= 0:
            return 0
        return min(int(round(total_weighted_strength / total_weight)), 100)
    
    def _calculate_advanced_confidence(self, supporting_signals: List[SignalData],
                                     conflicting_signals: List[SignalData],
                                     market_context: MarketContext) -> float:
        """
        Уверенность по поддерживающим сигналам и штраф за конфликт.
        Не усредняем по всем (long+short) — иначе при 2 LONG 0.9 и 2 SHORT 0.9 получали бы 0.9.
        """
        total = len(supporting_signals) + len(conflicting_signals)
        if total == 0:
            return 0.5
        # База только по поддерживающему направлению
        if supporting_signals:
            signal_confidence = float(np.mean([s.confidence for s in supporting_signals]))
        else:
            signal_confidence = 0.5
        # Штраф за долю конфликтующих
        conflict_penalty = len(conflicting_signals) / total
        signal_confidence *= (1.0 - 0.5 * conflict_penalty)

        context_factor = 1.0
        if market_context.volume_24h > 0:
            volume_factor = min(market_context.volume_24h / 1000000, 2.0)
            context_factor *= (0.8 + 0.2 * volume_factor)
        if market_context.volatility and market_context.volatility > 10:
            context_factor *= 0.9
        if abs(market_context.price_change_24h) > 5:
            context_factor *= 1.1
        signal_count_factor = min(total / 5.0, 1.5)
        context_factor *= signal_count_factor

        return min(signal_confidence * context_factor, 1.0)
    
    async def _enhance_analysis_with_ml(self, symbol: str, analysis: Dict[str, Any], 
                                       market_context: MarketContext) -> Dict[str, Any]:
        """Улучшает анализ с помощью машинного обучения"""
        try:
            if not self.ml_predictor:
                return analysis
            
            # Получаем ML предсказания
            ml_predictions = []
            
            # Предсказание направления цены
            price_prediction = await self.ml_predictor.predict_price_direction(symbol)
            if price_prediction:
                ml_predictions.append(price_prediction)
            
            # Предсказание силы сигналов
            for signal in analysis.get("supporting_signals", []):
                signal_data = {
                    "strength": signal.strength,
                    "confidence": signal.confidence,
                    "signal_type": signal.signal_type.value,
                    "age": (datetime.now() - signal.timestamp).total_seconds(),
                    "volume_24h": market_context.volume_24h,
                    "price_change_24h": market_context.price_change_24h,
                    "volatility": market_context.volatility or 0
                }
                
                strength_prediction = await self.ml_predictor.predict_signal_strength(symbol, signal_data)
                if strength_prediction:
                    ml_predictions.append(strength_prediction)
            
            # Корректируем анализ на основе ML предсказаний
            if ml_predictions:
                analysis = self._apply_ml_corrections(analysis, ml_predictions, market_context)

            # OutcomePredictor: блендинг P(win) в confidence
            if self.outcome_predictor and analysis.get("direction") != SignalDirection.NEUTRAL:
                try:
                    supporting = analysis.get("supporting_signals", [])
                    first_sig = supporting[0] if supporting else None
                    sig_type = first_sig.signal_type.value if first_sig else "composite"
                    direction_str = analysis["direction"].value if hasattr(analysis["direction"], "value") else str(analysis["direction"])
                    features_dict = {
                        "volatility": market_context.volatility or 0,
                        "price_change_24h": market_context.price_change_24h or 0,
                    }
                    win_prob = self.outcome_predictor.predict_win_prob(
                        signal_type=sig_type,
                        direction=direction_str,
                        strength=analysis.get("strength", 50),
                        confidence=analysis.get("confidence", 0.5),
                        features_dict=features_dict,
                        regime=None,  # режим появится после регистрации сделки
                    )
                    if win_prob is not None:
                        orig = analysis.get("confidence", 0.5)
                        analysis["confidence"] = round(orig * 0.7 + win_prob * 0.3, 4)
                        logger.debug(
                            "OutcomePredictor: P(win)=%.2f conf %.3f→%.3f",
                            win_prob, orig, analysis["confidence"],
                        )
                except Exception as op_err:
                    logger.debug("OutcomePredictor blend: %s", op_err)

            return analysis

        except Exception as e:
            logger.exception(f"Ошибка ML улучшения анализа для {symbol}: {e}")
            return analysis
    
    def _apply_ml_corrections(self, analysis: Dict[str, Any], 
                             ml_predictions: List[MLPrediction], 
                             market_context: MarketContext) -> Dict[str, Any]:
        """Применяет ML корректировки к анализу"""
        try:
            # Корректируем силу на основе ML предсказаний
            ml_strength_adjustment = 0
            ml_confidence_adjustment = 0
            
            for prediction in ml_predictions:
                if prediction.prediction_type == PredictionType.PRICE_DIRECTION:
                    # Корректируем силу на основе предсказания направления
                    direction_match = self._check_direction_match(analysis["direction"], prediction.predicted_value)
                    if direction_match:
                        ml_strength_adjustment += prediction.confidence * 10  # До 10 баллов
                    else:
                        ml_strength_adjustment -= prediction.confidence * 5  # До -5 баллов
                
                elif prediction.prediction_type == PredictionType.SIGNAL_STRENGTH:
                    # Корректируем силу на основе предсказания силы сигнала
                    predicted_strength = prediction.predicted_value * 100  # Конвертируем в 0-100
                    current_strength = analysis["strength"]
                    
                    # Если ML предсказывает более высокую силу, увеличиваем
                    if predicted_strength > current_strength:
                        ml_strength_adjustment += (predicted_strength - current_strength) * prediction.confidence * 0.3
                    else:
                        ml_strength_adjustment -= (current_strength - predicted_strength) * prediction.confidence * 0.2
                
                # Корректируем уверенность
                ml_confidence_adjustment += prediction.confidence * 0.1  # До 0.1
            
            # Применяем корректировки
            analysis["strength"] = max(0, min(100, analysis["strength"] + ml_strength_adjustment))
            analysis["confidence"] = max(0.0, min(1.0, analysis["confidence"] + ml_confidence_adjustment))
            
            # Добавляем ML метаданные
            analysis["ml_enhanced"] = True
            analysis["ml_predictions_count"] = len(ml_predictions)
            analysis["ml_strength_adjustment"] = ml_strength_adjustment
            analysis["ml_confidence_adjustment"] = ml_confidence_adjustment
            
            return analysis
            
        except Exception as e:
            logger.exception(f"Ошибка применения ML корректировок: {e}")
            return analysis
    
    def _check_direction_match(self, analysis_direction: SignalDirection, 
                              ml_prediction: float) -> bool:
        """Проверяет соответствие направления анализа и ML предсказания"""
        if analysis_direction == SignalDirection.LONG and ml_prediction > 0.5:
            return True
        elif analysis_direction == SignalDirection.SHORT and ml_prediction < 0.5:
            return True
        elif analysis_direction == SignalDirection.NEUTRAL:
            return 0.4 <= ml_prediction <= 0.6
        return False
    
    def _update_signal_statistics(self, signals: List[SignalData], 
                                 recommendation: TradingRecommendation):
        """Обновляет статистику сигналов на основе рекомендации"""
        # Это упрощенная версия - в реальной системе нужно отслеживать
        # успешность сигналов через время
        for signal in signals:
            # Пока просто увеличиваем счетчик сигналов
            self.signal_performance[signal.signal_type]["total_signals"] += 1
    
    async def _get_market_context(self, symbol: str) -> MarketContext:
        """Получает контекст рынка для символа"""
        try:
            # Нормализуем символ
            normalized_symbol = self.data_collector.normalize_symbol(symbol)
            logger.debug(f"Получение контекста для {symbol} (нормализован: {normalized_symbol})")
            
            ticker = await self.data_collector.get_ticker(normalized_symbol)
            if not ticker:
                logger.warning(f"Не удалось получить тикер для {symbol} (нормализован: {normalized_symbol})")
                # Пробуем получить цену из OHLCV данных
                try:
                    df = await self.data_collector.get_ohlcv(normalized_symbol, "1m", limit=1)
                    if df is not None and not df.empty:
                        price = float(df['close'].iloc[-1])
                        return MarketContext(
                            symbol=symbol,
                            current_price=price,
                            volume_24h=0,  # Не знаем объем, но цена есть
                            volume_change_24h=0,
                            price_change_24h=0,
                            volatility=None
                        )
                except Exception:
                    pass
                
                return MarketContext(
                    symbol=symbol,
                    current_price=0,
                    volume_24h=0,
                    volume_change_24h=0,
                    price_change_24h=0
                )
            
            # Извлекаем данные из тикера
            current_price = ticker.get('last') or ticker.get('close') or 0
            base_volume = ticker.get('baseVolume') or ticker.get('quoteVolume') or 0
            quote_volume = ticker.get('quoteVolume') or ticker.get('baseVolume') or 0
            price_change = ticker.get('percentage') or 0
            
            # Если объем в baseVolume, конвертируем в quoteVolume (примерно)
            if base_volume > 0 and quote_volume == 0:
                quote_volume = base_volume * current_price if current_price > 0 else 0
            
            logger.debug(f"Контекст для {symbol}: цена={current_price}, объем={quote_volume}, изменение={price_change}%")
            
            return MarketContext(
                symbol=symbol,
                current_price=current_price,
                volume_24h=quote_volume,  # Используем quoteVolume как основной объем
                volume_change_24h=0,  # Не всегда доступно
                price_change_24h=price_change,
                volatility=self._calculate_volatility(symbol)
            )
            
        except Exception as e:
            logger.exception(f"Ошибка получения контекста для {symbol}: {e}")
            return MarketContext(
                symbol=symbol,
                current_price=0,
                volume_24h=0,
                volume_change_24h=0,
                price_change_24h=0
            )
    
    def _calculate_volatility(self, symbol: str) -> Optional[float]:
        """Рассчитывает волатильность символа"""
        try:
            # Упрощенный расчет волатильности
            if symbol in self.signal_history and len(self.signal_history[symbol]) > 10:
                recent_signals = self.signal_history[symbol][-10:]
                price_changes = []
                
                for signal in recent_signals:
                    if 'price_change' in signal.data:
                        price_changes.append(abs(signal.data['price_change']))
                
                if price_changes:
                    return np.std(price_changes)
            
            return None
            
        except Exception:
            return None
    
    def _generate_recommendation(self, symbol: str, signals: List[SignalData],
                               analysis: Dict[str, Any], 
                               market_context: MarketContext) -> TradingRecommendation:
        """Генерирует финальную торговую рекомендацию"""
        
        strength = analysis["strength"]
        confidence = analysis["confidence"]
        direction = analysis["direction"]
        supporting_signals = analysis["supporting_signals"]
        conflicting_signals = analysis["conflicting_signals"]
        
        # Определяем действие
        if strength >= self.thresholds["min_strength"] and confidence >= self.thresholds["min_confidence"]:
            if direction == SignalDirection.LONG:
                action = "BUY"
            elif direction == SignalDirection.SHORT:
                action = "SELL"
            else:
                action = "HOLD"
        elif strength >= 20:
            action = "WATCH"
        else:
            action = "HOLD"
        
        # Определяем уровень риска
        risk_level = self._determine_risk_level(strength, confidence, market_context)
        
        # Генерируем обоснование
        reasoning = self._generate_reasoning(signals, analysis, market_context)
        
        # Рассчитываем уровни входа, стоп-лосса и тейк-профита
        entry_price, stop_loss, take_profit = self._calculate_levels(
            symbol, direction, market_context, signals
        )
        
        return TradingRecommendation(
            symbol=symbol,
            action=action,
            direction=direction,
            overall_strength=strength,
            confidence=confidence,
            risk_level=risk_level,
            signals_count=len(signals),
            supporting_signals=supporting_signals,
            conflicting_signals=conflicting_signals,
            market_context=market_context,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reasoning=reasoning,
            timestamp=datetime.now()
        )
    
    def _determine_risk_level(self, strength: int, confidence: float, 
                             market_context: MarketContext) -> str:
        """Определяет уровень риска"""
        
        risk_score = 0
        
        # Базовая оценка риска
        if strength < 40:
            risk_score += 2
        elif strength < 60:
            risk_score += 1
        
        if confidence < 0.6:
            risk_score += 2
        elif confidence < 0.8:
            risk_score += 1
        
        # Корректировка на основе контекста
        if market_context.volatility and market_context.volatility > 15:
            risk_score += 1
        
        if market_context.price_change_24h and abs(market_context.price_change_24h) > 10:
            risk_score += 1
        
        if risk_score >= 4:
            return "HIGH"
        elif risk_score >= 2:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _generate_reasoning(self, signals: List[SignalData], analysis: Dict[str, Any],
                          market_context: MarketContext) -> List[str]:
        """Генерирует обоснование рекомендации"""
        reasoning = []
        
        # Основные сигналы
        if analysis["supporting_signals"]:
            signal_types = [s.signal_type.value for s in analysis["supporting_signals"]]
            reasoning.append(f"Поддерживающие сигналы: {', '.join(set(signal_types))}")
        
        # Конфликтующие сигналы
        if analysis["conflicting_signals"]:
            signal_types = [s.signal_type.value for s in analysis["conflicting_signals"]]
            reasoning.append(f"Конфликтующие сигналы: {', '.join(set(signal_types))}")
        
        # Контекст рынка
        if market_context.volume_24h > 0:
            reasoning.append(f"Объем 24ч: {market_context.volume_24h:,.0f}")
        
        if market_context.price_change_24h:
            reasoning.append(f"Изменение цены 24ч: {market_context.price_change_24h:+.2f}%")
        
        # Общая оценка
        reasoning.append(f"Общая сила: {analysis['strength']}/100")
        reasoning.append(f"Уверенность: {analysis['confidence']:.2f}")
        
        return reasoning
    
    def _calculate_levels(self, symbol: str, direction: SignalDirection,
                         market_context: MarketContext, 
                         signals: List[SignalData]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Рассчитывает уровни входа, стоп-лосса и тейк-профита"""
        
        current_price = market_context.current_price
        if current_price == 0:
            return None, None, None
        
        entry_price = current_price
        
        # Рассчитываем стоп-лосс и тейк-профит на основе волатильности
        volatility = market_context.volatility or 5.0  # По умолчанию 5%
        
        if direction == SignalDirection.LONG:
            stop_loss = current_price * (1 - volatility / 100)
            take_profit = current_price * (1 + volatility * 1.5 / 100)
        elif direction == SignalDirection.SHORT:
            stop_loss = current_price * (1 + volatility / 100)
            take_profit = current_price * (1 - volatility * 1.5 / 100)
        else:
            stop_loss = None
            take_profit = None
        
        return entry_price, stop_loss, take_profit
    
    def get_performance_statistics(self) -> Dict[str, Any]:
        """Возвращает статистику производительности системы"""
        stats = {
            "signal_performance": {},
            "overall_accuracy": 0.0,
            "total_recommendations": 0,
            "cache_hit_rate": 0.0,
            "last_updated": datetime.now()
        }
        
        # Статистика по типам сигналов
        total_signals = 0
        successful_signals = 0
        
        for signal_type, perf in self.signal_performance.items():
            stats["signal_performance"][signal_type.value] = {
                "total_signals": perf["total_signals"],
                "successful_signals": perf["successful_signals"],
                "accuracy": perf["accuracy"],
                "avg_strength": perf["avg_strength"],
                "avg_confidence": perf["avg_confidence"]
            }
            
            total_signals += perf["total_signals"]
            successful_signals += perf["successful_signals"]
        
        # Общая точность
        if total_signals > 0:
            stats["overall_accuracy"] = successful_signals / total_signals
        
        # Общее количество рекомендаций
        for symbol_recommendations in self.recommendation_history.values():
            stats["total_recommendations"] += len(symbol_recommendations)
        
        # Статистика кэша
        cache_hits = len(self.analysis_cache)
        total_requests = stats["total_recommendations"] + cache_hits
        if total_requests > 0:
            stats["cache_hit_rate"] = cache_hits / total_requests
        
        return stats
    
    def get_recommendation_history(self, symbol: str = None, limit: int = 10) -> List[TradingRecommendation]:
        """Возвращает историю рекомендаций"""
        if symbol:
            return self.recommendation_history.get(symbol, [])[-limit:]
        
        # Все рекомендации
        all_recommendations = []
        for symbol_recommendations in self.recommendation_history.values():
            all_recommendations.extend(symbol_recommendations)
        
        # Сортируем по времени
        all_recommendations.sort(key=lambda x: x.timestamp, reverse=True)
        return all_recommendations[:limit]
    
    def optimize_weights(self):
        """Оптимизирует веса сигналов на основе исторической производительности"""
        for signal_type, perf in self.signal_performance.items():
            if perf["total_signals"] > 10:  # Минимум 10 сигналов для оптимизации
                accuracy = perf["accuracy"]
                
                # Корректируем вес на основе точности
                current_weight = self.signal_weights.get(signal_type, 0.1)
                
                if accuracy > 0.7:  # Высокая точность - увеличиваем вес
                    new_weight = min(current_weight * 1.2, 0.5)
                elif accuracy < 0.4:  # Низкая точность - уменьшаем вес
                    new_weight = max(current_weight * 0.8, 0.05)
                else:
                    new_weight = current_weight
                
                self.signal_weights[signal_type] = new_weight
                logger.info(f"Оптимизирован вес {signal_type.value}: {current_weight:.3f} -> {new_weight:.3f}")
    
    def clear_cache(self):
        """Очищает кэш анализа"""
        self.analysis_cache.clear()
        logger.info("Кэш анализа очищен")
    
    def reset_statistics(self):
        """Сбрасывает статистику производительности"""
        self._initialize_performance_tracking()
        self.recommendation_history.clear()
        self.analysis_cache.clear()
        logger.info("Статистика производительности сброшена")
    
    async def train_ml_models(self, training_period_days: int = 30):
        """Обучает ML модели на исторических данных"""
        if not self.ml_predictor:
            logger.warning("ML модуль недоступен для обучения")
            return False
        
        try:
            logger.info(f"Начинаем обучение ML моделей за {training_period_days} дней...")
            
            # Собираем исторические данные для обучения
            training_data = []
            
            # Получаем список символов для обучения
            symbols = list(self.recommendation_history.keys())
            if not symbols:
                logger.warning("Нет исторических данных для обучения")
                return False
            
            # Ограничиваем количество символов для обучения
            symbols = symbols[:10]  # Максимум 10 символов
            
            for symbol in symbols:
                try:
                    # Получаем исторические данные
                    df_1h = await self.data_collector.get_ohlcv(symbol, "1h", limit=training_period_days * 24)
                    if df_1h is None or len(df_1h) < 50:
                        continue
                    
                    # Создаем обучающие примеры
                    for i in range(20, len(df_1h) - 1):  # Оставляем место для будущих данных
                        # Определяем направление цены
                        current_price = df_1h['close'].iloc[i]
                        future_price = df_1h['close'].iloc[i + 1]
                        price_direction = 1 if future_price > current_price else 0
                        
                        # Рассчитываем волатильность
                        volatility = df_1h['close'].pct_change().rolling(20).std().iloc[i] * 100
                        
                        # Создаем точку данных
                        data_point = {
                            'df': df_1h.iloc[:i+1],
                            'price_direction': price_direction,
                            'volatility': volatility,
                            'volume_anomaly': 1 if df_1h['volume'].iloc[i] > df_1h['volume'].rolling(20).mean().iloc[i] * 3 else 0
                        }
                        
                        training_data.append(data_point)
                        
                except Exception as e:
                    logger.warning(f"Ошибка сбора данных для обучения {symbol}: {e}")
                    continue
            
            if len(training_data) < 100:
                logger.warning(f"Недостаточно данных для обучения: {len(training_data)}")
                return False
            
            # Обучаем модели
            await self.ml_predictor.train_models(training_data)

            logger.info(f"Обучение ML моделей завершено. Использовано {len(training_data)} примеров")

            # Переобучаем OutcomePredictor на свежих данных из simulated_trades
            if self.outcome_predictor is not None:
                try:
                    self.outcome_predictor.fit(self._db_path)
                    logger.info("OutcomePredictor переобучён: %s", self.outcome_predictor.info())
                except Exception as op_err:
                    logger.warning("OutcomePredictor retrain: %s", op_err)

            # Обновляем адаптивные веса после переобучения
            self.update_signal_weights()

            return True

        except Exception as e:
            logger.exception(f"Ошибка обучения ML моделей: {e}")
            return False
    
    def get_ml_performance(self) -> Dict[str, Any]:
        """Возвращает производительность ML моделей"""
        if not self.ml_predictor:
            return {"error": "ML модуль недоступен"}
        
        return self.ml_predictor.get_model_performance()
    
    def get_enhanced_statistics(self) -> Dict[str, Any]:
        """Возвращает расширенную статистику включая ML"""
        stats = self.get_performance_statistics()
        
        # Добавляем ML статистику
        if self.ml_predictor:
            ml_stats = self.get_ml_performance()
            stats["ml_performance"] = ml_stats
            stats["ml_available"] = True
        else:
            stats["ml_available"] = False
        
        return stats
    
    def record_recommendation(self, recommendation: TradingRecommendation) -> bool:
        """Записывает рекомендацию в историю для последующего анализа"""
        if not self.historical_analyzer:
            return False
        
        try:
            # Создаем исторический сигнал
            historical_signal = HistoricalSignal(
                symbol=recommendation.symbol,
                signal_type="intelligence",  # Тип комплексного анализа
                direction=recommendation.direction.value,
                strength=recommendation.overall_strength,
                confidence=recommendation.confidence,
                entry_price=recommendation.entry_price or 0.0,
                stop_loss=recommendation.stop_loss,
                take_profit=recommendation.take_profit,
                timestamp=recommendation.timestamp,
                outcome=SignalOutcome.PENDING,
                metadata={
                    "action": recommendation.action,
                    "risk_level": recommendation.risk_level,
                    "signals_count": recommendation.signals_count,
                    "supporting_signals": [s.signal_type.value for s in recommendation.supporting_signals],
                    "conflicting_signals": [s.signal_type.value for s in recommendation.conflicting_signals],
                    "ml_enhanced": recommendation.metadata.get('ml_enhanced', False) if hasattr(recommendation, 'metadata') else False
                }
            )
            
            return self.historical_analyzer.record_signal(historical_signal)
            
        except Exception as e:
            logger.exception(f"Ошибка записи рекомендации в историю: {e}")
            return False
    
    def get_performance_analysis(self, symbol: str = None, days: int = 30) -> Dict[str, Any]:
        """Получает анализ производительности"""
        if not self.historical_analyzer:
            return {"error": "Исторический анализатор недоступен"}
        
        try:
            start_date = datetime.now() - timedelta(days=days)
            
            # Получаем метрики производительности
            metrics = self.historical_analyzer.calculate_performance_metrics(
                symbol, None, start_date
            )
            
            # Получаем производительность по типам сигналов
            performance_by_type = self.historical_analyzer.get_performance_by_signal_type(
                symbol, start_date
            )
            
            # Получаем тренд производительности
            performance_trend = self.historical_analyzer.get_performance_trend(symbol, days)
            
            # Получаем рекомендации для улучшения
            improvement_recommendations = self.historical_analyzer.get_recommendations_for_improvement(symbol)
            
            return {
                "metrics": {
                    "total_signals": metrics.total_signals,
                    "success_rate": metrics.success_rate,
                    "profit_factor": metrics.profit_factor,
                    "win_rate": metrics.win_rate,
                    "average_profit": metrics.average_profit,
                    "average_loss": metrics.average_loss,
                    "max_drawdown": metrics.max_drawdown,
                    "sharpe_ratio": metrics.sharpe_ratio,
                    "consecutive_wins": metrics.consecutive_wins,
                    "consecutive_losses": metrics.consecutive_losses
                },
                "performance_by_type": {
                    signal_type: {
                        "success_rate": perf.success_rate,
                        "profit_factor": perf.profit_factor,
                        "total_signals": perf.total_signals
                    } for signal_type, perf in performance_by_type.items()
                },
                "performance_trend": performance_trend,
                "improvement_recommendations": improvement_recommendations,
                "analysis_period_days": days
            }
            
        except Exception as e:
            logger.exception(f"Ошибка получения анализа производительности: {e}")
            return {"error": f"Ошибка анализа: {e}"}
    
    def get_signal_effectiveness_report(self, symbol: str = None, days: int = 30) -> str:
        """Генерирует отчет об эффективности сигналов"""
        analysis = self.get_performance_analysis(symbol, days)
        
        if "error" in analysis:
            return f"❌ Ошибка анализа: {analysis['error']}"
        
        metrics = analysis["metrics"]
        recommendations = analysis["improvement_recommendations"]
        
        # Формируем отчет
        report_parts = [
            f"📊 <b>ОТЧЕТ О ПРОИЗВОДИТЕЛЬНОСТИ</b>",
            f"Период: {days} дней",
            f"Символ: {symbol or 'Все'}"
        ]
        
        if metrics["total_signals"] > 0:
            report_parts.extend([
                "",
                "<b>📈 Основные метрики:</b>",
                f"• Всего сигналов: {metrics['total_signals']}",
                f"• Успешность: {metrics['success_rate']:.1%}",
                f"• Win Rate: {metrics['win_rate']:.1%}",
                f"• Profit Factor: {metrics['profit_factor']:.2f}",
                f"• Средняя прибыль: {metrics['average_profit']:.2f}",
                f"• Средний убыток: {metrics['average_loss']:.2f}",
                f"• Макс. просадка: {metrics['max_drawdown']:.1f}%",
                f"• Sharpe Ratio: {metrics['sharpe_ratio']:.2f}",
                f"• Послед. выигрыши: {metrics['consecutive_wins']}",
                f"• Послед. проигрыши: {metrics['consecutive_losses']}"
            ])
        else:
            report_parts.append("\n⚠️ Нет данных для анализа")
        
        if recommendations:
            report_parts.extend([
                "",
                "<b>💡 Рекомендации для улучшения:</b>"
            ])
            for rec in recommendations:
                report_parts.append(f"• {rec}")
        
        return "\n".join(report_parts)
    
    def enhance_with_risk_management(self, recommendation: TradingRecommendation) -> TradingRecommendation:
        """Улучшает рекомендацию с помощью риск-менеджмента"""
        if not self.risk_manager:
            return recommendation
        
        try:
            # Создаем профиль риска для символа
            market_context = recommendation.market_context
            volatility = market_context.volatility or 10.0
            
            risk_profile = self.risk_manager.create_risk_profile(
                symbol=recommendation.symbol,
                volatility=volatility,
                volume=market_context.volume_24h,
                price_change_24h=market_context.price_change_24h or 0.0
            )
            
            # Рассчитываем размер позиции
            if recommendation.entry_price:
                position_size, size_category = self.risk_manager.calculate_position_size(
                    symbol=recommendation.symbol,
                    entry_price=recommendation.entry_price,
                    stop_loss=recommendation.stop_loss or recommendation.entry_price * 0.98
                )
                
                # Рассчитываем стоп-лосс и тейк-профит
                stop_loss, take_profit = self.risk_manager.calculate_stop_loss_take_profit(
                    symbol=recommendation.symbol,
                    entry_price=recommendation.entry_price,
                    direction=recommendation.direction.value
                )
                
                # Оцениваем риск позиции
                position_risk = self.risk_manager.assess_position_risk(
                    symbol=recommendation.symbol,
                    entry_price=recommendation.entry_price,
                    position_size=position_size,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                
                # Проверяем лимиты риска
                risk_ok, risk_warnings = self.risk_manager.check_risk_limits(
                    symbol=recommendation.symbol,
                    position_risk=position_risk
                )
                
                # Обновляем рекомендацию
                entry_price = recommendation.entry_price
                recommendation.stop_loss = stop_loss
                recommendation.take_profit = take_profit
                
                # Добавляем информацию о рисках
                if not hasattr(recommendation, 'metadata'):
                    recommendation.metadata = {}
                
                recommendation.metadata.update({
                    'risk_managed': True,
                    'risk_level': risk_profile.risk_level.value,
                    'position_size': position_size,
                    'size_category': size_category.value,
                    'risk_percent': position_risk.risk_percent,
                    'risk_reward_ratio': position_risk.risk_reward_ratio,
                    'risk_warnings': risk_warnings,
                    'risk_ok': risk_ok
                })
                
                # Корректируем уровень риска в рекомендации
                if risk_profile.risk_level == RiskLevel.VERY_HIGH:
                    recommendation.risk_level = "HIGH"
                elif risk_profile.risk_level == RiskLevel.HIGH:
                    recommendation.risk_level = "HIGH"
                elif risk_profile.risk_level == RiskLevel.MEDIUM:
                    recommendation.risk_level = "MEDIUM"
                else:
                    recommendation.risk_level = "LOW"
            
            return recommendation
            
        except Exception as e:
            logger.exception(f"Ошибка улучшения рекомендации риск-менеджментом: {e}")
            return recommendation
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Возвращает сводку по рискам"""
        if not self.risk_manager:
            return {"error": "Риск-менеджер недоступен"}
        
        return self.risk_manager.get_risk_summary()
    
    def get_risk_recommendations(self) -> List[str]:
        """Возвращает рекомендации по управлению рисками"""
        if not self.risk_manager:
            return ["Риск-менеджер недоступен"]
        
        return self.risk_manager.get_risk_recommendations()


