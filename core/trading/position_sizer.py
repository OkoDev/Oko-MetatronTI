"""
PositionSizer — DEV-78.

Вычисляет размер позиции по формуле риск-менеджмента:
    qty = (deposit × risk_pct) / (sl_dist_pct × entry_price)

Где sl_dist_pct = |entry - sl| / entry (автовычисляется из цен).

Пример:
    sizer = PositionSizer(config)
    qty = sizer.calc_qty(deposit=10000, entry=83000, sl=80000)
    # risk=1%, sl_dist=3.6% → qty=0.0338 BTC, notional=$2806
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MIN_NOTIONAL_USDT = 5.0


class PositionSizer:
    """Риск-ориентированный расчёт размера позиции."""

    def __init__(self, config=None) -> None:
        self._cfg = config

    def _get(self, key: str, default: float) -> float:
        if self._cfg is None:
            return default
        return float(self._cfg.get(key, default))

    def calc_qty(
        self,
        entry_price: float,
        sl_price:    float,
        deposit:     float = 0.0,
        risk_pct:    float = 0.0,   # % от депозита (1.0 = 1%)
        leverage:    int   = 1,
    ) -> float:
        """
        Рассчитывает qty в базовой валюте.

        Формула:
            sl_dist = |entry - sl| / entry
            notional = (deposit × risk_pct / 100) / sl_dist
            qty = notional / entry_price

        Leverage влияет только на требуемую маржу:
            margin_required = notional / leverage

        Args:
            entry_price: цена входа
            sl_price:    цена стоп-лосса
            deposit:     размер депозита в USDT
            risk_pct:    процент риска на сделку (1.0 = 1%)
            leverage:    плечо (только для informational log)

        Returns:
            qty — количество базовой валюты (0.0 при ошибке)
        """
        if deposit <= 0 or risk_pct <= 0 or entry_price <= 0:
            return 0.0
        if sl_price <= 0 or sl_price == entry_price:
            return 0.0

        sl_dist = abs(entry_price - sl_price) / entry_price
        if sl_dist <= 0:
            return 0.0

        risk_amount = deposit * risk_pct / 100.0
        notional    = risk_amount / sl_dist
        qty         = notional / entry_price

        margin_req = notional / max(leverage, 1)
        logger.debug(
            "[PositionSizer] deposit=%.0f risk=%.1f%% sl_dist=%.2f%% → "
            "notional=%.2f USDT qty=%.6f margin=%.2f (x%d)",
            deposit, risk_pct, sl_dist * 100, notional, qty, margin_req, leverage,
        )
        return qty

    def calc_qty_from_config(
        self,
        entry_price: float,
        sl_price:    float,
        deposit:     float = 0.0,
    ) -> float:
        """
        Рассчитывает qty используя параметры из config.yaml:
          trading.risk_pct, trading.leverage (или user_settings значения).
        """
        risk_pct = self._get("trading.risk_pct", 1.0)
        leverage = int(self._get("trading.leverage", 1))
        if deposit <= 0:
            deposit = self._get("trading.deposit_usdt", 1000.0)
        return self.calc_qty(entry_price, sl_price, deposit, risk_pct, leverage)

    def margin_required(self, notional: float, leverage: int = 1) -> float:
        """Требуемая маржа = notional / leverage."""
        return notional / max(leverage, 1)

    def check_notional(self, qty: float, entry_price: float) -> bool:
        """Проверяет что notional >= MIN_NOTIONAL_USDT."""
        return qty * entry_price >= MIN_NOTIONAL_USDT
