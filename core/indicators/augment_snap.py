"""
ARCH-128 AUGMENT — единый калькулятор «недостающих» признаков для condition-mining.

🔴 ИНВАРИАНТ «ОДИН КАЛЬКУЛЯТОР» (ARCH-118): эта функция — ЕДИНСТВЕННЫЙ путь расчёта
augment-признаков. Вызывается из:
  A) live-снимка на РЕГИСТРАЦИИ сделки (feature_snapshot / trade_simulator), НЕ в hot scan-loop.
  B) backtest-харнесса ре-майна (тот же df → те же числа).
Запрещён второй независимый расчёт этих признаков.

Зачем: карта (docs/FEATURE_CATALOG.md) показала, что условные edge из памяти
(wt_b×ADX<25, divergence×n_down=3-4, волновые фазы) НЕ попадали в снимок — их не было.
Все детекторы уже существуют, здесь только ПРОВОДКА (reuse, не дублирование):
  - ADX/RSI            → core.indicators.indicators.compute_adx / compute_rsi
  - n_up/n_down        → find_swing_lows/highs + calculate_n_up/n_down (прокси волны Эллиотта)
  - Elliott (фрактал)  → core.smc.smc_engine.detect_elliott_mtf (single + multi-scale)
  - fib retracement    → позиция цены в swing-диапазоне (+ w2/w4 retr из импульса)

Считается на РЕГИСТРАЦИИ (раз на сделку) → детект Эллиотта (3 zigzag-прохода) не грузит
горячий цикл. Каждый под-расчёт в try/except → один сбой не валит снимок.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# swing period для n_up/n_down (эталон find_swing_* = 5, под OKO-SM pivot)
_SWING_PERIOD = 5
_MIN_BARS = 30


def compute_augment_snap(df: Optional[pd.DataFrame]) -> dict[str, Any]:
    """Единый калькулятор augment-признаков из готового OHLCV-DataFrame.

    Возвращает плоский dict (под snapshot): adx, rsi, n_up, n_down, fib_retracement,
    in_ote + вложенный elliott{direction, scale, w2_retr, w4_retr, w3_ext, textbook, n_impulses}.
    Пустой/короткий df → {} (декодер восстановит отсутствие).
    """
    out: dict[str, Any] = {}
    if df is None or len(df) < _MIN_BARS:
        return out
    cols = set(df.columns)
    if not {"high", "low", "close"}.issubset(cols):
        return out

    h, l, c = df["high"], df["low"], df["close"]

    # --- ADX / RSI (единый источник indicators.py) ---
    try:
        from core.indicators.indicators import compute_adx, compute_rsi
        adx = compute_adx(h.tolist(), l.tolist(), c.tolist())
        rsi = compute_rsi(c)
        if adx is not None:
            out["adx"] = round(float(adx), 1)
        if rsi is not None:
            out["rsi"] = round(float(rsi), 1)
    except Exception:
        pass

    # --- n_up / n_down (прокси восходящей/нисходящей волны Эллиотта) ---
    try:
        from core.indicators.indicators import (
            find_swing_highs, find_swing_lows, calculate_n_down, calculate_n_up,
        )
        out["n_down"] = calculate_n_down(find_swing_highs(h, _SWING_PERIOD))
        out["n_up"] = calculate_n_up(find_swing_lows(l, _SWING_PERIOD))
    except Exception:
        pass

    # --- Elliott: single + multi-scale (фрактальная мультиструктура) ---
    try:
        from core.smc.smc_engine import detect_elliott_mtf
        imps = detect_elliott_mtf(df)
        if imps:
            last = imps[-1]   # самый крупный масштаб последним (detect_elliott_mtf: мелкий→крупный)
            out["elliott"] = {
                "direction": last.get("direction"),
                "scale": last.get("scale"),          # dev zigzag = степень волны
                "w2_retr": last.get("w2_retr"),      # откат волны 2 (классич. OTE 0.5-0.886)
                "w4_retr": last.get("w4_retr"),
                "w3_ext": last.get("w3_ext"),        # расширение волны 3 (≥1.618 = сильный импульс)
                "textbook": last.get("textbook"),
                "n_impulses": len(imps),             # импульсов на разных масштабах = мультиструктура
            }
    except Exception:
        pass

    # --- fib retracement: позиция цены в недавнем swing-диапазоне (50 баров) ---
    try:
        cur = float(c.iloc[-1])
        hi = float(h.tail(50).max())
        lo = float(l.tail(50).min())
        if hi > lo:
            r = (cur - lo) / (hi - lo)
            out["fib_retracement"] = round(r, 3)
            # OTE-зона по фибо (0.5-0.79 от диапазона, в любую сторону от середины)
            out["in_ote"] = bool(0.21 <= r <= 0.5 or 0.5 <= r <= 0.79)
    except Exception:
        pass

    return out
