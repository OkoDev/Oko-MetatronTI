"""
DEV-12 (Этап 8.4.6): Decision Trace — полный аудит принятия решения по сделке.

Записывает ВСЕ шаги от сырых сигналов до финального action:
  сигналы → MTF контекст → множители → ML blend → фильтры → результат.

Пишется в simulated_trades.decision_trace_json при регистрации сделки.
Читается через /api/trades/{id}/trace для ретроспективного анализа.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """Результат применения одного фильтра."""
    name: str
    passed: bool
    reason: str = ""
    details: Optional[Dict[str, Any]] = None


@dataclass
class DecisionTrace:
    """Полный trace принятия решения по символу."""

    symbol: str
    timestamp: str = ""

    # ── Входные сигналы ──
    raw_signals: List[Dict[str, Any]] = field(default_factory=list)
    signal_count: int = 0
    signal_quality: str = "full"  # full / degraded / timeout

    # ── MTF Context ──
    mtf_context: Optional[Dict[str, Any]] = None
    mtf_multipliers: List[Dict[str, Any]] = field(default_factory=list)
    # [{signal_type, direction, original_strength, dir_mult, zone_mult, combined, new_strength}]

    # ── Market Context ──
    market_context: Optional[Dict[str, Any]] = None

    # ── Strategy Selection ──
    strategy_name: str = ""
    strategy_candidates: List[Dict[str, Any]] = field(default_factory=list)
    # [{name, action, confidence, strength}]

    # ── ML Enhancement ──
    ml_adjustment: Optional[Dict[str, Any]] = None
    # {original_confidence, win_prob, blended_confidence, model_version}

    # ── Фильтры ──
    filters: List[Dict[str, Any]] = field(default_factory=list)

    # ── Финальный результат ──
    final_action: str = ""
    final_confidence: float = 0.0
    final_strength: int = 0
    final_direction: str = ""

    # ── Regime ──
    regime: str = ""

    def add_signal(self, signal_data: Any) -> None:
        """Добавляет сырой сигнал в trace."""
        if signal_data is None:
            return
        try:
            sig_type = getattr(signal_data, "signal_type", "?")
            direction = getattr(signal_data, "direction", "?")
            # Enum → string
            if hasattr(sig_type, "value"):
                sig_type = sig_type.value
            if hasattr(direction, "value"):
                direction = direction.value
            entry = {
                "type": sig_type,
                "direction": str(direction),
                "strength": getattr(signal_data, "strength", 0),
                "confidence": getattr(signal_data, "confidence", 0),
                "timeframe": getattr(signal_data, "timeframe", ""),
            }
            self.raw_signals.append(entry)
        except Exception as e:
            logger.debug("DecisionTrace.add_signal error: %s", e)

    def add_mtf_multiplier(
        self,
        signal_type: str,
        direction: str,
        original_strength: int,
        dir_mult: float,
        zone_mult: float,
        combined: float,
        new_strength: int,
    ) -> None:
        """Записывает применение MTF-множителя к сигналу."""
        self.mtf_multipliers.append({
            "signal_type": signal_type,
            "direction": direction,
            "original_strength": original_strength,
            "dir_mult": round(dir_mult, 3),
            "zone_mult": round(zone_mult, 3),
            "combined": round(combined, 3),
            "new_strength": new_strength,
        })

    def add_filter(self, name: str, passed: bool, reason: str = "", **details) -> None:
        """Записывает результат фильтра."""
        entry: Dict[str, Any] = {"name": name, "passed": passed, "reason": reason}
        if details:
            entry["details"] = details
        self.filters.append(entry)

    def set_ml_adjustment(
        self,
        original_confidence: float,
        win_prob: float,
        blended_confidence: float,
    ) -> None:
        """Записывает ML-корректировку confidence."""
        self.ml_adjustment = {
            "original_confidence": round(original_confidence, 4),
            "win_prob": round(win_prob, 4),
            "blended_confidence": round(blended_confidence, 4),
        }

    def set_strategy_candidates(self, candidates: Dict[str, Any]) -> None:
        """Записывает все стратегии-кандидаты и их результаты."""
        for name, rec in candidates.items():
            if rec is None:
                continue
            self.strategy_candidates.append({
                "name": name,
                "action": getattr(rec, "action", "?"),
                "confidence": getattr(rec, "confidence", 0),
                "strength": getattr(rec, "overall_strength", 0),
                "direction": str(getattr(rec, "direction", "?")),
            })

    def set_final(self, action: str, confidence: float, strength: int, direction: str) -> None:
        """Устанавливает финальный результат."""
        self.final_action = action
        self.final_confidence = round(confidence, 4)
        self.final_strength = strength
        self.final_direction = direction

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для JSON."""
        return asdict(self)

    def to_json(self) -> str:
        """Компактный JSON для записи в БД."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def summary(self) -> str:
        """Человекочитаемая строка для логирования."""
        parts = [f"{self.symbol} {self.final_action}"]
        parts.append(f"signals={self.signal_count}")
        if self.mtf_context:
            bias = self.mtf_context.get("direction_bias", "?")
            zone = self.mtf_context.get("price_zone", "?")
            parts.append(f"bias={bias} zone={zone}")
        if self.mtf_multipliers:
            mults = [f"{m['signal_type']}:{m['original_strength']}→{m['new_strength']}" for m in self.mtf_multipliers]
            parts.append(f"mtf_adj=[{', '.join(mults)}]")
        if self.ml_adjustment:
            ml = self.ml_adjustment
            parts.append(f"ml={ml['original_confidence']:.2f}→{ml['blended_confidence']:.2f}")
        filters_blocked = [f for f in self.filters if not f["passed"]]
        if filters_blocked:
            parts.append(f"blocked=[{', '.join(f['name'] for f in filters_blocked)}]")
        parts.append(f"→ {self.final_direction} str={self.final_strength} conf={self.final_confidence:.2f}")
        parts.append(f"strategy={self.strategy_name}")
        return " | ".join(parts)


def create_trace(symbol: str) -> DecisionTrace:
    """Фабрика — создаёт пустой trace с timestamp."""
    return DecisionTrace(
        symbol=symbol,
        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
