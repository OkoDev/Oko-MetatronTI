"""
Confluence Scanner — Lookback-детектор мульти-факторных сетапов.

Ищет в окне lookback_bars баров совпадение условий:
  1. WT был в OS зоне (wt1 < -53)          → +20 очков
  2. TSL пересечение UP (тренд сменился 1)  → +20 очков
  3. Цена была у ключевого пивота (S1/PP)   → +25 очков
  4. Бычья дивергенция WT (price LL, wt HL)→ +20 очков
  5. Текущая цена выше дневного PP          → +15 очков

Порог сигнала: strength ≥ 60 (3+ факторов).
Функция синхронная — не делает API-запросов, только считает по готовым df.

Пример использования (в scan_one):
    from core.confluence_scanner import scan_confluence
    cfg = getattr(bot.config, '_data', bot.config) if hasattr(bot.config, '_data') else {}
    for sig in scan_confluence(sym, df_15m, df_1h, bot.pivot_calculator.pivot_cache, cfg=bot.config):
        all_scan_signals.append(sig)
        signals_to_broadcast.append(("confluence", _confluence_message(sym, sig), None))
"""
import logging
from datetime import datetime
from typing import List, Dict, Any

import numpy as np
import pandas as pd

from core.indicators import calculate_trend, calculate_wt
from core.signal_models import SignalData, SignalType, SignalDirection

logger = logging.getLogger(__name__)

# ── Дефолты (перекрываются через config.yaml → analysis.confluence) ──────────
_DEFAULT_WT_OS = -60
_DEFAULT_WT_OB = 60   # WT в OB → OS сигнал уже устарел
_DEFAULT_PIVOT_PCT = 1.0
_DEFAULT_MIN_STRENGTH = 60
_DEFAULT_DIV_MIN_BARS = 3
_DEFAULT_LOOKBACK = 30

# Очки за каждое условие (постоянные)
_SCORE_WT_OS = 20
_SCORE_TSL_CROSS = 20
_SCORE_NEAR_PIVOT = 25
_SCORE_DIVERGENCE = 20
_SCORE_ABOVE_PP = 15


def _get_cfg(cfg) -> dict:
    """Извлекает analysis.confluence из объекта конфига (поддерживает ConfigLoader и dict)."""
    if cfg is None:
        return {}
    if hasattr(cfg, "get"):
        # ConfigLoader с dot-нотацией
        block = cfg.get("analysis.confluence", None)
        if isinstance(block, dict):
            return block
        # plain dict
        return (cfg.get("analysis") or {}).get("confluence", {})
    return {}


def scan_confluence(
    symbol: str,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    pivot_cache: Dict[str, Any],
    lookback_bars: int = _DEFAULT_LOOKBACK,
    cfg=None,
) -> List[SignalData]:
    """
    Lookback-сканер конфлюэнции. Возвращает список SignalData (обычно 0 или 1 сигнал).

    Args:
        symbol:        торговая пара (напр. "BTC/USDT")
        df_15m:        OHLCV DataFrame 15m (>= lookback_bars строк)
        df_1h:         OHLCV DataFrame 1h (>= lookback_bars строк)
        pivot_cache:   bot.pivot_calculator.pivot_cache (dict ключ = f"{sym}_1D")
        lookback_bars: глубина поиска в барах 15m (~7.5 часов при 30 барах)
        cfg:           объект конфига (ConfigLoader или dict) — читает analysis.confluence
    """
    results: List[SignalData] = []

    try:
        # ── Параметры из конфига (с дефолтами) ───────────────────────────
        conf_cfg = _get_cfg(cfg)
        if not conf_cfg.get("enabled", True):
            return results

        lookback_bars = int(conf_cfg.get("lookback_bars", lookback_bars))
        wt_os_thr     = float(conf_cfg.get("wt_os_threshold", _DEFAULT_WT_OS))
        wt_ob_thr     = float(conf_cfg.get("wt_ob_threshold", _DEFAULT_WT_OB))
        pivot_pct     = float(conf_cfg.get("pivot_proximity_pct", _DEFAULT_PIVOT_PCT))
        min_strength  = int(conf_cfg.get("min_strength", _DEFAULT_MIN_STRENGTH))
        div_min_bars  = int(conf_cfg.get("div_min_bars", _DEFAULT_DIV_MIN_BARS))

        if df_15m is None or len(df_15m) < max(lookback_bars + 5, 50):
            return results

        # ── Расчёт индикаторов ────────────────────────────────────────────
        df = calculate_wt(df_15m, n1=10, n2=21)
        df = calculate_trend(df, atr_period=43, factor=1.0)

        # Окно поиска: последние lookback_bars свечей
        window = df.iloc[-lookback_bars:].reset_index(drop=True)
        current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return results

        # ── Получаем дневные пивоты из кеша ──────────────────────────────
        daily_pivots = pivot_cache.get(f"{symbol}_1D") or {}

        # ── Проверка каждого условия ──────────────────────────────────────
        score = 0
        factors: List[str] = []
        factor_data: Dict[str, Any] = {}

        # 1. WT был в OS зоне в окне И сейчас не в OB (иначе сигнал устарел)
        wt_min_in_window = float(window["wt1"].min())
        wt_current = float(window["wt1"].iloc[-1])
        if wt_min_in_window < wt_os_thr and wt_current < wt_ob_thr:
            score += _SCORE_WT_OS
            factors.append("WT_OS")
            factor_data["wt_min"] = round(wt_min_in_window, 1)

        # 2. TSL пересечение — тренд сменился с -1 на 1 в окне
        trend_series = window["trend"].values
        tsl_cross_up = any(
            trend_series[i] == -1 and trend_series[i + 1] == 1
            for i in range(len(trend_series) - 1)
        )
        if tsl_cross_up:
            score += _SCORE_TSL_CROSS
            factors.append("TSL_CROSS_UP")

        # 3. Цена была у ключевого пивота (S1 или PP дневной/недельный)
        pivot_hit, pivot_desc = _check_near_pivot(window, daily_pivots,
                                                  pivot_cache, symbol, pivot_pct)
        if pivot_hit:
            score += _SCORE_NEAR_PIVOT
            factors.append("NEAR_PIVOT")
            factor_data["pivot_hit"] = pivot_desc

        # 4. Бычья дивергенция WT: price LL, wt1 HL
        div_found, div_desc = _check_bullish_divergence_wt(window, div_min_bars)
        if div_found:
            score += _SCORE_DIVERGENCE
            factors.append("WT_DIVERGENCE")
            factor_data["div_desc"] = div_desc

        # 5. Текущая цена выше дневного PP (подтверждение пробоя)
        daily_pp = daily_pivots.get("PP") or 0.0
        if daily_pp > 0 and current_price > daily_pp:
            score += _SCORE_ABOVE_PP
            factors.append("ABOVE_PP")
            factor_data["daily_pp"] = round(daily_pp, 8)

        # ── Сигнал только если score >= порога ───────────────────────────
        if score < min_strength:
            logger.debug("[confluence] %s: score=%d < %d — пропуск %s",
                         symbol, score, min_strength, factors)
            return results

        # Конфлюэнция бычья (long): WT OS + TSL UP + поддержка
        # Медвежья логика добавляется позже (Шаг 2)
        direction = SignalDirection.LONG

        desc = f"Конфлюэнция ({'|'.join(factors)})"
        interpretation = (
            f"score={score}/100 — {len(factors)} из 5 условий: {', '.join(factors)}"
        )

        sig = SignalData(
            symbol=symbol,
            signal_type=SignalType.CONFLUENCE,
            direction=direction,
            strength=min(score, 100),
            confidence=round(score / 100.0, 2),
            timestamp=datetime.now(),
            data={
                "score": score,
                "factors": factors,
                **factor_data,
                "lookback_bars": lookback_bars,
                "current_price": current_price,
            },
            timeframe="15m",
            description=desc,
            interpretation=interpretation,
        )

        logger.info("[confluence] %s: СИГНАЛ score=%d %s", symbol, score, factors)
        results.append(sig)

    except Exception:
        logger.exception("[confluence] Ошибка scan_confluence для %s", symbol)

    return results


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _check_near_pivot(
    window: pd.DataFrame,
    daily_pivots: Dict,
    pivot_cache: Dict,
    symbol: str,
    proximity_pct: float = _DEFAULT_PIVOT_PCT,
) -> tuple[bool, str]:
    """
    Проверяет: была ли цена (low) в окне в пределах _PIVOT_PROXIMITY_PCT%
    от уровней S1, S2, PP дневных или недельных пивотов.
    """
    if not daily_pivots:
        # Пробуем недельные как fallback
        daily_pivots = pivot_cache.get(f"{symbol}_1W") or {}

    if not daily_pivots:
        return False, ""

    check_levels = ["S1", "S2", "PP"]
    lows = window["low"].values
    closes = window["close"].values

    for level in check_levels:
        pv_price = daily_pivots.get(level) or 0.0
        if pv_price <= 0:
            continue
        for price in lows:
            dist_pct = abs(price - pv_price) / pv_price * 100
            if dist_pct <= proximity_pct:
                return True, f"1D_{level}={round(pv_price, 8)}"

    return False, ""


def _check_bullish_divergence_wt(
    window: pd.DataFrame,
    div_min_bars: int = _DEFAULT_DIV_MIN_BARS,
) -> tuple[bool, str]:
    """
    Упрощённая проверка бычьей дивергенции WT в окне.

    Условие: найти два трога WT (локальных минимума wt1) где:
      - второй трог по цене НИЖЕ первого (price LL)
      - второй трог по wt1  ВЫШЕ первого (wt  HL)
    """
    wt1 = window["wt1"].values
    lows = window["low"].values
    n = len(wt1)

    if n < div_min_bars * 2 + 1:
        return False, ""

    # Находим локальные минимумы wt1 (трогá)
    troughs = []
    for i in range(1, n - 1):
        if wt1[i] < wt1[i - 1] and wt1[i] < wt1[i + 1] and wt1[i] < -30:
            troughs.append(i)

    if len(troughs) < 2:
        return False, ""

    # Проверяем пары трогов: price LL + wt HL
    for j in range(1, len(troughs)):
        i1, i2 = troughs[j - 1], troughs[j]
        if i2 - i1 < div_min_bars:
            continue
        price_ll = lows[i2] < lows[i1]      # цена делает новый лоу
        wt_hl = wt1[i2] > wt1[i1]           # WT при этом выше
        if price_ll and wt_hl:
            desc = (f"price_low: {round(lows[i1], 6)}→{round(lows[i2], 6)}, "
                    f"wt: {round(wt1[i1], 1)}→{round(wt1[i2], 1)}")
            return True, desc

    return False, ""


def confluence_message(symbol: str, sig: "SignalData") -> str:
    """Форматирует TG-сообщение для confluence сигнала."""
    from core.message_builder import tv_link
    data = sig.data or {}
    factors = data.get("factors", [])
    score = data.get("score", 0)
    price = data.get("current_price", 0)

    emoji_map = {
        "WT_OS":       "🌊 WT OS",
        "TSL_CROSS_UP": "📈 TSL↑",
        "NEAR_PIVOT":  "🎯 Пивот",
        "WT_DIVERGENCE": "🔄 Дивер",
        "ABOVE_PP":    "✅ >PP",
    }
    factor_str = "  ·  ".join(emoji_map.get(f, f) for f in factors)

    strength_emoji = "🔥🔥🔥" if score >= 80 else "🔥🔥" if score >= 60 else "🔥"

    lines = [
        "\n",
        f"🔗 <b>CONFLUENCE · {tv_link(symbol)} · LONG ↑</b>",
        f"{strength_emoji} <b>{score}/100</b>  ({len(factors)}/5 факторов)",
        "",
        f"  {factor_str}",
    ]

    pivot_hit = data.get("pivot_hit", "")
    div_desc = data.get("div_desc", "")
    if pivot_hit:
        lines.append(f"  📍 {pivot_hit}")
    if div_desc:
        lines.append(f"  ↗️ {div_desc}")
    if price:
        try:
            from core.intelligence_formatter import _fmt_price
            lines += ["", f"  Цена: <code>{_fmt_price(float(price))}</code>"]
        except Exception:
            lines += ["", f"  Цена: {price}"]

    lines += ["", f"⏰ {datetime.now().strftime('%d.%m %H:%M')}", "\n"]
    return "\n".join(lines)
