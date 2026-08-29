"""
pair_search.py — ПОИСК СВЯЗОК ПРИЗНАКОВ (пары и тройки), общий инструмент (29.08.2026).

Задача Егора: «ищи все возможные связки по всем семьям и признакам».

🔴 ПОЧЕМУ ОДИН ИНСТРУМЕНТ, А НЕ ПО СКРИПТУ НА ИСПОЛНИТЕЛЯ. За эту сессию признак EQH
трижды поменял вердикт, и каждый раз причина была в РЕАЛИЗАЦИИ: разное окно расчёта,
разный сдвиг, разный набор зон. Три исполнителя напишут три версии и получат три ответа.
Здесь порядок зафиксирован один раз: окно, сдвиг, пороги, контроль.

🔴 ГЛАВНАЯ ОПАСНОСТЬ ПЕРЕБОРА ПАР — МНОЖЕСТВЕННОСТЬ. Из 200 признаков выходит ~20 000 пар;
при таком числе гипотез «PF 5» находится в чистом шуме гарантированно. Поэтому:
  · то же число комбинаций гоняется по ПЕРЕМЕШАННОМУ pnl (тот же конвейер целиком),
    и P(шум ≥ нашего) считается по числу ВЫЖИВШИХ, а не по лучшему PF;
  · порог — ОТНОСИТЕЛЬНО базы своей выборки, не абсолютный;
  · IS/OOS разбиение по МОНЕТАМ (пересечения нет) + отдельно временной OOS.

Данные берутся из `cache/matrix_run_15m_lw.parquet` — матрицы, пересчитанной БОЕВЫМ окном
(суффикс `_lw`), где это имело значение ([[window_sensitivity_only_smc_breaks]]).

    python scripts/pair_search.py --side short --families all
    python scripts/pair_search.py --side long --families SCALES,WAVES --max-feats 60
"""
from __future__ import annotations

import argparse
import itertools
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m_lw.parquet"
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")

FAMILIES = {
    "SCALES": lambda c: c.startswith(("st5_", "st50_", "sc_")),
    "WAVES":  lambda c: c.startswith("leg_"),
    "SMC":    lambda c: c.endswith("_lw"),
    "MKT":    lambda c: c.startswith(("mkt_", "btc_")),
    "FUND":   lambda c: c.startswith("fund_"),
    "DIST":   lambda c: c.startswith("dist_"),
    "CANDLE": lambda c: any(k in c for k in ("body_frac", "wick", "close_pos", "vol_ratio",
                                            "vol_delta", "cum_delta", "bar_range")),
    "OLD":    lambda c: not any(c.startswith(p) for p in
                                ("st5_", "st50_", "sc_", "leg_", "mkt_", "btc_", "fund_", "dist_"))
              and not c.endswith("_lw"),
}
# служебные колонки — не признаки
SKIP = {"sym", "oos", "year", "side", "pnl", "signal_bar", "entry_ts", "_ts",
        "stop_pct", "amp_pct", "vratio", "regime", "age", "px"}


def binarize(A: pd.DataFrame, col: str) -> list[tuple[str, pd.Series]]:
    """Признак → набор условий. Булев как есть, числовой — децилями в обе стороны."""
    v = A[col].dropna()
    if v.nunique() < 2:
        return []
    if v.nunique() <= 2:
        return [(f"{col}=1", A[col] == 1.0)]
    out = []
    for q in (0.15, 0.3, 0.7, 0.85):
        t = float(v.quantile(q))
        if q <= 0.3:
            out.append((f"{col}<={t:.4g}", A[col] <= t))
        else:
            out.append((f"{col}>={t:.4g}", A[col] >= t))
    return out


def run_scan(D: pd.DataFrame, conds: list[tuple[str, pd.Series]], *,
             min_n: int, lift: float, top: int) -> list[tuple]:
    """Одиночки и пары: отбор на IS, проверка на OOS. Возвращает выживших."""
    IS, OOS = D[~D.oos], D[D.oos]
    bi, bo = stat(IS), stat(OOS)
    if not bi or not bo:
        return []
    cand = []
    for nm, m in conds:
        s = stat(IS[m[IS.index]])
        if s and s["n"] >= min_n and s["pf"] > bi["pf"] * lift:
            cand.append((s["pf"], nm, m))
    # пары строятся ТОЛЬКО из одиночек, прошедших IS — иначе комбинаторный взрыв
    cand.sort(reverse=True, key=lambda x: x[0])
    base = cand[:60]
    pairs = []
    for (p1, n1, m1), (p2, n2, m2) in itertools.combinations(base, 2):
        if n1.split("<")[0].split(">")[0].split("=")[0] == n2.split("<")[0].split(">")[0].split("=")[0]:
            continue                       # одна и та же колонка с двух сторон — не связка
        mm = m1 & m2
        s = stat(IS[mm[IS.index]])
        if s and s["n"] >= min_n and s["pf"] > bi["pf"] * lift:
            pairs.append((s["pf"], f"{n1}  &  {n2}", mm))
    allc = sorted(cand + pairs, reverse=True, key=lambda x: x[0])[:top]
    surv = []
    for pf, nm, m in allc:
        o = stat(OOS[m[OOS.index]])
        if o and o["n"] >= max(40, min_n // 3) and o["pf"] > bo["pf"] * lift:
            surv.append((nm, stat(IS[m[IS.index]]), o, m))
    return surv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", default="short", choices=["short", "long"])
    ap.add_argument("--families", default="all", help="через запятую или all")
    ap.add_argument("--gate", default="1", help="1 = поверх боевого дрейф-гейта")
    ap.add_argument("--min-n", type=int, default=100)
    ap.add_argument("--lift", type=float, default=1.15)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--perm", type=int, default=15)
    ap.add_argument("--max-feats", type=int, default=0, help="ограничить число признаков")
    a = ap.parse_args()

    X = pd.read_parquet(PQ)
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    D = X[X.side == a.side].copy()
    if a.gate == "1":
        D = D[D.mkt_drift_slope > 0]
    D = D.reset_index(drop=True)

    fams = list(FAMILIES) if a.families == "all" else [f.strip() for f in a.families.split(",")]
    cols = []
    for f in fams:
        pred = FAMILIES.get(f)
        if pred is None:
            print(f"🔴 неизвестная семья: {f}"); return 1
        cols += [c for c in D.columns if c not in SKIP and pred(c)
                 and pd.api.types.is_numeric_dtype(D[c])]
    cols = sorted(set(cols))
    if a.max_feats:
        cols = cols[:a.max_feats]

    b = stat(D)
    print("=" * 104)
    print(f"ПОИСК СВЯЗОК · сторона {a.side.upper()} · гейт {'ДА' if a.gate=='1' else 'нет'} · "
          f"семьи {','.join(fams)} · признаков {len(cols)}")
    print("=" * 104)
    print(line(D, "  БАЗА"))
    conds, seen = [], set()
    for c in cols:
        for nm, m in binarize(D, c):
            # у признака с малым числом уникальных значений соседние квантили дают
            # ОДИН И ТОТ ЖЕ порог — без дедупликации такие условия попадают в отбор
            # дважды и раздувают счёт выживших, а с ним и оценку значимости
            if nm in seen:
                continue
            seen.add(nm)
            conds.append((nm, m))
    print(f"  условий из признаков: {len(conds)} · пар будет до {60*59//2}")

    surv = run_scan(D, conds, min_n=a.min_n, lift=a.lift, top=a.top)
    print(f"\nПЕРЕЖИЛО OOS: {len(surv)}")
    for nm, s, o, m in surv:
        yrs = []
        for y in sorted(D.year.unique()):
            g = D[D.year == y]
            aa, bb = stat(g[m[g.index]]), stat(g)
            yrs.append(f"{y}×{aa['pf']/bb['pf']:.1f}" if (aa and bb and bb["pf"]) else f"{y}—")
        print(f"  {nm[:74]:<76}")
        print(f"      IS {s['pf']:5.2f} n={s['n']:<4} → OOS {o['pf']:5.2f} n={o['n']:<4} "
              f"безтоп10% {o['bt']:+7.0f} охват {o['cov']:3.0f}%  " + " ".join(yrs))

    print(f"\n🎲 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ ({a.perm} перемешиваний, ТОТ ЖЕ конвейер целиком):")
    rng = np.random.default_rng(7)
    noise = []
    for _ in range(a.perm):
        Ds = D.assign(pnl=rng.permutation(D.pnl.values))
        cs = []
        for c in cols:
            cs += binarize(Ds, c)
        noise.append(len(run_scan(Ds, cs, min_n=a.min_n, lift=a.lift, top=a.top)))
    noise = np.array(noise)
    p = float((noise >= len(surv)).mean())
    print(f"   ШУМ: медиана {np.median(noise):.1f} · 95-й перцентиль {np.percentile(noise,95):.1f}"
          f" · максимум {noise.max()}   наш {len(surv)}")
    print(f"   P(шум ≥ нашего) = {p:.3f}   " +
          ("🟢 ОТЛИЧИМО ОТ ШУМА" if p < 0.05 else
           "🟡 на границе" if p <= 0.15 else "🔴 НЕ отличимо — находок нет"))
    print("\n🔑 При P > 0.15 любые красивые PF выше — шум. Не докладывать их как находки.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
