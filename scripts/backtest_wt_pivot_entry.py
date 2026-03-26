#!/usr/bin/env python3
"""
Бэктест: WT crossup < -59 + ATR crossup + касание конфлюентного пивота
=======================================================================
3m таймфрейм, ATR factor=1.25

Условие входа:
  1. wt1 пересекает wt2 снизу вверх
  2. wt1 < -59 (глубокая перепроданность)
  3. ATR trend -1 → +1 (подтверждение разворота)
  4. [бонус] low бара сигнала в пределах PIVOT_TOUCH_PCT% от конфлюентного пивота

Конфлюентный пивот = уровень, который совпадает в 2+ ТФ (1D+1W, 1D+1M, 1W+1M)

Сравнение:
  A) Все сигналы (baseline)
  B) Только с касанием конфлюентного пивота
  C) Только с касанием любого пивота (1D / 1W / 1M)

Запуск: python scripts/backtest_wt_pivot_entry.py
"""
import os, sys, asyncio, sqlite3, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np

from core.data_collector import RealTimeData
from core.indicators import calculate_wt, calculate_trend
from core.pivot_calculator_fixed import PivotCalculatorFixed

logging.basicConfig(level=logging.WARNING)

# ── Параметры ────────────────────────────────────────────────────────────────
SYMBOLS_LIMIT    = 50
CANDLES          = 1440       # max BingX 3m
TIMEFRAME        = "3m"
WT_OVERSOLD      = -59
ATR_WINDOW       = 1
ATR_FACTOR       = 1.25
MIN_SL_PCT       = 0.003
MAX_SL_PCT       = 0.08
PIVOT_TOUCH_PCT  = 1.0        # % от уровня пивота для "касания"
CONFLUENCE_PCT   = 0.5        # % для признания конфлюэнции между ТФ


# ── Поиск сигналов ───────────────────────────────────────────────────────────

def find_signals(df: pd.DataFrame, pivot_levels: dict) -> list:
    """
    pivot_levels = {
        'any':         [(price, label), ...],   # все уровни 1D+1W+1M
        'confluence':  [(price, label), ...],   # только конфлюентные (2+ ТФ)
    }
    """
    signals = []

    for i in range(2, len(df) - 1):
        wt1_prev = df["wt1"].iloc[i-1]
        wt2_prev = df["wt2"].iloc[i-1]
        wt1_cur  = df["wt1"].iloc[i]
        wt2_cur  = df["wt2"].iloc[i]

        if pd.isna(wt1_prev) or pd.isna(wt2_prev) or pd.isna(wt1_cur) or pd.isna(wt2_cur):
            continue

        if not ((wt1_prev < wt2_prev) and (wt1_cur >= wt2_cur)):
            continue

        if wt1_cur >= WT_OVERSOLD:
            continue

        # ATR trend crossup
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

        sl_price = df["trendup"].iloc[i]
        if pd.isna(sl_price) or sl_price <= 0:
            continue

        entry_price = float(df["open"].iloc[i + 1])
        if entry_price <= 0:
            continue

        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct < MIN_SL_PCT or sl_dist_pct > MAX_SL_PCT:
            continue

        # Проверяем касание пивота по low бара сигнала
        bar_low = float(df["low"].iloc[i])

        has_any_pivot = _near_any(bar_low, pivot_levels.get("any", []))
        has_confluence = _near_any(bar_low, pivot_levels.get("confluence", []))

        signals.append({
            "signal_idx":    i,
            "entry_idx":     i + 1,
            "entry_price":   entry_price,
            "sl_price":      float(sl_price),
            "sl_pct":        sl_dist_pct * 100,
            "wt1":           wt1_cur,
            "has_any_pivot": has_any_pivot,
            "has_confluence": has_confluence,
        })

    return signals


def _near_any(price: float, levels: list) -> bool:
    """True если price в пределах PIVOT_TOUCH_PCT% от любого уровня."""
    for lvl_price, _ in levels:
        if lvl_price <= 0:
            continue
        if abs(price - lvl_price) / lvl_price * 100 <= PIVOT_TOUCH_PCT:
            return True
    return False


# ── Получение пивотов ────────────────────────────────────────────────────────

async def get_pivot_levels(pc: PivotCalculatorFixed, symbol: str, dc) -> dict:
    """Возвращает {'any': [...], 'confluence': [...]}."""
    try:
        mtf = await pc.get_multi_timeframe_pivots(symbol, dc)
    except Exception:
        return {"any": [], "confluence": []}

    # Все уровни из всех ТФ
    level_keys = ["PP", "S1", "S2", "S3", "R1", "R2", "R3"]
    all_levels = []
    by_tf = {}

    for tf in ("1M", "1W", "1D"):
        pivots = mtf.get(tf)
        if not pivots:
            continue
        tf_levels = []
        for k in level_keys:
            v = pivots.get(k)
            if v and v > 0:
                all_levels.append((v, f"{tf}_{k}"))
                tf_levels.append((v, k))
        by_tf[tf] = tf_levels

    # Конфлюентные: уровень встречается в 2+ ТФ в пределах CONFLUENCE_PCT%
    confluence = []
    tfs = list(by_tf.keys())
    seen = set()
    for i_tf in range(len(tfs)):
        for j_tf in range(i_tf + 1, len(tfs)):
            for p_a, k_a in by_tf[tfs[i_tf]]:
                for p_b, k_b in by_tf[tfs[j_tf]]:
                    dist = abs(p_a - p_b) / max(p_a, p_b) * 100
                    if dist <= CONFLUENCE_PCT:
                        mid = (p_a + p_b) / 2
                        label = f"{tfs[i_tf]}_{k_a}+{tfs[j_tf]}_{k_b}"
                        key = round(mid, 8)
                        if key not in seen:
                            seen.add(key)
                            confluence.append((mid, label))

    return {"any": all_levels, "confluence": confluence}


# ── Симуляция ────────────────────────────────────────────────────────────────

def simulate_trade(df: pd.DataFrame, entry_idx: int, entry_price: float, sl_price: float) -> dict:
    one_r = entry_price - sl_price
    if one_r <= 0:
        return {"status": "INVALID", "exit_r": None}

    current_sl    = sl_price
    tsl_activated = False

    for i in range(entry_idx + 1, len(df)):
        low   = float(df["low"].iloc[i])
        close = float(df["close"].iloc[i])

        if low <= current_sl:
            exit_r = (current_sl - entry_price) / one_r
            return {"status": "TSL" if tsl_activated else "SL",
                    "exit_r": exit_r, "bars": i - entry_idx}

        if not tsl_activated and (close - entry_price) / one_r >= 1.0:
            tsl_activated = True

        new_sl = df["trendup"].iloc[i]
        if not pd.isna(new_sl) and new_sl > current_sl:
            current_sl = float(new_sl)

    final_r = (float(df["close"].iloc[-1]) - entry_price) / one_r
    return {"status": "OPEN", "exit_r": final_r, "bars": len(df) - entry_idx}


# ── Метрики ──────────────────────────────────────────────────────────────────

def print_metrics(label: str, trades: list):
    n = len(trades)
    if n == 0:
        print(f"  {label}: нет сделок")
        return

    rs      = [t["exit_r"] for t in trades]
    wins    = [t for t in trades if t["exit_r"] > 0]
    losses  = [t for t in trades if t["exit_r"] <= 0]
    sl_ex   = [t for t in trades if t["status"] == "SL"]
    tsl_ex  = [t for t in trades if t["status"] == "TSL"]
    open_p  = [t for t in trades if t["status"] == "OPEN"]
    moon    = [t for t in trades if t["exit_r"] >= 5]

    avg_r  = sum(rs) / n
    win_r  = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
    loss_r = sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
    wrate  = 100 * len(wins) / n
    pf     = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")

    rs_arr = np.array(rs)
    sharpe = rs_arr.mean() / rs_arr.std() * np.sqrt(n) if rs_arr.std() > 0 else 0
    cum    = np.cumsum(rs_arr)
    max_dd = (cum - np.maximum.accumulate(cum)).min()

    print(f"  {label}")
    print(f"  {'─'*52}")
    print(f"  Сделок:        {n}{'  ⚠️ мало' if n < 20 else ''}")
    print(f"  Win Rate:      {wrate:.1f}%")
    print(f"  Avg R:         {avg_r:+.2f}")
    print(f"  Avg R (win):   {win_r:+.2f}   Avg R (loss): {loss_r:+.2f}")
    print(f"  Profit Factor: {pf:.2f}   Sharpe: {sharpe:.2f}")
    print(f"  Max DD (R):    {max_dd:+.2f}")
    print(f"  Moonshots ≥5R: {len(moon)}")
    print(f"  Выходы:        SL={len(sl_ex)}  TSL={len(tsl_ex)}  OPEN={len(open_p)}")
    print(f"  Avg SL dist:   {sum(t['sl_pct'] for t in trades)/n:.2f}%")

    buckets = [("<−1R", lambda r: r < -1), ("−1–0R", lambda r: -1 <= r < 0),
               ("0–1R", lambda r: 0 <= r < 1), ("1–2R", lambda r: 1 <= r < 2),
               ("2–3R", lambda r: 2 <= r < 3), ("3–5R", lambda r: 3 <= r < 5),
               ("5R+",  lambda r: r >= 5)]
    print()
    for lbl, fn in buckets:
        cnt = sum(1 for t in trades if fn(t["exit_r"]))
        bar = "█" * (cnt // max(1, n // 40))
        print(f"  {lbl:7s}: {cnt:3d}  {bar}")
    print()


# ── Основная функция ─────────────────────────────────────────────────────────

async def run_backtest():
    print("=" * 70)
    print(f"  БЭКТЕСТ: WT < {WT_OVERSOLD} + ATR crossup + Конфлюентный пивот")
    print(f"  TF={TIMEFRAME}  ATR={ATR_FACTOR}  PIVOT_TOUCH={PIVOT_TOUCH_PCT}%  CONFLUENCE={CONFLUENCE_PCT}%")
    print("=" * 70)

    conn = sqlite3.connect("subscriptions.db")
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM simulated_trades WHERE timeframe='15m' ORDER BY created_at DESC LIMIT ?",
        (SYMBOLS_LIMIT,)
    ).fetchall()]
    conn.close()

    print(f"\nСимволов: {len(symbols)}  Свечей: {CANDLES} × {TIMEFRAME}\n")

    dc = RealTimeData("bingx", api_semaphore_size=15, api_rps=15.0)
    await dc.load_markets()
    pc = PivotCalculatorFixed(dc)

    all_trades     = []
    any_piv_trades = []
    conf_trades    = []
    total_signals  = 0
    skipped        = 0

    for idx, sym in enumerate(symbols, 1):
        try:
            df = await dc.get_ohlcv(sym, timeframe=TIMEFRAME, limit=CANDLES)
            if df is None or len(df) < 100:
                skipped += 1
                continue

            df = calculate_wt(df)
            df = calculate_trend(df, factor=ATR_FACTOR)

            pivot_levels = await get_pivot_levels(pc, sym, dc)

            signals = find_signals(df, pivot_levels)
            total_signals += len(signals)

            for sig in signals:
                result = simulate_trade(df, sig["entry_idx"], sig["entry_price"], sig["sl_price"])
                if result["exit_r"] is None:
                    continue
                trade = {**sig, **result}
                all_trades.append(trade)
                if sig["has_any_pivot"]:
                    any_piv_trades.append(trade)
                if sig["has_confluence"]:
                    conf_trades.append(trade)

        except Exception as e:
            skipped += 1
            continue

        if idx % 10 == 0:
            print(f"  Обработано {idx}/{len(symbols)}...")

    await dc.stop()

    print(f"\nОбработано: {len(symbols)-skipped}/{len(symbols)}")
    print(f"Сигналов всего:          {total_signals}")
    print(f"С любым пивотом:         {sum(1 for s in all_trades if s['has_any_pivot'])} ({100*sum(1 for s in all_trades if s['has_any_pivot'])//max(1,len(all_trades))}%)")
    print(f"С конфлюентным пивотом:  {sum(1 for s in all_trades if s['has_confluence'])} ({100*sum(1 for s in all_trades if s['has_confluence'])//max(1,len(all_trades))}%)")

    print("\n" + "=" * 70)
    print("  A) BASELINE — все сигналы")
    print("=" * 70)
    print_metrics("WT < -59 + ATR", all_trades)

    print("=" * 70)
    print("  B) + любой пивот 1D/1W/1M в пределах 1%")
    print("=" * 70)
    print_metrics("WT < -59 + ATR + любой пивот", any_piv_trades)

    print("=" * 70)
    print("  C) + конфлюентный пивот (2+ ТФ совпадают)")
    print("=" * 70)
    print_metrics("WT < -59 + ATR + конфлюенция", conf_trades)

    # Сравнительная таблица
    print("=" * 70)
    print("  СРАВНЕНИЕ")
    print("=" * 70)
    print(f"  {'Вариант':<35}  {'n':>4}  {'WR%':>6}  {'Avg R':>7}  {'PF':>5}  {'Moon':>4}")
    print(f"  {'─'*35}  {'─'*4}  {'─'*6}  {'─'*7}  {'─'*5}  {'─'*4}")
    for lbl, trades in [
        ("A) baseline",                   all_trades),
        ("B) + любой пивот",              any_piv_trades),
        ("C) + конфлюентный пивот",       conf_trades),
    ]:
        if not trades:
            print(f"  {lbl:<35}  {'—':>4}")
            continue
        rs    = [t["exit_r"] for t in trades]
        wins  = [t for t in trades if t["exit_r"] > 0]
        losses= [t for t in trades if t["exit_r"] <= 0]
        wr    = 100 * len(wins) / len(trades)
        ar    = sum(rs) / len(trades)
        win_r = sum(t["exit_r"] for t in wins)   / len(wins)   if wins   else 0
        loss_r= sum(t["exit_r"] for t in losses) / len(losses) if losses else 0
        pf    = win_r * len(wins) / abs(loss_r * len(losses)) if losses and loss_r != 0 else float("inf")
        moon  = sum(1 for t in trades if t["exit_r"] >= 5)
        print(f"  {lbl:<35}  {len(trades):>4}  {wr:>5.1f}%  {ar:>+7.2f}  {pf:>5.2f}  {moon:>4}")

    print()


if __name__ == "__main__":
    asyncio.run(run_backtest())
