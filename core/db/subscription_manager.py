"""
Модуль управления подписками пользователей
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)

class SubscriptionTier(Enum):
    """Уровни подписки"""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    PRO = "pro"

class SubscriptionManager:
    """Менеджер подписок пользователей"""
    
    def __init__(self, db_path: str = "subscriptions.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Создает таблицы в базе данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Таблица подписок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tier TEXT NOT NULL,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    payment_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Таблица статистики сигналов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    signal_type TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            """)
            
            # Таблица симулированных сделок (Trade Simulator — Этап 1 ROADMAP)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS simulated_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL DEFAULT '1h',
                    signal_type TEXT,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    strength INTEGER,
                    confidence REAL,
                    regime TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    exit_price REAL,
                    profit_pct REAL,
                    R_multiple REAL,
                    closed_at TIMESTAMP,
                    duration_minutes REAL,
                    features_json TEXT,
                    max_price REAL,
                    min_price REAL,
                    max_R_possible REAL,
                    captured_R_pct REAL,
                    sl_source TEXT,
                    tp_source TEXT,
                    tsl_activated INTEGER DEFAULT 0,
                    strategy_name TEXT,
                    tsl_tf TEXT DEFAULT '15m',
                    exchange_order_id TEXT
                )
            """)

            # Миграция: добавляем колонки если их нет (для существующих БД)
            for col, coltype in [
                ("max_price", "REAL"), ("min_price", "REAL"),
                ("max_R_possible", "REAL"), ("captured_R_pct", "REAL"),
                ("sl_source", "TEXT"), ("tp_source", "TEXT"),
                ("tsl_activated", "INTEGER DEFAULT 0"),
                ("strategy_name", "TEXT"),
                ("tsl_tf", "TEXT DEFAULT '15m'"),
                ("exchange_order_id", "TEXT"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE simulated_trades ADD COLUMN {col} {coltype}")
                except Exception:
                    pass  # колонка уже существует

            # Персональные настройки капитала (Этап 5 ROADMAP)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    deposit_usdt REAL NOT NULL DEFAULT 1000.0,
                    leverage INTEGER NOT NULL DEFAULT 10,
                    risk_pct REAL NOT NULL DEFAULT 1.0,
                    sl_pct REAL NOT NULL DEFAULT 2.0,
                    tp_pct REAL NOT NULL DEFAULT 4.0,
                    auto_sizing INTEGER NOT NULL DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # DEV-15: таблица LLM-разборов SL-сделок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER NOT NULL,
                    analysis TEXT,
                    model TEXT,
                    prompt_tokens INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

            conn.commit()
    
    def add_user(self, user_id: int, username: str = None, 
                 first_name: str = None, last_name: str = None):
        """Добавляет пользователя в базу"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO users 
                    (user_id, username, first_name, last_name)
                    VALUES (?, ?, ?, ?)
                """, (user_id, username, first_name, last_name))
                conn.commit()
                logger.info(f"Пользователь {user_id} добавлен в базу")
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя {user_id}: {e}")
    
    def get_user_subscription(self, user_id: int) -> Optional[Dict]:
        """Получает активную подписку пользователя"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT tier, start_date, end_date, is_active
                    FROM subscriptions
                    WHERE user_id = ? AND is_active = TRUE
                    ORDER BY start_date DESC
                    LIMIT 1
                """, (user_id,))
                
                result = cursor.fetchone()
                if result:
                    return {
                        'tier': result[0],
                        'start_date': result[1],
                        'end_date': result[2],
                        'is_active': result[3]
                    }
                return None
        except Exception as e:
            logger.error(f"Ошибка получения подписки {user_id}: {e}")
            return None
    
    def create_subscription(self, user_id: int, tier: str, 
                          duration_days: int = 30) -> bool:
        """Создает новую подписку"""
        try:
            start_date = datetime.now()
            end_date = start_date + timedelta(days=duration_days)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Деактивируем старые подписки
                cursor.execute("""
                    UPDATE subscriptions 
                    SET is_active = FALSE 
                    WHERE user_id = ?
                """, (user_id,))
                
                # Создаем новую подписку
                cursor.execute("""
                    INSERT INTO subscriptions 
                    (user_id, tier, start_date, end_date)
                    VALUES (?, ?, ?, ?)
                """, (user_id, tier, start_date, end_date))
                
                conn.commit()
                logger.info(f"Подписка {tier} создана для пользователя {user_id}")
                return True
        except Exception as e:
            logger.error(f"Ошибка создания подписки {user_id}: {e}")
            return False
    
    def can_receive_signal(self, user_id: int, signal_type: str) -> bool:
        """Проверяет, может ли пользователь получить сигнал"""
        subscription = self.get_user_subscription(user_id)
        
        if not subscription:
            # Бесплатный пользователь - только аномалии
            return signal_type == "anomaly"
        
        tier = subscription['tier']
        
        # Проверяем лимиты по типу подписки
        if tier == SubscriptionTier.BASIC.value:
            return signal_type in ["anomaly", "wt_signal"]
        elif tier == SubscriptionTier.PREMIUM.value:
            return signal_type in ["anomaly", "wt_signal",
                                 "mtf_alert", "trend_signal", "divergence"]
        elif tier == SubscriptionTier.PRO.value:
            return True  # Все сигналы
        
        return False
    
    def get_daily_signal_count(self, user_id: int) -> int:
        """Получает количество сигналов за сегодня"""
        try:
            today = datetime.now().date()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM signal_stats
                    WHERE user_id = ? AND DATE(sent_at) = ?
                """, (user_id, today))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Ошибка подсчета сигналов {user_id}: {e}")
            return 0
    
    def can_send_signal_today(self, user_id: int) -> bool:
        """Проверяет, можно ли отправить сигнал сегодня"""
        subscription = self.get_user_subscription(user_id)
        
        if not subscription:
            # Бесплатный - максимум 5 сигналов в день
            return self.get_daily_signal_count(user_id) < 5
        
        tier = subscription['tier']
        daily_limit = self.get_daily_limit(tier)
        current_count = self.get_daily_signal_count(user_id)
        
        return current_count < daily_limit
    
    def get_daily_limit(self, tier: str) -> int:
        """Получает дневной лимит сигналов для уровня подписки"""
        limits = {
            SubscriptionTier.BASIC.value: 10,
            SubscriptionTier.PREMIUM.value: 50,
            SubscriptionTier.PRO.value: 999999  # Неограниченно
        }
        return limits.get(tier, 5)
    
    def increment_signal_count(self, user_id: int, signal_type: str):
        """Увеличивает счётчик отправленных сигналов (алиас для record_signal_sent)."""
        self.record_signal_sent(user_id, signal_type)

    def record_signal_sent(self, user_id: int, signal_type: str):
        """Записывает отправленный сигнал"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO signal_stats (user_id, signal_type)
                    VALUES (?, ?)
                """, (user_id, signal_type))
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка записи сигнала {user_id}: {e}")
    
    def get_subscription_info(self, user_id: int) -> Dict:
        """Получает информацию о подписке для отображения"""
        subscription = self.get_user_subscription(user_id)
        
        if not subscription:
            return {
                'tier': 'FREE',
                'status': 'Неактивна',
                'signals_today': self.get_daily_signal_count(user_id),
                'signals_limit': 5,
                'expires': None
            }
        
        tier = subscription['tier']
        signals_today = self.get_daily_signal_count(user_id)
        signals_limit = self.get_daily_limit(tier)
        
        return {
            'tier': tier.upper(),
            'status': 'Активна' if subscription['is_active'] else 'Неактивна',
            'signals_today': signals_today,
            'signals_limit': signals_limit,
            'expires': subscription['end_date']
        }
