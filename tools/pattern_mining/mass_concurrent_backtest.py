"""
DEV-225 (Phase 2): MASS-CONCURRENT BACKTEST.

User vision 2026-05-20:
"На каждом TF не 4 patterns а сколько найдём. Всё используем одновременно
без ограничений. Копать глубже всю информацию."

Реализация:
1. Берём ВСЕ 12 002 MHT-passed паттернов (Phase 1.A)
2. Для каждой пары × каждой свечи 1h: собираем какие паттерны срабатывают одновременно
3. Симулируем КАЖДУЮ entry независимо (own SL, own R, own exit)
4. Aggregate:
   - Total trades count
   - Per-pair concurrent positions (peak / avg)
   - Total R (если бы все торговали с 0.1% risk → portfolio compound)
   - Risk concentration: сколько паттернов на одной паре одновременно

Output:
  data/research/2026-05-20--ph2/mass_concurrent.csv
  data/research/2026-05-20--ph2/mass_concurrent_per_pair.csv
"""
from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
MHT_INPUT = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1" / "walkforward_full_mht.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Используем ТОПОВ-K паттернов (компромисс между depth и speed)
TOP_K_PATTERNS = 500
TIME_EXIT_BARS = 24      # 24h exit для 1h baseline
SL_LOOKBACK = 10


def load_top_patterns(top_k: int = TOP_K_PATTERNS):
    """Returns top-K MHT-passed patterns ordered by composite score."""
    df = pd.read_csv(MHT_INPUT)
    df = df.sort_values("composite_score", ascending=False).head(top_k)
    return [
        {
            "factors": tuple(f.strip() for f in row["pattern"].split(" + ")),
            "direction": row["direction"],
            "test_avgR": row["test_avgR"],
            "test_WR": row["test_WR"],
        }
        for _, row in df.iterrows()
    ]


def simulate_no_trail(df, entry_i, direction, sl_lookback=SL_LOOKBACK, time_bars=TIME_EXIT_BARS):
    n = len(df)
    if entry_i < sl_lookback or entry_i + time_bars >= n:
        return None
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    price = float(close[entry_i])
    if direction == "LONG":
        sl_price = float(low[entry_i - sl_lookback:entry_i + 1].min()) * 0.999
        sl_dist = price - sl_price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        for i in range(entry_i + 1, entry_i + 1 + time_bars):
            if low[i] <= sl_price:
                return -1.0
        end_price = float(close[entry_i + time_bars])
        return (end_price - price) / sl_dist
    else:
        sl_price = float(high[entry_i - sl_lookback:entry_i + 1].max()) * 1.001
        sl_dist = sl_price - price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        for i in range(entry_i + 1, entry_i + 1 + time_bars):
            if high[i] >= sl_price:
                return -1.0
        end_price = float(close[entry_i + time_bars])
        return (price - end_price) / sl_dist


def process_symbol(sym: str, patterns: list, ohlcv_dfs: dict):
    """Для одного symbol собирает все entries всех patterns с симуляцией."""
    res = cb.process_symbol(HISTORY_1H / f"{sym}.parquet")
    if res is None:
        return [], None
    flags, _, _ = res

    df = ohlcv_dfs.get(sym)
    if df is None:
        path = HISTORY_1H / f"{sym}.parquet"
        if not path.exists():
            return [], None
        df = pd.read_parquet(path)
        df.columns = [c.lower() for c in df.columns]
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
            df = df.set_index("ts")
        df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()

    # Align flags to df
    common_idx = flags.index.intersection(df.index)
    flags = flags.loc[common_idx]
    df = df.loc[common_idx]

    entries = []
    for pat_idx, pat in enumerate(patterns):
        # Build mask
        try:
            mask = np.ones(len(flags), dtype=bool)
            for f in pat["factors"]:
                if f not in flags.columns:
                    mask = mask & False
                    break
                mask &= flags[f].values
        except Exception:
            continue
        if not mask.any():
            continue

        # Symulate каждое срабатывание
        for i in np.where(mask)[0]:
            r = simulate_no_trail(df, i, pat["direction"])
            if r is None:
                continue
            entries.append({
                "sym": sym,
                "pat_idx": pat_idx,
                "ts": flags.index[i],
                "direction": pat["direction"],
                "r": r,
            })

    return entries, df


def main():
    with register_run("mass_concurrent_backtest", params={"top_k": TOP_K_PATTERNS}) as run:
        patterns = load_top_patterns(TOP_K_PATTERNS)
        print(f"Loaded {len(patterns)} top patterns")
        print(f"  LONG: {sum(1 for p in patterns if p['direction']=='LONG')}")
        print(f"  SHORT: {sum(1 for p in patterns if p['direction']=='SHORT')}")

        files = sorted(HISTORY_1H.glob("*.parquet"))
        all_entries = []
        ohlcv_cache = {}
        t0 = time.time()

        for i, path in enumerate(files):
            sym = path.stem
            entries, df = process_symbol(sym, patterns, ohlcv_cache)
            if df is not None:
                ohlcv_cache[sym] = df
            all_entries.extend(entries)
            if (i + 1) % 5 == 0:
                print(f"  ...{i+1}/{len(files)} | total entries: {len(all_entries)} | {time.time()-t0:.0f}s")

        print(f"\nTotal trades collected: {len(all_entries)}")
        if not all_entries:
            return

        df_all = pd.DataFrame(all_entries)
        df_all["ts"] = pd.to_datetime(df_all["ts"], utc=True)

        # ─── Stats ───
        print(f"\n{'='*80}")
        print(f"MASS-CONCURRENT STATS")
        print(f"{'='*80}")
        print(f"  Total trades: {len(df_all)}")
        print(f"  Total R sum: {df_all['r'].sum():+.1f}")
        print(f"  Avg R per trade: {df_all['r'].mean():+.3f}")
        print(f"  Overall WR: {(df_all['r']>0).mean()*100:.1f}%")

        print(f"\nBy direction:")
        for direction in ["LONG", "SHORT"]:
            sub = df_all[df_all["direction"] == direction]
            if not len(sub):
                continue
            print(f"  {direction}: n={len(sub):>7} avgR={sub['r'].mean():>+.3f} "
                  f"WR={(sub['r']>0).mean()*100:>4.1f}% sumR={sub['r'].sum():>+9.1f}")

        # Concurrent positions analysis per pair × hour
        df_all["hour"] = df_all["ts"].dt.floor("1h")
        concur = df_all.groupby(["sym", "hour"]).agg(
            n_concurrent=("pat_idx", "count"),
            n_long=("direction", lambda x: (x == "LONG").sum()),
            n_short=("direction", lambda x: (x == "SHORT").sum()),
        ).reset_index()

        print(f"\n=== Concurrent triggers per (pair × hour) ===")
        print(f"  Max concurrent triggers: {concur['n_concurrent'].max()}")
        print(f"  Avg concurrent triggers: {concur['n_concurrent'].mean():.2f}")
        print(f"  Median: {int(concur['n_concurrent'].median())}")
        for n in [1, 5, 10, 20, 50, 100, 200]:
            cnt = (concur['n_concurrent'] >= n).sum()
            print(f"  ≥{n:>3} concurrent: {cnt} events")

        # Per-pair totals
        print(f"\n=== Per-pair trade volume ===")
        per_pair = df_all.groupby("sym").agg(
            n_trades=("r", "count"),
            sumR=("r", "sum"),
            avgR=("r", "mean"),
            wr=("r", lambda x: (x > 0).mean() * 100),
        ).sort_values("sumR", ascending=False)

        out_pair = OUTPUT_DIR / "mass_concurrent_per_pair.csv"
        per_pair.to_csv(out_pair, encoding="utf-8")
        run.add_output(out_pair)

        print(f"\n  TOP-10 pairs by sumR:")
        for sym, row in per_pair.head(10).iterrows():
            print(f"    {sym:<18} n={int(row['n_trades']):>6} sumR={row['sumR']:>+8.1f} "
                  f"avgR={row['avgR']:>+.3f} WR={row['wr']:>4.1f}%")

        print(f"\n  BOTTOM-5 pairs by sumR:")
        for sym, row in per_pair.tail(5).iterrows():
            print(f"    {sym:<18} n={int(row['n_trades']):>6} sumR={row['sumR']:>+8.1f} "
                  f"avgR={row['avgR']:>+.3f} WR={row['wr']:>4.1f}%")

        # Portfolio simulation (0.1% risk per trade — to handle massive concurrent)
        # If we trade ALL signals — compound wealth growth
        df_sorted = df_all.sort_values("ts")
        rs = df_sorted["r"].values
        wealth = 1.0
        for r in rs:
            wealth *= (1 + 0.001 * r)   # 0.1% risk per trade
        print(f"\n=== Portfolio compound (0.1% risk / trade, all-in sequential) ===")
        print(f"  Initial: 1.00")
        print(f"  Final wealth: {wealth:.3f}")
        print(f"  Total return: {(wealth-1)*100:+.1f}%")
        print(f"  Annualized (over ~2 years): {((wealth)**(1/2)-1)*100:+.1f}%")

        out = OUTPUT_DIR / "mass_concurrent.csv"
        df_all.to_csv(out, index=False, encoding="utf-8")
        run.add_output(out)


if __name__ == "__main__":
    main()
