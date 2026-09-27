"""Сравнение ТФ подтверждения (входа) для одного HTF-импульса на ОДНОМ окне данных.
python ltf_compare.py <pkl1> <pkl2> ... [--t0 2025-01-01] [--t1 2026-05-31]"""
import sys, argparse, numpy as np, pandas as pd
sys.path.insert(0, ".")
from channel_depth import add_geom, SP
from wave5_sm import block

pd.set_option("display.width", 230)


def prep(name, t0, t1):
    d = pd.read_pickle(SP + name)
    d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d)
    d = d[(d.ts >= pd.Timestamp(t0, tz="UTC")) & (d.ts <= pd.Timestamp(t1, tz="UTC"))]
    return d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1].copy()


def sel_test(base, mask, n_sim=3000):
    sub = base[mask]
    if len(sub) < 20 or len(sub) == len(base):
        return "—"
    rs = np.random.RandomState(11)
    dif = (base.pnl_w4 - base.ctl_w4).values; obs = (sub.pnl_w4 - sub.ctl_w4).mean()
    sims = np.array([rs.choice(dif, len(sub), replace=False).mean() for _ in range(n_sim)])
    return f"{(sims < obs).mean()*100:.0f}"


def row(g, base, label, yrs):
    if len(g) < 12:
        return {"срез": label, "n": len(g)}
    r = block(g, "w4") if len(g) >= 20 else None
    out = {"срез": label, "n": len(g), "в год": round(len(g) / yrs), "на сд%": g.pnl_w4.mean(), "R": (g.pnl_w4 / g.sl_pct).mean(),
           "медR": (g.pnl_w4 / g.sl_pct).median(), "дошли%": g.hit_w4.mean() * 100, "WR%": (g.pnl_w4 > 0).mean() * 100,
           "стоп%": g.sl_pct.median(), "лаг ч": g.lag_htf_bars.median() * {"15m": 15, "1h": 60, "4h": 240}[g.htf.iloc[0]] / 60,
           "hold ч": g.hold.median() * {"1m": 1, "5m": 5, "15m": 15, "1h": 60}[g.ltf.iloc[0]] / 60,
           "gone": g.gone.median(), "монет+%": (g.groupby("sym").pnl_w4.sum() > 0).mean() * 100,
           "отбор": sel_test(base, base.index.isin(g.index))}
    if r:
        out.update({"перевес": r["перевес"], "ДИ": r["ДИ"], "безтоп10": r["безтоп10"]})
    return out


ap = argparse.ArgumentParser()
ap.add_argument("pkls", nargs="+"); ap.add_argument("--t0", default="2025-01-01"); ap.add_argument("--t1", default="2026-05-31")
a = ap.parse_args()
for name in a.pkls:
    b = prep(name, a.t0, a.t1)
    if not len(b):
        print(f"\n===== {name}: пусто в окне"); continue
    yrs = max((b.ts.max() - b.ts.min()).days / 365.25, 0.25)
    print(f"\n===== {name} · окно {b.ts.min():%Y-%m-%d} → {b.ts.max():%Y-%m-%d} ({yrs:.2f} г) · база лонг n={len(b)}")
    f = b[b.fractal_ok]
    rows = [row(b, b, "база", yrs), row(f, b, "фрактал", yrs), row(b[~b.fractal_ok], b, "без фрактала", yrs)]
    for lo, hi in ((-9, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 99)):
        rows.append(row(f[(f.depth5 >= lo) & (f.depth5 < hi)], b, f"  фрактал+канал [{lo},{hi})", yrs))
    rows.append(row(f[f.depth5 >= 0.5], b, "ФРАКТАЛ + КАНАЛ ≥0.5 (v2)", yrs))
    rows.append(row(b[~b.fractal_ok & (b.depth5 >= 0.5)], b, "без фрактала + канал ≥0.5", yrs))
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:6.2f}"))
    v2 = f[f.depth5 >= 0.5]
    if len(v2):
        print("  v2 по годам: " + " · ".join(f"{y}: n={len(x)} {x.pnl_w4.mean():+.2f}%" for y, x in v2.groupby("year")))
        print("  v2 корзины стопа: " + " · ".join(f"{lo}-{hi}%: n={len(x)} {x.pnl_w4.mean():+.2f}% R {(x.pnl_w4/x.sl_pct).mean():+.2f} дошли {x.hit_w4.mean()*100:.0f}%"
              for lo, hi in ((0, 1.5), (1.5, 3), (3, 5), (5, 99)) for x in [v2[(v2.sl_pct >= lo) & (v2.sl_pct < hi)]] if len(x)))
