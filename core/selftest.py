"""
SelfTest система (ARCH-14 + ARCH-73).

При каждом запуске бот проверяет работоспособность всех ключевых слоёв
ПЕРЕД началом торговли. Если критический тест провален — бот не стартует.

Слои проверки:
  L1 — Config:       конфигурация загружена, ключи на месте
  L2 — Imports:      все модули импортируются без ошибок
  L3 — Indicators:   индикаторы считают корректно на синтетических данных
  L4 — Database:     SQLite доступен, таблицы и схема на месте
  L5 — Exchange:     API биржи отвечает (загрузка рынков)
  L6 — MultiTF:      конфигурация entry TF валидна
  L7 — Pivots:       pivot calculator инициализируется
  L8 — Intelligence: TradingIntelligence + стратегии
  L9 — Strategies:   все заявленные стратегии загружены
  L10 — TradeSimulator: проверка схемы БД и логики
  L11 — Config Integrity: dot-notation, типы, опасные значения
  L12 — Trade Lifecycle:  полный цикл register→open→close(TP)→verify→cleanup
  L13 — Cube Spheres:     статус всех 13 сфер Куба (ACTIVE/SHADOW/MISSING)
  L14 — Cube Edges:       рёбра — связи между сферами
  L15 — Feedback Loops:   циклы обратной связи замкнуты

Каждый тест возвращает SelfTestResult. Критические отказы блокируют запуск.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SelfTestResult:
    """Результат одного теста."""
    layer: str           # "L1", "L2", ...
    name: str            # Человекочитаемое имя
    passed: bool
    critical: bool       # Если True и не passed → бот не стартует
    duration_ms: float = 0.0
    message: str = ""
    error: str = ""


@dataclass
class SelfTestReport:
    """Сводный отчёт по всем тестам."""
    results: List[SelfTestResult] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    total_duration_ms: float = 0.0
    cube_text: str = ""   # L13-L15: отчёт Куба Метатрона (format_cube_report)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def critical_passed(self) -> bool:
        return all(r.passed for r in self.results if r.critical)

    @property
    def failed(self) -> List[SelfTestResult]:
        return [r for r in self.results if not r.passed]

    @property
    def critical_failed(self) -> List[SelfTestResult]:
        return [r for r in self.results if r.critical and not r.passed]

    def summary_text(self) -> str:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        critical_fail = len(self.critical_failed)

        lines = [
            f"{'✅' if self.critical_passed else '❌'} <b>SELFTEST REPORT</b>",
            f"Тестов: {passed}/{total} пройдено",
        ]
        if failed:
            lines.append(f"❌ Провалено: {failed} (критических: {critical_fail})")

        lines.append("")
        for r in self.results:
            icon = "✅" if r.passed else ("🔴" if r.critical else "⚠️")
            dur = f" ({r.duration_ms:.0f}ms)" if r.duration_ms > 0 else ""
            msg = r.message if r.passed else r.error
            detail = f"  {msg[:80]}" if msg else ""
            lines.append(f"  {icon} [{r.layer}] {r.name}{dur}{detail}")

        lines.append("")
        lines.append(f"Общее время: {self.total_duration_ms:.0f}ms")
        if not self.critical_passed:
            lines.append("\n🚫 <b>КРИТИЧЕСКИЙ ОТКАЗ — бот не может стартовать!</b>")
        if self.cube_text:
            lines.append("")
            lines.extend(self.cube_text.split("\n"))
        return "\n".join(lines)


class SelfTest:
    """Запускает все проверки и возвращает SelfTestReport."""

    def __init__(self, config=None, bot=None):
        self.config = config
        self.bot = bot

    async def _notify(self, text: str):
        """Отправка сообщения в Telegram админу (если bot доступен)."""
        try:
            if self.bot and hasattr(self.bot, "bot") and hasattr(self.bot, "config"):
                admin_id = self.bot.config.get("telegram.admin_id")
                if admin_id:
                    await self.bot.bot.send_message(int(admin_id), text, parse_mode="HTML")
        except Exception:
            pass  # TG ещё не подключен — нормально при старте

    async def run_all(self) -> SelfTestReport:
        """Запуск всех тестов последовательно с live-уведомлениями."""
        report = SelfTestReport()
        t0 = time.monotonic()

        await self._notify("🔄 <b>Запуск SelfTest...</b>")

        tests = [
            ("L1",  "Config",             self._test_config),
            ("L2",  "Imports",            self._test_imports),
            ("L3",  "Indicators",         self._test_indicators),
            ("L4",  "Database",           self._test_database),
            ("L5",  "Exchange API",       self._test_exchange),
            ("L6",  "MultiTF Config",     self._test_multi_tf_config),
            ("L7",  "Pivot Calculator",   self._test_pivot_calculator),
            ("L8",  "Trading Intelligence", self._test_intelligence),
            ("L9",  "Strategies",         self._test_strategies),
            ("L10", "Trade Simulator",    self._test_trade_simulator),
            ("L11", "Config Integrity",   self._test_config_integrity),
            ("L12", "Trade Lifecycle",    self._test_trade_lifecycle),
        ]

        for layer, name, test_fn in tests:
            if asyncio.iscoroutinefunction(test_fn):
                result = await test_fn()
            else:
                result = test_fn()
            report.results.append(result)

            # При критическом провале — сразу уведомляем
            if not result.passed and result.critical:
                await self._notify(
                    f"🔴 <b>CRITICAL FAIL [{layer}] {name}</b>\n{result.error[:200]}"
                )

        # L13-L15: Куб Метатрона (сферы + рёбра + feedback loops)
        if self.bot is not None:
            try:
                from core.selftest_cube import run_cube_selftest, format_cube_report
                cube_results = await run_cube_selftest(self.bot)
                report.cube_text = format_cube_report(cube_results)
            except Exception as _ce:
                report.cube_text = f"🔴 Cube selftest ошибка: {_ce}"

        report.total_duration_ms = (time.monotonic() - t0) * 1000

        # Итоговый отчёт в TG
        await self._notify(report.summary_text())

        return report

    # ------------------------------------------------------------------
    # L1: Config
    # ------------------------------------------------------------------
    def _test_config(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            from core.infra.config_loader import config as cfg
            required_keys = [
                "exchanges.default",
                "analysis.check_interval",
                "trading.entry_timeframe",
            ]
            missing = []
            for key in required_keys:
                val = cfg.get(key)
                if val is None:
                    missing.append(key)

            if missing:
                return SelfTestResult(
                    layer="L1", name="Config", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"Отсутствуют ключи: {missing}",
                )

            # Telegram token
            try:
                token = cfg.get_telegram_token()
                if not token or len(token) < 10:
                    return SelfTestResult(
                        layer="L1", name="Config", passed=False, critical=True,
                        duration_ms=(time.monotonic() - t0) * 1000,
                        error="Telegram token отсутствует или невалидный",
                    )
            except Exception as e:
                return SelfTestResult(
                    layer="L1", name="Config", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"Telegram token: {e}",
                )

            exchange = cfg.get("exchanges.default", "?")
            entry_tf = cfg.get("trading.entry_timeframe", "?")
            return SelfTestResult(
                layer="L1", name="Config", passed=True, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=f"OK — exchange={exchange}, entry_tf={entry_tf}",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L1", name="Config", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # L2: Imports
    # ------------------------------------------------------------------
    def _test_imports(self) -> SelfTestResult:
        t0 = time.monotonic()
        errors = []
        modules = [
            "core.indicators.indicators",
            "core.signals.signal_checkers",
            "core.trading_intelligence",
            "core.trading.trade_simulator",
            "core.pivots.pivot_calculator_fixed",
            "core.indicators.divergence_detector",
            "core.infra.entry_config",
            "core.mtf.multi_tf_resolver",
            "core.signals.wt_15m_reversal_scanner",
            "core.indicators.trend_signals",
            "core.pivots.pivot_reversal",
            "core.mtf.mtf_checker",
            "core.ml.auto_calibrator",
            "core.indicators.market_regime",
            "core.trading.regime_strategy",
            "bot.loops.scan_loop",
            "bot.monitoring",
            "web.dashboard_server",
        ]
        import importlib
        for mod_name in modules:
            try:
                importlib.import_module(mod_name)
            except Exception as e:
                errors.append(f"{mod_name}: {type(e).__name__}: {e}")

        if errors:
            return SelfTestResult(
                layer="L2", name="Imports", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error="; ".join(errors[:3]),
            )
        return SelfTestResult(
            layer="L2", name="Imports", passed=True, critical=True,
            duration_ms=(time.monotonic() - t0) * 1000,
            message=f"{len(modules)} модулей OK",
        )

    # ------------------------------------------------------------------
    # L3: Indicators — проверка на синтетических данных
    # ------------------------------------------------------------------
    def _test_indicators(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            from core.indicators.indicators import calculate_wt, calculate_trend, compute_atr, detect_fvg

            n = 100
            np.random.seed(42)
            close = 100 + np.cumsum(np.random.randn(n) * 0.5)
            high = close + np.abs(np.random.randn(n) * 0.3)
            low = close - np.abs(np.random.randn(n) * 0.3)
            open_ = close + np.random.randn(n) * 0.1
            volume = np.random.rand(n) * 1000

            df = pd.DataFrame({
                "open": open_, "high": high, "low": low,
                "close": close, "volume": volume,
            })

            errors = []

            df_wt = calculate_wt(df)
            if "wt1" not in df_wt.columns or "wt2" not in df_wt.columns:
                errors.append("WT: нет колонок wt1/wt2")
            elif df_wt["wt1"].isna().all():
                errors.append("WT: все NaN")

            df_tr = calculate_trend(df.copy(), atr_period=14, factor=1.0)
            if "trend" not in df_tr.columns:
                errors.append("Trend: нет колонки trend")
            elif df_tr["trend"].isna().all():
                errors.append("Trend: все NaN")

            atr = compute_atr(df.copy(), period=14)
            if atr is None:
                errors.append("ATR: None")

            try:
                detect_fvg(df.tail(10))
            except Exception as e:
                errors.append(f"FVG: {e}")

            if errors:
                return SelfTestResult(
                    layer="L3", name="Indicators", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="; ".join(errors),
                )
            return SelfTestResult(
                layer="L3", name="Indicators", passed=True, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                message="WT, Trend, ATR, FVG — OK",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L3", name="Indicators", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # L4: Database — таблицы + схема
    # ------------------------------------------------------------------
    def _test_database(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            import sqlite3
            db_path = "subscriptions.db"
            if self.bot and hasattr(self.bot, "trade_simulator"):
                db_path = self.bot.trade_simulator.db_path

            with sqlite3.connect(db_path) as conn:
                tables = [
                    r[0] for r in
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]

            expected = ["simulated_trades", "pivot_cache", "confluence_states"]
            missing = [t for t in expected if t not in tables]
            warnings = []

            # Проверяем схему simulated_trades
            if "simulated_trades" in tables:
                with sqlite3.connect(db_path) as conn:
                    cols = [r[1] for r in conn.execute("PRAGMA table_info(simulated_trades)").fetchall()]
                    required_cols = [
                        "signal_type", "direction", "entry_price", "stop_loss",
                        "take_profit", "status", "R_multiple", "strategy_type",
                        "sl_source", "tp_source", "decision_trace_json",
                    ]
                    missing_cols = [c for c in required_cols if c not in cols]
                    if missing_cols:
                        warnings.append(f"simulated_trades: нет колонок {missing_cols}")

                    # Проверяем количество открытых сделок
                    open_count = conn.execute(
                        "SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'"
                    ).fetchone()[0]
                    total = conn.execute("SELECT COUNT(*) FROM simulated_trades").fetchone()[0]

            msg_parts = [f"DB OK, таблиц: {len(tables)}, сделок: {total}"]
            if open_count:
                msg_parts.append(f"открытых: {open_count}")
            if missing:
                msg_parts.append(f"нет таблиц: {missing}")
            if warnings:
                msg_parts.append(f"схема: {'; '.join(warnings)}")

            return SelfTestResult(
                layer="L4", name="Database", passed=not warnings, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=", ".join(msg_parts) if not warnings else "",
                error="; ".join(warnings) if warnings else "",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L4", name="Database", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # L5: Exchange API
    # ------------------------------------------------------------------
    async def _test_exchange(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            if self.bot and hasattr(self.bot, "data_collector"):
                dc = self.bot.data_collector
            else:
                from core.infra.config_loader import config as cfg
                from core.infra.data_collector import RealTimeData
                exchange_id = cfg.get("exchanges.default", "bingx")
                dc = RealTimeData(exchange_id=exchange_id)

            markets = await asyncio.wait_for(
                dc.load_markets(min_volume_usd=0), timeout=10,
            )
            if not markets or len(markets) == 0:
                return SelfTestResult(
                    layer="L5", name="Exchange API", passed=False, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="API вернул 0 рынков",
                )
            return SelfTestResult(
                layer="L5", name="Exchange API", passed=True, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=f"Рынков: {len(markets)}",
            )
        except asyncio.TimeoutError:
            return SelfTestResult(
                layer="L5", name="Exchange API", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error="Таймаут 10с",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L5", name="Exchange API", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L6: MultiTF config
    # ------------------------------------------------------------------
    def _test_multi_tf_config(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            from core.infra.entry_config import get_entry_timeframes
            from core.mtf.multi_tf_resolver import validate_multi_tf_config

            cfg = self.config if self.config else None
            tfs = get_entry_timeframes(cfg)
            ok, msg = validate_multi_tf_config(tfs)

            return SelfTestResult(
                layer="L6", name="MultiTF Config", passed=ok, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=msg if ok else "",
                error="" if ok else msg,
            )
        except Exception as e:
            return SelfTestResult(
                layer="L6", name="MultiTF Config", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # L7: Pivot calculator
    # ------------------------------------------------------------------
    def _test_pivot_calculator(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed
            pc = PivotCalculatorFixed(db_path=":memory:")
            pivots = pc.calculate_traditional_pivots(high=110, low=90, close=100)
            if not pivots or "PP" not in pivots:
                return SelfTestResult(
                    layer="L7", name="Pivot Calculator", passed=False, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="calculate_pivots не вернул PP",
                )
            pp = pivots["PP"]
            expected_pp = (110 + 90 + 100) / 3
            if abs(pp - expected_pp) > 0.01:
                return SelfTestResult(
                    layer="L7", name="Pivot Calculator", passed=False, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"PP={pp}, ожидали {expected_pp}",
                )

            # Проверяем кеш пивотов бота
            cache_msg = ""
            if self.bot and hasattr(self.bot, "pivot_calculator"):
                cache_size = len(getattr(self.bot.pivot_calculator, "pivot_cache", {}))
                cache_msg = f", кеш: {cache_size} записей"

            return SelfTestResult(
                layer="L7", name="Pivot Calculator", passed=True, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=f"PP={pp:.2f} OK{cache_msg}",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L7", name="Pivot Calculator", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L8: Trading Intelligence
    # ------------------------------------------------------------------
    def _test_intelligence(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            if self.bot and hasattr(self.bot, "trading_intelligence"):
                ti = self.bot.trading_intelligence
                strategies = list(ti.strategies.keys()) if hasattr(ti, "strategies") else []
                active = getattr(ti, "active_strategy_name", "?")
                return SelfTestResult(
                    layer="L8", name="Trading Intelligence", passed=True, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    message=f"active={active}, стратегий: {len(strategies)}",
                )
            else:
                from core.trading_intelligence import TradingIntelligence
                TradingIntelligence.__new__(TradingIntelligence)
                return SelfTestResult(
                    layer="L8", name="Trading Intelligence", passed=True, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    message="class OK",
                )
        except Exception as e:
            return SelfTestResult(
                layer="L8", name="Trading Intelligence", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L9: Strategies — все заявленные стратегии загружены
    # ------------------------------------------------------------------
    def _test_strategies(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            from core.infra.config_loader import config as cfg
            declared = cfg.get("trading.active_strategies") or []
            if not declared:
                return SelfTestResult(
                    layer="L9", name="Strategies", passed=True, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    message="Нет заявленных стратегий в конфиге",
                )

            # Проверяем что bot.trading_intelligence загрузил все
            loaded = []
            missing = []
            if self.bot and hasattr(self.bot, "trading_intelligence"):
                ti = self.bot.trading_intelligence
                loaded = list(ti.strategies.keys()) if hasattr(ti, "strategies") else []
                missing = [s for s in declared if s not in loaded]
            else:
                # Без бота — проверяем через registry
                from strategies.registry import get_strategy
                for sname in declared:
                    try:
                        get_strategy(sname, {})
                        loaded.append(sname)
                    except Exception:
                        missing.append(sname)

            if missing:
                return SelfTestResult(
                    layer="L9", name="Strategies", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"Не загружены: {missing} (загружены: {loaded})",
                )
            return SelfTestResult(
                layer="L9", name="Strategies", passed=True, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=f"{len(loaded)}/{len(declared)} загружены: {', '.join(loaded)}",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L9", name="Strategies", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L10: Trade Simulator — проверка регистрации/трекинга
    # ------------------------------------------------------------------
    def _test_trade_simulator(self) -> SelfTestResult:
        t0 = time.monotonic()
        try:
            if not (self.bot and hasattr(self.bot, "trade_simulator")):
                return SelfTestResult(
                    layer="L10", name="Trade Simulator", passed=True, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    message="Нет экземпляра (не в контексте бота)",
                )

            ts = self.bot.trade_simulator
            import sqlite3

            with sqlite3.connect(ts.db_path) as conn:
                # Статистика
                row = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open_n,
                        SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) as sl_n,
                        SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END) as win_n
                    FROM simulated_trades
                """).fetchone()
                total, open_n, sl_n, win_n = row
                closed = (win_n or 0) + (sl_n or 0)
                wr = round(win_n / closed * 100, 1) if closed > 0 else 0

                # Последняя сделка
                last = conn.execute(
                    "SELECT created_at FROM simulated_trades ORDER BY id DESC LIMIT 1"
                ).fetchone()
                last_dt = last[0][:16] if last else "—"

            msg = f"Всего: {total}, открытых: {open_n or 0}, WR: {wr}%, последняя: {last_dt}"
            return SelfTestResult(
                layer="L10", name="Trade Simulator", passed=True, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=msg,
            )
        except Exception as e:
            return SelfTestResult(
                layer="L10", name="Trade Simulator", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L11: Config Integrity — ловим скрытые баги конфигурации
    # ------------------------------------------------------------------
    def _test_config_integrity(self) -> SelfTestResult:
        t0 = time.monotonic()
        warnings = []
        try:
            from core.infra.config_loader import config as cfg

            # 1. Проверяем что TradingIntelligence получает ConfigLoader, а не dict
            if self.bot and hasattr(self.bot, "trading_intelligence"):
                ti_config = self.bot.trading_intelligence.config
                if isinstance(ti_config, dict) and not hasattr(ti_config, "get_all"):
                    # plain dict — dot-notation не работает!
                    warnings.append(
                        "TradingIntelligence получил dict вместо ConfigLoader — "
                        "dot-notation (trading.active_strategies) не работает!"
                    )

            # 2. Проверяем критические значения конфига
            checks = {
                "signal_quality.min_strength_register": (1, 100),
                "signal_quality.min_strength": (1, 100),
                "analysis.check_interval": (10, 600),
                "performance.scan_semaphore_size": (1, 100),
            }
            for key, (lo, hi) in checks.items():
                val = cfg.get(key)
                if val is not None:
                    try:
                        v = float(val)
                        if v < lo or v > hi:
                            warnings.append(f"{key}={val} вне диапазона [{lo},{hi}]")
                    except (ValueError, TypeError):
                        pass

            # 3. use_state_machine vs confluence scanner
            use_sm = cfg.get("analysis.confluence.use_state_machine")
            if use_sm is True:
                # state machine должен быть инициализирован
                if self.bot and not hasattr(self.bot, "confluence_sm"):
                    warnings.append("use_state_machine=true, но confluence_sm не найден в bot")

            # 4. Проверяем что все signal types из strategy weights валидны
            weights = cfg.get("strategy.confluence.signal_weights")
            if weights and isinstance(weights, dict):
                from core.signals.signal_models import SignalType
                valid = {st.value for st in SignalType}
                unknown = [k for k in weights if k not in valid]
                if unknown:
                    warnings.append(f"Неизвестные signal_weights: {unknown}")

            if warnings:
                return SelfTestResult(
                    layer="L11", name="Config Integrity", passed=False, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="; ".join(warnings),
                )
            return SelfTestResult(
                layer="L11", name="Config Integrity", passed=True, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                message="Все проверки целостности пройдены",
            )
        except Exception as e:
            return SelfTestResult(
                layer="L11", name="Config Integrity", passed=False, critical=False,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:100],
            )

    # ------------------------------------------------------------------
    # L12: Trade Lifecycle — полный цикл register → open → close → verify
    # ------------------------------------------------------------------
    def _test_trade_lifecycle(self) -> SelfTestResult:
        t0 = time.monotonic()
        test_trade_id = None
        try:
            if not (self.bot and hasattr(self.bot, "trade_simulator")):
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=True, critical=False,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    message="Нет экземпляра TradeSimulator",
                )

            ts = self.bot.trade_simulator
            import sqlite3
            import json
            from types import SimpleNamespace
            from datetime import datetime, timezone

            # --- Шаг 1: Регистрация тестовой сделки ---
            test_symbol = "__SELFTEST__/USDT"
            test_rec = SimpleNamespace(
                symbol=test_symbol,
                entry_price=100.0,
                direction="LONG",
                stop_loss=95.0,       # -5%
                take_profit=115.0,    # +15%, RR=3.0
                tp1_price=None,
                overall_strength=80,
                confidence=0.9,
                timestamp=datetime.now(timezone.utc),
                market_context=None,
                supporting_signals=[],
                sl_source="selftest",
                tp_source="selftest",
                metadata={"strategy_name": "selftest"},
            )
            test_trade_id = ts.register_trade(test_rec, regime="RANGE")

            if test_trade_id is None:
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="register_trade вернул None — сделка не создана!",
                )

            # --- Шаг 2: Проверяем что сделка OPEN в БД ---
            with sqlite3.connect(ts.db_path) as conn:
                row = conn.execute(
                    "SELECT status, direction, entry_price, stop_loss, take_profit, strategy_type "
                    "FROM simulated_trades WHERE id=?",
                    (test_trade_id,),
                ).fetchone()

            if not row:
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"Сделка id={test_trade_id} не найдена в БД после register",
                )

            status, direction, entry, sl, tp, strategy_type = row
            checks = []
            if status != "OPEN":
                checks.append(f"status={status}≠OPEN")
            if direction != "LONG":
                checks.append(f"dir={direction}≠LONG")
            if abs(float(entry) - 100.0) > 0.01:
                checks.append(f"entry={entry}≠100")
            if abs(float(sl) - 95.0) > 0.01:
                checks.append(f"sl={sl}≠95")
            if abs(float(tp) - 115.0) > 0.01:
                checks.append(f"tp={tp}≠115")

            if checks:
                # Удаляем тестовую сделку
                with sqlite3.connect(ts.db_path) as conn:
                    conn.execute("DELETE FROM simulated_trades WHERE id=?", (test_trade_id,))
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"OPEN-проверка: {'; '.join(checks)}",
                )

            # --- Шаг 3: Закрываем сделку (TP) ---
            closed = ts.close_trade(
                trade_id=test_trade_id,
                status="TP",
                exit_price=115.0,
                closed_at=datetime.now(timezone.utc),
            )
            if not closed:
                with sqlite3.connect(ts.db_path) as conn:
                    conn.execute("DELETE FROM simulated_trades WHERE id=?", (test_trade_id,))
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error="close_trade вернул False — не удалось закрыть",
                )

            # --- Шаг 4: Проверяем закрытую сделку ---
            with sqlite3.connect(ts.db_path) as conn:
                row2 = conn.execute(
                    "SELECT status, exit_price, profit_pct, R_multiple "
                    "FROM simulated_trades WHERE id=?",
                    (test_trade_id,),
                ).fetchone()

            close_checks = []
            if row2[0] != "TP":
                close_checks.append(f"status={row2[0]}≠TP")
            if abs(float(row2[1]) - 115.0) > 0.01:
                close_checks.append(f"exit={row2[1]}≠115")
            if row2[2] is None or float(row2[2]) < 14.0:
                close_checks.append(f"profit_pct={row2[2]}≠~15%")
            if row2[3] is None or float(row2[3]) < 2.5:
                close_checks.append(f"R={row2[3]}≠~3.0")

            # --- Шаг 5: Удаляем тестовую сделку ---
            with sqlite3.connect(ts.db_path) as conn:
                conn.execute("DELETE FROM simulated_trades WHERE id=?", (test_trade_id,))

            if close_checks:
                return SelfTestResult(
                    layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    error=f"CLOSE-проверка: {'; '.join(close_checks)}",
                )

            return SelfTestResult(
                layer="L12", name="Trade Lifecycle", passed=True, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                message=f"register→open→close(TP)→verify OK, strategy={strategy_type}, R={float(row2[3]):.1f}",
            )
        except Exception as e:
            # Cleanup при исключении
            if test_trade_id is not None:
                try:
                    import sqlite3 as _sq
                    with _sq.connect(self.bot.trade_simulator.db_path) as _c:
                        _c.execute("DELETE FROM simulated_trades WHERE id=?", (test_trade_id,))
                except Exception:
                    pass
            return SelfTestResult(
                layer="L12", name="Trade Lifecycle", passed=False, critical=True,
                duration_ms=(time.monotonic() - t0) * 1000,
                error=str(e)[:120],
            )


async def run_selftest(config=None, bot=None) -> SelfTestReport:
    """Удобная функция для вызова из bot startup."""
    st = SelfTest(config=config, bot=bot)
    return await st.run_all()
