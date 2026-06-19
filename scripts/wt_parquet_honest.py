# -*- coding: utf-8 -*-
"""WT-REVERSION на ЧИСТЫХ паркет-данных. Без API, без DB, без fake-R.
46 пар × 868 баров 1H → честный backtest WT процентилей.
"""
import os, sys, argparse
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd, numpy as np
from core.indicators.indicators import calculate_wt


def backtest_wt(close, wt_vals, w, pct):
    """WT процентильный кросс-овер backtest. Возвращает список R-значений (после fee)."""
    trades = []; in_pos = None; ei = 0
    for i in range(w + 10, len(close) - 5):
        win = wt_vals[i-w:i]
        th = np.percentile(win, pct)
        th_h = np.percentile(win, 100 - pct)
        if in_pos is None:
            if wt_vals[i-1] < th and wt_vals[i] > th:
                in_pos = 'LONG'; ei = i
            elif wt_vals[i-1] > th_h and wt_vals[i] < th_h:
                in_pos = 'SHORT'; ei = i
        else:
            ex = (in_pos == 'LONG' and wt_vals[i-1] > 0 and wt_vals[i] < 0) or \
                 (in_pos == 'SHORT' and wt_vals[i-1] < 0 and wt_vals[i] > 0)
            if ex or i - ei > w * 2:
                ep = close[ei]; xp = close[i]
                pnl_pct = (xp / ep - 1) * 100 if in_pos == 'LONG' else (ep / xp - 1) * 100
                sl_pct = max(abs(ep - close[ei+1]) / ep * 100, 0.05)
                fee_r = 0.1 / sl_pct
                r_val = pnl_pct / sl_pct
                trades.append(r_val - fee_r)
                in_pos = None
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=46)
    args = ap.parse_args()

    parquets = sorted(Path("data/history/15m").glob("*.parquet"))[:args.pairs]
    print(f"WT-REVERSION honest: {len(parquets)} пар из data/history/15m/")

    # Все комбинации
    configs = [(50, 5, "P5/50b"), (100, 5, "P5/100b"), (200, 5, "P5/200b"),
               (30, 5, "P5/30b"), (20, 10, "P10/20b")]

    for w, pct, label in configs:
        all_trades = []
        pos_pairs = 0; total_pairs = 0

        for pq in parquets:
            sym = pq.stem
            df15 = pd.read_parquet(pq)
            if len(df15) < w + 100:
                continue
            total_pairs += 1
            close = df15["close"].values
            wt_df = calculate_wt(df15, 10, 21)
            wt_vals = wt_df["wt2"].values

            if len(wt_vals) < w + 10:
                continue

            trades = backtest_wt(close, wt_vals, w, pct)
            if len(trades) >= 3:
                all_trades.extend(trades)
                if np.mean(trades) > 0:
                    pos_pairs += 1

        if all_trades:
            rs = np.array(all_trades)
            wr = np.mean(rs > 0) * 100
            print(f"  {label:>10s}: {len(all_trades):5d}tr  "
                  f"GROSS={np.mean(rs):+.3f}R  WR={wr:.0f}%  "
                  f"pos={pos_pairs}/{total_pairs} pairs")
        else:
            print(f"  {label:>10s}: NO trades")


if __name__ == "__main__":
    main()
