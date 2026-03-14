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
        self.data_collector = RealTimeData(exchange_id=config.get("exchanges.default", "bingx"))
        self.divergence_detector = DivergenceDetector()
        self.pivot_calculator = PivotCalculatorFixed(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )
        self.trading_intelligence = TradingIntelligence(
            data_collector=self.data_collector,
            config=config.get_all(),
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db"),
        )
        self.menu_handler = MenuHandler(self)
        self.trade_simulator = TradeSimulator(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )
        self.watchlist_manager = WatchlistManager(
            db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db")
        )

        # Состояние бота
        self.is_monitoring = False
        self.monitor_task = None
        self.monitored_pairs = []
        self.recent_anomalies = {}
        self.recent_signals: dict = {}   # {symbol: [SignalData, ...]} — кеш сигналов из последнего скана
        self.subscribers = set()
        self.signal_counters = {
            "anomaly": 0, "wt_signal": 0, "mtf_signal": 0, "mtf_alert": 0,
            "trend_signal": 0, "divergence": 0, "pivot_reversal": 0,
            "pivot_alert": 0, "total": 0,
        }
        # Фильтры качества сигналов (Этап 5.1)
        self._last_signal = {}  # {(symbol, signal_type, direction): datetime}
        # Этап 5.2: кеш режима BTC
        self._btc_regime_cache = None
        # Этап 7: R-регрессор (Kelly-sizing)
        self.r_predictor = RPredictor()

        self._register_routers()

    def _register_routers(self):
        from bot.handlers.subscription_handlers import get_router as sub_router
        from bot.handlers.pivot_handlers import get_router as pivot_router
        from bot.handlers.analysis_handlers import get_router as analysis_router
        from bot.handlers.scan_handlers import get_router as scan_router
        from bot.handlers.core_handlers import get_router as core_router
        from bot.handlers.callback_handlers import get_router as callback_router

        # FSM-роутеры включаются ДО catch-all F.text (core_router)
        self.dp.include_router(sub_router(self))
        self.dp.include_router(pivot_router(self))
        self.dp.include_router(analysis_router(self))
        self.dp.include_router(scan_router(self))
        self.dp.include_router(core_router(self))     # содержит F.text catch-all
        self.dp.include_router(callback_router(self))

    def run(self):
        logger.info("Запуск бота с поддержкой подписок...")

        async def _run():
            from bot.monitoring import trade_tracker_loop
            from bot.loops.ml_loop import ml_training_loop, weekly_report_loop
            from web.dashboard_server import start_dashboard

            asyncio.create_task(trade_tracker_loop(self))
            asyncio.create_task(start_dashboard(
                db_path=self.trade_simulator.db_path,
                config=config,
                data_collector=self.data_collector,
                trade_simulator=self.trade_simulator,
            ))
            asyncio.create_task(ml_training_loop(self))
            asyncio.create_task(weekly_report_loop(self))
            await self.dp.start_polling(self.bot)

        asyncio.run(_run())
