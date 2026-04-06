"""
Модуль стратегий торговли.
Содержит интерфейс BaseStrategy и реестр доступных стратегий.
"""

from strategies.base import BaseStrategy
from strategies.registry import (
    get_strategy,
    list_strategies,
    get_strategy_info,
    register_strategy,
    STRATEGY_REGISTRY
)

__all__ = [
    "BaseStrategy",
    "get_strategy",
    "list_strategies",
    "get_strategy_info",
    "register_strategy",
    "STRATEGY_REGISTRY",
]
