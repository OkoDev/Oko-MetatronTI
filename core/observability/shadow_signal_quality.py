"""
Shadow Signal Quality — 27.05.2026.

Вычисляет shadow flags для 4 правок улучшения качества триггеров
(консенсус роя 5/5):
  - pivot_reversal: real touch + volume spike
  - wt_signal: confirmation aggregation (≥1 из SMC/OTE/pivot/div)
  - confluence: divergence required
  - общий timing-guard: scan_loop_duration > 250s

Все проверки SHADOW: записывают результат в features_json, НО не блокируют
сделку. Через 50-100 сделок — A/B анализ:
    SELECT signal_type, AVG(R_multiple) FROM simulated_trades
    WHERE features_json LIKE '%"shadow_..._would_pass": true%'

Включение в production: добавить hard gate в детектор/router при подтверждении.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Веса confirmations (из ConfirmationRegistry) которые ценны для wt_signal
_WT_REQUIRED_CONFIRM_SOURCES = (
    "smc_bos_15m", "smc_bos_1h", "smc_choch_15m", "smc_choch_1h",
    "ote_zone", "pivot_confluence_2plus", "hidden_div_15m", "hidden_div_1h",
    "fvg_touch", "wt_extreme",
)

# Порог timing-guard (сек). Из консенсуса роя.
_SCAN_LOOP_LATE_THRESHOLD = 250.0


def compute_shadow_flags(
    bot,
    recommendation,
    df_15m=None,
    scan_loop_duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Вычисляет shadow flags для записи в features_json.

    Args:
        bot: ссылка на бот (для confirmation_aggregator)
        recommendation: TradingRecommendation
        df_15m: pre-fetched 15m DataFrame (опционально, для pivot real_touch + volume)
        scan_loop_duration_sec: длительность последнего scan_loop цикла

    Returns:
        dict с shadow_* полями. Все опциональные — заполняются только если есть данные.
    """
    flags: Dict[str, Any] = {}

    try:
        sig_type = _get_signal_type(recommendation)
        flags["shadow_signal_type"] = sig_type
        direction = _get_direction(recommendation)
        symbol = getattr(recommendation, "symbol", "") or ""

        # ── 1. pivot_reversal: real touch + volume spike ─────────────────────
        if sig_type == "pivot_reversal" and df_15m is not None and len(df_15m) >= 21:
            flags.update(_compute_pivot_shadow(recommendation, df_15m, direction))

        # ── 2. wt_signal: confirmation aggregation ─────────────────────────────
        if sig_type == "wt_signal" and symbol and direction:
            flags.update(_compute_wt_shadow(bot, symbol, direction))

        # ── 3. confluence: divergence required ────────────────────────────────
        if sig_type == "confluence":
            flags.update(_compute_confluence_shadow(recommendation))

        # ── 4. Общий timing-guard ─────────────────────────────────────────────
        # Источники в порядке приоритета: параметр → bot._last_scan["elapsed_sec"]
        _scan_dur = scan_loop_duration_sec
        if _scan_dur is None:
            try:
                _last = getattr(bot, "_last_scan", None) or {}
                _scan_dur = _last.get("elapsed_sec")
            except Exception:
                pass
        if _scan_dur is not None:
            late = _scan_dur > _SCAN_LOOP_LATE_THRESHOLD
            flags["shadow_scan_loop_late"] = late
            flags["shadow_scan_loop_duration_s"] = round(float(_scan_dur), 1)

    except Exception as e:
        logger.debug("[shadow_signal_quality] error: %s (%s)", e, type(e).__name__)

    return flags


# ──────────────────────────────────────────────────────────────────────────
# Внутренние помощники
# ──────────────────────────────────────────────────────────────────────────

def _get_signal_type(rec) -> str:
    """Извлекает signal_type из TradingRecommendation (через supporting_signals)."""
    try:
        sigs = getattr(rec, "supporting_signals", []) or []
        for s in sigs:
            st = getattr(s, "signal_type", None)
            if st is not None:
                return st.value if hasattr(st, "value") else str(st)
    except Exception:
        pass
    return ""


def _get_direction(rec) -> str:
    """Возвращает 'LONG' | 'SHORT' | ''."""
    try:
        d = getattr(rec, "direction", None)
        if d is None:
            return ""
        return d.value if hasattr(d, "value") else str(d)
    except Exception:
        return ""


def _compute_pivot_shadow(rec, df_15m, direction: str) -> Dict[str, Any]:
    """pivot_reversal shadow checks: real touch + volume spike."""
    out: Dict[str, Any] = {}

    # Находим pivot level из supporting_signals.data
    level: Optional[float] = None
    try:
        for s in (rec.supporting_signals or []):
            data = getattr(s, "data", None) or {}
            lvl = data.get("level_price") or data.get("price") or data.get("level")
            if isinstance(lvl, (int, float)) and lvl > 0:
                level = float(lvl)
                break
    except Exception:
        pass

    if level is None:
        out["shadow_pivot_real_touch"] = None
        out["shadow_pivot_volume_spike"] = None
        return out

    # Real touch: LONG требует low[-1] < level < close[-1] (wick через + reclaim)
    try:
        low_curr = float(df_15m["low"].iloc[-1])
        high_curr = float(df_15m["high"].iloc[-1])
        close_curr = float(df_15m["close"].iloc[-1])
        if direction == "LONG":
            real_touch = (low_curr < level) and (close_curr > level)
        elif direction == "SHORT":
            real_touch = (high_curr > level) and (close_curr < level)
        else:
            real_touch = None
        out["shadow_pivot_real_touch"] = real_touch
    except Exception:
        out["shadow_pivot_real_touch"] = None

    # Volume spike: vol[-1] > avg(vol[-21:-1]) * 1.3
    try:
        vol = df_15m["volume"].iloc[-21:-1]  # 20 предыдущих свечей
        avg_vol = float(vol.mean()) if len(vol) > 0 else 0.0
        last_vol = float(df_15m["volume"].iloc[-1])
        if avg_vol > 0:
            out["shadow_pivot_volume_spike"] = last_vol > avg_vol * 1.3
            out["shadow_pivot_vol_ratio"] = round(last_vol / avg_vol, 2)
        else:
            out["shadow_pivot_volume_spike"] = None
    except Exception:
        out["shadow_pivot_volume_spike"] = None

    # Would pass (оба HARD)
    would_pass = (out.get("shadow_pivot_real_touch") is True
                  and out.get("shadow_pivot_volume_spike") is True)
    out["shadow_pivot_would_pass"] = would_pass
    return out


def _compute_wt_shadow(bot, symbol: str, direction: str) -> Dict[str, Any]:
    """wt_signal shadow: проверка наличия ≥1 подтверждения в ConfirmationAggregator."""
    out: Dict[str, Any] = {}
    try:
        ca = getattr(bot, "confirmation_aggregator", None)
        if ca is None:
            return out
        side = direction  # 'LONG' | 'SHORT'
        agg = ca.aggregate(symbol, side) or {}
        confs = agg.get("confirmations") or []
        sources = [getattr(c, "source", "") for c in confs]
        # Релевантные подтверждения (из консенсуса роя)
        relevant = [s for s in sources if s in _WT_REQUIRED_CONFIRM_SOURCES]
        out["shadow_wt_confirm_sources"] = ",".join(relevant) if relevant else ""
        out["shadow_wt_confirm_count"] = len(relevant)
        out["shadow_wt_would_pass"] = len(relevant) >= 1
    except Exception as e:
        logger.debug("[shadow_wt] %s: %s", symbol, e)
    return out


def _compute_confluence_shadow(rec) -> Dict[str, Any]:
    """confluence shadow: проверка наличия divergence в supporting_signals.data."""
    out: Dict[str, Any] = {}
    try:
        div_count = 0
        for s in (rec.supporting_signals or []):
            data = getattr(s, "data", None) or {}
            # Поля где confluence пишет div info (из confluence_scanner.py)
            if data.get("has_div") or data.get("div_strength", 0) > 0:
                div_count += 1
            # Иногда в data попадает div_count напрямую
            dc = data.get("div_count")
            if isinstance(dc, int) and dc > 0:
                div_count = max(div_count, dc)
        out["shadow_confluence_div_count"] = div_count
        out["shadow_confluence_would_pass"] = div_count >= 1
    except Exception:
        pass
    return out
