"""Стоп для достроенного входа (line24): на готовых входах меняем ТОЛЬКО стоп, вход/цель/удержание те же.
Варианты: A за экстремум пятой (текущий) · B под последний подтверждённый младший свинг 15m (len=SWL) до входа ·
C минимум последних N часов до входа · D половина расстояния до экстремума · E под линию 2-4 на баре входа − буфер ·
F 1.5×ATR(14, 4h) от входа. Каузально: всё по барам ≤ j."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import load, _swings, TF_MIN
from channel_depth import add_geom, SP
from alternation import prep as prep_alt

PKL = sys.argv[1] if len(sys.argv) > 1 else "wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl"
COST = 0.10; BUF = 0.0015
d = prep_alt(PKL)                       # лонг, gone≤25%, w3≥w1, + чередование/счёт поля
d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
d["altern"] = d.alt_sharp_flat | d.alt_form
d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
sets = {"фрактал+канал (100)": d[d.fractal_ok & (d.depth5 >= 0.5)],
        "полный набор (67)": d[d.fractal_ok & (d.depth5 >= 0.5) & d.altern & d.count_ok]}
htf, ltf = d.htf.iloc[0], d.ltf.iloc[0]; bpm = 60 // TF_MIN[ltf]


def walk(h, l, c, j1, e, sl, tp, end):
    for k in range(j1, end + 1):
        if l[k] <= sl: return (sl - e) / e * 100 - COST, "stop"
        if h[k] >= tp: return (tp - e) / e * 100 - COST, "tp"
    return (c[end] - e) / e * 100 - COST, "time"


rows = []
cache = {}
for sym, g in pd.concat(sets.values()).drop_duplicates(["sym", "ts"]).groupby("sym"):
    dl = load(sym, ltf); dh = load(sym, htf)
    h, l, c, o = dl.high.values.astype(float), dl.low.values.astype(float), dl.close.values.astype(float), dl.open.values.astype(float)
    lt = dl.index.values.astype("datetime64[ns]"); idx_h = dh.index
    # ATR(14) на 4h
    hh, lh, ch = dh.high.values.astype(float), dh.low.values.astype(float), dh.close.values.astype(float)
    tr = np.maximum(hh[1:] - lh[1:], np.maximum(abs(hh[1:] - ch[:-1]), abs(lh[1:] - ch[:-1]))); atr = pd.Series(tr).rolling(14).mean().values
    for _, r in g.iterrows():
        j = int(r.j); e = float(o[j + 1]); tp = float(r.p4); end = min(len(dl) - 1, j + 1 + int(r.hold))
        if e <= 0 or tp <= e: continue
        stops = {"A: за экстремум пятой": float(r.sl)}
        # B: последний подтверждённый младший свинг-лоу на LTF до j (несколько масштабов)
        seg_lo = max(0, j - 96 * 4); sh = pd.Series(h[seg_lo:j + 1]); sl_ = pd.Series(l[seg_lo:j + 1])
        for swl in (4, 8, 16):
            sw = [s for s in _swings(sh, sl_, swl) if (not s[3]) and s[0] + seg_lo <= j]
            if sw:
                lvl = float(sw[-1][2]) * (1 - BUF)
                if lvl < e: stops[f"B: свинг 15m len={swl} ({swl*15//60}ч)"] = lvl
        # C: минимум последних N часов
        for nh in (12, 24, 48):
            lvl = float(l[max(0, j - nh * bpm):j + 1].min()) * (1 - BUF)
            if lvl < e: stops[f"C: минимум {nh} ч"] = lvl
        # D: половина / треть расстояния до экстремума пятой
        stops["D: 0.5 расстояния до экстремума"] = e - 0.5 * (e - float(r.sl))
        stops["D: 0.33 расстояния до экстремума"] = e - 0.33 * (e - float(r.sl))
        # E: под линию 2-4 на баре входа
        w_idx = [int(x) for x in r.wave_idx]; w_px = [float(x) for x in r.wave_px]
        x2, x4 = float(w_idx[2]), float(w_idx[4]); y2, y4 = w_px[2], w_px[4]
        slope = (y4 - y2) / (x4 - x2) if x4 > x2 else 0.0
        pos_h = x4 + (lt[j] - np.datetime64(idx_h[int(x4)].to_datetime64())) / np.timedelta64(TF_MIN[htf], "m")
        line = y4 + slope * (pos_h - x4)
        for bufl in (0.01, 0.02):
            lvl = line * (1 - bufl)
            if lvl < e: stops[f"E: под линию 2-4 −{int(bufl*100)}%"] = lvl
        # F: ATR
        th = int(np.searchsorted(idx_h.values.astype("datetime64[ns]"), lt[j], side="right")) - 2   # последний закрытый 4h
        if th >= 14 and np.isfinite(atr[th - 1]):
            for m in (1.0, 1.5, 2.0):
                stops[f"F: {m}×ATR(14) 4h"] = e - m * atr[th - 1]
        for name, sl in stops.items():
            if sl >= e: continue
            pnl, how = walk(h, l, c, j + 1, e, sl, tp, end)
            rows.append({"sym": sym, "ts": r.ts, "stop": name, "sl_pct": (e - sl) / e * 100, "pnl": pnl, "how": how, "R": pnl / ((e - sl) / e * 100), "year": r.year})
f = pd.DataFrame(rows)
for tag, s in sets.items():
    keys = set(zip(s.sym, s.ts)); g = f[[k in keys for k in zip(f.sym, f.ts)]]
    print(f"\n===== {tag} · достроенный вход · цель w4 · удержание ≤240 ч")
    out = []
    for name, x in g.groupby("stop"):
        ep = x.groupby(pd.to_datetime(x.ts).dt.strftime("%Y-%m-%d")).pnl.mean()
        out.append({"стоп": name, "n": len(x), "стоп%": x.sl_pct.median(), "на сд%": x.pnl.mean(), "R": x.R.mean(), "медR": x.R.median(), "WR%": (x.pnl > 0).mean() * 100,
                    "цель%": (x.how == "tp").mean() * 100, "стоп-аут%": (x.how == "stop").mean() * 100, "безтоп10": x.pnl.sort_values(ascending=False).iloc[int(len(x) * 0.1):].mean(),
                    "монет+%": (x.groupby("sym").pnl.sum() > 0).mean() * 100, "дней+%": (ep > 0).mean() * 100, "мед.дня": ep.median(), "сумR": x.R.sum(),
                    "годы": " ".join(f"{str(y)[2:]}:{v.R.mean():+.2f}" for y, v in x.groupby("year"))})
    print(pd.DataFrame(out).sort_values("R", ascending=False).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))
