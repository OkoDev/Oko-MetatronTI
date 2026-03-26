"""
Infra Layer — транспортный слой и загрузка конфигурации.

Модули:
  api_engine    — LRU cache, CircuitBreaker, retry, in-flight dedup
  data_collector — получение данных с биржи (OHLCV + ticker)
  config_loader — загрузка config.yaml и .env
  data_quality  — валидация качества OHLCV данных
  entry_config  — конфигурация точки входа

Использование:
  from core.infra.api_engine import ApiEngine
  from core.infra.data_collector import DataCollector
  from core.infra import config_loader
"""
__all__ = ["api_engine", "data_collector", "config_loader", "data_quality", "entry_config"]
