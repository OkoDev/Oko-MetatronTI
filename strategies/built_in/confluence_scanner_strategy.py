"""
Стратегия Confluence Scanner:
Генерирует сигналы на основе мульти-факторных сетапов (LONG и SHORT).

Ищет сигналы типа SignalType.CONFLUENCE в переданном списке
(которые создаёт core/confluence_scanner.scan_confluence).

Логика входа:
  LONG:  WT OS + TSL↑ + поддержка + дивергенция bull + цена > PP  (≥3 факторов)
  SHORT: WT OB + TSL↓ + сопротивление + дивергенция bear + цена < PP (≥3 факторов)

SL: TSL-линия из market_context (tsl_trendup/trenddown), fallback ATR×1.5
TP: entry ± sl_dist × tp_rr (дефолт 3.0 = RR 1:3)

Для бэктестинга: движок вызывает scan_confluence(df_window, df_1h, pivots)
и передаёт результат как pre_signals в analyze().
"""
import logging
from typing import Dict, List, Optional, Tuple

from core.signal_models import (
    SignalData, SignalType, SignalDirection, MarketContext, TradingRecommendation
)
from strategies.base import BaseStrategy
from strategies.registry import register_strategy

logger = logging.getLogger(__name__)


@register_strategy("confluence_scanner")
class ConfluenceScannerStrategy(BaseStrategy):
    """
    Confluence Scanner Strategy — мульти-факторный сетап LONG/SHORT.

    Параметры конфига (под ключом strategies.confluence_scanner в config.yaml):
      min_strength:   int  = 60   — минимальный score для генерации сигнала
      tp_rr:          float = 3.0 — RR цели (TP = entry ± sl_dist × tp_rr)
      sl_buffer_pct:  float = 0.3 — буфер за TSL-линией, %
      tsl_max_dist:   float = 3.0 — максимальный SL от цены, %
      tsl_min_dist:   float = 0.6 — минимальный SL от цены (если TSL слишком близко → fallback ATR)
    """

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)
        cfg = config or {}
        self.min_strength   = int(cfg.get("min_strength", 60))
        self.tp_rr          = float(cfg.get("tp_rr", 3.0))
        self.sl_buffer_pct  = float(cfg.get("sl_buffer_pct", 0.3))
        self.tsl_max_dist   = float(cfg.get("tsl_max_dist", 3.0))
        self.tsl_min_dist   = float(cfg.get("tsl_min_dist", 0.6))
        self.logger.info(
            "ConfluenceScannerStrategy: min_strength=%d tp_rr=%.1f",
            self.min_strength, self.tp_rr
        )

    def analyze(
        self,
        signals: List[SignalData],
        market_context: MarketContext,
    ) -> Optional[TradingRecommendation]:
        """
        Ищет CONFLUENCE-сигналы в signals. Берёт сильнейший LONG или SHORT.
        Если оба есть — берёт с бо́льшим score. При равенстве — None (конфликт).
        """
        conf_sigs = [
            s for s in signals
            if s.signal_type == SignalType.CONFLUENCE
            and s.strength >= self.min_strength
        ]
        if not conf_sigs:
            return None

        long_sigs  = [s for s in conf_sigs if s.direction == SignalDirection.LONG]
        short_sigs = [s for s in conf_sigs if s.direction == SignalDirection.SHORT]

        best_long  = max(long_sigs,  key=lambda s: s.strength) if long_sigs  else None
        best_short = max(short_sigs, key=lambda s: s.strength) if short_sigs else None

        # Выбираем направление
        if best_long and best_short:
            if best_long.strength == best_short.strength:
                logger.debug("[conf_scan] %s: конфликт LONG=%d SHORT=%d",
                             market_context.symbol, best_long.strength, best_short.strength)
                return None
            winner = best_long if best_long.strength > best_short.strength else best_short
        elif best_long:
            winner = best_long
        else:
            winner = best_short

        direction = winner.direction
        action = "BUY" if direction == SignalDirection.LONG else "SELL"

        entry = market_context.current_price
        atr = market_context.atr
        sl, tp, _ = self.calculate_sl_tp(entry, direction.value, atr, market_context)

        # tp1 = entry ± sl_dist × 1.0 (первая цель = 1R для частичного выхода)
        sl_dist = abs(entry - sl)
        tp1 = (entry + sl_dist) if direction == SignalDirection.LONG else (entry - sl_dist)

        factors = winner.data.get("factors", []) if winner.data else []
        reasoning = [
            f"Confluence {direction.value}: score={winner.strength}/100",
            f"Факторы ({len(factors)}/5+): {', '.join(factors)}",
        ]
        if winner.data:
            if "pivot_hit" in winner.data:
                reasoning.append(f"Уровень: {winner.data['pivot_hit']}")
            if "div_desc" in winner.data:
                reasoning.append(f"Дивергенция: {winner.data['div_desc']}")

        return TradingRecommendation(
            symbol=market_context.symbol,
            action=action,
            direction=direction,
            overall_strength=winner.strength,
            confidence=winner.confidence,
            risk_level=self._risk_level(winner.strength),
            signals_count=len(conf_sigs),
            supporting_signals=[winner],
            conflicting_signals=[],
            market_context=market_context,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            tp1_price=tp1,
            sl_source="tsl_line" if self._tsl_available(direction, market_context) else "atr_14",
            tp_source=f"atr_rr_{self.tp_rr:.1f}",
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
        SL: TSL-линия (trendup/trenddown) с буфером sl_buffer_pct%.
        Fallback (TSL слишком близко или недоступна): ATR × 1.5, зажат в [min, max]%.
        TP: entry ± sl_dist × tp_rr.
        """
        is_long = direction.upper() == "LONG"
        buf = self.sl_buffer_pct / 100.0

        # Попробуем взять TSL-линию
        tsl_line = (
            market_context.tsl_trendup if is_long else market_context.tsl_trenddown
        ) if market_context else None

        sl = None
        if tsl_line and tsl_line > 0 and entry_price > 0:
            if is_long:
                sl_candidate = tsl_line * (1 - buf)
                dist_pct = (entry_price - sl_candidate) / entry_price * 100
            else:
                sl_candidate = tsl_line * (1 + buf)
                dist_pct = (sl_candidate - entry_price) / entry_price * 100

            if self.tsl_min_dist <= dist_pct <= self.tsl_max_dist:
                sl = sl_candidate

        # Fallback: ATR × 1.5
        if sl is None:
            if atr and atr > 0 and entry_price > 0:
                sl_dist = max(
                    min(atr * 1.5, entry_price * self.tsl_max_dist / 100),
                    entry_price * self.tsl_min_dist / 100,
                )
            else:
                sl_dist = entry_price * 0.02  # 2% hard fallback
            sl = (entry_price - sl_dist) if is_long else (entry_price + sl_dist)

        sl_dist = abs(entry_price - sl)
        tp = (entry_price + sl_dist * self.tp_rr) if is_long else (entry_price - sl_dist * self.tp_rr)

        return sl, tp, 1.0

    # ── helpers ───────────────────────────────────────────────────────────────

    def _tsl_available(self, direction: SignalDirection, ctx: MarketContext) -> bool:
        if not ctx:
            return False
        line = ctx.tsl_trendup if direction == SignalDirection.LONG else ctx.tsl_trenddown
        return bool(line and line > 0)

    @staticmethod
    def _risk_level(strength: int) -> str:
        if strength >= 80:
            return "LOW"
        if strength >= 60:
            return "MEDIUM"
        return "HIGH"
