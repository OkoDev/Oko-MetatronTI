"""Отчёт по fib3m_full.pkl: механика Егора на настоящем 3m по всей базе (145 монет, 2023-26), цели по 4h-импульсу
от уточнённой точки 0, срез по положению пятой в дневной ноге."""
import sys, numpy as np, pandas as pd

f = pd.read_pickle(sys.argv[1] if len(sys.argv) > 1 else "fib3m_full.pkl")
f["zone"] = pd.cut(f.depth.fillna(9), [-9, .5, .62, .79, 1.0, 99],
                   labels=["мелкая <0.5", "0.5-0.62", "OTE 0.62-0.79", "глубокая 0.79-1.0", "за пределами ноги"])
EX = ["X3 микро: 50 вершина A + 50 C=A", "Y1 100% 0.382 4h", "Y0 100% конец w4", "Z1 ½ 0.382 + ½ w4 (БУ)", "Z2 ⅓ 0.382·⅓ 0.618·⅓ w4"]
print(f"сетапов с входом: {f[['sym', 'ts']].drop_duplicates().shape[0]} · монет {f.sym.nunique()} · годы {f.drop_duplicates(['sym','ts']).year.value_counts().sort_index().to_dict()}")
print("зоны (по сетапам):", f.drop_duplicates(["sym", "ts"]).zone.value_counts().to_dict())


def row(g, xn, extra):
    s = g[xn].dropna()
    if len(s) < 10:
        return None
    gg = g.loc[s.index].assign(p=s); R = s / gg.risk
    ctl = gg["ctl " + xn].mean()
    return {**extra, "выход": xn[:2], "n": len(s), "стоп%": gg.risk.median(), "на сд%": s.mean(), "контр%": ctl, "Δ": s.mean() - ctl,
            "R": R.mean(), "WR%": (s > 0).mean() * 100, "без топ10": s.sort_values(ascending=False).iloc[int(len(s) * .1):].mean(),
            "дней+%": (gg.groupby("day").p.mean() > 0).mean() * 100, "монет+%": (gg.groupby("sym").p.sum() > 0).mean() * 100,
            "годы": " ".join(f"{str(y)[2:]}:{v.p.mean():+.1f}/{len(v)}" for y, v in gg.groupby("year"))}


fmt = lambda v: f"{v:6.2f}"
for tag, x in (("вся база", f), ("фрактал+канал", f[f.fc])):
    print(f"\n===== {tag} · все зоны · лонг · 3m")
    out = [r for v, g in x.groupby("v") for xn in EX if (r := row(g, xn, {"вход": v}))]
    print(pd.DataFrame(out).to_string(index=False, float_format=fmt))
MAIN = ["CHoCH3m · верш.N20 · фибо 0.5 · стоп под 0.886", "без CHoCH · верш.N20 · фибо 0.5 · стоп под 0.886",
        "CHoCH3m · верш.N20 · фибо 0.618 · стоп под 0.886", "PEAK: вход на CHoCH 3m · стоп под пятую"]
print("\n===== по зоне дневной ноги · вся база")
out = [r for v in MAIN for z, g in f[f.v == v].groupby("zone", observed=True) for xn in ("Y0 100% конец w4", "Z1 ½ 0.382 + ½ w4 (БУ)")
       if (r := row(g, xn, {"вход": v[:28], "зона": z}))]
print(pd.DataFrame(out).to_string(index=False, float_format=fmt))
