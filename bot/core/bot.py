"""
Класс TradingAlertBot — ядро бота: инициализация зависимостей и запуск цикла.
Точка входа: bot_with_subscriptions.py
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from core.config_loader import config
from core.subscription_manager import SubscriptionManager
from core.watchlist_manager import WatchlistManager
from core.data_collector import RealTimeData
from core.divergence_detector import DivergenceDetector
from core.pivot_calculator_fixed import PivotCalculatorFixed
from core.trading_intelligence import TradingIntelligence
from core.trade_simulator import TradeSimulator
from core.r_predictor import RPredictor
from core.confluence_state_machine import ConfluenceStateMachine
from core.multi_tf_resolver import MultiTFResolver
from core.bounce_detector import BounceDetector
from core.signal_watch_list import SignalWatchList
from core.context.pair_context import PairContextBus
from core.trading.post_trade_analyser import PostTradeAnalyser
from core.exchange import OrderManager as OrderExecutor
from core.trading.position_sizer import PositionSizer
from core.trading.position_manager import PositionManager
from core.infra.ws_feed import WsFeed
from bot.menus import MenuHandler

logger = logging.getLogger(__name__)


class TradingAlertBot:
    def __init__(self):
        self.token = config.get_telegram_token()
        self.config = config
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
        )
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)

        self.subscription_manager = SubscriptionManager()
        self.data_collector = RealTimeData(
            exchange_id=config.get("exchanges.default", "bingx"),
            api_semaphore_size=int(config.get("performance.api_semaphore_size", 5)),
            api_rps=float(config.get("performance.api_rps", 8.0)),
        )
        self.divergence_detector = DivergenceDetector()
        self.pivot_calculator = PivotCalculatorFixed(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )
        self.trading_intelligence = TradingIntelligence(
            data_collector=self.data_collector,
            config=config,
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db"),
            pivot_calculator=self.pivot_calculator,  # DEV-45 fix: общий кеш с _prefetch_pivots
        )
        self.menu_handler = MenuHandler(self)
        self.trade_simulator = TradeSimulator(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )
        # DEV-93/DEV-94/DEV-95: Куб Метатрона — Shared Context Bus + PostTradeAnalyser
        self.pair_context = PairContextBus()
        self.post_analyser = PostTradeAnalyser(self.pair_context, self.data_collector)
        self.trade_simulator.set_post_trade_callback(self.post_analyser.on_trade_closed)
        # Куб: Сфера 10 (Exit Manager) → PairContextBus
        self.trade_simulator._pair_context_bus = self.pair_context

        # DEV-77/78: OrderExecutor + PositionSizer (SIM → VST → LIVE)
        self.order_executor = OrderExecutor(config)
        self.position_sizer = PositionSizer(config)
        _pm_db = getattr(self.subscription_manager, "db_path", "subscriptions.db")
        self.position_manager = PositionManager(db_path=_pm_db)
        logger.info("[Bot] execution_mode=%s", self.order_executor.mode.value)

        self.watchlist_manager = WatchlistManager(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )
        # State Machine для confluence (ARCH-03)
        _sm_db = getattr(self.subscription_manager, "db_path", "subscriptions.db")
        self.confluence_sm = ConfluenceStateMachine(db_path=_sm_db)
        self.confluence_sm.load_from_db()

        # Состояние бота
        self.is_monitoring = False
        self.monitor_task = None
        self.monitored_pairs = []
        self.recent_anomalies = {}
        self.recent_signals: dict = {}   # {symbol: [SignalData, ...]} — кеш сигналов из последнего скана
        self.subscribers = set()
        self.signal_counters = {
            "anomaly": 0, "wt_signal": 0, "mtf_alert": 0,
            "trend_signal": 0, "divergence": 0, "pivot_reversal": 0,
            "pivot_alert": 0, "total": 0,
        }
        # Фильтры качества сигналов (Этап 5.1)
        self._last_signal = {}  # {(symbol, signal_type, direction): datetime}
        # Этап 5.2: кеш режима BTC
        self._btc_regime_cache = None
        # Этап 7: R-регрессор (Kelly-sizing)
        self.r_predictor = RPredictor()
        # ARCH-15: Bounce Detector (контртренд-отскоки)
        self.bounce_detector = BounceDetector(config=config)
        # ARCH-13: Multi-TF Conflict Resolver (с bounce support)
        self.multi_tf_resolver = MultiTFResolver(config=config, bounce_detector=self.bounce_detector)
        # DEV-22: WATCH LIST — автоматическое наблюдение и эскалация сигналов
        _wl_ttl = int(config.get("signal_quality.watch_list_ttl_hours", 4))
        self.signal_watch_list = SignalWatchList(ttl_hours=_wl_ttl)

        # DEV-103 / ARCH-65: Exchange Health Guard
        self.exchange_health     = "HEALTHY"   # ExchangeHealth.HEALTHY
        self.exchange_latency_ms = 0.0
        self.down_since          = None        # datetime | None

        # ARCH-70: EventBus — централизованная шина Full CALL
        from core.context.event_bus import EventBus
        self.event_bus = EventBus(config=config)
        # Подключаем EventBus к TradingIntelligence (для wt_verdict_strong триггера)
        self.trading_intelligence._event_bus = self.event_bus
        # Куб: PairContextBus → TradingIntelligence (NarrativeBuilder + wt_verdict persist)
        self.trading_intelligence._pair_context_bus = self.pair_context
        # ARCH-72: Feedback Loop — PostTradeAnalyser получает доступ к intelligence + event_bus
        self.post_analyser._intelligence = self.trading_intelligence
        self.post_analyser._event_bus = self.event_bus

        # ═══ КУБ МЕТАТРОНА: HTF детекторы (Сфера 7) ═══
        from core.signals.htf_detectors import TrendChangeDetector, WTCrossHTFDetector
        self._htf_detectors = (TrendChangeDetector(), WTCrossHTFDetector())

        # ═══ КУБ: Sphere Registry (Сфера 12 — Self-Diagnostics) ═══
        from core.context.sphere_registry import SphereRegistry
        self.sphere_registry = SphereRegistry(self.pair_context)

        # ═══ КУБ: Подписки между сферами (mesh-связность) ═══
        self._wire_cube_subscriptions()

        # WsFeed: WebSocket real-time тикеры (фаза 1) + OHLCV для приоритетных пар (фаза 2)
        self.ws_feed = WsFeed(
            ohlcv_cache=self.data_collector._engine._cache,
        )
        self.data_collector.set_ws_feed(self.ws_feed)  # data_collector.get_current_price() → WS first
        # Куб: WsFeed → PairContextBus (Сфера 2 → Central Hub)
        self.ws_feed._pair_context_bus = self.pair_context

        self._register_routers()

    def _wire_cube_subscriptions(self):
        """
        Куб Метатрона: подписки между сферами.
        Каждая сфера подписывается на события других через PairContextBus.
        Это создаёт mesh-связность — любое событие достигает всех заинтересованных узлов.
        """
        from core.context.pair_context import SphereEvent
        bus = self.pair_context

        # ── Сфера 3 (WT Specialist) подписана на: regime_updated ──────────────
        # При смене режима → verdict может измениться (EXHAUSTION в TREND vs RANGE разное)
        def _on_regime_for_wt(symbol, data):
            state = bus.get(symbol)
            # Если режим сменился на REVERSAL mode — WT specialist должен знать
            if data.get("mode") == "REVERSAL" and state.wt_verdict == "TREND_CONTINUATION":
                logger.debug("[Cube] %s: regime→REVERSAL, WT verdict stale", symbol)
        bus.subscribe(SphereEvent.REGIME_UPDATED, _on_regime_for_wt)

        # ── Сфера 6 (Regime) подписана на: wt_snap_updated ───────────────────
        # WT snap на 4h даёт сигнал о reversal mode
        def _on_wt_for_regime(symbol, data):
            wt_4h = data.get("4h")
            if wt_4h:
                wt1 = wt_4h.get("wt1", 0)
                state = bus.get(symbol)
                if abs(wt1) > 60 and state.reversal_mode != "REVERSAL":
                    logger.debug("[Cube] %s: WT 4h=%+.0f → potential REVERSAL", symbol, wt1)
        bus.subscribe(SphereEvent.WT_SNAP_UPDATED, _on_wt_for_regime)

        # ── Сфера 9 (Narrative Builder) подписана на: все ключевые события ────
        # Narrative Builder реагирует на каждый новый сигнал
        def _on_signal_for_narrative(symbol, data):
            state = bus.get(symbol)
            # Обновляем narrative-relevant fields
            sig_type = data.get("signal_type", "")
            if sig_type and state.last_signal_type != sig_type:
                logger.debug("[Cube] %s: signal %s → narrative update pending", symbol, sig_type)
        bus.subscribe(SphereEvent.SIGNAL_DETECTED, _on_signal_for_narrative)

        # ── Сфера 10 (Exit Manager) подписана на: wt_snap, regime, divergence ─
        # При дивергенции — Exit Manager может подтянуть TSL
        def _on_div_for_exit(symbol, data):
            state = bus.get(symbol)
            if state.open_trade_id and state.tsl_active:
                logger.debug("[Cube] %s: divergence → Exit Manager aware (trade #%d)",
                             symbol, state.open_trade_id)
        bus.subscribe(SphereEvent.DIVERGENCE_FOUND, _on_div_for_exit)

        # ── Сфера 11 (Post-Trade) подписана на: position_closed ──────────────
        # Когда позиция закрывается — cascade обновляется
        def _on_close_for_cascade(symbol, data):
            state = bus.get(symbol)
            logger.debug("[Cube] %s: position closed → cascade_count=%d", symbol, state.cascade_count)
        bus.subscribe(SphereEvent.POSITION_CLOSED, _on_close_for_cascade)

        # ── Сфера 12 (Diagnostics) подписана на: все события ─────────────────
        # SphereRegistry отслеживает здоровье всех сфер
        if hasattr(self, 'sphere_registry'):
            self.sphere_registry.wire_subscriptions(bus)

        # ── Cross-subscriptions для mesh: Сфера 5 ↔ Сфера 7 ─────────────────
        # Cross-Market (BTC regime) влияет на все сигналы
        def _on_btc_for_signals(symbol, data):
            state = bus.get(symbol)
            state.btc_regime = data.get("btc_regime")
        bus.subscribe(SphereEvent.CROSS_MARKET, _on_btc_for_signals)

        # ── Pivot touch → Exit Manager (TP targets near pivot) ───────────────
        def _on_pivot_for_exit(symbol, data):
            state = bus.get(symbol)
            if state.open_trade_id:
                logger.debug("[Cube] %s: pivot touch → TP check (trade #%d)",
                             symbol, state.open_trade_id)
        bus.subscribe(SphereEvent.PIVOT_TOUCH, _on_pivot_for_exit)

        _n_subs = sum(len(v) for v in bus._subscribers.values())
        logger.info("[Cube] mesh-связность: %d подписок на %d типов событий",
                    _n_subs, len(bus._subscribers))

    def _register_routers(self):
        from bot.handlers.subscription_handlers import get_router as sub_router
        from bot.handlers.pivot_handlers import get_router as pivot_router
        from bot.handlers.analysis_handlers import get_router as analysis_router
        from bot.handlers.scan_handlers import get_router as scan_router
        from bot.handlers.deep_analysis_handler import get_router as deep_router
        from bot.handlers.core_handlers import get_router as core_router
        from bot.handlers.callback_handlers import get_router as callback_router

        # FSM-роутеры включаются ДО catch-all F.text (core_router)
        self.dp.include_router(sub_router(self))
        self.dp.include_router(pivot_router(self))
        self.dp.include_router(analysis_router(self))
        self.dp.include_router(scan_router(self))
        self.dp.include_router(deep_router(self))     # ARCH-29: /deep SYMBOL [TF]
        self.dp.include_router(core_router(self))     # содержит F.text catch-all
        self.dp.include_router(callback_router(self))

    async def _start_ws_feed(self) -> None:
        """Запускает WsFeed после прогрева пар (ждёт до 30 сек пока monitored_pairs заполнится)."""
        for _ in range(30):
            if self.monitored_pairs:
                break
            await asyncio.sleep(1)
        if not self.monitored_pairs:
            logger.warning("[WsFeed] monitored_pairs пусты — WsFeed не запущен")
            return
        pairs = list(self.monitored_pairs)
        # Фаза 2: OHLCV для пар с открытыми сделками (get_open_trades — sync)
        priority_pairs = []
        try:
            open_trades = self.trade_simulator.get_open_trades()
            priority_pairs = list({t.get("symbol") for t in open_trades if t.get("symbol")})
        except Exception as e:
            logger.debug("[WsFeed] priority_pairs error: %s", e)
        logger.info("[WsFeed] Старт: %d пар, %d priority OHLCV", len(pairs), len(priority_pairs))
        # DEV-101: логируем stats через 5 мин после старта для верификации
        asyncio.create_task(self._log_ws_stats_after_warmup())
        await self.ws_feed.start(pairs, priority_pairs=priority_pairs)

    async def _log_ws_stats_after_warmup(self) -> None:
        """DEV-101: через 5 мин после старта WS — логируем статус для верификации."""
        await asyncio.sleep(300)
        stats = self.ws_feed.stats()
        if stats["active_tickers"] > 0:
            logger.info(
                "[WsFeed] ✅ LIVE | tickers=%d updates=%d errors=%d uptime=%ds",
                stats["active_tickers"], stats["ticker_updates"],
                stats["errors"], stats["uptime_sec"],
            )
        else:
            logger.warning("[WsFeed] ⚠️ НЕТ активных тикеров через 5 мин — проверь ccxt.pro")

    def run(self):
        logger.info("Запуск бота с поддержкой подписок...")

        async def _run():
            # === SELFTEST при старте (ARCH-14) ===
            from core.selftest import run_selftest
            selftest_report = await run_selftest(config=self.config, bot=self)
            logger.info("SelfTest завершён: %d/%d пройдено за %.0fms",
                        sum(1 for r in selftest_report.results if r.passed),
                        len(selftest_report.results),
                        selftest_report.total_duration_ms)
            if not selftest_report.critical_passed:
                for r in selftest_report.critical_failed:
                    logger.error("CRITICAL SELFTEST FAIL [%s] %s: %s", r.layer, r.name, r.error)
                logger.error("Бот не может стартовать — критические тесты провалены!")
                return
            if selftest_report.failed:
                for r in selftest_report.failed:
                    logger.warning("SELFTEST WARN [%s] %s: %s", r.layer, r.name, r.error)
            # Сохраняем отчёт для /status команды
            self._selftest_report = selftest_report

            # DEV-145: синхронизация live_orders с реальными позициями при старте
            _exec_mode = self.config.get("trading.execution_mode", "sim_only")
            if _exec_mode in ("vst", "live"):
                try:
                    from core.trading.order_reconciler import OrderReconciler
                    _reconciler = OrderReconciler(
                        position_manager=self.position_manager,
                        order_manager=self.order_executor,
                        execution_mode=_exec_mode,
                    )
                    _rec_stats = await _reconciler.reconcile()
                    logger.info("[Bot] live_orders reconcile: ok=%d closed=%d",
                                _rec_stats.get("ok", 0), _rec_stats.get("closed", 0))
                except Exception as _re:
                    logger.warning("[Bot] reconcile error (не критично): %s", _re)

            from bot.monitoring import trade_tracker_loop
            from bot.loops.ml_loop import ml_training_loop, weekly_report_loop, wr_health_check_loop, auto_review_loop, circuit_breaker_loop
            from bot.loops.trigger_loop import run_trigger_loop
            from bot.loops.health_loop import health_check_loop
            from web.dashboard_server import start_dashboard

            asyncio.create_task(health_check_loop(self))        # DEV-103: Exchange Health Guard
            asyncio.create_task(trade_tracker_loop(self))
            asyncio.create_task(run_trigger_loop(self))     # DEV-95: Куб Метатрона — OTE/Cascade триггеры
            asyncio.create_task(self.event_bus.consume_loop(self))  # ARCH-70: EventBus Full CALL шина
            asyncio.create_task(self._start_ws_feed())      # WsFeed: real-time тикеры через WebSocket
            asyncio.create_task(start_dashboard(
                db_path=self.trade_simulator.db_path,
                config=config,
                data_collector=self.data_collector,
                trade_simulator=self.trade_simulator,
                bot=self,
            ))
            asyncio.create_task(ml_training_loop(self))
            asyncio.create_task(weekly_report_loop(self))
            asyncio.create_task(wr_health_check_loop(self))    # DEV-27: rolling WR monitor
            asyncio.create_task(auto_review_loop(self))        # DEV-12/8.4.9: weekly auto-review
            asyncio.create_task(circuit_breaker_loop(self))   # DEV-156: Circuit Breaker
            await self.dp.start_polling(self.bot)

        asyncio.run(_run())
