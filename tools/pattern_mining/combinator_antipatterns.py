"""
DEV-212: Anti-patterns mining (kill-switches).

Подход: берём топ-валидированных паттернов (golden, premium_short),
смотрим где они LOSS на test (R<0). Затем ищем какие LTF/контекст-факторы
**сильно различают win/loss подмножества** — это kill-switches.

Метод:
1. Для каждого top-anchor собираем все trades (win + loss)
2. Для каждого LTF/контекст factor вычисляем:
   - WR_when_factor_TRUE vs WR_when_factor_FALSE
   - Significant gap → kill_factor (если факт=True убивает WR)
3. Output: список kill_factors с эффект-сайзом

Output: data/research/2026-05-20--ph1/antipatterns_v1.csv
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

import math
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Топ-якоря для анализа (LONG)
ANCHORS = {
    "golden_long": {
        "factors": ["bull_div_1d", "bull_fvg_4h", "wt_os_4h"],
        "direction": "LONG",
    },
    "wt_double_long": {
        "factors": ["wt_os_1d", "bull_fvg_4h", "wt_os_1h"],
        "direction": "LONG",
    },
    "premium_short": {
        "factors": ["atr_cross_down_1d", "bear_bos_1d", "premium_4h"],
        "direction": "SHORT",
    },
}

MIN_N_LOSSES = 5    # минимум LOSS-trades для надёжной оценки kill_factor


def collect_anchor_trades(anchor_factors: list, direction: str) -> list:
    """Возвращает список (timestamp, sym, factors_dict, r_value) для всех triggers anchor."""
    files = sorted(HISTORY_1H.glob("*.parquet"))
    trades = []

    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res

        # Anchor mask
        mask = np.ones(len(flags), dtype=bool)
        for f in anchor_factors:
            if f not in flags.columns:
                mask = mask & False
                break
            mask &= flags[f].values
        if not mask.any():
            continue

        rs = r_long if direction == "LONG" else r_short
        valid_idx = np.where(mask & ~np.isnan(rs))[0]
        if len(valid_idx) == 0:
            continue

        flag_cols = flags.columns.tolist()
        flag_arr = flags.values
        for i in valid_idx:
            row_flags = {col: bool(flag_arr[i, j]) for j, col in enumerate(flag_cols)}
            trades.append({
                "sym": path.stem,
                "ts": flags.index[i],
                "r": float(rs[i]),
                "flags": row_flags,
            })

    return trades


def find_kill_factors(trades: list, base_win_rate: float) -> pd.DataFrame:
    """Для каждого LTF/контекст-фактора смотрим как меняется WR при factor=TRUE."""
    if not trades:
        return pd.DataFrame()

    # Все факторы (берём из первой trade)
    all_factors = list(trades[0]["flags"].keys())

    # Не интересны те факторы которые входят в anchor (они всегда TRUE)
    candidate_factors = [f for f in all_factors if not all(t["flags"].get(f, False) for t in trades)]

    results = []
    for factor in candidate_factors:
        true_rs = [t["r"] for t in trades if t["flags"].get(factor, False)]
        false_rs = [t["r"] for t in trades if not t["flags"].get(factor, False)]

        if len(true_rs) < MIN_N_LOSSES or len(false_rs) < MIN_N_LOSSES:
            continue

        wr_true = sum(1 for r in true_rs if r > 0) / len(true_rs)
        wr_false = sum(1 for r in false_rs if r > 0) / len(false_rs)
        avgr_true = sum(true_rs) / len(true_rs)
        avgr_false = sum(false_rs) / len(false_rs)

        wr_gap = wr_true - wr_false
        avgr_gap = avgr_true - avgr_false

        # Kill factor: factor=TRUE → WR падает (gap<0) И avgR падает
        is_kill = (wr_gap < -0.15) and (avgr_gap < -0.5)
        # Boost factor: factor=TRUE → WR растёт (gap>0) И avgR растёт
        is_boost = (wr_gap > +0.15) and (avgr_gap > +0.5)

        results.append({
            "factor": factor,
            "n_true": len(true_rs),
            "n_false": len(false_rs),
            "wr_true": round(wr_true * 100, 1),
            "wr_false": round(wr_false * 100, 1),
            "wr_gap_pct": round(wr_gap * 100, 1),
            "avgR_true": round(avgr_true, 3),
            "avgR_false": round(avgr_false, 3),
            "avgR_gap": round(avgr_gap, 3),
            "is_kill_switch": is_kill,
            "is_boost_factor": is_boost,
        })

    df = pd.DataFrame(results)
    if len(df):
        df = df.sort_values("avgR_gap")
    return df


def main():
    with register_run("combinator_antipatterns", params={"anchors": list(ANCHORS.keys())}) as run:
        all_results = []

        for anchor_id, cfg in ANCHORS.items():
            print(f"\n{'='*80}")
            print(f"Anchor: {anchor_id} ({cfg['direction']})")
            print(f"Factors: {' + '.join(cfg['factors'])}")
            print(f"{'='*80}")

            t0 = time.time()
            trades = collect_anchor_trades(cfg["factors"], cfg["direction"])
            print(f"  Trades collected: {len(trades)} ({time.time()-t0:.0f}s)")

            if len(trades) < 30:
                print(f"  ❌ Too few trades, skip")
                continue

            base_wr = sum(1 for t in trades if t["r"] > 0) / len(trades)
            base_avgr = sum(t["r"] for t in trades) / len(trades)
            print(f"  Base WR: {base_wr*100:.1f}%, base avgR: {base_avgr:+.3f}")

            t0 = time.time()
            df = find_kill_factors(trades, base_wr)
            print(f"  Kill/boost analysis: {len(df)} factors checked ({time.time()-t0:.0f}s)")

            if df.empty:
                continue

            df["anchor_id"] = anchor_id

            # Top-15 kill switches
            kills = df[df["is_kill_switch"]].head(15)
            boosts = df[df["is_boost_factor"]].tail(15)

            print(f"\n  🔴 TOP-10 KILL-SWITCHES (factor=TRUE → стрелочка вниз):")
            for _, r in kills.head(10).iterrows():
                print(f"    {r['factor']:<35} n_T={r['n_true']:>4} WR={r['wr_true']:>5.1f}% (gap {r['wr_gap_pct']:>+5.1f}%) "
                      f"avgR={r['avgR_true']:>+.3f} (gap {r['avgR_gap']:>+.3f})")

            print(f"\n  🟢 TOP-10 BOOST FACTORS (factor=TRUE → стрелочка вверх):")
            for _, r in boosts.iloc[::-1].head(10).iterrows():
                print(f"    {r['factor']:<35} n_T={r['n_true']:>4} WR={r['wr_true']:>5.1f}% (gap {r['wr_gap_pct']:>+5.1f}%) "
                      f"avgR={r['avgR_true']:>+.3f} (gap {r['avgR_gap']:>+.3f})")

            all_results.append(df)

        if all_results:
            full = pd.concat(all_results, ignore_index=True)
            out = OUTPUT_DIR / "antipatterns_v1.csv"
            full.to_csv(out, index=False, encoding="utf-8")
            run.add_output(out)
            print(f"\n✅ Сохранено: {out} ({len(full)} rows)")


if __name__ == "__main__":
    main()
