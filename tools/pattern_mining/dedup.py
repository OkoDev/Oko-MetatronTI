"""
Дедупликация топ-паттернов после combinator.

Логика:
1. Группа по (direction, n, round(avgR, 3), round(WR, 1))
2. В каждой группе оставляем самый простой паттерн (минимум факторов)
3. Также убираем "субсеты": если A = (X,Y) и B = (X,Y,Z) и stats отличаются мало → оставляем A

Запуск: python e:/tmp/smc_dedup.py [v1|v2]
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
import pandas as pd

VERSION = sys.argv[1] if len(sys.argv) > 1 else "v2"
RESULTS_CSV = Path(f"e:/tmp/smc_combinator{'_v2' if VERSION=='v2' else ''}_results.csv")


def main():
    if not RESULTS_CSV.exists():
        print(f"Нет файла {RESULTS_CSV}"); return

    df = pd.read_csv(RESULTS_CSV)
    print(f"Всего паттернов: {len(df)}")

    # Парсим pattern → tuple факторов
    df["_factors"] = df["pattern"].apply(lambda p: tuple(sorted(f.strip() for f in p.split(" + "))))
    df["_k"]       = df["k"]

    # ── Шаг 1: группировка по идентичным stats ──────────────────────────
    df["_grp"] = list(zip(
        df["direction"],
        df["n"].astype(int),
        df["avgR"].round(3),
        df["WR"].round(1),
    ))

    keep_idx = []
    for grp, sub in df.groupby("_grp"):
        # Берём с минимальным k (простейший паттерн)
        idx = sub.sort_values("_k").index[0]
        keep_idx.append(idx)
    df_dedup = df.loc[keep_idx].copy()
    print(f"После dedup по identical stats: {len(df_dedup)}")

    # ── Шаг 2: убираем supersets ────────────────────────────────────────
    df_dedup = df_dedup.sort_values("score", ascending=False).reset_index(drop=True)
    keep = []
    seen_subsets = []   # списки (direction, frozenset факторов, n, avgR)
    for _, r in df_dedup.iterrows():
        factors_set = frozenset(r["_factors"])
        direction = r["direction"]
        is_superset_of_better = False
        for prev_dir, prev_set, prev_n, prev_avg in seen_subsets:
            if prev_dir != direction:
                continue
            # Если уже видели subset того же паттерна со сравнимыми stats — пропускаем
            if prev_set.issubset(factors_set) and len(prev_set) < len(factors_set):
                # subset уже зарегистрирован → текущий = superset
                # Оставляем только если он СУЩЕСТВЕННО лучше (avgR > prev_avg + 0.1)
                if r["avgR"] <= prev_avg + 0.1:
                    is_superset_of_better = True
                    break
        if not is_superset_of_better:
            keep.append(r.name)
            seen_subsets.append((direction, factors_set, r["n"], r["avgR"]))
    df_final = df_dedup.loc[keep].copy()
    print(f"После dedup supersets: {len(df_final)}")

    # ── Вывод топ-30 ────────────────────────────────────────────────────
    df_final = df_final.sort_values("score", ascending=False)

    print(f"\n{'='*110}")
    print(f"ТОП-30 УНИКАЛЬНЫХ ПАТТЕРНОВ")
    print(f"{'='*110}")
    print(f"{'#':<3} {'k':<2} {'dir':<5} {'n':>5} {'avgR':>7} {'WR%':>6} {'sumR':>8} {'score':>7}  pattern")
    print("-"*110)
    for i, (_, r) in enumerate(df_final.head(30).iterrows(), 1):
        pat = r["pattern"][:65] + ("…" if len(r["pattern"])>65 else "")
        print(f"{i:<3} {int(r['k']):<2} {r['direction']:<5} {int(r['n']):>5} {r['avgR']:>+7.3f} {r['WR']:>5.1f}% {r['sumR']:>+8.1f} {r['score']:>+7.3f}  {pat}")

    print(f"\n=== ТОП-15 LONG (уникальных) ===")
    for i, (_, r) in enumerate(df_final[df_final["direction"]=="LONG"].head(15).iterrows(), 1):
        pat = r["pattern"][:75] + ("…" if len(r["pattern"])>75 else "")
        print(f"  {i:>2}. k={int(r['k'])} n={int(r['n']):>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {pat}")

    print(f"\n=== ТОП-15 SHORT (уникальных) ===")
    for i, (_, r) in enumerate(df_final[df_final["direction"]=="SHORT"].head(15).iterrows(), 1):
        pat = r["pattern"][:75] + ("…" if len(r["pattern"])>75 else "")
        print(f"  {i:>2}. k={int(r['k'])} n={int(r['n']):>5} avgR={r['avgR']:>+.3f} WR={r['WR']:>4.1f}%  {pat}")

    out = Path(f"e:/tmp/smc_dedup_{VERSION}_results.csv")
    df_final.drop(columns=["_factors","_k","_grp"]).to_csv(out, index=False, encoding="utf-8")
    print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()
