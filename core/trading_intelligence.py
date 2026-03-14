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
    check_trend_signals, check_mtf_bias_signal,
)

# Форматтер рекомендаций
from core.intelligence_formatter import format_intelligence_message  # noqa: F401 — re-export
from core.data_quality import check_ohlcv_quality

# Strategy Pattern
try:
    from strategies import get_strategy, list_strategies
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False
    logger.warning("Strategies module not available, will use legacy logic")

try:
    from core.indicators import calculate_trend, calculate_wt, get_zone, detect_fvg, compute_atr, compute_volatility
except ImportError:
    import logging as _log
    _log.getLogger(__name__).error(
        "КРИТИЧЕСКАЯ ОШИБКА: core.indicators недоступен — используются заглушки! "
        "Тренд, TSL и ATR будут некорректны!"
    )

    def calculate_trend(df, atr_period=43, factor=1.0):  # noqa: stub
        df = df.copy(); df["trend"] = 1; return df

    def calculate_wt(df, n1=10, n2=21):  # noqa: stub
        df = df.copy(); df["wt1"] = 0; df["wt2"] = 0; return df

    def get_zone(wt_value):  # noqa: stub
        return "OS" if wt_value < -60 else ("OB" if wt_value > 60 else "N")

    def detect_fvg(df):  # noqa: stub
        return "NONE", 0

    def compute_atr(df=None, period=14, **kw):  # noqa: stub
        return None

    def compute_volatility(*_args, **_kw):  # noqa: stub
        return None

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

        # Веса сигналов: MTF_BIAS = главное WaveTrend-ядро (7 TF, alignment, senior gate)
        # Пивоты = второе ядро (подтверждение + цели).
        # MTF_SIGNAL / MTF_ALERT — временно сохранены, будут упразднены после тестирования MTF_BIAS.
        self.signal_weights = {
            SignalType.MTF_BIAS:       0.50,  # ГЛАВНОЕ ядро — WaveTrend 7 TF
            SignalType.PIVOT_REVERSAL: 0.20,  # второе ядро — пивоты (подтверждение + цели)
            SignalType.CONFLUENCE:     0.15,  # производный от WT
            SignalType.DIVERGENCE:     0.10,
            SignalType.MTF_ALERT:      0.10,  # → будет упразднён в Шаге 3
            SignalType.WT_SIGNAL:      0.08,
            SignalType.MTF_SIGNAL:     0.05,  # → будет упразднён в Шаге 3
            SignalType.TREND_SIGNAL:   0.05,
            SignalType.ANOMALY:        0.03,
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

        # Strategy Pattern: инициализируем все активные стратегии
        self.strategy = None           # основная (для TG-сигналов)
        self.strategies: Dict[str, Any] = {}  # все активные стратегии
        self.active_strategy_name: str = "confluence"
        if STRATEGIES_AVAILABLE:
            try:
                # Основная стратегия (для TG-сигналов)
                self.active_strategy_name = (
                    (config.get("trading.active_strategy") if config else None)
                    or (config.get("strategy", {}).get("name") if config else None)
                    or "confluence"
                )
                # Список всех стратегий для параллельной симуляции
                active_list = (
                    (config.get("trading.active_strategies") if config else None)
                    or [self.active_strategy_name]
                )
                for sname in active_list:
                    try:
                        scfg = (
                            (config.get(f"trading.strategies.{sname}") if config else None)
                            or (config.get("strategy", {}).get(sname, {}) if config else {})
                            or {}
                        )
                        self.strategies[sname] = get_strategy(sname, scfg)
                        logger.info(f"Strategy loaded: {sname}")
                    except Exception as e:
                        logger.warning(f"Strategy '{sname}' не загружена: {e}")
                # Обратная совместимость: self.strategy = основная
                self.strategy = self.strategies.get(self.active_strategy_name)
                if self.strategy is None and self.strategies:
                    # fallback на первую доступную
                    self.active_strategy_name, self.strategy = next(iter(self.strategies.items()))
                logger.info(f"Active strategy: {self.active_strategy_name}, total: {list(self.strategies.keys())}")
            except Exception as e:
                logger.warning(f"Failed to initialize strategies, falling back to legacy: {e}")
                self.strategy = None
        else:
            logger.debug("Strategy Pattern not available, using legacy analysis")

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
            "mtf_bias":       SignalType.MTF_BIAS,
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
    
    async def _run_strategy(self, symbol: str, signals: List[SignalData],
                           market_context: MarketContext) -> Optional[TradingRecommendation]:
        """Запускает основную стратегию. Async для совместимости с asyncio.wait_for()."""
        if not self.strategy:
            return None
        try:
            recommendation = self.strategy.analyze(signals, market_context)
            return recommendation
        except Exception as e:
            logger.exception(f"Strategy.analyze() error for {symbol}: {e}")
            return None

    async def _run_all_strategies(self, symbol: str, signals: List[SignalData],
                                  market_context: MarketContext) -> Dict[str, TradingRecommendation]:
        """
        Запускает все активные стратегии параллельно.
        Возвращает Dict[strategy_name, recommendation] — только успешные результаты.
        Основная стратегия тоже включена в словарь.
        """
        if not self.strategies:
            return {}

        async def _run_one(name: str, strat) -> tuple:
            try:
                rec = strat.analyze(signals, market_context)
                return name, rec
            except Exception as e:
                logger.debug(f"Strategy '{name}' ошибка для {symbol}: {e}")
                return name, None

        results = await asyncio.gather(
            *[_run_one(name, strat) for name, strat in self.strategies.items()],
            return_exceptions=False
        )
        return {
            name: rec for name, rec in results
            if rec is not None
        }
    
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

            # Этап 8.4.2: фиксируем единый snapshot_time для всех проверок
            snapshot_time = datetime.now()

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

            # Этап 8.4.2: None = data collection error (no silent fallback)
            if signals is None:
                logger.info("[intelligence] %s: данные недоступны — анализ пропущен", symbol)
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
                fallback_price = 0.0
                try:
                    _df = await self.data_collector.get_ohlcv(symbol, "15m", limit=5)
                    if _df is not None and len(_df) > 0:
                        fallback_price = float(_df["close"].iloc[-1])
                except Exception:
                    pass
                market_context = MarketContext(
                    symbol=symbol, current_price=fallback_price,
                    volume_24h=0, volume_change_24h=0, price_change_24h=0,
                )
            
            # Проверяем минимальные требования к рынку
            if not self._validate_market_context(market_context):
                logger.warning(f"Рыночный контекст не подходит для анализа {symbol} (объем: {market_context.volume_24h}, цена: {market_context.current_price})")
                # Для топ-пар все равно продолжаем, даже если контекст не идеален
                if symbol_base not in top_pairs:
                    return None
            
            # Запускаем все стратегии параллельно
            all_recs: Dict[str, TradingRecommendation] = {}
            if self.strategies:
                try:
                    all_recs = await asyncio.wait_for(
                        self._run_all_strategies(symbol, filtered_signals, market_context),
                        timeout=20.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Strategies timeout for {symbol}, using legacy analysis")
                except Exception as e:
                    logger.warning(f"Strategies error for {symbol}: {e}, falling back to legacy")

            # Основная рекомендация — от active стратегии
            recommendation = all_recs.get(self.active_strategy_name)

            # Если основная стратегия не выдала результат — legacy fallback
            if recommendation is None:
                logger.debug(f"Active strategy '{self.active_strategy_name}' вернула None для {symbol} — legacy")
                analysis = self._analyze_signals_advanced(filtered_signals, market_context)
                recommendation = self._generate_recommendation(
                    symbol, filtered_signals, analysis, market_context
                )

            # Тегируем основную рекомендацию именем стратегии
            if recommendation is not None:
                recommendation.metadata = recommendation.metadata or {}
                recommendation.metadata["strategy_name"] = self.active_strategy_name
                # Остальные стратегии передаём в monitoring для раздельной регистрации
                other_recs = {k: v for k, v in all_recs.items() if k != self.active_strategy_name}
                if other_recs:
                    recommendation.metadata["all_strategy_recs"] = other_recs
            
            if recommendation is None:
                return None
            
            # Улучшаем анализ с помощью ML (с таймаутом)
            if self.ml_predictor:
                try:
                    recommendation = await asyncio.wait_for(
                        self._enhance_recommendation_with_ml(symbol, recommendation, market_context),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут ML анализа для {symbol}, продолжаем без ML")
                except Exception as e:
                    logger.warning(f"Ошибка ML анализа для {symbol}: {e}, продолжаем без ML")
            
            # Этап 8.4.2: фиксируем snapshot_time в метаданных рекомендации
            if recommendation.metadata is None:
                recommendation.metadata = {}
            recommendation.metadata["snapshot_time"] = snapshot_time.isoformat()

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
    
    async def _collect_all_signals(self, symbol: str) -> Optional[List[SignalData]]:
        """
        Собирает все доступные сигналы для символа.
        Возвращает:
          - List[SignalData] — сигналы (может быть пустым если нет сигналов)
          - None — критичная ошибка загрузки данных (no silent fallback, Этап 8.4.2)
        """
        signals: List[SignalData] = []
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

            # Этап 8.4.2: нет данных = ошибка, не тихий возврат
            if df_1h is None or df_1h.empty:
                logger.info("[intelligence] %s: 1h OHLCV недоступен — пропуск (data error)", symbol)
                return None

            # Проверка качества 15m-данных (свежесть + NaN)
            if df_15m is not None and not df_15m.empty:
                ok, reason = check_ohlcv_quality(
                    df_15m, timeframe="15m",
                    min_bars=50,   # limit=100, берём 50 как разумный минимум
                    symbol=symbol,
                )
                if not ok:
                    logger.info("[intelligence] %s: пропуск из-за качества данных: %s", symbol, reason)
                    return None

            # Параллельная проверка всех сигналов
            # Примитивные check_divergence_signals / check_pivot_signals удалены:
            # их роль выполняют полные divergence_detector + pivot_reversal (фоновые задачи).
            # MTF_BIAS — главное WT-ядро (7 TF, alignment score, senior gate).
            results = await asyncio.gather(
                check_anomaly_signals(symbol, df_15m),
                check_wt_signals(symbol, df_15m),
                check_mtf_signals(symbol, df_1h, df_15m, df_3m),
                check_trend_signals(symbol, df_1h),
                check_mtf_bias_signal(symbol, self.data_collector, regime=None, cfg=self.config),
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
        """Делегирует в core.intelligence.signal_aggregator."""
        from core.intelligence.signal_aggregator import analyze_signals_advanced
        return analyze_signals_advanced(
            signals, market_context,
            self.signal_weights, self.thresholds,
            self._calculate_advanced_confidence,
        )
    
    def _calculate_adaptive_weighted_strength(self, signals: List[SignalData]) -> int:
        """Делегирует в core.intelligence.signal_aggregator."""
        from core.intelligence.signal_aggregator import calculate_adaptive_weighted_strength
        return calculate_adaptive_weighted_strength(signals, self.signal_weights)
    
    def _calculate_advanced_confidence(self, supporting_signals: List[SignalData],
                                     conflicting_signals: List[SignalData],
                                     market_context: MarketContext) -> float:
        """Делегирует в core.intelligence.confidence_calculator."""
        from core.intelligence.confidence_calculator import calculate_advanced_confidence
        return calculate_advanced_confidence(supporting_signals, conflicting_signals, market_context)
    
    async def _enhance_recommendation_with_ml(self, symbol: str, recommendation: TradingRecommendation,
                                             market_context: MarketContext) -> TradingRecommendation:
        """
        Улучшает рекомендацию с помощью ML (OutcomePredictor).
        Модифицирует confidence на основе P(win).
        """
        if not recommendation or not self.outcome_predictor:
            return recommendation
        
        try:
            if recommendation.direction == SignalDirection.NEUTRAL:
                return recommendation
            
            supporting = recommendation.supporting_signals or []
            first_sig = supporting[0] if supporting else None
            sig_type = first_sig.signal_type.value if first_sig else "composite"
            direction_str = recommendation.direction.value if hasattr(recommendation.direction, "value") else str(recommendation.direction)
            
            features_dict = {
                "volatility": market_context.volatility or 0,
                "price_change_24h": market_context.price_change_24h or 0,
            }
            
            win_prob = self.outcome_predictor.predict_win_prob(
                signal_type=sig_type,
                direction=direction_str,
                strength=recommendation.overall_strength,
                confidence=recommendation.confidence,
                features_dict=features_dict,
                regime=None,
            )
            
            if win_prob is not None:
                orig_conf = recommendation.confidence
                # Блендируем: 70% оригинал, 30% предсказание ML
                blended_conf = orig_conf * 0.7 + win_prob * 0.3
                recommendation.confidence = round(blended_conf, 4)
                logger.debug(
                    f"[{symbol}] OutcomePredictor: P(win)={win_prob:.2f} "
                    f"conf {orig_conf:.3f}→{recommendation.confidence:.3f}"
                )
        except Exception as e:
            logger.debug(f"OutcomePredictor blend error: {e}")
        
        return recommendation
    
    async def _enhance_analysis_with_ml(self, symbol: str, analysis: Dict[str, Any],
                                       market_context: MarketContext) -> Dict[str, Any]:
        """Делегирует в core.intelligence.ml_enhancer."""
        from core.intelligence.ml_enhancer import enhance_analysis_with_ml
        return await enhance_analysis_with_ml(
            symbol, analysis, market_context,
            self.ml_predictor, self.outcome_predictor,
        )

    def _apply_ml_corrections(self, analysis: Dict[str, Any],
                             ml_predictions,
                             market_context: MarketContext) -> Dict[str, Any]:
        """Делегирует в core.intelligence.ml_enhancer."""
        from core.intelligence.ml_enhancer import apply_ml_corrections
        return apply_ml_corrections(analysis, ml_predictions, market_context)

    def _check_direction_match(self, analysis_direction: SignalDirection,
                              ml_prediction: float) -> bool:
        """Делегирует в core.intelligence.ml_enhancer."""
        from core.intelligence.ml_enhancer import _check_direction_match
        return _check_direction_match(analysis_direction, ml_prediction)
    
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

            # ATR(14), ATR(28), TSL-линии, свинг-уровни и волатильность из 15m датафрейма
            atr = None
            atr_slow = None
            tsl_trendup = None
            tsl_trenddown = None
            swing_low = None
            swing_high = None
            volatility = None
            try:
                df_15m = await self.data_collector.get_ohlcv(normalized_symbol, "15m", limit=60)
                atr = self._compute_atr(df_15m, period=14)
                atr_slow = self._compute_atr(df_15m, period=28)
                if df_15m is not None and len(df_15m) >= 21:
                    # Волатильность из OHLCV — единый источник (проценты)
                    volatility = compute_volatility(df_15m['close'])
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
                volatility=volatility,
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
    def _compute_swing_levels(df, current_price: float, lookback: int = 20, wing: int = 4):
        """Находит структурный свинг-лоу и свинг-хай за последние lookback баров.

        Принцип "за вершину": берём МИНИМАЛЬНЫЙ low (самый низкий экстремум в окне) —
        это реальная структурная вершина, видимая на графике.
        wing=4 используется только для отбора значимых локальных экстремумов
        (не берём случайные шумовые свечи без подтверждения соседями).

        Возвращает (swing_low, swing_high) — оба могут быть None.
        """
        try:
            if df is None or len(df) < lookback + wing * 2:
                return None, None
            recent = df.iloc[-(lookback + wing * 2):].reset_index(drop=True)
            lows_candidates, highs_candidates = [], []
            # Ищем значимые экстремумы (не шум): low/high ниже/выше всех wing соседей
            for i in range(wing, len(recent) - wing):
                low_i  = recent["low"].iloc[i]
                high_i = recent["high"].iloc[i]
                left_l  = recent["low"].iloc[i - wing: i]
                right_l = recent["low"].iloc[i + 1: i + wing + 1]
                left_h  = recent["high"].iloc[i - wing: i]
                right_h = recent["high"].iloc[i + 1: i + wing + 1]
                if low_i < left_l.min() and low_i < right_l.min() and low_i < current_price:
                    lows_candidates.append(low_i)
                if high_i > left_h.max() and high_i > right_h.max() and high_i > current_price:
                    highs_candidates.append(high_i)
            # "За вершину" = самый ДАЛЬНИЙ экстремум (min low / max high)
            swing_low  = float(min(lows_candidates))  if lows_candidates  else None
            swing_high = float(max(highs_candidates)) if highs_candidates else None
            return swing_low, swing_high
        except Exception:
            return None, None

    @staticmethod
    def _compute_atr(df, period: int = 14) -> Optional[float]:
        """ATR через единую функцию из core/indicators.py (Wilder's RMA)."""
        try:
            return compute_atr(df=df, period=period)
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
    
    def _generate_recommendation(self, symbol, signals, analysis, market_context):
        from core.intelligence.recommendation_generator import generate_recommendation
        return generate_recommendation(symbol, signals, analysis, market_context, self.thresholds, self.config)

    def _determine_risk_level(self, strength, confidence, market_context):
        from core.intelligence.recommendation_generator import determine_risk_level
        return determine_risk_level(strength, confidence, market_context)

    def _generate_reasoning(self, signals, analysis, market_context):
        from core.intelligence.recommendation_generator import generate_reasoning
        return generate_reasoning(signals, analysis, market_context)

    def _calculate_levels(self, symbol, direction, market_context, signals):
        from core.intelligence.recommendation_generator import calculate_levels
        return calculate_levels(symbol, direction, market_context, signals, self.config)
    
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
            # Волатильность в % — эквивалент compute_volatility(closes, period=20)
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
    


