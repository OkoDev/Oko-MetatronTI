"""
DEV-18 / Phase 3: Multi-Agent System — интерфейсы агентов.

Концепция: каждый компонент — отдельный AI-агент, оркестрация через Claude Agent SDK.

Агенты:
  ScoutAgent      — поиск сетапов (MTFContext + сигналы)
  RiskAgent       — оценка риска (correlation, regime, position sizing)
  ExecutionAgent  — управление SL/TP/TSL (RL-based, DEV-16)
  AnalystAgent    — разбор закрытых сделок (LLM, DEV-15)

⚠️ ЗАБЛОКИРОВАНО до Phase 3 — требует стабильной архитектуры + DEV-15/16 в prod.
"""
from core.agents.base import BaseAgent
from core.agents.scout import ScoutAgent
from core.agents.risk import RiskAgent
from core.agents.analyst import AnalystAgent

__all__ = ["BaseAgent", "ScoutAgent", "RiskAgent", "AnalystAgent"]
