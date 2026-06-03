"""
DEV-210 + DEV-210b: Walk-Forward на ВСЕХ паттернах из combinator_v2 (22 835)
с применением MHT correction (Benjamini-Hochberg FDR).

Параллельный через multiprocessing.Pool (CPU N_jobs).

Output:
  data/research/2026-05-20--ph1/walkforward_full.csv
  data/research/2026-05-20--ph1/walkforward_full_mht.csv (с adjusted p-values)

Воспроизводимость через _run_registry.
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

from multiprocessing import Pool, cpu_count
import numpy as np
import pandas as pd
import math

sys.path.insert(0, str(Path(__file__).parent))
from _run_registry import register_run
import combinator_v2 as cb


def _student_t_sf(t: float, df: int) -> float:
    """One-sided survival function P(T > t) for Student-t distribution.
    Approximation via Welch-Satterthwaite — точно для df>5."""
    if df < 2:
        return 0.5
    # Numerical integration via Student-t CDF approximation
    x = df / (df + t * t)
    # Regularized incomplete beta function I(x; df/2, 1/2)
    # Используем approx через normal для df > 30, иначе формулу
    if df > 30:
        # Normal approximation
        from math import erfc, sqrt
        return 0.5 * erfc(t / sqrt(2))
    # Series expansion для small df
    a = df / 2.0
    b = 0.5
    # Бета-функция через лог-гамму
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    # I_x(a, b) — incomplete beta. Используем continued fraction expansion для x in [0,1]
    # Простой fallback: численная интеграция
    n_steps = 100
    dx = x / n_steps
    integral = 0.0
    for i in range(n_steps):
        xi = (i + 0.5) * dx
        if xi <= 0 or xi >= 1:
            continue
        integral += (xi ** (a - 1)) * ((1 - xi) ** (b - 1)) * dx
    p = math.exp(math.log(max(integral, 1e-300)) - log_beta) / 2.0
    return min(max(p, 0.0), 1.0)

# Override MIN_N для walk-forward (делим выборку 2x)
cb.MIN_N = 20

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data" / "history" / "1h"
INPUT_CSV = PROJECT_ROOT / "data" / "research" / "2026-06-03--ds315" / "combinator_v2_results.csv"
OUTPUT_DIR = PROJECT_ROOT / "data" / "research" / "2026-06-03--ds315"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2026-03-01", tz="UTC")
MIN_N_TRAIN = 30


# ────────────────────────── Глобальное состояние для воркеров ─────────────────────────
_DATA: dict = {}
_TRAIN_MASKS: dict = {}
_TEST_MASKS: dict = {}


def _init_worker(history_dir: str):
    """Каждый worker подгружает данные один раз (фоном для multiprocessing)."""
    global _DATA, _TRAIN_MASKS, _TEST_MASKS
    files = sorted(Path(history_dir).glob("*.parquet"))
    for path in files:
        res = cb.process_symbol(path)
        if res is None:
            continue
        flags, r_long, r_short = res
        _DATA[path.stem] = (flags, r_long, r_short)
        idx = flags.index
        _TRAIN_MASKS[path.stem] = np.asarray(idx < TRAIN_END)
        _TEST_MASKS[path.stem] = np.asarray(idx >= TRAIN_END)


def _evaluate_one(args):
    """Воркер: оценить один паттерн на train + test split."""
    idx, pattern_str, direction = args
    factors = tuple(f.strip() for f in pattern_str.split(" + "))

    # Train
    tr_rs = []
    te_rs = []
    for sym, (flags, r_long, r_short) in _DATA.items():
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
        mask_tr = mask & _TRAIN_MASKS[sym] & ~np.isnan(rs)
        mask_te = mask & _TEST_MASKS[sym] & ~np.isnan(rs)
        tr_rs.extend(rs[mask_tr].tolist())
        te_rs.extend(rs[mask_te].tolist())

    if len(tr_rs) < MIN_N_TRAIN or len(te_rs) < 10:
        return None

    tr_arr = np.array(tr_rs)
    te_arr = np.array(te_rs)
    deg = float(tr_arr.mean() - te_arr.mean())
    stable = (te_arr.mean() > 0 and (te_arr > 0).mean() > 0.5 and abs(deg) < 1.5)

    # One-sample one-sided t-test (H0: avgR<=0, H1: avgR>0)
    n_te = len(te_arr)
    mean = float(te_arr.mean())
    std = float(te_arr.std(ddof=1))
    if std == 0 or n_te < 2:
        p_value = 0.5
    else:
        t_stat = mean / (std / math.sqrt(n_te))
        p_value = _student_t_sf(t_stat, n_te - 1) if t_stat > 0 else 1.0

    return {
        "idx":           idx,
        "pattern":       pattern_str,
        "direction":     direction,
        "train_n":       len(tr_arr),
        "train_avgR":    float(tr_arr.mean()),
        "train_WR":      float((tr_arr > 0).mean() * 100),
        "test_n":        len(te_arr),
        "test_avgR":     float(te_arr.mean()),
        "test_WR":       float((te_arr > 0).mean() * 100),
        "test_sumR":     float(te_arr.sum()),
        "test_maxR":     float(te_arr.max()),
        "degradation":   deg,
        "stable":        stable,
        "p_value":       float(p_value),
    }


def bh_fdr_correction(p_values: np.ndarray, alpha: float = 0.05) -> tuple:
    """Benjamini-Hochberg FDR correction.

    Returns (adjusted_p_values, rejected_bools)
    """
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]

    # BH: p_adj[i] = min(p[k] × n/k for k>=i)
    adj = np.zeros(n)
    cmin = 1.0
    for i in range(n - 1, -1, -1):
        cmin = min(cmin, sorted_p[i] * n / (i + 1))
        adj[i] = cmin

    # Unsort
    adj_orig = np.zeros(n)
    adj_orig[sorted_idx] = adj
    rejected = adj_orig < alpha
    return adj_orig, rejected


def main():
    with register_run("walkforward_full", params={"input": str(INPUT_CSV)}) as run:
        run.add_input(INPUT_CSV)

        # Загружаем все 22 835 паттернов
        df = pd.read_csv(INPUT_CSV)
        # Фильтруем по minimum all_n (полная выборка должна быть достаточно большой для train+test split)
        df = df[df["n"] >= MIN_N_TRAIN * 2].copy()
        print(f"Паттернов для walk-forward: {len(df)}")

        # Подготовим аргументы для пула
        args_list = [(i, row["pattern"], row["direction"]) for i, row in df.iterrows()]

        # Multiprocessing pool
        n_workers = max(1, cpu_count() - 1)
        print(f"CPU workers: {n_workers}")
        print(f"Стартую walk-forward...")

        t0 = time.time()
        results = []

        with Pool(n_workers, initializer=_init_worker, initargs=(str(HISTORY_1H),)) as pool:
            for i, res in enumerate(pool.imap_unordered(_evaluate_one, args_list, chunksize=20)):
                if res is not None:
                    results.append(res)
                if (i + 1) % 500 == 0:
                    elapsed = time.time() - t0
                    eta = elapsed / (i + 1) * (len(args_list) - i - 1)
                    print(f"  ...{i+1}/{len(args_list)} | passed: {len(results)} | "
                          f"elapsed: {elapsed/60:.1f}min | ETA: {eta/60:.1f}min")

        elapsed = time.time() - t0
        print(f"\n✅ Завершено за {elapsed/60:.1f} мин. Прошли train+test min_n: {len(results)} / {len(args_list)}")

        if not results:
            print("Нет результатов")
            return

        res_df = pd.DataFrame(results)

        # MHT: BH FDR correction
        p_vals = res_df["p_value"].values
        p_adj, rejected = bh_fdr_correction(p_vals, alpha=0.05)
        res_df["p_value_adj_bh"] = p_adj
        res_df["mht_passed"] = rejected & (res_df["test_avgR"] > 0)

        # Bonferroni (более строгий)
        bonf_threshold = 0.05 / len(p_vals)
        res_df["bonferroni_passed"] = (p_vals < bonf_threshold) & (res_df["test_avgR"] > 0)

        # Sort by composite
        res_df["composite_score"] = res_df["test_avgR"] * (res_df["test_WR"] / 100) * np.log(res_df["test_n"])
        res_df = res_df.sort_values("composite_score", ascending=False)

        # Stats
        n_stable = int(res_df["stable"].sum())
        n_mht_pass = int(res_df["mht_passed"].sum())
        n_bonf_pass = int(res_df["bonferroni_passed"].sum())

        print(f"\n📊 Итоги walk-forward:")
        print(f"  Total tested:      {len(res_df)}")
        print(f"  Stable (deg<1.5):  {n_stable}")
        print(f"  MHT pass (BH FDR): {n_mht_pass}  ← real edges after correction")
        print(f"  Bonferroni pass:   {n_bonf_pass}  (strict)")

        # Save
        out_main = OUTPUT_DIR / "walkforward_full.csv"
        res_df.to_csv(out_main, index=False, encoding="utf-8")
        run.add_output(out_main)

        # Только MHT-passed для feeding в Phase 1.5 ML
        mht_passed = res_df[res_df["mht_passed"]].copy()
        out_mht = OUTPUT_DIR / "walkforward_full_mht.csv"
        mht_passed.to_csv(out_mht, index=False, encoding="utf-8")
        run.add_output(out_mht)

        print(f"\nСохранено:")
        print(f"  {out_main} ({len(res_df)} rows)")
        print(f"  {out_mht} ({len(mht_passed)} rows after MHT)")

        # Top-20 MHT-passed
        if n_mht_pass:
            print(f"\n=== ТОП-20 MHT-passed ===")
            for _, r in mht_passed.head(20).iterrows():
                pat = r["pattern"][:70] + ("…" if len(r["pattern"]) > 70 else "")
                print(f"  {r['direction']:<5} n_te={r['test_n']:>4} avgR_te={r['test_avgR']:>+.3f} "
                      f"WR={r['test_WR']:>4.1f}% p_adj={r['p_value_adj_bh']:.4f}  {pat}")


if __name__ == "__main__":
    main()
