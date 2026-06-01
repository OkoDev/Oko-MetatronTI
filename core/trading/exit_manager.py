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


class _MagnetCtx:
    """Лёгкий контекст для TPSelector — собран из Bus smc_snap + pivot_cache.
    Работает для ЛЮБОГО канала регистрации (Phase 2: TP в точке схождения)."""
    def __init__(self, symbol, smc_snap, pivot_cache):
        self.symbol = symbol
        self.smc_snap = smc_snap                 # ARCH-120/122: OB/FVG/EQH/Fib
        self.smc_context = None                  # fallback не нужен (есть snap)
        self.pivot_cache_1d_1w = pivot_cache or {}
        # swing из snap (TPSelector читает скаляр)
        sh = (smc_snap or {}).get("swing_high") or {}
        sl = (smc_snap or {}).get("swing_low") or {}
        self.swing_high = sh.get("price")
        self.swing_low = sl.get("price")


def resolve_magnet_tp(
    symbol: str,
    entry: float,
    stop_loss: float,
    direction: str,
    bus: Any,
    pivot_calc: Any,
    config: Any,
) -> Any:
    """Phase 2: магнит-TP для ЛЮБОГО канала, из Bus snapshot. Вызов в register_trade.

    Возвращает (tp_price, tp_label) — лучший gravity-магнит на разумной RR-дистанции,
    либо None (сохранить существующий TP). Предпочитает tp2 (HTF main, dist 1-3R =
    хороший RR), fallback tp1. Близкий tp1 (<1R) как ГЛАВНЫЙ TP не берём — RR-фильтр.
    """
    try:
        cfg = config.get("sl_tp_engine") if hasattr(config, "get") else None
        if not (cfg or {}).get("tp_selector_enabled", False):
            return None
        if not entry or entry <= 0 or not stop_loss or stop_loss <= 0:
            return None
        sl_dist_pct = abs(entry - stop_loss) / entry * 100
        if sl_dist_pct <= 0:
            return None

        snap = None
        try:
            st = bus.get(symbol) if bus is not None else None
            snap = getattr(st, "smc_snap", None) if st else None
        except Exception:
            snap = None
        piv = getattr(pivot_calc, "pivot_cache", {}) if pivot_calc is not None else {}

        from core.smc.tp_selector import TPSelector
        ctx = _MagnetCtx(symbol, snap, piv)
        tp1, tp2 = TPSelector(config=cfg).select(
            entry=entry, direction=(direction or "").upper(),
            sl_dist_pct=sl_dist_pct, market_context=ctx, config=cfg,
        )
        # tp2 = HTF main (1-3R, хороший RR) → приоритет. Fallback tp1 если dist_R≥1.
        for cand in (tp2, tp1):
            if cand is not None and getattr(cand, "dist_R", 0) >= 1.0:
                return (cand.price, cand.label)
        return None
    except Exception as e:
        logger.debug("[ExitManager] resolve_magnet_tp %s error: %s", symbol, e)
        return None
