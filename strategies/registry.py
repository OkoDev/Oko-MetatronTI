"""
Реестр стратегий и фабрика для создания стратегий по имени.
"""

import logging
from typing import Dict, List, Type, Optional
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


# Реестр доступных стратегий
STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {}


def register_strategy(name: str):
    """Декоратор для регистрации стратегии в реестре."""
    def wrapper(cls: Type[BaseStrategy]):
        STRATEGY_REGISTRY[name.lower()] = cls
        logger.debug(f"Registered strategy: {name} → {cls.__name__}")
        return cls
    return wrapper


def get_strategy(name: str, config: Dict = None) -> BaseStrategy:
    """
    Фабрика: получить экземпляр стратегии по имени.
    
    Args:
        name: Имя стратегии из STRATEGY_REGISTRY
        config: Конфигурация для инициализации
    
    Returns:
        Экземпляр стратегии
    
    Raises:
        ValueError: Если стратегия не найдена в реестре
    """
    name_lower = name.lower()
    
    if name_lower not in STRATEGY_REGISTRY:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Strategy '{name}' not found in registry. Available: {available}"
        )
    
    strategy_cls = STRATEGY_REGISTRY[name_lower]
    logger.info(f"Creating strategy instance: {name} ({strategy_cls.__name__})")
    return strategy_cls(config)


def list_strategies() -> List[str]:
    """Получить список всех зарегистрированных стратегий."""
    return sorted(list(STRATEGY_REGISTRY.keys()))


def get_strategy_info(name: str) -> Dict:
    """Получить информацию о стратегии (without instantiation)."""
    name_lower = name.lower()
    if name_lower not in STRATEGY_REGISTRY:
        return None
    
    strategy_cls = STRATEGY_REGISTRY[name_lower]
    return {
        "name": name_lower,
        "class": strategy_cls.__name__,
        "doc": strategy_cls.__doc__
    }


# Ленивый импорт встроенных стратегий при первом использовании
_strategies_loaded = False


def _load_built_in_strategies():
    """Загрузить встроенные стратегии из strategies/built_in/."""
    global _strategies_loaded
    if _strategies_loaded:
        return
    
    try:
        from strategies.built_in.confluence import ConfluenceStrategy
        from strategies.built_in.reversal_scanner_strategy import ReversalScannerStrategy
        from strategies.built_in.conservative import ConservativeStrategy
        from strategies.built_in.pivot_reversal_strategy import PivotReversalStrategy
        try:
            from strategies.built_in.mtf_bias import MTFBiasStrategy
        except Exception:
            pass
        try:
            from strategies.built_in.reversal_strategy import ReversalStrategy
        except Exception:
            pass
        try:
            from strategies.built_in.trend_strategy import TrendFollowingStrategy
        except Exception:
            pass
        _strategies_loaded = True
        logger.debug(f"Loaded built-in strategies: {list_strategies()}")
    except ImportError as e:
        logger.warning(f"Failed to load built-in strategies: {e}")
    except Exception as e:
        logger.error(f"Error loading built-in strategies: {e}")


# Загрузить встроенные стратегии при импорте модуля
try:
    _load_built_in_strategies()
except Exception as e:
    logger.warning(f"Could not auto-load strategies: {e}")
