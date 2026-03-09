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
from core.data_quality import check_ohlcv_quality

try:
    from core.indicators import calculate_trend, calculate_wt, get_zone, detect_fvg
except ImportError:
    def calculate_trend(df, atr_period=43, factor=1.0):
        df = df.copy(); df["trend"] = 1; return df

    def calculate_wt(df, n1=10, n2=21):
        df = df.copy(); df["wt1"] = 0; df["wt2"] = 0; return df

    def get_zone(wt_value):
        # Официальные стандартные зоны WaveTrend: ±60
        return "OS" if wt_value < -60 else ("OB" if wt_value > 60 else "N")

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
        "confluence":     None,
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
            SignalType.PIVOT_ALERT: 0.15,
            SignalType.CONFLUENCE: 0.35,  # высокий вес — мультифакторный сигнал
        }
        # Исходные веса сохраняем отдельно — чтобы не накапливать корректировки
        self._base_signal_weights = dict(self.signal_weights)
        
        # Адаптивные пороги для принятия решений
        self.thresholds = {
            "min_signals": 2,  # Минимум сигналов для рекомендации
            "min_strength": 10,  # TI не фильтрует — фильтрация только в monitoring.py через config.yaml
            "min_confidence": 0.55,  # Минимальная уверенность (снижено с 0.6 для устойчивости к штрафам)
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
        
    async def analyze_symbol(self, symbol: str, pre_collected_signals=None) -> Optional[TradingRecommendation]:
        """
        Комплексный анализ символа и генерация рекомендации.
        pre_collected_signals — если переданы, пропускает _collect_all_signals (экономит API-вызовы).
        """
        import asyncio
        start_time = datetime.now()

        try:
            # Проверяем кэш
            cached_result = self._get_cached_analysis(symbol)
            if cached_result:
                logger.debug(f"Используем кэшированный анализ для {symbol}")
                return cached_result

            if pre_collected_signals:
                signals = pre_collected_signals
                logger.debug(f"[{symbol}] analyze_symbol: используем {len(signals)} pre_collected сигналов")
            else:
                # Собираем все доступные сигналы с таймаутом
                try:
                    signals = await asyncio.wait_for(
                        self._collect_all_signals(symbol),
                        timeout=20.0
                    )
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.error(f"Таймаут при сборе сигналов для {symbol} (прошло {elapsed:.1f}s)")
                    return None
            
            if not signals:
                logger.warning(f"Не найдено сигналов для {symbol} (pre_collected={bool(pre_collected_signals)})")
                return None
            
            # Фильтруем сигналы по качеству
            filtered_signals = self._filter_signals_by_quality(signals)
            
            # Снижаем требования для популярных пар
            _sig_cfg = self.config.get("analysis", {}).get("signals", {})
            min_signals = _sig_cfg.get("min_signals", self.thresholds["min_signals"])
            top_pairs = _sig_cfg.get("premium_pairs",
                ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'DOT', 'MATIC', 'AVAX'])
            single_min_strength = _sig_cfg.get("single_signal_min_strength", 50)
            symbol_base = symbol.split('/')[0] if '/' in symbol else symbol.replace('USDT', '').replace(':USDT', '')
            if symbol_base in top_pairs:
                min_signals = 1  # Для топ-пар достаточно 1 сигнала

            if len(filtered_signals) < min_signals:
                # Сильный одиночный сигнал пропускаем даже для не-топ пар
                max_strength = max((s.strength for s in filtered_signals), default=0)
                if symbol_base not in top_pairs and max_strength < single_min_strength:
                    logger.warning(f"Недостаточно сигналов для {symbol}: {len(filtered_signals)} < {min_signals}, max_str={max_strength}")
                    return None
                
            # Получаем контекст рынка с таймаутом
            try:
                market_context = await asyncio.wait_for(
                    self._get_market_context(symbol),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                elapsed = (datetime.now() - start_time).total_seconds()
                logger.warning(f"Таймаут контекста для {symbol} ({elapsed:.1f}s) — используем fallback")
                # Fallback: цена из OHLCV (уже в кеше после _collect_all_signals)
                market_context = MarketContext(
                    symbol=symbol, current_price=0,
                    volume_24h=0, volume_change_24h=0, price_change_24h=0,
                )
            
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
            t0 = asyncio.get_event_loop().time()

            # Параллельная загрузка OHLCV для всех таймфреймов
            df_1h, df_15m, df_3m = await asyncio.gather(
                self.data_collector.get_ohlcv(symbol, "1h", limit=100),
                self.data_collector.get_ohlcv(symbol, "15m", limit=100),
                self.data_collector.get_ohlcv(symbol, "3m", limit=100),
            )
            t1 = asyncio.get_event_loop().time()
            logger.debug(f"[{symbol}] OHLCV fetch: {t1-t0:.2f}s")

            if df_1h is None or df_1h.empty:
                return signals

            # Проверка качества 15m-данных (свежесть + NaN)
            if df_15m is not None and not df_15m.empty:
                ok, reason = check_ohlcv_quality(
                    df_15m, timeframe="15m",
                    min_bars=50,   # limit=100, берём 50 как разумный минимум
                    symbol=symbol,
                )
                if not ok:
                    logger.info("[intelligence] %s: пропуск из-за качества данных: %s", symbol, reason)
                    return signals

            # Параллельная проверка всех сигналов
            results = await asyncio.gather(
                check_anomaly_signals(symbol, df_15m),
                check_wt_signals(symbol, df_15m),
                check_mtf_signals(symbol, df_1h, df_15m, df_3m),
                check_trend_signals(symbol, df_1h),
                check_divergence_signals(symbol, df_1h),
                check_pivot_signals(symbol, df_1h),
                return_exceptions=True,
            )
            t2 = asyncio.get_event_loop().time()
            logger.debug(f"[{symbol}] signal checks: {t2-t1:.2f}s | total: {t2-t0:.2f}s")

            for r in results:
                if isinstance(r, Exception):
                    logger.debug(f"[{symbol}] signal check error: {r}")
                elif r:
                    signals.extend(r)
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

        # Плавный конфликт: очень сильный → NEUTRAL, умеренный → штраф confidence
        # conflict_ratio = abs(long-short)/max(long,short)
        # 70 vs 68 → 0.029 → NEUTRAL (почти равны)
        # 70 vs 60 → 0.143 → штраф confidence (LONG явно доминирует)
        # 70 vs 40 → 0.429 → без штрафа
        if dominant > 0 and conflict_ratio < 0.05:
            # Очень сильный конфликт (почти равные стороны) → NEUTRAL
            direction = SignalDirection.NEUTRAL
            supporting_signals = []
            conflicting_signals = signals
        elif dominant > 0 and conflict_ratio < conflict_threshold:
            # Умеренный конфликт — direction остаётся, но confidence снижена
            pass  # direction сохраняется по сильнейшей стороне

        # Уверенность: по поддерживающим сигналам + штраф за конфликт (не по всем подряд)
        confidence = self._calculate_advanced_confidence(
            supporting_signals, conflicting_signals, market_context
        )
        if dominant > 0 and conflict_ratio < 0.05:
            confidence *= 0.5
        elif dominant > 0 and conflict_ratio < conflict_threshold:
            confidence *= (0.6 + conflict_ratio)  # 0.6–0.9 плавно
        
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
        # CONFLUENCE сигналы содержат N факторов — считаем каждый как отдельный сигнал
        effective_count = total
        for sig in supporting_signals + conflicting_signals:
            if getattr(sig, "signal_type", None) == SignalType.CONFLUENCE:
                n_factors = len((sig.data or {}).get("factors", []))
                if n_factors > 1:
                    effective_count += n_factors - 1
        signal_count_factor = min(effective_count / 5.0, 1.5)
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

            # ATR(14), ATR(28), TSL-линии и свинг-уровни из 15m датафрейма
            atr = None
            atr_slow = None
            tsl_trendup = None
            tsl_trenddown = None
            swing_low = None
            swing_high = None
            try:
                df_15m = await self.data_collector.get_ohlcv(normalized_symbol, "15m", limit=60)
                atr = self._compute_atr(df_15m, period=14)
                atr_slow = self._compute_atr(df_15m, period=28)
                if df_15m is not None and len(df_15m) >= 44:
                    _trend_cfg = self.config.get("analysis", {}).get("indicators", {}).get("trend", {})
                    _atr_pd  = _trend_cfg.get("atr_period", 43)
                    _factor  = _trend_cfg.get("factor", 1.1)
                    df_t = calculate_trend(df_15m, atr_period=_atr_pd, factor=_factor)
                    tsl_trendup   = float(df_t["trendup"].iloc[-1])
                    tsl_trenddown = float(df_t["trenddown"].iloc[-1])
                    # Свинг-уровни: локальные минимумы/максимумы за последние 20 баров
                    swing_low, swing_high = self._compute_swing_levels(df_15m, current_price)
            except Exception:
                pass

            return MarketContext(
                symbol=symbol,
                current_price=current_price,
                volume_24h=quote_volume,  # Используем quoteVolume как основной объем
                volume_change_24h=0,  # Не всегда доступно
                price_change_24h=price_change,
                volatility=self._calculate_volatility(symbol),
                atr=atr,
                atr_slow=atr_slow,
                tsl_trendup=tsl_trendup,
                tsl_trenddown=tsl_trenddown,
                swing_low=swing_low,
                swing_high=swing_high,
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
    
    @staticmethod
    def _compute_swing_levels(df, current_price: float, lookback: int = 20, wing: int = 2):
        """Находит ближайший свинг-лоу ниже цены и свинг-хай выше цены за последние N баров.

        wing=2 — локальный минимум/максимум определяется как ниже/выше 2 соседних баров с каждой стороны.
        Возвращает (swing_low, swing_high) — оба могут быть None.
        """
        try:
            if df is None or len(df) < lookback + wing * 2:
                return None, None
            recent = df.iloc[-(lookback + wing * 2):].reset_index(drop=True)
            lows_below, highs_above = [], []
            # не берём последние wing баров (нет "правых" соседей)
            for i in range(wing, len(recent) - wing):
                low_i  = recent["low"].iloc[i]
                high_i = recent["high"].iloc[i]
                left_l  = recent["low"].iloc[i - wing: i]
                right_l = recent["low"].iloc[i + 1: i + wing + 1]
                left_h  = recent["high"].iloc[i - wing: i]
                right_h = recent["high"].iloc[i + 1: i + wing + 1]
                if low_i < left_l.min() and low_i < right_l.min() and low_i < current_price:
                    lows_below.append(low_i)
                if high_i > left_h.max() and high_i > right_h.max() and high_i > current_price:
                    highs_above.append(high_i)
            swing_low  = float(max(lows_below))  if lows_below  else None  # ближайший = самый высокий
            swing_high = float(min(highs_above)) if highs_above else None  # ближайший = самый низкий
            return swing_low, swing_high
        except Exception:
            return None, None

    @staticmethod
    def _compute_atr(df, period: int = 14) -> Optional[float]:
        """Вычисляет ATR(14) из датафрейма OHLCV."""
        try:
            if df is None or len(df) < period + 1:
                return None
            high = df['high']
            low = df['low']
            close = df['close']
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(window=period, min_periods=period).mean().iloc[-1]
            return float(atr) if not np.isnan(atr) else None
        except Exception:
            return None

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
        elif strength >= 10:
            action = "WATCH"
        else:
            action = "HOLD"
        
        # Определяем уровень риска
        risk_level = self._determine_risk_level(strength, confidence, market_context)
        
        # Генерируем обоснование
        reasoning = self._generate_reasoning(signals, analysis, market_context)
        
        # Рассчитываем уровни входа, стоп-лосса и тейк-профита
        entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source = self._calculate_levels(
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
            tp1_price=tp1_price,
            sl_source=sl_source,
            tp_source=tp_source,
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
                         signals: List[SignalData]) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], str, str]:
        """Рассчитывает уровни входа, SL и TP. Возвращает (entry, sl, tp, tp1, sl_source, tp_source).

        tp1 — фиксированный уровень частичного выхода (50% позиции при 3R).
        tp  — то же что tp1 (или пивот-уровень если он ≥ 3R).

        SL (приоритет):
          1. TSL-линия индикатора (trendup для LONG / trenddown для SHORT, ATR-43 factor-1.1)
             — самый точный структурный стоп, тонкий при свежей смене тренда
          2. Пивот-уровень из PIVOT_REVERSAL сигналов — если TSL слишком далеко
          3. ATR(14) × динамический множитель (ratio ATR14/ATR28)
          4. Волатильность fallback / фиксированный 2.0%
        """
        current_price = market_context.current_price
        if current_price == 0:
            return None, None, None, None, "", ""

        entry_price = current_price

        # --- Параметры из конфига ---
        sl_cfg     = self.config.get("trading", {}).get("sl_tp", {})
        atr_mult   = sl_cfg.get("atr_multiplier", 1.2)
        sl_min     = sl_cfg.get("sl_min_pct", 0.8)
        sl_max     = sl_cfg.get("sl_max_pct", 3.0)
        tp_rr      = sl_cfg.get("tp_fallback_rr", 2.0)
        atr_dyn    = sl_cfg.get("atr_dynamic", True)
        atr_exp    = sl_cfg.get("atr_expand_threshold", 1.3)
        atr_con    = sl_cfg.get("atr_contract_threshold", 0.8)
        struct_buf = sl_cfg.get("struct_sl_buffer_pct", 0.3)  # % от цены
        struct_max = sl_cfg.get("struct_sl_max_dist", 3.0)

        is_long = direction == SignalDirection.LONG
        is_short = direction == SignalDirection.SHORT

        # --- ATR динамика: корректируем базовый множитель ---
        if atr_dyn and market_context.atr and market_context.atr_slow:
            ratio = market_context.atr / market_context.atr_slow
            if ratio > atr_exp:
                atr_mult = round(atr_mult * 0.85, 3)    # всплеск → SL уже
            elif ratio < atr_con:
                atr_mult = round(min(atr_mult * 1.1, 1.5), 3)  # затишье → чуть шире

        # --- ATR/волатильность baseline ---
        if market_context.atr and entry_price > 0:
            atr_pct = market_context.atr / entry_price * 100
            sl_pct  = max(sl_min, min(atr_mult * atr_pct, sl_max))
            sl_source = f"atr_14:{atr_pct:.2f}%"
        elif market_context.volatility:
            sl_pct  = max(sl_min, min(market_context.volatility, sl_max))
            sl_source = f"volatility:{market_context.volatility:.2f}%"
        else:
            sl_pct  = 2.0
            sl_source = "fallback:2.0%"

        if direction not in (SignalDirection.LONG, SignalDirection.SHORT):
            return entry_price, None, None, None, "", ""

        tsl_too_tight = sl_cfg.get("tsl_too_tight_pct", 0.6)

        # ── 1. TSL-линия (trendup / trenddown ATR-43) ──────────────────────
        tsl_line = market_context.tsl_trendup if is_long else market_context.tsl_trenddown
        if tsl_line and tsl_line > 0:
            if is_long and tsl_line < entry_price:
                tsl_dist_pct = (entry_price - tsl_line) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if sl_min <= tsl_sl_pct <= struct_max:
                    # TSL слишком близко — ищем свинг-лоу как запасной уровень
                    if tsl_sl_pct < tsl_too_tight and market_context.swing_low:
                        sw = market_context.swing_low
                        sw_pct = (entry_price - sw) / entry_price * 100 + struct_buf
                        if sl_min <= sw_pct <= struct_max:
                            sl_pct    = sw_pct
                            sl_source = "swing_low"
                        else:
                            sl_pct    = tsl_sl_pct
                            sl_source = "tsl_line:trendup"
                    else:
                        sl_pct    = tsl_sl_pct
                        sl_source = "tsl_line:trendup"
            elif is_short and tsl_line > entry_price:
                tsl_dist_pct = (tsl_line - entry_price) / entry_price * 100
                tsl_sl_pct   = tsl_dist_pct + struct_buf
                if sl_min <= tsl_sl_pct <= struct_max:
                    if tsl_sl_pct < tsl_too_tight and market_context.swing_high:
                        sw = market_context.swing_high
                        sw_pct = (sw - entry_price) / entry_price * 100 + struct_buf
                        if sl_min <= sw_pct <= struct_max:
                            sl_pct    = sw_pct
                            sl_source = "swing_high"
                        else:
                            sl_pct    = tsl_sl_pct
                            sl_source = "tsl_line:trenddown"
                    else:
                        sl_pct    = tsl_sl_pct
                        sl_source = "tsl_line:trenddown"

        # ── 2. Пивот-уровень как резервный структурный SL ──────────────────
        # Используем только если TSL не дал результата (SL всё ещё ATR-based)
        if "tsl_line" not in sl_source and "swing" not in sl_source:
            pivot_type = "support" if is_long else "resistance"
            struct_levels = [
                s.data["level"]
                for s in signals
                if s.signal_type == SignalType.PIVOT_REVERSAL
                and s.data.get("pivot_type") == pivot_type
                and (s.data.get("level", 0) < entry_price if is_long
                     else s.data.get("level", 0) > entry_price)
            ]
            if struct_levels:
                nearest = max(struct_levels) if is_long else min(struct_levels)
                pivot_sl_pct = abs(entry_price - nearest) / entry_price * 100 + struct_buf
                if sl_min <= pivot_sl_pct <= struct_max and pivot_sl_pct < sl_pct:
                    sl_pct    = pivot_sl_pct
                    sl_source = f"structural:{pivot_type}:{nearest:.6g}"

        # ── TP1: фиксированный 3R (частичный выход 50% позиции) ───────────
        # Всегда 3R от SL независимо от пивотов
        tp1_pct = sl_pct * 3.0
        if is_long:
            stop_loss  = entry_price * (1 - sl_pct / 100)
            tp1_price  = entry_price * (1 + tp1_pct / 100)
        else:
            stop_loss  = entry_price * (1 + sl_pct / 100)
            tp1_price  = entry_price * (1 - tp1_pct / 100)

        # ── TP fallback = TP1 (пивот-TP может перезаписать в monitoring,
        #    но только если он ≥ 3R, иначе take_profit = tp1) ──────────────
        take_profit = tp1_price
        tp_source   = f"atr_rr_3.0:{tp1_pct:.2f}%"

        return entry_price, stop_loss, take_profit, tp1_price, sl_source, tp_source
    
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
    
    @staticmethod
    def _build_training_data(dfs: dict) -> list:
        """Подготовка обучающих данных — CPU-bound, вызывается из thread pool."""
        training_data = []
        for symbol, df_1h in dfs.items():
            if df_1h is None or len(df_1h) < 50:
                continue
            # Предварительный расчёт (O(n) вместо O(n²))
            volatility_series = df_1h['close'].pct_change().rolling(20).std() * 100
            vol_mean_series = df_1h['volume'].rolling(20).mean()
            for i in range(20, len(df_1h) - 1):
                training_data.append({
                    'df': df_1h.iloc[:i+1],
                    'price_direction': 1 if df_1h['close'].iloc[i + 1] > df_1h['close'].iloc[i] else 0,
                    'volatility': volatility_series.iloc[i],
                    'volume_anomaly': 1 if df_1h['volume'].iloc[i] > vol_mean_series.iloc[i] * 3 else 0,
                })
        return training_data

    async def train_ml_models(self, training_period_days: int = 30):
        """Обучает ML модели на исторических данных"""
        if not self.ml_predictor:
            logger.warning("ML модуль недоступен для обучения")
            return False

        try:
            logger.info(f"Начинаем обучение ML моделей за {training_period_days} дней...")

            # Получаем список символов для обучения
            symbols = list(self.recommendation_history.keys())
            if not symbols:
                symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]
                logger.info("recommendation_history пуст — используем базовые символы для ML-обучения")
            symbols = symbols[:10]

            # Параллельная загрузка OHLCV (async, event loop)
            dfs_list = await asyncio.gather(*[
                self.data_collector.get_ohlcv(s, "1h", limit=training_period_days * 24)
                for s in symbols
            ], return_exceptions=True)
            dfs = {
                s: df for s, df in zip(symbols, dfs_list)
                if isinstance(df, __import__('pandas').DataFrame)
            }

            # Подготовка данных + обучение — всё в thread pool, не блокирует event loop
            def _train_sync():
                training_data = self._build_training_data(dfs)
                if len(training_data) < 100:
                    logger.warning(f"Недостаточно данных для обучения: {len(training_data)}")
                    return 0
                self.ml_predictor._train_models_sync(training_data)
                return len(training_data)

            training_count = await asyncio.to_thread(_train_sync)
            if not training_count:
                return False

            logger.info(f"Обучение ML моделей завершено. Использовано {training_count} примеров")

            # Переобучаем OutcomePredictor на свежих данных из simulated_trades
            if self.outcome_predictor is not None:
                try:
                    await asyncio.to_thread(self.outcome_predictor.fit, self._db_path)
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
    


