"""
DEV-220: TP/Exit Grid Search (Phase 2).

Расширенный exit grid:
  (A) Static TP: 2R, 3R, 5R, 10R, 15R
  (B) Time exit grid: 6h, 12h, 24h, 48h, 72h, 120h, 168h
  (C) R-conditional exit:
      - cut_early_if_loss: 6h если R<0, иначе 24h
      - extend_if_strong: 24h базовый, до 72h если R>+1
  (D) Hybrid: trail_after_2R + time fallback

Тестируется на топ-5 anchors (DEV-211 list).

Output:
  data/research/2026-05-20--ph2/tp_exit_grid_<anchor>.csv
  data/research/2026-05-20--ph2/tp_exit_grid_summary.csv
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
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


ANCHORS = {
    "L1_golden": {
        "factors": ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"],
        "direction": "LONG",
    },
    "L2_wt_double": {
        "factors": ["wt_os_1d", "bull_fvg_4h", "wt_os_1h"],
        "direction": "LONG",
    },
    "L4_wt_atr": {
        "factors": ["wt_os_1d", "atr_up_4h", "wt_os_1h"],
        "direction": "LONG",
    },
    "S1_bos_premium": {
        "factors": ["atr_cross_down_1d", "bear_bos_1d", "premium_4h"],
        "direction": "SHORT",
    },
    "S3_full_short": {
        "factors": ["bear_bos_1d", "bear_fvg_in_1h", "below_ema50_1h", "premium_4h"],
        "direction": "SHORT",
    },
}

# Time exit grid (in 1h bars)
TIME_EXIT_GRID = [6, 12, 24, 48, 72, 120, 168]   # 6h..1week

# TP-R grid
TP_R_GRID = [2.0, 3.0, 5.0, 10.0, 15.0]

SL_LOOKBACK = 10


def simulate_static_tp(df: pd.DataFrame, entry_i: int, sl_buf: float, tp_r: float,
                      time_limit: int, direction: str) -> dict:
    """Simulate trade with static TP/SL + time limit."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    price = close[entry_i]
    if direction == "LONG":
        sl_price = low[max(0, entry_i - SL_LOOKBACK):entry_i + 1].min() * (1 - sl_buf)
        sl_dist = price - sl_price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        tp_price = price + sl_dist * tp_r

        end_i = min(n - 1, entry_i + time_limit)
        for i in range(entry_i + 1, end_i + 1):
            if low[i] <= sl_price:
                return {"r": -1.0, "exit": "sl", "duration": i - entry_i}
            if high[i] >= tp_price:
                return {"r": tp_r, "exit": "tp", "duration": i - entry_i}
        # Time exit
        exit_r = (close[end_i] - price) / sl_dist
        return {"r": exit_r, "exit": "time", "duration": end_i - entry_i}
    else:   # SHORT
        sl_price = high[max(0, entry_i - SL_LOOKBACK):entry_i + 1].max() * (1 + sl_buf)
        sl_dist = sl_price - price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        tp_price = price - sl_dist * tp_r

        end_i = min(n - 1, entry_i + time_limit)
        for i in range(entry_i + 1, end_i + 1):
            if high[i] >= sl_price:
                return {"r": -1.0, "exit": "sl", "duration": i - entry_i}
            if low[i] <= tp_price:
                return {"r": tp_r, "exit": "tp", "duration": i - entry_i}
        exit_r = (price - close[end_i]) / sl_dist
        return {"r": exit_r, "exit": "time", "duration": end_i - entry_i}


def simulate_no_trail(df: pd.DataFrame, entry_i: int, sl_buf: float, time_limit: int,
                     direction: str) -> dict:
    """No TP — только SL и time exit."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    price = close[entry_i]
    if direction == "LONG":
        sl_price = low[max(0, entry_i - SL_LOOKBACK):entry_i + 1].min() * (1 - sl_buf)
        sl_dist = price - sl_price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        end_i = min(n - 1, entry_i + time_limit)
        for i in range(entry_i + 1, end_i + 1):
            if low[i] <= sl_price:
                return {"r": -1.0, "exit": "sl", "duration": i - entry_i}
        return {"r": (close[end_i] - price) / sl_dist, "exit": "time", "duration": end_i - entry_i}
    else:
        sl_price = high[max(0, entry_i - SL_LOOKBACK):entry_i + 1].max() * (1 + sl_buf)
        sl_dist = sl_price - price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        end_i = min(n - 1, entry_i + time_limit)
        for i in range(entry_i + 1, end_i + 1):
            if high[i] >= sl_price:
                return {"r": -1.0, "exit": "sl", "duration": i - entry_i}
        return {"r": (price - close[end_i]) / sl_dist, "exit": "time", "duration": end_i - entry_i}


def simulate_trail_after_2r(df: pd.DataFrame, entry_i: int, sl_buf: float, time_limit: int,
                            trail_distance_r: float, direction: str) -> dict:
    """Initial SL; при +2R активируем trail; time fallback."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    price = close[entry_i]
    if direction == "LONG":
        initial_sl = low[max(0, entry_i - SL_LOOKBACK):entry_i + 1].min() * (1 - sl_buf)
        sl_dist = price - initial_sl
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None

        sl_price = initial_sl
        peak = price
        end_i = min(n - 1, entry_i + time_limit)
        trail_active = False
        for i in range(entry_i + 1, end_i + 1):
            if high[i] > peak:
                peak = high[i]
            current_r = (peak - price) / sl_dist
            if not trail_active and current_r >= 2.0:
                trail_active = True
            if trail_active:
                new_sl = peak - trail_distance_r * sl_dist
                if new_sl > sl_price:
                    sl_price = new_sl
            if low[i] <= sl_price:
                return {"r": (sl_price - price) / sl_dist, "exit": "trail" if trail_active else "sl",
                        "duration": i - entry_i}
        return {"r": (close[end_i] - price) / sl_dist, "exit": "time", "duration": end_i - entry_i}
    else:
        initial_sl = high[max(0, entry_i - SL_LOOKBACK):entry_i + 1].max() * (1 + sl_buf)
        sl_dist = initial_sl - price
        if sl_dist <= 0 or sl_dist / price > 0.06:
            return None
        sl_price = initial_sl
        bottom = price
        end_i = min(n - 1, entry_i + time_limit)
        trail_active = False
        for i in range(entry_i + 1, end_i + 1):
            if low[i] < bottom:
                bottom = low[i]
            current_r = (price - bottom) / sl_dist
            if not trail_active and current_r >= 2.0:
                trail_active = True
            if trail_active:
                new_sl = bottom + trail_distance_r * sl_dist
                if new_sl < sl_price:
                    sl_price = new_sl
            if high[i] >= sl_price:
                return {"r": (price - sl_price) / sl_dist, "exit": "trail" if trail_active else "sl",
                        "duration": i - entry_i}
        return {"r": (price - close[end_i]) / sl_dist, "exit": "time", "duration": end_i - entry_i}


def collect_entries(anchor_factors: list, direction: str) -> list:
    """Returns list of (df_ref, entry_idx, sym)."""
    files = sorted(HISTORY_1H.glob("*.parquet"))
    entries = []

    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res

        mask = np.ones(len(flags), dtype=bool)
        for f in anchor_factors:
            if f not in flags.columns:
                mask = mask & False
                break
            mask &= flags[f].values
        if not mask.any():
            continue

        # Load OHLCV
        df = pd.read_parquet(path)
        df.columns = [c.lower() for c in df.columns]
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
            df = df.set_index("ts")
        df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()

        # Match indices (flags index may differ from df after dropna)
        common_idx = flags.index.intersection(df.index)
        if len(common_idx) == 0:
            continue
        df = df.loc[common_idx]
        mask_aligned = pd.Series(mask, index=flags.index).reindex(df.index, fill_value=False).values

        for i in np.where(mask_aligned)[0]:
            entries.append({"df_path": str(path), "entry_i": i, "sym": path.stem})

    return entries


def run_anchor_grid(anchor_id: str, anchor_cfg: dict):
    print(f"\n{'='*70}")
    print(f"Anchor: {anchor_id} ({anchor_cfg['direction']})")
    print(f"{'='*70}")

    t0 = time.time()
    entries = collect_entries(anchor_cfg["factors"], anchor_cfg["direction"])
    if not entries:
        print(f"  No entries")
        return None
    print(f"  Entries collected: {len(entries)} ({time.time()-t0:.0f}s)")

    direction = anchor_cfg["direction"]
    sl_buf = 0.001
    results = []

    # Cache DF per pair
    df_cache = {}
    def get_df(path):
        if path not in df_cache:
            df = pd.read_parquet(path)
            df.columns = [c.lower() for c in df.columns]
            if "ts" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
                df = df.set_index("ts")
            df_cache[path] = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
        return df_cache[path]

    # ─── (A) Static TP ─── × ─── (B) Time grid ───
    t1 = time.time()
    for tp_r in TP_R_GRID:
        for time_limit in TIME_EXIT_GRID:
            rs = []
            for ent in entries:
                df = get_df(ent["df_path"])
                if ent["entry_i"] >= len(df) - time_limit:
                    continue
                r = simulate_static_tp(df, ent["entry_i"], sl_buf, tp_r, time_limit, direction)
                if r is not None:
                    rs.append(r["r"])
            if len(rs) < 10:
                continue
            arr = np.array(rs)
            results.append({
                "strategy": f"static_tp_{tp_r}R_time_{time_limit}h",
                "tp_r": tp_r,
                "time_h": time_limit,
                "n": len(arr),
                "avgR": float(arr.mean()),
                "WR": float((arr > 0).mean() * 100),
                "sumR": float(arr.sum()),
                "maxR": float(arr.max()),
                "minR": float(arr.min()),
            })
    print(f"  Static TP grid: {len(TP_R_GRID) * len(TIME_EXIT_GRID)} combos | {time.time()-t1:.0f}s")

    # ─── No-trail × Time grid ───
    t1 = time.time()
    for time_limit in TIME_EXIT_GRID:
        rs = []
        for ent in entries:
            df = get_df(ent["df_path"])
            if ent["entry_i"] >= len(df) - time_limit:
                continue
            r = simulate_no_trail(df, ent["entry_i"], sl_buf, time_limit, direction)
            if r is not None:
                rs.append(r["r"])
        if len(rs) < 10:
            continue
        arr = np.array(rs)
        results.append({
            "strategy": f"no_trail_time_{time_limit}h",
            "tp_r": None,
            "time_h": time_limit,
            "n": len(arr),
            "avgR": float(arr.mean()),
            "WR": float((arr > 0).mean() * 100),
            "sumR": float(arr.sum()),
            "maxR": float(arr.max()),
            "minR": float(arr.min()),
        })
    print(f"  No-trail grid: {len(TIME_EXIT_GRID)} combos | {time.time()-t1:.0f}s")

    # ─── Trail after 2R × Time grid × Trail distance ───
    t1 = time.time()
    for trail_d in [1.0, 1.5, 2.0]:
        for time_limit in TIME_EXIT_GRID:
            rs = []
            for ent in entries:
                df = get_df(ent["df_path"])
                if ent["entry_i"] >= len(df) - time_limit:
                    continue
                r = simulate_trail_after_2r(df, ent["entry_i"], sl_buf, time_limit, trail_d, direction)
                if r is not None:
                    rs.append(r["r"])
            if len(rs) < 10:
                continue
            arr = np.array(rs)
            results.append({
                "strategy": f"trail_after_2R_d{trail_d}_time_{time_limit}h",
                "tp_r": None,
                "time_h": time_limit,
                "trail_distance_r": trail_d,
                "n": len(arr),
                "avgR": float(arr.mean()),
                "WR": float((arr > 0).mean() * 100),
                "sumR": float(arr.sum()),
                "maxR": float(arr.max()),
                "minR": float(arr.min()),
            })
    print(f"  Trail-after-2R: {3 * len(TIME_EXIT_GRID)} combos | {time.time()-t1:.0f}s")

    df_res = pd.DataFrame(results).sort_values("avgR", ascending=False)
    df_res["anchor_id"] = anchor_id

    out = OUTPUT_DIR / f"tp_exit_grid_{anchor_id}.csv"
    df_res.to_csv(out, index=False, encoding="utf-8")

    print(f"\n  TOP-15 strategies:")
    for _, r in df_res.head(15).iterrows():
        print(f"    {r['strategy']:<40} n={int(r['n']):>4} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}% sumR={r['sumR']:>+7.1f}")

    return df_res


def main():
    with register_run("tp_exit_grid", params={"anchors": list(ANCHORS.keys())}) as run:
        all_dfs = []
        for anchor_id, cfg in ANCHORS.items():
            df = run_anchor_grid(anchor_id, cfg)
            if df is not None:
                all_dfs.append(df)
                run.add_output(OUTPUT_DIR / f"tp_exit_grid_{anchor_id}.csv")

        if all_dfs:
            summary = pd.concat(all_dfs, ignore_index=True)
            sum_path = OUTPUT_DIR / "tp_exit_grid_summary.csv"
            summary.to_csv(sum_path, index=False, encoding="utf-8")
            run.add_output(sum_path)

            print(f"\n\n{'='*80}")
            print(f"GLOBAL TOP-20 (across all anchors)")
            print(f"{'='*80}")
            for _, r in summary.sort_values("avgR", ascending=False).head(20).iterrows():
                print(f"  {r['anchor_id']:<22} {r['strategy']:<40} n={int(r['n']):>4} "
                      f"avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%")


if __name__ == "__main__":
    main()
