import asyncio
import logging
import platform
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

from core.config import CONFIG
from core.data_collector import RealTimeData
from core.anomaly_detector import AnomalyDetector
from core.message_builder import anomaly_message, wt_message, mtf_message, tv_link
from core.mtf_checker import collect_mtf_data, check_mtf_alert, mtf_alert_message
from core.trend_signals import check_trend_following_signal, trend_signal_message
from core.divergence_detector import DivergenceDetector, divergence_message
from core.pivot_levels import PivotLevels, pivot_message
from core.pivot_reversal import check_pivot_level_signal, pivot_level_signal_message
from core.pivot_calculator_fixed import PivotCalculatorFixed  # ⭐ НОВЫЙ МОДУЛЬ
from core.keyboards import main_menu

# ==============================
# Логирование
# ==============================
logging.basicConfig(
    level=getattr(logging, CONFIG.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("crypto_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
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
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("bot.py:" + str(os.getpid()))

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


# ==============================
# FSM States для пивотов
# ==============================
class PivotStates(StatesGroup):
    waiting_for_pivots = State()      # Ждём тиккер для показа пивотов
    waiting_for_check = State()       # Ждём тиккер для проверки


class TradingAlertBot:
    """
    Основной класс бота для мониторинга криптовалют.
    """

    def __init__(self):
        # --- Инициализация бота ---
        self.token = CONFIG["TELEGRAM_TOKEN"]
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        # ВАЖНО: Storage для FSM
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)

        # --- Ядро системы ---
        self.data_collector = RealTimeData(exchange_id=CONFIG.get("EXCHANGE", "bingx"))
        self.detector = AnomalyDetector(
            volume_multiplier=CONFIG.get("VOLUME_MULTIPLIER", 5.0),
            price_threshold=CONFIG.get("PRICE_THRESHOLD", 7.0)
        )
        self.divergence_detector = DivergenceDetector()  # Без параметров
        self.pivot_calculator = PivotLevels()
        self.pivot_calculator_fixed = PivotCalculatorFixed()  # ⭐ НОВЫЙ

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
            "pivot_alert": 0,  # ⭐ НОВЫЙ счетчик
            "total": 0
        }
        
        if CONFIG.get("ADMIN_ID"):
            try:
                self.subscribers.add(int(CONFIG["ADMIN_ID"]))
            except Exception:
                pass

        # --- Регистрация команд ---
        self.dp.message.register(self.cmd_start, Command("start"))
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_monitor, Command("monitor"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.cmd_subscribe, Command("subscribe"))
        self.dp.message.register(self.cmd_unsubscribe, Command("unsubscribe"))
        self.dp.message.register(self.cmd_top, Command("top"))
        self.dp.message.register(self.cmd_reset_stats, Command("reset"))
        
        # --- Команды для пивотов (ОБЕ через FSM) ---
        self.dp.message.register(self.cmd_request_pivots, Command("pivots"))  # Показ пивотов
        self.dp.message.register(self.cmd_request_check, Command("check_pivot"))  # Проверка близости

        # --- Регистрация обработчиков FSM (по состояниям) ---
        self.dp.message.register(self.process_show_pivots, PivotStates.waiting_for_pivots)
        self.dp.message.register(self.process_check_pivot, PivotStates.waiting_for_check)

        # --- Регистрация обработки кнопок меню (ДОЛЖНО БЫТЬ ПОСЛЕДНИМ!) ---
        self.dp.message.register(self.menu_handler)

    # ==============================
    # Команды
    # ==============================
    async def cmd_start(self, message: Message):
        """Приветственное сообщение + меню"""
        self.subscribers.add(message.chat.id)
        await message.answer(
            "👋 Привет!\n\n🚀 Я бот для мониторинга криптовалют.\n"
            "Отслеживаю объёмы, WT, MTF и тренд-сигналы.\n\n"
            "Выберите действие:",
            reply_markup=main_menu()
        )

    async def cmd_help(self, message: Message):
        """Вывод справки по командам"""
        await message.answer(
            "📚 <b>Справка:</b>\n\n"
            "/start - Главное меню\n"
            "/monitor - Запуск/остановка мониторинга\n"
            "/stats - Статистика\n"
            "/top - Топ-10 по объёму\n"
            "/subscribe - Подписаться\n"
            "/unsubscribe - Отписаться\n"
            "/reset - Сбросить счетчики\n\n"
            "<b>📊 Команды для Pivot Points:</b>\n"
            "/pivots - Недельные и дневные пивоты\n"
            "/check_pivot - Проверка близости к пивотам\n\n"
            "/help - Справка\n\n"
            "<b>Типы сигналов:</b>\n"
            "🚨 Аномалии - резкие всплески объема/цены\n"
            "📊 WT - сигналы по Wavetrend\n"
            "🔄 MTF - мультитаймфрейм анализ\n"
            "🎯 MTF Точки разворота - продвинутый анализ\n"
            "📈 Тренд-сигналы - работа по тренду (с пивотами)\n"
            "💎 Дивергенции - расхождения цены и индикатора\n"
            "📊 Пивоты - уровни поддержки/сопротивления (1W + 1D)\n"
            "🔄 Развороты от пивотов - недельные уровни + FVG\n\n"
            "Также используйте меню кнопок.",
            reply_markup=main_menu()
        )

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

    async def cmd_subscribe(self, message: Message):
        """Подписка на сигналы"""
        self.subscribers.add(message.chat.id)
        await message.answer("✅ Вы подписаны на уведомления.", reply_markup=main_menu())

    async def cmd_unsubscribe(self, message: Message):
        """Отписка от сигналов"""
        self.subscribers.discard(message.chat.id)
        await message.answer("✅ Вы отписаны.", reply_markup=main_menu())

    # ==============================
    # КОМАНДЫ ДЛЯ ПИВОТОВ (через FSM)
    # ==============================
    
    async def cmd_request_pivots(self, message: Message, state: FSMContext):
        """
        📊 Команда /pivots - показ недельных и дневных пивотов
        """
        if not self.monitored_pairs:
            await message.answer(
                "⚠️ Сначала запустите мониторинг /monitor",
                reply_markup=main_menu()
            )
            return
        
        # Показываем примеры
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
        """
        🔍 Команда /check_pivot - проверка близости к пивотам
        """
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
            
            # ⭐ НОВОЕ: Получаем WT данные для рекомендаций
            df_15m = await self.data_collector.get_ohlcv(target, "15m", limit=150)
            wt_15m_data = None
            wt_zone = "N/A"
            wt_signal = "Нет данных"
            
            if df_15m is not None and not df_15m.empty:
                from core.indicators import calculate_wt, get_zone
                df_15m = calculate_wt(df_15m)
                wt1_curr = df_15m['wt1'].iloc[-1]
                wt2_curr = df_15m['wt2'].iloc[-1]
                wt1_prev = df_15m['wt1'].iloc[-2]
                wt2_prev = df_15m['wt2'].iloc[-2]
                wt_zone = get_zone(wt1_curr)
                
                # Определяем кроссы
                cross_up = (wt1_prev < wt2_prev) and (wt1_curr > wt2_curr)
                cross_down = (wt1_prev > wt2_prev) and (wt1_curr < wt2_curr)
                
                wt_15m_data = {
                    'wt1': wt1_curr,
                    'wt2': wt2_curr,
                    'zone': wt_zone,
                    'cross_up': cross_up,
                    'cross_down': cross_down
                }
                
                if cross_up and wt_zone == "OS":
                    wt_signal = "🟢 LONG (кросс вверх в OS)"
                elif cross_down and wt_zone == "OB":
                    wt_signal = "🔴 SHORT (кросс вниз в OB)"
                elif wt_zone == "OS":
                    wt_signal = "🟡 Перепроданность (ждать кросс вверх)"
                elif wt_zone == "OB":
                    wt_signal = "🟡 Перекупленность (ждать кросс вниз)"
                else:
                    wt_signal = f"⚪ Нейтрально (WT1={wt1_curr:.1f})"
            
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
                parts.append(f"📊 <b>WT на 15m:</b> {wt_signal}")
                
                if wt_15m_data:
                    parts.append(f"   WT1: {wt_15m_data['wt1']:.1f} | WT2: {wt_15m_data['wt2']:.1f}")
                    parts.append(f"   Зона: {wt_15m_data['zone']}")
                
                parts.append("")
                parts.append("<b>🎯 ТОРГОВЫЙ ПЛАН:</b>")
                
                # ⭐ УМНЫЕ РЕКОМЕНДАЦИИ на основе пивота + WT
                if near_level['level_type'] == 'support':
                    parts.append("")
                    parts.append("📈 <b>Сценарий LONG (от поддержки):</b>")
                    
                    if wt_15m_data and wt_15m_data['cross_up'] and wt_15m_data['zone'] == "OS":
                        parts.append("  ✅ <b>СИГНАЛ АКТИВЕН!</b>")
                        parts.append("  • WT кросс вверх в зоне OS ✅")
                        parts.append("  • Цена у поддержки ✅")
                        parts.append("")
                        parts.append("  💡 <b>Действия:</b>")
                        parts.append(f"  1. Вход: {current_price:.6f}")
                        parts.append(f"  2. Стоп: {near_level['price'] * 0.998:.6f} (за {near_level['level']})")
                        parts.append(f"  3. Цель 1: следующее сопротивление")
                        parts.append(f"  4. Подтверждение: тренд 5m UP")
                    elif wt_15m_data and wt_15m_data['zone'] == "OS":
                        parts.append("  🟡 <b>ПОДГОТОВКА К ВХОДУ</b>")
                        parts.append("  • Цена у поддержки ✅")
                        parts.append("  • WT в зоне OS ✅")
                        parts.append("  • Ждём: кросс вверх для входа")
                    else:
                        parts.append("  ⏳ <b>ЖДЁМ УСЛОВИЙ</b>")
                        parts.append("  • Цена у поддержки ✅")
                        parts.append("  • Ждём: WT войдёт в OS + кросс вверх")
                    
                elif near_level['level_type'] == 'resistance':
                    parts.append("")
                    parts.append("📉 <b>Сценарий SHORT (от сопротивления):</b>")
                    
                    if wt_15m_data and wt_15m_data['cross_down'] and wt_15m_data['zone'] == "OB":
                        parts.append("  ✅ <b>СИГНАЛ АКТИВЕН!</b>")
                        parts.append("  • WT кросс вниз в зоне OB ✅")
                        parts.append("  • Цена у сопротивления ✅")
                        parts.append("")
                        parts.append("  💡 <b>Действия:</b>")
                        parts.append(f"  1. Вход: {current_price:.6f}")
                        parts.append(f"  2. Стоп: {near_level['price'] * 1.002:.6f} (за {near_level['level']})")
                        parts.append(f"  3. Цель 1: следующая поддержка")
                        parts.append(f"  4. Подтверждение: тренд 5m DOWN")
                    elif wt_15m_data and wt_15m_data['zone'] == "OB":
                        parts.append("  🟡 <b>ПОДГОТОВКА К ВХОДУ</b>")
                        parts.append("  • Цена у сопротивления ✅")
                        parts.append("  • WT в зоне OB ✅")
                        parts.append("  • Ждём: кросс вниз для входа")
                    else:
                        parts.append("  ⏳ <b>ЖДЁМ УСЛОВИЙ</b>")
                        parts.append("  • Цена у сопротивления ✅")
                        parts.append("  • Ждём: WT войдёт в OB + кросс вниз")
                
                else:  # pivot
                    parts.append("")
                    parts.append("⚡️ <b>Цена у PIVOT POINT - ключевой уровень!</b>")
                    
                    if wt_15m_data:
                        if wt_15m_data['cross_up'] and wt_15m_data['zone'] == "OS":
                            parts.append("")
                            parts.append("  ✅ <b>LONG СИГНАЛ</b>")
                            parts.append("  • Пробой PP вверх + WT кросс в OS")
                            parts.append(f"  • Вход: {current_price:.6f}")
                            parts.append(f"  • Стоп: под PP ({near_level['price'] * 0.998:.6f})")
                            parts.append("  • Цель: R1 → R2")
                        elif wt_15m_data['cross_down'] and wt_15m_data['zone'] == "OB":
                            parts.append("")
                            parts.append("  ✅ <b>SHORT СИГНАЛ</b>")
                            parts.append("  • Пробой PP вниз + WT кросс в OB")
                            parts.append(f"  • Вход: {current_price:.6f}")
                            parts.append(f"  • Стоп: над PP ({near_level['price'] * 1.002:.6f})")
                            parts.append("  • Цель: S1 → S2")
                        else:
                            parts.append("")
                            parts.append("  ⏳ <b>ЖДЁМ ПРОБОЯ</b>")
                            parts.append(f"  • WT текущее: {wt_15m_data['zone']}")
                            parts.append("  • Пробой вверх → LONG (при WT в OS)")
                            parts.append("  • Пробой вниз → SHORT (при WT в OB)")
                
                parts.append("")
                parts.append("<b>💡 Общие рекомендации:</b>")
                parts.append("  1. Дождись WT сигнала на 15m")
                parts.append("  2. Проверь разворот тренда на 5m")
                parts.append("  3. Ищи FVG на 3m для подтверждения")
                parts.append("  4. Стоп - за уровень (тайтовый)")
                parts.append("  5. Цель - следующий пивот")
                
            else:
                parts.append("✅ Цена далеко от пивотных уровней")
                parts.append("Ближайший уровень >1% от текущей цены")
                parts.append("")
                parts.append(f"📊 <b>WT на 15m:</b> {wt_signal}")
                
                # Показываем ближайшие уровни
                nearest = self.pivot_calculator_fixed.get_nearest_levels(current_price, weekly_pivots)
                
                if nearest.get('support') and len(nearest['support']) > 0:
                    sup = nearest['support'][0]  # Берем первый (ближайший) элемент
                    parts.append(f"\n🟢 Ближайшая поддержка: {sup[0]}")  # sup[0] = level
                    parts.append(f"   Цена: {sup[1]:.6f} ({sup[2]:.2f}%)")  # sup[1] = price, sup[2] = distance
                
                if nearest.get('resistance') and len(nearest['resistance']) > 0:
                    res = nearest['resistance'][0]  # Берем первый (ближайший) элемент
                    parts.append(f"\n🔴 Ближайшее сопротивление: {res[0]}")  # res[0] = level
                    parts.append(f"   Цена: {res[1]:.6f} ({res[2]:.2f}%)")  # res[1] = price, res[2] = distance
            
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
        
        # ⭐ ОБРАБОТКА КНОПОК ПИВОТОВ
        elif text == "📊 Пивоты":
            await self.cmd_request_pivots(message, state)
        elif text == "🔍 Проверить пивоты":
            await self.cmd_request_check(message, state)

    # ==============================
    # Мониторинг рынка
    # ==============================
    async def start_monitoring(self, message: Message):
        """Запуск фонового мониторинга"""
        if self.is_monitoring:
            await message.answer("⚠️ Мониторинг уже запущен.", reply_markup=main_menu())
            return
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
            f"📡 Отслеживаю: аномалии, WT, MTF, тренд-сигналы и дивергенции",
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
        """Основной цикл мониторинга"""
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
    # Проверки с подсчетом сигналов
    # ==============================
    async def check_anomalies(self):
        """Проверка аномалий по объёму/цене"""
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
        for sym, info in found:
            await self.broadcast(anomaly_message(sym, info))

    async def check_wt_signals(self):
        """Проверка сигналов по Wavetrend"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await self.detector.check_wt_signal(sym, self.data_collector)
                if is_sig:
                    info["volume_details"] = list(self.data_collector.volume_history.get(sym, []))[-5:]
                    await self.broadcast(wt_message(sym, info))
                    self.signal_counters["wt_signal"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_wt_signal для {sym}")

    async def check_mtf_signals(self):
        """Проверка сигналов по мультиТФ"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await self.detector.check_mtf_signal(sym, self.data_collector)
                if is_sig:
                    info["volume_details"] = list(self.data_collector.volume_history.get(sym, []))[-5:]
                    await self.broadcast(mtf_message(sym, info))
                    self.signal_counters["mtf_signal"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_mtf_signal для {sym}")

    async def check_mtf_alerts(self):
        """Проверка MTF snapshot на кастомные условия"""
        for sym in self.monitored_pairs:
            try:
                snapshot = await collect_mtf_data(sym, self.data_collector)
                if not snapshot:
                    continue
                is_alert, sig = check_mtf_alert(snapshot)
                if is_alert:
                    await self.broadcast(mtf_alert_message(sym, snapshot, sig))
                    self.signal_counters["mtf_alert"] += 1
                    self.signal_counters["total"] += 1
            except Exception:
                logger.exception(f"Ошибка check_mtf_alerts для {sym}")

    async def check_trend_signals(self):
        """Проверка тренд-сигналов (работа по тренду)"""
        for sym in self.monitored_pairs:
            try:
                is_sig, info = await check_trend_following_signal(
                    sym, self.data_collector, self.divergence_detector, self.pivot_calculator
                )
                if is_sig:
                    await self.broadcast(trend_signal_message(sym, info))
                    self.signal_counters["trend_signal"] += 1
                    self.signal_counters["total"] += 1
                    logger.info(f"[{sym}] Обнаружен тренд-сигнал: {info.get('pattern')}")
            except Exception:
                logger.exception(f"Ошибка check_trend_signals для {sym}")

    async def check_divergences(self):
        """Проверка дивергенций на разных таймфреймах"""
        timeframes = ["15m", "1h"]
        
        for sym in self.monitored_pairs:
            for tf in timeframes:
                try:
                    has_div, div_info = await self.divergence_detector.detect_divergence(
                        sym, self.data_collector, timeframe=tf
                    )
                    if has_div:
                        await self.broadcast(divergence_message(sym, div_info))
                        self.signal_counters["divergence"] += 1
                        self.signal_counters["total"] += 1
                        logger.info(f"[{sym}] Обнаружена дивергенция на {tf}: {div_info.get('type')}")
                        break
                except Exception:
                    logger.exception(f"Ошибка check_divergences для {sym} {tf}")

    async def check_pivot_reversals(self):
        """Проверка входов от недельных пивотов"""
        for sym in self.monitored_pairs:
            try:
                has_signal, info = await check_pivot_level_signal(
                    sym, self.data_collector, self.pivot_calculator
                )
                if has_signal:
                    await self.broadcast(pivot_level_signal_message(sym, info))
                    self.signal_counters["pivot_reversal"] += 1
                    self.signal_counters["total"] += 1
                    logger.info(f"[{sym}] Вход от уровня: {info.get('level')} R:R={info.get('rr_ratio', 0):.1f}")
            except Exception:
                logger.exception(f"Ошибка check_pivot_reversals для {sym}")

    # ==============================
    # Вызов MTF snapshot вручную
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
    # Отправка сообщений
    # ==============================
    async def broadcast(self, text: str):
        """Рассылка сообщений всем подписчикам"""
        for uid in list(self.subscribers):
            try:
                await self.bot.send_message(chat_id=uid, text=text, disable_web_page_preview=True)
            except Exception:
                logger.exception(f"Ошибка отправки сообщения {uid}")

    # ==============================
    # Запуск бота
    # ==============================
    def run(self):
        logger.info("Запуск бота...")
        asyncio.run(self.dp.start_polling(self.bot))


if __name__ == "__main__":
    if not _acquire_single_instance_lock():
        print("⚠️ Бот уже запущен (обнаружен lock-файл). Закрываю второй экземпляр.")
        raise SystemExit(1)
    TradingAlertBot().run()