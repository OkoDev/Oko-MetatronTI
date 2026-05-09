"""
core/smc/deep_analysis.py — ARCH-29: Глубокий анализ символа с вариантами сценариев.

Команда /deep SYMBOL [TF] — детерминированный нарратив без API:
  - Структура рынка (SMC: trend, CHoCH, BOS, OB+FVG суперсетап)
  - Активные FVG зоны
  - FVG + Пивот конфлюэнции (ARCH-28)
  - Кросс-ТФ пивотные конфлюэнции (ARCH-27)
  - Тройные конфлюэнции (FVG + 2 ТФ пивота)
  - Два сценария (бычий / медвежий) с конкретными уровнями
  - Текущий сетап

Использование:
    text = await build_deep_analysis(symbol, tf, bot)
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import List

from core.smc.models import SMCContext, analyze_smc
from core.smc.confluence import FVGPivotConfluence, find_fvg_pivot_confluences

logger = logging.getLogger(__name__)


# ── Форматирование цены ────────────────────────────────────────────────────────

def _fp(price: float) -> str:
    """Компактный формат цены."""
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    elif price >= 0.01:
        return f"{price:.5f}"
    return f"{price:.6g}"


def _pct(price: float, ref: float) -> str:
    if ref <= 0:
        return ""
    return f"{(price - ref) / ref * 100:+.1f}%"


# ── Тройные конфлюэнции ────────────────────────────────────────────────────────

def _find_triple_confluences(
    fvg_zones: list,
    cross_pivots: list,
    tolerance_pct: float = 2.0,
) -> list[str]:
    """
    Зоны где FVG+Pivot конфлюэнция совпадает с кросс-ТФ пивотной конфлюэнцией.
    Возвращает список строк-меток для отображения.
    """
    result = []
    seen = set()
    for z in fvg_zones:
        for c in cross_pivots:
            avg = (c["price_a"] + c["price_b"]) / 2
            if avg <= 0:
                continue
            dist = abs(z.pivot_price - avg) / avg * 100
            if dist <= tolerance_pct:
                key = (z.label, c["tf_a"], c["tf_b"])
                if key not in seen:
                    seen.add(key)
                    result.append(
                        f"{z.label}  +  {c['tf_a']}_{c['level_a']} ≈ {c['tf_b']}_{c['level_b']}"
                        f" @ <code>{_fp(z.pivot_price)}</code>"
                    )
    return result


# ── Форматирование ─────────────────────────────────────────────────────────────

def _format_deep_analysis(
    symbol: str,
    tf: str,
    price: float,
    ctx: SMCContext,
    fvg_zones: list,
    pivot_confluences: list,
) -> str:

    parts = [f"\n📊 <b>{symbol} · {tf} · Глубокий анализ</b>\n"]

    # ── Структура рынка ────────────────────────────────────────────────────────
    trend_val = ctx.trend.value
    trend_icon = {"BULLISH": "🟢", "BEARISH": "🔴"}.get(trend_val, "⬜")
    lb = ctx.last_break
    struct_suffix = f" · {lb.break_type.value}" if lb else ""

    parts.append("<b>🏗 Структура рынка</b>")
    parts.append(f"  {trend_icon} {trend_val}{struct_suffix}")
    if ctx.active_support:
        parts.append(f"  Поддержка:    <code>{_fp(ctx.active_support)}</code>  ({_pct(ctx.active_support, price)})")
    if ctx.active_resistance:
        parts.append(f"  Сопротивление: <code>{_fp(ctx.active_resistance)}</code>  ({_pct(ctx.active_resistance, price)})")
    if ctx.price_in_ote:
        parts.append("  ✨ OTE — цена в зоне оптимального трейда (0.618–0.786)")
    if ctx.has_bullish_ob_with_fvg:
        parts.append("  🔥 BULL суперсетап: OB + FVG перекрываются")
    if ctx.has_bearish_ob_with_fvg:
        parts.append("  🔥 BEAR суперсетап: OB + FVG перекрываются")
    parts.append("")

    # ── Активные FVG зоны ─────────────────────────────────────────────────────
    active_bull = ctx.fvg.active_bull[:3]
    active_bear = ctx.fvg.active_bear[:3]
    if active_bull or active_bear:
        parts.append("<b>📈 Активные FVG зоны</b>")
        for fvg in active_bull:
            d = (fvg.midpoint - price) / price * 100
            parts.append(
                f"  🟢 Bull FVG <code>{_fp(fvg.bottom)}–{_fp(fvg.top)}</code>"
                f"  ({d:+.1f}%)  заполнен: {fvg.mitigation_pct:.0f}%"
            )
        for fvg in active_bear:
            d = (fvg.midpoint - price) / price * 100
            parts.append(
                f"  🔴 Bear FVG <code>{_fp(fvg.bottom)}–{_fp(fvg.top)}</code>"
                f"  ({d:+.1f}%)  заполнен: {fvg.mitigation_pct:.0f}%"
            )
        parts.append("")

    # ── Зоны конфлюэнции ──────────────────────────────────────────────────────
    # Кросс-ТФ пивоты — только настоящие (не same-TF)
    cross_tf = [
        c for c in pivot_confluences
        if {c["tf_a"], c["tf_b"]} not in ({"1D", "1D_prev"}, {"1W", "1W_prev"})
    ][:5]

    triple = _find_triple_confluences(fvg_zones, cross_tf)

    if fvg_zones or cross_tf:
        parts.append("<b>📐 Зоны конфлюэнции</b>")

        if fvg_zones:
            parts.append("  <i>FVG + Пивот (ARCH-28):</i>")
            # Поддержки (ниже цены) — сначала ближайшие; сопротивления (выше) — тоже ближайшие
            _sup = sorted([z for z in fvg_zones if z.distance_pct < 0],
                          key=lambda z: abs(z.distance_pct))
            _res = sorted([z for z in fvg_zones if z.distance_pct > 0],
                          key=lambda z: z.distance_pct)
            for z in (_res[:3] + _sup[:3]):
                emoji = "🟢" if z.side == "support" else "🔴"
                parts.append(
                    f"  {emoji} {z.label} @ <code>{_fp(z.pivot_price)}</code>"
                    f"  ({z.distance_pct:+.1f}%)  score={z.score}"
                )

        if cross_tf:
            if fvg_zones:
                parts.append("")
            parts.append("  <i>Кросс-ТФ пивоты (ARCH-27):</i>")
            for c in cross_tf:
                avg = (c["price_a"] + c["price_b"]) / 2
                d = (avg - price) / price * 100
                parts.append(
                    f"  ⭐ {c['tf_a']}_{c['level_a']} ≈ {c['tf_b']}_{c['level_b']}"
                    f" @ <code>{_fp(avg)}</code>  ({d:+.1f}%)"
                )

        if triple:
            parts.append("")
            for t in triple:
                parts.append(f"  🔥 <b>ТРОЙНАЯ: {t}</b>")

        parts.append("")

    # ── Сценарии ──────────────────────────────────────────────────────────────
    is_bearish = trend_val == "BEARISH" or ctx.has_choch

    support_zones = [z for z in fvg_zones if z.distance_pct < 0]   # ниже цены
    resist_zones  = [z for z in fvg_zones if z.distance_pct > 0]   # выше цены
    cross_below = sorted(
        [c for c in cross_tf if (c["price_a"] + c["price_b"]) / 2 < price],
        key=lambda c: (c["price_a"] + c["price_b"]) / 2, reverse=True,
    )
    cross_above = sorted(
        [c for c in cross_tf if (c["price_a"] + c["price_b"]) / 2 > price],
        key=lambda c: (c["price_a"] + c["price_b"]) / 2,
    )

    def _zone_label(z: FVGPivotConfluence) -> str:
        return f"{z.label} @ <code>{_fp(z.pivot_price)}</code>  ({z.distance_pct:+.1f}%)"

    def _cross_label(c: dict) -> str:
        avg = (c["price_a"] + c["price_b"]) / 2
        d = (avg - price) / price * 100
        return f"{c['tf_a']}_{c['level_a']} ≈ {c['tf_b']}_{c['level_b']} @ <code>{_fp(avg)}</code>  ({d:+.1f}%)"

    if is_bearish:
        parts.append("<b>🐻 Медвежий сценарий (приоритет)</b>")
        if support_zones:
            parts.append(f"  Цель:  {_zone_label(support_zones[0])}")
        elif cross_below:
            parts.append(f"  Цель:  {_cross_label(cross_below[0])}")
        if resist_zones:
            parts.append(f"  Вход:  откат к {_zone_label(resist_zones[0])} + WT OB")
        elif ctx.nearest_bear_fvg:
            f = ctx.nearest_bear_fvg
            d = (f.midpoint - price) / price * 100
            parts.append(f"  Вход:  откат к Bear FVG <code>{_fp(f.bottom)}–{_fp(f.top)}</code>  ({d:+.1f}%)")
        if ctx.has_choch:
            parts.append("  ⚠️ CHoCH подтверждает разворот структуры")
        parts.append("")

        parts.append("<b>🐂 Бычий сценарий</b>")
        if support_zones:
            z = support_zones[0]
            parts.append(f"  Условие: отскок от <code>{_fp(z.pivot_price)}</code> + WT OS разворот")
        if resist_zones:
            parts.append(f"  Цель:    {_zone_label(resist_zones[0])}")
        parts.append("")

    else:
        parts.append("<b>🐂 Бычий сценарий (приоритет)</b>")
        if resist_zones:
            parts.append(f"  Цель:  {_zone_label(resist_zones[0])}")
        elif cross_above:
            parts.append(f"  Цель:  {_cross_label(cross_above[0])}")
        if support_zones:
            parts.append(f"  Вход:  откат к {_zone_label(support_zones[0])} + WT OS")
        elif ctx.nearest_bull_fvg:
            f = ctx.nearest_bull_fvg
            d = (f.midpoint - price) / price * 100
            parts.append(f"  Вход:  откат к Bull FVG <code>{_fp(f.bottom)}–{_fp(f.top)}</code>  ({d:+.1f}%)")
        if ctx.has_bos:
            parts.append("  ✅ BOS подтверждает продолжение тренда")
        parts.append("")

        parts.append("<b>🐻 Медвежий сценарий</b>")
        if support_zones:
            z = support_zones[0]
            parts.append(f"  Условие: пробой <code>{_fp(z.pivot_price)}</code> с закрытием ниже")
        if cross_below:
            parts.append(f"  Цель:    {_cross_label(cross_below[0])}")
        parts.append("")

    # ── Текущий сетап ─────────────────────────────────────────────────────────
    parts.append("<b>🎯 Текущий сетап</b>")
    if is_bearish and resist_zones:
        z = resist_zones[0]
        sl_zone = next((z2 for z2 in resist_zones[1:] if z2.score >= 25), None)
        parts.append(f"  SHORT · откат к <code>{_fp(z.pivot_price)}</code> · WT OB")
        if sl_zone:
            parts.append(f"  SL: выше <code>{_fp(sl_zone.pivot_price)}</code>")
        if support_zones:
            parts.append(f"  TP: {_zone_label(support_zones[0])}")
    elif not is_bearish and support_zones:
        z = support_zones[0]
        parts.append(f"  LONG · откат к <code>{_fp(z.pivot_price)}</code> · WT OS")
        if resist_zones:
            parts.append(f"  TP: {_zone_label(resist_zones[0])}")
    elif is_bearish and ctx.nearest_bear_fvg:
        f = ctx.nearest_bear_fvg
        parts.append(f"  SHORT · ждём откат к Bear FVG <code>{_fp(f.bottom)}–{_fp(f.top)}</code>")
    else:
        parts.append("  Нет чёткого сетапа — ждём конфлюэнцию")

    parts.append("")
    parts.append(f"  Цена: <code>{_fp(price)}</code>")
    parts.append(f"⏰ {_dt.datetime.utcnow().strftime('%d.%m %H:%M')} UTC")
    parts.append("\n")

    return "\n".join(parts)


# ── Публичный API ──────────────────────────────────────────────────────────────

async def build_deep_analysis(symbol: str, tf: str, bot) -> str:
    """
    Собирает и форматирует глубокий анализ символа.

    Args:
        symbol: торговая пара (например "FAI/USDT:USDT")
        tf:     таймфрейм (например "4h", "1h", "15m")
        bot:    экземпляр TradingAlertBot (нужны data_collector и pivot_calculator)

    Returns:
        Готовое TG-сообщение в HTML.
    """
    try:
        # 1. OHLCV данные: кол-во баров зависит от TF + 80 баров warmup для WT
        from core.ui.chart_builder import _bars_for_tf
        _WARMUP = 80
        _BARS   = _bars_for_tf(tf)
        df_full = await bot.data_collector.get_ohlcv(symbol, tf, limit=_BARS + _WARMUP)
        if df_full is None or len(df_full) < 50:
            return f"❌ Нет данных для {symbol} {tf} (минимум 50 свечей)"

        price = float(df_full["close"].iloc[-1])

        # 2. SMC анализ на видимых барах (без warmup) — FVG.index совпадёт с x-координатой чарта
        df_smc = df_full.iloc[-_BARS:].copy() if len(df_full) > _BARS else df_full
        ctx = analyze_smc(df_smc)

        # 3. Пивоты из кеша бота
        pc = getattr(bot, "pivot_calculator", None)
        dc = getattr(bot, "data_collector", None)
        pivots_1d = (pc.pivot_cache.get(f"{symbol}_1D") or {}) if pc else {}
        pivots_1w = (pc.pivot_cache.get(f"{symbol}_1W") or {}) if pc else {}
        pivots_1m = (pc.pivot_cache.get(f"{symbol}_1M") or {}) if pc else {}
        # Если кеш 1W содержит aggregated_from_1h — форсируем прямой расчёт из 1w свечей
        if pc and dc and (pivots_1w.get("method") == "aggregated_from_1h" or not pivots_1w):
            _fresh_1w = await pc._weekly_from_1w(symbol, dc)
            if _fresh_1w:
                pivots_1w = _fresh_1w

        # Плоский dict для FVG конфлюэнций (ARCH-28)
        # Только уровни PP/S1-S5/R1-R5 — исключаем source_high/low/close и служебные поля
        _PIVOT_KEYS = {"PP", "R1", "R2", "R3", "R4", "R5", "S1", "S2", "S3", "S4", "S5"}
        flat_pivots: dict = {}
        for tf_key, levels in [("1D", pivots_1d), ("1W", pivots_1w), ("1M", pivots_1m)]:
            for lk, lv in (levels or {}).items():
                if lk in _PIVOT_KEYS and isinstance(lv, (int, float)) and lv > 0:
                    flat_pivots[f"{tf_key}_{lk}"] = lv

        # 4. FVG + Pivot конфлюэнции (ARCH-28)
        # tolerance_pct=5.0 для /deep — пивот РЯДОМ с FVG тоже считается конфлюэнцией
        fvg_zones = find_fvg_pivot_confluences(ctx.fvg, flat_pivots, price,
                                               tolerance_pct=5.0) if flat_pivots else []

        # 5. Кросс-ТФ пивотные конфлюэнции (ARCH-27)
        pivot_confluences: list = []
        if pc:
            pivots_data = {k: v for k, v in [("1D", pivots_1d), ("1W", pivots_1w), ("1M", pivots_1m)] if v}
            if len(pivots_data) >= 2:
                pivot_confluences = pc._find_all_confluences(pivots_data)

        # Пивоты для чарта — берём свежие (уже обновлены выше)
        daily_pivots  = pivots_1d or {}
        weekly_pivots = pivots_1w or {}

        # 6. Форматирование
        all_fvgs = ctx.fvg.active_bull + ctx.fvg.active_bear

        text = _format_deep_analysis(symbol, tf, price, ctx, fvg_zones, pivot_confluences)
        # df_full передаём целиком — build_deep_chart срежет после прогрева WT
        return text, fvg_zones, pivot_confluences, df_full, daily_pivots, weekly_pivots, all_fvgs

    except Exception:
        logger.exception("build_deep_analysis: ошибка для %s %s", symbol, tf)
        return f"❌ Ошибка анализа {symbol} {tf}", [], [], None, {}, {}, []
