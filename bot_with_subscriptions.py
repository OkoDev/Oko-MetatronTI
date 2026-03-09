import asyncio
import logging
import platform
import sys
import os
import atexit

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

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    level=getattr(logging, config.get("logging.level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crypto_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass

logger = logging.getLogger(__name__)

# ==============================
# Single-instance lock
# ==============================
_LOCK_FILE = os.path.join(os.path.dirname(__file__) or ".", "bot_instance.lock")


def _acquire_single_instance_lock(lock_path: str = _LOCK_FILE) -> bool:
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))

        def _cleanup():
            try:
                if os.path.exists(lock_path):
                    os.remove(lock_path)
            except Exception:
                pass

        atexit.register(_cleanup)
        return True
    except FileExistsError:
        return False
    except Exception:
        logger.warning("Не удалось создать lock-файл. Продолжаю без блокировки.")
        return True


# ==============================
# Windows fix
# ==============================
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class TradingAlertBot:
    def __init__(self):
        self.token = config.get_telegram_token()
        self.config = config
        self.bot = Bot(token=self.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
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
        self._last_signal = {}  # {(symbol, signal_type): datetime} — для дедупликации
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

        async def _ml_training_loop():
            """Первичное обучение ML через 2 мин после старта, затем каждые 24ч."""
            await asyncio.sleep(120)
            while True:
                try:
                    ok = await self.trading_intelligence.train_ml_models(training_period_days=30)
                    if ok:
                        logger.info("ML-модели успешно обучены/переобучены")
                except Exception as e:
                    logger.warning(f"Ошибка обучения ML: {e}")
                # Этап 7: обучение R-регрессора (требует 100+ закрытых сделок с max_R_possible)
                try:
                    db_path = self.trade_simulator.db_path
                    r_ok = await asyncio.get_event_loop().run_in_executor(
                        None, self.r_predictor.fit, db_path
                    )
                    if r_ok:
                        logger.info(
                            "RPredictor обучен: %d сделок, CV RMSE=%.3f",
                            self.r_predictor._n_samples,
                            self.r_predictor._cv_rmse or 0,
                        )
                except Exception as e:
                    logger.warning("Ошибка обучения RPredictor: %s", e)
                await asyncio.sleep(86400)  # 24 часа

        async def _weekly_report_loop():
            """Отправляет отчёт каждое воскресенье в 20:00 UTC."""
            from datetime import datetime, timezone, timedelta
            from bot.monitoring import send_weekly_report
            while True:
                try:
                    now = datetime.now(timezone.utc)
                    days_to_sunday = (6 - now.weekday()) % 7 or 7
                    target = now.replace(hour=20, minute=0, second=0, microsecond=0)
                    target += timedelta(days=days_to_sunday)
                    await asyncio.sleep((target - now).total_seconds())
                    await send_weekly_report(self)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception("weekly_report_loop: %s", e)
                    await asyncio.sleep(3600)

        async def _run():
            from bot.monitoring import trade_tracker_loop
            from web.dashboard_server import start_dashboard
            asyncio.create_task(trade_tracker_loop(self))
            asyncio.create_task(start_dashboard(
                db_path=self.trade_simulator.db_path,
                config=config,
                data_collector=self.data_collector,
                trade_simulator=self.trade_simulator,
            ))
            asyncio.create_task(_ml_training_loop())
            asyncio.create_task(_weekly_report_loop())
            await self.dp.start_polling(self.bot)

        asyncio.run(_run())


if __name__ == "__main__":
    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        sys.exit(1)
    TradingAlertBot().run()
