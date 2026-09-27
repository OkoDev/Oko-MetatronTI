"""Егор 13.09: «чередование и вложенность работают везде — вопрос масштаба и соотношений внутри него».
Каузальные признаки по разметке (все точки известны на входе):
  ЧЕРЕДОВАНИЕ: w2 и w4 разнотипны по глубине (retr) и времени (баров): резкая = глубокая+быстрая, плоская = мелкая+долгая.
  ВЛОЖЕННОСТЬ 5-3-5-3: подсвингов младшего слоя в импульсных волнах ≥ чем в соседних коррекционных (ns1≥ns2, ns3≥ns4).
  СООТНОШЕНИЯ: w2∈[0.5,0.786], w4∈[0.236,0.5], w3≥w1, w5/w1∈[0.618,1.0]."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from channel_depth import add_geom, SP
pd.set_option("display.width", 230)


def prep(name, side="down"):
    d = pd.read_pickle(SP + name); d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d); d["R"] = d.pnl_w4 / d.sl_pct
    xi = np.array([[float(v) for v in w] for w in d.wave_idx]); px = np.array([[float(v) for v in w] for w in d.wave_px])
    d["t1"], d["t2"], d["t3"], d["t4"], d["t5"] = [xi[:, k + 1] - xi[:, k] for k in range(5)]
    # чередование: глубина
    d["alt_depth"] = (d.w2_retr - d.w4_retr).abs() >= 0.2                   # заметно разная глубина
    d["alt_time"] = ((d.t2 / d.t4) >= 1.5) | ((d.t4 / d.t2) >= 1.5)         # заметно разное время
    d["alt_sharp_flat"] = ((d.w2_retr > d.w4_retr) & (d.t2 < d.t4)) | ((d.w2_retr < d.w4_retr) & (d.t2 > d.t4))   # резкая vs плоская
    d["alt_full"] = d.alt_sharp_flat & d.alt_depth
    # вложенность 5-3-5-3
    if "ns1" in d:
        d["nest_13"] = (d.ns1 >= d.ns2) & (d.ns3 >= d.ns4)
        d["nest_strict"] = (d.ns1 > d.ns2) & (d.ns3 > d.ns4)
        d["nest_odd"] = (d.ns1 % 2 == 1) & (d.ns3 % 2 == 1)                 # нечётное число подсвингов в импульсных
    # соотношения
    d["r_w2"] = d.w2_retr.between(0.5, 0.786); d["r_w4"] = d.w4_retr.between(0.236, 0.5); d["r_w5"] = d.w5_w1.between(0.618, 1.0)
    d["ratios_all"] = d.r_w2 & d.r_w4 & d.r_w5
    return d[(d.dir == side) & (d.gone <= 0.25) & d.w3_ge_w1].copy()


def line(g, lbl):
    if len(g) < 12:
        print(f"{lbl:<46} n={len(g)} мало"); return
    ep = g.groupby(g.ts.dt.strftime("%Y-%m-%d")).pnl_w4.mean()
    print(f"{lbl:<46} n={len(g):3d} на сд {g.pnl_w4.mean():+.2f}% R {g.R.mean():+.2f} медR {g.R.median():+.2f} цель {g.hit_w4.mean()*100:.0f}% WR {(g.pnl_w4>0).mean()*100:.0f}% "
          f"безтоп10 {g.pnl_w4.sort_values(ascending=False).iloc[int(len(g)*0.1):].mean():+.2f} монет+ {(g.groupby('sym').pnl_w4.sum()>0).mean()*100:.0f}% дней+ {(ep>0).mean()*100:.0f}% мед.дня {ep.median():+.2f} "
          f"| " + " ".join(f"{y}:{x.pnl_w4.mean():+.1f}" for y, x in g.groupby("year")))


def sel(base, mask, lbl, n_sim=4000):
    sub = base[mask]
    if len(sub) < 15 or len(sub) > len(base) - 10:
        print(f"    отбор {lbl}: n={len(sub)} — пропуск"); return
    rs = np.random.RandomState(11); dif = (base.pnl_w4 - base.ctl_w4).values; obs = (sub.pnl_w4 - sub.ctl_w4).mean()
    sims = np.array([rs.choice(dif, len(sub), replace=False).mean() for _ in range(n_sim)])
    pn = base.pnl_w4.values; obs2 = sub.pnl_w4.mean(); sims2 = np.array([rs.choice(pn, len(sub), replace=False).mean() for _ in range(n_sim)])
    print(f"    отбор {lbl}: n={len(sub)} перевес перц. {(sims<obs).mean()*100:5.1f} · на сд перц. {(sims2<obs2).mean()*100:5.1f}")


for name, tag in (("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", "4h→15m 15/4 · кросс"),
                  ("wave5sm_4h_15m_sw20_hold240_z45.pkl", "4h→15m 20/5 · кросс"),
                  ("wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl", "4h→15m 15/4 · линия 2-4")):
    b = prep(name); f = b[b.fractal_ok]; v2 = f[f.depth5 >= 0.5]
    print(f"\n===== {tag} · ЛОНГ · база {len(b)} · фрактал {len(f)} · v2 {len(v2)} · чередование(резкая/плоская) у {b.alt_sharp_flat.mean()*100:.0f}% · вложенность 5-3-5-3 у {b.nest_13.mean()*100:.0f}%")
    for tg, g in (("ФРАКТАЛ", f), ("V2", v2)):
        print(f"-- {tg}")
        line(g, "  все")
        line(g[g.alt_sharp_flat], "  чередование: резкая/плоская ✓"); line(g[~g.alt_sharp_flat], "  чередование ✗ (однотипные 2 и 4)")
        line(g[g.alt_full], "  чередование полное (тип + глубина ≥0.2)")
        line(g[g.alt_time], "  чередование по времени (×1.5)"); line(g[~g.alt_time], "  время 2 ≈ время 4")
        line(g[g.nest_13], "  вложенность ns1≥ns2 & ns3≥ns4 ✓"); line(g[~g.nest_13], "  вложенность ✗")
        line(g[g.nest_strict], "  вложенность строгая (>)")
        line(g[g.ratios_all], "  соотношения все (w2,w4,w5) ✓"); line(g[~g.ratios_all], "  соотношения ✗")
        line(g[g.alt_sharp_flat & g.nest_13], "  чередование ✓ + вложенность ✓")
        line(g[g.alt_sharp_flat & g.nest_13 & g.ratios_all], "  чередование + вложенность + соотношения")
        line(g[~g.alt_sharp_flat & ~g.nest_13], "  ни чередования, ни вложенности")
        sel(g, g.alt_sharp_flat, "чередование"); sel(g, g.alt_full, "чередование полное"); sel(g, g.nest_13, "вложенность")
        sel(g, g.alt_sharp_flat & g.nest_13, "чередование+вложенность"); sel(g, g.ratios_all, "соотношения")
    # эталон Егора
    for s, dt in (("NEAR/USDT", "2026-01-14"), ("ARKM/USDT", "2025-06-06"), ("DOGE/USDT", "2024-06-24"), ("ZK/USDT", "2025-12-01")):
        dd = pd.read_pickle(SP + name); dd = dd[(dd.sym == s) & (dd.ts.dt.strftime("%Y-%m-%d") == dt)]
        for _, r in dd.iterrows():
            xi = [float(v) for v in r.wave_idx]; t2, t4 = xi[2] - xi[1], xi[4] - xi[3]
            print(f"   эталон {s:<10} w2 {r.w2_retr:.2f}/{t2:.0f}б · w4 {r.w4_retr:.2f}/{t4:.0f}б · ns {r.ns1}/{r.ns2}/{r.ns3}/{r.ns4}/{r.ns5} → чередование {'✓' if ((r.w2_retr>r.w4_retr and t2<t4) or (r.w2_retr<r.w4_retr and t2>t4)) else '✗'} вложенность {'✓' if (r.ns1>=r.ns2 and r.ns3>=r.ns4) else '✗'}")
