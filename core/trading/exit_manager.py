"""
ExitManager — Сфера 10 Куба Метатрона (ARCH-122 ч.1b).

Единая точка решения «какой TP применить». Корень проблемы (мониторинг 31.05):
TPSelector считал gravity-магниты, но финальный TP перетирался pivot'ом в 4+
разных местах (monitoring:1122, monitoring:1681, trade_simulator range_bounce:1185,
regime). Результат: 0/51 сделок имели магнит-метку — DEV-224 «TPSelector ВКЛ»
работал вхолостую.

Phase 1: предикат `magnet_tp_locked()` — единый источник правды «магнит победил».
Все override-пойнты зовут его вместо собственной логики. Когда магнит есть и
TPSelector включён — pivot/range_bounce НЕ перетирают.

Связь ARCH-124: regime сломан (78% RANGE = мислейбл тренда) → regime-условные
TP-override (range_bounce) построены на неверной метке → магнит обоснованно
важнее. Exit Manager делает TP regime-НЕзависимым.

Phase 2 (позже): полное извлечение SL/TP/TSL-решения в этот модуль
(ExitManager.resolve(recommendation, context) → sl/tp/sources единообразно).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ExitManager")

# Метка TPSelector-кластера всегда содержит '@' (формат "ob+eqh+fvg_1h@price").
_MAGNET_MARK = "@"


def magnet_tp_locked(recommendation: Any, config: Any) -> bool:
    """True если TP уже выбран TPSelector-магнитом и его НЕЛЬЗЯ перетирать.

    Условия: tp_selector_enabled И recommendation.tp_source содержит '@'
    (gravity-кластер из calculate_levels). Иначе (atr_fallback и пр.) —
    pivot/range_bounce override разрешён как раньше.

    Args:
        recommendation: объект с .tp_source (TradingRecommendation).
        config:         конфиг бота (для sl_tp_engine.tp_selector_enabled).

    Returns:
        bool — True = магнит зафиксирован, override запрещён.
    """
    try:
        cfg = config.get("sl_tp_engine") if hasattr(config, "get") else None
        enabled = bool((cfg or {}).get("tp_selector_enabled", False))
        if not enabled:
            return False
        tp_source = str(getattr(recommendation, "tp_source", "") or "")
        return _MAGNET_MARK in tp_source
    except Exception as e:
        logger.debug("[ExitManager] magnet_tp_locked error: %s", e)
        return False
