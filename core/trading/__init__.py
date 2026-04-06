"""
Trading Layer — торговый движок и аналитика.

Модули:
  trade_simulator  — регистрация сделок, SL/TP/TSL трекинг, MFE
  trade_analyzer   — анализ закрытых сделок
  performance_engine — агрегированная аналитика по simulated_trades (read-only)
  regime_strategy  — адаптация параметров под рыночный режим (ARCH-04)

Использование:
  from core.trading.trade_simulator import TradeSimulator
  from core.trading.performance_engine import PerformanceEngine
  from core.trading.regime_strategy import apply_regime_to_strategy
"""
# Импорты lazy — не загружаем при инициализации пакета чтобы избежать circular imports.
# Используй явный импорт: from core.trading.trade_simulator import TradeSimulator

__all__ = ["trade_simulator", "trade_analyzer", "performance_engine", "regime_strategy"]
