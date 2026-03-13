"""
Стратегия PivotReversal:
Генерирует сигналы от ключевых недельных уровней (S1/S2/R1/R2/PP).

Логика входа:
  LONG:  цена у поддержки + WT кросс вверх на 15m + тренд 15m UP
  SHORT: цена у сопротивления + WT кросс вниз на 15m + тренд 15m DOWN

БОНУС: FVG на 3m → confidence = VERY_HIGH, strength += 10
КОНФЛЮЭНЦИЯ 1W+1D → strength += 10

SL: ATR(14) × 1.5, зажат в [1%, 4%]
TP: TP1 = первый недельный уровень в направлении (1R+)
    TP  = второй уровень (основная цель, лучший R:R)

Используется в живом боте через check_pivot_reversals() в monitoring.py.
Для бэктестинга: python run_backtest.py --strategy pivot_reversal --symbol BTC/USDT --days 60
"""
import logging
from typing import Dict, List, Optional, Tuple

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)


@register_strategy("pivot_reversal")
class PivotReversalStrategy(BaseStrategy):
    """
    Стратегия входа от недельных пивот-уровней с подтверждением WT и тренда 15m.

    Параметры конфига (strategies.pivot_reversal в config.yaml):
      min_strength:  int   = 60   — минимальный score для входа
      tp_rr:         float = 2.5  — RR при отсутствии следующего пивота (fallback)
      sl_buffer_pct: float = 0.1  — дополнительный буфер за SL, %
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        cfg = config or {}
        self.min_strength  = int(cfg.get("min_strength", 60))
        self.tp_rr         = float(cfg.get("tp_rr", 2.5))
        self.sl_buffer_pct = float(cfg.get("sl_buffer_pct", 0.1))
        self.logger.info(
            "PivotReversalStrategy: min_strength=%d tp_rr=%.1f",
            self.min_strength, self.tp_rr
        )

    def analyze(
        self,
        signals: List[SignalData],
        market_context: MarketContext,
    ) -> Optional[TradingRecommendation]:
        """
        Ищет PIVOT_REVERSAL сигналы в signals (генерируются check_pivot_level_signal).
        Выбирает сильнейший LONG или SHORT.
        """
        pivot_sigs = [
            s for s in signals
            if s.signal_type == SignalType.PIVOT_REVERSAL
            and s.strength >= self.min_strength
        ]
        if not pivot_sigs:
            return None

        long_sigs  = [s for s in pivot_sigs if s.direction == SignalDirection.LONG]
        short_sigs = [s for s in pivot_sigs if s.direction == SignalDirection.SHORT]

        best_long  = max(long_sigs,  key=lambda s: s.strength) if long_sigs  else None
        best_short = max(short_sigs, key=lambda s: s.strength) if short_sigs else None

        if best_long and best_short:
            if best_long.strength == best_short.strength:
                return None  # конфликт
            winner = best_long if best_long.strength > best_short.strength else best_short
        elif best_long:
            winner = best_long
        else:
            winner = best_short

        direction = winner.direction
        action = "BUY" if direction == SignalDirection.LONG else "SELL"

        entry = market_context.current_price
        atr   = market_context.atr
        sl, tp, _ = self.calculate_sl_tp(entry, direction.value, atr, market_context)
        sl_dist = abs(entry - sl)
        tp1 = (entry + sl_dist) if direction == SignalDirection.LONG else (entry - sl_dist)

        data = winner.data or {}
        level = data.get("level", "")
        reasoning = [
            f"PivotReversal {direction.value}: уровень {level}, score={winner.strength}/100",
        ]
        if data.get("has_fvg"):
            reasoning.append(f"FVG {data.get('fvg_type')} на 3m")
        if data.get("has_confluence"):
            reasoning.append("Конфлюэнция 1W+1D")

        return TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=winner.strength,
            confidence=winner.confidence,
            risk_level=self._risk_level(winner.strength),
            signals_count=len(pivot_sigs),
            supporting_signals=[winner],
            conflicting_signals=[],
            market_context=market_context,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            tp1_price=tp1,
            sl_source="atr_14",
            tp_source=f"pivot_1W_{level}" if level else f"atr_rr_{self.tp_rr:.1f}",
            reasoning=reasoning,
        )

    def calculate_sl_tp(
        self,
        entry_price: float,
        direction: str,
        atr: Optional[float],
        market_context: MarketContext,
    ) -> Tuple[float, float, float]:
        """
        SL: ATR(14) × 1.5, зажат в [1%, 4%], с буфером sl_buffer_pct%.
        TP: entry ± sl_dist × tp_rr.
        """
        is_long = direction.upper() == "LONG"
        buf = self.sl_buffer_pct / 100.0

        if atr and atr > 0 and entry_price > 0:
            sl_dist = max(
                min(atr * 1.5, entry_price * 0.04),  # max 4%
                entry_price * 0.01,                   # min 1%
            )
        else:
            sl_dist = entry_price * 0.02  # 2% hard fallback

        # Дополнительный буфер
        sl_dist *= (1 + buf)

        sl = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)
        tp = (entry_price + sl_dist * self.tp_rr) if is_long else (entry_price - sl_dist * self.tp_rr)

        return sl, tp, 1.0

    @staticmethod
    def _risk_level(strength: int) -> str:
        if strength >= 80:
            return "LOW"
        if strength >= 60:
            return "MEDIUM"
        return "HIGH"
