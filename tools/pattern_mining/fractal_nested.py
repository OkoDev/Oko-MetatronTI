"""
DEV-223-v3 (Phase 2): FRACTAL Nested Patterns — концепция user 2026-05-20.

ИДЕЯ:
Не один HTF паттерн с 4 LTF entries (это было v2),
а 4 НЕЗАВИСИМЫХ "golden-like" паттернов — каждый на своём TF:

  Level 4h:  bull_div_4h + bull_fvg_1d + wt_os_1d    (самый редкий)
  Level 1h:  bull_div_1h + bull_fvg_4h + wt_os_4h    ← наш L1_golden
  Level 15m: bull_div_15m + bull_fvg_1h + wt_os_1h
  Level 5m:  bull_div_5m + bull_fvg_15m + wt_os_15m  (самый частый)

Каждая система:
  - Independent entry detection на своём TF
  - Independent SL/TP/exit
  - Может работать ОДНОВРЕМЕННО с другими TFs на одной паре
  - Compound effect: 4 систем = 4× больше сделок при том же edge

Output: data/research/2026-05-20--ph2/fractal_nested_*.csv
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
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph2"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Fractal levels — каждый собственный TF + reindex от соседних старших
# Формат: detection_tf, htf1_tf, htf2_tf — для bull_div, bull_fvg, wt_os respectively
FRACTAL_LEVELS = {
    "L_5m":  {"detection_tf": "5m",  "div_tf": "5m",  "fvg_tf": "15m", "wt_tf": "15m"},
    "L_15m": {"detection_tf": "15m", "div_tf": "15m", "fvg_tf": "1h",  "wt_tf": "1h"},
    "L_1h":  {"detection_tf": "1h",  "div_tf": "1d",  "fvg_tf": "4h",  "wt_tf": "4h"},   # = L1_golden
    "L_4h":  {"detection_tf": "4h",  "div_tf": "1d",  "fvg_tf": "1d",  "wt_tf": "1d"},
}

# Bars per time horizon = 24h
TIME_EXIT_BARS = {
    "5m": 288,   # 24h
    "15m": 96,   # 24h
    "1h": 24,    # 24h
    "4h": 6,     # 24h (короткое окно для медленного TF)
}

SL_LOOKBACK = 10


def load_tf(symbol: str, tf: str) -> pd.DataFrame:
    base = PROJECT_ROOT / "data" / "history" / tf
    path = base / f"{symbol}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
        df = df.set_index("ts")
    return df[["open", "high", "low", "close", "volume"]].dropna().sort_index()


def resample_to(df_1h: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    rule = {"4h": "4h", "1d": "1D"}[target_tf]
    return df_1h.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()


def build_anchor_mask_for_tf(symbol: str, level_cfg: dict) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Возвращает (df_detection_tf, mask) — где mask=True на барах detection_tf
    когда активны все три anchor factors (div, fvg, wt_os) на соответствующих TFs.
    """
    det_tf = level_cfg["detection_tf"]
    df_det = load_tf(symbol, det_tf)
    if df_det is None or len(df_det) < 200:
        return None, None

    # Загружаем helper TFs для других флагов
    # bull_div from div_tf
    div_tf = level_cfg["div_tf"]
    fvg_tf = level_cfg["fvg_tf"]
    wt_tf = level_cfg["wt_tf"]

    # Helper для compute flags на любом TF
    def get_flags(tf):
        if tf == det_tf:
            return cb.compute_flags(df_det, tf)
        # Load или resample
        if tf in ("5m", "15m", "1h"):
            dh = load_tf(symbol, tf)
        elif tf == "4h":
            df_1h_full = load_tf(symbol, "1h")
            dh = resample_to(df_1h_full, "4h") if df_1h_full is not None else None
        elif tf == "1d":
            df_1h_full = load_tf(symbol, "1h")
            dh = resample_to(df_1h_full, "1d") if df_1h_full is not None else None
        else:
            return None
        if dh is None or len(dh) < 30:
            return None
        return cb.compute_flags(dh, tf)

    # Compute flag arrays для каждого нужного TF
    div_flags = get_flags(div_tf)
    fvg_flags = get_flags(fvg_tf)
    wt_flags = get_flags(wt_tf)
    if div_flags is None or fvg_flags is None or wt_flags is None:
        return None, None

    div_col = f"bull_div_{div_tf}"
    fvg_col = f"bull_fvg_{fvg_tf}"
    wt_col = f"wt_os_{wt_tf}"

    for col, df_src in [(div_col, div_flags), (fvg_col, fvg_flags), (wt_col, wt_flags)]:
        if col not in df_src.columns:
            return None, None

    # Reindex helper TFs на detection grid (с lookahead-safe shift)
    def reindex_to_det(df_src, src_tf, target_idx):
        if src_tf == det_tf:
            return df_src.reindex(target_idx, method="ffill").fillna(False)
        # Shift index forward by 1 bar of src_tf
        shift = pd.Timedelta(
            {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}[src_tf]
        )
        df_shifted = df_src.copy()
        df_shifted.index = df_shifted.index + shift
        return df_shifted.reindex(target_idx, method="ffill").fillna(False)

    div_aligned = reindex_to_det(div_flags[[div_col]], div_tf, df_det.index)
    fvg_aligned = reindex_to_det(fvg_flags[[fvg_col]], fvg_tf, df_det.index)
    wt_aligned = reindex_to_det(wt_flags[[wt_col]], wt_tf, df_det.index)

    mask = (
        div_aligned[div_col].values.astype(bool)
        & fvg_aligned[fvg_col].values.astype(bool)
        & wt_aligned[wt_col].values.astype(bool)
    )
    return df_det, mask


def simulate_no_trail(df, entry_i, sl_lookback, time_bars):
    n = len(df)
    if entry_i < sl_lookback or entry_i + time_bars >= n:
        return None
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
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
    r = (end_price - price) / sl_dist
    return {"r": r, "exit": "time", "duration_bars": time_bars,
            "entry_price": price, "sl_dist_pct": sl_dist / price * 100}


def run_level(level_id: str, level_cfg: dict, symbols: list[str]) -> list[dict]:
    det_tf = level_cfg["detection_tf"]
    time_bars = TIME_EXIT_BARS[det_tf]
    results = []

    for sym in symbols:
        try:
            df, mask = build_anchor_mask_for_tf(sym, level_cfg)
        except Exception as e:
            continue
        if df is None or mask is None or not mask.any():
            continue

        trigger_indices = np.where(mask)[0]
        for i in trigger_indices:
            res = simulate_no_trail(df, i, SL_LOOKBACK, time_bars)
            if res is None:
                continue
            results.append({
                "level": level_id,
                "detection_tf": det_tf,
                "symbol": sym,
                "ts": df.index[i].isoformat(),
                "entry_price": res["entry_price"],
                "sl_dist_pct": res["sl_dist_pct"],
                "exit_r": res["r"],
                "exit_type": res["exit"],
                "duration_bars": res["duration_bars"],
            })

    return results


def main():
    with register_run("fractal_nested") as run:
        # Common symbols across all TFs (need 5m, 15m, 1h)
        syms_5m = {p.stem for p in (PROJECT_ROOT / "data" / "history" / "5m").glob("*.parquet")}
        syms_15m = {p.stem for p in (PROJECT_ROOT / "data" / "history" / "15m").glob("*.parquet")}
        syms_1h = {p.stem for p in (PROJECT_ROOT / "data" / "history" / "1h").glob("*.parquet")}
        common = sorted(syms_5m & syms_15m & syms_1h)
        print(f"Common symbols across all TF: {len(common)}")

        all_results = []
        for level_id, cfg in FRACTAL_LEVELS.items():
            print(f"\n{'='*70}")
            print(f"Level: {level_id} (detection_tf={cfg['detection_tf']})")
            print(f"Anchor: bull_div_{cfg['div_tf']} + bull_fvg_{cfg['fvg_tf']} + wt_os_{cfg['wt_tf']}")
            print(f"{'='*70}")
            t0 = time.time()
            level_results = run_level(level_id, cfg, common)
            print(f"  Entries: {len(level_results)} | {time.time()-t0:.0f}s")
            if level_results:
                rs = [r["exit_r"] for r in level_results]
                print(f"  avgR: {np.mean(rs):+.3f} | WR: {(np.array(rs)>0).mean()*100:.1f}% | sumR: {sum(rs):+.1f}")
            all_results.extend(level_results)

        if not all_results:
            print("\n❌ No fractal entries found")
            return

        df = pd.DataFrame(all_results)
        out = OUTPUT_DIR / "fractal_nested.csv"
        df.to_csv(out, index=False, encoding="utf-8")
        run.add_output(out)

        # Aggregate stats
        print(f"\n{'='*80}")
        print(f"FRACTAL NESTED STATISTICS — TOTAL")
        print(f"{'='*80}")
        print(f"\nTotal entries: {len(df)}")
        print(f"Total R: {df['exit_r'].sum():+.1f}")
        print(f"Avg R: {df['exit_r'].mean():+.3f}")
        print(f"Overall WR: {(df['exit_r'] > 0).mean() * 100:.1f}%")

        print(f"\n=== Per-level breakdown ===")
        print(f"{'level':<7} {'n':>6} {'avgR':>8} {'WR':>6} {'sumR':>9} {'avg_dur_bars':>13}")
        for lev in ["L_5m", "L_15m", "L_1h", "L_4h"]:
            sub = df[df["level"] == lev]
            if not len(sub):
                continue
            print(f"{lev:<7} {len(sub):>6} {sub['exit_r'].mean():>+8.3f} "
                  f"{(sub['exit_r']>0).mean()*100:>5.1f}% {sub['exit_r'].sum():>+9.1f} "
                  f"{sub['duration_bars'].mean():>13.1f}")

        # Concurrent positions per pair
        df["ts_dt"] = pd.to_datetime(df["ts"], utc=True)
        df = df.sort_values(["symbol", "ts_dt"])

        print(f"\n=== Concurrent positions analysis ===")
        # Для каждой пары + времени — сколько level overlap
        # Грубо: group by sym + date hour
        df["hour_bucket"] = df["ts_dt"].dt.floor("4h")
        concur = df.groupby(["symbol", "hour_bucket"])["level"].nunique().reset_index()
        concur.columns = ["symbol", "hour_bucket", "n_concurrent_levels"]

        for n_lev in [1, 2, 3, 4]:
            cnt = (concur["n_concurrent_levels"] == n_lev).sum()
            print(f"  {n_lev} concurrent levels: {cnt} events")

        # Top symbols by total R
        print(f"\n=== TOP-10 symbols by total R ===")
        sym_totals = df.groupby("symbol").agg(
            n=("exit_r", "count"),
            total_r=("exit_r", "sum"),
            avg_r=("exit_r", "mean"),
        ).sort_values("total_r", ascending=False).head(10)
        for sym, row in sym_totals.iterrows():
            print(f"  {sym:<18} n={int(row['n']):>4} total_R={row['total_r']:>+7.1f} avgR={row['avg_r']:>+.3f}")


if __name__ == "__main__":
    main()
