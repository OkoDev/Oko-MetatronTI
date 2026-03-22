"""
Trading Intelligence Layer - система объединения и анализа сигналов
Объединяет все типы сигналов в комплексные торговые рекомендации
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, NamedTuple, Optional, Tuple, Any
import pandas as pd
import numpy as np

# Модели данных
from core.signal_models import (
    SignalType, SignalDirection, SignalStrength,
    SignalData, MarketContext, TradingRecommendation, MTFContext,
)

# Проверки сигналов
from core.signal_checkers import (
    check_anomaly_signals, check_wt_signals,
    check_trend_signals, check_mtf_bias_signal, check_wt_b_signals,
)

# Форматтер рекомендаций
from core.intelligence_formatter import format_intelligence_message  # noqa: F401 — re-export
from core.data_quality import check_ohlcv_quality
from core.entry_config import get_primary_entry_tf

# Strategy Pattern
try:
    from strategies import get_strategy, list_strategies
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False

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
        "confluence":     None,
        "smc_structure":  None,
    }

    def __init__(self, data_collector, config: Dict = None, db_path: str = "subscriptions.db"):
        self.data_collector = data_collector
        self.config = config or {}
        self._db_path = db_path

        # Веса сигналов: MTF_BIAS = главное WaveTrend-ядро (7 TF, alignment, senior gate)
        # Пивоты = второе ядро (подтверждение + цели).
        # DEV-31: MTF_SIGNAL удалён (legacy, 0 сделок, заменён MTF_BIAS).
        self.signal_weights = {
            SignalType.MTF_BIAS:       0.50,  # ГЛАВНОЕ ядро — WaveTrend 7 TF
            SignalType.PIVOT_REVERSAL: 0.20,  # второе ядро — пивоты (подтверждение + цели)
            SignalType.CONFLUENCE:     0.15,  # производный от WT
            SignalType.DIVERGENCE:     0.10,
            SignalType.MTF_ALERT:      0.10,  # → будет упразднён в Шаге 3
            SignalType.WT_SIGNAL:      0.08,
            SignalType.WT_B_SIGNAL:    0.35,  # тип B: WR=85% на бэктесте (DEV-24: реанимация)
            SignalType.TREND_SIGNAL:   0.05,
            SignalType.ANOMALY:        0.03,
            SignalType.SMC_STRUCTURE:  0.12,  # BOS/CHoCH — Этап 9 SMC
        }
        # Исходные веса сохраняем отдельно — чтобы не накапливать корректировки
        self._base_signal_weights = dict(self.signal_weights)
        
        # Адаптивные пороги для принятия решений
        self.thresholds = {
            "min_signals": 2,  # Минимум сигналов для рекомендации
            "min_strength": 10,  # TI не фильтрует — фильтрация только в monitoring.py через config.yaml
            "min_confidence": 0.55,  # Минимальная уверенность
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
        _use_op = (config.get("ml.use_outcome_predictor", True) if config else True)
        if not _use_op:
            logger.info("OutcomePredictor отключён: ml.use_outcome_predictor=false (AUC<0.5)")
        else:
            try:
                from core.outcome_predictor import OutcomePredictor
                op = OutcomePredictor()
                # ARCH-21: скользящее окно из конфига (None = вся история)
                _tw = (config.get("outcome_predictor.training_window") if config else None)
                op.fit(db_path, training_window=_tw)
                self.outcome_predictor = op
                logger.info("OutcomePredictor: %s", op.info())
            except Exception as e:
                logger.warning("OutcomePredictor не инициализирован: %s", e)

        # ARCH-12.5: AutoCalibrator — rule-based калибровка MTF multipliers
        self._auto_calibrator = None
        try:
            from core.auto_calibrator import AutoCalibrator
            self._auto_calibrator = AutoCalibrator(db_path=db_path)
            logger.info("AutoCalibrator: загружен (%s)", self._auto_calibrator.calibration_path)
        except Exception as e:
            logger.warning("AutoCalibrator не инициализирован: %s", e)

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
            "wt_b_signal":    SignalType.WT_B_SIGNAL,
            "anomaly":        SignalType.ANOMALY,
            "divergence":     SignalType.DIVERGENCE,
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
    
    # Приоритет стратегий для оркестровки (ARCH-09)
    _STRATEGY_PRIORITY = [
        "reversal_scanner",     # WT 15m разворот — CONFLUENCE + TSL + пивот + дивер
        "reversal",             # качественный разворот (1 сигнал без count-penalty)
        "trend_following",      # несколько трендовых подтверждений
    ]

    def _pick_best_recommendation(
        self,
        all_recs: Dict[str, "TradingRecommendation"],
    ) -> tuple[Optional["TradingRecommendation"], str]:
        """
        Оркестровый выбор лучшей рекомендации (ARCH-09):
          1. reversal_scanner (разворотный сетап) — если есть, берём сразу
          2. reversal / trend_following — из обоих берём с бо́льшим strength
          3. Любая другая загруженная стратегия (fallback)

        Returns (recommendation, strategy_name).
        """
        if not all_recs:
            return None, "legacy"

        # Priority-1: reversal_scanner
        if rec := all_recs.get("reversal_scanner"):
            return rec, "reversal_scanner"

        # Priority-2: reversal / trend_following — max by overall_strength
        candidates = {
            k: v for k, v in all_recs.items()
            if k in ("reversal", "trend_following")
        }
        if candidates:
            best_name = max(
                candidates,
                key=lambda n: candidates[n].overall_strength or 0,
            )
            return candidates[best_name], best_name

        # Priority-3: любая другая стратегия
        name, rec = next(iter(all_recs.items()))
        return rec, name

    # ── ARCH-20: явный арбитр стратегий ──────────────────────────────────────

    class _StrategyDecision(NamedTuple):
        direction: "SignalDirection"
        confidence_mult: float
        reason: str

    def _select_strategy(
        self,
        signals: List[SignalData],
        mtf_ctx: Optional[MTFContext],
    ) -> "_StrategyDecision":
        """
        ARCH-20: Явный арбитр направлений (interim fix без ScanContext).

        Считает силу LONG vs SHORT по взвешенной сумме strength сигналов,
        сверяет с MTF bias → возвращает итоговое direction, confidence_mult и reason.
        confidence_mult применяется к recommendation.confidence после выбора стратегии.
        """
        if not signals:
            return self._StrategyDecision(SignalDirection.NEUTRAL, 1.0, "no_signals")

        long_str = sum(s.strength for s in signals if s.direction == SignalDirection.LONG)
        short_str = sum(s.strength for s in signals if s.direction == SignalDirection.SHORT)
        total = long_str + short_str or 1

        long_pct = long_str / total
        short_pct = short_str / total

        # Доминирующее направление из сигналов (порог 65%)
        if long_pct >= 0.65:
            sig_dir = SignalDirection.LONG
        elif short_pct >= 0.65:
            sig_dir = SignalDirection.SHORT
        else:
            sig_dir = SignalDirection.NEUTRAL  # конфликт

        bias = mtf_ctx.direction_bias if mtf_ctx else SignalDirection.NEUTRAL
        bs = mtf_ctx.bias_strength if mtf_ctx else 0.0

        if bias == SignalDirection.NEUTRAL:
            if sig_dir == SignalDirection.NEUTRAL:
                return self._StrategyDecision(SignalDirection.NEUTRAL, 0.85, "direction_conflict_no_bias")
            return self._StrategyDecision(sig_dir, 1.0, "no_mtf_bias")

        if sig_dir == SignalDirection.NEUTRAL:
            # Конфликт сигналов → доверяем MTF bias, снижаем уверенность
            return self._StrategyDecision(bias, 0.80, f"direction_conflict|bias={bias.value}")

        if sig_dir == bias:
            # Сигналы согласованы с bias → лёгкое усиление
            mult = round(min(1.15, 1.0 + 0.1 * bs), 2)
            return self._StrategyDecision(sig_dir, mult, f"aligned|bias={bias.value}")

        # Сигналы против bias → снижаем уверенность пропорционально bias_strength
        mult = round(max(0.70, 1.0 - 0.30 * bs), 2)
        return self._StrategyDecision(sig_dir, mult, f"counter_bias={bias.value}")

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
        
    async def analyze_symbol(self, symbol: str, pre_collected_signals=None, manual_request: bool = False) -> Optional[TradingRecommendation]:
        """
        Комплексный анализ символа и генерация рекомендации.
        pre_collected_signals — если переданы, пропускает _collect_all_signals (экономит API-вызовы).
        manual_request — ручной запрос пользователя: смягчаем фильтры, чтобы показать хоть что-то.
        """
        import asyncio
        from core.intelligence.decision_trace import create_trace
        start_time = datetime.now()

        try:
            # Проверяем кэш
            cached_result = self._get_cached_analysis(symbol)
            if cached_result:
                logger.debug(f"Используем кэшированный анализ для {symbol}")
                return cached_result

            # DEV-12: Decision Trace — аудит решения
            trace = create_trace(symbol)

            # Этап 8.4.2: фиксируем единый snapshot_time для всех проверок
            snapshot_time = datetime.now()

            # Этап 8.4.3: маркер качества анализа (full|degraded|timeout)
            collect_quality = "full"

            if pre_collected_signals:
                signals = pre_collected_signals
                logger.debug("[%s] analyze_symbol: используем %d pre_collected сигналов", symbol, len(signals))
            else:
                # ── HARD timeout: сбор сигналов (Этап 8.4.3) ─────────────────
                try:
                    signals, collect_quality = await asyncio.wait_for(
                        self._collect_all_signals(symbol),
                        timeout=20.0
                    )
                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logger.error(
                        "[intelligence] %s: HARD timeout при сборе сигналов (%.1fs) — analysis_quality=timeout",
                        symbol, elapsed,
                    )
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

            # DEV-12: записываем сырые сигналы в trace
            for sig in filtered_signals:
                trace.add_signal(sig)
            trace.signal_count = len(filtered_signals)
            trace.signal_quality = collect_quality

            # Снижаем требования для популярных пар
            _sig_cfg = self.config.get("analysis", {}).get("signals", {})
            min_signals = _sig_cfg.get("min_signals", self.thresholds["min_signals"])
            top_pairs = _sig_cfg.get("premium_pairs",
                ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE', 'DOT', 'MATIC', 'AVAX'])
            single_min_strength = _sig_cfg.get("single_signal_min_strength", 50)
            symbol_base = symbol.split('/')[0] if '/' in symbol else symbol.replace('USDT', '').replace(':USDT', '')
            if symbol_base in top_pairs or manual_request:
                min_signals = 1  # Для топ-пар и ручного запроса достаточно 1 сигнала

            if len(filtered_signals) < min_signals:
                # Сильный одиночный сигнал пропускаем даже для не-топ пар
                max_strength = max((s.strength for s in filtered_signals), default=0)
                if not manual_request and symbol_base not in top_pairs and max_strength < single_min_strength:
                    trace.add_filter("min_signals", False,
                                     f"{len(filtered_signals)} < {min_signals}, max_str={max_strength}")
                    logger.warning(f"Недостаточно сигналов для {symbol}: {len(filtered_signals)} < {min_signals}, max_str={max_strength}")
                    return None
                trace.add_filter("min_signals", True, f"bypassed: top_pair={symbol_base in top_pairs} or strong={max_strength}")
            else:
                trace.add_filter("min_signals", True, f"{len(filtered_signals)} >= {min_signals}")
                
            # ── ARCH-12: MTF Context (аналитический центр) ────────────────────
            mtf_context = await self._build_mtf_context(symbol)
            if mtf_context is not None:
                # DEV-12: сохраняем pre-MTF strength для trace
                _pre_mtf = {id(s): s.strength for s in filtered_signals}
                filtered_signals = self._apply_mtf_context(filtered_signals, mtf_context)
                # DEV-12: записываем multipliers в trace
                trace.mtf_context = {
                    "direction_bias": mtf_context.direction_bias.value,
                    "bias_strength": mtf_context.bias_strength,
                    "price_zone": mtf_context.price_zone,
                    "aligned_pct": mtf_context.aligned_pct,
                    "regime": mtf_context.regime,
                }
                for sig in filtered_signals:
                    orig = _pre_mtf.get(id(sig), sig.strength)
                    if orig != sig.strength:
                        sig_type = getattr(sig.signal_type, "value", str(sig.signal_type))
                        sig_dir = getattr(sig.direction, "value", str(sig.direction))
                        dir_m = mtf_context.direction_multiplier(sig.direction)
                        zone_m = mtf_context.zone_multiplier(sig.direction)
                        comb = dir_m * 0.7 + zone_m * 0.3
                        trace.add_mtf_multiplier(sig_type, sig_dir, orig, dir_m, zone_m, comb, sig.strength)

            # ── SOFT timeout: контекст рынка (Этап 8.4.3) ────────────────────
            try:
                market_context = await asyncio.wait_for(
                    self._get_market_context(symbol),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                elapsed = (datetime.now() - start_time).total_seconds()
                # Soft timeout: деградируем, но продолжаем с fallback-контекстом
                collect_quality = "degraded"
                logger.warning(
                    "[intelligence] %s: SOFT timeout контекста (%.1fs) — analysis_quality=degraded, fallback",
                    symbol, elapsed,
                )
                fallback_price = 0.0
                try:
                    _df = await self.data_collector.get_ohlcv(symbol, get_primary_entry_tf(self.config), limit=5)
                    if _df is not None and len(_df) > 0:
                        fallback_price = float(_df["close"].iloc[-1])
                except Exception:
                    pass
                market_context = MarketContext(
                    symbol=symbol, current_price=fallback_price,
                    volume_24h=0, volume_change_24h=0, price_change_24h=0,
                )
            
            # ARCH-12: обогащаем MarketContext полем mtf_context
            if mtf_context is not None:
                market_context.mtf_context = mtf_context

            # ARCH-17: SMC Context (структура + зоны интереса)
            smc_context = None
            try:
                from core.smc import analyze_smc
                df_entry = await self.data_collector.get_ohlcv(
                    symbol, get_primary_entry_tf(self.config), limit=100,
                )
                if df_entry is not None and len(df_entry) >= 30:
                    smc_context = analyze_smc(df_entry)
                    market_context.smc_context = smc_context
            except Exception:
                logger.debug("[%s] analyze_smc failed", symbol, exc_info=True)

            # Проверяем минимальные требования к рынку
            if not self._validate_market_context(market_context):
                logger.warning(f"Рыночный контекст не подходит для анализа {symbol} (объем: {market_context.volume_24h}, цена: {market_context.current_price})")
                # Для топ-пар все равно продолжаем, даже если контекст не идеален
                if symbol_base not in top_pairs and not manual_request:
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

            # ── ARCH-09: оркестровый выбор лучшей стратегии ─────────────────
            # Priority: reversal_scanner > reversal > trend_following > legacy
            recommendation, chosen_strategy = self._pick_best_recommendation(all_recs)

            # DEV-12: записываем strategy candidates
            trace.set_strategy_candidates(all_recs)
            trace.strategy_name = chosen_strategy or ""

            if recommendation is None:
                # Legacy fallback: ни одна стратегия не дала результат
                # Проверяем min_signals (как стратегии) — не пропускаем одиночные сигналы
                if len(filtered_signals) < min_signals:
                    logger.debug("[%s] legacy fallback пропущен: %d сигналов < min_signals=%d",
                                 symbol, len(filtered_signals), min_signals)
                else:
                    logger.debug("[%s] все стратегии вернули None — legacy fallback", symbol)
                    analysis = self._analyze_signals_advanced(filtered_signals, market_context)
                    recommendation = self._generate_recommendation(
                        symbol, filtered_signals, analysis, market_context
                    )
                chosen_strategy = "legacy"

            # Тегируем рекомендацию выбранной стратегией
            if recommendation is not None:
                recommendation.metadata = recommendation.metadata or {}
                recommendation.metadata["strategy_name"] = chosen_strategy
                # Все остальные рекомендации — для раздельной регистрации в monitoring
                other_recs = {k: v for k, v in all_recs.items() if k != chosen_strategy}
                if other_recs:
                    recommendation.metadata["all_strategy_recs"] = other_recs
                if chosen_strategy != self.active_strategy_name:
                    logger.info(
                        "[%s] ARCH-09 выбрана стратегия '%s' (active='%s')",
                        symbol, chosen_strategy, self.active_strategy_name,
                    )
            
            if recommendation is None:
                return None

            # ── ARCH-20: явный арбитр направлений ────────────────────────────
            arbiter = self._select_strategy(filtered_signals, mtf_context)
            if arbiter.confidence_mult != 1.0:
                new_conf = round(recommendation.confidence * arbiter.confidence_mult, 3)
                logger.debug(
                    "[%s] ARCH-20 arbiter: dir=%s conf %.3f→%.3f mult=%.2f (%s)",
                    symbol, arbiter.direction.value,
                    recommendation.confidence, new_conf,
                    arbiter.confidence_mult, arbiter.reason,
                )
                recommendation.confidence = new_conf
            recommendation.metadata = recommendation.metadata or {}
            recommendation.metadata["strategy_arbiter"] = {
                "direction": arbiter.direction.value,
                "confidence_mult": arbiter.confidence_mult,
                "reason": arbiter.reason,
            }

            # Улучшаем анализ с помощью ML (с таймаутом)
            _pre_ml_conf = recommendation.confidence
            if self.ml_predictor:
                try:
                    recommendation = await asyncio.wait_for(
                        self._enhance_recommendation_with_ml(symbol, recommendation, market_context),
                        timeout=5.0
                    )
                    # DEV-12: записываем ML adjustment
                    if recommendation.confidence != _pre_ml_conf:
                        trace.set_ml_adjustment(
                            _pre_ml_conf,
                            recommendation.metadata.get("ml_win_prob", recommendation.confidence) if recommendation.metadata else recommendation.confidence,
                            recommendation.confidence,
                        )
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут ML анализа для {symbol}, продолжаем без ML")
                    trace.add_filter("ml_enhance", False, "timeout")
                except Exception as e:
                    logger.warning(f"Ошибка ML анализа для {symbol}: {e}, продолжаем без ML")
                    trace.add_filter("ml_enhance", False, str(e))

            # Пересчёт action после ML blend: confidence могла упасть ниже порога
            _signals_cfg = self.config.get("analysis", {}).get("signals", {}) if self.config else {}
            _global_min_conf = _signals_cfg.get("min_confidence", self.thresholds["min_confidence"])
            # DEV-26: per-signal-type порог — берём тип доминирующего сигнала (max strength)
            _by_type = _signals_cfg.get("min_confidence_by_type", {})
            _primary_type = ""
            if recommendation.supporting_signals:
                _dom = max(recommendation.supporting_signals, key=lambda s: s.strength or 0)
                _primary_type = _dom.signal_type.value if hasattr(_dom.signal_type, "value") else str(_dom.signal_type)
            _min_conf = _by_type.get(_primary_type, _global_min_conf)
            if recommendation.confidence < _min_conf:
                if recommendation.action in ("BUY", "SELL"):
                    trace.add_filter("confidence_gate", False,
                                     f"confidence={recommendation.confidence:.3f} < {_min_conf:.2f} ({_primary_type or 'global'}) → WATCH")
                    logger.info(
                        "[%s] action %s→WATCH: confidence=%.3f < %.2f (type=%s) после ML",
                        symbol, recommendation.action,
                        recommendation.confidence, _min_conf, _primary_type or "global",
                    )
                    recommendation.action = "WATCH"
            else:
                trace.add_filter("confidence_gate", True,
                                 f"confidence={recommendation.confidence:.3f} >= {_min_conf:.2f}")

            # DEV-32: блокировка контр-тренд входов (TRADER 23.03)
            # TREND_DOWN → блокировать LONG, TREND_UP → блокировать SHORT
            if (recommendation.action in ("BUY", "SELL")
                    and mtf_context is not None and mtf_context.regime):
                _rdb = (self.config.get("trading", {}).get("regime_direction_block", {})
                        if self.config else {})
                if _rdb.get("enabled", False):
                    _blocked = _rdb.get(mtf_context.regime)  # "LONG" или "SHORT"
                    _rec_dir = (recommendation.direction.value
                                if hasattr(recommendation.direction, "value")
                                else str(recommendation.direction))
                    if _blocked and _rec_dir == _blocked:
                        logger.info(
                            "[%s] DEV-32 regime_block: %s→WATCH (regime=%s блокирует %s)",
                            symbol, recommendation.action, mtf_context.regime, _blocked,
                        )
                        trace.add_filter(
                            "regime_direction_block", False,
                            f"regime={mtf_context.regime} блокирует {_blocked}",
                        )
                        recommendation.action = "WATCH"

            # DEV-33: блокировка HIGH_VOL режима (WR=0%, avg_R=-0.25)
            if (recommendation.action in ("BUY", "SELL")
                    and mtf_context is not None and mtf_context.regime):
                _blocked_regimes = (self.config.get("trading", {}).get("blocked_regimes", [])
                                    if self.config else [])
                if mtf_context.regime in _blocked_regimes:
                    logger.info(
                        "[%s] DEV-33 blocked_regime: %s→WATCH (regime=%s заблокирован)",
                        symbol, recommendation.action, mtf_context.regime,
                    )
                    trace.add_filter(
                        "blocked_regime", False,
                        f"regime={mtf_context.regime} в blocked_regimes",
                    )
                    recommendation.action = "WATCH"

            # DEV-36: Future PP score modifier (ARCH-33 спек, TRADER 23.03)
            # Модифицирует overall_strength на основе позиции цены относительно Future Daily PP.
            # LONG в PREMIUM (выше future_pp) → -10. LONG в DISCOUNT → +5.
            # SHORT — зеркально.
            _fpp_enabled = (self.config.get("trading", {}).get("future_pp_score_modifier", {}).get("enabled", False)
                            if self.config else False)
            if (_fpp_enabled
                    and recommendation.direction is not None
                    and recommendation.direction.value in ("LONG", "SHORT")):
                try:
                    from core.pivot_calculator_fixed import PivotCalculatorFixed as _PCF
                    _pc = _PCF()
                    _fdp = await _pc.get_future_daily_pivots(symbol, self.data_collector)
                    if _fdp and "PP" in _fdp:
                        _fpp = float(_fdp["PP"])
                        _price = (recommendation.entry_price
                                  or (market_context.current_price if market_context else 0))
                        _dir = recommendation.direction.value
                        _etf = get_primary_entry_tf(self.config)

                        # Порог DISCOUNT зависит от ТФ входа
                        _discount_thr = {"15m": 0.985, "1h": 0.990, "4h": 0.993}.get(_etf, 0.985)
                        _premium_thr_short = 1.015  # для SHORT premium

                        _fpp_delta = 0
                        if _dir == "LONG":
                            if _price > _fpp:
                                _fpp_delta = -10  # PREMIUM для LONG = плохо
                            elif _price < _fpp * _discount_thr:
                                _fpp_delta = +5   # DISCOUNT для LONG = хорошо
                        else:  # SHORT
                            if _price > _fpp * _premium_thr_short:
                                _fpp_delta = +5   # PREMIUM для SHORT = хорошо
                            elif _price < _fpp:
                                _fpp_delta = -10  # DISCOUNT для SHORT = плохо

                        # Weekly PP конфликт: если Weekly и Daily говорят разное → -5
                        if _fpp_delta != 0:
                            try:
                                _fwp = await _pc.get_future_weekly_pivots(symbol, self.data_collector)
                                if _fwp and "PP" in _fwp:
                                    _wpp = float(_fwp["PP"])
                                    _w_neutral = abs(_price - _wpp) / _wpp <= 0.005  # ±0.5%
                                    if not _w_neutral:
                                        # Weekly говорит LONG если price < weekly_pp, SHORT если > weekly_pp
                                        _w_dir = "LONG" if _price < _wpp else "SHORT"
                                        if _w_dir != _dir:
                                            _fpp_delta -= 5  # Weekly против → дополнительный штраф
                            except Exception:
                                pass

                        if _fpp_delta != 0:
                            _old_str = recommendation.overall_strength
                            recommendation.overall_strength = max(0, min(100, _old_str + _fpp_delta))
                            logger.info(
                                "[%s] DEV-36 FuturePP: dir=%s price=%.6f fpp=%.6f delta=%+d str %d→%d",
                                symbol, _dir, _price, _fpp, _fpp_delta,
                                _old_str, recommendation.overall_strength,
                            )
                except Exception as _e:
                    logger.debug("[%s] DEV-36 Future PP modifier: %s", symbol, _e)

            # Этап 8.4.2/8.4.3: snapshot_time + analysis_quality в метаданных
            if recommendation.metadata is None:
                recommendation.metadata = {}
            recommendation.metadata["snapshot_time"] = snapshot_time.isoformat()
            recommendation.metadata["analysis_quality"] = collect_quality
            # ARCH-12: сохраняем MTFContext для features_json
            if mtf_context is not None:
                recommendation.metadata["mtf_context"] = {
                    "direction_bias": mtf_context.direction_bias.value,
                    "bias_strength": mtf_context.bias_strength,
                    "price_zone": mtf_context.price_zone,
                    "aligned_pct": mtf_context.aligned_pct,
                    "senior_matches": mtf_context.senior_matches,
                    "wt_spreads": mtf_context.wt_spreads,
                    "regime": mtf_context.regime,
                    "bull_pct": mtf_context.bull_pct,
                    "bear_pct": mtf_context.bear_pct,
                    "senior_reversal": mtf_context.senior_reversal,
                }
            # ARCH-17: сохраняем SMCContext для features_json
            if smc_context is not None:
                recommendation.metadata["smc_context"] = smc_context.to_features()
            if collect_quality != "full":
                logger.info(
                    "[intelligence] %s: рекомендация с analysis_quality=%s",
                    symbol, collect_quality,
                )

            # DEV-12: финализируем trace и записываем в metadata
            trace.set_final(
                action=recommendation.action,
                confidence=recommendation.confidence,
                strength=recommendation.overall_strength,
                direction=getattr(recommendation.direction, "value", str(recommendation.direction)),
            )
            trace.regime = getattr(mtf_context, "regime", "") or "" if mtf_context else ""
            recommendation.metadata["decision_trace"] = trace.to_dict()
            logger.debug("[decision_trace] %s", trace.summary())

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
    
    async def _collect_all_signals(
        self, symbol: str
    ) -> tuple[Optional[List[SignalData]], str]:
        """
        Собирает все доступные сигналы для символа.

        Returns
        -------
        (signals_or_none, analysis_quality)

        signals_or_none:
          - List[SignalData] — сигналы (может быть пустым)
          - None — критичная ошибка загрузки данных (hard block, Этап 8.4.2)

        analysis_quality: "full" | "degraded"
          - "full"     — все 6 детекторов завершились без ошибок
          - "degraded" — один или несколько детекторов бросили исключение,
                         но хотя бы часть сигналов собрана (soft fallback, Этап 8.4.3)
        """
        _TOTAL_CHECKERS = 5  # DEV-31: было 6, убран check_mtf_signals
        signals: List[SignalData] = []
        quality = "full"
        try:
            t0 = asyncio.get_event_loop().time()

            # ── HARD: параллельная загрузка OHLCV (критичный шаг) ─────────────
            df_1h, df_15m, df_3m = await asyncio.gather(
                self.data_collector.get_ohlcv(symbol, "1h", limit=100),
                self.data_collector.get_ohlcv(symbol, get_primary_entry_tf(self.config), limit=100),
                self.data_collector.get_ohlcv(symbol, "3m", limit=100),
            )
            t1 = asyncio.get_event_loop().time()
            logger.debug("[%s] OHLCV fetch: %.2fs", symbol, t1 - t0)

            # Этап 8.4.2: нет данных = hard block (no silent fallback)
            if df_1h is None or df_1h.empty:
                logger.info("[intelligence] %s: 1h OHLCV недоступен — пропуск (data error)", symbol)
                return None, "full"  # quality неважен — None остановит анализ

            # Проверка качества 15m-данных (свежесть + NaN)
            if df_15m is not None and not df_15m.empty:
                ok, reason = check_ohlcv_quality(
                    df_15m, timeframe=get_primary_entry_tf(self.config),
                    min_bars=50,
                    symbol=symbol,
                )
                if not ok:
                    logger.info("[intelligence] %s: пропуск из-за качества данных: %s", symbol, reason)
                    return None, "full"

            # ── Regime: определяем режим рынка для mtf_bias ──────────────────
            _regime: Optional[str] = None
            try:
                from core.market_regime import MarketRegimeClassifier
                _regime = MarketRegimeClassifier().classify_from_dataframes(df_15m, df_1h)
            except Exception:
                logger.debug("[%s] MarketRegime: не удалось определить", symbol)

            # ── SOFT: параллельный запуск детекторов (Этап 8.4.3) ─────────────
            # return_exceptions=True: отдельный детектор не ломает остальных
            # MTF_BIAS — главное WT-ядро (7 TF, alignment score, senior gate)
            results = await asyncio.gather(
                check_anomaly_signals(symbol, df_15m),
                check_wt_signals(symbol, df_15m),
                check_trend_signals(symbol, df_1h),
                check_mtf_bias_signal(symbol, self.data_collector, regime=_regime, cfg=self.config),
                check_wt_b_signals(symbol, df_1h),
                return_exceptions=True,
            )
            t2 = asyncio.get_event_loop().time()
            logger.debug("[%s] signal checks: %.2fs | total: %.2fs", symbol, t2 - t1, t2 - t0)

            failed = 0
            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                    logger.debug("[%s] signal check error: %s", symbol, r)
                elif r:
                    signals.extend(r)

            if failed > 0:
                quality = "degraded"
                logger.info(
                    "[intelligence] %s: analysis_quality=degraded (%d/%d детекторов упали)",
                    symbol, failed, _TOTAL_CHECKERS,
                )
        except Exception as e:
            logger.exception("Ошибка сбора сигналов для %s: %s", symbol, e)
        return signals, quality
    
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
    
    async def _build_mtf_context(self, symbol: str) -> Optional[MTFContext]:
        """
        ARCH-12: Строит MTFContext для символа.
        Данные из кешированного collect_mtf_data + weekly_pivots + regime.
        """
        try:
            from core.mtf_checker import collect_mtf_data
            from core.mtf_interpreter import analyze_context

            snapshot = await collect_mtf_data(symbol, self.data_collector)
            if not snapshot:
                return None

            # Текущая цена из snapshot (15m или 1h)
            current_price = 0.0
            try:
                _df = await self.data_collector.get_ohlcv(symbol, get_primary_entry_tf(self.config), limit=5)
                if _df is not None and len(_df) > 0:
                    current_price = float(_df["close"].iloc[-1])
            except Exception:
                pass

            # Weekly pivots из кеша
            weekly_pivots = None
            try:
                from core.pivot_calculator_fixed import PivotCalculatorFixed
                pc = PivotCalculatorFixed()
                weekly_pivots = await pc.get_weekly_pivots(symbol, self.data_collector)
            except Exception:
                logger.debug("[%s] weekly pivots для MTFContext недоступны", symbol)

            # Regime
            _regime: Optional[str] = None
            try:
                from core.market_regime import MarketRegimeClassifier
                df_15m = await self.data_collector.get_ohlcv(symbol, get_primary_entry_tf(self.config), limit=100)
                df_1h = await self.data_collector.get_ohlcv(symbol, "1h", limit=100)
                _regime = MarketRegimeClassifier().classify_from_dataframes(df_15m, df_1h)
            except Exception:
                pass

            ctx = analyze_context(
                snapshot=snapshot,
                current_price=current_price,
                weekly_pivots=weekly_pivots,
                regime=_regime,
            )

            # ARCH-12.5: подгружаем калиброванные параметры
            if hasattr(self, '_auto_calibrator') and self._auto_calibrator is not None:
                ctx.calibration_params = self._auto_calibrator.get_params()

            return ctx

        except Exception:
            logger.debug("[%s] _build_mtf_context failed", symbol, exc_info=True)
            return None

    @staticmethod
    def _apply_mtf_context(
        signals: List[SignalData], ctx: MTFContext
    ) -> List[SignalData]:
        """
        ARCH-12: Применяет MTFContext к сигналам — адаптивные множители strength.

        Принцип: адаптивные веса, НЕ жёсткие блоки.
        Сигнал ПРОТИВ bias ослабляется, но не запрещается.
        Разворот от R5 (zone=1.0) при SHORT должен пройти.
        """
        for signal in signals:
            original = signal.strength

            # Множитель по направлению bias
            dir_mult = ctx.direction_multiplier(signal.direction)

            # ARCH-19: дифференцированный penalty для контр-трендовых сигналов.
            # Вместо единого floor (≈0.3-0.4) — три уровня в зависимости от качества сигнала.
            if dir_mult < 1.0:
                score = signal.data.get("score", 0) if signal.data else 0
                has_div = any(
                    f in (signal.data.get("factors") or [])
                    for f in ("WT_DIVERGENCE", "WT_HIDDEN_DIV")
                )
                if signal.signal_type == SignalType.PIVOT_REVERSAL and score >= 65:
                    dir_mult = 1.0   # senior_reversal — без penalty
                elif has_div and score >= 65:
                    dir_mult = 0.75  # div + качество — умеренное снижение
                else:
                    dir_mult = 0.40  # шум — текущее поведение

            # Множитель по ценовой зоне (пивоты)
            zone_mult = ctx.zone_multiplier(signal.direction)

            # Комбинированный множитель (веса из калибровки или defaults)
            cp = ctx.calibration_params or {}
            dw = cp.get("dir_weight", 0.7)
            zw = cp.get("zone_weight", 0.3)
            combined = dir_mult * dw + zone_mult * zw

            # CONFLUENCE — агрегированный сигнал, MTF bias уже частично учтён внутри score.
            # Мягкий penalty: максимум -25%, чтобы сильные (80+) проходили, слабые (60) отсеивались.
            if signal.signal_type == SignalType.CONFLUENCE:
                combined = max(0.75, combined)

            new_strength = max(0, min(100, int(round(signal.strength * combined))))
            signal.strength = new_strength

            # Пересчёт confidence
            signal.confidence = round(new_strength / 100.0, 2)

            if abs(new_strength - original) >= 5:
                logger.debug(
                    "[mtf_context] %s %s %s: strength %d→%d (dir=%.2f zone=%.2f comb=%.2f)",
                    signal.symbol, signal.signal_type.value, signal.direction.value,
                    original, new_strength, dir_mult, zone_mult, combined,
                )

        return signals

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
                df_15m = await self.data_collector.get_ohlcv(normalized_symbol, get_primary_entry_tf(self.config), limit=60)
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
    


