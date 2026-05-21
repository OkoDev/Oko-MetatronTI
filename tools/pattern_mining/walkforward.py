"""
Walk-forward validation топовых паттернов.

Берёт ТОП-50 паттернов из smc_combinator_results.csv (или v2),
делит данные на train/test:
  Train: 2024-01-01 → 2025-06-30 (18 мес)
  Test:  2025-07-01 → 2026-05-17 (11 мес)

Для каждого паттерна:
  - avgR на train / WR / n
  - avgR на test / WR / n
  - degradation = train.avgR - test.avgR (если test значимо хуже — паттерн нестабилен)
  - is_stable = test.avgR > 0 AND test.WR > 50 AND degradation < 0.5

Запуск:
  python e:/tmp/smc_walkforward.py [v1|v2]
"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from pathlib import Path
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# Импорты из combinator скрипта
sys.path.insert(0, "e:/tmp")

VERSION = sys.argv[1] if len(sys.argv) > 1 else "v2"
if VERSION == "v2":
    import smc_combinator_v2 as cb
    RESULTS_CSV = Path("e:/tmp/smc_combinator_v2_results.csv")
else:
    import smc_combinator as cb
    RESULTS_CSV = Path("e:/tmp/smc_combinator_results.csv")
# Снижаем MIN_N до 20 для walk-forward (train/test делит выборку)
cb.MIN_N = 20
process_symbol = cb.process_symbol
evaluate = cb.evaluate
score_fn = cb.score_fn
HISTORY_DIR = cb.HISTORY_DIR

TRAIN_END = pd.Timestamp("2025-07-01", tz="UTC")
TOP_N     = 100   # сколько топ-паттернов проверяем


def split_flags(flags_dict: dict, cutoff: pd.Timestamp):
    """Разделяет flags_dict на train / test по дате."""
    train = {}
    test  = {}
    for sym, (flags, r_long, r_short) in flags_dict.items():
        mask_train = flags.index < cutoff
        mask_test  = flags.index >= cutoff
        mask_train_arr = mask_train.values if hasattr(mask_train, "values") else np.asarray(mask_train)
        mask_test_arr  = mask_test.values  if hasattr(mask_test,  "values") else np.asarray(mask_test)
        train[sym] = (
            flags[mask_train_arr],
            r_long[mask_train_arr],
            r_short[mask_train_arr],
        )
        test[sym] = (
            flags[mask_test_arr],
            r_long[mask_test_arr],
            r_short[mask_test_arr],
        )
    return train, test


def main():
    if not RESULTS_CSV.exists():
        print(f"Нет файла {RESULTS_CSV}")
        return

    df = pd.read_csv(RESULTS_CSV)
    print(f"Загружено паттернов: {len(df)}")

    # Топ-N по score
    top = df.head(TOP_N).copy()
    print(f"Берём топ-{TOP_N}\n")

    # Загружаем данные
    files = sorted(HISTORY_DIR.glob("*.parquet"))
    print(f"Загрузка {len(files)} пар...")
    flags_dict = {}
    for path in files:
        res = process_symbol(path)
        if res is None: continue
        flags_dict[path.stem] = res
    print(f"  Готово. Пар: {len(flags_dict)}")

    print(f"\nДеление train/test по {TRAIN_END}")
    train, test = split_flags(flags_dict, TRAIN_END)

    results = []
    for _, row in top.iterrows():
        pat_str = row["pattern"]
        factors = tuple(f.strip() for f in pat_str.split(" + "))
        direction = row["direction"]

        s_train = evaluate(train, factors, direction)
        s_test  = evaluate(test,  factors, direction)

        if not s_train or not s_test:
            continue

        deg = s_train["avgR"] - s_test["avgR"]
        is_stable = (s_test["avgR"] > 0 and s_test["WR"] > 50 and deg < 0.5)

        results.append({
            "pattern":   pat_str,
            "direction": direction,
            "k":         int(row["k"]),
            "all_n":     int(row["n"]),
            "all_avgR":  row["avgR"],
            "train_n":   s_train["n"],
            "train_avgR":s_train["avgR"],
            "train_WR":  s_train["WR"],
            "test_n":    s_test["n"],
            "test_avgR": s_test["avgR"],
            "test_WR":   s_test["WR"],
            "degradation": deg,
            "stable":    is_stable,
        })

    res_df = pd.DataFrame(results)
    if len(res_df) == 0:
        print("\nНет паттернов прошедших оба периода. Снизьте MIN_N или возьмите больше TOP_N.")
        return
    res_df = res_df.sort_values("test_avgR", ascending=False)

    print(f"\n{'='*120}")
    print(f"WALK-FORWARD VALIDATION (TOP-{TOP_N})  cutoff={TRAIN_END}")
    print(f"{'='*120}")

    # Stable паттерны
    stable = res_df[res_df["stable"]]
    print(f"\n=== УСТОЙЧИВЫЕ ПАТТЕРНЫ (test_avgR>0 AND test_WR>50 AND deg<0.5): {len(stable)}/{len(res_df)} ===")
    print(f"{'dir':<5} {'k':<2} {'train_n':>7} {'tr_avgR':>8} {'tr_WR':>6} {'test_n':>6} {'te_avgR':>8} {'te_WR':>6} {'deg':>6}  pattern")
    print("-"*120)
    for _, r in stable.iterrows():
        pat = r["pattern"][:55] + ("…" if len(r["pattern"])>55 else "")
        print(f"{r['direction']:<5} {r['k']:<2} {r['train_n']:>7} {r['train_avgR']:>+8.3f} {r['train_WR']:>5.1f}% {r['test_n']:>6} {r['test_avgR']:>+8.3f} {r['test_WR']:>5.1f}% {r['degradation']:>+6.2f}  {pat}")

    # Overfitted паттерны (деградация >1.0)
    overfit = res_df[res_df["degradation"] > 1.0]
    print(f"\n=== OVERFITTED (degradation > 1.0): {len(overfit)}/{len(res_df)} ===")
    if len(overfit):
        print(f"{'dir':<5} {'k':<2} {'tr_avgR':>8} {'te_avgR':>8} {'deg':>6}  pattern")
        for _, r in overfit.head(10).iterrows():
            pat = r["pattern"][:60] + ("…" if len(r["pattern"])>60 else "")
            print(f"{r['direction']:<5} {r['k']:<2} {r['train_avgR']:>+8.3f} {r['test_avgR']:>+8.3f} {r['degradation']:>+6.2f}  {pat}")

    # Сохраним
    out = Path(f"e:/tmp/smc_walkforward_{VERSION}_results.csv")
    res_df.to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")
    print(f"Всего проверено: {len(res_df)}, устойчивых: {len(stable)}")


if __name__ == "__main__":
    main()
