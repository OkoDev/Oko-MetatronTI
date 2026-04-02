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
from typing import Optional

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


class PairContextBus:
    """
    In-memory хранилище PairState по символу.

    Thread-safe в рамках asyncio event loop (нет shared мутации из разных потоков).
    Данные теряются при перезапуске бота — это ожидаемо (состояние пересчитывается).
    """

    def __init__(self) -> None:
        self._states: dict[str, PairState] = {}

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
