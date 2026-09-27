"""Срезы ядра по дневному контексту (степень 4h-пятёрки на дневной структуре)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from channel_depth import add_geom, SP
from wave5_sm import block
pd.set_option("display.width", 230)


def prep(name, side):
    d = pd.read_pickle(SP + name); d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d); d["R"] = d.pnl_w4 / d.sl_pct
    return d[(d.dir == side) & (d.gone <= 0.25) & d.w3_ge_w1].copy()


def line(g, lbl):
    if len(g) < 12:
        print(f"{lbl:<52} n={len(g)} мало"); return
    ep = g.groupby(g.ts.dt.strftime("%Y-%m-%d")).pnl_w4.mean()
    print(f"{lbl:<52} n={len(g):3d} на сд {g.pnl_w4.mean():+.2f}% R {g.R.mean():+.2f} медR {g.R.median():+.2f} цель {g.hit_w4.mean()*100:.0f}% WR {(g.pnl_w4>0).mean()*100:.0f}% "
          f"безтоп10 {g.pnl_w4.sort_values(ascending=False).iloc[int(len(g)*0.1):].mean():+.2f} монет+ {(g.groupby('sym').pnl_w4.sum()>0).mean()*100:.0f}% дней+ {(ep>0).mean()*100:.0f}% мед.дня {ep.median():+.2f} "
          f"| годы " + " ".join(f"{y}:{x.pnl_w4.mean():+.1f}" for y, x in g.groupby("year")))


def sel(base, mask, lbl, n_sim=3000):
    sub = base[mask]
    if len(sub) < 15 or len(sub) >= len(base) - 5:
        return
    rs = np.random.RandomState(11); dif = (base.pnl_w4 - base.ctl_w4).values; obs = (sub.pnl_w4 - sub.ctl_w4).mean()
    sims = np.array([rs.choice(dif, len(sub), replace=False).mean() for _ in range(n_sim)])
    print(f"    тест отбора {lbl}: n={len(sub)} перц. {(sims < obs).mean()*100:.1f}")


for name in sys.argv[1:]:
    for side, sl in (("down", "ЛОНГ"), ("up", "ШОРТ")):
        b = prep(name, side)
        if "d_bull" not in b:
            print("нет контекста в", name); break
        b = b[b.d_bull.notna()]
        v2 = b[b.fractal_ok & (b.depth5 >= 0.5)]
        print(f"\n===== {name} · {sl} · база n={len(b)} · v2 n={len(v2)}")
        for tag, g in (("v2", v2), ("фрактал", b[b.fractal_ok])):
            print(f"-- {tag}")
            line(g, "  все")
            db = g.d_bull.astype(bool)
            line(g[db], "  дневная структура БЫЧЬЯ (последний слом bull)"); line(g[~db], "  дневная структура МЕДВЕЖЬЯ")
            br = g.d_broke.astype(bool)
            line(g[br], "  пятёрка ПРОБИЛА дневной свинг (дневной слом)"); line(g[~br], "  пятёрка НЕ пробила дневной свинг (коррекция)")
            ft = g.d_from_top.astype(bool)
            line(g[ft], "  импульс из-за дневного экстремума"); line(g[~ft], "  импульс изнутри дневной структуры")
            if side == "down":
                line(g[db & ~br], "  бычья 1D + не пробила (дневная коррекция 2/4)"); line(g[~db & br], "  медвежья 1D + пробила (дневная 3/5 вниз)")
                line(g[db & br], "  бычья 1D + пробила"); line(g[~db & ~br], "  медвежья 1D + не пробила")
                line(g[g.d_wt < -45], "  дневной WT < −45 (дневная перепроданность)"); line(g[g.d_wt >= -45], "  дневной WT ≥ −45")
            else:
                line(g[~db & ~br], "  медвежья 1D + не пробила (дневная коррекция вверх)"); line(g[db & br], "  бычья 1D + пробила (дневная 1/3 вверх — MEW)")
                line(g[db & ~br], "  бычья 1D + не пробила"); line(g[~db & br], "  медвежья 1D + пробила")
                line(g[g.d_wt > 45], "  дневной WT > 45 (дневная перекупленность)"); line(g[g.d_wt <= 45], "  дневной WT ≤ 45")
            st = g.d_st.astype(int)
            line(g[st == 1], "  supertrend 1D вверх"); line(g[st == -1], "  supertrend 1D вниз")
            if tag == "v2":
                sel(g, db, "бычья 1D"); sel(g, ~br, "не пробила"); sel(g, db & ~br, "бычья+не пробила")
                if side == "down": sel(g, g.d_wt < -45, "WT1D<-45")
                else: sel(g, ~db & ~br, "медвежья+не пробила")
