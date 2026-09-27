"""Внутренняя пятиволновка ВОЛНЫ 5 (идея Егора 13.09: «ловить внутренние 5-волновые структуры»).
Для готовых сделок 4h→5m: на 5m-ряде от точки 4 до бара кросса j ищем 5 свингов OKO-SM мелкого масштаба
по направлению импульса с provisional точкой 5 = экстремум; считаем внутренний канал. Каузально: только бары ≤ j.
Флаг inner5 = внутренняя структура завершена (5 подволн + w3≥w1 + внутренний depth5 ≥ 0.5)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import load, impulses_on_bar, _swings, TF_MIN
from channel_depth import add_geom, SP

INNER_SW = int(sys.argv[1]) if len(sys.argv) > 1 else 12   # свинг младшего масштаба на 5m (12 = 1 ч)
PKL = sys.argv[2] if len(sys.argv) > 2 else "wave5sm_4h_5m_sw20_hold240_z45.pkl"


def inner_depth(w_idx, w_px, up):
    xi = [float(v) for v in w_idx]; px = [float(v) for v in w_px]; sgn = 1.0 if up else -1.0
    slope = (px[4] - px[2]) / (xi[4] - xi[2]) if xi[4] > xi[2] else 0.0
    width = sgn * (px[3] - (px[2] + slope * (xi[3] - xi[2])))
    depth = sgn * (px[5] - (px[4] + slope * (xi[5] - xi[4])))
    return depth / width if width > 0 else np.nan


d = pd.read_pickle(SP + PKL); d = d[d.pnl_w4.notna()].copy()
for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
    d[c] = d[c].astype(bool)
d = add_geom(d)
base = d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1].copy()
print(f"база лонг n={len(base)}, монет {base.sym.nunique()}, внутренний свинг {INNER_SW} баров 5m")
rows = []
cache = {}
for sym, g in base.groupby("sym"):
    dh = load(sym, "4h"); dl = load(sym, "5m")
    if dl.empty:
        continue
    idx_h = dh.index; lt = dl.index.values.astype("datetime64[ns]")
    hh, ll = dl.high.values.astype(float), dl.low.values.astype(float)
    for i, r in g.iterrows():
        w_idx = list(r.wave_idx); up = r.dir == "up"
        t4 = np.datetime64(idx_h[int(w_idx[4])].to_datetime64())
        j0 = int(np.searchsorted(lt, t4)); j = int(r.j)
        if j - j0 < 6 * INNER_SW:
            rows.append({"i": i, "inner_n": 0, "inner5": False, "inner_depth": np.nan, "inner_len": j - j0}); continue
        seg_h = pd.Series(hh[j0:j + 1]); seg_l = pd.Series(ll[j0:j + 1])
        sw = _swings(seg_h, seg_l, INNER_SW)
        t = len(seg_h) - 1
        imps = impulses_on_bar(sw, t, seg_h.values, seg_l.values)
        # нужна пятиволновка ПО НАПРАВЛЕНИЮ старшего импульса, чья точка 0 близка к точке 4 старшего
        ok, dep = False, np.nan
        for imp in imps:
            if imp["direction"] != r.dir:
                continue
            wi = [int(x[0]) for x in imp["waves"]]; wp = [float(x[1]) for x in imp["waves"]]
            if wi[0] > 0.35 * t:          # подимпульс должен начинаться у начала волны 5
                continue
            dep = inner_depth(wi, wp, up)
            ok = imp["w3_ext"] >= 1.0 and np.isfinite(dep) and dep >= 0.5
            break
        rows.append({"i": i, "inner_n": len(imps), "inner5": ok, "inner_depth": dep, "inner_len": j - j0})
f = pd.DataFrame(rows).set_index("i")
base = base.join(f)
base["R"] = base.pnl_w4 / base.sl_pct
print(f"подимпульс найден у {(base.inner_n > 0).mean()*100:.0f}% · inner5 у {base.inner5.mean()*100:.0f}% · длина волны 5 медиана {base.inner_len.median()/12:.0f} ч")


def line(g, lbl):
    if len(g) < 8:
        print(f"{lbl:<44} n={len(g)} мало"); return
    print(f"{lbl:<44} n={len(g):3d} на сд {g.pnl_w4.mean():+.2f}% R {g.R.mean():+.2f} медR {g.R.median():+.2f} дошли {g.hit_w4.mean()*100:.0f}% "
          f"безтоп10 {g.pnl_w4.sort_values(ascending=False).iloc[int(len(g)*0.1):].mean():+.2f} монет+ {(g.groupby('sym').pnl_w4.sum()>0).mean()*100:.0f}%")


v2 = base[base.fractal_ok & (base.depth5 >= 0.5)]
for tag, g in (("база", base), ("фрактал", base[base.fractal_ok]), ("v2 (фрактал+канал)", v2)):
    print(f"--- {tag}")
    line(g[g.inner5 == True], "  внутренняя пятиволновка завершена")
    line(g[(g.inner5 == False) & (g.inner_n > 0)], "  подимпульс есть, не завершён (канал<0.5/w3<w1)")
    line(g[g.inner_n == 0], "  подимпульса нет (волна 5 без 5 подволн)")
    if tag == "v2":
        for lo, hi in ((-9, 0.3), (0.3, 0.6), (0.6, 99)):
            line(g[(g.inner_depth >= lo) & (g.inner_depth < hi)], f"  внутренний канал [{lo},{hi})")
base.to_pickle(SP + f"inner5_{INNER_SW}.pkl")
