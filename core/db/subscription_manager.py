"""
Модуль управления подписками пользователей
"""
import sqlite3
import logging
import time
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
    
    def _db_connect(self, timeout: int = 30):
        """DEV-148: единое место для настройки соединения — busy_timeout на каждом connect."""
        conn = sqlite3.connect(self.db_path, timeout=timeout)
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def init_database(self):
        """Создает таблицы в базе данных"""
        with self._db_connect() as conn:
            # WAL mode — параллельные читатели не блокируют писателей
            conn.execute("PRAGMA journal_mode=WAL")
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
                    exchange_order_id TEXT,
                    exchange_sl_order_id TEXT,
                    position_id TEXT,
                    tp1_price REAL,
                    tp2_price REAL,
                    tp3_price REAL,
                    tp1_hit_at TIMESTAMP,
                    strategy_type TEXT,
                    decision_trace_json TEXT,
                    original_sl REAL,
                    magnet_tp_price REAL,
                    magnet_tp_rr REAL,
                    magnet_tp_src TEXT,
                    regime_v2 TEXT
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
                ("exchange_sl_order_id", "TEXT"),
                # fake-R фикс (19.06): positionID жизни позиции (вход+SL+TP+перевыставленные =
                # ОДИН positionID) — надёжный якорь exit'а в _resolve_exit вместо протухающего
                # orderId / эвристики symbol+side, что хватала чужой старый close. [[bug_phantom_exit_resolve]]
                ("position_id", "TEXT"),
                # fake-R карантин (19.06): миграция помечает фантом-монстров R>10 с MFE=None,
                # которые НЕЛЬЗЯ восстановить (нет [min,max] и нет ордера в окне allOrders) →
                # R_multiple/profit_pct=NULL (исключены из метрик/весов), пометка для аудита.
                ("fakeR_quarantine", "INTEGER DEFAULT 0"),
                ("tp1_price", "REAL"),
                ("tp2_price", "REAL"),
                ("tp3_price", "REAL"),
                ("tp1_hit_at", "TIMESTAMP"),
                ("strategy_type", "TEXT"),
                ("decision_trace_json", "TEXT"),
                ("original_sl", "REAL"),
                ("source_router", "TEXT"),   # TradeRouter: имя источника (atr_change/monitoring/...)
                ("magnet_tp_price", "REAL"),  # ARCH-122 P2 shadow: gravity-магнит цена (не закрывает)
                ("magnet_tp_rr", "REAL"),     # ARCH-122 P2 shadow: RR магнита от entry
                ("magnet_tp_src", "TEXT"),    # ARCH-122 P2 shadow: метка кластера
                ("regime_v2", "TEXT"),        # ARCH-124 shadow: HTF-доминантная метка режима
                # ARCH-DB-V2 Ф1 (12.06): явная разметка сделок (было косвенно через exchange_order_id)
                ("account_id", "INTEGER DEFAULT 1"),       # суб-аккаунт (1/2/...); старые сделки=1
                ("execution_mode", "TEXT DEFAULT 'SIM'"),  # SIM/VST/LIVE — явно, не через NULL
                ("exchange", "TEXT DEFAULT 'bingx'"),      # биржа (Ф2 нормализует в exchange_id)
                ("total_fee", "REAL DEFAULT 0"),           # 13.06: комиссия round-trip (qty×entry×0.1%), заполняется при close_trade
                # 19.06: фактическое плечо сделки (записывается при открытии в trade_router).
                # Корень: дашборд брал leverage из ЖИВОГО config → старые сделки «перекрашивались»
                # задним числом при смене конфига. Теперь = свойство сделки (per-source, не глобал).
                ("leverage", "REAL"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE simulated_trades ADD COLUMN {col} {coltype}")
                except Exception:
                    pass  # колонка уже существует

            # ARCH-DB-V2 Ф2: справочники бирж и аккаунтов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exchanges (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT NOT NULL UNIQUE,
                    is_active  INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("INSERT OR IGNORE INTO exchanges (id, name) VALUES (1, 'bingx')")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id          INTEGER PRIMARY KEY,
                    exchange_id INTEGER REFERENCES exchanges(id),
                    name        TEXT,
                    api_env     TEXT DEFAULT 'vst',
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for _aid, _aname in [(1, 'VST-Main'), (2, 'VST-Sub')]:
                cursor.execute(
                    "INSERT OR IGNORE INTO accounts (id, exchange_id, name, api_env) VALUES (?, 1, ?, 'vst')",
                    (_aid, _aname),
                )

            # ARCH-DB-V2 Ф2: current-state открытых позиций (PK account+symbol+side)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    account_id     INTEGER NOT NULL,
                    symbol         TEXT NOT NULL,
                    side           TEXT NOT NULL,
                    qty            REAL,
                    entry_price    REAL,
                    unrealized_pnl REAL,
                    margin         REAL,
                    updated_at     TEXT,
                    mark_price     REAL,
                    PRIMARY KEY (account_id, symbol, side)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_positions_account "
                "ON positions(account_id, updated_at)"
            )
            # mark_price (17.06, DS-запрос): текущая mark с биржи для drawer открытых позиций
            # (Mark + uPnL% без REST). Идемпотентная миграция для существующих БД.
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN mark_price REAL")
            except Exception:
                pass

            # ARCH-DB-V2 Ф1: история equity по аккаунтам (решает «движение баланса»)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS balance_snapshots (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id     INTEGER NOT NULL,
                    exchange       TEXT NOT NULL DEFAULT 'bingx',
                    timestamp      TEXT NOT NULL,
                    equity         REAL NOT NULL,
                    available      REAL,
                    used_margin    REAL,
                    unrealized_pnl REAL,
                    source         TEXT DEFAULT 'poll',
                    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_balance_acc_ts "
                "ON balance_snapshots(account_id, exchange, timestamp)"
            )
            # индексы под частые фильтры терминала (account/mode/exchange)
            # + 03.07.2026 дашборд-аудит: status/created_at/signal_type/symbol — до этого
            # КАЖДЫЙ запрос дашборда = SCAN 491MB (full_stats 6.9s→2.1s одними индексами)
            for _ix, _cols in [
                ("idx_trades_account", "account_id, created_at"),
                ("idx_trades_mode", "execution_mode, created_at"),
                ("idx_trades_exchange", "exchange, created_at"),
                ("idx_trades_status_created", "status, created_at DESC"),
                ("idx_trades_created", "created_at DESC"),
                ("idx_trades_signal_created", "signal_type, created_at DESC"),
                ("idx_trades_symbol_created", "symbol, created_at DESC"),
            ]:
                try:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS {_ix} ON simulated_trades({_cols})")
                except Exception:
                    pass

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

            # DEV-177: история адаптивных весов (траектория для дашборда и debug)
            cursor.execute("""
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
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_swh_computed_at "
                "ON signal_weights_history(computed_at)"
            )

            # DEV-203: таблица отброшенных сигналов (DecisionTrace)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_drops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT,
                    direction TEXT,
                    strength INTEGER,
                    gate_name TEXT NOT NULL,
                    drop_reason TEXT NOT NULL,
                    features_json TEXT,
                    dropped_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_drops_gate "
                "ON signal_drops(gate_name, dropped_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_drops_symbol "
                "ON signal_drops(symbol, dropped_at)"
            )

            # DEV-222: хранение TG message_id для reply при закрытии сделки
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tg_messages (
                    trade_id INTEGER NOT NULL,
                    user_id  INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY (trade_id, user_id)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_tg_messages_trade "
                "ON tg_messages(trade_id)"
            )

            # ARCH-118 Шаг 5b: единый снимок признаков (вариант B, live=backtest parity).
            # Архивный слой Куба — persistence-проекция PairFullState на момент входа.
            # 1:1 с simulated_trades (trade_id PK = FK). features_json = вложенный sparse
            # снимок {meta, context:{smc,wt,rsi,trend,mom,pivot}, signal}. Горячие поля
            # (schema_version/source/entry_tf) — top-level колонки для query/индексов.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_features (
                    trade_id INTEGER PRIMARY KEY,
                    schema_version INTEGER NOT NULL DEFAULT 2,
                    source TEXT,
                    entry_tf TEXT,
                    snapshot_ts TEXT,
                    n_true INTEGER,
                    n_total INTEGER,
                    features_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (trade_id) REFERENCES simulated_trades(id)
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_features_schema "
                "ON trade_features(schema_version, entry_tf)"
            )

            conn.commit()
    
    def add_user(self, user_id: int, username: str = None, 
                 first_name: str = None, last_name: str = None):
        """Добавляет пользователя в базу"""
        try:
            with self._db_connect() as conn:
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
            with self._db_connect() as conn:
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
            
            with self._db_connect() as conn:
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
            with self._db_connect() as conn:
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
        retries = 4
        delay_sec = 0.15
        for attempt in range(retries):
            try:
                with self._db_connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO signal_stats (user_id, signal_type)
                        VALUES (?, ?)
                    """, (user_id, signal_type))
                    conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower() and attempt < retries - 1:
                    time.sleep(delay_sec * (attempt + 1))
                    continue
                logger.error(f"Ошибка записи сигнала {user_id}: {e}")
                return
            except Exception as e:
                logger.error(f"Ошибка записи сигнала {user_id}: {e}")
                return
    
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
