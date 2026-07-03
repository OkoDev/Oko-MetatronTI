"""SHADOW-логгер atr_S2 (03.07.2026) — единственный эдж, переживший честную валидацию.

Рецепт (memory atr_s2_survived_honest, scripts/test_atr_s2.py): 4h ATRTrend-флип ВНИЗ + close <
недельного PP (пивоты ПРОШЛОЙ недели) → SHORT, цель недельная S2, SL за swing-high 12×4h.
Бэктест: +0.471%/сделку net, n=5290, 2022-2026, 4/5 лет. SHORT-only (LONG-зеркало −0.14).

Этот модуль ТОЛЬКО ЛОГИРУЕТ сетапы в logs/atr_s2_shadow.jsonl (никакой торговли) — копим живую
статистику для сверки с бэктестом перед включением. Вызов из scan_loop на atr_change_4h SHORT.
⚠️ df бота = RangeIndex + 'time'(ms), НЕ DatetimeIndex ([[feedback_get_ohlcv_format_trap]]) — конвертим.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_LOG_PATH = Path("logs/atr_s2_shadow.jsonl")
SL_LOOKBACK = 12          # swing-high окна (4h баров)
SL_BUF = 1.0015
MAX_RISK_PCT = 10.0


def _to_dt(df: pd.DataFrame) -> pd.DataFrame | None:
    """Бот-формат (RangeIndex + 'time' ms) → DatetimeIndex копия для resample."""
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    if "time" in df.columns:
        d = df.copy()
        d.index = pd.to_datetime(d["time"], unit="ms")
        return d
    return None


def check_atr_s2_setup(symbol: str, df_4h: pd.DataFrame, price: float) -> dict | None:
    """Проверяет сетап atr_S2 на 4h DOWN-флипе. Возвращает dict сетапа или None (без записи)."""
    try:
        d = _to_dt(df_4h)
        # 130×4h = ~22 дня: гарантия ПОЛНОЙ прошлой недели (60-баровый df скана ломал пивоты — 03.07)
        if d is None or len(d) < 130:
            return None
        # недельные пивоты ПРОШЛОЙ завершённой недели (текущую неполную неделю выбрасываем)
        wk = d.resample("W").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        if len(wk) < 4:
            return None
        prev = wk.iloc[-2]                          # последняя ЗАВЕРШЁННАЯ неделя
        pp = float((prev["high"] + prev["low"] + prev["close"]) / 3)
        s1 = float(2 * pp - prev["high"])
        s2 = float(pp - (prev["high"] - prev["low"]))
        if price >= pp:                             # bias-фильтр: только ниже WPP
            return None
        if s2 >= price:                             # цель уже пройдена/выше цены — невалидна
            return None
        sl = float(d["high"].values[-SL_LOOKBACK:].max()) * SL_BUF
        risk_pct = (sl - price) / price * 100.0
        if sl <= price or risk_pct > MAX_RISK_PCT:
            return None
        return {
            "ts": int(time.time() * 1000),
            "symbol": symbol,
            "entry": price,
            "wpp": pp, "s1": s1, "s2": s2,
            "sl": sl, "risk_pct": round(risk_pct, 3),
            "tp_pct": round((price - s2) / price * 100.0, 3),
        }
    except Exception as e:  # noqa: BLE001 — shadow не должен ломать scan_loop
        logger.debug("[ATR-S2-SHADOW] %s error: %s", symbol, e)
        return None


def log_atr_s2_setup(symbol: str, df_4h: pd.DataFrame, price: float) -> None:
    """Проверить и записать сетап в JSONL (fire-and-forget, безопасно для scan_loop)."""
    setup = check_atr_s2_setup(symbol, df_4h, price)
    if setup is None:
        return
    try:
        _LOG_PATH.parent.mkdir(exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(setup, ensure_ascii=False) + "\n")
        logger.info("[ATR-S2-SHADOW] %s SHORT setup: entry=%.6g S2=%.6g SL=%.6g (risk %.2f%%, tp %.2f%%)",
                    symbol, setup["entry"], setup["s2"], setup["sl"], setup["risk_pct"], setup["tp_pct"])
    except Exception as e:  # noqa: BLE001
        logger.debug("[ATR-S2-SHADOW] %s write error: %s", symbol, e)
