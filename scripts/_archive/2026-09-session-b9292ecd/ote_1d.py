"""Егор 14.09 (RECALL 1D): 4h-пятёрка вниз = волна C дневной коррекции; сильный слом — когда пятая в OTE (0.62-0.79)
предыдущей ДНЕВНОЙ ноги вверх; цели — ретест дневного хая и расширения.
Нога: последний подтверждённый (к моменту t) дневной свинг-минимум L, образовавшийся ДО начала пятёрки (a), и максимум H
от L до p5. Глубина = (H − p5)/(H − L). Вход и стоп — как в базе (кросс WT 15m, стоп за пятой).
Цели: W4 (как было) · H (ретест дневного хая) · 0.382/0.5 коррекции от H до p5 · H + 0.272·(H−L).
Удержание 240 ч и 720 ч. Контроль: 30 случайных входов в окне 72 ч от детекции, тот же % стопа и % до цели."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import load, TF_MIN, _swings

COST, NCTL = 0.10, 30
rng = np.random.default_rng(23)
from alternation import prep as prep_alt
d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl")          # лонги ядра (как во всех лабах)
print("сетапов:", len(d), d.year.value_counts().sort_index().to_dict())


def walk(h, l, c, k0, e, sl, tp, end):
    for k in range(k0, end + 1):
        if l[k] <= sl: return (sl - e) / e * 100 - COST, "stop"
        if h[k] >= tp: return (tp - e) / e * 100 - COST, "tp"
    return (c[end] - e) / e * 100 - COST, "time"


rows = []
for sym, g in d.groupby("sym"):
    dh = load(sym, "4h"); dl = load(sym, "15m")
    ih = dh.index; hh, lh = dh.high.values.astype(float), dh.low.values.astype(float)
    dd = dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    dsw = _swings(dd["high"], dd["low"], 10)            # (conf_i, sw_i, price, is_top) в днях
    dt = dd.index
    h, l, c, o = (dl[k].values.astype(float) for k in ("high", "low", "close", "open")); lt = dl.index.values.astype("datetime64[ns]")
    for _, r in g.iterrows():
        a, b, t, j = int(r.a), int(r.b), int(r.t), int(r.j)
        now = ih[t] + pd.Timedelta(hours=4)
        lows = [s for s in dsw if (not s[3]) and dt[int(s[0])] + pd.Timedelta(days=1) <= now and dt[int(s[1])] < ih[a]]
        if not lows:
            continue
        Ld = lows[-1]; L = float(Ld[2]); tL = dt[int(Ld[1])]
        kL = int(np.searchsorted(ih, tL))
        H = float(hh[kL:b + 1].max()); p5 = float(r.p5)
        if H <= L or p5 <= L * 0.5:
            continue
        depth = (H - p5) / (H - L)
        e = float(o[j + 1]); sl = float(r.sl)
        if not (sl < e):
            continue
        tg = {"W4": float(r.p4), "c382": p5 + .382 * (H - p5), "c500": p5 + .5 * (H - p5), "H": H, "H+0.272": H + .272 * (H - L), "H+0.62": H + .62 * (H - L), "H+1.0": H + 1.0 * (H - L)}
        risk = (e - sl) / e * 100
        rec = dict(sym=sym, ts=r.ts, year=r.year, depth=depth, risk=risk, fc=bool(r.fractal_ok and r.depth5 >= 0.5),
                   rrH=(H - e) / (e - sl), day=str(pd.Timestamp(r.ts).date()))
        j0 = int(np.searchsorted(lt, (ih[t] + pd.Timedelta(hours=4)).to_datetime64()))
        for hold in (720,):
            end = min(len(dl) - 1, j + 1 + hold * 4)
            for n, tp in tg.items():
                if tp <= e:
                    rec[f"{n}_{hold}"] = np.nan; continue
                p, how = walk(h, l, c, j + 1, e, sl, tp, end)
                rec[f"{n}_{hold}"] = p; rec[f"hit_{n}_{hold}"] = how == "tp"
                if hold == 720 and n in ("W4", "H"):
                    cp = []
                    for kr in rng.integers(j0, min(j0 + 72 * 4, len(dl) - 2), NCTL):
                        er = float(o[kr + 1]); cp.append(walk(h, l, c, kr + 1, er, er * (1 - risk / 100), er * tp / e, min(len(dl) - 1, kr + 1 + hold * 4))[0])
                    rec[f"ctl_{n}_{hold}"] = np.mean(cp)
        rows.append(rec)
f = pd.DataFrame(rows); f.to_pickle("ote_1d.pkl")
f["zone"] = pd.cut(f.depth, [-9, .382, .62, .79, 1.0, 9], labels=["<0.382", "0.382-0.62", "OTE 0.62-0.79", "0.79-1.0", ">1 (ниже L)"])
print(f"\nс дневной ногой: {len(f)} · доля в OTE: {(f.zone == 'OTE 0.62-0.79').mean()*100:.0f}%")
for tag, x in (("вся база", f), ("фрактал+канал", f[f.fc])):
    print(f"\n===== {tag} · лонг 2023-26 · вход кросс 15m, стоп за пятой")
    out = []
    for z, g in x.groupby("zone", observed=True):
        rr = {"зона": z, "n": len(g), "стоп%": g.risk.median(), "RR→H": g.rrH.median()}
        for n in ("W4_720", "c382_720", "H_720", "H+0.272_720", "H+0.62_720", "H+1.0_720"):
            rr[n] = g[n].mean() if n in g else np.nan
        rr["hitH%"] = g["hit_H_720"].mean() * 100
        rr["ctl W4"] = g["ctl_W4_720"].mean(); rr["ctl H"] = g["ctl_H_720"].mean()
        rr["без топ10 H"] = g["H_720"].dropna().sort_values(ascending=False).iloc[int(len(g) * .1):].mean()
        rr["годы H"] = " ".join(f"{str(y)[2:]}:{v['H_720'].mean():+.1f}/{len(v)}" for y, v in g.groupby("year"))
        out.append(rr)
    print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))
