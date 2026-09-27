"""Вложенная инвалидация (Егор 14.09, RECALL 15m: «вот и думай где сетап инвалидируется»).
После пятой: CHoCH вверх на старшем слое LTF (swing, «CHoCH 15m») = микро-w1 → откат держится выше p5 →
CHoCH вверх на младшем слое (internal, «CHoCH 3m») = конец микро-w2 → стоп под минимум микро-w2 (более высокий минимум).
Режимы:  first — один перенос (под w2) · trail — каждый следующий internal bull CHoCH с более высоким минимумом поднимает стоп.
Контроль: noswing — то же без требования CHoCH старшего слоя (только internal).
3m в кэше на 42 монетах → младший слой = internal-свинги OKO-SM на 15m (len 3/5). Вход, цель w4, ≤240 ч — как в ядре.
Каузально: событие известно на баре e.i, стоп действует со следующего бара; стоп проверяется прежде цели."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure

COST, BUF = 0.10, 0.0015
SCALES = [(20, 3), (20, 5), (50, 5)]


def walk(h, l, c, j1, e, sl0, tp, end, ev, i5, p5, mode):
    sl = sl0; moved = 0
    sw = {x.i for x in ev if (not x.internal) and x.bull and x.kind == "CHoCH" and x.i > i5}
    it = {x.i for x in ev if x.internal and x.bull and x.kind == "CHoCH" and x.i > i5}
    c1 = None if mode != "noswing" else i5; last = None
    # события до входа — применяем сразу на j1 (всё ≤ j1-1 известно)
    for kk in range(i5 + 1, end + 1):
        if kk >= j1:
            if l[kk] <= sl:
                return (sl - e) / e * 100 - COST, ("stop" if sl < e else "be+"), moved, sl
            if h[kk] >= tp:
                return (tp - e) / e * 100 - COST, "tp", moved, sl
        if c1 is None and sw and kk in sw:
            c1 = kk
        if c1 is not None and kk in it and kk > c1:
            a = c1 if last is None else last
            lo = float(l[a:kk + 1].min())
            if lo > p5 and (mode == "trail" or moved == 0):
                ns = lo * (1 - BUF)
                if ns > sl and ns < c[kk]:
                    sl = ns; moved += 1
            last = kk
    return (c[end] - e) / e * 100 - COST, "time", moved, sl


rows = []
for PKL, tag_e in (("wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl", "line24"),
                   ("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", "кросс")):
    d = prep_alt(PKL)
    d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
    d["altern"] = d.alt_sharp_flat | d.alt_form
    d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
    d["full"] = d.fractal_ok & (d.depth5 >= 0.5) & d.altern & d.count_ok
    d = d[d.fractal_ok & (d.depth5 >= 0.5)]
    htf, ltf = d.htf.iloc[0], d.ltf.iloc[0]
    for sym, g in d.groupby("sym"):
        dl = load(sym, ltf); dh = load(sym, htf)
        h, l, c, o = (dl[k].values.astype(float) for k in ("high", "low", "close", "open"))
        lt = dl.index.values.astype("datetime64[ns]"); ih = dh.index.values.astype("datetime64[ns]")
        for _, r in g.iterrows():
            j = int(r.j); e = float(o[j + 1]); tp = float(r.p4); sl0 = float(r.sl); end = min(len(dl) - 1, j + 1 + int(r.hold))
            if e <= 0 or tp <= e or sl0 >= e:
                continue
            t5 = ih[int(r.b)]; a5 = int(np.searchsorted(lt, t5)); b5 = int(np.searchsorted(lt, t5 + np.timedelta64(TF_MIN[htf], "m")))
            if b5 <= a5 or b5 > j + 1:
                continue
            i5 = a5 + int(l[a5:b5].argmin()); p5 = float(l[i5])
            w0 = max(0, i5 - 400)
            base = dict(sym=sym, ts=r.ts, year=r.year, entry=tag_e, full=bool(r.full), risk=(e - sl0) / e * 100)
            pa, ha, _, _ = walk(h, l, c, j + 1, e, sl0, tp, end, [], i5, p5, "first")
            rows.append({**base, "v": "A: стоп за пятой", "pnl": pa, "how": ha, "base": ha, "moved": 0, "new_risk": base["risk"]})
            for S, I in SCALES:
                st = run_structure(dl.iloc[w0:end + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=S, internal_len=I)
                ev = [type("E", (), dict(i=x.i + w0, bull=x.bull, internal=x.internal, kind=x.kind)) for x in st.events]
                for mode in ("first", "trail", "noswing"):
                    p, hw, mv, sl = walk(h, l, c, j + 1, e, sl0, tp, end, ev, i5, p5, mode)
                    rows.append({**base, "v": f"{mode} · swing{S}/int{I}", "pnl": p, "how": hw, "base": ha, "moved": mv,
                                 "new_risk": (e - sl) / e * 100})
    print(f"[{tag_e}] готово", flush=True)

f = pd.DataFrame(rows); f["R"] = f.pnl / f.risk
f.to_pickle("nested_inval.pkl")
for ent in ("line24", "кросс"):
    for tag, m in (("фрактал+канал", slice(None)), ("полный набор", "full")):
        x = f[f.entry == ent]; x = x[x.full] if m == "full" else x
        n = (x.v == "A: стоп за пятой").sum()
        print(f"\n===== вход {ent} · {tag} (n={n}) · лонг 2023-26 · цель w4 · ≤240 ч")
        out = []
        for name, g in x.groupby("v", sort=False):
            ep = g.groupby(pd.to_datetime(g.ts).dt.strftime("%Y-%m-%d")).pnl.mean()
            out.append({"ведение": name, "на сд%": g.pnl.mean(), "R": g.R.mean(), "WR%": (g.pnl > 0).mean() * 100,
                        "цель%": (g.how == "tp").mean() * 100, "стоп<вход%": (g.how == "stop").mean() * 100, "стоп≥вход%": (g.how == "be+").mean() * 100,
                        "перенос%": (g.moved > 0).mean() * 100, "риск→%": g[g.moved > 0].new_risk.median() if (g.moved > 0).any() else np.nan,
                        "риск было%": g[g.moved > 0].risk.median() if (g.moved > 0).any() else np.nan,
                        "убито целей": int(((g.base == "tp") & (g.how != "tp")).sum()),
                        "спасено": int(((g.base == "stop") & (g.how != "stop")).sum()),
                        "ср.убыток%": g[g.pnl < 0].pnl.mean(), "дней+%": (ep > 0).mean() * 100,
                        "годы R": " ".join(f"{str(y)[2:]}:{v.R.mean():+.2f}" for y, v in g.groupby("year"))})
        print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))
