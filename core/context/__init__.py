"""
core/context — Shared Context Bus (DEV-93 / Куб Метатрона Фаза 1).

Хранит состояние по паре в памяти между итерациями скана.
Основа для PostTradeAnalyser (DEV-94) и TriggerBus (DEV-95).
"""
from core.context.pair_context import PairContextBus, PairState

__all__ = ["PairContextBus", "PairState"]
