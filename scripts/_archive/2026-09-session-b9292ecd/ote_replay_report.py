"""Отчёт по реплею ote_nested (4h_1h_pull) на истории: зона цены входа в дневной ноге аналитика против всей базы.
Срезы протокола: сторона · год (+режим) · размер стопа · кластер дня · хрупкость · охват монет · тест отбора (перцентиль)."""
import pickle, glob
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path("G:/oko_lab/out")      # результаты замеров переехали на G: (16.09)
rows = [r for f in glob.glob(str(HERE / "ote_replay" / "*.pkl")) for r in pickle.load(open(f, "rb"))]
d = pd.DataFrame(rows)
print(f"монет с файлом: {len(glob.glob(str(HERE / 'ote_replay' / '*.pkl')))} · FIRE-сделок {len(d)} · монет с сделками {d.sym.nunique()}")
d["year"] = d.ts.dt.year; d["day"] = d.ts.dt.floor("D")
d["dn"] = d.groupby("day").sym.transform("size")
d["стоп"] = pd.cut(d.risk_pct, [0, 1, 2, 4, 100], labels=["<1", "1-2", "2-4", ">4"])
d["комп"] = np.where(d.dn >= 3, "кластер ≥3/день", "одиночка")
d["dep"] = pd.cut(d.depth_1d, [0, .25, .5, .62, .79, 1, 1.25, 1.6, 100])
rs = np.random.RandomState(5)


def stats(g, base):
    if len(g) < 20:
        return {"n": len(g)}
    x = g.pnl.values; bx = base.pnl.values
    sims = np.array([bx[rs.randint(0, len(bx), len(x))].mean() for _ in range(2000)])
    keep = np.sort(x)[::-1][int(len(x) * .1):]
    return {"n": len(g), "на сд": x.mean(), "медиана": np.median(x), "WR": (x > 0).mean() * 100, "tp1%": (g.outcome == "tp1").mean() * 100,
            "Δ": x.mean() - bx.mean(), "перц": (sims < x.mean()).mean() * 100, "безтоп10": keep.mean(),
            "монет+%": (g.groupby("sym").pnl.sum() > 0).mean() * 100}


def table(title, base, by):
    out = [{"срез": "ВСЯ БАЗА", **stats(base, base)}]
    for k, g in base.groupby(by, observed=True):
        out.append({"срез": " · ".join(map(str, k)) if isinstance(k, tuple) else str(k), **stats(g, base)})
    print(f"\n--- {title}"); print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:7.2f}"))


table("ЗОНА ВХОДА В ДНЕВНОЙ НОГЕ", d, "zone_1d")
table("ГРАДИЕНТ ГЛУБИНЫ × СТОРОНА", d, ["side", "dep"])
for col in ("side", "year", "стоп", "комп"):
    table(f"ЗОНА × {col}", d, [col, "zone_1d"])
