"""
DEV-213: Composite Scoring 0-100 (вместо binary AND).

Идея: вместо требования ВСЕХ factors=True, считаем взвешенный score.
Weights определяются по avgR влияния каждого factor (из walkforward_full).

Score = sum(weight_i × factor_i_TRUE) → нормализовано 0-100.
Entry threshold = 60 (тестируемый).

Output:
  data/research/2026-05-20--ph1/composite_scoring_v1.csv
  models/composite_weights.json (для production)
"""
from __future__ import annotations

import sys
import time
import warnings
import json
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
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-05-20--ph1"
WF_RESULTS = OUTPUT_DIR / "walkforward_full.csv"

MIN_FACTOR_N = 200  # min trades per factor для считать веса
THRESHOLDS = [40, 50, 60, 70, 80]  # candidate entry thresholds


def collect_per_factor_stats():
    """Для каждого LTF/HTF factor считаем avgR_when_TRUE на всех trades.
    Используется как weight для composite score."""
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"Сбор per-factor stats на {len(files)} парах...")

    all_factor_stats = {"LONG": {}, "SHORT": {}}
    all_factor_counts = {"LONG": {}, "SHORT": {}}

    for i, path in enumerate(files):
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res
        flag_cols = flags.columns.tolist()
        flag_arr = flags.values

        for direction, rs in [("LONG", r_long), ("SHORT", r_short)]:
            valid_mask = ~np.isnan(rs)
            if not valid_mask.any():
                continue

            for j, col in enumerate(flag_cols):
                # Trades где factor=TRUE
                factor_mask = flag_arr[:, j].astype(bool) & valid_mask
                if not factor_mask.any():
                    continue
                rs_factor = rs[factor_mask]
                if col not in all_factor_stats[direction]:
                    all_factor_stats[direction][col] = []
                    all_factor_counts[direction][col] = 0
                all_factor_stats[direction][col].extend(rs_factor.tolist())
                all_factor_counts[direction][col] += len(rs_factor)

        if (i + 1) % 10 == 0:
            print(f"  ...{i+1}/{len(files)}")

    # Aggregate
    weights = {"LONG": {}, "SHORT": {}}
    stats_records = []
    for direction in ["LONG", "SHORT"]:
        for factor, rs_list in all_factor_stats[direction].items():
            n = len(rs_list)
            if n < MIN_FACTOR_N:
                continue
            arr = np.array(rs_list)
            avg_r = float(arr.mean())
            wr = float((arr > 0).mean() * 100)
            # Weight = avgR (можно положительный или отрицательный)
            # Clamp [-1, 1] — потом нормализуем
            weight = max(-1.0, min(1.0, avg_r))
            weights[direction][factor] = weight
            stats_records.append({
                "direction": direction,
                "factor": factor,
                "n": n,
                "avgR": avg_r,
                "WR": wr,
                "weight_raw": weight,
            })

    return weights, pd.DataFrame(stats_records)


def normalize_weights_to_100(weights: dict) -> dict:
    """Положительные веса нормализуем так чтобы max=1.0 → max possible score = 100.
    Отрицательные веса оставляем как есть (это penalty)."""
    normalized = {"LONG": {}, "SHORT": {}}
    for direction in weights:
        positives = [w for w in weights[direction].values() if w > 0]
        if not positives:
            normalized[direction] = weights[direction]
            continue
        max_pos = max(positives)
        scale = 100 / sum(sorted(positives, reverse=True)[:5])  # top-5 positive sum → 100
        for f, w in weights[direction].items():
            normalized[direction][f] = round(w * scale, 2)
    return normalized


def evaluate_composite_score(weights: dict, threshold_grid: list):
    """Для каждого threshold вычисляем performance:
    - n_trades
    - avgR
    - WR
    - sumR
    """
    files = sorted(HISTORY_1H.glob("*.parquet"))
    print(f"\nОценка thresholds {threshold_grid} на {len(files)} парах...")

    results = []

    for direction in ["LONG", "SHORT"]:
        w_dict = weights[direction]
        factor_list = list(w_dict.keys())
        weight_vec = np.array([w_dict[f] for f in factor_list])

        for path in files:
            res = cb.process_symbol(path)
            if res is None:
                continue
            flags, r_long, r_short = res

            rs = r_long if direction == "LONG" else r_short
            valid = ~np.isnan(rs)
            if not valid.any():
                continue

            # Извлекаем только нужные factors
            try:
                factor_arr = flags[factor_list].values.astype(np.float32)
            except KeyError:
                # Какие-то factors отсутствуют — пропускаем
                missing = set(factor_list) - set(flags.columns)
                if missing:
                    continue

            # Score для каждой строки = sum(weights × factor)
            scores = factor_arr @ weight_vec
            for threshold in threshold_grid:
                mask = (scores >= threshold) & valid
                if not mask.any():
                    continue
                rs_passed = rs[mask]
                # Сохраним per-pair-per-threshold
                results.append({
                    "direction": direction,
                    "threshold": threshold,
                    "symbol": path.stem,
                    "n": len(rs_passed),
                    "avgR": float(rs_passed.mean()),
                    "sumR": float(rs_passed.sum()),
                    "WR": float((rs_passed > 0).mean() * 100),
                })

    return pd.DataFrame(results)


def main():
    with register_run("composite_scoring_v1", params={"thresholds": THRESHOLDS}) as run:
        # Step 1: per-factor weights
        weights_raw, factor_stats = collect_per_factor_stats()
        weights_norm = normalize_weights_to_100(weights_raw)

        # Save weights
        weights_path = PROJECT_ROOT / "models" / "composite_weights.json"
        weights_path.parent.mkdir(exist_ok=True)
        with open(weights_path, "w", encoding="utf-8") as f:
            json.dump({
                "weights_raw": weights_raw,
                "weights_normalized": weights_norm,
                "thresholds": THRESHOLDS,
                "min_factor_n": MIN_FACTOR_N,
            }, f, indent=2, ensure_ascii=False)
        run.add_output(weights_path)

        # Save per-factor stats
        factor_stats_path = OUTPUT_DIR / "composite_factor_stats.csv"
        factor_stats.to_csv(factor_stats_path, index=False, encoding="utf-8")
        run.add_output(factor_stats_path)

        print(f"\n📊 Weights summary:")
        for direction in ["LONG", "SHORT"]:
            top_pos = sorted([(w, f) for f, w in weights_norm[direction].items() if w > 0], reverse=True)[:10]
            top_neg = sorted([(w, f) for f, w in weights_norm[direction].items() if w < 0])[:10]
            print(f"\n  {direction} top-10 POSITIVE weights:")
            for w, f in top_pos:
                print(f"    {f:<32} {w:>+7.2f}")
            print(f"\n  {direction} top-10 NEGATIVE weights:")
            for w, f in top_neg:
                print(f"    {f:<32} {w:>+7.2f}")

        # Step 2: evaluate composite at different thresholds
        eval_df = evaluate_composite_score(weights_norm, THRESHOLDS)
        eval_path = OUTPUT_DIR / "composite_scoring_v1.csv"
        eval_df.to_csv(eval_path, index=False, encoding="utf-8")
        run.add_output(eval_path)

        # Agg by direction × threshold
        print(f"\n📊 Composite Scoring performance (agg по парам):")
        agg = eval_df.groupby(["direction", "threshold"]).agg(
            n_total=("n", "sum"),
            avgR_weighted=("avgR", lambda x: float(np.average(x, weights=eval_df.loc[x.index, "n"]))),
            WR_weighted=("WR", lambda x: float(np.average(x, weights=eval_df.loc[x.index, "n"]))),
            sumR_total=("sumR", "sum"),
        ).reset_index()

        print(f"\n  {'dir':<6} {'thr':>4} {'n_total':>8} {'avgR':>7} {'WR':>6} {'sumR':>9}")
        for _, r in agg.iterrows():
            print(f"  {r['direction']:<6} {int(r['threshold']):>4} {int(r['n_total']):>8} "
                  f"{r['avgR_weighted']:>+7.3f} {r['WR_weighted']:>5.1f}% {r['sumR_total']:>+9.1f}")

        print(f"\n✅ DEV-213 COMPLETED")
        print(f"  Weights: {weights_path}")
        print(f"  Eval:    {eval_path}")


if __name__ == "__main__":
    main()
