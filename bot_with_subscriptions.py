import asyncio
import logging
import platform
import sys
import os
import atexit
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Импорты из нашего проекта
from core.config_loader import config
from core.subscription_manager import SubscriptionManager, SubscriptionTier
from core.data_collector import RealTimeData
from core.anomaly_detector import AnomalyDetector
from core.message_builder import anomaly_message, wt_message, mtf_message, tv_link
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import DivergenceDetector, divergence_message
from core.pivot_levels import PivotLevels, pivot_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.pivot_calculator_fixed import PivotCalculatorFixed
from core.trading_intelligence import TradingIntelligence, format_intelligence_message
from core.trade_simulator import TradeSimulator
from core.keyboards import main_menu
from core.menu_handler import MenuHandler

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    level=getattr(logging, config.get("logging.level", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crypto_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Настраиваем кодировку консоли для эмодзи/UTF-8 на Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="ignore")
except Exception:
    pass
logger = logging.getLogger(__name__)

# ==============================
# Simple single-instance lock (PID file)
# ==============================
_LOCK_FILE = os.path.join(os.path.dirname(__file__) or ".", "bot_instance.lock")

def _acquire_single_instance_lock(lock_path: str = _LOCK_FILE) -> bool:
    """Create a lock file to prevent multiple bot instances.

    Returns True if lock acquired; False if another instance is running.
    """
    try:
        # Exclusive create; fails if file already exists
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
        # If anything unexpected happens, do not block startup, but log it
        logger.warning("Не удалось создать lock-файл. Продолжаю без блокировки.")
        return True

# ==============================
# Windows fix
# ==============================
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ==============================
# FSM States для пивотов
# ==============================
class PivotStates(StatesGroup):
    waiting_for_pivots = State()
    waiting_for_check = State()

class SubscriptionStates(StatesGroup):
    waiting_for_payment = State()

class AIAnalysisStates(StatesGroup):
    waiting_for_symbol = State()
    waiting_for_symbol_search = State()

class TradingAlertBot:
    """
    Основной класс бота для мониторинга криптовалют с поддержкой подписок
    """

    def __init__(self):
        # --- Инициализация бота ---
        self.token = config.get_telegram_token()
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)

        # --- Менеджер подписок ---
        self.subscription_manager = SubscriptionManager()

        # --- Ядро системы ---
        self.data_collector = RealTimeData(exchange_id=config.get("exchanges.default", "bingx"))
        self.detector = AnomalyDetector(
            volume_multiplier=config.get("analysis.volume_multiplier", 50.0),
            price_threshold=config.get("analysis.price_threshold", 40.0)
        )
        self.divergence_detector = DivergenceDetector()
        # Используем исправленный калькулятор для всех операций с пивотами
        self.pivot_calculator = PivotCalculatorFixed()  # Заменено на исправленный модуль
        self.pivot_calculator_fixed = PivotCalculatorFixed()
        
        # --- Trading Intelligence Layer ---
        self.trading_intelligence = TradingIntelligence(
            data_collector=self.data_collector,
            config=config.get_all()
        )
        
        # --- Обработчик расширенного меню ---
        self.menu_handler = MenuHandler(self)

        # --- Trade Simulator (отслеживание исходов по SL/TP) ---
        self.trade_simulator = TradeSimulator(db_path=getattr(self.subscription_manager, "db_path", "subscriptions.db"))

        # --- Состояние бота ---
        self.is_monitoring = False
        self.monitor_task = None
        self.monitored_pairs = []
        self.recent_anomalies = {}
        self.subscribers = set()
        
        # --- Счетчики сигналов ---
        self.signal_counters = {
            "anomaly": 0,
            "wt_signal": 0,
            "mtf_signal": 0,
            "mtf_alert": 0,
            "trend_signal": 0,
            "divergence": 0,
            "pivot_reversal": 0,
            "pivot_alert": 0,
            "total": 0
        }
        
        # --- Регистрация команд ---
        self._register_commands()

    def _register_commands(self):
        """Регистрирует все команды бота"""
        # Основные команды
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_monitor, Command("monitor"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.cmd_top, Command("top"))
        self.dp.message.register(self.cmd_reset_stats, Command("reset"))
        
        # Команды подписок
        self.dp.message.register(self.cmd_subscribe, Command("subscribe"))
        self.dp.message.register(self.cmd_unsubscribe, Command("unsubscribe"))
        self.dp.message.register(self.cmd_my_subscription, Command("my_subscription"))
        self.dp.message.register(self.cmd_buy_subscription, Command("buy_subscription"))
        
        # Команды для пивотов
        self.dp.message.register(self.cmd_request_pivots, Command("pivots"))
        self.dp.message.register(self.cmd_request_check, Command("check_pivot"))
        
        # Команды для комплексного анализа
        self.dp.message.register(self.cmd_intelligence, Command("intelligence"))

        # FSM обработчики
        self.dp.message.register(self.process_show_pivots, PivotStates.waiting_for_pivots)
        self.dp.message.register(self.process_check_pivot, PivotStates.waiting_for_check)
        self.dp.message.register(self.process_payment, SubscriptionStates.waiting_for_payment)
        self.dp.message.register(self.process_symbol_input, AIAnalysisStates.waiting_for_symbol)
        self.dp.message.register(self.process_symbol_search, AIAnalysisStates.waiting_for_symbol_search)

        # Универсальный обработчик всех кнопок меню с глубоким логированием
        self.dp.message.register(self.handle_any_button, F.text)
        
        # Обработчик callback кнопок (inline)
        self.dp.callback_query.register(self.handle_callback_query)

    # ==============================
    # Команды подписок
    # ==============================
    async def cmd_subscribe(self, message: Message):
        """Подписка на сигналы (бесплатная)"""
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        
        # Добавляем пользователя в базу
        self.subscription_manager.add_user(user_id, username, first_name, last_name)
        
        self.subscribers.add(user_id)
        await message.answer(
            "✅ Вы подписаны на бесплатные сигналы!\n\n"
            "📊 <b>Что включено:</b>\n"
            "• 5 сигналов в день\n"
            "• Только аномалии объёма/цены\n\n"
            "💎 <b>Для большего:</b>\n"
            "• /buy_subscription - купить подписку\n"
            "• /my_subscription - моя подписка",
            reply_markup=main_menu()
        )

    async def cmd_unsubscribe(self, message: Message):
        """Отписка от сигналов"""
        user_id = message.from_user.id
        self.subscribers.discard(user_id)
        await message.answer("✅ Вы отписаны от всех сигналов.", reply_markup=main_menu())

    async def cmd_my_subscription(self, message: Message):
        """Показывает информацию о подписке"""
        user_id = message.from_user.id
        sub_info = self.subscription_manager.get_subscription_info(user_id)
        
        # Получаем конфигурацию подписок
        sub_config = config.get_subscription_config()
        current_tier = sub_info['tier'].lower()
        
        if current_tier in sub_config:
            tier_info = sub_config[current_tier]
            price = tier_info.get('price', 0)
            signals = tier_info.get('signals', [])
        else:
            price = 0
            signals = ['anomaly']
        
        # Форматируем список сигналов
        signal_names = {
            'anomaly': '🚨 Аномалии',
            'wt_signal': '📊 WT сигналы',
            'mtf_signal': '🔄 MTF сигналы',
            'mtf_alert': '🎯 MTF точки разворота',
            'trend_signal': '📈 Тренд-сигналы',
            'divergence': '💎 Дивергенции',
            'all': '🌟 Все сигналы'
        }
        
        signal_list = []
        if 'all' in signals:
            signal_list = ['🌟 Все доступные сигналы']
        else:
            signal_list = [signal_names.get(s, s) for s in signals]
        
        parts = [
            f"💎 <b>МОЯ ПОДПИСКА</b>",
            f"Уровень: <b>{sub_info['tier']}</b>",
            f"Статус: {sub_info['status']}",
            f"Цена: ${price}/месяц",
            "",
            f"📊 <b>Сигналы сегодня:</b>",
            f"Отправлено: {sub_info['signals_today']}/{sub_info['signals_limit']}",
            "",
            f"🎯 <b>Доступные сигналы:</b>"
        ]
        
        for signal in signal_list:
            parts.append(f"  • {signal}")
        
        if sub_info['expires']:
            parts.append(f"\n⏰ Истекает: {sub_info['expires']}")
        
        parts.extend([
            "",
            "💡 <b>Команды:</b>",
            "/buy_subscription - купить подписку",
            "/subscribe - подписаться бесплатно"
        ])
        
        await message.answer("\n".join(parts), reply_markup=main_menu())

    async def cmd_buy_subscription(self, message: Message, state: FSMContext):
        """Покупка подписки"""
        sub_config = config.get_subscription_config()
        
        parts = [
            "💎 <b>ПОДПИСКИ НА СИГНАЛЫ</b>",
            "",
            "🆓 <b>БЕСПЛАТНО</b>",
            "• 5 сигналов в день",
            "• Только аномалии",
            "• Цена: $0/месяц",
            "",
            "💎 <b>BASIC - $9.99/месяц</b>",
            "• 10 сигналов в день",
            "• Аномалии + WT + MTF",
            "• Уведомления в Telegram",
            "",
            "🚀 <b>PREMIUM - $29.99/месяц</b>",
            "• 50 сигналов в день",
            "• Все типы сигналов",
            "• Приоритетные уведомления",
            "",
            "👑 <b>PRO - $99.99/месяц</b>",
            "• Неограниченно сигналов",
            "• Все функции",
            "• Веб-панель управления",
            "",
            "💳 <b>Для покупки:</b>",
            "1. Выберите уровень подписки",
            "2. Отправьте скриншот оплаты",
            "3. Получите доступ к сигналам",
            "",
            "📞 <b>Контакты для оплаты:</b>",
            "• Telegram: @your_username",
            "• Email: your@email.com",
            "",
            "Введите номер подписки (1-3) или 'cancel' для отмены:"
        ]
        
        await message.answer("\n".join(parts), reply_markup=ReplyKeyboardRemove())
        await state.set_state(SubscriptionStates.waiting_for_payment)

    async def process_payment(self, message: Message, state: FSMContext):
        """Обработка выбора подписки"""
        text = message.text.strip().lower()
        
        if text == 'cancel':
            await message.answer("❌ Покупка отменена.", reply_markup=main_menu())
            await state.clear()
            return
        
        # Маппинг номеров на уровни
        tier_mapping = {
            '1': 'basic',
            '2': 'premium', 
            '3': 'pro'
        }
        
        if text in tier_mapping:
            tier = tier_mapping[text]
            user_id = message.from_user.id
            
            # Создаем подписку (в реальном проекте здесь была бы проверка оплаты)
            success = self.subscription_manager.create_subscription(user_id, tier, 30)
            
            if success:
                await message.answer(
                    f"✅ Подписка {tier.upper()} активирована!\n"
                    f"Срок действия: 30 дней\n\n"
                    f"Теперь вы получаете расширенные сигналы!",
                    reply_markup=main_menu()
                )
            else:
                await message.answer(
                    "❌ Ошибка активации подписки. Попробуйте позже.",
                    reply_markup=main_menu()
                )
        else:
            await message.answer(
                "❌ Неверный номер. Введите 1, 2, 3 или 'cancel'",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        await state.clear()

    # ==============================
    # Основные команды (адаптированные)
    # ==============================
    async def cmd_start(self, message: Message):
        """Приветственное сообщение + меню"""
        user_id = message.from_user.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        
        # Добавляем пользователя в базу
        self.subscription_manager.add_user(user_id, username, first_name, last_name)
        
        self.subscribers.add(user_id)
        await message.answer(
            "👋 <b>Добро пожаловать в Crypto Volume Bot!</b>\n\n"
            "🚀 <b>Я анализирую криптовалюты и отправляю торговые сигналы:</b>\n"
            "• 🚨 Аномалии объёма и цены\n"
            "• 📊 WT сигналы (Wavetrend)\n"
            "• 🔄 MTF анализ (мультитаймфрейм)\n"
            "• 💎 Дивергенции\n"
            "• 📊 Пивотные уровни\n\n"
            "💎 <b>Подписки:</b>\n"
            "• Бесплатно: 5 сигналов/день\n"
            "• Premium: 50 сигналов/день\n\n"
            "Выберите действие:",
            reply_markup=main_menu()
        )

    async def cmd_help(self, message: Message):
        """Вывод справки по командам"""
        await message.answer(
            "📚 <b>СПРАВКА ПО КОМАНДАМ</b>\n\n"
            "<b>🔧 Основные:</b>\n"
            "/start - Главное меню\n"
            "/monitor - Запуск/остановка мониторинга\n"
            "/stats - Статистика бота\n"
            "/top - Топ-10 по объёму\n"
            "/reset - Сбросить счетчики\n\n"
            "<b>💎 Подписки:</b>\n"
            "/subscribe - Подписаться бесплатно\n"
            "/unsubscribe - Отписаться\n"
            "/my_subscription - Моя подписка\n"
            "/buy_subscription - Купить подписку\n\n"
            "<b>📊 Анализ:</b>\n"
            "/pivots - Недельные и дневные пивоты\n"
            "/check_pivot - Проверка близости к пивотам\n\n"
            "<b>🎯 Типы сигналов:</b>\n"
            "🚨 Аномалии - всплески объёма/цены\n"
            "📊 WT - сигналы по Wavetrend\n"
            "🔄 MTF - мультитаймфрейм анализ\n"
            "🎯 MTF Точки разворота - продвинутый анализ\n"
            "📈 Тренд-сигналы - работа по тренду\n"
            "💎 Дивергенции - расхождения цены и индикатора\n"
            "📊 Пивоты - уровни поддержки/сопротивления\n"
            "🔄 Развороты от пивотов - недельные уровни + FVG",
            reply_markup=main_menu()
        )

    # ==============================
    # Остальные команды (адаптированные под подписки)
    # ==============================
    async def cmd_monitor(self, message: Message):
        """Запуск или остановка мониторинга"""
        if self.is_monitoring:
            await self.stop_monitoring(message)
        else:
            await self.start_monitoring(message)

    async def cmd_stats(self, message: Message):
        """Вывод расширенной статистики"""
        uptime = "N/A"
        if hasattr(self, "start_time") and self.start_time:
            delta = datetime.now() - self.start_time
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            uptime = f"{delta.days}д {hours}ч {minutes}м"
        
        # Получаем информацию о подписке пользователя
        user_id = message.from_user.id
        sub_info = self.subscription_manager.get_subscription_info(user_id)
        
        stats = [
            "📊 <b>СТАТИСТИКА БОТА</b>",
            "",
            f"{'✅ Активен' if self.is_monitoring else '⏹ Остановлен'}",
            f"⏱ Время работы: {uptime}",
            "",
            "<b>📈 Мониторинг:</b>",
            f"• Отслеживаемых пар: {len(self.monitored_pairs)}",
            f"• Подписчиков: {len(self.subscribers)}",
            "",
            f"<b>💎 Ваша подписка:</b>",
            f"• Уровень: {sub_info['tier']}",
            f"• Сигналов сегодня: {sub_info['signals_today']}/{sub_info['signals_limit']}",
            "",
            "<b>🎯 Обнаружено сигналов:</b>",
            f"• 🚨 Аномалий: {self.signal_counters['anomaly']}",
            f"• 📊 WT сигналов: {self.signal_counters['wt_signal']}",
            f"• 🔄 MTF базовых: {self.signal_counters['mtf_signal']}",
            f"• 🎯 MTF точек разворота: {self.signal_counters['mtf_alert']}",
            f"• 📈 Тренд-сигналов: {self.signal_counters['trend_signal']}",
            f"• 💎 Дивергенций: {self.signal_counters['divergence']}",
            f"• 🔄 Разворотов от пивотов: {self.signal_counters['pivot_reversal']}",
            f"• 📊 Пивот-алертов: {self.signal_counters['pivot_alert']}",
            f"• <b>📌 Всего: {self.signal_counters['total']}</b>",
            "",
            f"💾 Сохранено аномалий в кэше: {len(self.recent_anomalies)}"
        ]
        
        await message.answer("\n".join(stats), reply_markup=main_menu())

    def _resolve_symbol_for_intelligence(self, symbol: str):
        """
        Преобразует ввод пользователя (BTC, BTCUSDT и т.д.) в символ биржи.
        Возвращает (target_symbol, display_symbol) или (None, display_symbol).
        """
        symbol = symbol.strip().upper()
        if not symbol or len(symbol) < 2:
            return None, symbol or "?"
        simple_usdt = symbol if symbol.endswith("USDT") else f"{symbol}USDT"
        normalized = self.data_collector.normalize_symbol(symbol)
        slash_usdt = f"{simple_usdt.replace('USDT', '')}/USDT"
        if not self.monitored_pairs:
            return None, symbol
        candidates = [normalized, slash_usdt + ":USDT", slash_usdt, simple_usdt]
        for cand in candidates:
            if cand in self.monitored_pairs:
                return cand, symbol
        base = simple_usdt.replace("USDT", "")
        for p in self.monitored_pairs:
            if p.startswith(base + "/USDT"):
                return p, symbol
        return None, symbol

    async def _run_intelligence_analysis(self, message: Message, target_symbol: str, display_symbol: str, user_id: int):
        """
        Выполняет комплексный анализ и отправляет результат в Telegram.
        Используется и из /intelligence, и из AI-меню (ввод символа).
        """
        analysis_msg = await message.answer(
            f"🔍 <b>Анализирую {display_symbol}...</b>\n"
            "Собираю данные и выполняю комплексный анализ...",
            reply_markup=main_menu()
        )
        try:
            recommendation = await self.trading_intelligence.analyze_symbol(target_symbol)
            if not recommendation:
                error_text = (
                    f"❌ Не удалось выполнить анализ для {display_symbol}.\n"
                    "Возможно, недостаточно данных."
                )
                try:
                    await analysis_msg.edit_text(error_text)
                except Exception:
                    await message.answer(error_text, reply_markup=main_menu())
                return
            intelligence_message = format_intelligence_message(recommendation)
            try:
                await analysis_msg.edit_text(intelligence_message)
            except Exception:
                await message.answer(intelligence_message, reply_markup=main_menu())
            try:
                await message.answer("Выберите действие:", reply_markup=main_menu())
            except Exception:
                pass
            self.subscription_manager.increment_signal_count(user_id, "intelligence")
            self.signal_counters["total"] += 1
            # Регистрация сделки для симуляции (отслеживание SL/TP)
            try:
                self.trade_simulator.register_trade(recommendation)
            except Exception as tr_err:
                logger.debug("TradeSimulator register_trade: %s", tr_err)
        except Exception as e:
            logger.exception(f"Ошибка комплексного анализа для {display_symbol}")
            error_text = f"❌ Ошибка анализа {display_symbol}: {str(e)}"
            try:
                await analysis_msg.edit_text(error_text)
            except Exception:
                await message.answer(error_text, reply_markup=main_menu())
            await message.answer("Попробуйте другой символ", reply_markup=main_menu())

    async def cmd_intelligence(self, message: Message):
        """Комплексный анализ символа с использованием Trading Intelligence Layer"""
        user_id = message.from_user.id
        
        # Проверяем подписку
        if not self.subscription_manager.can_receive_signal(user_id, "intelligence"):
            await message.answer(
                "❌ Превышен лимит сигналов для вашей подписки.\n"
                "💎 Обновите подписку для получения большего количества сигналов.",
                reply_markup=main_menu()
            )
            return
        
        # Получаем текст сообщения
        text = message.text.strip()
        
        if len(text.split()) < 2:
            await message.answer(
                "🤖 <b>Комплексный анализ</b>\n\n"
                "Использование: <code>/intelligence BTCUSDT</code>\n\n"
                "Эта команда выполняет комплексный анализ символа, объединяя:\n"
                "• Аномалии объема\n"
                "• Wavetrend сигналы\n"
                "• Мультитаймфреймовый анализ\n"
                "• Трендовые сигналы\n"
                "• Дивергенции\n"
                "• Пивотные уровни\n\n"
                "Результат: единая торговая рекомендация с оценкой силы и риска.",
                reply_markup=main_menu()
            )
            return
        
        symbol = text.split()[1].upper()

        # Убедимся, что список пар загружен
        if not self.monitored_pairs:
            pairs = await self.data_collector.load_markets()
            self.monitored_pairs = pairs or []

        target_symbol, display_symbol = self._resolve_symbol_for_intelligence(symbol)
        if not target_symbol:
            examples = "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]])
            await message.answer(
                f"❌ Пара '{display_symbol}' не найдена.\n\n"
                f"Попробуйте из списка:\n{examples}\n\n"
                f"<code>Или просто: BTC, ETH, SOL...</code>",
                reply_markup=main_menu()
            )
            return
        
        await self._run_intelligence_analysis(message, target_symbol, display_symbol, user_id)

    # ==============================
    # Остальные методы (адаптированные)
    # ==============================
    async def start_monitoring(self, message: Message):
        """Запуск фонового мониторинга"""
        if self.is_monitoring:
            await message.answer("⚠️ Мониторинг уже запущен.", reply_markup=main_menu())
            return
        
        user_id = message.from_user.id
        # Автоматически добавляем пользователя в подписчики, если его еще нет
        if user_id not in self.subscribers:
            self.subscribers.add(user_id)
            self.subscription_manager.add_user(
                user_id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name
            )
            logger.info(f"Пользователь {user_id} автоматически добавлен в подписчики при старте мониторинга")
        
        pairs = await self.data_collector.load_markets()
        if not pairs:
            await message.answer("❌ Не удалось загрузить пары.", reply_markup=main_menu())
            return
        
        self.monitored_pairs = pairs
        self.is_monitoring = True
        self.start_time = datetime.now()
        self.monitor_task = asyncio.create_task(self.monitor_market())
        
        await message.answer(
            f"✅ Запущен мониторинг {len(self.monitored_pairs)} пар.\n"
            f"📡 Отслеживаю: аномалии, WT, MTF, тренд-сигналы и дивергенции\n\n"
            f"💎 <b>Ваша подписка:</b> {self.subscription_manager.get_subscription_info(message.from_user.id)['tier']}",
            reply_markup=main_menu()
        )

    async def stop_monitoring(self, message: Message):
        """Остановка мониторинга"""
        if not self.is_monitoring:
            await message.answer("⚠️ Мониторинг не запущен.", reply_markup=main_menu())
            return
        
        self.is_monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
        await self.data_collector.stop()
        await message.answer("⏹ Мониторинг остановлен.", reply_markup=main_menu())

    async def monitor_market(self):
        """Основной цикл мониторинга с проверкой подписок"""
        try:
            asyncio.create_task(self.data_collector.fetch_candles())
            while self.is_monitoring:
                await self.check_anomalies()
                await self.check_wt_signals()
                await self.check_mtf_signals()
                await self.check_mtf_alerts()
                await self.check_trend_signals()
                await self.check_divergences()
                await self.check_pivot_reversals()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            logger.info("Мониторинг остановлен")
            raise
        except Exception:
            logger.exception("Ошибка в monitor_market")

    # ==============================
    # Проверки с учетом подписок
    # ==============================
    async def check_anomalies(self):
        """Проверка аномалий с учетом подписок"""
        found = []
        for sym in self.monitored_pairs:
            try:
                is_anom, info = self.detector.check_spike(sym, self.data_collector)
                if is_anom:
                    found.append((sym, info))
                    self.recent_anomalies[sym] = {"timestamp": datetime.now(), "info": info}
                    self.signal_counters["anomaly"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_spike для {sym}")
        # Для найденных аномалий запускаем комплексный AI-анализ.
        for sym, info in found:
            raw_text = anomaly_message(sym, info)
            await self._broadcast_intelligence_alert(sym, raw_text, "anomaly")

    async def check_wt_signals(self):
        """Проверка WT сигналов с учетом подписок"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await self.detector.check_wt_signal(sym, self.data_collector)
                if is_sig:
                    logger.info(f"WT сигнал обнаружен для {sym}: {info.get('type', 'N/A')}")
                    info["volume_details"] = list(self.data_collector.volume_history.get(sym, []))[-5:]
                    raw_text = wt_message(sym, info)
                    await self._broadcast_intelligence_alert(sym, raw_text, "wt_signal")
                    self.signal_counters["wt_signal"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_wt_signal для {sym}")

    async def check_mtf_signals(self):
        """Проверка MTF сигналов с учетом подписок"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await self.detector.check_mtf_signal(sym, self.data_collector)
                if is_sig:
                    info["volume_details"] = list(self.data_collector.volume_history.get(sym, []))[-5:]
                    raw_text = mtf_message(sym, info)
                    await self._broadcast_intelligence_alert(sym, raw_text, "mtf_signal")
                    self.signal_counters["mtf_signal"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_mtf_signal для {sym}")

    async def check_mtf_alerts(self):
        """Проверка MTF алертов с учетом подписок"""
        for sym in self.monitored_pairs:
            try:
                snapshot = await collect_mtf_data(sym, self.data_collector)
                if not snapshot:
                    continue
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    raw_text = mtf_alert_message(sym, snapshot, sig)
                    await self._broadcast_intelligence_alert(sym, raw_text, "mtf_alert")
                    self.signal_counters["mtf_alert"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_mtf_alerts для {sym}")

    async def check_trend_signals(self):
        """Проверка тренд-сигналов с учетом подписок"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await check_trend_following_signal(
                    sym, self.data_collector, self.divergence_detector, self.pivot_calculator
                )
                if is_sig:
                    raw_text = trend_signal_message(sym, info)
                    await self._broadcast_intelligence_alert(sym, raw_text, "trend_signal")
                    self.signal_counters["trend_signal"] += 1
                    self.signal_counters["total"] += 1
                    logger.info(f"[{sym}] Обнаружен тренд-сигнал: {info.get('pattern')}")
            except Exception:
                logger.exception(f"Ошибка check_trend_signals для {sym}")

    async def check_divergences(self):
        """Проверка дивергенций с учетом подписок"""
        timeframes = ["15m", "1h"]
        
        for sym in self.monitored_pairs:
            for tf in timeframes:
                try:
                    has_div, div_info = await self.divergence_detector.detect_divergence(
                        sym, self.data_collector, timeframe=tf
                    )
                    if has_div:
                        raw_text = divergence_message(sym, div_info)
                        await self._broadcast_intelligence_alert(sym, raw_text, "divergence")
                        self.signal_counters["divergence"] += 1
                        self.signal_counters["total"] += 1
                        logger.info(f"[{sym}] Обнаружена дивергенция на {tf}: {div_info.get('type')}")
                        break
                except Exception:
                    logger.exception(f"Ошибка check_divergences для {sym} {tf}")

    async def check_pivot_reversals(self):
        """Проверка разворотов от пивотов с учетом подписок"""
        for sym in self.monitored_pairs:
            try:
                has_signal, info = await check_pivot_level_signal(
                    sym, self.data_collector, self.pivot_calculator
                )
                if has_signal:
                    raw_text = pivot_level_signal_message(sym, info)
                    await self._broadcast_intelligence_alert(sym, raw_text, "pivot_reversal")
                    self.signal_counters["pivot_reversal"] += 1
                    self.signal_counters["total"] += 1
                    logger.info(f"[{sym}] Вход от уровня: {info.get('level')} R:R={info.get('rr_ratio', 0):.1f}")
            except Exception:
                logger.exception(f"Ошибка check_pivot_reversals для {sym}")

    # ==============================
    # Новые методы для подписок
    # ==============================
    async def _broadcast_intelligence_alert(self, symbol: str, raw_text: str, signal_type: str):
        """
        Пытается отправить комплексный AI-сигнал по символу.
        Если AI-анализ не удался или не дал рекомендации, отправляет сырой текст.
        В случае успешной рекомендации регистрирует сделку в TradeSimulator.
        """
        recommendation = None
        try:
            recommendation = await self.trading_intelligence.analyze_symbol(symbol)
        except Exception as e:
            logger.exception(f"Ошибка AI-анализа для {symbol} при сигнале {signal_type}: {e}")

        text = raw_text
        if recommendation:
            try:
                text = format_intelligence_message(recommendation)
            except Exception as e:
                logger.exception(f"Ошибка форматирования AI-сообщения для {symbol}: {e}")
                text = raw_text

        # Рассылка с учетом подписок и лимитов
        await self.broadcast_with_subscription_check(text, signal_type)

        # Регистрируем сделку только если есть полноценная рекомендация
        if recommendation:
            try:
                self.trade_simulator.register_trade(recommendation)
            except Exception as e:
                logger.debug(f"TradeSimulator register_trade для {symbol} ({signal_type}): {e}")

    async def broadcast_with_subscription_check(self, text: str, signal_type: str):
        """Рассылка с проверкой подписок"""
        if not self.subscribers:
            logger.warning(f"Нет подписчиков для отправки сигнала {signal_type}")
            return
        
        logger.info(f"Отправка сигнала {signal_type} для {len(self.subscribers)} подписчиков")
        
        sent_count = 0
        for uid in list(self.subscribers):
            try:
                # Проверяем подписку пользователя
                if not self.subscription_manager.can_receive_signal(uid, signal_type):
                    logger.debug(f"Пользователь {uid} не может получить сигнал {signal_type}")
                    continue
                
                # Проверяем дневной лимит
                if not self.subscription_manager.can_send_signal_today(uid):
                    logger.debug(f"Пользователь {uid} достиг дневного лимита сигналов")
                    continue
                
                # Отправляем сообщение
                await self.bot.send_message(chat_id=uid, text=text, disable_web_page_preview=True)
                sent_count += 1
                logger.info(f"Сигнал {signal_type} отправлен пользователю {uid}")
                
                # Записываем отправку сигнала
                self.subscription_manager.record_signal_sent(uid, signal_type)
                
            except Exception as e:
                logger.exception(f"Ошибка отправки сообщения {uid}: {e}")
        
        if sent_count == 0:
            logger.warning(f"Сигнал {signal_type} не был отправлен ни одному подписчику")
        else:
            logger.info(f"Сигнал {signal_type} отправлен {sent_count} подписчикам")

    # ==============================
    # Остальные методы (без изменений)
    # ==============================
    async def cmd_top(self, message: Message):
        """Вывод топ-10 пар по объёму"""
        if not self.is_monitoring:
            await message.answer("⚠️ Мониторинг не запущен.", reply_markup=main_menu())
            return
        
        volumes = {}
        for sym in self.monitored_pairs:
            vhist = self.data_collector.volume_history.get(sym, [])
            if vhist:
                volumes[sym] = vhist[-1]
        
        sorted_volumes = sorted(volumes.items(), key=lambda x: x[1], reverse=True)
        lines = ["📊 <b>ТОП-10 пар по объёму</b>"]
        for i, (sym, vol) in enumerate(sorted_volumes[:10], 1):
            lines.append(f"{i}. {sym}: {vol:.2f}")
        
        await message.answer("\n".join(lines), reply_markup=main_menu())

    async def cmd_reset_stats(self, message: Message):
        """Сброс счетчиков статистики"""
        self.signal_counters = {
            "anomaly": 0,
            "wt_signal": 0,
            "mtf_signal": 0,
            "mtf_alert": 0,
            "trend_signal": 0,
            "divergence": 0,
            "pivot_reversal": 0,
            "pivot_alert": 0,
            "total": 0
        }
        self.recent_anomalies = {}
        if hasattr(self, "start_time"):
            self.start_time = datetime.now()
        
        await message.answer(
            "✅ Счетчики статистики сброшены!",
            reply_markup=main_menu()
        )

    # ==============================
    # Обработка кнопок меню
    # ==============================
    async def menu_handler(self, message: Message, state: FSMContext):
        """Реакция на кнопки меню"""
        text = (message.text or "").strip()
        
        if text == "🟢 Запустить мониторинг":
            await self.start_monitoring(message)
        elif text == "⏹ Остановить мониторинг":
            await self.stop_monitoring(message)
        elif text == "📊 Статистика":
            await self.cmd_stats(message)
        elif text in ("🏆 Топ", "🔝 Топ", "🏆 ТОП-10 по объему"):
            await self.cmd_top(message)
        elif text in ("📚 Справка", "ℹ️ Помощь"):
            await self.cmd_help(message)
        elif text == "📊 MTF Snapshot":
            await self.cmd_mtf_snapshot(message)
        elif text == "✅ Подписаться":
            await self.cmd_subscribe(message)
        elif text == "❌ Отписаться":
            await self.cmd_unsubscribe(message)
        elif text == "📊 Пивоты":
            await self.cmd_request_pivots(message, state)
        elif text == "🔍 Проверить пивоты":
            await self.cmd_request_check(message, state)

    # ==============================
    # Остальные методы (адаптированные под подписки)
    # ==============================
    async def cmd_mtf_snapshot(self, message: Message):
        """Вывод снимка MTF (по первой паре)"""
        if not self.monitored_pairs:
            await message.answer("Нет загруженных пар — запустите мониторинг.", reply_markup=main_menu())
            return
        
        target = self.monitored_pairs[0]
        snapshot = await collect_mtf_data(target, self.data_collector)
        if not snapshot:
            await message.answer("Нет данных для snapshot.", reply_markup=main_menu())
            return
        
        order = ["3m", "5m", "15m", "45m", "1h", "4h", "1d"]
        available = [tf for tf in order if tf in snapshot]
        lines = [f"📊 <b>MTF Snapshot</b> — {target}", "<pre>TF   Trend  WT1/WT2    Zone</pre>"]
        for tf in available:
            d = snapshot[tf]
            lines.append(f"{tf:>3}  {d['trend']:^5}  {d['wt1']:.1f}/{d['wt2']:.1f}    {d['zone']}")
        
        await message.answer("\n".join(lines), reply_markup=main_menu())

    # ==============================
    # Методы для пивотов (адаптированные)
    # ==============================
    async def cmd_request_pivots(self, message: Message, state: FSMContext):
        """Команда /pivots - показ недельных и дневных пивотов"""
        if not self.monitored_pairs:
            await message.answer(
                "⚠️ Сначала запустите мониторинг /monitor",
                reply_markup=main_menu()
            )
            return
        
        examples = "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]])
        
        await message.answer(
            f"📊 <b>НЕДЕЛЬНЫЕ И ДНЕВНЫЕ ПИВОТЫ</b>\n\n"
            f"💬 Введите тиккер монеты:\n\n"
            f"<i>Примеры:</i>\n{examples}\n\n"
            f"<code>Или просто: BTC, ETH, SOL...</code>",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(PivotStates.waiting_for_pivots)
        logger.info(f"Пользователь {message.from_user.id} запросил пивоты")

    async def cmd_request_check(self, message: Message, state: FSMContext):
        """Команда /check_pivot - проверка близости к пивотам"""
        if not self.monitored_pairs:
            await message.answer(
                "⚠️ Сначала запустите мониторинг /monitor",
                reply_markup=main_menu()
            )
            return
        
        examples = "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]])
        
        await message.answer(
            f"🔍 <b>ПРОВЕРКА БЛИЗОСТИ К ПИВОТАМ</b>\n\n"
            f"💬 Введите тиккер монеты для проверки:\n\n"
            f"<i>Примеры:</i>\n{examples}\n\n"
            f"<code>Или просто: BTC, ETH, SOL...</code>",
            reply_markup=ReplyKeyboardRemove()
        )
        
        await state.set_state(PivotStates.waiting_for_check)
        logger.info(f"Пользователь {message.from_user.id} запросил проверку пивотов")

    async def process_show_pivots(self, message: Message, state: FSMContext):
        """Обработка ввода тиккера для ПОКАЗА ПИВОТОВ"""
        user_input = message.text.strip().upper()
        logger.info(f"Получен тиккер для пивотов: {user_input}")
        
        # Поиск пары
        target = self._find_pair(user_input)
        
        if not target:
            await message.answer(
                f"❌ Пара '{user_input}' не найдена.\n\n"
                f"Попробуйте из списка:\n" + "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]]),
                reply_markup=main_menu()
            )
            await state.clear()
            return
        
        await message.answer(f"⏳ Расчет недельных и дневных пивотов для {target}...")
        
        try:
            # Получаем пивоты
            pivots_data = await self.pivot_calculator_fixed.get_multi_timeframe_pivots(
                target, self.data_collector
            )
            
            if not pivots_data:
                await message.answer(
                    f"❌ Не удалось рассчитать пивоты для {target}",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            
            # Получаем текущую цену
            df = await self.data_collector.get_ohlcv(target, "1m", limit=1)
            current_price = float(df['close'].iloc[-1]) if df is not None and not df.empty else 0
            
            # Форматируем сообщение
            msg = self.pivot_calculator_fixed.format_pivot_message(
                target, pivots_data, current_price
            )
            
            await message.answer(msg, disable_web_page_preview=True, reply_markup=main_menu())
            logger.info(f"Пивоты отправлены для {target}")
            
        except Exception as e:
            logger.exception(f"Ошибка в process_show_pivots для {target}")
            await message.answer(
                f"❌ Ошибка при расчете пивотов:\n{str(e)}",
                reply_markup=main_menu()
            )
        
        await state.clear()

    async def process_check_pivot(self, message: Message, state: FSMContext):
        """Обработка ввода тиккера для ПРОВЕРКИ БЛИЗОСТИ"""
        user_input = message.text.strip().upper()
        logger.info(f"Получен тиккер для проверки: {user_input}")
        
        # Поиск пары
        target = self._find_pair(user_input)
        
        if not target:
            await message.answer(
                f"❌ Пара '{user_input}' не найдена.\n\n"
                f"Попробуйте из списка:\n" + "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]]),
                reply_markup=main_menu()
            )
            await state.clear()
            return
        
        await message.answer(f"⏳ Проверка близости к пивотам для {target}...")
        
        try:
            # Получаем пивоты
            pivots_data = await self.pivot_calculator_fixed.get_multi_timeframe_pivots(
                target, self.data_collector
            )
            
            if not pivots_data or '1W' not in pivots_data:
                await message.answer(
                    f"❌ Не удалось рассчитать пивоты для {target}",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            
            weekly_pivots = pivots_data['1W']
            confluence = pivots_data.get('confluence', [])
            
            # Получаем текущую цену
            df = await self.data_collector.get_ohlcv(target, "1m", limit=1)
            
            if df is None or df.empty:
                await message.answer(
                    f"❌ Не удалось получить цену для {target}",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            
            current_price = float(df['close'].iloc[-1])
            
            # Проверяем близость к уровням
            near_level = self.pivot_calculator_fixed.is_near_level(
                current_price, weekly_pivots, threshold_percent=1.0
            )
            
            # Проверяем конфлюэнцию
            has_confluence = False
            if near_level and confluence:
                for c in confluence:
                    if c['weekly_level'] == near_level['level']:
                        has_confluence = True
                        break
            
            parts = [
                "🎯 <b>ЦЕНА У НЕДЕЛЬНОГО ПИВОТА!</b>" if near_level else "🔍 <b>ПРОВЕРКА БЛИЗОСТИ К ПИВОТАМ</b>",
                f"Пара: {tv_link(target, interval=240)}",
                f"Цена: {current_price:.6f}",
                ""
            ]
            
            if near_level:
                parts.append(f"<b>Уровень: {near_level['level']}</b>")
                parts.append(f"Тип: {near_level['level_type']}")
                parts.append(f"Цена уровня: {near_level['price']:.6f}")
                parts.append(f"Расстояние: {near_level['distance_percent']:.3f}%")
                
                if has_confluence:
                    parts.append("")
                    parts.append("⭐️ <b>БОНУС: Есть конфлюэнция с дневным!</b>")
                
                parts.append("")
                parts.append("<b>🎯 ТОРГОВЫЙ ПЛАН:</b>")
                
                if near_level['level_type'] == 'support':
                    parts.append("")
                    parts.append("📈 <b>Сценарий LONG (от поддержки):</b>")
                    parts.append("  • Ждём подтверждения разворота")
                    parts.append("  • Вход после пробоя локального максимума")
                    parts.append("  • Стоп за уровень поддержки")
                elif near_level['level_type'] == 'resistance':
                    parts.append("")
                    parts.append("📉 <b>Сценарий SHORT (от сопротивления):</b>")
                    parts.append("  • Ждём подтверждения разворота")
                    parts.append("  • Вход после пробоя локального минимума")
                    parts.append("  • Стоп за уровень сопротивления")
                else:  # pivot
                    parts.append("")
                    parts.append("⚡️ <b>Цена у PIVOT POINT - ключевой уровень!</b>")
                    parts.append("  • Ждём пробоя в любую сторону")
                    parts.append("  • Вход по направлению пробоя")
                    parts.append("  • Стоп за противоположную сторону")
            else:
                parts.append("✅ Цена далеко от пивотных уровней")
                parts.append("Ближайший уровень >1% от текущей цены")
            
            await message.answer("\n".join(parts), disable_web_page_preview=True, reply_markup=main_menu())
            logger.info(f"Проверка близости отправлена для {target}")
            
        except Exception as e:
            logger.exception(f"Ошибка в process_check_pivot для {target}")
            await message.answer(
                f"❌ Ошибка при проверке:\n{str(e)}",
                reply_markup=main_menu()
            )
        
        await state.clear()

    def _find_pair(self, ticker: str) -> str:
        """Умный поиск пары по тиккеру"""
        ticker = ticker.upper().strip()
        
        # 1. Точное совпадение
        if ticker in self.monitored_pairs:
            return ticker
        
        # 2. Поиск по началу (BTC → BTC/USDT:USDT)
        for pair in self.monitored_pairs:
            if pair.startswith(ticker + "/"):
                return pair
        
        # 3. Поиск внутри строки
        for pair in self.monitored_pairs:
            if ticker in pair:
                return pair
        
        return None

    # ==============================
    # Запуск бота
    # ==============================
    # ==============================
    # Обработчики расширенного меню
    # ==============================
    
    async def handle_main_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок главного меню"""
        await self.menu_handler.handle_main_menu_buttons(message, state)
    
    async def handle_monitoring_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню мониторинга"""
        await self.menu_handler.handle_monitoring_menu_buttons(message, state)
    
    async def handle_ai_analysis_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню AI анализа"""
        await self.menu_handler.handle_ai_analysis_menu_buttons(message, state)
    
    async def handle_signals_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню сигналов"""
        await self.menu_handler.handle_signals_menu_buttons(message, state)
    
    async def handle_pivots_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню пивотов"""
        await self.menu_handler.handle_pivots_menu_buttons(message, state)
    
    async def handle_risk_management_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню управления рисками"""
        await self.menu_handler.handle_risk_management_menu_buttons(message, state)
    
    async def handle_history_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню исторического анализа"""
        await self.menu_handler.handle_history_menu_buttons(message, state)
    
    async def handle_subscriptions_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню подписок"""
        await self.menu_handler.handle_subscriptions_menu_buttons(message, state)
    
    async def handle_settings_menu_buttons(self, message: Message, state: FSMContext):
        """Обработка кнопок меню настроек"""
        await self.menu_handler.handle_settings_menu_buttons(message, state)
    
    async def handle_any_button(self, message: Message, state: FSMContext):
        """Универсальный обработчик всех кнопок с глубоким логированием"""
        await self.menu_handler.handle_any_button(message, state)
    
    async def handle_callback_query(self, callback_query):
        """Обработчик callback кнопок (inline) с глубоким логированием"""
        from aiogram.types import CallbackQuery
        
        user_id = callback_query.from_user.id
        username = callback_query.from_user.username or "Unknown"
        data = callback_query.data
        
        logger.info(f"🔍 [CALLBACK] Получен callback от {username} ({user_id}): '{data}'")
        
        try:
            # Логируем детали callback
            logger.debug(f"📝 [CALLBACK] Детали: user_id={user_id}, username={username}, data='{data}', message_id={callback_query.message.message_id}")
            
            # Обрабатываем различные типы callback
            if data.startswith("ai_"):
                await self._handle_ai_callback(callback_query)
            elif data.startswith("signal_"):
                await self._handle_signal_callback(callback_query)
            elif data.startswith("risk_"):
                await self._handle_risk_callback(callback_query)
            elif data.startswith("history_"):
                await self._handle_history_callback(callback_query)
            elif data.startswith("sub_"):
                await self._handle_subscription_callback(callback_query)
            elif data.startswith("select_symbol_"):
                await self._handle_symbol_selection_callback(callback_query)
            elif data.startswith("timeframe_"):
                await self._handle_timeframe_callback(callback_query)
            elif data.startswith("confirm_") or data.startswith("cancel_"):
                await self._handle_confirmation_callback(callback_query)
            else:
                logger.warning(f"❌ [CALLBACK] Неизвестный callback: '{data}' от {username}")
                await callback_query.answer("❌ Неизвестная команда")
                
        except Exception as e:
            logger.error(f"💥 [CALLBACK] Ошибка при обработке callback '{data}' от {username}: {e}")
            logger.exception("Полная трассировка ошибки:")
            await callback_query.answer("❌ Произошла ошибка при обработке команды")
    
    async def _handle_ai_callback(self, callback_query):
        """Обработка AI callback кнопок"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"🧠 [AI_CALLBACK] Обработка AI callback '{data}' для {username}")
        
        if data == "ai_intelligence":
            await callback_query.answer("🧠 Запуск комплексного анализа...")
            await callback_query.message.answer("🧠 <b>Комплексный AI анализ</b>\n\nВведите символ для анализа (например: BTC, ETH, SOL):")
        elif data == "ai_ml_predictions":
            await callback_query.answer("🤖 Запуск ML предсказаний...")
            await callback_query.message.answer("🤖 <b>ML Предсказания</b>\n\nМашинное обучение для прогнозирования движения цен.")
        elif data == "ai_performance":
            await callback_query.answer("📊 Анализ эффективности AI...")
            await callback_query.message.answer("📊 <b>Эффективность AI</b>\n\nАнализ производительности машинного обучения...")
        elif data == "ai_retrain":
            await callback_query.answer("🔄 Обновление ML моделей...")
            await callback_query.message.answer("🔄 <b>Обновление моделей</b>\n\nПереобучение ML моделей на новых данных...")
        elif data == "ai_ml_stats":
            await callback_query.answer("📚 ML статистика...")
            await callback_query.message.answer("📚 <b>ML Статистика</b>\n\nСтатистика работы машинного обучения...")
        elif data == "ai_settings":
            await callback_query.answer("⚙️ Настройки AI...")
            await callback_query.message.answer("⚙️ <b>Настройки AI</b>\n\nКонфигурация параметров машинного обучения...")
        else:
            await callback_query.answer("❌ Неизвестная AI команда")
    
    async def _handle_signal_callback(self, callback_query):
        """Обработка сигнальных callback кнопок"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"📈 [SIGNAL_CALLBACK] Обработка сигнального callback '{data}' для {username}")
        await callback_query.answer(f"📈 Обработка сигнала: {data}")
    
    async def _handle_risk_callback(self, callback_query):
        """Обработка риск-менеджмент callback кнопок"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"🛡️ [RISK_CALLBACK] Обработка риск callback '{data}' для {username}")
        await callback_query.answer(f"🛡️ Управление рисками: {data}")
    
    async def _handle_history_callback(self, callback_query):
        """Обработка исторического анализа callback кнопок"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"📚 [HISTORY_CALLBACK] Обработка истории callback '{data}' для {username}")
        await callback_query.answer(f"📚 Исторический анализ: {data}")
    
    async def _handle_subscription_callback(self, callback_query):
        """Обработка подписочных callback кнопок"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"💎 [SUBSCRIPTION_CALLBACK] Обработка подписки callback '{data}' для {username}")
        await callback_query.answer(f"💎 Подписка: {data}")
    
    async def _handle_symbol_selection_callback(self, callback_query):
        """Обработка выбора символа"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        symbol = data.replace("select_symbol_", "")
        
        logger.info(f"🎯 [SYMBOL_CALLBACK] Выбран символ '{symbol}' для {username}")
        await callback_query.answer(f"🎯 Выбран символ: {symbol}")
    
    async def _handle_timeframe_callback(self, callback_query):
        """Обработка выбора таймфрейма"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        timeframe = data.replace("timeframe_", "")
        
        logger.info(f"⏰ [TIMEFRAME_CALLBACK] Выбран таймфрейм '{timeframe}' для {username}")
        await callback_query.answer(f"⏰ Выбран таймфрейм: {timeframe}")
    
    async def _handle_confirmation_callback(self, callback_query):
        """Обработка подтверждений"""
        data = callback_query.data
        username = callback_query.from_user.username or "Unknown"
        
        logger.info(f"✅ [CONFIRMATION_CALLBACK] Обработка подтверждения '{data}' для {username}")
        await callback_query.answer(f"✅ Подтверждение: {data}")

    # ==============================
    # FSM обработчики для AI анализа
    # ==============================
    
    async def process_symbol_input(self, message: Message, state: FSMContext):
        """Обработка ввода символа для AI анализа — полный комплексный анализ одного инструмента."""
        symbol = message.text.strip().upper()
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        
        logger.info(f"🧠 [AI] Обработка символа '{symbol}' от {username}")
        
        try:
            if len(symbol) < 2 or len(symbol) > 15:
                await message.answer(
                    "❌ Неверный формат символа. Введите корректный тикер (например: BTC, ETH, SOL).",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            if not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"
            # Проверка подписки (как в /intelligence)
            if not self.subscription_manager.can_receive_signal(user_id, "intelligence"):
                await message.answer(
                    "❌ Превышен лимит сигналов для вашей подписки.\n"
                    "💎 Обновите подписку для получения большего количества сигналов.",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            if not self.monitored_pairs:
                pairs = await self.data_collector.load_markets()
                self.monitored_pairs = pairs or []
            target_symbol, display_symbol = self._resolve_symbol_for_intelligence(symbol)
            if not target_symbol:
                examples = "\n".join([f"  • {p.split('/')[0]}" for p in self.monitored_pairs[:10]])
                await message.answer(
                    f"❌ Пара '{display_symbol}' не найдена.\n\n"
                    f"Попробуйте из списка:\n{examples}\n\n"
                    f"<code>Или просто: BTC, ETH, SOL...</code>",
                    reply_markup=main_menu()
                )
                await state.clear()
                return
            await self._run_intelligence_analysis(message, target_symbol, display_symbol, user_id)
            await state.clear()
        except Exception as e:
            logger.exception(f"💥 [AI] Ошибка при обработке символа '{symbol}' от {username}")
            await message.answer("❌ Произошла ошибка при анализе. Попробуйте еще раз.", reply_markup=main_menu())
            await state.clear()
    
    async def process_symbol_search(self, message: Message, state: FSMContext):
        """Обработка поиска символа"""
        symbol = message.text.strip().upper()
        user_id = message.from_user.id
        username = message.from_user.username or "Unknown"
        
        logger.info(f"🔍 [SEARCH] Поиск символа '{symbol}' от {username}")
        
        try:
            # Проверяем валидность символа
            if len(symbol) < 2 or len(symbol) > 10:
                await message.answer("❌ Неверный формат символа. Введите корректный тикер (например: BTC, ETH, SOL)")
                return
            
            # Добавляем USDT если не указан
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"

            await message.answer(f"🔍 Ищу информацию о {symbol}...")

            # Нормализуем под биржу и получаем тикер
            normalized = self.data_collector.normalize_symbol(symbol)
            ticker = await self.data_collector.get_ticker(normalized)

            if not ticker:
                await message.answer(
                    f"❌ Не удалось получить данные по {symbol}",
                    reply_markup=main_menu()
                )
                await state.clear()
                return

            last = float(ticker.get('last') or ticker.get('close') or 0)
            base_volume = float(ticker.get('baseVolume') or 0)
            quote_volume = float(ticker.get('quoteVolume') or 0)
            percentage = ticker.get('percentage')
            if percentage is None:
                try:
                    open_p = float(ticker.get('open') or 0)
                    if open_p:
                        percentage = (last - open_p) / open_p * 100.0
                except Exception:
                    percentage = 0.0

            def fmt_money(v: float) -> str:
                try:
                    if v >= 1_000_000_000:
                        return f"${v/1_000_000_000:.2f}B"
                    if v >= 1_000_000:
                        return f"${v/1_000_000:.2f}M"
                    if v >= 1_000:
                        return f"${v/1_000:.2f}K"
                    return f"${v:.4f}"
                except Exception:
                    return str(v)

            vol_text = fmt_money(quote_volume or base_volume)
            price_text = f"${last:.6f}" if last < 1 else f"${last:.2f}"
            pct_text = f"{float(percentage):+.2f}%" if percentage is not None else "N/A"

            await message.answer(
                f"🔍 <b>Результаты поиска для {symbol}</b>\n\n"
                f"📊 Найдена информация о паре\n"
                f"📈 Текущая цена: {price_text}\n"
                f"📊 Объем 24ч: {vol_text}\n"
                f"📈 Изменение 24ч: {pct_text}",
                reply_markup=main_menu()
            )
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            logger.error(f"💥 [SEARCH] Ошибка при поиске символа '{symbol}' от {username}: {e}")
            await message.answer("❌ Произошла ошибка при поиске. Попробуйте еще раз.", reply_markup=main_menu())
            await state.clear()

    async def _trade_tracker_loop(self):
        """Фоновая проверка открытых симулированных сделок (SL/TP/EXPIRED)."""
        interval_seconds = 300  # 5 минут
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                closed = await self.trade_simulator.check_open_trades(self.data_collector)
                if closed > 0:
                    logger.info("TradeSimulator: закрыто сделок за цикл: %s", closed)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("TradeSimulator loop: %s", e)

    def run(self):
        logger.info("Запуск бота с поддержкой подписок...")

        async def _run():
            asyncio.create_task(self._trade_tracker_loop())
            await self.dp.start_polling(self.bot)

        asyncio.run(_run())

if __name__ == "__main__":
    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        sys.exit(1)
    TradingAlertBot().run()
