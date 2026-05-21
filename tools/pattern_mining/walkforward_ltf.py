"""
Walk-forward validation для LTF nested паттернов.

Использует результаты v3_nested на 15m или 5m + HTF mask (золотой паттерн).
Делит данные на train (2024-01..2025-06) / test (2025-07..2026-05).

Запуск:
  python tools/pattern_mining/walkforward_ltf.py [15m|5m]
"""
import sys, time, warnings
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path
import pandas as pd
import numpy as np

LTF = sys.argv[1] if len(sys.argv) > 1 else "15m"

PROJECT_ROOT = Path("E:/MTF BOT/CURSOR/crypto_volume_bot")
HISTORY_1H = PROJECT_ROOT / "data/history/1h"
HISTORY_LTF = PROJECT_ROOT / f"data/history/{LTF}"
RESULTS_CSV = PROJECT_ROOT / f"data/research/2026-05-19/nested_v3_{LTF}_results.csv"

sys.path.insert(0, str(Path(__file__).parent))
import combinator_v2 as cb
import combinator_v3_nested as nested

# Снижаем MIN_N для walk-forward (делим выборку)
nested.MIN_N = 15

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")
TOP_N = 100   # сколько топ-паттернов проверять


def split_data(data: dict, cutoff: pd.Timestamp):
    """Делит nested data на train/test."""
    train, test = {}, {}
    for sym, (flags, r_long, htf_mask) in data.items():
        idx = flags.index
        mask_tr = (idx < cutoff)
        mask_te = (idx >= cutoff)
        mask_tr_arr = np.asarray(mask_tr)
        mask_te_arr = np.asarray(mask_te)
        train[sym] = (flags[mask_tr_arr], r_long[mask_tr_arr], htf_mask[mask_tr_arr])
        test[sym]  = (flags[mask_te_arr], r_long[mask_te_arr], htf_mask[mask_te_arr])
    return train, test


def main():
    if not RESULTS_CSV.exists():
        print(f"Нет файла {RESULTS_CSV}. Сначала запусти combinator_v3_nested.py {LTF}")
        return

    df = pd.read_csv(RESULTS_CSV)
    print(f"LTF: {LTF}  |  Топ-{TOP_N} паттернов из {len(df)}")
    top = df.sort_values("score", ascending=False).head(TOP_N).copy()

    print(f"\nЗагрузка данных всех пар...")
    t0 = time.time()
    files = sorted(HISTORY_LTF.glob("*.parquet"))
    data = {}
    for path in files:
        res = nested.process_pair(path.stem)
        if res is None: continue
        data[path.stem] = res
    print(f"  Готово за {time.time()-t0:.0f}с. Пар: {len(data)}")

    train, test = split_data(data, TRAIN_END)

    results = []
    for _, row in top.iterrows():
        pat = row["pattern"]
        factors = tuple(f.strip() for f in pat.split(" + "))

        s_tr = nested.evaluate_nested(train, factors)
        s_te = nested.evaluate_nested(test, factors)
        if not s_tr or not s_te: continue

        deg = s_tr["avgR"] - s_te["avgR"]
        stable = s_te["avgR"] > 0 and s_te["WR"] > 50 and deg < 0.5

        results.append({
            "pattern":    pat,
            "k":          int(row["k"]),
            "all_n":      int(row["n"]),
            "all_avgR":   float(row["avgR"]),
            "all_WR":     float(row["WR"]),
            "train_n":    s_tr["n"],
            "train_avgR": s_tr["avgR"],
            "train_WR":   s_tr["WR"],
            "test_n":     s_te["n"],
            "test_avgR":  s_te["avgR"],
            "test_WR":    s_te["WR"],
            "degradation": deg,
            "stable":     stable,
        })

    res_df = pd.DataFrame(results)
    if len(res_df) == 0:
        print(f"\nНет паттернов прошедших оба периода (даже с MIN_N={nested.MIN_N}).")
        return

    res_df = res_df.sort_values("test_avgR", ascending=False)
    stable = res_df[res_df["stable"]]

    print(f"\n{'='*120}")
    print(f"LTF WALK-FORWARD ({LTF})  cutoff={TRAIN_END}  |  Проверено: {len(res_df)}/{TOP_N}")
    print(f"{'='*120}")

    print(f"\n=== УСТОЙЧИВЫЕ ПАТТЕРНЫ: {len(stable)}/{len(res_df)} ===")
    print(f"{'k':<2} {'tr_n':>4} {'tr_avgR':>8} {'tr_WR':>6} {'te_n':>4} {'te_avgR':>8} {'te_WR':>6} {'deg':>6}  pattern")
    print("-"*120)
    for _, r in stable.iterrows():
        pat = r["pattern"][:70] + ("…" if len(r["pattern"])>70 else "")
        print(f"{r['k']:<2} {r['train_n']:>4} {r['train_avgR']:>+8.3f} {r['train_WR']:>5.1f}% {r['test_n']:>4} {r['test_avgR']:>+8.3f} {r['test_WR']:>5.1f}% {r['degradation']:>+6.2f}  {pat}")

    # Overfit
    overfit = res_df[res_df["degradation"] > 1.0]
    print(f"\n=== OVERFITTED (deg > 1.0): {len(overfit)}/{len(res_df)} ===")
    for _, r in overfit.head(10).iterrows():
        pat = r["pattern"][:65] + ("…" if len(r["pattern"])>65 else "")
        print(f"  tr_avgR={r['train_avgR']:>+.3f} → te_avgR={r['test_avgR']:>+.3f} (deg={r['degradation']:+.2f})  {pat}")

    out = PROJECT_ROOT / f"data/research/2026-05-19/walkforward_nested_{LTF}_results.csv"
    res_df.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()
