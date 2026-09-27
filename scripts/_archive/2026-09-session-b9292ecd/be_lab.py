"""БУ-лаборатория (Егор 14.09, RECALL: «с такими движениями можно стоп переводить в БУ без зазрения совести»).
На готовых входах ядра (line24 и кросс) меняем ТОЛЬКО правило ведения стопа. Вход, цель = конец w4, удержание ≤240 ч —
те же. Варианты:
  A  держать стоп за экстремумом пятой до конца (текущее)
  BE k   перенос стопа в цену входа, когда ход в плюс достиг k × расстояния до стопа (k = 0.5, 1, 1.5, 2)
  BE 382 перенос в БУ при касании corr_382 (первая цель коррекции по фибо)
  TR k   после k × стопа — трейлинг под минимум последних 24 ч 15m (обновляется только вверх)
Каузально: всё по барам ≤ k, стоп проверяется ПРЕЖДЕ цели на том же баре (консервативно).
Печатается ключевое: сколько сделок БУ/трейл забирают из тех, что при A дошли до цели."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import load, TF_MIN, _swings
from alternation import prep as prep_alt

COST = 0.10
out_all = []
for PKL, tag_e in (("wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl", "line24"),
                   ("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", "кросс")):
    d = prep_alt(PKL)
    d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
    d["altern"] = d.alt_sharp_flat | d.alt_form
    d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
    sets = {"фрактал+канал": d[d.fractal_ok & (d.depth5 >= 0.5)],
            "полный набор": d[d.fractal_ok & (d.depth5 >= 0.5) & d.altern & d.count_ok],
            "вся база": d}
    htf, ltf = d.htf.iloc[0], d.ltf.iloc[0]; bpm = 60 // TF_MIN[ltf]

    def walk(h, l, c, j1, e, sl0, tp, end, mode, k=0.0, lvl382=None, sw=None):
        sl = sl0; risk = e - sl0; armed = False; mfe = 0.0
        tops = [x for x in (sw or []) if x[3]]; bots = [x for x in (sw or []) if not x[3]]
        for kk in range(j1, end + 1):
            if l[kk] <= sl:
                return (sl - e) / e * 100 - COST, ("be" if armed and sl >= e else "stop")
            if h[kk] >= tp:
                return (tp - e) / e * 100 - COST, "tp"
            mfe = max(mfe, h[kk] - e)
            if mode in ("sbe", "sst"):
                # слом вверх: high пробил последний ПОДТВЕРЖДЁННЫЙ (conf ≤ kk) младший top, сформированный после входа
                ct = [x for x in tops if x[0] <= kk and x[1] >= j1]
                if ct and h[kk] > float(ct[-1][2]):
                    cb = [x for x in bots if x[0] <= kk and x[1] >= j1]
                    if mode == "sbe":
                        sl = max(sl, e); armed = True
                    elif cb:
                        sl = max(sl, float(cb[-1][2]) * (1 - 0.0015)); armed = sl >= e or armed
            if mode == "be" and not armed and mfe >= k * risk:
                sl = e; armed = True
            elif mode == "be382" and not armed and lvl382 is not None and h[kk] >= lvl382:
                sl = e; armed = True
            elif mode == "tr" and mfe >= k * risk:
                armed = True
                lo = float(l[max(j1, kk - 24 * bpm):kk + 1].min())
                sl = max(sl, e, lo)
        return (c[end] - e) / e * 100 - COST, "time"

    rows = []
    for sym, g in d.groupby("sym"):
        dl = load(sym, ltf)
        h, l, c, o = dl.high.values.astype(float), dl.low.values.astype(float), dl.close.values.astype(float), dl.open.values.astype(float)
        for _, r in g.iterrows():
            j = int(r.j); e = float(o[j + 1]); tp = float(r.p4); sl0 = float(r.sl); end = min(len(dl) - 1, j + 1 + int(r.hold))
            if e <= 0 or tp <= e or sl0 >= e:
                continue
            lvl382 = float(r.p5) + 0.382 * (float(r.p0) - float(r.p5))
            variants = [("A: стоп за пятой до конца", "a", 0, None)]
            variants += [(f"BE после {k}×стопа", "be", k, None) for k in (0.5, 1.0, 1.5, 2.0)]
            variants += [("BE при касании corr_382", "be382", 0, lvl382)]
            variants += [(f"трейл 24ч после {k}×стопа", "tr", k, None) for k in (1.0, 2.0)]
            # структура 15m после входа: свинги len 4/8/16 (1/2/4 ч) на окне вход..конец, каузально по conf_i
            seg0 = max(0, j + 1 - 200); seg1 = end
            sws = {}
            for L in (4, 8, 16):
                sws[L] = [(x[0] + seg0, x[1] + seg0, x[2], x[3]) for x in _swings(pd.Series(h[seg0:seg1 + 1]), pd.Series(l[seg0:seg1 + 1]), L)]
                variants += [(f"структ.БУ: слом 15m len={L} → стоп в БУ", "sbe", L, None), (f"структ.стоп: слом 15m len={L} → под младший low", "sst", L, None)]
            base = None
            for name, mode, k, lv in variants:
                pnl, how = walk(h, l, c, j + 1, e, sl0, tp, end, mode, k, lv, sws.get(int(k)) if mode in ("sbe", "sst") else None)
                if mode == "a":
                    base = how
                rows.append({"sym": sym, "ts": r.ts, "v": name, "pnl": pnl, "how": how, "R": pnl / ((e - sl0) / e * 100),
                             "year": r.year, "base_how": base, "sl_pct": (e - sl0) / e * 100})
    f = pd.DataFrame(rows)
    for tag, s in sets.items():
        keys = set(zip(s.sym, s.ts)); x = f[[kk in keys for kk in zip(f.sym, f.ts)]]
        if x.empty:
            continue
        print(f"\n===== вход {tag_e} · {tag} (n={x.v.eq('A: стоп за пятой до конца').sum()}) · цель w4 · ≤240 ч")
        out = []
        for name, g in x.groupby("v", sort=False):
            ep = g.groupby(pd.to_datetime(g.ts).dt.strftime("%Y-%m-%d")).pnl.mean()
            killed = ((g.base_how == "tp") & (g.how != "tp")).sum()       # при A дошли до цели, здесь — нет
            saved = ((g.base_how == "stop") & (g.how != "stop") & (g.pnl > -0.5)).sum()   # при A стоп, здесь спасены
            out.append({"ведение": name, "на сд%": g.pnl.mean(), "R": g.R.mean(), "медR": g.R.median(), "WR%": (g.pnl > 0).mean() * 100,
                        "цель%": (g.how == "tp").mean() * 100, "стоп%": (g.how == "stop").mean() * 100, "БУ%": (g.how == "be").mean() * 100,
                        "убито целей": killed, "спасено от стопа": saved,
                        "безтоп10": g.pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):].mean(),
                        "дней+%": (ep > 0).mean() * 100, "сумR": g.R.sum(),
                        "годы": " ".join(f"{str(y)[2:]}:{v.R.mean():+.2f}" for y, v in g.groupby("year"))})
        print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))
