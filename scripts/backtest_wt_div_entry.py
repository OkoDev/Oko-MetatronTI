#!/usr/bin/env python3
"""
Бэктест стратегии: WT crossup в OS + ATR crossup + бонус WT дивергенция
========================================================================
Условие входа (LONG 15m):
  1. wt1 пересекает wt2 снизу вверх (wt1_prev < wt2_prev AND wt1 >= wt2)
  2. wt1 < WT_OVERSOLD (зона перепроданности)
  3. ATR trend crossup: trend -1 → +1 в пределах ATR_WINDOW баров

Бонус-фильтр (вариант B):
  + Бычья WT дивергенция: price делает нижний лой, WT делает более высокий лой
    (ищем предыдущий локальный минимум WT за последние DIV_LOOKBACK баров)

SL = trendup (ATR-based support line)
TSL следует за trendup после +1R

Запуск: python scripts/backtest_wt_div_entry.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)

# ── Параметры ────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT   = 50       # Максимум символов
CANDLES         = 500      # Глубина истории (500 × 15m ≈ 5 дней)
WT_OVERSOLD     = -30      # Порог перепроданности
ATR_WINDOW      = 1        # Сколько баров назад разрешён ATR crossup
ATR_FACTOR      = 1.25     # ATR множитель для trendup
MIN_SL_PCT      = 0.003    # Минимальный SL 0.3%
MAX_SL_PCT      = 0.08     # Максимальный SL 8%
TIMEFRAME       = "15m"
DIV_LOOKBACK    = 50       # Окно поиска предыдущего WT минимума (баров)
DIV_MIN_BARS    = 5        # Минимальная дистанция до предыдущего минимума


# ── Детектор дивергенции ─────────────────────────────────────────────────────

def detect_wt_divergence(df: pd.DataFrame, i: int) -> bool:
    """
    Бычья регулярная дивергенция:
      - Цена (low) делает более низкий лой: cur_low <= prev_low
      - WT1 делает более высокий лой: cur_wt1 > prev_wt1_min
    Ищем последний локальный минимум WT1 за [i-DIV_LOOKBACK, i-DIV_MIN_BARS].
    """
    cur_wt  = df["wt1"].iloc[i]
    cur_low = df["low"].iloc[i]

    start = max(1, i - DIV_LOOKBACK)
    end   = i - DIV_MIN_BARS

    if end <= start:
        return False

    for j in range(end, start, -1):
        wt_j = df["wt1"].iloc[j]
        if pd.isna(wt_j):
            continue
        wt_prev = df["wt1"].iloc[j - 1]
        wt_next = df["wt1"].iloc[j + 1] if j + 1 < len(df) else np.nan
        if pd.isna(wt_prev) or pd.isna(wt_next):
            continue

        # Локальный минимум WT
        if wt_j < wt_prev and wt_j < wt_next:
            low_j = df["low"].iloc[j]
            # Бычья дивергенция: цена ниже, WT выше
            if cur_low <= low_j and cur_wt > wt_j:
                return True

    return False


# ── Поиск сигналов ───────────────────────────────────────────────────────────

def find_signals(df: pd.DataFrame) -> list:
    """Возвращает сигналы с флагом has_div."""
    signals = []
    for i in range(2, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue

        # 1. WT crossup
        if not ((wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)):
            continue

        # 2. WT в зоне перепроданности
        if wt1_cur >= WT_OVERSOLD:
            continue

        # 3. ATR trend crossup
        atr_crossup = False
        for w in range(ATR_WINDOW + 1):
            if i - w >= 1:
                t_now  = df["trend"].iloc[i - w]
                t_prev = df["trend"].iloc[i - w - 1] if (i - w - 1) >= 0 else np.nan
                if not pd.isna(t_now) and not pd.isna(t_prev):
                    if t_now == 1.0 and t_prev == -1.0:
                        atr_crossup = True
                        break
        if not atr_crossup:
            continue

        # 4. SL = trendup
        sl_price = df["trendup"].iloc[i]
        if pd.isna(sl_price) or sl_price <= 0:
            continue

        entry_price = float(df["open"].iloc[i + 1])
        if entry_price <= 0:
            continue

        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct < MIN_SL_PCT or sl_dist_pct > MAX_SL_PCT:
            continue

        # Проверяем дивергенцию
        has_div = detect_wt_divergence(df, i)

        signals.append({
            "signal_idx":  i,
            "entry_idx":   i + 1,
            "entry_price": entry_price,
            "sl_price":    float(sl_price),
            "sl_pct":      sl_dist_pct * 100,
            "wt1":         wt1_cur,
            "has_div":     has_div,
        })

    return signals


# ── Симуляция сделки ─────────────────────────────────────────────────────────

def simulate_trade(df: pd.DataFrame, entry_idx: int, entry_price: float, sl_price: float) -> dict:
    """LONG с TSL по trendup."""
    one_r = entry_price - sl_price
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl = sl_price
    tsl_activated = False
    TSL_ACTIVATION_R = 1.0

    for i in range(entry_idx + 1, len(df)):
        low   = float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])

        if low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            return {"status": "TSL" if tsl_activated else "SL",
                    "exit_r": exit_r, "bars": i - entry_idx}

        if not tsl_activated and (close - entry_price) / one_r >= TSL_ACTIVATION_R:
            tsl_activated = True

        new_sl = df["trendup"].iloc[i]
        if not pd.isna(new_sl) and new_sl > current_sl:
            current_sl = float(new_sl)

    final_r = (float(df["close"].iloc[-1]) - entry_price) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df) - entry_idx}


# ── Метрики одного набора сделок ─────────────────────────────────────────────

def print_metrics(label: str, trades: list):
    n = len(trades)
    if n == 0:
        print(f"\n  {label}: нет сделок")
        return

    rs      = [t["exit_r"] for t in trades]
    wins    = [t for t in trades if t["exit_r"] > 0]
    losses  = [t for t in trades if t["exit_r"] <= 0]
    sl_exits  = [t for t in trades if t["status"] == "SL"]
    tsl_exits = [t for t in trades if t["status"] == "TSL"]
    open_pos  = [t for t in trades if t["status"] == "OPEN"]
    moonshots = [t for t in trades if t["exit_r"] >= 5]

    avg_r  = sum(rs) / n
    win_r  = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
    loss_r = sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
    wrate  = 100 * len(wins) / n
    pf     = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")

    rs_arr = np.array(rs)
    sharpe = rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0

    cum  = np.cumsum(rs_arr)
    peak = np.maximum.accumulate(cum)
    max_dd_r = (cum - peak).min()

    print(f"\n  {label}")
    print(f"  {'─'*50}")
    print(f"  Сделок:        {n}")
    print(f"  Win Rate:      {wrate:.1f}%   {'[НОРМ]' if wrate >= 45 else '[СЛАБО]'}")
    print(f"  Avg R:         {avg_r:+.2f}   {'[НОРМ]' if avg_r >= 0.5 else '[СЛАБО]'}")
    print(f"  Avg R (win):   {win_r:+.2f}")
    print(f"  Avg R (loss):  {loss_r:+.2f}")
    print(f"  Profit Factor: {pf:.2f}   {'[НОРМ]' if pf >= 1.5 else '[СЛАБО]'}")
    print(f"  Sharpe:        {sharpe:.2f}")
    print(f"  Max DD (R):    {max_dd_r:+.2f}")
    print(f"  Moonshots ≥5R: {len(moonshots)}")
    print(f"  Выходы:        SL={len(sl_exits)}  TSL={len(tsl_exits)}  OPEN={len(open_pos)}")
    print(f"  Avg SL dist:   {sum(t['sl_pct'] for t in trades)/n:.2f}%")
    print(f"  Avg bars:      {sum(t['bars'] for t in trades)/n:.0f} × 15m")

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
        bar = "█" * (cnt // max(1, n // 40))
        print(f"  {lbl:7s}: {cnt:3d}  {bar}")

    if n < 30:
        print(f"  ⚠️  Малая выборка ({n} сделок)")


# ── Основная функция ─────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 70)
    print(f"  БЭКТЕСТ: WT crossup OS + ATR crossup + WT Divergence бонус")
    print(f"  WT_OVERSOLD={WT_OVERSOLD}  ATR_FACTOR={ATR_FACTOR}  DIV_LOOKBACK={DIV_LOOKBACK}")
    print("=" * 70)

    conn = sqlite3.connect("subscriptions.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT symbol FROM simulated_trades
        WHERE timeframe = '15m'
        ORDER BY created_at DESC
        LIMIT ?
    """, (SYMBOLS_LIMIT,))
    symbols = [r[0] for r in cur.fetchall()]
    conn.close()

    print(f"\nСимволов: {len(symbols)}")
    print(f"Свечей:   {CANDLES} × {TIMEFRAME} ≈ {CANDLES * 15 // 60 // 24} дней\n")

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    all_trades  = []   # все сигналы (baseline)
    div_trades  = []   # только с дивергенцией
    total_signals = 0
    total_div     = 0
    skipped = 0

    for sym in symbols:
        try:
            df = await dc.get_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLES)
            if df is None or len(df) < 100:
                skipped += 1
                continue

            df = calculate_wt(df)
            df = calculate_trend(df, factor=ATR_FACTOR)

            signals = find_signals(df)
            total_signals += len(signals)
            total_div     += sum(1 for s in signals if s["has_div"])

            for sig in signals:
                result = simulate_trade(df, sig["entry_idx"], sig["entry_price"], sig["sl_price"])
                if result["exit_r"] is None:
                    continue
                trade = {
                    "symbol":      sym,
                    "entry_price": sig["entry_price"],
                    "sl_price":    sig["sl_price"],
                    "sl_pct":      sig["sl_pct"],
                    "wt1":         sig["wt1"],
                    "has_div":     sig["has_div"],
                    "status":      result["status"],
                    "exit_r":      result["exit_r"],
                    "bars":        result.get("bars", 0),
                }
                all_trades.append(trade)
                if sig["has_div"]:
                    div_trades.append(trade)

        except Exception:
            skipped += 1
            continue

    await dc.stop()

    print(f"Обработано: {len(symbols) - skipped}/{len(symbols)}")
    print(f"Сигналов всего:       {total_signals}")
    print(f"Сигналов с дивергенцией: {total_div} ({100*total_div/max(1,total_signals):.0f}%)")

    print("\n" + "=" * 70)
    print("  ВАРИАНТ A — WT crossup OS + ATR (baseline, без фильтра дивергенции)")
    print("=" * 70)
    print_metrics("Все сигналы", all_trades)

    print("\n" + "=" * 70)
    print("  ВАРИАНТ B — WT crossup OS + ATR + WT Дивергенция")
    print("=" * 70)
    print_metrics("Только с дивергенцией", div_trades)

    # Сравнительная таблица
    print("\n" + "=" * 70)
    print("  СРАВНЕНИЕ")
    print("=" * 70)

    def metrics(trades):
        if not trades:
            return (0, 0, 0, 0)
        rs    = [t["exit_r"] for t in trades]
        wins  = [t for t in trades if t["exit_r"] > 0]
        wrate = 100 * len(wins) / len(trades)
        avg_r = sum(rs) / len(trades)
        moon  = sum(1 for t in trades if t["exit_r"] >= 5)
        return (len(trades), wrate, avg_r, moon)

    for lbl, trades in [("Baseline (без div)",   all_trades),
                         ("С WT дивергенцией",    div_trades)]:
        n, wr, ar, ms = metrics(trades)
        print(f"  {lbl:25s}  n={n:3d}  WR={wr:.1f}%  Avg R={ar:+.2f}  Moon≥5R={ms}")

    # Вердикт
    print("\n" + "=" * 70)
    print("  ВЕРДИКТ")
    print("=" * 70)
    _, wr_a, ar_a, _ = metrics(all_trades)
    _, wr_b, ar_b, _ = metrics(div_trades)

    if ar_b > ar_a and len(div_trades) >= 10:
        print(f"  ✅ Дивергенция улучшает стратегию: Avg R {ar_a:+.2f} → {ar_b:+.2f}")
        print(f"     Фильтрует {len(all_trades)-len(div_trades)} сигналов ({100*(len(all_trades)-len(div_trades))/max(1,len(all_trades)):.0f}% отсева)")
    elif len(div_trades) < 10:
        print(f"  ⚠️  Слишком мало сделок с дивергенцией ({len(div_trades)}) — нет статистики")
    else:
        print(f"  ❌ Дивергенция не улучшает: {ar_a:+.2f} → {ar_b:+.2f}")


if __name__ == "__main__":
    asyncio.run(run_backtest())
