"""
Trading Intelligence Layer - система объединения и анализа сигналов
Объединяет все типы сигналов в комплексные торговые рекомендации
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Tuple, Any
import pandas as pd
import numpy as np

# Модели данных
from core.signals.signal_models import (
    SignalType, SignalDirection, SignalStrength,
    SignalData, MarketContext, TradingRecommendation, MTFContext,
)

# Проверки сигналов
from core.signals.signal_checkers import (
    check_anomaly_signals, check_wt_signals,
    check_trend_signals, check_mtf_bias_signal, check_wt_b_signals,
)

# Форматтер рекомендаций
from core.ui.intelligence_formatter import format_intelligence_message  # noqa: F401 — re-export
from core.infra.data_quality import check_ohlcv_quality
from core.infra.entry_config import get_primary_entry_tf

# Strategy Pattern
try:
    from strategies import get_strategy, list_strategies
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False

try:
    from core.indicators.indicators import calculate_trend, calculate_wt, get_zone, detect_fvg, compute_atr, compute_volatility
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
    from core.ml.ml_predictor import MLPredictor, MLPrediction, PredictionType
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

    def __init__(self, data_collector, config: Dict = None, db_path: str = "subscriptions.db",
                 pivot_calculator=None):
        self.data_collector = data_collector
        self.config = config or {}
        self._db_path = db_path
        # ARCH-38 / DEV-45: Singleton — один инстанс на весь цикл, кеш живёт с db_path
        # Если передан внешний инстанс (bot.pivot_calculator) — используем его кеш (DEV-45 fix)
        from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed as _PCF_cls
        self._pivot_calc_shared: _PCF_cls = pivot_calculator or _PCF_cls(db_path=db_path)

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
                from core.ml.outcome_predictor import OutcomePredictor
                op = OutcomePredictor()
                # ARCH-21: скользящее окно из конфига (None = вся история)
                _tw = (config.get("outcome_predictor.training_window") if config else None)
                op.fit(db_path, training_window=_tw)
                self.outcome_predictor = op
                logger.info("OutcomePredictor: %s", op.info())
            except Exception as e:
                logger.warning("OutcomePredictor не инициализирован: %s", e)

        # DEV-138: MTF WT Specialist (shadow mode)
        self._wt_specialist = None
        # DEV-139: MTF SMC Specialist (shadow mode)
        self._smc_specialist = None
        try:
            from core.ml.mtf_wt_specialist import MTFWTSpecialist
            spec = MTFWTSpecialist()
            spec.fit(db_path)
            self._wt_specialist = spec
            logger.info("MTFWTSpecialist: %s", spec.info())
        except Exception as _e:
            logger.warning("MTFWTSpecialist не инициализирован: %s", _e)

        try:
            from core.ml.mtf_smc_specialist import MTFSMCSpecialist
            smc_spec = MTFSMCSpecialist()
            smc_spec.fit(db_path)
            self._smc_specialist = smc_spec
            logger.info("MTFSMCSpecialist: %s", smc_spec.info())
        except Exception as _e:
            logger.warning("MTFSMCSpecialist не инициализирован: %s", _e)

        # ARCH-12.5: AutoCalibrator — rule-based калибровка MTF multipliers
        self._auto_calibrator = None
        try:
            from core.ml.auto_calibrator import AutoCalibrator
            self._auto_calibrator = AutoCalibrator(db_path=db_path)
            logger.info("AutoCalibrator: загружен (%s)", self._auto_calibrator.calibration_path)
        except Exception as e:
            logger.warning("AutoCalibrator не инициализирован: %s", e)

        # Strategy Pattern: инициализируем все активные стратегии
        self.strategy = None           # основная (для TG-сигналов)
        self.strategies: Dict[str, Any] = {}  # все активные стратегии
        self.active_strategy_name: str = "multi_signal"
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

        DEV-177: по умолчанию — EMA по хронологии (half-life 50 сделок, data_era='post_fix').
        Старый режим (full-history AVG) доступен через ``trading.adaptive_weights.method=full_history``.
        Параллельно логируется второй режим для shadow-сравнения.
        Минимум 20 закрытых сделок на тип (в отфильтрованной выборке) — иначе вес не меняется.
        """
        _MIN_TRADES = 20
        db = db_path or self._db_path
        _map = {
            "pivot_reversal": SignalType.PIVOT_REVERSAL,
            "trend_signal":   SignalType.TREND_SIGNAL,
            "wt_signal":      SignalType.WT_SIGNAL,
            "wt_b_signal":    SignalType.WT_B_SIGNAL,
            "anomaly":        SignalType.ANOMALY,
            "divergence":     SignalType.DIVERGENCE,
            "mtf_bias":       SignalType.MTF_BIAS,
        }
        # DEV-177: параметры из config
        try:
            from core.infra.config_loader import config as _cfg
            _aw = ((_cfg.get("trading") or {}).get("adaptive_weights") or {})
        except Exception:
            _aw = {}
        _method = str(_aw.get("method", "ema")).lower()
        _hl = float(_aw.get("half_life", 50))
        _era = _aw.get("data_era_filter", "post_fix")
        _hist_enabled = bool(_aw.get("history_log_enabled", True))
        _hist_interval_min = float(_aw.get("history_log_interval_min", 60))

        try:
            from core.trading.performance_engine import PerformanceEngine
            pe = PerformanceEngine(db)
            rows_ema = pe.by_signal_type_ema(half_life=_hl, data_era=_era)
            rows_full = pe.by_signal_type()

            # Основной источник по конфигу; shadow — второй для сравнения в логе
            rows = rows_ema if _method == "ema" else rows_full
            by_full: Dict[str, Dict[str, Any]] = {r["signal_type"]: r for r in rows_full}
            by_ema: Dict[str, Dict[str, Any]] = {r["signal_type"]: r for r in rows_ema}

            changed = []
            snapshots: List[Dict[str, Any]] = []
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

                # Параллельное значение (shadow) — EMA если method=full_history, иначе full-history
                _other_row = (by_full if _method == "ema" else by_ema).get(row["signal_type"], {}) or {}
                _other_r = _other_row.get("avg_r")
                _other_n = (_other_row.get("wins") or 0) + (_other_row.get("losses") or 0)
                _other_label = "full" if _method == "ema" else "EMA"
                _main_label = "EMA" if _method == "ema" else "full"

                if abs(new_w - old_w) > 0.001:
                    _shadow_part = (
                        f" vs {_other_label} avg_R={_other_r:+.2f} (n={_other_n})"
                        if _other_r is not None else ""
                    )
                    changed.append(
                        f"{row['signal_type']}: {old_w:.3f}→{new_w:.3f} | "
                        f"{_main_label} avg_R={avg_r:+.2f} (n={closed}){_shadow_part}"
                    )

                snapshots.append({
                    "signal_type": row["signal_type"],
                    "ema_avg_r": (by_ema.get(row["signal_type"], {}) or {}).get("avg_r"),
                    "full_avg_r": (by_full.get(row["signal_type"], {}) or {}).get("avg_r"),
                    "adapted_weight": new_w,
                    "base_weight": base,
                    "n_trades": closed,
                })

            if changed:
                logger.info(
                    "Adaptive weights (method=%s hl=%g era=%s): %s",
                    _method, _hl, _era, " | ".join(changed),
                )
            else:
                logger.debug(
                    "Adaptive weights (method=%s): нет изменений (мало данных или малая дельта)",
                    _method,
                )

            # DEV-177: запись snapshot в signal_weights_history (не чаще раз в час)
            if _hist_enabled and snapshots:
                try:
                    self._log_weights_history(
                        db, snapshots, method=_method, half_life=_hl,
                        min_interval_min=_hist_interval_min,
                    )
                except Exception as e:
                    logger.debug("signal_weights_history write skipped: %s", e)
        except Exception as e:
            logger.warning("update_signal_weights: %s", e)

    @staticmethod
    def _log_weights_history(
        db_path: str,
        snapshots: List[Dict[str, Any]],
        method: str,
        half_life: float,
        min_interval_min: float = 60.0,
    ) -> None:
        """DEV-177: запись снэпшота адаптивных весов в signal_weights_history.

        Пишем не чаще чем раз в ``min_interval_min`` минут (от последней записи).
        """
        import sqlite3 as _sql
        with _sql.connect(db_path, timeout=30) as conn:
            cur = conn.cursor()
            # Таблица должна существовать (создаётся в subscription_manager); на всякий случай
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signal_weights_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_type TEXT NOT NULL,
                    ema_avg_r REAL,
                    full_avg_r REAL,
                    adapted_weight REAL,
                    base_weight REAL,
                    n_trades INTEGER,
                    half_life REAL,
                    method TEXT,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Throttle по последней записи
            row = cur.execute(
                "SELECT MAX(computed_at) FROM signal_weights_history"
            ).fetchone()
            last_at = row[0] if row else None
            if last_at:
                try:
                    delta = cur.execute(
                        "SELECT (julianday('now') - julianday(?)) * 24 * 60",
                        (last_at,),
                    ).fetchone()[0]
                    if delta is not None and delta < min_interval_min:
                        return
                except Exception:
                    pass
            cur.executemany(
                """INSERT INTO signal_weights_history
                   (signal_type, ema_avg_r, full_avg_r, adapted_weight,
                    base_weight, n_trades, half_life, method)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        s["signal_type"],
                        s.get("ema_avg_r"),
                        s.get("full_avg_r"),
                        s.get("adapted_weight"),
                        s.get("base_weight"),
                        s.get("n_trades"),
                        half_life,
                        method,
                    )
                    for s in snapshots
                ],
            )
            conn.commit()

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
    # wt_entry УДАЛЕНА 18.04.2026 (ARCH-83): WR=4.7% post-15.04, деградация подтверждена
    _STRATEGY_PRIORITY = [
        "reversal",        # качественный разворот (1 сигнал без count-penalty)
        "trend_following", # несколько трендовых подтверждений
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

        # Priority-1: reversal / trend_following — max by overall_strength
        # (wt_entry удалена ARCH-83: WR=4.7% post-15.04)
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
        
    async def analyze_symbol(self, symbol: str, pre_collected_signals=None, manual_request: bool = False,
                             pre_fetched_dfs: Optional[Dict[str, Any]] = None,
                             extra_pre_signals=None) -> Optional[TradingRecommendation]:
        """
        Комплексный анализ символа и генерация рекомендации.
        pre_collected_signals — если переданы, пропускает _collect_all_signals (экономит API-вызовы).
        extra_pre_signals     — дополнительные сигналы (напр. дивергенции из Full CALL),
                                добавляются ПОСЛЕ _collect_all_signals (не заменяют его).
        manual_request — ручной запрос пользователя: смягчаем фильтры, чтобы показать хоть что-то.
        """
        import asyncio
        from core.intelligence.decision_trace import create_trace
        start_time = datetime.now()

        try:
            # Проверяем кэш — manual_request всегда получает свежий анализ
            if not manual_request:
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
                # ARCH-71: даже при None — если есть extra_pre_signals (div от Full CALL), продолжаем
                if extra_pre_signals:
                    signals = []
                else:
                    logger.info("[intelligence] %s: данные недоступны — анализ пропущен", symbol)
                    return None

            # ARCH-71: Inject дополнительных сигналов от Full CALL ДО проверки min_signals
            if extra_pre_signals:
                signals = list(signals or []) + list(extra_pre_signals)
                logger.info("[%s] analyze_symbol: +%d extra_pre_signals (итого %d)",
                            symbol, len(extra_pre_signals), len(signals))

            if not signals:
                if not manual_request:
                    logger.warning(f"Не найдено сигналов для {symbol} (pre_collected={bool(pre_collected_signals)})")
                    return None
                logger.info(f"[manual] {symbol}: нет сигналов, но запрос ручной — показываем рыночный контекст")
                signals = []

            # Фильтруем сигналы по качеству
            filtered_signals = self._filter_signals_by_quality(signals)

            # DEV-55 / ARCH-46: PIVOT_TOUCH staleness penalty
            # Если касание пивота было давно (> staleness_bars баров) — снижаем strength сигнала.
            _pts_cfg = (self.config.get("trading", {}) or {}).get("pivot_touch_staleness", {})
            if _pts_cfg.get("enabled"):
                _pts_bars = int(_pts_cfg.get("staleness_bars", 5))
                _pts_penalty = int(_pts_cfg.get("score_penalty", -10))
                for _sig55 in filtered_signals:
                    _factors = (_sig55.data.get("factors") or []) if _sig55.data else []
                    if "PIVOT_TOUCH" in _factors:
                        _bars_ago = _sig55.data.get("pivot_bars_ago", 0) if _sig55.data else 0
                        if _bars_ago > _pts_bars:
                            _old_str = _sig55.strength
                            _sig55.strength = max(0, _sig55.strength + _pts_penalty)
                            logger.info(
                                "[%s] DEV-55 PIVOT_TOUCH stale: %d баров (penalty %d) str %d→%d",
                                symbol, _bars_ago, _pts_penalty, _old_str, _sig55.strength,
                            )

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
            try:
                mtf_context = await asyncio.wait_for(
                    self._build_mtf_context(symbol),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                _mtf_elapsed = (datetime.now() - start_time).total_seconds()
                logger.warning(
                    "[intelligence] %s: timeout _build_mtf_context (%.1fs) — mtf_context=None",
                    symbol, _mtf_elapsed,
                )
                mtf_context = None
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

                # ARCH-56 Phase B: shadow-mode лог фазы/паттерна/avoid_reason
                _ar = mtf_context.avoid_reason
                logger.info(
                    "[phase56] %s phase=%s zone=%s pattern=%s(%.2f) avoid=%s",
                    symbol,
                    mtf_context.phase,
                    mtf_context.zone_state,
                    mtf_context.pattern_name,
                    mtf_context.pattern_confidence,
                    _ar or "—",
                )

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
                # ARCH-55: сохраняем режим чтобы calculate_levels() мог выбрать RANGE BOUNCE
                market_context.regime = getattr(mtf_context, "regime", "") or ""

            # ARCH-55: RANGE BOUNCE — загружаем пивоты если режим RANGE и фича включена
            # ARCH-113: также загружаем если tp_selector_enabled (нужны PDH/PWH для TPSelector)
            try:
                _rb_cfg = (self.config or {}).get("trading", {}).get("range_bounce", {})
                _sl_tp_cfg = (self.config or {}).get("sl_tp_engine", {})
                _tp_sel_enabled = _sl_tp_cfg.get("tp_selector_enabled", False)
                _tp_sel_shadow  = _sl_tp_cfg.get("tp_selector_shadow", False)
                _need_pivots = (
                    (_rb_cfg.get("enabled", False) and market_context.regime == "RANGE")
                    or _tp_sel_enabled
                    or _tp_sel_shadow
                )
                if _need_pivots and self.data_collector is not None:
                    _pcf = self._pivot_calc_shared
                    _1d = await _pcf.get_daily_pivots(symbol, self.data_collector) or {}
                    _1w = await _pcf.get_weekly_pivots(symbol, self.data_collector) or {}
                    market_context.pivot_cache_1d_1w = {
                        f"{symbol}_1D": _1d,
                        f"{symbol}_1W": _1w,
                    }
                    logger.debug("[ARCH-55/113] %s pivot_cache загружен (regime=%s tp_sel=%s shadow=%s): 1D=%d 1W=%d уровней",
                                 symbol, market_context.regime, _tp_sel_enabled, _tp_sel_shadow, len(_1d), len(_1w))
            except Exception as _e55:
                logger.debug("[ARCH-55] pivot_cache load failed: %s", _e55)

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

            # ARCH-122: богатый multi-TF SMC snap из Bus (SMC Sub-куб) → market_context.
            # TPSelector._collect_magnets читает его для OB/multi-TF-FVG/EQH-EQL/Fib магнитов.
            try:
                _pcb = getattr(self, "_pair_context_bus", None)
                if _pcb is not None:
                    _st = _pcb.get(symbol)
                    _bus_snap = getattr(_st, "smc_snap", None) if _st else None
                    if _bus_snap:
                        market_context.smc_snap = _bus_snap
            except Exception:
                logger.debug("[%s] smc_snap inject failed", symbol, exc_info=True)

            # ARCH-51 + ARCH-53: единый MTF блок
            # Приоритет: pre_fetched_dfs (переданы из scan_one — уже загружены и wt рассчитан)
            #            → fallback: fetch через data_collector (ручной /intelligence запрос)
            # Нет повторных API-вызовов, нет повторного calculate_wt.
            try:
                from core.smc import analyze_smc as _smc_analyze
                from core.smc.models import build_mtf_smc_snapshot
                from core.signals.ote_detector import detect_ote_signal
                _cur_price    = market_context.current_price
                _entry_tf     = get_primary_entry_tf(self.config)
                _ote_shadow   = (self.config or {}).get("signal_quality", {}).get("ote_shadow_mode", True)
                _ote_zone_tfs = (self.config or {}).get("signal_quality", {}).get(
                    "ote_zone_tfs", ["1h", "4h", "1d"]
                )
                # Скальп OTE: 15m zone → 3m trigger (ICT-правильный pipeline)
                _scalp_zone_tfs   = (self.config or {}).get("signal_quality", {}).get(
                    "ote_scalp_zone_tfs", ["15m"]
                )
                _scalp_trigger_tf = (self.config or {}).get("signal_quality", {}).get(
                    "ote_scalp_trigger_tf", "3m"
                )
                # 04.05.2026: откат к wide-only [0.705–0.786] + ATR-trend gate включён
                # C4 бэктест (0.5, no-gates): WR=23.7%, −588R/90дн → ОТКАЗ
                _ote_zone_min_fib = (self.config or {}).get("signal_quality", {}).get(
                    "ote_zone_min_fib", 0.705
                )
                _ote_use_trend_gate = (self.config or {}).get("signal_quality", {}).get(
                    "ote_use_trend_gate", True
                )
                _arch51_fields = {"4h": "smc_h4", "1d": "smc_d1"}
                _pdfs = pre_fetched_dfs or {}  # уже загруженные df из scan_one

                async def _get_df(tf: str, limit: int = 100):
                    """Берёт df из pre_fetched_dfs или фетчит (fallback для /intelligence)."""
                    df = _pdfs.get(tf)
                    if df is not None and len(df) >= 10:
                        return df
                    return await self.data_collector.get_ohlcv(symbol, tf, limit=limit)

                # ── Swing/Position OTE zones: 1h/4h/1d ──────────────────────
                _smc_contexts: dict = {}
                for _ztf in _ote_zone_tfs:
                    try:
                        _df_ztf = await _get_df(_ztf)
                        if _df_ztf is None or len(_df_ztf) < 30:
                            continue
                        _ctx_ztf = _smc_analyze(_df_ztf)
                        _smc_contexts[_ztf] = _ctx_ztf
                        if _ztf in _arch51_fields and mtf_context is not None:
                            snap = build_mtf_smc_snapshot(_ctx_ztf, _cur_price)
                            setattr(mtf_context, _arch51_fields[_ztf], snap)
                    except Exception:
                        logger.debug("[%s] MTF SMC %s failed", symbol, _ztf, exc_info=True)

                # OTE swing сигнал: zone=1h/4h/1d → trigger=15m
                if _smc_contexts and df_entry is not None:
                    if "cross_up" not in df_entry.columns:
                        from core.indicators.indicators import calculate_wt
                        df_entry = calculate_wt(df_entry)
                    ote_sig = detect_ote_signal(
                        df_trigger=df_entry,
                        symbol=symbol,
                        smc_contexts=_smc_contexts,
                        trigger_tf=_entry_tf,
                        shadow_mode=_ote_shadow,
                        ote_zone_min_fib=_ote_zone_min_fib,
                        df_trend_ref=_pdfs.get("1h") if _ote_use_trend_gate else None,
                    )
                    if ote_sig is not None:
                        filtered_signals.append(ote_sig)

                # ── Scalp OTE: zone=15m → trigger=3m (ICT) ──────────────────
                # 15m SMC уже вычислен выше как smc_context — переиспользуем
                _scalp_smc_contexts: dict = {}
                if smc_context is not None and "15m" in _scalp_zone_tfs:
                    _scalp_smc_contexts["15m"] = smc_context

                _df_scalp_trigger = await _get_df(_scalp_trigger_tf)
                if _scalp_smc_contexts and _df_scalp_trigger is not None and len(_df_scalp_trigger) >= 30:
                    if "cross_up" not in _df_scalp_trigger.columns:
                        from core.indicators.indicators import calculate_wt
                        _df_scalp_trigger = calculate_wt(_df_scalp_trigger)
                    ote_scalp_sig = detect_ote_signal(
                        df_trigger=_df_scalp_trigger,
                        symbol=symbol,
                        smc_contexts=_scalp_smc_contexts,
                        trigger_tf=_scalp_trigger_tf,
                        shadow_mode=_ote_shadow,
                        ote_zone_min_fib=_ote_zone_min_fib,
                    )
                    if ote_scalp_sig is not None:
                        filtered_signals.append(ote_scalp_sig)

            except Exception:
                logger.debug("[%s] ARCH-51+53 MTF block failed", symbol, exc_info=True)

            # Проверяем минимальные требования к рынку
            if not self._validate_market_context(market_context):
                logger.warning(f"Рыночный контекст не подходит для анализа {symbol} (объем: {market_context.volume_24h}, цена: {market_context.current_price})")
                # Для топ-пар все равно продолжаем, даже если контекст не идеален
                if symbol_base not in top_pairs and not manual_request:
                    return None

            # DEV-41: wt_signal + NEAR_PIVOT → strength +20
            # wt_signal у пивота статистически avg_R=+1.27 vs +0.32 без пивота (ARCH-23)
            _daily_pivots_41: Optional[Dict] = None
            _weekly_pivots_41: Dict = {}
            for _sig41 in filtered_signals:
                if getattr(_sig41.signal_type, "value", str(_sig41.signal_type)) != "wt_signal":
                    continue
                # Ленивый fetch (PivotCalculatorFixed кеширует — нет лишних API-запросов)
                if _daily_pivots_41 is None:
                    try:
                        _pcf41 = self._pivot_calc_shared
                        _daily_pivots_41 = await _pcf41.get_daily_pivots(symbol, self.data_collector) or {}
                        _weekly_pivots_41 = await _pcf41.get_weekly_pivots(symbol, self.data_collector) or {}
                    except Exception:
                        _daily_pivots_41 = {}
                # Объединяем 1D + 1W уровни
                _all_levels_41 = dict(_daily_pivots_41)
                _all_levels_41.update({f"1W_{k}": v for k, v in _weekly_pivots_41.items()})
                if not _all_levels_41:
                    continue
                # Ищем ближайший уровень в ±1%
                _price41 = (market_context.current_price if market_context else 0) or _sig41.data.get("price", 0)
                _nearest_name, _nearest_dist = None, float("inf")
                for _lvl_name, _lvl_price in _all_levels_41.items():
                    try:
                        if _lvl_price and float(_lvl_price) > 0:
                            _d = abs(_price41 - float(_lvl_price)) / float(_lvl_price) * 100
                            if _d < _nearest_dist:
                                _nearest_dist, _nearest_name = _d, _lvl_name
                    except Exception:
                        pass
                if _nearest_dist > 1.0:
                    continue  # не у пивота — не буcтим
                # Защита от дублирования с confluence / wt_b_signal
                _st_vals_41 = {getattr(s.signal_type, "value", str(s.signal_type)) for s in filtered_signals}
                if _st_vals_41 & {"confluence", "wt_b_signal"}:
                    continue
                # Буст +20
                _old_str41 = _sig41.strength
                _sig41.strength = min(100, _sig41.strength + 20)
                if _sig41.data is None:
                    _sig41.data = {}
                _sig41.data["near_pivot"] = _nearest_name
                _sig41.data["near_pivot_dist_pct"] = round(_nearest_dist, 3)
                logger.info("[DEV-41] %s wt_signal NEAR_PIVOT=%s (%.2f%%), str %d→%d",
                            symbol, _nearest_name, _nearest_dist, _old_str41, _sig41.strength)

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
                # DEV-149: bypass для сильных одиночных сигналов (аналогично строке 569)
                _max_str_legacy = max((s.strength for s in filtered_signals), default=0)
                _bypass_legacy = _max_str_legacy >= single_min_strength or symbol_base in top_pairs
                if len(filtered_signals) < min_signals and not manual_request and not _bypass_legacy:
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
                # ARCH-95 H1: detector_price — цена close бара при детекции (shadow)
                if market_context and getattr(market_context, "current_price", 0) > 0:
                    recommendation.metadata["detector_price"] = market_context.current_price
                # Все остальные рекомендации — для раздельной регистрации в monitoring
                other_recs = {k: v for k, v in all_recs.items() if k != chosen_strategy}
                if other_recs:
                    recommendation.metadata["all_strategy_recs"] = other_recs
                if chosen_strategy != self.active_strategy_name and chosen_strategy != "legacy":
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

            # DEV-137: Reversal Mode — записываем в metadata
            if mtf_context is not None and mtf_context.reversal_mode is not None:
                recommendation.metadata["reversal_mode"] = mtf_context.reversal_mode
                logger.info(
                    "[%s][DEV-137] reversal_mode=%s",
                    symbol, mtf_context.reversal_mode,
                )

            # DEV-149: Reversal Boost — если mode=REVERSAL + WT 4h в OB/OS + реверсивный сигнал
            # → strength +8 и флаг для обхода regime_direction_block (чтобы не проспать разворот рынка).
            try:
                _rm_val = (recommendation.metadata or {}).get("reversal_mode")
                _sig_t  = (getattr(recommendation, "signal_type", "") or "").lower()
                _dir_v  = (recommendation.direction.value
                           if hasattr(recommendation.direction, "value")
                           else str(recommendation.direction))
                _rev_types = ("pivot_reversal", "confluence", "watch_list_breach", "wl_breach")
                if (_rm_val == "REVERSAL"
                        and _sig_t in _rev_types
                        and mtf_context is not None
                        and getattr(mtf_context, "wt_snap", None)):
                    _wt4h = float((mtf_context.wt_snap.get("4h") or {}).get("wt1", 0.0))
                    _zone_ok = (
                        (_dir_v == "LONG"  and _wt4h < -60) or
                        (_dir_v == "SHORT" and _wt4h >  60)
                    )
                    if _zone_ok:
                        _old_s = float(getattr(recommendation, "overall_strength", 0) or 0)
                        recommendation.overall_strength = round(min(100.0, _old_s + 8.0), 1)
                        recommendation.metadata["reversal_boost"] = {
                            "wt_4h": round(_wt4h, 1),
                            "strength_delta": 8.0,
                            "old_strength": _old_s,
                        }
                        logger.info(
                            "[%s][DEV-149] REVERSAL-BOOST %s sig=%s wt_4h=%.1f strength %.0f→%.0f",
                            symbol, _dir_v, _sig_t, _wt4h, _old_s, recommendation.overall_strength,
                        )
            except Exception as _e_rb:
                logger.debug("[DEV-149] reversal_boost error: %s", _e_rb)

            # DEV-139: MTF SMC Specialist shadow — predict + запись в metadata
            if mtf_context is not None and getattr(mtf_context, "smc_snap", None):
                recommendation.metadata["smc_snap"] = mtf_context.smc_snap
                try:
                    _smc_verdict = self._smc_specialist.predict(mtf_context.smc_snap) if self._smc_specialist else None
                    if _smc_verdict is not None:
                        recommendation.metadata["smc_verdict"] = {
                            "label": _smc_verdict.label,
                            "confidence": round(_smc_verdict.confidence, 3),
                        }
                        logger.debug(
                            "[%s][DEV-139] smc_verdict=%s conf=%.3f",
                            symbol, _smc_verdict.label, _smc_verdict.confidence,
                        )
                except Exception as _e:
                    logger.debug("[DEV-139] smc_specialist.predict error: %s", _e)

            # DEV-161: rule-based WT verdict (заменяет ML predict — AUC=0.49 был < случайного)
            if mtf_context is not None and mtf_context.wt_snap:
                recommendation.metadata["wt_snap"] = mtf_context.wt_snap
                try:
                    from core.intelligence.wt_specialist import derive_wt_verdict as _derive_wt_verdict
                    _wt_label = _derive_wt_verdict(mtf_context.wt_snap)
                    # UNCLEAR не записываем — нет смысла буститься/блокировать при неопределённости
                    if _wt_label and _wt_label != "UNCLEAR":
                        _WT_RULE_CONF = {
                            "EXHAUSTION":         0.80,  # 2+ TF в OB/OS → gate BLOCK (порог 0.65)
                            "REVERSAL_SETUP":     0.75,  # кросс 4h/1h в зоне → strength boost
                            "TREND_CONTINUATION": 0.70,  # резерв (отключён в derive_wt_verdict)
                        }
                        _wt_conf = _WT_RULE_CONF.get(_wt_label, 0.70)
                        recommendation.metadata["wt_verdict"] = {
                            "label":      _wt_label,
                            "confidence": _wt_conf,
                        }
                        logger.info(
                            "[%s][DEV-161] wt_verdict=%s conf=%.2f (rule-based)",
                            symbol, _wt_label, _wt_conf,
                        )
                except Exception as _e:
                    logger.debug("[DEV-161] derive_wt_verdict error: %s", _e)

            # ARCH-70: wt_verdict_strong → EventBus Full CALL (publish если REVERSAL_SETUP conf≥0.7)
            try:
                _wt_v_meta = recommendation.metadata.get("wt_verdict")
                if _wt_v_meta and _wt_v_meta.get("label") == "REVERSAL_SETUP":
                    if _wt_v_meta.get("confidence", 0) >= 0.70:
                        _eb_ti = getattr(self, "_event_bus", None)
                        if _eb_ti is not None:
                            import asyncio as _asyncio
                            _asyncio.create_task(_eb_ti.publish(
                                symbol, "wt_verdict_strong", priority=2,
                                data={"label": _wt_v_meta["label"], "conf": _wt_v_meta["confidence"]},
                            ))
                            logger.debug(
                                "[ARCH-70] %s wt_verdict_strong conf=%.2f → EventBus",
                                symbol, _wt_v_meta["confidence"],
                            )
            except Exception as _e_eb:
                logger.debug("[ARCH-70] wt_verdict_strong publish error: %s", _e_eb)

            # ARCH-51: shadow logging MTF SMC snapshots (не влияет на strength/action)
            if mtf_context is not None:
                for _snap_tf, _snap_attr in (("4h", "smc_h4"), ("1d", "smc_d1")):
                    snap = getattr(mtf_context, _snap_attr, None)
                    if snap is not None:
                        key = f"arch51_{_snap_tf}"
                        recommendation.metadata[key] = {
                            "bull_ob_nearby": snap.bull_ob_nearby,
                            "bear_ob_nearby": snap.bear_ob_nearby,
                            "fvg_support": snap.fvg_support,
                            "fvg_resistance": snap.fvg_resistance,
                            "choch_direction": snap.choch_direction,
                            "bos_direction": snap.bos_direction,
                            "ob_proximity_pct": round(snap.ob_proximity_pct, 3),
                        }
                        logger.debug(
                            "[%s] ARCH-51 %s: bull_ob=%s bear_ob=%s fvg_sup=%s fvg_res=%s choch=%s bos=%s prox=%.2f%%",
                            symbol, _snap_tf,
                            snap.bull_ob_nearby, snap.bear_ob_nearby,
                            snap.fvg_support, snap.fvg_resistance,
                            snap.choch_direction, snap.bos_direction,
                            snap.ob_proximity_pct,
                        )

            # DEV-146: VerdictAggregator — gate из WTVerdict + SMCVerdict
            try:
                from core.intelligence.verdict_aggregator import aggregate_verdicts
                _vg_wt_v = recommendation.metadata.get("wt_verdict")
                _vg_sc_v = recommendation.metadata.get("smc_verdict")
                if _vg_wt_v or _vg_sc_v:
                    class _VGVrd:
                        def __init__(self, d): self.label = d.get("label"); self.confidence = d.get("confidence", 0.5)
                    _vgate_enabled = bool(
                        (self.config or {}).get("trading", {}).get("verdict_gate", {}).get("enabled", False)
                    )
                    # TR-007: direction-aware EXHAUSTION gate
                    _vg_exha_dir = None
                    _vg_wt_snap = recommendation.metadata.get("wt_snap")
                    if _vg_wt_snap and _vg_wt_v and _vg_wt_v.get("label") == "EXHAUSTION":
                        try:
                            from core.intelligence.wt_specialist import get_wt_exhaustion_direction as _get_exha_dir
                            _vg_exha_dir = _get_exha_dir(_vg_wt_snap)
                        except Exception:
                            pass
                    _vgate = aggregate_verdicts(
                        # 12.08 ФИКС: было str(enum) → 'SignalDirection.LONG', а агрегатор
                        # сравнивает с 'LONG' → гейт не срабатывал НИ РАЗУ с апреля
                        # (0 блокировок при 22 684 EXHAUSTION). Контрфакт: резал бы худшее
                        # (WR 4.0% против базы 12.1%). memory/verdict_gate_dead_enum_str.md
                        direction=str(getattr(recommendation.direction, "value", None)
                                      or getattr(recommendation, "direction", "") or ""),
                        wt_verdict=_VGVrd(_vg_wt_v) if _vg_wt_v else None,
                        smc_verdict=_VGVrd(_vg_sc_v) if _vg_sc_v else None,
                        config=(self.config or {}).get("trading"),
                        enabled=_vgate_enabled,
                        wt_exhaustion_dir=_vg_exha_dir,
                    )
                    recommendation.metadata["verdict_gate"] = {
                        "should_block": _vgate.should_block,
                        "would_block":  _vgate.would_block,
                        "strength_delta": _vgate.strength_delta,
                        "reason": _vgate.reason,
                    }
                    # 12.08 ДИАГНОСТИКА: за 5 недель лога — 22 684 wt_verdict=EXHAUSTION
                    # с conf 0.80 (порог 0.65) и НИ ОДНОГО VERDICT_GATE. Ретроспективно по
                    # wt_snap из БД 80 из 576 EXHAUSTION подпадали под блок, но лежат
                    # зарегистрированными. Логируем ИСХОД гейта, а не только факт блока.
                    if _vg_wt_v and _vg_wt_v.get("label") == "EXHAUSTION":
                        logger.info(
                            "[%s][DEV-146] GATE_EVAL exha_dir=%s dir=%s block=%s would=%s delta=%s reason=%s",
                            symbol, _vg_exha_dir, getattr(recommendation, "direction", None),
                            _vgate.should_block, _vgate.would_block, _vgate.strength_delta,
                            _vgate.reason or "-",
                        )
                    if _vgate.should_block:
                        # Реальный gate: обнуляем strength → сигнал не пройдёт is_actionable
                        recommendation.overall_strength = 0
                        recommendation.action = "WATCH"
                        logger.info(
                            "[%s][DEV-146] VERDICT_GATE BLOCK: %s",
                            symbol, _vgate.reason,
                        )
                    elif _vgate.strength_delta != 0.0 and not _vgate.would_block:
                        # Только буст (не штраф): корректируем strength
                        _new_str = round(
                            min(100.0, max(0.0, float(recommendation.overall_strength or 0) + _vgate.strength_delta)),
                            1,
                        )
                        recommendation.overall_strength = _new_str
            except Exception as _e_vg:
                # Был logger.debug при уровне INFO — гейт мог падать молча месяцами.
                logger.warning("[%s][DEV-146] VerdictAggregator error: %r", symbol, _e_vg)

            # DEV-141: Narrative Builder (shadow — config toggle trading.narrative.enabled)
            _narrative_enabled = (self.config or {}).get("trading", {}).get("narrative", {}).get("enabled", False)
            try:
                from core.intelligence.narrative_builder import NarrativeBuilder
                _rm  = recommendation.metadata.get("reversal_mode", "UNCLEAR")
                _wt_v = recommendation.metadata.get("wt_verdict")
                _sc_v = recommendation.metadata.get("smc_verdict")
                # WTVerdict/SMCVerdict как простые namespace-ы (dataclass-совместимо)
                class _Vrd:
                    def __init__(self, d): self.label = d.get("label"); self.confidence = d.get("confidence", 0.5)
                _wt_vrd  = _Vrd(_wt_v)  if _wt_v  else None
                _smc_vrd = _Vrd(_sc_v)  if _sc_v  else None
                _p_out   = recommendation.metadata.get("p_win")
                _btc_reg = recommendation.metadata.get("btc_4h_regime")
                # ARCH-78: fallback — читаем из BTCRegimeProvider если metadata пуста
                if _btc_reg is None:
                    _btc_prov = getattr(self, "_btc_provider", None)
                    if _btc_prov is not None:
                        _btc_reg = _btc_prov.get_btc_mode()
                _pair_bus = getattr(self, '_pair_context_bus', None)
                _nb = NarrativeBuilder(_pair_bus)
                _narrative = _nb.build(
                    symbol=symbol,
                    recommendation=recommendation,
                    wt_verdict=_wt_vrd,
                    smc_verdict=_smc_vrd,
                    reversal_mode=_rm,
                    btc_regime=_btc_reg,
                    p_outcome=_p_out,
                )
                recommendation.metadata["narrative"] = {
                    "text": _narrative.text,
                    "p_win": _narrative.p_win,
                    "mode": _narrative.mode,
                    "key_factors": _narrative.key_factors,
                    "confidence": _narrative.confidence,
                    # ARCH-90: SMC-факторы + плоские поля для ML
                    "smc_factors": _narrative.smc_factors,
                    "smc_flat": _narrative.smc_flat,
                }
                if _narrative_enabled:
                    logger.info("[%s][DEV-141] narrative: %s", symbol, _narrative.text)
                else:
                    logger.debug("[%s][DEV-141] narrative (shadow): %s", symbol, _narrative.text)
            except Exception as _e_narr:
                logger.debug("[DEV-141] narrative error: %s", _e_narr)

            # ARCH-53: OTE shadow metadata
            if smc_context is not None:
                _ote_zone = smc_context.fibonacci.active_ote if smc_context.fibonacci else None
                recommendation.metadata["ote_shadow"] = {
                    "in_ote": _ote_zone is not None and _ote_zone.price_in_ote,
                    "zone": str(_ote_zone) if _ote_zone else None,
                    "direction": _ote_zone.direction if _ote_zone else None,
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
                    # DEV-149: REVERSAL-BOOST обходит regime_direction_block —
                    # это классический reversal setup (WT 4h OB/OS + reversal mode).
                    _has_rev_boost = bool((recommendation.metadata or {}).get("reversal_boost"))
                    if _has_rev_boost and _blocked and _rec_dir == _blocked:
                        logger.info(
                            "[%s][DEV-149] regime_direction_block SKIPPED — reversal_boost active",
                            symbol,
                        )
                        _blocked = None
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
                    _pc = self._pivot_calc_shared
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

            # DEV-37: Pivot Proximity Filter (ARCH-34 спек, TRADER 23.03)
            # Штраф к score если цена далеко от ближайшего пивота (1D/1W/1M PP).
            # shadow mode (enabled: false) — только логирование без изменений.
            # TRADER 25.03: pivot_reversal исключён — сигнал по определению стоит на пивоте,
            #               PPF создаёт двойной фильтр одного условия и штрафует хороший тип.
            _ppf_cfg = (self.config.get("trading", {}).get("pivot_proximity_filter", {})
                        if self.config else {})
            _ppf_enabled = _ppf_cfg.get("enabled", False)
            _ppf_shadow  = not _ppf_enabled  # shadow = логируем, но не меняем
            _ppf_skip_pivot_reversal = any(
                getattr(getattr(s, "signal_type", None), "value", None) == "pivot_reversal"
                for s in (recommendation.supporting_signals or [])
            ) and not any(
                getattr(getattr(s, "signal_type", None), "value", None) in ("wt_b_signal", "mtf_bias", "confluence")
                for s in (recommendation.supporting_signals or [])
            )
            try:
                if _ppf_skip_pivot_reversal:
                    logger.debug("[%s] DEV-37 PPF: пропуск для pivot_reversal", symbol)
                else:
                  _price37 = (recommendation.entry_price
                              or (market_context.current_price if market_context else 0))
                  if _price37 > 0:
                    # 4h ATR для адаптивных порогов (кешировано scan_loop-ом)
                    _atr_pct37 = None
                    try:
                        _df_4h37 = await self.data_collector.get_ohlcv(symbol, "4h", limit=20)
                        if _df_4h37 is not None and len(_df_4h37) >= 14:
                            _atr_val37 = compute_atr(_df_4h37, period=14)
                            if _atr_val37 and _atr_val37 > 0:
                                _atr_pct37 = _atr_val37 / _price37 * 100
                    except Exception:
                        pass

                    if _atr_pct37:
                        _tier1_37 = max(1.0, min(_atr_pct37 * 1.5, 5.0))  # TRADER TR-004: cap 5%
                        _tier2_37 = _tier1_37 * 2
                        _hard_m37 = float(_ppf_cfg.get("hard_block_mult", 3))

                        # PP уровни: Daily + Weekly + Monthly из кеша
                        _pp_levels37 = []
                        try:
                            _pc37 = self._pivot_calc_shared
                            _dp37 = await _pc37.get_daily_pivots(symbol, self.data_collector)
                            if _dp37 and "PP" in _dp37:
                                _pp_levels37.append(float(_dp37["PP"]))
                            _wp37 = await _pc37.get_weekly_pivots(symbol, self.data_collector)
                            if _wp37 and "PP" in _wp37:
                                _pp_levels37.append(float(_wp37["PP"]))
                        except Exception:
                            pass

                        if _pp_levels37:
                            _min_dist37 = min(
                                abs(p - _price37) / _price37 * 100 for p in _pp_levels37
                            )
                            _hard_thr37 = _tier1_37 * _hard_m37

                            if _min_dist37 < _tier1_37:
                                _ppf_tag = "near"       # рядом — торгуем нормально
                            elif _min_dist37 < _hard_thr37:
                                _ppf_tag = "penalty"    # умеренно/далеко — штраф -10
                            else:
                                _ppf_tag = "hard_block" # очень далеко → WATCH

                            logger.info(
                                "[%s] DEV-37 PivotProximity: dist=%.2f%% tier1=%.2f%% "
                                "tier2=%.2f%% hard=%.2f%% tag=%s shadow=%s",
                                symbol, _min_dist37, _tier1_37, _tier2_37,
                                _hard_thr37, _ppf_tag, _ppf_shadow,
                            )
                            # DEV-53: сохраняем для cond4
                            recommendation.metadata["dist_pivot_pct"] = round(_min_dist37, 3)
                            recommendation.metadata["tier1_pct"] = round(_tier1_37, 3)

                            if not _ppf_shadow:
                                if _ppf_tag == "hard_block" and recommendation.action in ("BUY", "SELL"):
                                    recommendation.action = "WATCH"
                                    trace.add_filter(
                                        "pivot_proximity_hard", False,
                                        f"dist={_min_dist37:.1f}% > {_hard_m37}×tier1",
                                    )
                                elif _ppf_tag == "penalty":
                                    _old37 = recommendation.overall_strength
                                    recommendation.overall_strength = max(0, min(100, _old37 - 10))
                                    logger.info(
                                        "[%s] DEV-37: str %d→%d",
                                        symbol, _old37, recommendation.overall_strength,
                                    )
            except Exception as _e37:
                logger.debug("[%s] DEV-37 Pivot Proximity Filter: %s", symbol, _e37)

            # DEV-52: L3 условия 3+5 — shadow mode (только лог, не блокирует)
            try:
                from core.infra.config_loader import config as _cfg_52ti
                _l3_52 = (_cfg_52ti.get("trading", {}) or {}).get("l3_checker", {}) if _cfg_52ti else {}
                if _l3_52:
                    _min_score_52 = _l3_52.get("min_score", 85)
                    _dir_52ti = str(getattr(recommendation, "direction", "") or "").upper()
                    _score_52 = getattr(recommendation, "overall_strength", 0) or 0
                    _cond5 = _score_52 >= _min_score_52

                    # Условие 3: 1h структура не противоположна направлению
                    _cond3 = True
                    _cond3_note = "no_data"
                    try:
                        from core.signals.structure_detector import detect_structure as _det_struct_52
                        _df_1h_52 = await self.data_collector.get_ohlcv(symbol, "1h", limit=100)
                        if _df_1h_52 is not None and len(_df_1h_52) >= 20:
                            _struct_52 = _det_struct_52(_df_1h_52)
                            _last_bos  = _struct_52.get("bos")
                            _last_choch = _struct_52.get("choch")
                            _last_brk = _last_bos or _last_choch
                            if _last_brk:
                                _bars_ago_52 = len(_df_1h_52) - 1 - _last_brk.get("broken_index", 0)
                                _is_stale_52 = _bars_ago_52 > 48  # >48 баров 1h = >48ч
                                _brk_dir_52  = (_last_brk.get("direction") or "").upper()
                                _brk_type_52 = "BOS" if _last_bos else "CHOCH"
                                if not _is_stale_52:
                                    if _dir_52ti == "LONG" and _brk_dir_52 == "BEARISH" and _brk_type_52 == "BOS":
                                        _cond3 = False
                                        _cond3_note = f"BEARISH_BOS {_bars_ago_52}bars_ago"
                                    elif _dir_52ti == "SHORT" and _brk_dir_52 == "BULLISH" and _brk_type_52 == "BOS":
                                        _cond3 = False
                                        _cond3_note = f"BULLISH_BOS {_bars_ago_52}bars_ago"
                                    elif _dir_52ti == "LONG" and _brk_dir_52 == "BEARISH" and _brk_type_52 == "CHOCH":
                                        _cond3_note = f"BEARISH_CHOCH soft {_bars_ago_52}bars"
                                    elif _dir_52ti == "SHORT" and _brk_dir_52 == "BULLISH" and _brk_type_52 == "CHOCH":
                                        _cond3_note = f"BULLISH_CHOCH soft {_bars_ago_52}bars"
                                    else:
                                        _cond3_note = f"{_brk_dir_52}_{_brk_type_52} ok"
                                else:
                                    _cond3_note = f"stale({_bars_ago_52}bars)"
                    except Exception as _e52_struct:
                        logger.debug("[%s] DEV-52 struct: %s", symbol, _e52_struct)

                    # DEV-53 (Фаза B): Условие 4 — WT кросс freshness (≤3 бара 15m) + near pivot
                    _cond4 = False
                    _cond4_note = "no_wt"
                    try:
                        _wt_sigs_53 = [
                            s for s in (recommendation.supporting_signals or [])
                            if getattr(getattr(s, "signal_type", None), "value", None) == "wt_signal"
                        ]
                        if _wt_sigs_53:
                            _wt_s53 = _wt_sigs_53[0]
                            _wt_bar_idx_53 = (_wt_s53.data or {}).get("wt_cross_bar_index")
                            if _wt_bar_idx_53 is not None:
                                _df_15m_53 = await self.data_collector.get_ohlcv(symbol, "15m", limit=100)
                                if _df_15m_53 is not None:
                                    _bars_ago_53 = len(_df_15m_53) - 1 - _wt_bar_idx_53
                                    _fresh_53 = _bars_ago_53 <= 3
                                    _dist53 = (recommendation.metadata or {}).get("dist_pivot_pct", 999)
                                    _tier1_53 = (recommendation.metadata or {}).get("tier1_pct", 5.0)
                                    _near_53 = _dist53 < _tier1_53
                                    _cond4 = _fresh_53 and _near_53
                                    _cond4_note = (
                                        f"fresh={_fresh_53}({_bars_ago_53}bars)"
                                        f" near={_near_53}(dist={_dist53:.2f}%<{_tier1_53:.2f}%)"
                                    )
                            else:
                                _cond4_note = "no_bar_idx"
                    except Exception as _e53_cond4:
                        logger.debug("[%s] DEV-53 cond4: %s", symbol, _e53_cond4)

                    # DEV-53: CHoCH soft penalty (-8 score) — активен при наличии l3_checker конфига
                    _choch_penalty_53 = False
                    if "CHOCH" in _cond3_note:
                        _old_53 = getattr(recommendation, "overall_strength", 0) or 0
                        recommendation.overall_strength = max(0, _old_53 - 8)
                        _choch_penalty_53 = True
                        logger.info(
                            "[%s] DEV-53: CHoCH soft penalty str %d→%d (%s)",
                            symbol, _old_53, recommendation.overall_strength, _cond3_note,
                        )

                    # Сводный лог
                    _conds_met = sum([_cond3, _cond4, _cond5])  # условия 3+4+5
                    logger.info(
                        "[%s] DEV-52-L3 cond3=%s(%s) cond4=%s(%s) cond5=%s(score=%d≥%d) choch_pen=%s met=%d/3",
                        symbol, _cond3, _cond3_note, _cond4, _cond4_note,
                        _cond5, _score_52, _min_score_52, _choch_penalty_53, _conds_met,
                    )

                    # DEV-84 (Фаза C) — shadow logging: FVG support + OTE zone
                    _cond_c1, _cond_c1_note = False, "no_smc_h4"
                    try:
                        _snap_h4_84 = getattr(mtf_context, "smc_h4", None) if mtf_context else None
                        if _snap_h4_84 is not None:
                            if _dir_52ti == "LONG":
                                _cond_c1 = bool(_snap_h4_84.fvg_support)
                                _cond_c1_note = f"4h_fvg_sup={'Y' if _cond_c1 else 'N'}"
                            else:
                                _cond_c1 = bool(_snap_h4_84.fvg_resistance)
                                _cond_c1_note = f"4h_fvg_res={'Y' if _cond_c1 else 'N'}"
                    except Exception as _e84c1:
                        logger.debug("[%s] DEV-84 cond_c1: %s", symbol, _e84c1)

                    _cond_c2, _cond_c2_note = False, "no_smc"
                    try:
                        _fib_84 = getattr(smc_context, "fibonacci", None) if smc_context else None
                        if _fib_84 is not None:
                            _cond_c2 = _fib_84.active_ote is not None
                            _cond_c2_note = f"ote={'Y' if _cond_c2 else 'N'}"
                    except Exception as _e84c2:
                        logger.debug("[%s] DEV-84 cond_c2: %s", symbol, _e84c2)

                    logger.info(
                        "[%s] DEV-84-L3C cond_c1=%s(%s) cond_c2=%s(%s)",
                        symbol, _cond_c1, _cond_c1_note, _cond_c2, _cond_c2_note,
                    )
            except Exception as _e52ti:
                logger.debug("[%s] DEV-52 L3 checker: %s", symbol, _e52ti)

            # ARCH-48: Weekly Bias Filter — Фаза A shadow (DEV-56) + Фаза B production gate (DEV-58)
            # Фаза A: записывает weekly_bias в metadata (shadow, всегда)
            # Фаза B: production gate (enabled: false → включить вручную через config.yaml)
            try:
                _wcfg_48 = (self.config.get("trading") or {}).get("weekly_bias_filter") or {}
                _pc_48 = self._pivot_calc_shared
                _wp48  = await _pc_48.get_weekly_pivots(symbol, self.data_collector)
                _weekly_pp_48 = float((_wp48 or {}).get("PP") or 0) or None
                _price_48 = float(recommendation.entry_price or
                                  (market_context.current_price if market_context else 0) or 0)
                if not (_weekly_pp_48 and _price_48):
                    # Находка 4 (ARCH 29.03): явно записываем UNKNOWN чтобы видеть в features_json
                    recommendation.metadata = recommendation.metadata or {}
                    recommendation.metadata["weekly_bias"] = "UNKNOWN"
                    recommendation.metadata["weekly_gate_would_block"] = False
                elif _weekly_pp_48 and _price_48:
                    _weekly_bias_48 = "BULLISH" if _price_48 > _weekly_pp_48 else "BEARISH"
                    _mp48  = await _pc_48.get_monthly_pivots(symbol, self.data_collector)
                    _dp48  = await _pc_48.get_daily_pivots(symbol, self.data_collector)
                    _monthly_pp_48 = float((_mp48 or {}).get("PP") or 0) or None
                    _daily_pp_48   = float((_dp48 or {}).get("PP") or 0) or None
                    _ctx_score_48  = sum([
                        bool(_monthly_pp_48 and _price_48 < _monthly_pp_48),
                        bool(_weekly_pp_48  and _price_48 < _weekly_pp_48),
                        bool(_daily_pp_48   and _price_48 < _daily_pp_48),
                    ])
                    _dir_48 = str(getattr(recommendation.direction, "value", recommendation.direction) or "").upper()
                    _gate_block_48 = (
                        (_dir_48 == "LONG"  and _weekly_bias_48 == "BEARISH") or
                        (_dir_48 == "SHORT" and _weekly_bias_48 == "BULLISH")
                    )
                    if _gate_block_48:
                        logger.info(
                            "[ARCH-48 shadow] %s: direction=%s would_block=True weekly_bias=%s ctx_score=%d",
                            symbol, _dir_48, _weekly_bias_48, _ctx_score_48,
                        )
                    recommendation.metadata = recommendation.metadata or {}
                    recommendation.metadata.update({
                        "weekly_bias": _weekly_bias_48,
                        "weekly_context_score": _ctx_score_48,
                        "weekly_gate_would_block": _gate_block_48,
                        "weekly_pp": _weekly_pp_48,
                        # ARCH-64: уровни для near_level check (без повторного API вызова)
                        "weekly_s1": float((_wp48 or {}).get("S1") or 0) or None,
                        "weekly_s2": float((_wp48 or {}).get("S2") or 0) or None,
                        "weekly_r1": float((_wp48 or {}).get("R1") or 0) or None,
                        "weekly_r2": float((_wp48 or {}).get("R2") or 0) or None,
                    })

                    # DEV-58: Фаза B — production gate (включить: weekly_bias_filter.enabled: true)
                    if _gate_block_48 and _wcfg_48.get("enabled"):
                        _penalty_48 = int(_wcfg_48.get("soft_penalty", 25))
                        _near_pct_48 = float(_wcfg_48.get("near_level_pct", 1.5)) / 100
                        _hard_ctx_48 = int(_wcfg_48.get("hard_block_ctx_score", 3))
                        # near_s: LONG исключение — рядом с weekly поддержкой (S1/S2/PP)
                        # near_r: SHORT исключение — рядом с weekly сопротивлением (R1/R2/PP)
                        _wp48_pp = float((_wp48 or {}).get("PP") or 0) or None
                        _wr1 = float((_wp48 or {}).get("R1") or 0) or None
                        _wr2 = float((_wp48 or {}).get("R2") or 0) or None
                        _ws1 = float((_wp48 or {}).get("S1") or 0) or None
                        _ws2 = float((_wp48 or {}).get("S2") or 0) or None
                        def _within(_lvl, _p, _pct):
                            return bool(_lvl and abs(_p - _lvl) / _p < _pct)
                        def _near_label(_lvl, _name, _p, _pct):
                            if _within(_lvl, _p, _pct):
                                return _name
                            return None
                        _near_s_label = (
                            _near_label(_ws1, "W_S1", _price_48, _near_pct_48) or
                            _near_label(_ws2, "W_S2", _price_48, _near_pct_48) or
                            (_near_label(_wp48_pp, "W_PP", _price_48, _near_pct_48)
                             if _weekly_bias_48 == "BEARISH" else None)
                        )
                        _near_r_label = (
                            _near_label(_wr1, "W_R1", _price_48, _near_pct_48) or
                            _near_label(_wr2, "W_R2", _price_48, _near_pct_48) or
                            (_near_label(_wp48_pp, "W_PP", _price_48, _near_pct_48)
                             if _weekly_bias_48 == "BULLISH" else None)
                        )
                        _near_s = bool(_near_s_label)
                        _near_r = bool(_near_r_label)

                        # DEV-89 sub-task: tp_source содержит Weekly/Daily уровень → разрешить
                        # Если get_tp_by_hierarchy() вернул W/D S/R как TP — сигнал уже
                        # находится в контексте этой зоны (reversal у уровня)
                        _tp_src_89 = str(getattr(recommendation, "tp_source", None) or "")
                        _tp_src_lower = _tp_src_89.lower()
                        for _tf_tag in ("1W", "1w", "1D", "1d"):
                            if _tf_tag in _tp_src_89 or _tf_tag.lower() in _tp_src_lower:
                                if _dir_48 == "LONG" and any(x in _tp_src_89 for x in ("S1","S2","S3","PP")):
                                    _near_s = True
                                    _near_s_label = _near_s_label or f"tp_src:{_tp_src_89}"
                                elif _dir_48 == "SHORT" and any(x in _tp_src_89 for x in ("R1","R2","R3","PP")):
                                    _near_r = True
                                    _near_r_label = _near_r_label or f"tp_src:{_tp_src_89}"
                                break

                        if _dir_48 == "LONG" and _weekly_bias_48 == "BEARISH":
                            if _near_s:
                                logger.info(
                                    "[DEV-58] %s LONG/BEARISH ALLOWED — near %s (within %.1f%%)",
                                    symbol, _near_s_label, _near_pct_48 * 100,
                                )
                            elif _ctx_score_48 >= _hard_ctx_48:
                                recommendation.action = "WATCH"
                                logger.info(
                                    "[DEV-58] %s hard_block LONG/BEARISH ctx=%d (≥%d)",
                                    symbol, _ctx_score_48, _hard_ctx_48,
                                )
                            else:
                                overall_strength = max(0, overall_strength - _penalty_48)
                                logger.info(
                                    "[DEV-58] %s soft_penalty LONG/BEARISH ctx=%d strength=%d→%d",
                                    symbol, _ctx_score_48, overall_strength + _penalty_48, overall_strength,
                                )
                        elif _dir_48 == "SHORT" and _weekly_bias_48 == "BULLISH":
                            if _near_r:
                                logger.info(
                                    "[DEV-58] %s SHORT/BULLISH ALLOWED — near %s (within %.1f%%)",
                                    symbol, _near_r_label, _near_pct_48 * 100,
                                )
                            elif _ctx_score_48 >= _hard_ctx_48:
                                recommendation.action = "WATCH"
                                logger.info(
                                    "[DEV-58] %s hard_block SHORT/BULLISH ctx=%d (≥%d)",
                                    symbol, _ctx_score_48, _hard_ctx_48,
                                )
                            else:
                                overall_strength = max(0, overall_strength - _penalty_48)
                                logger.info(
                                    "[DEV-58] %s soft_penalty SHORT/BULLISH ctx=%d strength=%d→%d",
                                    symbol, _ctx_score_48, overall_strength + _penalty_48, overall_strength,
                                )
            except Exception as _e48:
                logger.debug("[ARCH-48] weekly bias error: %s", _e48)

            # ARCH-64: pivot_reversal weekly_bias gate (shadow по умолчанию)
            # Данные TRADER [02.04.2026]: weekly_bias=UNKNOWN → 62% сделок, EV -0.4..−0.76R
            # Логика: UNKNOWN → WOULD_BLOCK; против bias → WOULD_PENALIZE -20; рядом с W_S/R → исключение
            try:
                _a64_strat = (recommendation.metadata or {}).get("strategy_name", "")
                if _a64_strat == "pivot_reversal":
                    _a64_bias   = (recommendation.metadata or {}).get("weekly_bias", "UNKNOWN")
                    _a64_cfg    = (self.config.get("trading") or {}).get("pivot_reversal_bias", {})
                    _a64_shadow = not bool(_a64_cfg.get("enabled", False))
                    _dir_64     = str(getattr(recommendation.direction, "value", "") or "").upper()
                    _pfx64      = "[ARCH-64 SHADOW]" if _a64_shadow else "[ARCH-64]"

                    # Кейс 1: weekly_bias=UNKNOWN → самые убыточные (EV -0.76R, 62% pivot_reversal)
                    if _a64_bias == "UNKNOWN":
                        logger.info("%s %s pivot_reversal weekly_bias=UNKNOWN → WOULD_BLOCK", _pfx64, symbol)
                        if not _a64_shadow:
                            recommendation.action = "WATCH"
                            recommendation.metadata["arch64"] = "blocked:bias_unknown"

                    # Кейс 2: направление против weekly bias → штраф (LONG+BEARISH или SHORT+BULLISH)
                    elif ((_dir_64 == "LONG"  and _a64_bias == "BEARISH") or
                          (_dir_64 == "SHORT" and _a64_bias == "BULLISH")):
                        _a64_penalty  = int(_a64_cfg.get("against_bias_penalty", 20))
                        _a64_near_pct = float(_a64_cfg.get("near_level_pct", 1.5)) / 100
                        _a64_price    = float(
                            recommendation.entry_price or
                            (market_context.current_price if market_context else 0) or 0
                        )
                        # near_level: используем значения из metadata ARCH-48 (W_S1/S2 или W_R1/R2)
                        _a64_meta = recommendation.metadata or {}
                        _ws1_64 = _a64_meta.get("weekly_s1")
                        _ws2_64 = _a64_meta.get("weekly_s2")
                        _wr1_64 = _a64_meta.get("weekly_r1")
                        _wr2_64 = _a64_meta.get("weekly_r2")

                        def _near64(lvl):
                            return bool(lvl and _a64_price
                                        and abs(_a64_price - float(lvl)) / float(_a64_price) < _a64_near_pct)

                        _a64_near = (
                            (_near64(_ws1_64) or _near64(_ws2_64)) if _dir_64 == "LONG"
                            else (_near64(_wr1_64) or _near64(_wr2_64))
                        )

                        if _a64_near:
                            logger.info(
                                "%s %s pivot_reversal %s/%s ALLOWED (near W_S/R ≤%.1f%%)",
                                _pfx64, symbol, _dir_64, _a64_bias, _a64_near_pct * 100,
                            )
                        else:
                            logger.info(
                                "%s %s pivot_reversal %s/%s WOULD_PENALIZE -%d",
                                _pfx64, symbol, _dir_64, _a64_bias, _a64_penalty,
                            )
                            if not _a64_shadow:
                                overall_strength = max(0, overall_strength - _a64_penalty)
                                recommendation.metadata["arch64"] = f"penalty:-{_a64_penalty}"
            except Exception as _e64:
                logger.debug("[ARCH-64] error: %s", _e64)

            # ARCH-51-pre: логировать конфликт 15m bearish SMC + LONG (валидация до реализации ARCH-51)
            try:
                _smc51 = getattr(market_context, "smc_context", None)
                _dir51 = str(getattr(recommendation.direction, "value", recommendation.direction) or "").upper()
                if _smc51 is not None and _dir51 == "LONG":
                    _smc_trend51 = str(getattr(_smc51.trend, "value", "")).lower()
                    if _smc_trend51 == "bearish":
                        # pivot_dist: сначала ищем в metadata (future-proof), потом в wt_signal.data,
                        # потом вычисляем сами — ближайший 1D+1W уровень к текущей цене
                        _dist51 = (recommendation.metadata or {}).get("pivot_proximity_pct")
                        if _dist51 is None:
                            for _s51 in filtered_signals:
                                _d51 = (_s51.data or {}).get("near_pivot_dist_pct")
                                if _d51 is not None:
                                    _dist51 = _d51
                                    break
                        if _dist51 is None:
                            try:
                                _pcf51 = self._pivot_calc_shared
                                _dp51 = await _pcf51.get_daily_pivots(symbol, self.data_collector) or {}
                                _wp51 = await _pcf51.get_weekly_pivots(symbol, self.data_collector) or {}
                                _ap51 = dict(_dp51)
                                _ap51.update({f"1W_{k}": v for k, v in _wp51.items()})
                                _price51 = getattr(market_context, "current_price", 0) or 0
                                if _price51 and _ap51:
                                    _dists51 = [
                                        abs(_price51 - float(v)) / float(v) * 100
                                        for v in _ap51.values() if v and float(v) > 0
                                    ]
                                    _dist51 = round(min(_dists51), 2) if _dists51 else None
                            except Exception:
                                pass
                        _wgate51 = (recommendation.metadata or {}).get("weekly_gate_would_block", "?")
                        logger.info(
                            "[ARCH-51-pre] %s SMC conflict: 15m=bearish LONG, pivot_dist=%s, weekly_gate=%s",
                            symbol,
                            f"{_dist51:.1f}%" if isinstance(_dist51, (int, float)) else "?",
                            _wgate51,
                        )
            except Exception as _e51:
                logger.debug("[ARCH-51-pre] %s: %s", symbol, _e51)

            # DEV-40: ATR entry TF → используется в register_trade для ATR-based TP1
            try:
                from core.infra.entry_config import ENTRY_TO_TP1_TF as _TP1_TF_MAP
                _entry_tf_40 = get_primary_entry_tf(self.config)
                _atr_tf_40 = _TP1_TF_MAP.get(_entry_tf_40, "15m")
                _df_atr40 = await self.data_collector.get_ohlcv(symbol, _atr_tf_40, limit=20)
                if _df_atr40 is not None and len(_df_atr40) >= 14:
                    _atr40 = compute_atr(_df_atr40, period=14)
                    if _atr40 and _atr40 > 0:
                        recommendation.atr_entry_tf = float(_atr40)
            except Exception as _e40:
                logger.debug("[%s] DEV-40 atr_entry_tf: %s", symbol, _e40)

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

            # Куб: персистируем wt_verdict + reversal_mode в PairContextBus
            _pcb = getattr(self, '_pair_context_bus', None)
            if _pcb is not None:
                _pcb_updates = {}
                _wt_v_pcb = (recommendation.metadata or {}).get("wt_verdict")
                if _wt_v_pcb:
                    _pcb_updates["wt_verdict"] = _wt_v_pcb.get("label")
                _rm_pcb = (recommendation.metadata or {}).get("reversal_mode")
                if _rm_pcb:
                    _pcb_updates["reversal_mode"] = _rm_pcb
                if _pcb_updates:
                    _pcb.update(symbol, **_pcb_updates)

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
                from core.indicators.market_regime import MarketRegimeClassifier
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
            _ts = signal.timestamp if signal.timestamp.tzinfo is not None else signal.timestamp.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - _ts).total_seconds() < max_age_seconds:
                filtered.append(signal)
        return filtered
    
    async def _build_mtf_context(self, symbol: str) -> Optional[MTFContext]:
        """
        ARCH-12: Строит MTFContext для символа.
        Данные из кешированного collect_mtf_data + weekly_pivots + regime.
        """
        try:
            from core.mtf.mtf_checker import collect_mtf_data
            from core.mtf.mtf_interpreter import analyze_context

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
                pc = self._pivot_calc_shared
                weekly_pivots = await pc.get_weekly_pivots(symbol, self.data_collector)
            except Exception:
                logger.debug("[%s] weekly pivots для MTFContext недоступны", symbol)

            # Regime + ARCH-56: df_1h/df_4h для unswept liquidity
            _regime: Optional[str] = None
            df_1h = None
            df_4h = None
            try:
                from core.indicators.market_regime import MarketRegimeClassifier
                df_15m = await self.data_collector.get_ohlcv(symbol, get_primary_entry_tf(self.config), limit=100)
                df_1h = await self.data_collector.get_ohlcv(symbol, "1h", limit=100)
                df_4h = await self.data_collector.get_ohlcv(symbol, "4h", limit=60)
                _regime = MarketRegimeClassifier().classify_from_dataframes(df_15m, df_1h)
            except Exception:
                pass

            # DEV-137: Reversal Mode (shadow — только в metadata, не влияет на strength)
            _reversal_mode: Optional[str] = None
            try:
                _reversal_mode = MarketRegimeClassifier().classify_mode(df_4h, df_1h, df_15m)
                logger.debug("[%s][DEV-137] reversal_mode=%s", symbol, _reversal_mode)
            except Exception:
                pass

            ctx = analyze_context(
                snapshot=snapshot,
                current_price=current_price,
                weekly_pivots=weekly_pivots,
                regime=_regime,
                df_1h=df_1h,   # ARCH-56: unswept liquidity
                df_4h=df_4h,   # ARCH-56: unswept liquidity
            )

            # ARCH-12.5: подгружаем калиброванные параметры
            if hasattr(self, '_auto_calibrator') and self._auto_calibrator is not None:
                ctx.calibration_params = self._auto_calibrator.get_params()

            # DEV-137: сохраняем reversal_mode в контексте
            ctx.reversal_mode = _reversal_mode

            # DEV-138: сохраняем wt_snap из snapshot в контексте (для features_json + WTSpecialist)
            if snapshot:
                ctx.wt_snap = {
                    tf: {
                        "wt1": v.get("wt1", 0.0),
                        "wt2": v.get("wt2", 0.0),
                        "zone": v.get("zone", "Normal"),
                        "wt_cross": v.get("wt_cross", 0),
                        "trend": v.get("trend", 0),
                    }
                    for tf, v in snapshot.items()
                    if isinstance(v, dict)
                }

            # DEV-139: smc_snap — вычисляем для 4 TF (использует уже загруженные df)
            try:
                from core.ml.mtf_smc_specialist import _build_smc_snap_from_df
                _cur_price_smc = current_price or 0.0
                _smc_snap: dict = {}
                for _tf_name, _df_smc in (
                    ("15m", df_15m), ("1h", df_1h), ("4h", df_4h)
                ):
                    if _df_smc is not None and len(_df_smc) >= 30:
                        _smc_snap[_tf_name] = _build_smc_snap_from_df(_df_smc, _cur_price_smc)
                # 1d — загружаем отдельно (не было в _build_mtf_context)
                try:
                    _df_1d = await self.data_collector.get_ohlcv(symbol, "1d", limit=60)
                    if _df_1d is not None and len(_df_1d) >= 30:
                        _smc_snap["1d"] = _build_smc_snap_from_df(_df_1d, _cur_price_smc)
                except Exception:
                    pass
                if _smc_snap:
                    ctx.smc_snap = _smc_snap
            except Exception as _e_smc:
                logger.debug("[DEV-139] smc_snap error: %s", _e_smc)

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
            # ARCH-45 Этап A: передаём фичи 17-23 из metadata (fix feature mismatch).
            # Без этого модель получала 2 из 23 признаков → фичи distance_to_sl/wt_snap всегда 0.
            _meta = recommendation.metadata or {}
            # wt_snap → признаки 19-20 (wt1_15m, wt2_15m)
            if _meta.get("wt_snap"):
                features_dict["wt_snap"] = _meta["wt_snap"]
            # reversal_mode → признаки 21-23 (one-hot TREND/REVERSAL/UNCLEAR)
            if _meta.get("reversal_mode"):
                features_dict["reversal_mode"] = _meta["reversal_mode"]
            # distance_to_sl_pct → признак 17
            if recommendation.entry_price and recommendation.stop_loss and recommendation.entry_price > 0:
                features_dict["distance_to_sl_pct"] = round(
                    abs(recommendation.entry_price - recommendation.stop_loss)
                    / recommendation.entry_price * 100, 4
                )
            # sl_atr_ratio → признак 18
            if (recommendation.atr_entry_tf and recommendation.atr_entry_tf > 0
                    and "distance_to_sl_pct" in features_dict):
                _sl_abs = features_dict["distance_to_sl_pct"] / 100.0 * recommendation.entry_price
                features_dict["sl_atr_ratio"] = round(_sl_abs / recommendation.atr_entry_tf, 2)

            # regime из market_context (было None → пустой one-hot)
            _regime_ml = getattr(market_context, "regime", None) if market_context else None

            win_prob = self.outcome_predictor.predict_win_prob(
                signal_type=sig_type,
                direction=direction_str,
                strength=recommendation.overall_strength,
                confidence=recommendation.confidence,
                features_dict=features_dict,
                regime=_regime_ml,
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
            # Ближайший значимый экстремум — SL за него тесней, в пределах sl_max кода
            # Для LONG: самый высокий swing low ниже цены (ближайший снизу)
            # Для SHORT: самый низкий swing high выше цены (ближайший сверху)
            swing_low  = float(max(lows_candidates))  if lows_candidates  else None
            swing_high = float(min(highs_candidates)) if highs_candidates else None
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
    


