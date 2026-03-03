"""
Модуль для исторического анализа эффективности торговых сигналов
Отслеживает успешность рекомендаций и анализирует паттерны
"""

import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class SignalOutcome(Enum):
    """Результат сигнала"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    PENDING = "pending"

@dataclass
class HistoricalSignal:
    """Исторический сигнал с результатом"""
    symbol: str
    signal_type: str
    direction: str
    strength: int
    confidence: float
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    timestamp: datetime
    outcome: SignalOutcome
    exit_price: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    profit_loss: Optional[float] = None
    profit_loss_percent: Optional[float] = None
    hold_time_hours: Optional[float] = None
    max_favorable: Optional[float] = None
    max_adverse: Optional[float] = None
    metadata: Dict[str, Any] = None

@dataclass
class PerformanceMetrics:
    """Метрики производительности"""
    total_signals: int
    successful_signals: int
    failed_signals: int
    partial_signals: int
    pending_signals: int
    success_rate: float
    average_profit: float
    average_loss: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    average_hold_time: float
    win_rate: float
    loss_rate: float
    best_trade: float
    worst_trade: float
    consecutive_wins: int
    consecutive_losses: int

class HistoricalAnalyzer:
    """
    Анализатор исторической эффективности торговых сигналов
    """
    
    def __init__(self, db_path: str = "trading_history.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Инициализирует базу данных для хранения истории"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Таблица исторических сигналов
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS historical_signals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        strength INTEGER NOT NULL,
                        confidence REAL NOT NULL,
                        entry_price REAL NOT NULL,
                        stop_loss REAL,
                        take_profit REAL,
                        timestamp TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        exit_price REAL,
                        exit_timestamp TEXT,
                        profit_loss REAL,
                        profit_loss_percent REAL,
                        hold_time_hours REAL,
                        max_favorable REAL,
                        max_adverse REAL,
                        metadata TEXT
                    )
                """)
                
                # Таблица метрик производительности
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS performance_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT,
                        signal_type TEXT,
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        metrics TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                
                # Индексы для быстрого поиска
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_timestamp ON historical_signals(symbol, timestamp)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_type ON historical_signals(signal_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_outcome ON historical_signals(outcome)")
                
                conn.commit()
                logger.info("База данных исторического анализа инициализирована")
                
        except Exception as e:
            logger.exception(f"Ошибка инициализации базы данных: {e}")
    
    def record_signal(self, signal: HistoricalSignal) -> bool:
        """Записывает сигнал в историю"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO historical_signals (
                        symbol, signal_type, direction, strength, confidence,
                        entry_price, stop_loss, take_profit, timestamp, outcome,
                        exit_price, exit_timestamp, profit_loss, profit_loss_percent,
                        hold_time_hours, max_favorable, max_adverse, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal.symbol,
                    signal.signal_type,
                    signal.direction,
                    signal.strength,
                    signal.confidence,
                    signal.entry_price,
                    signal.stop_loss,
                    signal.take_profit,
                    signal.timestamp.isoformat(),
                    signal.outcome.value,
                    signal.exit_price,
                    signal.exit_timestamp.isoformat() if signal.exit_timestamp else None,
                    signal.profit_loss,
                    signal.profit_loss_percent,
                    signal.hold_time_hours,
                    signal.max_favorable,
                    signal.max_adverse,
                    json.dumps(signal.metadata) if signal.metadata else None
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.exception(f"Ошибка записи сигнала: {e}")
            return False
    
    def update_signal_outcome(self, signal_id: int, outcome: SignalOutcome, 
                             exit_price: float = None, exit_timestamp: datetime = None,
                             profit_loss: float = None, profit_loss_percent: float = None,
                             hold_time_hours: float = None, max_favorable: float = None,
                             max_adverse: float = None) -> bool:
        """Обновляет результат сигнала"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE historical_signals 
                    SET outcome = ?, exit_price = ?, exit_timestamp = ?, 
                        profit_loss = ?, profit_loss_percent = ?, hold_time_hours = ?,
                        max_favorable = ?, max_adverse = ?
                    WHERE id = ?
                """, (
                    outcome.value,
                    exit_price,
                    exit_timestamp.isoformat() if exit_timestamp else None,
                    profit_loss,
                    profit_loss_percent,
                    hold_time_hours,
                    max_favorable,
                    max_adverse,
                    signal_id
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.exception(f"Ошибка обновления результата сигнала: {e}")
            return False
    
    def get_signals(self, symbol: str = None, signal_type: str = None, 
                   start_date: datetime = None, end_date: datetime = None,
                   outcome: SignalOutcome = None, limit: int = 1000) -> List[HistoricalSignal]:
        """Получает исторические сигналы с фильтрацией"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM historical_signals WHERE 1=1"
                params = []
                
                if symbol:
                    query += " AND symbol = ?"
                    params.append(symbol)
                
                if signal_type:
                    query += " AND signal_type = ?"
                    params.append(signal_type)
                
                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date.isoformat())
                
                if outcome:
                    query += " AND outcome = ?"
                    params.append(outcome.value)
                
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                signals = []
                for row in rows:
                    signal = HistoricalSignal(
                        symbol=row[1],
                        signal_type=row[2],
                        direction=row[3],
                        strength=row[4],
                        confidence=row[5],
                        entry_price=row[6],
                        stop_loss=row[7],
                        take_profit=row[8],
                        timestamp=datetime.fromisoformat(row[9]),
                        outcome=SignalOutcome(row[10]),
                        exit_price=row[11],
                        exit_timestamp=datetime.fromisoformat(row[12]) if row[12] else None,
                        profit_loss=row[13],
                        profit_loss_percent=row[14],
                        hold_time_hours=row[15],
                        max_favorable=row[16],
                        max_adverse=row[17],
                        metadata=json.loads(row[18]) if row[18] else {}
                    )
                    signals.append(signal)
                
                return signals
                
        except Exception as e:
            logger.exception(f"Ошибка получения сигналов: {e}")
            return []
    
    def calculate_performance_metrics(self, symbol: str = None, signal_type: str = None,
                                    start_date: datetime = None, end_date: datetime = None) -> PerformanceMetrics:
        """Рассчитывает метрики производительности"""
        try:
            signals = self.get_signals(symbol, signal_type, start_date, end_date)
            
            if not signals:
                return PerformanceMetrics(
                    total_signals=0, successful_signals=0, failed_signals=0,
                    partial_signals=0, pending_signals=0, success_rate=0.0,
                    average_profit=0.0, average_loss=0.0, profit_factor=0.0,
                    sharpe_ratio=0.0, max_drawdown=0.0, average_hold_time=0.0,
                    win_rate=0.0, loss_rate=0.0, best_trade=0.0, worst_trade=0.0,
                    consecutive_wins=0, consecutive_losses=0
                )
            
            # Подсчитываем результаты
            total_signals = len(signals)
            successful_signals = len([s for s in signals if s.outcome == SignalOutcome.SUCCESS])
            failed_signals = len([s for s in signals if s.outcome == SignalOutcome.FAILURE])
            partial_signals = len([s for s in signals if s.outcome == SignalOutcome.PARTIAL])
            pending_signals = len([s for s in signals if s.outcome == SignalOutcome.PENDING])
            
            # Рассчитываем проценты
            success_rate = successful_signals / total_signals if total_signals > 0 else 0.0
            
            # Анализируем прибыли и убытки
            completed_signals = [s for s in signals if s.outcome in [SignalOutcome.SUCCESS, SignalOutcome.FAILURE, SignalOutcome.PARTIAL] and s.profit_loss is not None]
            
            if completed_signals:
                profits = [s.profit_loss for s in completed_signals if s.profit_loss > 0]
                losses = [s.profit_loss for s in completed_signals if s.profit_loss < 0]
                
                average_profit = np.mean(profits) if profits else 0.0
                average_loss = np.mean(losses) if losses else 0.0
                
                # Profit Factor
                total_profit = sum(profits) if profits else 0.0
                total_loss = abs(sum(losses)) if losses else 0.0
                profit_factor = total_profit / total_loss if total_loss > 0 else float('inf') if total_profit > 0 else 0.0
                
                # Win/Loss rates
                win_rate = len(profits) / len(completed_signals) if completed_signals else 0.0
                loss_rate = len(losses) / len(completed_signals) if completed_signals else 0.0
                
                # Best/Worst trades
                best_trade = max(completed_signals, key=lambda x: x.profit_loss or 0).profit_loss or 0.0
                worst_trade = min(completed_signals, key=lambda x: x.profit_loss or 0).profit_loss or 0.0
                
                # Sharpe Ratio (упрощенный)
                returns = [s.profit_loss_percent or 0 for s in completed_signals]
                if returns:
                    sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
                else:
                    sharpe_ratio = 0.0
                
                # Max Drawdown
                cumulative_returns = np.cumsum(returns)
                running_max = np.maximum.accumulate(cumulative_returns)
                drawdowns = cumulative_returns - running_max
                max_drawdown = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
                
                # Average hold time
                hold_times = [s.hold_time_hours for s in completed_signals if s.hold_time_hours is not None]
                average_hold_time = np.mean(hold_times) if hold_times else 0.0
                
                # Consecutive wins/losses
                consecutive_wins, consecutive_losses = self._calculate_consecutive_trades(completed_signals)
                
            else:
                average_profit = 0.0
                average_loss = 0.0
                profit_factor = 0.0
                sharpe_ratio = 0.0
                max_drawdown = 0.0
                average_hold_time = 0.0
                win_rate = 0.0
                loss_rate = 0.0
                best_trade = 0.0
                worst_trade = 0.0
                consecutive_wins = 0
                consecutive_losses = 0
            
            return PerformanceMetrics(
                total_signals=total_signals,
                successful_signals=successful_signals,
                failed_signals=failed_signals,
                partial_signals=partial_signals,
                pending_signals=pending_signals,
                success_rate=success_rate,
                average_profit=average_profit,
                average_loss=average_loss,
                profit_factor=profit_factor,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                average_hold_time=average_hold_time,
                win_rate=win_rate,
                loss_rate=loss_rate,
                best_trade=best_trade,
                worst_trade=worst_trade,
                consecutive_wins=consecutive_wins,
                consecutive_losses=consecutive_losses
            )
            
        except Exception as e:
            logger.exception(f"Ошибка расчета метрик производительности: {e}")
            return PerformanceMetrics(
                total_signals=0, successful_signals=0, failed_signals=0,
                partial_signals=0, pending_signals=0, success_rate=0.0,
                average_profit=0.0, average_loss=0.0, profit_factor=0.0,
                sharpe_ratio=0.0, max_drawdown=0.0, average_hold_time=0.0,
                win_rate=0.0, loss_rate=0.0, best_trade=0.0, worst_trade=0.0,
                consecutive_wins=0, consecutive_losses=0
            )
    
    def _calculate_consecutive_trades(self, signals: List[HistoricalSignal]) -> Tuple[int, int]:
        """Рассчитывает максимальные последовательные выигрыши и проигрыши"""
        if not signals:
            return 0, 0
        
        # Сортируем по времени
        sorted_signals = sorted(signals, key=lambda x: x.timestamp)
        
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0
        
        for signal in sorted_signals:
            if signal.profit_loss is None:
                continue
                
            if signal.profit_loss > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            elif signal.profit_loss < 0:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0
        
        return max_wins, max_losses
    
    def get_performance_by_signal_type(self, symbol: str = None, 
                                     start_date: datetime = None, 
                                     end_date: datetime = None) -> Dict[str, PerformanceMetrics]:
        """Получает производительность по типам сигналов"""
        try:
            signals = self.get_signals(symbol, None, start_date, end_date)
            
            # Группируем по типам сигналов
            signal_types = set(s.signal_type for s in signals)
            
            performance_by_type = {}
            for signal_type in signal_types:
                metrics = self.calculate_performance_metrics(symbol, signal_type, start_date, end_date)
                performance_by_type[signal_type] = metrics
            
            return performance_by_type
            
        except Exception as e:
            logger.exception(f"Ошибка получения производительности по типам: {e}")
            return {}
    
    def get_performance_trend(self, symbol: str = None, days: int = 30) -> Dict[str, List[float]]:
        """Получает тренд производительности за последние дни"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Разбиваем на периоды по дням
            daily_metrics = {}
            
            for i in range(days):
                period_start = start_date + timedelta(days=i)
                period_end = period_start + timedelta(days=1)
                
                metrics = self.calculate_performance_metrics(symbol, None, period_start, period_end)
                
                date_key = period_start.strftime('%Y-%m-%d')
                daily_metrics[date_key] = {
                    'success_rate': metrics.success_rate,
                    'profit_factor': metrics.profit_factor,
                    'win_rate': metrics.win_rate,
                    'total_signals': metrics.total_signals
                }
            
            return daily_metrics
            
        except Exception as e:
            logger.exception(f"Ошибка получения тренда производительности: {e}")
            return {}
    
    def save_performance_metrics(self, metrics: PerformanceMetrics, symbol: str = None, 
                                signal_type: str = None, period_days: int = 30) -> bool:
        """Сохраняет метрики производительности в базу данных"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                end_date = datetime.now()
                start_date = end_date - timedelta(days=period_days)
                
                cursor.execute("""
                    INSERT INTO performance_metrics (
                        symbol, signal_type, period_start, period_end, metrics, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    signal_type,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    json.dumps(asdict(metrics)),
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.exception(f"Ошибка сохранения метрик: {e}")
            return False
    
    def get_recommendations_for_improvement(self, symbol: str = None) -> List[str]:
        """Генерирует рекомендации для улучшения производительности"""
        try:
            recommendations = []
            
            # Получаем метрики за последние 30 дней
            metrics = self.calculate_performance_metrics(symbol, None, 
                                                       datetime.now() - timedelta(days=30))
            
            if metrics.total_signals < 10:
                recommendations.append("Недостаточно данных для анализа. Нужно больше сигналов.")
                return recommendations
            
            # Анализируем успешность
            if metrics.success_rate < 0.4:
                recommendations.append(f"Низкая успешность ({metrics.success_rate:.1%}). Рассмотрите улучшение фильтрации сигналов.")
            
            # Анализируем profit factor
            if metrics.profit_factor < 1.2:
                recommendations.append(f"Низкий profit factor ({metrics.profit_factor:.2f}). Улучшите управление рисками.")
            
            # Анализируем win rate
            if metrics.win_rate < 0.5:
                recommendations.append(f"Низкий win rate ({metrics.win_rate:.1%}). Пересмотрите критерии входа.")
            
            # Анализируем максимальную просадку
            if metrics.max_drawdown > 20:
                recommendations.append(f"Высокая максимальная просадка ({metrics.max_drawdown:.1f}%). Уменьшите размер позиций.")
            
            # Анализируем последовательные убытки
            if metrics.consecutive_losses > 5:
                recommendations.append(f"Много последовательных убытков ({metrics.consecutive_losses}). Добавьте защитные механизмы.")
            
            # Анализируем время удержания
            if metrics.average_hold_time > 48:
                recommendations.append(f"Долгое время удержания позиций ({metrics.average_hold_time:.1f}ч). Рассмотрите более быстрые стратегии.")
            
            if not recommendations:
                recommendations.append("Производительность в пределах нормы. Продолжайте текущую стратегию.")
            
            return recommendations
            
        except Exception as e:
            logger.exception(f"Ошибка генерации рекомендаций: {e}")
            return ["Ошибка анализа производительности"]
    
    def cleanup_old_data(self, days_to_keep: int = 365) -> bool:
        """Очищает старые данные"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Удаляем старые сигналы
                cursor.execute("DELETE FROM historical_signals WHERE timestamp < ?", 
                             (cutoff_date.isoformat(),))
                
                # Удаляем старые метрики
                cursor.execute("DELETE FROM performance_metrics WHERE created_at < ?", 
                             (cutoff_date.isoformat(),))
                
                conn.commit()
                
                logger.info(f"Очищены данные старше {days_to_keep} дней")
                return True
                
        except Exception as e:
            logger.exception(f"Ошибка очистки данных: {e}")
            return False
