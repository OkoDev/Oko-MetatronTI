#!/usr/bin/env python3
"""
Каскадный TSL для 3m и 5m входов
==================================
Заход: WT < -45 + ATR crossup (лучший результат из sweep)
SL при входе: trendup на TF входа (3m или 5m)

Варианты TSL:
  same_tf   — TSL всегда на TF входа (3m или 5m)
  15m_only  — TSL сразу 15m (широкий)
  esc_1.0R  — TF входа → 15m при достижении +1R
  esc_1.5R  — TF входа → 15m при +1.5R
  esc_2.5R  — TF входа → 15m при +2.5R
  esc_3.0R  — TF входа → 15m при +3.0R

Запуск: python scripts/backtest_3m5m_cascade_tsl.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)

# ── Параметры ─────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT = 50
ATR_FACTOR    = 1.25
ATR_WINDOW    = 1
WT_OS         = -45        # лучший порог по sweep
MIN_SL_PCT    = 0.003
MAX_SL_PCT    = 0.08

# Эскалация (TF входа → 15m) при достижении этих R-уровней
ESCALATION_LEVELS = [1.0, 1.5, 2.5, 3.0]

ENTRY_TFS = ["3m", "5m"]
CANDLES = {
    "3m":  1440,   # max BingX
    "5m":  1000,
    "15m": 500,
}


# ── Поиск сигналов на entry TF ────────────────────────────────────────────────

def find_signals(df: pd.DataFrame) -> list:
    signals = []
    for i in range(2, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]; wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i];   wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue
        if not ((wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)):
            continue
        if wt1_cur >= WT_OS:
            continue

        atr_ok = False
        for w in range(ATR_WINDOW + 1):
            if i - w >= 1:
                t_n = df["trend"].iloc[i - w]
                t_p = df["trend"].iloc[i - w - 1] if (i - w - 1) >= 0 else np.nan
                if not pd.isna(t_n) and not pd.isna(t_p) and t_n == 1.0 and t_p == -1.0:
                    atr_ok = True; break
        if not atr_ok:
            continue

        sl = df["trendup"].iloc[i]
        if pd.isna(sl) or sl <= 0:
            continue

        entry_price = float(df["open"].iloc[i + 1])
        if entry_price <= 0:
            continue

        sl_pct = abs(entry_price - sl) / entry_price
        if sl_pct < MIN_SL_PCT or sl_pct > MAX_SL_PCT:
            continue

        # Записываем timestamp бара входа для синхронизации с 15m
        entry_ts = df.index[i + 1] if isinstance(df.index, pd.DatetimeIndex) else None
        signal_ts = df["time"].iloc[i + 1] if "time" in df.columns else None

        signals.append({
            "signal_idx":  i,
            "entry_idx":   i + 1,
            "entry_price": entry_price,
            "sl_price":    float(sl),
            "sl_pct":      sl_pct * 100,
            "wt1":         wt1_cur,
            "entry_ts":    signal_ts,
        })
    return signals


# ── Синхронизация entry TF с 15m ─────────────────────────────────────────────

def align_15m_bars(df_entry: pd.DataFrame, df_15m: pd.DataFrame, entry_idx: int) -> int:
    """
    Возвращает индекс в df_15m, соответствующий бару entry_idx в df_entry.
    Используем колонку 'time' (unix ms).
    Если синхронизация не удалась — возвращает 0 (начало).
    """
    if "time" not in df_entry.columns or "time" not in df_15m.columns:
        return 0
    entry_time = df_entry["time"].iloc[entry_idx]
    # Ближайший бар 15m по времени
    diffs = (df_15m["time"] - entry_time).abs()
    idx_15m = int(diffs.idxmin()) if len(diffs) > 0 else 0
    return idx_15m


# ── Симуляция одной сделки ────────────────────────────────────────────────────

def simulate_trade(
    df_entry: pd.DataFrame,
    df_15m: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    sl_price: float,
    tsl_mode: str,          # "same_tf" | "15m_only" | "esc_X.XR"
    esc_r: float = None,    # порог эскалации (для mode="esc_X.XR")
) -> dict:
    """
    Симулирует LONG сделку.
    same_tf:  TSL только по df_entry trendup
    15m_only: TSL только по df_15m trendup
    esc_X.XR: TSL по df_entry до достижения esc_r, потом переключается на df_15m
    """
    one_r = entry_price - sl_price
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl    = sl_price
    tsl_activated = False
    escalated     = (tsl_mode == "15m_only")  # 15m_only → сразу на 15m

    # Начальный индекс в 15m
    idx_15m_start = align_15m_bars(df_entry, df_15m, entry_idx) if df_15m is not None else 0

    entry_bar_time = df_entry["time"].iloc[entry_idx] if "time" in df_entry.columns else None

    # Итерируем по барам entry TF
    for i in range(entry_idx + 1, len(df_entry)):
        low   = float(df_entry["low"].iloc[i])
        close = float(df_entry["close"].iloc[i])
        bar_time = df_entry["time"].iloc[i] if "time" in df_entry.columns else None

        # Обновляем TSL
        if tsl_mode == "same_tf":
            new_sl = df_entry["trendup"].iloc[i]
            if not pd.isna(new_sl) and new_sl > current_sl:
                current_sl = float(new_sl)

        elif tsl_mode == "15m_only" and df_15m is not None:
            # Берём последний 15m trendup ≤ текущему времени
            if bar_time is not None:
                mask = df_15m["time"] <= bar_time
                idx15 = df_15m.index[mask].max() if mask.any() else None
                if idx15 is not None:
                    new_sl = df_15m["trendup"].iloc[idx15]
                    if not pd.isna(new_sl) and new_sl > current_sl:
                        current_sl = float(new_sl)

        else:  # esc_X.XR
            current_r = (close - entry_price) / one_r
            if not escalated and current_r >= esc_r:
                escalated = True

            if not escalated:
                new_sl = df_entry["trendup"].iloc[i]
                if not pd.isna(new_sl) and new_sl > current_sl:
                    current_sl = float(new_sl)
            elif df_15m is not None and bar_time is not None:
                mask = df_15m["time"] <= bar_time
                idx15 = df_15m.index[mask].max() if mask.any() else None
                if idx15 is not None:
                    new_sl = df_15m["trendup"].iloc[idx15]
                    if not pd.isna(new_sl) and new_sl > current_sl:
                        current_sl = float(new_sl)

        # Проверка выбивания
        if low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            status = "TSL" if tsl_activated else "SL"
            return {"status": status, "exit_r": exit_r, "bars": i - entry_idx,
                    "escalated": escalated}

        # Активация TSL
        if not tsl_activated and (close - entry_price) / one_r >= 1.0:
            tsl_activated = True

    final_r = (float(df_entry["close"].iloc[-1]) - entry_price) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df_entry) - entry_idx,
            "escalated": escalated}


# ── Метрики ───────────────────────────────────────────────────────────────────

def calc_metrics(trades: list) -> dict | None:
    if not trades:
        return None
    rs    = [t["exit_r"] for t in trades]
    wins  = [t for t in trades if t["exit_r"] > 0]
    losses= [t for t in trades if t["exit_r"] <= 0]
    n     = len(trades)
    win_r = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
    loss_r= sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
    wrate = 100 * len(wins) / n
    pf    = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")
    rs_arr= np.array(rs)
    sharpe= rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0
    cum   = np.cumsum(rs_arr)
    max_dd= (cum - np.maximum.accumulate(cum)).min()
    moon  = sum(1 for t in trades if t["exit_r"] >= 5)
    return {"n": n, "wr": wrate, "avg_r": sum(rs)/n, "win_r": win_r,
            "pf": pf, "sharpe": sharpe, "max_dd": max_dd, "moon": moon}


def print_table(title: str, rows: list):
    print(f"\n  {title}")
    print(f"  {'─'*70}")
    print(f"  {'Вариант TSL':<18}  {'n':>4}  {'WR%':>6}  {'Avg R':>7}  {'PF':>5}  {'Sharpe':>6}  {'MaxDD':>7}  {'Moon':>4}")
    print(f"  {'─'*18}  {'─'*4}  {'─'*6}  {'─'*7}  {'─'*5}  {'─'*6}  {'─'*7}  {'─'*4}")
    best_r = max((m["avg_r"] for _, m in rows if m), default=0)
    for lbl, m in rows:
        if not m:
            print(f"  {lbl:<18}  —")
            continue
        mark = " ←" if abs(m["avg_r"] - best_r) < 0.001 else "  "
        warn = "⚠️" if m["n"] < 20 else "  "
        print(f"  {lbl:<18}  {m['n']:>4}  {m['wr']:>5.1f}%  {m['avg_r']:>+7.2f}"
              f"  {m['pf']:>5.2f}  {m['sharpe']:>6.2f}  {m['max_dd']:>+7.2f}  {m['moon']:>4}"
              f"  {warn}{mark}")


# ── Основная функция ──────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 72)
    print(f"  КАСКАДНЫЙ TSL: 3m/5m → 15m | WT < {WT_OS} + ATR | factor={ATR_FACTOR}")
    print("=" * 72)

    conn = sqlite3.connect("subscriptions.db")
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE timeframe='15m' "
        "ORDER BY created_at DESC LIMIT ?", (SYMBOLS_LIMIT,)
    ).fetchall()]
    conn.close()

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    # Загружаем данные для всех нужных TF
    print(f"\nЗагрузка данных ({len(symbols)} пар)...")
    data = {tf: {} for tf in ["3m", "5m", "15m"]}
    skipped = 0

    for sym in symbols:
        ok = True
        for tf, candles in CANDLES.items():
            try:
                df = await dc.get_ohlcv(sym, timeframe=tf, limit=candles)
                if df is None or len(df) < 50:
                    ok = False; break
                df = calculate_wt(df)
                df = calculate_trend(df, factor=ATR_FACTOR)
                data[tf][sym] = df
            except Exception:
                ok = False; break
        if not ok:
            skipped += 1

    await dc.stop()

    loaded = len(data["15m"])
    print(f"Загружено: {loaded}/{len(symbols)} символов (пропущено: {skipped})\n")

    # Варианты TSL
    tsl_variants = [
        ("same_tf",  "same_tf",  None),
        ("15m_only", "15m_only", None),
    ] + [(f"esc_{r}R", "esc", r) for r in ESCALATION_LEVELS]

    # Прогон по entry TF
    for entry_tf in ENTRY_TFS:
        print("=" * 72)
        print(f"  ENTRY TF: {entry_tf}  (WT < {WT_OS}, ATR factor={ATR_FACTOR})")
        print("=" * 72)

        results = {lbl: [] for lbl, _, _ in tsl_variants}
        total_signals = 0

        for sym in data[entry_tf]:
            if sym not in data["15m"]:
                continue
            df_e   = data[entry_tf][sym]
            df_15m = data["15m"][sym]

            signals = find_signals(df_e)
            total_signals += len(signals)

            for sig in signals:
                for lbl, mode, esc_r in tsl_variants:
                    result = simulate_trade(
                        df_e, df_15m,
                        sig["entry_idx"], sig["entry_price"], sig["sl_price"],
                        tsl_mode=mode, esc_r=esc_r,
                    )
                    if result["exit_r"] is None:
                        continue
                    results[lbl].append({**sig, **result})

        print(f"\n  Сигналов: {total_signals}  Символов: {len(data[entry_tf])}")
        rows = [(lbl, calc_metrics(results[lbl])) for lbl, _, _ in tsl_variants]
        print_table(f"Сравнение TSL ({entry_tf} входы)", rows)

        # Детали лучшего варианта
        best_lbl = max(
            [(lbl, m) for lbl, m in rows if m and m["n"] >= 10],
            key=lambda x: x[1]["avg_r"],
            default=(None, None)
        )[0]
        if best_lbl:
            trades = results[best_lbl]
            sl_ex  = sum(1 for t in trades if t["status"] == "SL")
            tsl_ex = sum(1 for t in trades if t["status"] == "TSL")
            open_p = sum(1 for t in trades if t["status"] == "OPEN")
            m = calc_metrics(trades)
            print(f"\n  ► Лучший: {best_lbl}")
            print(f"    Avg R: {m['avg_r']:+.2f}  Win R: {m['win_r']:+.2f}  Loss R: {-abs(m.get('loss_r', m['avg_r'])):+.2f}")
            print(f"    Выходы: SL={sl_ex}  TSL={tsl_ex}  OPEN={open_p}")
            buckets = [("<−1R", lambda r: r < -1), ("−1–0R", lambda r: -1 <= r < 0),
                       ("0–1R",  lambda r: 0 <= r < 1), ("1–2R", lambda r: 1 <= r < 2),
                       ("2–3R",  lambda r: 2 <= r < 3), ("3–5R", lambda r: 3 <= r < 5),
                       ("5R+",   lambda r: r >= 5)]
            print()
            for lbl2, fn in buckets:
                cnt = sum(1 for t in trades if fn(t["exit_r"]))
                bar = "█" * (cnt // max(1, m["n"] // 30))
                print(f"    {lbl2:7s}: {cnt:3d}  {bar}")

    # Сводная таблица
    print("\n" + "=" * 72)
    print("  СВОДНАЯ ТАБЛИЦА Avg R")
    print("=" * 72)
    print(f"  {'Вариант TSL':<18}  {'3m входы':>12}  {'5m входы':>12}")
    print(f"  {'─'*18}  {'─'*12}  {'─'*12}")

    # Пересобираем для сводной (нужно повторить прогон — но данные уже в памяти)
    # Используем last results из цикла — только 5m; добавим 3m отдельно
    summary = {}
    for entry_tf in ENTRY_TFS:
        results_tf = {lbl: [] for lbl, _, _ in tsl_variants}
        for sym in data[entry_tf]:
            if sym not in data["15m"]:
                continue
            df_e   = data[entry_tf][sym]
            df_15m = data["15m"][sym]
            for sig in find_signals(df_e):
                for lbl, mode, esc_r in tsl_variants:
                    result = simulate_trade(df_e, df_15m, sig["entry_idx"],
                                            sig["entry_price"], sig["sl_price"],
                                            tsl_mode=mode, esc_r=esc_r)
                    if result["exit_r"] is None:
                        continue
                    results_tf[lbl].append({**sig, **result})
        summary[entry_tf] = results_tf

    for lbl, _, _ in tsl_variants:
        vals = {}
        for tf in ENTRY_TFS:
            m = calc_metrics(summary[tf][lbl])
            vals[tf] = m
        r3 = f"{vals['3m']['avg_r']:>+12.2f}" if vals.get("3m") and vals["3m"]["n"] >= 10 else f"{'—':>12}"
        r5 = f"{vals['5m']['avg_r']:>+12.2f}" if vals.get("5m") and vals["5m"]["n"] >= 10 else f"{'—':>12}"
        print(f"  {lbl:<18}  {r3}  {r5}")

    print()


if __name__ == "__main__":
    asyncio.run(run_backtest())
