"""
DEV-223 (Phase 2): Multi-TF Scaling-In Backtest.

КОНЦЕПЦИЯ:
Когда сильный HTF паттерн (L1_golden) активен на паре, открываем
до 4-х НЕЗАВИСИМЫХ LONG позиций на разных TF одновременно:

  Position 1 (5m):  узкий SL (10 баров 5m swing) → большое R при движении
  Position 2 (15m): средний SL (10 баров 15m swing)
  Position 3 (1h):  широкий SL (10 баров 1h swing)
  Position 4 (4h):  самый широкий SL (10 баров 4h swing) → дольше держать

Каждая позиция — свой entry timing, своя R-multiple, свой exit per TF.

Опытные правила exit per TF (из D-022 + D-015):
  5m:  time_exit=4h (24 баров 5m) — захват быстрого движения
  15m: time_exit=12h (48 баров 15m)
  1h:  time_exit=24h (24 баров 1h) — D-022 sweet spot для L1_golden
  4h:  time_exit=96h=4 days (24 баров 4h)

HTF context = bull_div_1d + bull_fvg_4h + wt_os_4h (L1_golden) trigger на 1h.
Для каждого 1h trigger → пытаемся открыть entries на ВСЕХ 4 TF.

Output:
  data/research/2026-05-20--ph2/multi_tf_scaling_v2.csv
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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY = {
    "5m":  PROJECT_ROOT / "data" / "history" / "5m",
    "15m": PROJECT_ROOT / "data" / "history" / "15m",
    "1h":  PROJECT_ROOT / "data" / "history" / "1h",
    "4h":  None,   # 4h получаем resample из 1h
}
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# HTF anchor (L1_golden)
HTF_FACTORS = ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"]
DIRECTION = "LONG"

# Exit configuration per TF (из D-022)
EXIT_CONFIG = {
    "5m":  {"time_bars": 48,   "sl_lookback": 20, "tp_strategy": "no_trail"},   # 4h
    "15m": {"time_bars": 48,   "sl_lookback": 20, "tp_strategy": "no_trail"},   # 12h
    "1h":  {"time_bars": 24,   "sl_lookback": 10, "tp_strategy": "no_trail"},   # 24h (D-022 winner)
    "4h":  {"time_bars": 24,   "sl_lookback": 10, "tp_strategy": "no_trail"},   # 4 days
}


def load_df(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    return df[["open", "high", "low", "close", "volume"]].dropna().sort_index()


def resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h → 4h."""
    return df_1h.resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()


def simulate_no_trail(df: pd.DataFrame, entry_i: int, sl_lookback: int, time_bars: int) -> dict:
    """No-trail LONG simulation: SL = swing_low × 0.999, time exit."""
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    if entry_i + time_bars >= n or entry_i < sl_lookback:
        return None

    price = float(close[entry_i])
    sl_price = float(low[entry_i - sl_lookback:entry_i + 1].min()) * 0.999
    sl_dist = price - sl_price
    if sl_dist <= 0 or sl_dist / price > 0.06:
        return None

    for i in range(entry_i + 1, entry_i + 1 + time_bars):
        if low[i] <= sl_price:
            return {"r": -1.0, "exit": "sl", "duration_bars": i - entry_i,
                    "entry_price": price, "sl_dist_pct": sl_dist / price * 100}
    end_price = float(close[entry_i + time_bars])
    exit_r = (end_price - price) / sl_dist
    return {"r": exit_r, "exit": "time", "duration_bars": time_bars,
            "entry_price": price, "sl_dist_pct": sl_dist / price * 100}


def find_htf_trigger_timestamps(symbol: str) -> list[pd.Timestamp]:
    """Возвращает список 1h timestamps где L1_golden HTF активен."""
    path_1h = HISTORY["1h"] / f"{symbol}.parquet"
    if not path_1h.exists():
        return []

    res = cb.process_symbol(path_1h)
    if res is None:
        return []
    flags, _, _ = res

    mask = np.ones(len(flags), dtype=bool)
    for f in HTF_FACTORS:
        if f not in flags.columns:
            return []
        mask &= flags[f].values
    if not mask.any():
        return []

    return list(flags.index[mask])


def run_multi_tf_scaling(symbol: str) -> list[dict]:
    """Для каждого 1h HTF trigger пытаемся открыть entries на 4 TF.

    Returns list of dicts с результатами per (htf_ts, tf).
    """
    triggers = find_htf_trigger_timestamps(symbol)
    if not triggers:
        return []

    # Load all TF data
    dfs = {}
    for tf in ["5m", "15m", "1h"]:
        path = HISTORY[tf] / f"{symbol}.parquet"
        if not path.exists():
            return []
        dfs[tf] = load_df(path)
    dfs["4h"] = resample_to_4h(dfs["1h"])

    results = []
    for htf_ts in triggers:
        # Group ID = htf event identifier
        group_id = f"{symbol}_{htf_ts.isoformat()}"

        for tf in ["5m", "15m", "1h", "4h"]:
            df = dfs[tf]
            # Find first bar >= htf_ts in this TF
            try:
                # bar index
                idx_arr = df.index.values
                # Convert htf_ts to numpy
                target = np.datetime64(htf_ts.to_pydatetime().replace(tzinfo=None))
                # Find idx
                bar_idx = int(np.searchsorted(idx_arr, target, side="left"))
                if bar_idx >= len(df):
                    continue
            except Exception:
                continue

            cfg = EXIT_CONFIG[tf]
            res = simulate_no_trail(df, bar_idx, cfg["sl_lookback"], cfg["time_bars"])
            if res is None:
                continue

            results.append({
                "group_id": group_id,
                "symbol": symbol,
                "htf_ts": htf_ts.isoformat(),
                "tf": tf,
                "entry_price": res["entry_price"],
                "sl_dist_pct": res["sl_dist_pct"],
                "exit_r": res["r"],
                "exit_type": res["exit"],
                "duration_bars": res["duration_bars"],
            })

    return results


def main():
    with register_run("multi_tf_scaling_v2") as run:
        # Найти пары которые есть на всех 3 LTF
        syms_1h = {p.stem for p in HISTORY["1h"].glob("*.parquet")}
        syms_15m = {p.stem for p in HISTORY["15m"].glob("*.parquet")}
        syms_5m = {p.stem for p in HISTORY["5m"].glob("*.parquet")}
        common = sorted(syms_1h & syms_15m & syms_5m)
        print(f"Pairs available on all TF: {len(common)}")

        all_results = []
        t0 = time.time()
        for i, sym in enumerate(common):
            res = run_multi_tf_scaling(sym)
            all_results.extend(res)
            if (i + 1) % 5 == 0:
                print(f"  ...{i+1}/{len(common)} | entries collected: {len(all_results)} | {time.time()-t0:.0f}s")

        if not all_results:
            print("No HTF triggers found")
            return

        df = pd.DataFrame(all_results)
        out = OUTPUT_DIR / "multi_tf_scaling_v2.csv"
        df.to_csv(out, index=False, encoding="utf-8")
        run.add_output(out)

        # ─── Stats per TF ───
        print(f"\n{'='*80}")
        print(f"MULTI-TF SCALING STATISTICS")
        print(f"{'='*80}")
        print(f"\nTotal entries collected: {len(df)}")
        print(f"Unique HTF events: {df['group_id'].nunique()}")
        print(f"Avg entries per HTF event: {len(df) / df['group_id'].nunique():.2f}")

        print(f"\n=== Per-TF stats ===")
        print(f"{'TF':<5} {'n':>5} {'avgR':>8} {'WR':>6} {'sumR':>9} {'avg_dur_bars':>13}")
        for tf in ["5m", "15m", "1h", "4h"]:
            sub = df[df["tf"] == tf]
            if not len(sub):
                continue
            print(f"{tf:<5} {len(sub):>5} {sub['exit_r'].mean():>+8.3f} "
                  f"{(sub['exit_r']>0).mean()*100:>5.1f}% {sub['exit_r'].sum():>+9.1f} "
                  f"{sub['duration_bars'].mean():>13.1f}")

        # ─── Per-group stats (сколько TF удалось открыть в одном event) ───
        per_group = df.groupby("group_id").agg(
            n_entries=("tf", "count"),
            total_r=("exit_r", "sum"),
            mean_r=("exit_r", "mean"),
        ).reset_index()
        print(f"\n=== Per-HTF-event aggregation ===")
        print(f"  HTF events with 4 TF entries: {(per_group['n_entries'] == 4).sum()}")
        print(f"  HTF events with 3 TF entries: {(per_group['n_entries'] == 3).sum()}")
        print(f"  HTF events with 2 TF entries: {(per_group['n_entries'] == 2).sum()}")
        print(f"  HTF events with 1 TF entries: {(per_group['n_entries'] == 1).sum()}")
        print(f"\n  Avg total R per HTF event: {per_group['total_r'].mean():+.3f}")
        print(f"  Sum total R: {per_group['total_r'].sum():+.1f}")

        # ─── Compound effect: portfolio approach ───
        # Если открываем все 4 TF одновременно по 1% риска каждый — total 4% riskaccount
        # Total R per event = sum of per-TF R-multiples
        print(f"\n=== Portfolio scaling effect (1% risk per TF, max 4% per event) ===")
        portfolio_r = per_group["total_r"].values
        print(f"  Per-event total R: avg={portfolio_r.mean():+.3f}, median={np.median(portfolio_r):+.3f}")
        print(f"  Best event total R: {portfolio_r.max():+.2f}")
        print(f"  Worst event total R: {portfolio_r.min():+.2f}")

        # Top 10 best HTF events (compound effect)
        print(f"\n  TOP-10 HTF events by total R (multi-TF compound):")
        for _, r in per_group.sort_values("total_r", ascending=False).head(10).iterrows():
            tfs = df[df["group_id"] == r["group_id"]]["tf"].tolist()
            print(f"    {r['group_id']:<50} entries={int(r['n_entries'])} TFs={tfs} total_R={r['total_r']:+.2f}")


if __name__ == "__main__":
    main()
