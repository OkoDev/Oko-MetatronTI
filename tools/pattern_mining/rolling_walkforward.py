"""
DEV-250 (Phase 5): Rolling Walk-Forward на 6 cutoffs.

Берёт топ-устойчивых паттернов и проверяет stability на 6 различных
train/test разбивках с шагом 60 дней. Pattern stable если pass ≥5/6.

Cutoffs (60-day step):
  2024-12-01, 2025-02-01, 2025-04-01, 2025-06-01, 2025-08-01, 2025-10-01

Pattern stable per cutoff:
  - n_test ≥ 10
  - avgR_test > 0
  - WR_test > 50

Output: data/research/2026-05-20--ph5/rolling_walkforward.csv
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
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph5"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Берём MHT-passed паттерны (12002 из них)
MHT_INPUT = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1" / "walkforward_full_mht.csv"

# 6 cutoffs шагом 60 дней
CUTOFFS = [
    pd.Timestamp("2024-12-01", tz="UTC"),
    pd.Timestamp("2025-02-01", tz="UTC"),
    pd.Timestamp("2025-04-01", tz="UTC"),
    pd.Timestamp("2025-06-01", tz="UTC"),
    pd.Timestamp("2025-08-01", tz="UTC"),
    pd.Timestamp("2025-10-01", tz="UTC"),
]

TOP_N_PATTERNS = 100   # топ-100 из MHT
MIN_N_TEST = 10


def evaluate_pattern_at_cutoff(flags_dict, factors, direction, cutoff):
    """Compute train/test stats at a given cutoff."""
    tr_rs = []
    te_rs = []
    for sym, (flags, r_long, r_short) in flags_dict.items():
        mask = np.ones(len(flags), dtype=bool)
        skip = False
        for f in factors:
            if f not in flags.columns:
                skip = True
                break
            mask &= flags[f].values
        if skip or not mask.any():
            continue

        rs = r_long if direction == "LONG" else r_short
        idx = flags.index
        cmp_tr = idx < cutoff
        cmp_te = idx >= cutoff
        if hasattr(cmp_tr, "values"):
            cmp_tr = cmp_tr.values
            cmp_te = cmp_te.values
        tr_mask = mask & np.asarray(cmp_tr) & ~np.isnan(rs)
        te_mask = mask & np.asarray(cmp_te) & ~np.isnan(rs)
        tr_rs.extend(rs[tr_mask].tolist())
        te_rs.extend(rs[te_mask].tolist())

    if len(tr_rs) < 20 or len(te_rs) < MIN_N_TEST:
        return None

    tr_arr = np.array(tr_rs)
    te_arr = np.array(te_rs)
    return {
        "tr_n": len(tr_arr),
        "tr_avgR": float(tr_arr.mean()),
        "tr_WR": float((tr_arr > 0).mean() * 100),
        "te_n": len(te_arr),
        "te_avgR": float(te_arr.mean()),
        "te_WR": float((te_arr > 0).mean() * 100),
        "pass": (te_arr.mean() > 0) and ((te_arr > 0).mean() > 0.5),
    }


def main():
    with register_run("rolling_walkforward", params={"cutoffs": [str(c.date()) for c in CUTOFFS]}) as run:
        # Load top patterns
        if not MHT_INPUT.exists():
            print(f"❌ MHT input missing: {MHT_INPUT}")
            return

        mht_df = pd.read_csv(MHT_INPUT)
        top = mht_df.sort_values("composite_score", ascending=False).head(TOP_N_PATTERNS)
        print(f"Loaded top-{len(top)} patterns from MHT-passed")

        # Load all data
        print("Loading history...")
        t0 = time.time()
        flags_dict = {}
        for path in sorted(HISTORY_1H.glob("*.parquet")):
            res = cb.process_symbol(path)
            if res is None:
                continue
            flags_dict[path.stem] = res
        print(f"  {len(flags_dict)} pairs loaded ({time.time()-t0:.0f}s)")

        # Evaluate each pattern at each cutoff
        results = []
        for i, row in top.iterrows():
            pattern = row["pattern"]
            direction = row["direction"]
            factors = tuple(f.strip() for f in pattern.split(" + "))

            pass_count = 0
            cutoff_stats = {}
            for cutoff in CUTOFFS:
                stats = evaluate_pattern_at_cutoff(flags_dict, factors, direction, cutoff)
                if stats:
                    cutoff_stats[str(cutoff.date())] = stats
                    if stats["pass"]:
                        pass_count += 1

            results.append({
                "pattern": pattern,
                "direction": direction,
                "n_cutoffs_evaluated": len(cutoff_stats),
                "n_passed": pass_count,
                "pass_ratio": pass_count / max(1, len(cutoff_stats)),
                "is_stable_rolling": pass_count >= 5,
                "avg_test_avgR": np.mean([s["te_avgR"] for s in cutoff_stats.values()]) if cutoff_stats else 0,
                "avg_test_WR": np.mean([s["te_WR"] for s in cutoff_stats.values()]) if cutoff_stats else 0,
            })

            if (i + 1) % 20 == 0:
                stable_so_far = sum(1 for r in results if r["is_stable_rolling"])
                print(f"  ...{i+1}/{len(top)} | stable so far: {stable_so_far}")

        df_res = pd.DataFrame(results).sort_values("pass_ratio", ascending=False)

        out = OUTPUT_DIR / "rolling_walkforward.csv"
        df_res.to_csv(out, index=False, encoding="utf-8")
        run.add_output(out)

        stable = df_res[df_res["is_stable_rolling"]]
        print(f"\n{'='*70}")
        print(f"ROLLING WALK-FORWARD SUMMARY")
        print(f"{'='*70}")
        print(f"Evaluated: {len(df_res)}")
        print(f"Stable (pass ≥5/6): {len(stable)}")
        print(f"Robust (pass = 6/6): {(df_res['n_passed'] == 6).sum()}")

        print(f"\nTOP-20 stable patterns:")
        for _, r in stable.head(20).iterrows():
            pat = r["pattern"][:60] + ("…" if len(r["pattern"]) > 60 else "")
            print(f"  {r['direction']:<5} pass {r['n_passed']}/6 avgR={r['avg_test_avgR']:>+.3f} WR={r['avg_test_WR']:>4.1f}%  {pat}")


if __name__ == "__main__":
    main()
