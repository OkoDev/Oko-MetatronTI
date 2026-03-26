"""
MTF Layer — multi-timeframe анализ.

Модули:
  mtf_checker      — MTF проверки согласованности сигналов
  mtf_interpreter  — интерпретация MTF контекста
  multi_tf_resolver — резолвер конфликтов между таймфреймами

Использование:
  from core.mtf import mtf_checker
  from core.mtf.mtf_interpreter import MTFInterpreter
"""
__all__ = ["mtf_checker", "mtf_interpreter", "multi_tf_resolver"]
