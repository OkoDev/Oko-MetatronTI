# -*- coding: utf-8 -*-
"""СТЕНД ГЕОМЕТРИИ НА ЧИСТЫХ ДАННЫХ BINANCE — БЕЗ СИГНАЛОВ ВООБЩЕ (05.09.2026).

Зачем: на боевых входах BingX пара «широкий структурный стоп × ближняя цель swing»
пережила слепую проверку по монетам. Два вопроса остались открытыми:
  1. не артефакт ли это нашего кэша (в нём найдены битые символы:
     RAY 100% плоских свечей, STRAX 85% — [[law_check_db_cache_price_match]]);
  2. геометрия работает САМА или только вместе с нашими сигналами?

Здесь входы СИНТЕТИЧЕСКИЕ — каждый N-й бар, обе стороны, без всякого сигнала.
Если геометрия даёт эдж на случайных входах, это свойство РЫНКА, а не механики.
Данные — `data/history/*/*.parquet` (data.binance.vision), другая биржа и другой конвейер.

Уровни и сетка переиспользуются из `geometry_bench` (закон reuse ≠ дублирование).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from geometry_bench import build_levels, simulate, STOPS, TARGETS, RR_TARGETS, HOLDS  # noqa: E402

COST = 0.35


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--step", type=int, default=32, help="вход каждый N-й бар")
    ap.add_argument("--bars", type=int, default=22000, help="хвост истории на символ")
    ap.add_argument("--symbols", type=int, default=45)
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--max-stop", type=float, default=15.0)
    a = ap.parse_args()

    files = sorted(glob.glob(str(ROOT / "data" / "history" / a.tf / "*.parquet")))[:a.symbols]
    n_cells = len(STOPS) * (len(TARGETS) + len(RR_TARGETS)) * len(HOLDS)
    print(f"BINANCE PARQUET · {len(files)} символов · ТФ {a.tf} · вход каждый {a.step}-й бар · "
          f"косты {a.cost}%")
    print(f"🔴 ВХОДЫ СИНТЕТИЧЕСКИЕ (без сигнала) · {n_cells} ячеек сетки\n")

    rows = []
    t0 = time.time()
    for k, f in enumerate(files, 1):
        sym = os.path.basename(f).replace(".parquet", "")
        try:
            df = pd.read_parquet(f)
        except Exception:                                   # noqa: BLE001
            continue
        if df is None or len(df) < 2000:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            continue
        df = df.tail(a.bars)
        # 🔴 санитайзер источника: плоские свечи = битые данные (наш урок по RAY/STRAX)
        flat = float(((df.open == df.high) & (df.high == df.low) & (df.low == df.close)).mean())
        if flat > 0.10:
            print(f"  ⚠ {sym}: {flat*100:.0f}% плоских свечей → пропуск")
            continue
        try:
            LV = build_levels(df)
        except Exception:                                   # noqa: BLE001
            continue
        H, L, C = df.high.values, df.low.values, df.close.values
        n = len(C)
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        year = df.index.year.values
        for p in range(400, n - max(HOLDS.values()) - 1, a.step):
            e = float(C[p])
            for d in (1, -1):
                for s_name, k_long, k_short in STOPS:
                    sl = LV.get(k_long if d > 0 else k_short, np.full(n, np.nan))[p]
                    if not (sl == sl):
                        continue
                    if (d > 0 and sl >= e) or (d < 0 and sl <= e):
                        continue
                    sp = abs(e - sl) / e * 100.0
                    if not (0.15 <= sp <= a.max_stop):
                        continue
                    for t_name, tk_long, tk_short in TARGETS:
                        tp = LV.get(tk_long if d > 0 else tk_short, np.full(n, np.nan))[p]
                        if not (tp == tp):
                            continue
                        if (d > 0 and tp <= e) or (d < 0 and tp >= e):
                            continue
                        for h_name, hold in HOLDS.items():
                            r = simulate(H, L, C, p, e, d, sl, tp, hold)
                            if r is not None:
                                rows.append((sym, oos, int(year[p]), "LONG" if d > 0 else "SHORT",
                                             s_name, t_name, h_name, sp, r - a.cost))
                    for rr in RR_TARGETS:
                        tp = e * (1 + d * sp * rr / 100.0)
                        for h_name, hold in HOLDS.items():
                            r = simulate(H, L, C, p, e, d, sl, tp, hold)
                            if r is not None:
                                rows.append((sym, oos, int(year[p]), "LONG" if d > 0 else "SHORT",
                                             s_name, f"RR{rr:.0f}", h_name, sp, r - a.cost))
        if k % 5 == 0:
            print(f"  ... {k}/{len(files)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 нет данных")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "SL", "TP", "H", "sp", "r"])
    R.to_parquet(ROOT / "cache" / "geometry_bench_binance.parquet")
    print(f"\nсобрано: {len(R):,} строк · {R.sym.nunique()} символов · "
          f"{R.year.min()}-{R.year.max()} · входов {len(R)//max(R.groupby(['SL','TP','H']).ngroups,1):,}\n")

    for h in HOLDS:
        sub = R[R.H == h]
        pm = sub.pivot_table(index="SL", columns="TP", values="r", aggfunc="median")
        pn = sub.pivot_table(index="SL", columns="TP", values="r", aggfunc="size")
        cols = [c for c in pm.columns if pn[c].sum() >= a.min_n]
        print("=" * (18 + 11 * len(cols)))
        print(f"КАРТА · горизонт {h} · МЕДИАНА net % · СИНТЕТИЧЕСКИЕ входы")
        print("=" * (18 + 11 * len(cols)))
        print(f"{'стоп \\ цель':16s}" + "".join(f"{c:>11}" for c in cols))
        for i in pm.index:
            line = ""
            for cc in cols:
                v, nn = pm.loc[i, cc], pn.loc[i, cc]
                line += f"{v:>+10.3f}%" if (nn == nn and nn >= a.min_n) else f"{'—':>11}"
            print(f"{i:16s}{line}")
        print()

    print("=" * 112)
    print("СЛЕПАЯ ПРОВЕРКА ПО СИМВОЛАМ (отбор на половине → проверка на другой)")
    print("=" * 112)
    IS, OOS = R[~R.oos], R[R.oos]
    g = IS.groupby(["SL", "TP", "H"]).r.agg(["median", "mean", "size"])
    g = g[g["size"] >= a.min_n].sort_values("median", ascending=False)
    print(f"{'стоп':10s} {'цель':10s} {'гор.':5s} {'IS мед.':>10} {'OOS мед.':>10} "
          f"{'OOS сред.':>11} {'OOS WR':>8} {'OOS n':>8}")
    for (sl_, tp_, h_), row in g.head(12).iterrows():
        o = OOS[(OOS.SL == sl_) & (OOS.TP == tp_) & (OOS.H == h_)]
        if len(o) < 100:
            continue
        print(f"{sl_:10s} {tp_:10s} {h_:5s} {row['median']:>+9.3f}% {o.r.median():>+9.3f}% "
              f"{o.r.mean():>+10.3f}% {100*(o.r>0).mean():>7.1f}% {len(o):>8,}")

    print("\n" + "=" * 112)
    print("ЛУЧШАЯ СТРУКТУРНАЯ ПАРА — РАЗРЕЗЫ (сторона · год)")
    print("=" * 112)
    best = None
    for (sl_, tp_, h_), row in g.head(12).iterrows():
        if tp_.startswith("RR"):
            continue
        o = OOS[(OOS.SL == sl_) & (OOS.TP == tp_) & (OOS.H == h_)]
        if len(o) >= 100 and o.r.mean() > 0:
            best = (sl_, tp_, h_)
            break
    if best is None:
        print("   🔴 ни одна СТРУКТУРНАЯ пара не дала положительное среднее на OOS")
        return 0
    sl_, tp_, h_ = best
    B = R[(R.SL == sl_) & (R.TP == tp_) & (R.H == h_)]
    print(f"пара: стоп {sl_} × цель {tp_} · горизонт {h_}\n")
    for nm, sub in [("ВСЁ", B)] + [(d, B[B.dir == d]) for d in ("LONG", "SHORT")] + \
                   [(str(y), B[B.year == y]) for y in sorted(B.year.unique())]:
        if len(sub) < 100:
            continue
        v = np.sort(sub.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"   {nm:10s} n={len(sub):>7,} медиана={np.median(v):>+7.3f}% среднее={v.mean():>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
