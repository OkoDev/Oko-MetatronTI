"""Канал Эллиотта как ось ядра: тест отбора, объединение масштабов 15+20, перенос оси на 1h 80/20."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import block
from channel_depth import add_geom, line, SP

pd.set_option("display.width", 220)


def prep(name):
    d = pd.read_pickle(SP + name)
    d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "line24_break", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d)
    return d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1].copy()


def selection_test(base, mask, label, n_sim=3000):
    sub = base[mask]
    if len(sub) < 20:
        print(f"  {label}: n={len(sub)} мало"); return
    rs = np.random.RandomState(11)
    dif = (base.pnl_w4 - base.ctl_w4).values; obs = (sub.pnl_w4 - sub.ctl_w4).mean()
    sims = np.array([rs.choice(dif, len(sub), replace=False).mean() for _ in range(n_sim)])
    pnl = base.pnl_w4.values; obs2 = sub.pnl_w4.mean()
    sims2 = np.array([rs.choice(pnl, len(sub), replace=False).mean() for _ in range(n_sim)])
    print(f"  тест отбора {label}: n={len(sub)} перевес {obs:+.2f} → перц. {(sims < obs).mean()*100:5.1f} · "
          f"на сделку {obs2:+.2f} → перц. {(sims2 < obs2).mean()*100:5.1f}")


def dedup(d):
    d = d.sort_values(["sym", "ts"]); keep = []
    last = {}
    for i, r in d.iterrows():
        t0 = last.get(r.sym)
        if t0 is not None and (r.ts - t0) < pd.Timedelta(days=3):
            continue
        last[r.sym] = r.ts; keep.append(i)
    return d.loc[keep]


b20 = prep("wave5sm_4h_15m_sw20_z45.pkl"); b15 = prep("wave5sm_4h_15m_sw15_il4_z45.pkl")
for tag, b in (("4h 20/5", b20), ("4h 15/4", b15)):
    print(f"\n===== {tag}, база n={len(b)}")
    fb = b[b.fractal_ok]
    line(fb, "фрактал (текущее ядро)")
    line(fb[fb.depth5 >= 0.5], "фрактал + depth5≥0.5")
    line(fb[fb.depth5 >= 0.6], "фрактал + depth5≥0.6")
    line(fb[(fb.depth5 >= 0.6) & (fb.depth5 < 1.5)], "фрактал + depth5 [0.6,1.5)")
    line(fb[fb.w5_w1.between(0.618, 1.0)], "фрактал + w5/w1 [0.618,1.0]")
    line(fb[(fb.depth5 >= 0.5) & fb.w5_w1.between(0.5, 1.0)], "фрактал + depth5≥0.5 + w5/w1 [0.5,1.0]")
    line(fb[(fb.depth5 >= 0.5) & (fb.t5_t1 < 2)], "фрактал + depth5≥0.5 + t5/t1<2")
    line(b[~b.fractal_ok & (b.depth5 >= 0.6)], "БЕЗ фрактала + depth5≥0.6")
    line(b[b.depth5 >= 0.6], "depth5≥0.6 без фрактала вообще")
    selection_test(b, b.fractal_ok, "фрактал")
    selection_test(b, b.fractal_ok & (b.depth5 >= 0.5), "фрактал+depth5≥0.5")
    selection_test(b, b.fractal_ok & (b.depth5 >= 0.6), "фрактал+depth5≥0.6")
    selection_test(b, b.fractal_ok & (b.depth5 >= 0.5) & (b.t5_t1 < 2), "фрактал+depth5≥0.5+t5/t1<2")
    selection_test(b[b.fractal_ok], b[b.fractal_ok].depth5 >= 0.6, "depth5≥0.6 ВНУТРИ фрактала")

# объединение масштабов
u = dedup(pd.concat([b20, b15]))
fu = u[u.fractal_ok]
print(f"\n===== ОБЪЕДИНЕНИЕ 15+20 (дедуп <3 сут): база {len(u)}, фрактал {len(fu)}, "
      f"лет {(u.ts.max()-u.ts.min()).days/365.25:.2f}")
line(fu, "фрактал (ядро)")
for thr in (0.4, 0.5, 0.6):
    g = fu[fu.depth5 >= thr]
    line(g, f"фрактал + depth5≥{thr}  ({len(g)/((u.ts.max()-u.ts.min()).days/365.25):.0f}/год)")
g = fu[(fu.depth5 >= 0.5) & (fu.t5_t1 < 2)]
line(g, f"фрактал + depth5≥0.5 + t5/t1<2 ({len(g)/((u.ts.max()-u.ts.min()).days/365.25):.0f}/год)")
selection_test(u, u.fractal_ok & (u.depth5 >= 0.5), "объед. фрактал+depth5≥0.5")
selection_test(u[u.fractal_ok], u[u.fractal_ok].depth5 >= 0.5, "объед. depth5≥0.5 внутри фрактала")
# режим по годам для depth5≥0.5
g = fu[fu.depth5 >= 0.5]
print("  по годам (фрактал+depth5≥0.5): " + " · ".join(f"{y}: n={len(x)} {x.pnl_w4.mean():+.2f}% дошли {x.hit_w4.mean()*100:.0f}%"
                                                        for y, x in g.groupby("year")))
print("  корзины стопа (фрактал+depth5≥0.5): " + " · ".join(
    f"{lo}-{hi}%: n={len(x)} {x.pnl_w4.mean():+.2f}% R {(x.pnl_w4/x.sl_pct).mean():+.2f}"
    for lo, hi in ((0, 2), (2, 3), (3, 5), (5, 99)) for x in [g[(g.sl_pct >= lo) & (g.sl_pct < hi)]] if len(x)))

# перенос оси на 1h 80/20
try:
    b1 = prep("wave5sm_1h_15m_sw80_il20_z45.pkl")
    print(f"\n===== 1h 80/20 (в часах = 4h 20/5), база n={len(b1)}, depth5 медиана {b1.depth5.median():.2f}")
    f1 = b1[b1.fractal_ok]
    line(b1, "база"); line(f1, "фрактал")
    for lo, hi in ((-9, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 99)):
        line(f1[(f1.depth5 >= lo) & (f1.depth5 < hi)], f"  фрактал+depth5 [{lo:>4},{hi:>4})")
    line(f1[f1.depth5 >= 0.5], "фрактал + depth5≥0.5")
    line(b1[b1.depth5 >= 0.5], "depth5≥0.5 без фрактала")
    for lo, hi in ((0, 0.618), (0.618, 1.0), (1.0, 1.618), (1.618, 99)):
        line(f1[(f1.w5_w1 >= lo) & (f1.w5_w1 < hi)], f"  фрактал+w5/w1 [{lo:>5},{hi:>5})")
    selection_test(b1, b1.fractal_ok & (b1.depth5 >= 0.5), "1h фрактал+depth5≥0.5")
except FileNotFoundError as ex:
    print("1h pkl нет:", ex)
