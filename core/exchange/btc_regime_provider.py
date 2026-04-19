"""
ARCH-78: BTCRegimeProvider — Сфера 5 (Cross-Market).

Определяет глобальный режим BTC по ATR Supertrend (4h).
Все модули читают режим через get_btc_mode() — не вычисляют самостоятельно.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class BTCRegimeProvider:
    """
    Singleton-провайдер BTC 4h режима (BULL / BEAR / NEUTRAL).

    Режим определяется по ATR Supertrend:
      trend == 1  → BULL
      trend == -1 → BEAR
      смена тренда или нет данных → NEUTRAL (на 1 цикл при смене, потом стабилизируется)

    Обновляется раз в 5 мин (TTL). Хранит состояние в атрибутах.
    Не использует PairContextBus — режим глобальный, не per-pair.
    """

    _TTL_SECONDS = 300  # 5 минут

    def __init__(self, config=None):
        self._config = config
        self._btc_mode: str = "NEUTRAL"
        self._prev_trend: Optional[int] = None
        self._updated_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_btc_mode(self) -> str:
        """Текущий режим: 'BULL' | 'BEAR' | 'NEUTRAL'."""
        return self._btc_mode

    async def update(self, data_collector) -> None:
        """
        Обновляет режим если прошло >= TTL секунд с последнего обновления.
        Вызывается каждый цикл monitor_market — сама охраняет частоту вызовов.
        """
        now = datetime.utcnow()
        if self._updated_at is not None:
            elapsed = (now - self._updated_at).total_seconds()
            if elapsed < self._TTL_SECONDS:
                return  # ещё не пора

        try:
            await self._fetch_and_compute(data_collector)
        except Exception as exc:
            logger.debug("[BTCRegimeProvider] ошибка обновления: %s", exc)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_and_compute(self, data_collector) -> None:
        from core.indicators.indicators import calculate_trend

        cfg = self._config or {}
        _trend_cfg = (
            cfg.get("analysis", {}).get("indicators", {}).get("trend", {})
            if hasattr(cfg, "get") else {}
        )
        atr_period = int(_trend_cfg.get("atr_period", 43))
        factor = float(_trend_cfg.get("factor", 1.25))

        df = await data_collector.get_ohlcv("BTC/USDT:USDT", "4h", limit=60)
        if df is None or df.empty or len(df) < atr_period + 2:
            logger.debug("[BTCRegimeProvider] нет данных BTC 4h")
            return

        df_trend = calculate_trend(df, atr_period=atr_period, factor=factor)
        if df_trend is None or df_trend.empty:
            return

        trend_now = int(df_trend["trend"].iloc[-1])

        # Смена тренда → NEUTRAL на 1 цикл (переходный период)
        if self._prev_trend is not None and trend_now != self._prev_trend:
            new_mode = "NEUTRAL"
        elif trend_now == 1:
            new_mode = "BULL"
        elif trend_now == -1:
            new_mode = "BEAR"
        else:
            new_mode = "NEUTRAL"

        if new_mode != self._btc_mode:
            logger.info(
                "[BTCRegimeProvider] BTC 4h режим: %s → %s (trend=%d, atr_period=%d, factor=%.2f)",
                self._btc_mode, new_mode, trend_now, atr_period, factor,
            )

        self._prev_trend = trend_now
        self._btc_mode = new_mode
        self._updated_at = datetime.utcnow()
