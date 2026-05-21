"""
DEV-240 (Phase 4): Adjustments на commission + slippage + funding.

Берёт результаты Phase 2 (tp_exit_grid) и применяет реальные costs BingX:
  - Taker commission: 0.04% × 2 (entry + exit) × leverage
  - Slippage: 0.02-0.05% per entry/exit
  - Funding: avg 0.01%/8h × held_hours / 8

Output: data/research/2026-05-20--ph4/realistic_adjusted.csv
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
INPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph2"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph4"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# BingX futures realistic costs
TAKER_COMMISSION = 0.0004    # 0.04%
SLIPPAGE_PCT = 0.0003        # 0.03% per fill (entry + exit = 0.06%)
FUNDING_AVG_PER_8H = 0.0001  # 0.01% avg


def adjust_r_for_costs(avgR: float, leverage: int, time_h: float, sl_dist_pct: float = 2.0):
    """Adjust avgR для real-world costs.

    avgR — R-multiple на основе SL_distance
    leverage — позиционный leverage
    time_h — среднее время удержания

    Total costs as %:
      commission = TAKER × 2 (entry+exit)
      slippage = SLIPPAGE × 2
      funding = FUNDING_AVG × time_h / 8

    Costs в R-multiples: total_pct / (sl_dist_pct × leverage)
    Wait — leverage не влияет на R, оно влияет на $-PnL. R это (price_move / sl_dist).
    Для costs in R: costs_pct / sl_dist_pct
    """
    total_pct = (TAKER_COMMISSION * 2 + SLIPPAGE_PCT * 2 + FUNDING_AVG_PER_8H * time_h / 8) * 100
    cost_in_r = total_pct / sl_dist_pct  # SL distance in %, costs in %
    return avgR - cost_in_r, cost_in_r


def main():
    with register_run("realistic_costs") as run:
        input_file = INPUT_DIR / "tp_exit_grid_summary.csv"
        if not input_file.exists():
            print(f"❌ Phase 2 results not ready: {input_file}")
            print("   Run tp_exit_grid.py first")
            return

        df = pd.read_csv(input_file)
        print(f"Loaded {len(df)} strategies × anchors")

        # Apply adjustments
        # Assume avg leverage 5x, sl_distance 2%
        ADJ_LEVERAGE = 5
        ADJ_SL_DIST_PCT = 2.0

        df["cost_in_r"] = df.apply(
            lambda r: adjust_r_for_costs(r["avgR"], ADJ_LEVERAGE, r.get("time_h", 24), ADJ_SL_DIST_PCT)[1],
            axis=1
        )
        df["avgR_adjusted"] = df["avgR"] - df["cost_in_r"]
        df["sumR_adjusted"] = df["avgR_adjusted"] * df["n"]
        df["passes_realism"] = df["avgR_adjusted"] > 0.6

        # Save
        out = OUTPUT_DIR / "realistic_adjusted.csv"
        df.sort_values("avgR_adjusted", ascending=False).to_csv(out, index=False, encoding="utf-8")
        run.add_output(out)

        # Stats
        print(f"\nAvg cost in R: {df['cost_in_r'].mean():.3f}")
        print(f"Strategies passing realism (avgR_adj > 0.6): {df['passes_realism'].sum()} / {len(df)}")

        print(f"\n{'='*80}")
        print(f"TOP-20 after realistic adjustments")
        print(f"{'='*80}")
        for _, r in df.sort_values("avgR_adjusted", ascending=False).head(20).iterrows():
            print(f"  {r['anchor_id']:<22} {r['strategy']:<40} n={int(r['n']):>4} "
                  f"avgR_orig={r['avgR']:>+.3f} cost={r['cost_in_r']:>.3f} avgR_adj={r['avgR_adjusted']:>+.3f}")


if __name__ == "__main__":
    main()
