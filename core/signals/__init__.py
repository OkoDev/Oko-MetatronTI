"""
Signals Layer — модели данных и чекеры сигналов.

Модули:
  signal_models          — dataclass модели: SignalData, TradingRecommendation и др.
  signal_checkers        — чистые функции проверок по всем типам сигналов
  signal_watch_list      — логика WL breach сигналов
  wt_15m_reversal_scanner — сканер WT разворотов на 15m
  structure_detector     — детектор CHoCH/BOS на барах

Использование:
  from core.signals.signal_models import SignalData, TradingRecommendation
  from core.signals import signal_checkers
"""
# Импорты lazy — не загружаем при инициализации пакета чтобы избежать circular imports.
# Используй явный импорт: from core.signals.signal_models import SignalData

__all__ = ["signal_models", "signal_checkers", "signal_watch_list",
           "wt_15m_reversal_scanner", "structure_detector"]
