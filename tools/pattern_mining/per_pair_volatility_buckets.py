"""
DEV-214d-A: Volatility-bucket классификация 46 пар.

Шаг 1 для per-pair indicator tuning (D-016):
  - Считаем median_ATR_norm на 90 дней для каждой пары
  - Кластеризуем в 5 buckets: very_low / low / mid / high / micro
  - Output: config/pair_volatility_buckets.yaml

После этого шага DEV-214d-B будет запускать Optuna для каждого bucket.
"""
from __future__ import annotations

import sys
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


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Percentile-based boundaries (вычисляются динамически в main())
# Это даёт ~равное распределение по 5 buckets
BUCKET_NAMES = ["very_low_vol", "low_vol", "mid_vol", "high_vol", "micro_vol"]
BUCKETS = []   # будет заполнено в main()


def compute_atr_norm(path: Path, period: int = 14, n_bars: int = 2160) -> float:
    """Median ATR / close за последние n_bars (90 дней × 24h = 2160)."""
    try:
        df = pd.read_parquet(path)
        df.columns = [c.lower() for c in df.columns]
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True, errors="coerce")
            df = df.set_index("ts")
        df = df[["open", "high", "low", "close"]].dropna().tail(n_bars)
        if len(df) < 100:
            return float("nan")

        h, l, c = df["high"].values, df["low"].values, df["close"].values
        tr = np.maximum.reduce([
            h - l,
            np.abs(h - np.roll(c, 1)),
            np.abs(l - np.roll(c, 1)),
        ])
        tr[0] = h[0] - l[0]
        atr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
        atr_norm = atr / c * 100
        return float(np.median(atr_norm))
    except Exception as e:
        print(f"  ERR {path.stem}: {e}")
        return float("nan")


def assign_bucket(atr_norm: float) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= atr_norm < hi:
            return name
    return "unknown"


def main():
    global BUCKETS
    with register_run("per_pair_volatility_buckets", params={"period": 14, "n_bars": 2160}) as run:
        files = sorted(HISTORY_1H.glob("*.parquet"))
        print(f"Анализирую {len(files)} пар...")

        results = []
        for path in files:
            atr_norm = compute_atr_norm(path)
            results.append({"symbol": path.stem, "atr_norm_pct": atr_norm})

        df_raw = pd.DataFrame(results)
        # Исключаем NaN и suspicious zeros
        df_valid = df_raw[(df_raw["atr_norm_pct"] > 0.1) & (~df_raw["atr_norm_pct"].isna())].copy()
        df_invalid = df_raw[~df_raw.index.isin(df_valid.index)].copy()

        # Percentile-based boundaries (5 равных buckets)
        percentiles = [0, 20, 40, 60, 80, 100]
        boundaries = [np.percentile(df_valid["atr_norm_pct"], p) for p in percentiles]
        boundaries[0] = 0
        boundaries[-1] = 1000   # верхняя граница без лимита

        BUCKETS = []
        for i, name in enumerate(BUCKET_NAMES):
            BUCKETS.append((name, boundaries[i], boundaries[i+1]))

        print(f"\nDynamic boundaries (percentile-based):")
        for name, lo, hi in BUCKETS:
            print(f"  {name:<15} [{lo:.3f}-{hi:.3f}%]")

        # Назначение buckets
        def assign(atr):
            if np.isnan(atr) or atr <= 0.1:
                return "invalid_data"
            for name, lo, hi in BUCKETS:
                if lo <= atr < hi:
                    return name
            return "unknown"

        df_raw["bucket"] = df_raw["atr_norm_pct"].apply(assign)
        df = df_raw.sort_values("atr_norm_pct")

        print(f"\n{'='*70}")
        print(f"{'Symbol':<18} {'ATR_norm %':>11} {'Bucket':<15}")
        print(f"{'='*70}")
        for _, r in df.iterrows():
            print(f"{r['symbol']:<18} {r['atr_norm_pct']:>11.3f} {r['bucket']:<15}")

        # Stats per bucket
        print(f"\n{'='*70}")
        print(f"Bucket distribution:")
        for bucket_name, lo, hi in BUCKETS:
            in_bucket = df[df["bucket"] == bucket_name]
            symbols = list(in_bucket["symbol"].values)
            print(f"  {bucket_name:<15} [{lo:.1f}-{hi:.1f}%]: n={len(symbols):>2} | {', '.join(symbols[:8])}{('...' if len(symbols)>8 else '')}")

        # Save CSV
        out_csv = OUTPUT_DIR / "pair_volatility_buckets.csv"
        df.to_csv(out_csv, index=False, encoding="utf-8")
        run.add_output(out_csv)

        # Save YAML config
        out_yaml = PROJECT_ROOT / "config" / "pair_volatility_buckets.yaml"
        out_yaml.parent.mkdir(exist_ok=True)
        with open(out_yaml, "w", encoding="utf-8") as f:
            f.write("# Auto-generated per-pair volatility bucket assignment\n")
            f.write("# Source: tools/pattern_mining/per_pair_volatility_buckets.py\n")
            f.write("# Bucket boundaries (ATR_norm % on 1h, EMA-14):\n")
            for name, lo, hi in BUCKETS:
                f.write(f"#   {name}: [{lo:.1f}-{hi:.1f}%]\n")
            f.write("\nbuckets:\n")
            for bucket_name, _, _ in BUCKETS:
                in_bucket = df[df["bucket"] == bucket_name]
                f.write(f"  {bucket_name}:\n")
                f.write(f"    symbols:\n")
                for s in in_bucket["symbol"].values:
                    f.write(f"      - {s}\n")
        print(f"\n✅ Saved:\n  {out_csv}\n  {out_yaml}")


if __name__ == "__main__":
    main()
