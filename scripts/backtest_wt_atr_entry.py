#!/usr/bin/env python3
"""
Бэктест стратегии: WT crossup ниже -10 + ATR trend crossup
===========================================================
Условие входа (LONG 15m):
  1. wt1 пересекает wt2 снизу вверх (wt1_prev < wt2_prev AND wt1 >= wt2)
  2. wt1 в момент пересечения < -10 (зона перепроданности)
  3. ATR trend crossup: trend изменился с -1 → +1 на текущей или предыдущей свече

SL = trendup (ATR-based support line, динамический)
Трейлинг: TSL следует за trendup (двигается только вверх)
TP = нет фиксированного. Выход по TSL.

Запуск: python scripts/backtest_wt_atr_entry.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.infra.data_collector import RealTimeData
from core.indicators.indicators import calculate_wt, calculate_trend

logging.basicConfig(level=logging.WARNING)

# ── Параметры ────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT   = 50       # Максимум символов
CANDLES         = 500      # Глубина истории (500 × 15m ≈ 5 дней)
WT_OVERSOLD     = -30      # Порог перепроданности
ATR_WINDOW      = 1        # Сколько баров назад разрешён ATR crossup (0=тот же бар, 1=предыдущий)
MIN_SL_PCT      = 0.003    # Минимальный SL 0.3% (фильтр шума)
MAX_SL_PCT      = 0.08     # Максимальный SL 8% (фильтр нереалистичных уровней)
TIMEFRAME       = "15m"

# ── Вспомогательные функции ──────────────────────────────────────────────────

def find_signals(df: pd.DataFrame) -> list:
    """
    Возвращает список индексов баров где выполнены оба условия входа.
    Возвращает (idx, entry_price, sl_price).
    """
    signals = []
    for i in range(1, len(df) - 1):
        # 1. WT crossup
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue

        wt_crossup = (wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)
        if not wt_crossup:
            continue

        # 2. WT в зоне перепроданности
        if wt1_cur >= WT_OVERSOLD:
            continue

        # 3. ATR trend crossup: trend стал +1 на текущем или предыдущем баре
        trend_cur  = df["trend"].iloc[i]
        trend_prev = df["trend"].iloc[i-1] if i >= 1 else np.nan

        if pd.isna(trend_cur) or pd.isna(trend_prev):
            continue

        # ATR_WINDOW=0: только если trend переключился именно на этом баре
        # ATR_WINDOW=1: разрешаем если trend стал +1 на этом или предыдущем баре
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

        # 4. SL = trendup на баре сигнала
        sl_price = df["trendup"].iloc[i]
        if pd.isna(sl_price) or sl_price <= 0:
            continue

        # Вход: open следующего бара
        entry_price = float(df["open"].iloc[i + 1])
        if entry_price <= 0:
            continue

        # Фильтр SL distance
        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct < MIN_SL_PCT or sl_dist_pct > MAX_SL_PCT:
            continue

        signals.append({
            "signal_idx": i,
            "entry_idx":  i + 1,
            "entry_price": entry_price,
            "sl_price":    float(sl_price),
            "wt1":         wt1_cur,
            "wt2":         wt2_cur,
        })

    return signals


def simulate_trade(df: pd.DataFrame, entry_idx: int, entry_price: float, sl_price: float) -> dict:
    """Симулирует одну LONG сделку с TSL (trendup двигается вверх)."""
    one_r = entry_price - sl_price
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl = sl_price
    tsl_activated = False
    TSL_ACTIVATION_R = 1.0

    for i in range(entry_idx + 1, len(df)):
        low  = float(df["low"].iloc[i])
        high = float(df["high"].iloc[i])
        close = float(df["close"].iloc[i])

        # Проверка SL
        if low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            return {"status": "TSL" if tsl_activated else "SL",
                    "exit_r": exit_r, "bars": i - entry_idx}

        current_r = (close - entry_price) / one_r

        # Активация TSL
        if not tsl_activated and current_r >= TSL_ACTIVATION_R:
            tsl_activated = True

        # Двигаем TSL вверх по trendup
        new_sl = df["trendup"].iloc[i]
        if not pd.isna(new_sl) and new_sl > current_sl:
            current_sl = float(new_sl)

    # Дошли до конца свечей
    final_r = (float(df["close"].iloc[-1]) - entry_price) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df) - entry_idx}


# ── Основная функция ─────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 70)
    print(f"  БЭКТЕСТ: WT crossup < {WT_OVERSOLD} + ATR trend crossup | SL = trendup | ATR factor=1.25")
    print("=" * 70)

    # Список символов из БД (последние активные пары)
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

    print(f"\nСимволов для теста: {len(symbols)}")
    print(f"Свечей на символ: {CANDLES} × {TIMEFRAME} ≈ {CANDLES * 15 // 60 // 24} дней\n")

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()

    all_trades  = []
    total_signals = 0
    skipped = 0

    for sym in symbols:
        try:
            df = await dc.get_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLES)
            if df is None or len(df) < 100:
                skipped += 1
                continue

            df = calculate_wt(df)
            df = calculate_trend(df, factor=1.25)

            signals = find_signals(df)
            total_signals += len(signals)

            for sig in signals:
                result = simulate_trade(df, sig["entry_idx"], sig["entry_price"], sig["sl_price"])
                if result["exit_r"] is None:
                    continue
                all_trades.append({
                    "symbol":      sym,
                    "entry_price": sig["entry_price"],
                    "sl_price":    sig["sl_price"],
                    "sl_pct":      abs(sig["entry_price"] - sig["sl_price"]) / sig["entry_price"] * 100,
                    "wt1":         sig["wt1"],
                    "status":      result["status"],
                    "exit_r":      result["exit_r"],
                    "bars":        result.get("bars", 0),
                })

        except Exception as e:
            skipped += 1
            continue

    await dc.stop()

    # ── Результаты ────────────────────────────────────────────────────────────
    n = len(all_trades)
    print(f"Символов обработано: {len(symbols) - skipped}/{len(symbols)}")
    print(f"Сигналов найдено:    {total_signals}")
    print(f"Сделок в тесте:      {n}")

    if n < 5:
        print("\n⚠️  Недостаточно сделок для анализа (минимум 5).")
        return

    print("\n" + "=" * 70)
    print("  МЕТРИКИ СТРАТЕГИИ")
    print("=" * 70)

    rs = [t["exit_r"] for t in all_trades]
    wins   = [t for t in all_trades if t["exit_r"] > 0]
    losses = [t for t in all_trades if t["exit_r"] <= 0]
    tsl_exits = [t for t in all_trades if t["status"] == "TSL"]
    sl_exits  = [t for t in all_trades if t["status"] == "SL"]
    open_pos  = [t for t in all_trades if t["status"] == "OPEN"]

    avg_r   = sum(rs) / n
    win_r   = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
    loss_r  = sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
    wrate   = 100 * len(wins) / n
    pf      = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")

    rs_arr  = np.array(rs)
    sharpe  = rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0

    # Max drawdown (по кумулятивным R)
    cum = np.cumsum(rs_arr)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd_r = dd.min()

    moonshots = [t for t in all_trades if t["exit_r"] >= 5]

    print(f"\n  Сделок всего:    {n}")
    print(f"  Win Rate:        {wrate:.1f}%   {'[НОРМ]' if wrate >= 45 else '[СЛАБО]'}")
    print(f"  Avg R:           {avg_r:+.2f}   {'[НОРМ]' if avg_r >= 0.5 else '[СЛАБО]'}")
    print(f"  Avg R (win):     {win_r:+.2f}")
    print(f"  Avg R (loss):    {loss_r:+.2f}")
    print(f"  Profit Factor:   {pf:.2f}   {'[НОРМ]' if pf >= 1.5 else '[СЛАБО]'}")
    print(f"  Max DD (R):      {max_dd_r:+.2f}   {'[НОРМ]' if max_dd_r >= -5 else '[СЛАБО]'}")
    print(f"  Moonshots ≥5R:   {len(moonshots)}")
    print(f"\n  Выходы: SL={len(sl_exits)}  TSL={len(tsl_exits)}  OPEN={len(open_pos)}")
    print(f"  Avg SL dist:     {sum(t['sl_pct'] for t in all_trades)/n:.2f}%")
    print(f"  Avg bars/сделка: {sum(t['bars'] for t in all_trades)/n:.0f} баров × 15m")

    print("\n" + "=" * 70)
    print("  R-РАСПРЕДЕЛЕНИЕ")
    print("=" * 70)
    buckets = [("<−1R", lambda r: r < -1),
               ("−1–0R", lambda r: -1 <= r < 0),
               ("0–1R",  lambda r: 0  <= r < 1),
               ("1–2R",  lambda r: 1  <= r < 2),
               ("2–3R",  lambda r: 2  <= r < 3),
               ("3–5R",  lambda r: 3  <= r < 5),
               ("5R+",   lambda r: r >= 5)]
    for label, fn in buckets:
        cnt = sum(1 for t in all_trades if fn(t["exit_r"]))
        bar = "█" * (cnt // max(1, n // 40))
        print(f"  {label:7s}: {cnt:4d}  {bar}")

    print("\n" + "=" * 70)
    print("  ТОП-5 СДЕЛОК ПО R")
    print("=" * 70)
    top5 = sorted(all_trades, key=lambda x: x["exit_r"], reverse=True)[:5]
    for t in top5:
        print(f"  {t['symbol']:20s}  R={t['exit_r']:+.2f}  wt1={t['wt1']:.1f}  SL={t['sl_pct']:.2f}%  [{t['status']}]")

    print("\n" + "=" * 70)
    print("  ХУДШИЕ-5 СДЕЛОК")
    print("=" * 70)
    bot5 = sorted(all_trades, key=lambda x: x["exit_r"])[:5]
    for t in bot5:
        print(f"  {t['symbol']:20s}  R={t['exit_r']:+.2f}  wt1={t['wt1']:.1f}  SL={t['sl_pct']:.2f}%  [{t['status']}]")

    # Итоговый вердикт
    print("\n" + "=" * 70)
    print("  ВЕРДИКТ")
    print("=" * 70)
    if wrate >= 45 and avg_r >= 0.5 and pf >= 1.5:
        print("  ✅ СТРАТЕГИЯ ЖИЗНЕСПОСОБНА — все метрики в норме")
    elif wrate >= 40 and avg_r >= 0.2:
        print("  ⚡ СТРАТЕГИЯ ТРЕБУЕТ ДОРАБОТКИ — потенциал есть, но метрики ниже цели")
    else:
        print("  ❌ СТРАТЕГИЯ СЛАБАЯ — не рекомендована без существенных изменений")

    if n < 30:
        print(f"  ⚠️  Малая выборка ({n} сделок) — результаты не статистически значимы")


if __name__ == "__main__":
    asyncio.run(run_backtest())
