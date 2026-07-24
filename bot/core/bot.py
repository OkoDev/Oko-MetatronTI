"""
Класс TradingAlertBot — ядро бота: инициализация зависимостей и запуск цикла.
Точка входа: oko_mtf.py (бывш. bot_with_subscriptions.py, переим. 15.05.2026)
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from core.infra.config_loader import config
from core.db.subscription_manager import SubscriptionManager
from core.db.watchlist_manager import WatchlistManager
from core.infra.data_collector import RealTimeData
from core.indicators.divergence_detector import DivergenceDetector
from core.pivots.pivot_calculator_fixed import PivotCalculatorFixed
from core.trading_intelligence import TradingIntelligence
from core.trading.trade_simulator import TradeSimulator
from core.ml.r_predictor import RPredictor
from core.confluence.confluence_state_machine import ConfluenceStateMachine
from core.mtf.multi_tf_resolver import MultiTFResolver
from core.indicators.bounce_detector import BounceDetector
from core.signals.signal_watch_list import SignalWatchList
from core.context.pair_context import PairContextBus
from core.trading.post_trade_analyser import PostTradeAnalyser
from core.exchange import OrderManager as OrderExecutor
from core.trading.position_sizer import PositionSizer
from core.trading.position_manager import PositionManager
from core.infra.ws_feed import WsFeed
from core.exchange.btc_regime_provider import BTCRegimeProvider
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
        # PROXY-NODE: пул прокси для market-data (None если выключено/.env пуст → direct как было)
        from core.infra.proxy_pool import build_proxy_pool
        _proxy_pool = build_proxy_pool(config)
        self.data_collector = RealTimeData(
            exchange_id=config.get("exchanges.default", "bingx"),
            # config.perf: при proxy on → proxy_pool.overrides (rps=100/sem=30), иначе performance.* база
            api_semaphore_size=int(config.perf("api_semaphore_size", 5)),
            api_rps=float(config.perf("api_rps", 8.0)),
            proxy_pool=_proxy_pool,
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
        # 27.05: weakref bot для shadow_signal_quality (нужен ConfirmationAggregator)
        self.trade_simulator.set_bot_ref(self)
        # DEV-93/DEV-94/DEV-95: Куб Метатрона — Shared Context Bus + PostTradeAnalyser
        self.pair_context = PairContextBus()
        self.post_analyser = PostTradeAnalyser(self.pair_context, self.data_collector)
        self.trade_simulator.set_post_trade_callback(self.post_analyser.on_trade_closed)
        # DEV-222: TG reply при закрытии сделки
        from bot.monitoring import send_trade_close_reply as _tg_reply
        from bot.monitoring import send_tsl_activated_alert as _tg_tsl_alert
        _bot_ref = self
        async def _tg_close_cb(**kwargs):
            await _tg_reply(_bot_ref, **kwargs)
        async def _tg_tsl_cb(**kwargs):
            await _tg_tsl_alert(_bot_ref, **kwargs)
        self.trade_simulator.set_tg_close_callback(_tg_close_cb)
        # DEV-223: TG алерт при активации TSL
        self.trade_simulator.set_tg_tsl_alert_callback(_tg_tsl_cb)
        # Куб: Сфера 10 (Exit Manager) → PairContextBus
        self.trade_simulator._pair_context_bus = self.pair_context

        # DEV-77/78: OrderExecutor + PositionSizer (SIM → VST → LIVE)
        self.order_executor = OrderExecutor(config)
        self.position_sizer = PositionSizer(config)
        _pm_db = getattr(self.subscription_manager, "db_path", "subscriptions.db")
        self.position_manager = PositionManager(db_path=_pm_db)
        logger.info("[Bot] execution_mode=%s", self.order_executor.mode.value)

        # Сфера 9 Куба Метатрона (Phase 1) — TradeRouter: единый узел регистрации.
        # Включается через config.yaml → signal_router.enabled=true после dual_run.
        from core.trading.trade_router import TradeRouter
        self.trade_router = TradeRouter(self)
        _sr_enabled = bool(config.get("signal_router.enabled", False))
        logger.info("[Bot] TradeRouter инициализирован (enabled=%s)", _sr_enabled)

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
        # ARCH-78: BTCRegimeProvider — Сфера 5 (Cross-Market), глобальный BTC 4h режим
        self.btc_regime_provider = BTCRegimeProvider(config=config)
        self.trading_intelligence._btc_provider = self.btc_regime_provider
        # ARCH-72: Feedback Loop — PostTradeAnalyser получает доступ к intelligence + event_bus
        self.post_analyser._intelligence = self.trading_intelligence
        self.post_analyser._event_bus = self.event_bus

        # ═══ КУБ МЕТАТРОНА: HTF детекторы (Сфера 7) ═══
        from core.signals.htf_detectors import TrendChangeDetector, WTCrossHTFDetector, ZoneEntryDetector, WTExtremeDetector
        self._htf_detectors = (TrendChangeDetector(), WTCrossHTFDetector(), ZoneEntryDetector(), WTExtremeDetector())

        # ═══ КУБ: ATR Trend Change Detector (DEV-199) ═══
        from core.signals.atr_change_detector import ATRChangeDetector
        self.atr_change_detector = ATRChangeDetector()

        # ═══ КУБ: Confirmation Aggregator (DEV-201/202) ═══
        from core.intelligence.signal_aggregator import ConfirmationAggregator
        self.confirmation_aggregator = ConfirmationAggregator(window_seconds=600)

        # ═══ КУБ: Sphere Registry (Сфера 12 — Self-Diagnostics) ═══
        from core.context.sphere_registry import SphereRegistry
        self.sphere_registry = SphereRegistry(self.pair_context)

        # ═══ КУБ: Подписки между сферами (mesh-связность) ═══
        self._wire_cube_subscriptions()

        # WsFeed: WebSocket real-time тикеры (фаза 1) + OHLCV для приоритетных пар (фаза 2)
        # WS всегда использует LIVE ключи — VST ключи работают только с REST.
        # WsFeed читает только рыночные данные (не торгует), режим execution_mode не влияет.
        _ws_api_key = os.environ.get("BINGX_API_KEY") or config.get("exchanges.api_keys.bingx.api_key", "")
        _ws_secret  = os.environ.get("BINGX_SECRET_KEY") or config.get("exchanges.api_keys.bingx.secret", "")
        self.ws_feed = WsFeed(
            ohlcv_cache=self.data_collector._engine._cache,
            api_key=_ws_api_key,
            secret=_ws_secret,
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
        from bot.handlers.notif_handlers import get_router as notif_router

        # FSM-роутеры включаются ДО catch-all F.text (core_router)
        self.dp.include_router(sub_router(self))
        self.dp.include_router(pivot_router(self))
        self.dp.include_router(analysis_router(self))
        self.dp.include_router(scan_router(self))
        self.dp.include_router(deep_router(self))     # ARCH-29: /deep SYMBOL [TF]
        self.dp.include_router(notif_router(self))    # /notif + inline toggles
        self.dp.include_router(core_router(self))     # содержит F.text catch-all
        self.dp.include_router(callback_router(self))

    async def _ohlcv_cache_snapshot_loop(self, path: str) -> None:
        """D-069: периодический snapshot OHLCV cache (защита от kill -9)."""
        while True:
            await asyncio.sleep(300)   # каждые 5 минут
            try:
                # min_entries guard: не затирать хороший файл недогретым кэшем (≈3000 прогрет)
                saved = self.data_collector._engine._cache.save_to_disk(path, min_entries=1000)
                logger.debug("[D-069] periodic snapshot: %d entries", saved)
            except Exception as e:
                logger.warning("[D-069] periodic snapshot error: %s", e)

    async def _start_ws_feed(self) -> None:
        """D-053 fix: Запускает WsFeed и автоматически перезапускает при падении.

        D-068: ждёт прогрева пар до 5 мин, потом retry каждую минуту.
        D-053: restart-петля — если ws_feed.start() завершается, перезапускаем через 30s.
        """
        # DEV-230 kill-switch: при ws_enabled=false WsFeed не запускается — поток данных
        # работает на REST (event loop не забивается ccxt.pro watch-задачами). WsFeed-объект
        # существует (get_current_price → fallback, stats() → пустые), соединений нет.
        try:
            from core.infra.config_loader import config as _cfg_ws
            if not _cfg_ws.get("performance.ws_enabled", True):
                logger.warning("[WsFeed] ОТКЛЮЧЁН (performance.ws_enabled=false) — REST-only поток данных (DEV-230)")
                return
        except Exception:
            pass
        # Стартовый wait до 5 мин (300 сек), потом retry каждые 60 сек бесконечно
        for _ in range(300):
            if self.monitored_pairs:
                break
            await asyncio.sleep(1)
        # Если за 5 мин не заполнилось — retry каждую минуту (не блокируем остальную инициализацию)
        retry_count = 0
        while not self.monitored_pairs and retry_count < 30:   # макс 30 мин общий wait
            retry_count += 1
            logger.warning(
                "[WsFeed] monitored_pairs пусты — retry #%d через 60s",
                retry_count,
            )
            await asyncio.sleep(60)
        if not self.monitored_pairs:
            logger.error("[WsFeed] monitored_pairs пусты 30+ мин — WsFeed не запущен")
            return

        # D-053: restart-петля — WsFeed не должен умирать навсегда
        restart_count = 0
        while True:
            pairs = list(self.monitored_pairs)
            # D-066 STABLE (25.05 21:15): откат к Phase D — OHLCV WS только для открытых сделок.
            # Phase F (1×240) дал плато scan_loop 750s. Stable Phase D × 109 пар = 175-238s.
            priority_pairs = []
            try:
                open_trades = self.trade_simulator.get_open_trades()
                priority_pairs = list({t.get("symbol") for t in open_trades if t.get("symbol")})
            except Exception as e:
                logger.debug("[WsFeed] priority_pairs error: %s", e)

            if restart_count == 0:
                logger.info("[WsFeed] Старт: %d пар, %d priority OHLCV (STABLE)", len(pairs), len(priority_pairs))
                asyncio.create_task(self._log_ws_stats_after_warmup())
            else:
                logger.warning(
                    "[WsFeed] D-053: перезапуск #%d: %d пар, %d priority OHLCV",
                    restart_count, len(pairs), len(priority_pairs),
                )

            try:
                self.ws_feed.reset()
                await self.ws_feed.start(pairs, priority_pairs=priority_pairs)
            except asyncio.CancelledError:
                logger.info("[WsFeed] WsFeed отменён — остановка")
                return
            except Exception as e:
                logger.error("[WsFeed] D-053: start() ошибка: %s", e)

            restart_count += 1
            logger.warning("[WsFeed] D-053: WsFeed остановлен — перезапуск через 30s (#%d)", restart_count)
            await asyncio.sleep(30)

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
            # DEV-231 (30.05): event loop профайлер — логает блокирующие callback'и >threshold.
            # Корень: rtt BingX в боте 9-17с при ~1с извне. WS off не помог (DEV-230).
            # Включается через config performance.event_loop_debug: true.
            try:
                from core.infra.config_loader import config as _cfg_el
                if _cfg_el.get("performance.event_loop_debug", False):
                    _threshold = float(_cfg_el.get("performance.slow_callback_threshold_sec", 0.5))
                    _loop = asyncio.get_running_loop()
                    _loop.set_debug(True)
                    _loop.slow_callback_duration = _threshold
                    logger.warning("[EventLoop] DEBUG ON — slow_callback_threshold=%.2fs", _threshold)
                    # Task sampler — раз в 30с логирует топ типов pending tasks.
                    # Если очередь растёт / dominates один тип — это и есть bottleneck.
                    async def _task_sampler():
                        from collections import Counter
                        while True:
                            await asyncio.sleep(30)
                            try:
                                tasks = asyncio.all_tasks()
                                names = Counter()
                                for t in tasks:
                                    try:
                                        coro = t.get_coro()
                                        n = getattr(coro, '__qualname__', None) or getattr(coro, '__name__', 'unknown')
                                    except Exception:
                                        n = 'unknown'
                                    names[n] += 1
                                top = names.most_common(15)
                                logger.warning(
                                    "[TaskSampler] total=%d top15: %s",
                                    len(tasks),
                                    " ".join(f"{n}={c}" for n, c in top),
                                )
                            except Exception as _se:
                                logger.warning("[TaskSampler] error: %s", _se)
                    asyncio.create_task(_task_sampler())
            except Exception as _e:
                logger.warning("[EventLoop] debug setup failed: %s", _e)

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

            # ⚡ PERF-LOOP-DRIFT шаг B (13.06): выделенный торговый event loop за флагом.
            # Шаг 1 — только инфраструктура (loop крутится пустой, никто не использует).
            # Подключение торговых вызовов — шаги 2+. При флаге off — не стартует.
            try:
                from core.infra.trading_loop import init_trading_loop
                _ded = bool(self.config.get("trading.dedicated_loop", False))
                if init_trading_loop(_ded) is not None:
                    logger.info("[Bot] TradingLoop включён (trading.dedicated_loop=true)")
            except Exception as _tle:
                logger.warning("[Bot] TradingLoop init: %s", _tle)

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
            from bot.loops.ml_loop import ml_training_loop, weekly_report_loop, wr_health_check_loop, auto_review_loop, circuit_breaker_loop, morning_digest_loop
            from bot.loops.trigger_loop import run_trigger_loop
            from bot.loops.health_loop import health_check_loop
            from bot.loops.obsidian_loop import obsidian_daily_loop
            from bot.loops.watchlist_loop import watchlist_loop
            from bot.loops.advisor_loop import spawn_advisor   # ARCH-125: AdvisorPort (shadow, gated)
            from web.dashboard_server import start_dashboard
            from core.observability import decision_trace as _dt

            # DEV-203: DecisionTrace — инициализация и фоновый flush
            _dt.configure(self.trade_simulator.db_path)
            asyncio.create_task(_dt.flush_periodically(30))

            # D-069 (25.05): Persistent OHLCV cache — load с диска при старте.
            # Устраняет initial REST tax (~1159s/cycle при пустом cache).
            try:
                _cache_path = "cache/ohlcv_snapshot.pkl"
                _loaded = self.data_collector._engine._cache.load_from_disk(_cache_path)
                if _loaded > 0:
                    logger.info("[D-069] OHLCV cache loaded: %d entries from %s", _loaded, _cache_path)
                # Периодический snapshot каждые 5 мин (страховка от kill -9)
                asyncio.create_task(self._ohlcv_cache_snapshot_loop(_cache_path))
            except Exception as e:
                logger.warning("[D-069] cache load error (не критично): %s", e)

            asyncio.create_task(health_check_loop(self))        # DEV-103: Exchange Health Guard
            asyncio.create_task(trade_tracker_loop(self))
            asyncio.create_task(run_trigger_loop(self))     # DEV-95: Куб Метатрона — OTE/Cascade триггеры
            asyncio.create_task(self.event_bus.consume_loop(self))  # ARCH-70: EventBus Full CALL шина
            asyncio.create_task(self._start_ws_feed())      # WsFeed: real-time тикеры через WebSocket
            try:                                              # EXEC-WS: user-data WS (order/account push), за config-флагом
                from core.exchange.exec_ws_integration import start_exec_ws
                start_exec_ws(self)
            except Exception as _ews_e:
                logger.warning("[EXEC-WS] start error: %s", _ews_e)
            try:                                              # NOTIF: NotificationDispatcher = подписчик шины (LISTENER-CANON)
                from core.notifications.dispatcher import NotificationDispatcher
                from core.context.pair_context import SphereEvent
                self.notif_dispatcher = NotificationDispatcher(self)
                # Подписка на шину вместо прямого вызова из scan_loop:
                # scan_loop публикует SMC_SNAP_UPDATED → subscribe_async → on_smc_snap.
                # 0 строк notif в ядре; новый потребитель = +1 subscribe здесь.
                self.pair_context.subscribe_async(
                    SphereEvent.SMC_SNAP_UPDATED, self.notif_dispatcher.on_smc_snap
                )
                logger.info("[NOTIF] dispatcher подписан на шину (SMC_SNAP_UPDATED)")
            except Exception as _nd_e:
                logger.warning("[NOTIF] dispatcher init error: %s", _nd_e)
            try:                                              # MARKET-WS v2: kline-push WS в ПРОЦЕССЕ (обходит GIL), за флагом
                from core.infra.market_ws_v2 import start_market_ws_v2
                start_market_ws_v2(self)
            except Exception as _mws_e:
                logger.warning("[MarketWS-v2] start error: %s", _mws_e)
            # dashboard.enabled=false → не запускать (диагностика: изоляция нагрузки dashboard на loop)
            if config.get("dashboard.enabled", True):
                _dash_kwargs = dict(
                    db_path=self.trade_simulator.db_path,
                    host=config.get("dashboard.host", "127.0.0.1"),  # SEC-01a: localhost по умолчанию
                    config=config,
                    data_collector=self.data_collector,
                    trade_simulator=self.trade_simulator,
                    bot=self,
                )
                if config.get("dashboard.threaded", False):
                    # PERF-DASH-THREAD: dashboard в отдельном потоке+loop → HTTP не ждёт scan-очередь.
                    # Безопасно: engine per-call connect (WAL), pair_context all_symbols()=снимок,
                    # SSE через _broadcast_threadsafe (cross-loop мост). daemon → умрёт с процессом.
                    import threading

                    def _run_dashboard_thread():
                        _loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(_loop)
                        try:
                            _loop.run_until_complete(start_dashboard(**_dash_kwargs))
                        except Exception as _dte:
                            logger.error("[Dashboard-thread] упал: %s", _dte)

                    threading.Thread(target=_run_dashboard_thread, name="dashboard", daemon=True).start()
                    logger.info("[Dashboard] запущен в ОТДЕЛЬНОМ потоке (threaded=true) — не ждёт scan-очередь")
                else:
                    asyncio.create_task(start_dashboard(**_dash_kwargs))
            else:
                logger.warning("[Dashboard] ОТКЛЮЧЁН (dashboard.enabled=false) — диагностика нагрузки на loop")
            asyncio.create_task(ml_training_loop(self))
            asyncio.create_task(weekly_report_loop(self))
            asyncio.create_task(wr_health_check_loop(self))    # DEV-27: rolling WR monitor
            asyncio.create_task(auto_review_loop(self))        # DEV-12/8.4.9: weekly auto-review
            asyncio.create_task(circuit_breaker_loop(self))   # DEV-156: Circuit Breaker
            asyncio.create_task(obsidian_daily_loop(self))   # Obsidian pipeline: 00:05 UTC
            asyncio.create_task(watchlist_loop(self))         # Watch List: каждые 4ч
            asyncio.create_task(morning_digest_loop(self))   # DEV-224: Утренний дайджест 07:00 UTC
            spawn_advisor(self)   # ARCH-125: AdvisorPort брифинг (gated config advisor.enabled, default off)
            # ═══ ARCH-104: parallel observer для validation новых паттернов в VST/LIVE ═══
            try:
                from bot.loops.arch104_observer_loop import arch104_observer_loop
                asyncio.create_task(arch104_observer_loop(self))   # ARCH-104: каждые 5 мин
                logger.info("[ARCH-104 observer] task spawned")
            except Exception as e:
                logger.warning("[ARCH-104 observer] failed to start: %s", e)
            # ═══ ARCH-128: OTE observer — скелеты сетапов (геометрия OTE → FIRE) ═══
            try:
                from bot.loops.ote_observer_loop import ote_observer_loop
                asyncio.create_task(ote_observer_loop(self))   # ARCH-128: каждые 5 мин
                logger.info("[OTE observer] task spawned")
            except Exception as e:
                logger.warning("[OTE observer] failed to start: %s", e)
            # ═══ OKO-OTE observer — НОВАЯ стратегия (метод Егора, gated config.strategies.oko_ote) ═══
            try:
                from bot.loops.oko_ote_observer_loop import oko_ote_observer_loop
                asyncio.create_task(oko_ote_observer_loop(self))   # gated: enabled=false → не стартует
                logger.info("[OKO-OTE observer] task spawned (gated by config)")
            except Exception as e:
                logger.warning("[OKO-OTE observer] failed to start: %s", e)
            # ═══ DS-ADVISOR — торговый агент DC на VST (25.07 Егор; gated trading.ds_advisor.enabled) ═══
            try:
                from bot.loops.ds_advisor_loop import ds_advisor_loop
                asyncio.create_task(ds_advisor_loop(self))
                logger.info("[DS-ADVISOR] task spawned (gated by config)")
            except Exception as e:
                logger.warning("[DS-ADVISOR] failed to start: %s", e)
            # ═══ RADAR-ARMED — исполнение сетапов радара (gated config.trading.radar_armed) ═══
            try:
                from bot.loops.radar_armed_loop import radar_armed_loop
                asyncio.create_task(radar_armed_loop(self))   # gated: enabled=false → не стартует
                logger.info("[RADAR-ARMED] task spawned (gated by config)")
            except Exception as e:
                logger.warning("[RADAR-ARMED] failed to start: %s", e)
            # ═══ METHOD-V2 — фрактальный вход (ОТКЛЮЧЁН 05.07 look-ahead, gated trading.method_v2) ═══
            try:
                from bot.loops.method_v2_loop import method_v2_loop
                asyncio.create_task(method_v2_loop(self))   # gated: enabled=false → не стартует
                logger.info("[METHOD-V2] task spawned (gated by config)")
            except Exception as e:
                logger.warning("[METHOD-V2] failed to start: %s", e)
            # ═══ METHOD-EGOR — боевой вход по методу Егора (разворот у экстремума + откат + толпа,
            #     замена ote_nested; gated trading.method_egor) ═══
            try:
                from bot.loops.method_egor_loop import method_egor_loop
                asyncio.create_task(method_egor_loop(self))   # gated: enabled=false → не стартует
                logger.info("[METHOD-EGOR] task spawned (gated by config)")
            except Exception as e:
                logger.warning("[METHOD-EGOR] failed to start: %s", e)
            # Автостарт мониторинга ВСЕГДА (не ждём кнопку ТГ — scan стартует сам при
            # запуске бота, независимо от доступности Telegram). Раньше стартовал только
            # headless при падении polling → при доступном TG бот ждал ручной /start.
            self._monitoring_autostarted = False
            try:
                from bot.monitoring import start_monitoring
                from unittest.mock import MagicMock
                fake_msg = MagicMock()
                fake_msg.from_user.id = 1
                fake_msg.from_user.username = "auto"
                fake_msg.from_user.first_name = "Auto"
                fake_msg.from_user.last_name = ""
                async def _noop(*a, **kw): return None
                fake_msg.answer = _noop
                fake_msg.reply = _noop
                await start_monitoring(self, fake_msg)
                self._monitoring_autostarted = True
                logger.info("[Bot] Мониторинг АВТОЗАПУЩЕН при старте (не ждём кнопку ТГ)")
            except Exception as se:
                logger.warning("[Bot] автостарт мониторинга: %s", se)
            try:
                await self.dp.start_polling(self.bot)
            except Exception as e:
                msg = str(e)
                if "TelegramNetworkError" in type(e).__name__ or "Connect call failed" in msg:
                    logger.warning("[Bot] Telegram недоступен — дашборд (scan уже автозапущен)")
                    if not self._monitoring_autostarted:
                        try:
                            from bot.monitoring import start_monitoring
                            from unittest.mock import MagicMock
                            fake_msg = MagicMock()
                            fake_msg.from_user.id = 1
                            fake_msg.from_user.username = "auto"
                            fake_msg.from_user.first_name = "Auto"
                            fake_msg.from_user.last_name = ""
                            async def _noop(*a, **kw): return None
                            fake_msg.answer = _noop
                            fake_msg.reply = _noop
                            await start_monitoring(self, fake_msg)
                            logger.info("[Bot] Мониторинг запущен (headless fallback)")
                        except Exception as se:
                            logger.warning("[Bot] Не удалось автостартовать мониторинг: %s", se)
                    while True:
                        await asyncio.sleep(3600)
                else:
                    raise
            finally:
                # D-069: graceful save OHLCV cache при остановке (Ctrl+C / SIGTERM)
                try:
                    _cache_path = "cache/ohlcv_snapshot.pkl"
                    # min_entries guard: при ранней/холодной остановке не затереть хороший файл
                    _saved = self.data_collector._engine._cache.save_to_disk(_cache_path, min_entries=1000)
                    logger.info("[D-069] OHLCV cache saved: %d entries to %s", _saved, _cache_path)
                except Exception as e:
                    logger.warning("[D-069] cache save error: %s", e)

        asyncio.run(_run())
