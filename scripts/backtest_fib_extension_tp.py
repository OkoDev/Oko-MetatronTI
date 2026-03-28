#!/usr/bin/env python3
"""
Бэктест: Fibonacci Extension TP для OTE сетапов
================================================
Сравниваются три метода расчёта TP после входа из OTE зоны:

Set A — Fib Retracement 1.618 / 2.618 / 3.618 (от impulse_low вверх):
  TP1_A = impulse_low + 1.618 × range  = impulse_high + 0.618 × range
  TP2_A = impulse_low + 2.618 × range  = impulse_high + 1.618 × range
  TP3_A = impulse_low + 3.618 × range  = impulse_high + 2.618 × range

Set B — Fib Extension 1.0 / 1.618 / 2.618 (от impulse_high вверх):
  TP1_B = impulse_high              (уровень 1.0 — возврат к HIGH)
  TP2_B = impulse_high + 0.618 × range  (= TP1_A)
  TP3_B = impulse_high + 1.618 × range  (= TP2_A)

Ранее тестировалось (v1): 1.272 / 1.618 / 2.618 — hit rate 5-13%, признано неэффективным.
лучше чем текущий ATR-based TP (entry + ATR_TP_MULT × ATR).

Условия входа (LONG / SHORT зеркально):
  1. Структурный пробой (BOS/CHoCH) сформировал импульс
  2. Откат цены в OTE зону (0.618–0.786 от impulse range)
  3. WT crossup в зоне перепроданности (WT1 < WT_OVERSOLD)
  4. ATR trend crossup в пределах ATR_WINDOW баров

SL: impulse_low − ATR_SL_BUFFER × ATR  (для LONG)
TSL: активируется после +1R, следует за trendup

Запуск:
  python scripts/backtest_fib_extension_tp.py
  python scripts/backtest_fib_extension_tp.py --tf 1h
"""
import os, sys, asyncio, sqlite3, logging, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend
from core.smc.structure import detect_structure, BreakType
from core.smc.fibonacci import _calc_fib_levels, _calc_ote, FibZone

logging.basicConfig(level=logging.WARNING)

# ── Параметры ────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT    = 60       # Количество символов для теста
CANDLES          = 600      # Глубина истории
WT_OVERSOLD      = -35      # Порог WT перепроданности (для LONG)
WT_OVERBOUGHT    = 35       # Порог WT перекупленности (для SHORT)
ATR_WINDOW       = 2        # Окно для ATR crossup (баров)
ATR_FACTOR       = 1.25     # ATR множитель для trendup
ATR_SL_BUFFER    = 0.3      # Буфер SL в ATR от impulse_low
ATR_TP_MULT      = 2.5      # Множитель для ATR-based TP (сравнение)
MIN_SL_PCT       = 0.003    # Минимальный SL 0.3%
MAX_SL_PCT       = 0.10     # Максимальный SL 10%
MAX_BARS_HOLD    = 200      # Максимальное удержание (баров)
TSL_ACTIVATION_R = 1.0      # Активация TSL

# Set A — Fib Retracement 1.618/2.618/3.618 (от impulse_low):
#   tp = impulse_high + ADD × range
FIB_A_TP1_ADD = 0.618   # impulse_low+1.618×r = impulse_high+0.618×r
FIB_A_TP2_ADD = 1.618   # impulse_low+2.618×r = impulse_high+1.618×r
FIB_A_TP3_ADD = 2.618   # impulse_low+3.618×r = impulse_high+2.618×r

# Set B — Fib Extension 1.0/1.618/2.618 (от impulse_high):
#   TP1 = impulse_high (1.0), потом добавляем
FIB_B_TP1_ADD = 0.0     # impulse_high сам (уровень 1.0)
FIB_B_TP2_ADD = 0.618   # impulse_high + 0.618×r (= Set A TP1)
FIB_B_TP3_ADD = 1.618   # impulse_high + 1.618×r (= Set A TP2)


def build_fib_zones(df: pd.DataFrame) -> list:
    """
    Запускает detect_structure один раз, строит FibZone для каждого break.
    Возвращает список (break_index, FibZone) — sorted by break_index.
    """
    try:
        structure = detect_structure(df)
    except Exception as e:
        logging.debug("detect_structure error: %s", e)
        return []

    if not structure.breaks:
        return []

    sa = structure.swing_analysis
    result = []

    for brk in structure.breaks:
        swing = brk.broken_swing
        is_bullish = brk.break_type in (BreakType.BULLISH_BOS, BreakType.BULLISH_CHOCH)
        direction = "LONG" if is_bullish else "SHORT"

        try:
            if is_bullish:
                impulse_high = swing.value
                prev_lows = [s for s in sa.lows if s.index < swing.index]
                if not prev_lows:
                    continue
                impulse_low = prev_lows[-1].value
            else:
                impulse_low = swing.value
                prev_highs = [s for s in sa.highs if s.index < swing.index]
                if not prev_highs:
                    continue
                impulse_high = prev_highs[-1].value

            if impulse_high <= impulse_low:
                continue

            ote_top, ote_bottom = _calc_ote(impulse_high, impulse_low, direction)

            zone = FibZone(
                direction=direction,
                impulse_high=impulse_high,
                impulse_low=impulse_low,
                ote_top=ote_top,
                ote_bottom=ote_bottom,
                ote_midpoint=(ote_top + ote_bottom) / 2,
                price_in_ote=False,
            )
            result.append((brk.break_index, zone))

        except Exception as e:
            logging.debug("build_fib_zones zone error: %s", e)
            continue

    return sorted(result, key=lambda x: x[0])


def calc_atr(df: pd.DataFrame, i: int, period: int = 14) -> float:
    """ATR на баре i."""
    start = max(0, i - period)
    sub = df.iloc[start:i+1]
    if len(sub) < 2:
        return float(df["close"].iloc[i]) * 0.01
    trs = []
    for j in range(1, len(sub)):
        h = float(sub["high"].iloc[j])
        l = float(sub["low"].iloc[j])
        pc = float(sub["close"].iloc[j-1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else float(df["close"].iloc[i]) * 0.01


def find_ote_signals(df: pd.DataFrame, fib_zones: list) -> list:
    """
    Ищет OTE-входы:
      LONG: цена в OTE зоне (ote_bottom <= price <= ote_top) + WT crossup OS
      SHORT: цена в OTE зоне + WT crossdown OB

    Возвращает сигналы с Fib TP уровнями и ATR TP.
    """
    if not fib_zones:
        return []

    signals = []
    seen = set()  # (direction, zone_idx) — одна зона даёт один вход

    for i in range(30, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_cur) or pd.isna(wt2_cur) or pd.isna(wt1_prev) or pd.isna(wt2_prev):
            continue

        # WT crossup (LONG) или crossdown (SHORT)
        long_cross  = (wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)
        short_cross = (wt1_prev > wt2_prev) and (wt1_cur <= wt2_cur)

        if not long_cross and not short_cross:
            continue

        # ATR crossup/crossdown
        if long_cross:
            if wt1_cur >= WT_OVERSOLD:
                continue
            need_trend = "LONG"
            atr_ok = False
            for w in range(ATR_WINDOW + 1):
                ii = i - w
                if ii >= 1:
                    t_now  = df["trend"].iloc[ii]
                    t_prev = df["trend"].iloc[ii-1]
                    if not pd.isna(t_now) and not pd.isna(t_prev) and t_now == 1.0 and t_prev == -1.0:
                        atr_ok = True
                        break
            if not atr_ok:
                continue
        else:  # short_cross
            if wt1_cur <= WT_OVERBOUGHT:
                continue
            need_trend = "SHORT"
            atr_ok = False
            for w in range(ATR_WINDOW + 1):
                ii = i - w
                if ii >= 1:
                    t_now  = df["trend"].iloc[ii]
                    t_prev = df["trend"].iloc[ii-1]
                    if not pd.isna(t_now) and not pd.isna(t_prev) and t_now == -1.0 and t_prev == 1.0:
                        atr_ok = True
                        break
            if not atr_ok:
                continue

        price = float(df["close"].iloc[i])

        # Ищем активную OTE зону (самую свежую break_index <= i, нужного direction)
        active_zone = None
        for zone_idx, (bi, zone) in enumerate(fib_zones):
            if bi > i:
                break
            if zone.direction != need_trend:
                continue
            # Цена в OTE зоне?
            if zone.ote_bottom <= price <= zone.ote_top:
                active_zone = (zone_idx, zone)

        if active_zone is None:
            continue

        zone_idx, zone = active_zone

        # Одна зона → один вход
        sig_key = (need_trend, zone_idx)
        if sig_key in seen:
            continue
        seen.add(sig_key)

        entry_idx   = i + 1
        entry_price = float(df["open"].iloc[entry_idx])
        if entry_price <= 0:
            continue

        atr_now = calc_atr(df, i)
        impulse_range = zone.impulse_high - zone.impulse_low

        if need_trend == "LONG":
            sl_price   = zone.impulse_low - ATR_SL_BUFFER * atr_now
            # Set A: Retracement 1.618/2.618/3.618
            fib_a_tp1  = zone.impulse_high + FIB_A_TP1_ADD * impulse_range
            fib_a_tp2  = zone.impulse_high + FIB_A_TP2_ADD * impulse_range
            fib_a_tp3  = zone.impulse_high + FIB_A_TP3_ADD * impulse_range
            # Set B: Extension 1.0/1.618/2.618
            fib_b_tp1  = zone.impulse_high + FIB_B_TP1_ADD * impulse_range  # = impulse_high
            fib_b_tp2  = zone.impulse_high + FIB_B_TP2_ADD * impulse_range
            fib_b_tp3  = zone.impulse_high + FIB_B_TP3_ADD * impulse_range
            atr_tp     = entry_price + ATR_TP_MULT * atr_now
        else:
            sl_price   = zone.impulse_high + ATR_SL_BUFFER * atr_now
            fib_a_tp1  = zone.impulse_low - FIB_A_TP1_ADD * impulse_range
            fib_a_tp2  = zone.impulse_low - FIB_A_TP2_ADD * impulse_range
            fib_a_tp3  = zone.impulse_low - FIB_A_TP3_ADD * impulse_range
            fib_b_tp1  = zone.impulse_low - FIB_B_TP1_ADD * impulse_range   # = impulse_low
            fib_b_tp2  = zone.impulse_low - FIB_B_TP2_ADD * impulse_range
            fib_b_tp3  = zone.impulse_low - FIB_B_TP3_ADD * impulse_range
            atr_tp     = entry_price - ATR_TP_MULT * atr_now

        # Валидация SL
        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct < MIN_SL_PCT or sl_dist_pct > MAX_SL_PCT:
            continue

        signals.append({
            "signal_idx":     i,
            "entry_idx":      entry_idx,
            "direction":      need_trend,
            "entry_price":    entry_price,
            "sl_price":       float(sl_price),
            "sl_pct":         sl_dist_pct * 100,
            # Set A: Retracement 1.618/2.618/3.618
            "fib_a_tp1":      fib_a_tp1,
            "fib_a_tp2":      fib_a_tp2,
            "fib_a_tp3":      fib_a_tp3,
            # Set B: Extension 1.0/1.618/2.618
            "fib_b_tp1":      fib_b_tp1,
            "fib_b_tp2":      fib_b_tp2,
            "fib_b_tp3":      fib_b_tp3,
            "atr_tp":         atr_tp,
            "impulse_range":  impulse_range,
            "wt1":            wt1_cur,
            # legacy aliases (для совместимости со старым кодом)
            "fib_tp1":        fib_a_tp1,
            "fib_tp2":        fib_a_tp2,
            "fib_tp3":        fib_a_tp3,
        })

    return signals


def simulate_trade(df: pd.DataFrame, sig: dict) -> dict:
    """
    Симуляция от entry_idx вперёд.
    Возвращает exit_r и флаги hit_tp1/tp2/tp3 (Fib) и hit_atr_tp.
    TSL активируется после +1R (по trendup).
    """
    entry_idx   = sig["entry_idx"]
    entry_price = sig["entry_price"]
    sl_price    = sig["sl_price"]
    direction   = sig["direction"]
    fib_a_tp1   = sig["fib_a_tp1"]
    fib_a_tp2   = sig["fib_a_tp2"]
    fib_a_tp3   = sig["fib_a_tp3"]
    fib_b_tp1   = sig["fib_b_tp1"]
    fib_b_tp2   = sig["fib_b_tp2"]
    fib_b_tp3   = sig["fib_b_tp3"]
    atr_tp      = sig["atr_tp"]
    # legacy
    fib_tp1 = fib_a_tp1
    fib_tp2 = fib_a_tp2
    fib_tp3 = fib_a_tp3

    one_r = abs(entry_price - sl_price)
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    hit_a_tp1 = hit_a_tp2 = hit_a_tp3 = False
    hit_b_tp1 = hit_b_tp2 = hit_b_tp3 = False
    # legacy aliases
    hit_tp1 = hit_tp2 = hit_tp3 = hit_atr_tp = False
    current_sl = sl_price
    tsl_activated = False
    exit_r = None
    status = "OPEN"

    end_idx = min(entry_idx + MAX_BARS_HOLD, len(df) - 1)

    for i in range(entry_idx + 1, end_idx + 1):
        high  = float(df["high"].iloc[i])
        low   = float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])

        if direction == "LONG":
            top_price = high
            bot_price = low
        else:
            top_price = low   # для SHORT "top" — это низ
            bot_price = high  # для SHORT "bot" — это верх

        # Проверяем Fib TP hits (не меняют сделку, только фиксируем факт)
        if direction == "LONG":
            if not hit_a_tp1 and high >= fib_a_tp1: hit_a_tp1 = True
            if not hit_a_tp2 and high >= fib_a_tp2: hit_a_tp2 = True
            if not hit_a_tp3 and high >= fib_a_tp3: hit_a_tp3 = True
            if not hit_b_tp1 and high >= fib_b_tp1: hit_b_tp1 = True
            if not hit_b_tp2 and high >= fib_b_tp2: hit_b_tp2 = True
            if not hit_b_tp3 and high >= fib_b_tp3: hit_b_tp3 = True
            if not hit_atr_tp and high >= atr_tp:   hit_atr_tp = True
            # legacy
            hit_tp1 = hit_a_tp1; hit_tp2 = hit_a_tp2; hit_tp3 = hit_a_tp3
        else:
            if not hit_a_tp1 and low <= fib_a_tp1: hit_a_tp1 = True
            if not hit_a_tp2 and low <= fib_a_tp2: hit_a_tp2 = True
            if not hit_a_tp3 and low <= fib_a_tp3: hit_a_tp3 = True
            if not hit_b_tp1 and low <= fib_b_tp1: hit_b_tp1 = True
            if not hit_b_tp2 and low <= fib_b_tp2: hit_b_tp2 = True
            if not hit_b_tp3 and low <= fib_b_tp3: hit_b_tp3 = True
            if not hit_atr_tp and low <= atr_tp:   hit_atr_tp = True
            hit_tp1 = hit_a_tp1; hit_tp2 = hit_a_tp2; hit_tp3 = hit_a_tp3

        # SL hit?
        if direction == "LONG" and low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            status = "TSL" if tsl_activated else "SL"
            break
        if direction == "SHORT" and high >= current_sl:
            exit_r = (entry_price - current_sl) / one_r
            status = "TSL" if tsl_activated else "SL"
            break

        # TSL activation
        if direction == "LONG":
            cur_r = (close - entry_price) / one_r
        else:
            cur_r = (entry_price - close) / one_r

        if not tsl_activated and cur_r >= TSL_ACTIVATION_R:
            tsl_activated = True

        # TSL update (по trendup/trenddown)
        if tsl_activated:
            if direction == "LONG":
                new_sl = df["trendup"].iloc[i]
                if not pd.isna(new_sl) and float(new_sl) > current_sl:
                    current_sl = float(new_sl)
            else:
                new_sl = df["trenddown"].iloc[i]
                if not pd.isna(new_sl) and float(new_sl) < current_sl:
                    current_sl = float(new_sl)

    if exit_r is None:
        # Открытая или по MAX_BARS_HOLD
        last = float(df["close"].iloc[end_idx])
        if direction == "LONG":
            exit_r = (last - entry_price) / one_r
        else:
            exit_r = (entry_price - last) / one_r
        status = "OPEN"

    # R при фиксированных TP (если бы мы закрыли на этом уровне)
    if direction == "LONG":
        r_at_a_tp1 = (fib_a_tp1 - entry_price) / one_r
        r_at_a_tp2 = (fib_a_tp2 - entry_price) / one_r
        r_at_a_tp3 = (fib_a_tp3 - entry_price) / one_r
        r_at_b_tp1 = (fib_b_tp1 - entry_price) / one_r
        r_at_b_tp2 = (fib_b_tp2 - entry_price) / one_r
        r_at_b_tp3 = (fib_b_tp3 - entry_price) / one_r
        r_at_atr   = (atr_tp    - entry_price) / one_r
    else:
        r_at_a_tp1 = (entry_price - fib_a_tp1) / one_r
        r_at_a_tp2 = (entry_price - fib_a_tp2) / one_r
        r_at_a_tp3 = (entry_price - fib_a_tp3) / one_r
        r_at_b_tp1 = (entry_price - fib_b_tp1) / one_r
        r_at_b_tp2 = (entry_price - fib_b_tp2) / one_r
        r_at_b_tp3 = (entry_price - fib_b_tp3) / one_r
        r_at_atr   = (entry_price - atr_tp)    / one_r

    return {
        "status":      status,
        "exit_r":      exit_r,
        # Set A hits
        "hit_a_tp1":   hit_a_tp1, "hit_a_tp2": hit_a_tp2, "hit_a_tp3": hit_a_tp3,
        # Set B hits
        "hit_b_tp1":   hit_b_tp1, "hit_b_tp2": hit_b_tp2, "hit_b_tp3": hit_b_tp3,
        "hit_atr_tp":  hit_atr_tp,
        # R at each level
        "r_at_a_tp1":  r_at_a_tp1, "r_at_a_tp2": r_at_a_tp2, "r_at_a_tp3": r_at_a_tp3,
        "r_at_b_tp1":  r_at_b_tp1, "r_at_b_tp2": r_at_b_tp2, "r_at_b_tp3": r_at_b_tp3,
        "r_at_atr":    r_at_atr,
        # legacy
        "hit_tp1": hit_a_tp1, "hit_tp2": hit_a_tp2, "hit_tp3": hit_a_tp3,
        "r_at_tp1": r_at_a_tp1, "r_at_tp2": r_at_a_tp2, "r_at_tp3": r_at_a_tp3,
        "bars":     end_idx - sig["entry_idx"],
        "sl_pct":   sig["sl_pct"],
    }


def print_metrics(label: str, trades: list):
    n = len(trades)
    if n == 0:
        print(f"\n  {label}: нет сделок")
        return

    rs     = [t["exit_r"] for t in trades]
    wins   = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wrate  = 100 * len(wins) / n
    avg_r  = sum(rs) / n
    win_r  = sum(wins) / len(wins) if wins else 0
    loss_r = sum(losses) / len(losses) if losses else 0
    pf     = (win_r * len(wins)) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")

    rs_arr = np.array(rs)
    sharpe = rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0

    cum    = np.cumsum(rs_arr)
    peak   = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()

    sl_exits  = [t for t in trades if t["status"] == "SL"]
    tsl_exits = [t for t in trades if t["status"] == "TSL"]
    open_pos  = [t for t in trades if t["status"] == "OPEN"]

    print(f"\n  {label}")
    print(f"  {'─'*55}")
    print(f"  Сделок:        {n}  {'⚠️  мало' if n < 30 else ''}")
    print(f"  Win Rate:      {wrate:.1f}%   {'✅' if wrate >= 45 else '⚠️ '}")
    print(f"  Avg R:         {avg_r:+.3f}   {'✅' if avg_r >= 0.5 else '⚠️ '}")
    print(f"  Avg R (win):   {win_r:+.3f}")
    print(f"  Avg R (loss):  {loss_r:+.3f}")
    print(f"  Profit Factor: {pf:.2f}   {'✅' if pf >= 1.5 else '⚠️ '}")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Max DD (R):    {max_dd:+.2f}")
    print(f"  Avg bars hold: {sum(t['bars'] for t in trades)/n:.0f}")
    print(f"  Avg SL dist:   {sum(t['sl_pct'] for t in trades)/n:.2f}%")
    print(f"  Выходы:        SL={len(sl_exits)}  TSL={len(tsl_exits)}  OPEN={len(open_pos)}")

    # R-distribution
    buckets = [("<−1R", lambda r: r < -1),
               ("−1–0R", lambda r: -1 <= r < 0),
               ("0–1R",  lambda r: 0  <= r < 1),
               ("1–2R",  lambda r: 1  <= r < 2),
               ("2–3R",  lambda r: 2  <= r < 3),
               ("3–5R",  lambda r: 3  <= r < 5),
               ("5R+",   lambda r: r >= 5)]
    print()
    for lbl, fn in buckets:
        cnt = sum(1 for t in trades if fn(t["exit_r"]))
        bar = "█" * max(0, cnt * 30 // max(n, 1))
        print(f"  {lbl:7s}: {cnt:3d}  {bar}")


def expected_partial_r(trades: list, n: int, hit_key1: str, hit_key2: str,
                        r_key1: str, r_key2: str) -> float:
    """
    Ожидаемый R при схеме 20% на TP1, 50% на TP2, 30% runner (TSL).
    Если не доходит до TP1 → -1R на 100% позиции.
    """
    hit1 = sum(1 for t in trades if t[hit_key1])
    hit2 = sum(1 for t in trades if t[hit_key2])
    hits_tp1_and_tp2 = sum(1 for t in trades if t[hit_key1] and t[hit_key2])
    hits_tp1_only    = hit1 - hits_tp1_and_tp2

    avg_r1 = sum(t[r_key1] for t in trades) / n
    avg_r2 = sum(t[r_key2] for t in trades) / n

    if hit2 > 0:
        runners = [t["exit_r"] for t in trades if t[hit_key2]]
        avg_runner = sum(runners) / len(runners)
    else:
        avg_runner = -1.0

    exp_r = 0.0
    exp_r += ((0.20 * avg_r1 + 0.50 * avg_r2 + 0.30 * avg_runner) * hits_tp1_and_tp2 / n)
    exp_r += ((0.20 * avg_r1 + 0.80 * -1.0) * hits_tp1_only / n)
    exp_r += (-1.0 * (n - hit1) / n)
    return exp_r


def print_fib_analysis(trades: list, timeframe: str):
    """Сравнение Set A (Retracement 1.618/2.618/3.618) vs Set B (Extension 1.0/1.618/2.618)."""
    n = len(trades)
    if n == 0:
        return

    long_trades  = [t for t in trades if t.get("direction") == "LONG"]
    short_trades = [t for t in trades if t.get("direction") == "SHORT"]

    def pct(k): return sum(1 for t in trades if t[k])
    def avg_r(k): return sum(t[k] for t in trades) / n

    hit_a1, hit_a2, hit_a3 = pct("hit_a_tp1"), pct("hit_a_tp2"), pct("hit_a_tp3")
    hit_b1, hit_b2, hit_b3 = pct("hit_b_tp1"), pct("hit_b_tp2"), pct("hit_b_tp3")
    hit_atr = pct("hit_atr_tp")

    ar_a1, ar_a2, ar_a3 = avg_r("r_at_a_tp1"), avg_r("r_at_a_tp2"), avg_r("r_at_a_tp3")
    ar_b1, ar_b2, ar_b3 = avg_r("r_at_b_tp1"), avg_r("r_at_b_tp2"), avg_r("r_at_b_tp3")
    ar_atr = avg_r("r_at_atr")

    exp_a = expected_partial_r(trades, n, "hit_a_tp1", "hit_a_tp2", "r_at_a_tp1", "r_at_a_tp2")
    exp_b = expected_partial_r(trades, n, "hit_b_tp1", "hit_b_tp2", "r_at_b_tp1", "r_at_b_tp2")

    print(f"\n  ╔═══════════════════════════════════════════════════════════════════╗")
    print(f"  ║  FIB TP СРАВНЕНИЕ ({timeframe}) — Set A vs Set B vs ATR              ║")
    print(f"  ╚═══════════════════════════════════════════════════════════════════╝")
    print(f"\n  Сделок: {n}  (LONG: {len(long_trades)}, SHORT: {len(short_trades)})\n")

    W = 8
    print(f"  {'Уровень':<22}{'Hit Rate':>{W}}    {'R цели':>{W}}   Примечание")
    print(f"  {'─'*72}")

    # Set A
    print(f"\n  ── Set A: Retracement (от impulse_low) ─────────────────────────────")
    print(f"  {'TP1 = 1.618 (low+1.618r)':<22}{hit_a1:3d}/{n} = {100*hit_a1/n:5.1f}%   +{ar_a1:.2f}R")
    print(f"  {'TP2 = 2.618 (low+2.618r)':<22}{hit_a2:3d}/{n} = {100*hit_a2/n:5.1f}%   +{ar_a2:.2f}R")
    print(f"  {'TP3 = 3.618 (low+3.618r)':<22}{hit_a3:3d}/{n} = {100*hit_a3/n:5.1f}%   +{ar_a3:.2f}R")
    print(f"  {'Expected R (20/50/30):':<22}{'':>14}   {exp_a:+.3f}R")
    chain_a12 = sum(1 for t in trades if t["hit_a_tp1"] and t["hit_a_tp2"])
    print(f"  {'Цепочка TP1→TP2:':<22}{chain_a12:3d}/{n} = {100*chain_a12/n:5.1f}%")

    # Set B
    print(f"\n  ── Set B: Extension (от impulse_high) ──────────────────────────────")
    print(f"  {'TP1 = 1.0  (= impulse_hi)':<22}{hit_b1:3d}/{n} = {100*hit_b1/n:5.1f}%   +{ar_b1:.2f}R  ← возврат к HIGH")
    print(f"  {'TP2 = 1.618 (hi+0.618r)':<22}{hit_b2:3d}/{n} = {100*hit_b2/n:5.1f}%   +{ar_b2:.2f}R  (= Set A TP1)")
    print(f"  {'TP3 = 2.618 (hi+1.618r)':<22}{hit_b3:3d}/{n} = {100*hit_b3/n:5.1f}%   +{ar_b3:.2f}R  (= Set A TP2)")
    print(f"  {'Expected R (20/50/30):':<22}{'':>14}   {exp_b:+.3f}R")
    chain_b12 = sum(1 for t in trades if t["hit_b_tp1"] and t["hit_b_tp2"])
    print(f"  {'Цепочка TP1→TP2:':<22}{chain_b12:3d}/{n} = {100*chain_b12/n:5.1f}%")

    # ATR
    print(f"\n  ── ATR×{ATR_TP_MULT} (текущий бот) ───────────────────────────────────────")
    print(f"  {'ATR×'+str(ATR_TP_MULT):<22}{hit_atr:3d}/{n} = {100*hit_atr/n:5.1f}%   +{ar_atr:.2f}R")

    # Итог
    print(f"\n  ── ИТОГ: Expected R (схема 20/50/30) ───────────────────────────────")
    best = max([("Set A", exp_a), ("Set B", exp_b)], key=lambda x: x[1])
    print(f"  Set A (Retracement):   {exp_a:+.3f}R   {'← ЛУЧШЕ' if best[0]=='Set A' else ''}")
    print(f"  Set B (Extension):     {exp_b:+.3f}R   {'← ЛУЧШЕ' if best[0]=='Set B' else ''}")
    print()


async def run_backtest(timeframe: str):
    print("=" * 70)
    print(f"  БЭКТЕСТ: OTE Fib TP — Set A (Retr 1.618/2.618/3.618) vs Set B (Ext 1.0/1.618/2.618)")
    print(f"  TF={timeframe}  WT_OS={WT_OVERSOLD}  ATR_FACTOR={ATR_FACTOR}  ATR_TP_MULT={ATR_TP_MULT}×")
    print("=" * 70)

    conn = sqlite3.connect("subscriptions.db")
    cur  = conn.cursor()
    cur.execute("""
        SELECT DISTINCT symbol FROM simulated_trades
        WHERE timeframe = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (timeframe, SYMBOLS_LIMIT))
    symbols = [r[0] for r in cur.fetchall()]
    conn.close()

    if not symbols:
        # Fallback: популярные пары
        symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
                   "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]

    print(f"\n  Загружаем данные для {len(symbols)} символов ({timeframe}, {CANDLES} баров)...")

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    all_trades = []
    processed = 0
    skipped   = 0

    for sym in symbols:
        try:
            df = await dc.get_ohlcv(sym, timeframe=timeframe, limit=CANDLES)
            if df is None or len(df) < 100:
                skipped += 1
                continue

            df = calculate_wt(df)
            df = calculate_trend(df, factor=ATR_FACTOR)

            fib_zones = build_fib_zones(df)
            if not fib_zones:
                skipped += 1
                continue

            signals = find_ote_signals(df, fib_zones)
            if not signals:
                skipped += 1
                continue

            for sig in signals:
                result = simulate_trade(df, sig)
                if result["status"] == "INVALID":
                    continue
                all_trades.append({**sig, **result})

            processed += 1
            if processed % 10 == 0:
                print(f"  ... {processed}/{len(symbols)} символов, {len(all_trades)} сделок")

        except Exception as e:
            logging.debug("Error on %s: %s", sym, e)
            skipped += 1
            continue

    await dc.stop()

    print(f"\n  Обработано: {processed} символов, пропущено: {skipped}")
    print(f"  Найдено OTE-сигналов: {len(all_trades)}\n")

    if not all_trades:
        print("  Нет сделок для анализа. Попробуй другой TF или увеличь CANDLES.")
        return

    # ── Разделение по направлению ─────────────────────────────────────────
    long_trades  = [t for t in all_trades if t["direction"] == "LONG"]
    short_trades = [t for t in all_trades if t["direction"] == "SHORT"]

    # ── Метрики TSL (текущая логика бота) ────────────────────────────────
    print_metrics(f"ALL ({timeframe}) — TSL стратегия (текущая логика)", all_trades)
    print_metrics(f"LONG только", long_trades)
    print_metrics(f"SHORT только", short_trades)

    # ── Анализ hit rate обоих наборов ─────────────────────────────────────
    print_fib_analysis(all_trades, timeframe)

    # ── Симуляция TP1 как единственного выхода (без TSL) ──────────────────
    def make_tp_trades(trades, hit_key, r_key):
        return [
            {**t, "exit_r": t[r_key] if t[hit_key] else -1.0,
             "status": "TP" if t[hit_key] else "SL"}
            for t in trades
        ]

    t_a_tp1 = make_tp_trades(all_trades, "hit_a_tp1", "r_at_a_tp1")
    t_b_tp1 = make_tp_trades(all_trades, "hit_b_tp1", "r_at_b_tp1")
    t_atr   = make_tp_trades(all_trades, "hit_atr_tp", "r_at_atr")

    print_metrics(f"Если TP = Set A TP1 (Retracement 1.618)", t_a_tp1)
    print_metrics(f"Если TP = Set B TP1 (Extension 1.0 = impulse_high)", t_b_tp1)
    print_metrics(f"Если TP = ATR×{ATR_TP_MULT}", t_atr)

    # ── Итоговая таблица ──────────────────────────────────────────────────
    def avg_r_ts(ts): return sum(t["exit_r"] for t in ts) / len(ts) if ts else 0
    def wr_ts(ts): return 100 * sum(1 for t in ts if t["exit_r"] > 0) / len(ts) if ts else 0

    n = len(all_trades)
    print(f"\n{'═'*70}")
    print(f"  ИТОГ: {timeframe}   (всего сделок: {n})")
    print(f"{'─'*70}")
    print(f"  {'Стратегия':<35} {'WinRate':>8}  {'Avg R':>8}")
    print(f"  {'─'*55}")
    print(f"  {'TSL (текущий бот)':<35} {wr_ts(all_trades):>7.1f}%  {avg_r_ts(all_trades):>+8.3f}R")
    print(f"  {'Set A TP1 (Retracement 1.618)':<35} {wr_ts(t_a_tp1):>7.1f}%  {avg_r_ts(t_a_tp1):>+8.3f}R")
    print(f"  {'Set B TP1 (Extension 1.0=HIGH)':<35} {wr_ts(t_b_tp1):>7.1f}%  {avg_r_ts(t_b_tp1):>+8.3f}R")
    print(f"  {'ATR×'+str(ATR_TP_MULT):<35} {wr_ts(t_atr):>7.1f}%  {avg_r_ts(t_atr):>+8.3f}R")
    print(f"{'═'*70}\n")

    # TTS
    os.system(
        'powershell.exe -ExecutionPolicy Bypass -Command "'
        'Add-Type -AssemblyName System.Speech; '
        '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
        '$s.SelectVoice(\'Microsoft Irina Desktop\'); '
        f'$s.Speak(\'Backtest zavershen. {n} sdelok. Smotri rezultaty.\')\"'
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf", default="15m", help="Таймфрейм (15m, 1h, 4h)")
    args = parser.parse_args()
    asyncio.run(run_backtest(args.tf))
