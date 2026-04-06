"""
PairContextBus — DEV-93 / ARCH-59 / Куб Метатрона Фаза 1.

Singleton in-memory хранилище состояния по торговой паре.
Обновляется PostTradeAnalyser при закрытии каждой сделки.
Читается TriggerBus и scan_loop для адаптивного поведения.

Жизненный цикл:
    bot.pair_context = PairContextBus()
    bot.trade_simulator.set_post_trade_callback(bot.post_analyser.on_trade_closed)
    # После TSL/SL/TP → PairState автоматически обновляется.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PairState:
    """Состояние торговой пары — персистентное между итерациями скана."""

    symbol: str

    # Каскадная статистика
    cascade_count: int = 0                    # последовательных TSL/TP в одном направлении
    last_direction: Optional[str] = None      # "LONG" / "SHORT" последней закрытой сделки
    last_close_status: Optional[str] = None   # "TSL" / "SL" / "TP" / "EXPIRED"
    last_close_time: Optional[datetime] = None
    avg_r_cascade: float = 0.0                # средний R по текущей cascade серии

    # Post-TSL данные для OTE Re-entry (TR-010)
    post_tsl_data: Optional[dict] = None      # {direction, ote_top, ote_bot, impulse_high, impulse_low, exit_time, ttl_hours}

    # DEV-142: DEV-138/DEV-137/DEV-139 специалисты (pub/sub расширение)
    wt_verdict: Optional[str] = None          # "TREND_CONTINUATION" / "REVERSAL_SETUP" / ...
    smc_verdict: Optional[str] = None         # "STRONG_BULL_ZONE" / ...
    reversal_mode: Optional[str] = None       # "TREND" / "REVERSAL" / "UNCLEAR"


class PairContextBus:
    """
    In-memory хранилище PairState по символу.

    Thread-safe в рамках asyncio event loop (нет shared мутации из разных потоков).
    Данные теряются при перезапуске бота — это ожидаемо (состояние пересчитывается).
    """

    def __init__(self) -> None:
        self._states: dict[str, PairState] = {}
        # DEV-142: pub/sub подписчики {event_type: [handler, ...]}
        self._subscribers: Dict[str, List[Callable]] = {}

    def get(self, symbol: str) -> PairState:
        """Возвращает PairState для символа, создаёт если нет."""
        if symbol not in self._states:
            self._states[symbol] = PairState(symbol=symbol)
        return self._states[symbol]

    def update(self, symbol: str, **kwargs) -> None:
        """Обновляет поля PairState для символа."""
        state = self.get(symbol)
        for key, val in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, val)
            else:
                logger.warning("[PairContextBus] неизвестное поле PairState: %s", key)

    def all_symbols(self) -> list[str]:
        """Все символы с ненулевым состоянием."""
        return list(self._states.keys())

    def symbols_with_post_tsl(self) -> list[str]:
        """Символы с активной post_tsl_data (для TriggerBus)."""
        return [sym for sym, s in self._states.items() if s.post_tsl_data is not None]

    def reset(self, symbol: str) -> None:
        """Сбросить состояние по символу (например после длительного простоя)."""
        if symbol in self._states:
            del self._states[symbol]

    # ── DEV-142: pub/sub расширение ──────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Регистрирует обработчик события. handler(symbol, data) → None."""
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, symbol: str, event_type: str, data: dict) -> None:
        """Публикует событие. Синхронно вызывает подписчиков."""
        for handler in self._subscribers.get(event_type, []):
            try:
                handler(symbol, data)
            except Exception as e:
                logger.warning("[PairContextBus] subscriber error (%s): %s", event_type, e)

    def get_full_state(self, symbol: str) -> dict:
        """Полный снимок состояния пары — для Narrative Builder и отладки."""
        state = self.get(symbol)
        return {
            "cascade_count":    state.cascade_count,
            "last_direction":   state.last_direction,
            "last_close_status": state.last_close_status,
            "post_tsl_data":    state.post_tsl_data,
            "wt_verdict":       state.wt_verdict,
            "smc_verdict":      state.smc_verdict,
            "reversal_mode":    state.reversal_mode,
        }
