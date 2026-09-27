"""Вложенный вход Егора на НАСТОЯЩЕМ 3m (1m-паркеты → 3m, 50 монет, 2025-01…2026-08) + прогнозные цели от микроструктуры.
Егор 14.09: «5m — не то же, что 3m; на 5m детектор может не увидеть, а там часто FVG и сильные подтверждения».
Разметка как на его RECALL: CHoCH 15m (микро-w1/A) → откат держится выше пятой (B) → CHoCH 3m → вход, стоп под B.
Варианты слома старшего слоя:  V1 15m internal(5) · V2 15m swing(50) · V3 3m swing(50);  младший слой всегда 3m internal(5).
Сравнение на тех же сетапах: V0 — всё на 15m (swing20/internal3), как в прошлом прогоне.
Цели от B: T1=B+1.0·A (C=A) · T1618 · T2618 · W4 (конец волны 4 старшей пятёрки). A = от пятой до максимума перед B.
FVG-срез: был ли бычий FVG на 3m в ноге слома (от B до бара входа).
Каузально: 15m-событие известно на закрытии своего бара; 3m-вход — open следующего 3m-бара; стоп прежде целей; косты 0.10%."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure

COST, BUF, WIN_H, HOLD_H, NCTL = 0.10, 0.0015, 72, 240, 30
rng = np.random.default_rng(13)
STRATS = {"S1 100% T1": [(1.0, "T1")], "S2 100% T1.618": [(1.0, "T1618")],
          "S3 50 T1 + 50 T1.618": [(.5, "T1"), (.5, "T1618")], "S4 50 T1 + 50 T2.618": [(.5, "T1"), (.5, "T2618")],
          "S5 ⅓·⅓·⅓": [(1/3, "T1"), (1/3, "T1618"), (1/3, "T2618")], "S0 100% W4": [(1.0, "W4")]}


def run_exit(h, l, c, k0, e, sl0, tg, legs, end):
    lv = [(fr, tg[n]) for fr, n in legs]
    if any(p <= e for _, p in lv):
        return None
    sl, taken, pnl = sl0, 0, 0.0
    for k in range(k0, end + 1):
        if l[k] <= sl:
            return pnl + sum(fr for fr, _ in lv[taken:]) * (sl - e) / e * 100 - COST
        while taken < len(lv) and h[k] >= lv[taken][1]:
            pnl += lv[taken][0] * (lv[taken][1] - e) / e * 100; taken += 1
            if len(lv) > 1:
                sl = e if taken == 1 else lv[taken - 2][1]
        if taken == len(lv):
            return pnl - COST
    return pnl + sum(fr for fr, _ in lv[taken:]) * (c[end] - e) / e * 100 - COST


def ladder(h, l, k0, e, sl, tg, end):
    out = {n: False for n in tg}
    for k in range(k0, end + 1):
        if l[k] <= sl:
            break
        for n, p in tg.items():
            if h[k] >= p:
                out[n] = True
    return out


def events(df, w0, w1, S, I):
    st = run_structure(df.iloc[w0:w1 + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=S, internal_len=I)
    sw = sorted(x.i + w0 for x in st.events if not x.internal and x.bull and x.kind == "CHoCH")
    it = sorted(x.i + w0 for x in st.events if x.internal and x.bull and x.kind == "CHoCH")
    return sw, it


d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl")
d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
d["altern"] = d.alt_sharp_flat | d.alt_form
d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
d["fc"] = d.fractal_ok & (d.depth5 >= 0.5)
d["full"] = d.fc & d.altern & d.count_ok
d = d[pd.to_datetime(d.ts) >= "2025-01-05"]
htf = d.htf.iloc[0]
rows = []; nsyms = 0
for sym, g in d.groupby("sym"):
    d3 = load(sym, "3m")
    if d3.empty:
        continue
    nsyms += 1
    d15 = load(sym, "15m"); dh = load(sym, htf)
    ih = dh.index.values.astype("datetime64[ns]")
    L = {}
    for tf, df in (("3m", d3), ("15m", d15)):
        L[tf] = dict(df=df, h=df.high.values.astype(float), l=df.low.values.astype(float), c=df.close.values.astype(float),
                     o=df.open.values.astype(float), t=df.index.values.astype("datetime64[ns]"), bpm=60 // TF_MIN[tf])
    for _, r in g.iterrows():
        t5 = ih[int(r.b)]; t5e = t5 + np.timedelta64(TF_MIN[htf], "m"); tdet = ih[int(r.t)] + np.timedelta64(TF_MIN[htf], "m")
        X3, X15 = L["3m"], L["15m"]
        a5 = int(np.searchsorted(X3["t"], t5)); b5 = int(np.searchsorted(X3["t"], t5e))
        if b5 <= a5 or a5 < 2000 or b5 + (WIN_H + HOLD_H) * 20 + 50 >= len(X3["t"]) or X3["t"][a5] - t5 > np.timedelta64(1, "h"):
            continue
        i5 = a5 + int(X3["l"][a5:b5].argmin()); p5 = float(X3["l"][i5]); tp5 = X3["t"][i5]
        j0 = int(np.searchsorted(X3["t"], tdet)); jw = j0 + WIN_H * 20
        base = dict(sym=sym, ts=r.ts, year=r.year, fc=bool(r.fc), full=bool(r.full), day=str(pd.Timestamp(r.ts).date()))
        # события: 3m (swing50/internal5) и 15m (swing50/internal5 для V1/V2, swing20/internal3 для V0)
        sw3, it3 = events(d3, i5 - 1500, jw, 50, 5)
        k15a = int(np.searchsorted(X15["t"], tp5)); k15w = int(np.searchsorted(X15["t"], X3["t"][jw])) + 1
        sw15, it15 = events(d15, max(0, k15a - 400), min(len(d15) - 1, k15w), 50, 5)
        sw15b, it15b = events(d15, max(0, k15a - 400), min(len(d15) - 1, k15w), 20, 3)
        close15 = lambda k: X15["t"][k] + np.timedelta64(15, "m")
        variants = {}
        c_i15 = [close15(k) for k in it15 if X15["t"][k] > tp5]
        c_s15 = [close15(k) for k in sw15 if X15["t"][k] > tp5]
        c_s3 = [X3["t"][k] + np.timedelta64(3, "m") for k in sw3 if k > i5]
        for name, cl in (("V1 15m int5 → 3m int5", c_i15), ("V2 15m swing50 → 3m int5", c_s15), ("V3 3m swing50 → 3m int5", c_s3)):
            if not cl:
                continue
            c1 = int(np.searchsorted(X3["t"], cl[0]))        # первый 3m-бар, открытый после закрытия слома
            prev = c1; ent = None
            for k in it3:
                if k < c1:
                    continue
                ib = prev + int(X3["l"][prev:k + 1].argmin()); lo = float(X3["l"][ib])
                if j0 <= k < jw and lo > p5:
                    ent = (k, ib, lo); break
                prev = k
            if ent:
                variants[name] = ("3m", ent, i5, p5)
        # V0 — всё на 15m
        i5b = int(np.searchsorted(X15["t"], t5)); i5b = i5b + int(X15["l"][i5b:i5b + 16].argmin()); p5b = float(X15["l"][i5b])
        j0b = int(np.searchsorted(X15["t"], tdet)); jwb = j0b + WIN_H * 4
        s0 = [k for k in sw15b if k > i5b]
        if s0:
            prev = s0[0]; ent = None
            for k in it15b:
                if k <= s0[0]:
                    continue
                ib = prev + int(X15["l"][prev:k + 1].argmin()); lo = float(X15["l"][ib])
                if j0b <= k < jwb and lo > p5b:
                    ent = (k, ib, lo); break
                prev = k
            if ent:
                variants["V0 15m swing20 → 15m int3"] = ("15m", ent, i5b, p5b)
        for name, (tf, (k, ib, B), ii5, pp5) in variants.items():
            X = L[tf]; h, l, c, o = X["h"], X["l"], X["c"], X["o"]; bpm = X["bpm"]
            if k + 1 >= len(o):
                continue
            a_top = float(h[ii5:ib + 1].max()); A = a_top - pp5
            e = float(o[k + 1]); sl = B * (1 - BUF)
            if A <= 0 or sl >= e:
                continue
            tg = {"T1": B + A, "T1618": B + 1.618 * A, "T2618": B + 2.618 * A, "W4": float(r.p4)}
            end = min(len(o) - 1, k + 1 + HOLD_H * bpm); risk = (e - sl) / e * 100
            fvg = bool(np.any(l[ib + 2:k + 1] > h[ib:k - 1])) if k - ib >= 3 else False
            rec = {**base, "v": name, "risk": risk, "w2": (a_top - B) / A, "rr1": (tg["T1"] - e) / (e - sl), "fvg": fvg,
                   "h_from5": (X["t"][k] - X["t"][ii5]) / np.timedelta64(1, "h"),
                   **{f"hit_{n}": v for n, v in ladder(h, l, k + 1, e, sl, tg, end).items()}}
            dist = {n: p / e - 1 for n, p in tg.items()}
            jj0 = j0 if tf == "3m" else j0b; jjw = jw if tf == "3m" else jwb
            for sn, legs in STRATS.items():
                rec[sn] = run_exit(h, l, c, k + 1, e, sl, tg, legs, end)
                cp = []
                for kr in rng.integers(jj0, jjw, NCTL):
                    er = float(o[kr + 1])
                    pr = run_exit(h, l, c, kr + 1, er, er * (1 - risk / 100), {n: er * (1 + dd) for n, dd in dist.items()}, legs,
                                  min(len(o) - 1, kr + 1 + HOLD_H * bpm))
                    if pr is not None:
                        cp.append(pr)
                rec["ctl " + sn] = np.mean(cp) if cp else np.nan
            rows.append(rec)
print(f"монет с 3m: {nsyms} · сетапов в окне 2025-01+: {len(d)}", flush=True)
f = pd.DataFrame(rows); f.to_pickle("nested_targets3m.pkl")
for tag, m in (("вся база", None), ("фрактал+канал", "fc"), ("полный набор", "full")):
    x = f if m is None else f[f[m]]
    print(f"\n===== {tag} · 2025-01…2026-07 · лонг · вложенный вход, стоп под B, цели от микроструктуры")
    for v, g in x.groupby("v"):
        print(f"\n--- {v}: n={len(g)} · стоп мед {g.risk.median():.2f}% · RR до T1 мед {g.rr1.median():.1f} · глубина B {g.w2.median():.2f} · ч от пятой {g.h_from5.median():.0f} · FVG в ноге {g.fvg.mean()*100:.0f}%")
        print("    ЛЕСТНИЦА до стопа: " + " · ".join(f"{n} {g['hit_' + n].mean() * 100:.0f}%" for n in ("T1", "T1618", "T2618", "W4")))
        out = []
        for sn in STRATS:
            s = g[sn].dropna()
            if len(s) < 5:
                continue
            R = s / g.loc[s.index, "risk"]; gg = g.loc[s.index].assign(p=s)
            out.append({"выход": sn, "n": len(s), "на сд%": s.mean(), "контроль%": gg["ctl " + sn].mean(), "R": R.mean(), "медR": R.median(),
                        "WR%": (s > 0).mean() * 100, "безтоп10%": s.sort_values(ascending=False).iloc[int(len(s) * .1):].mean(),
                        "дней+%": (gg.groupby("day").p.mean() > 0).mean() * 100, "монет+%": (gg.groupby("sym").p.sum() > 0).mean() * 100,
                        "25/26 %": " ".join(f"{str(y)[2:]}:{vv.p.mean():+.1f}/{len(vv)}" for y, vv in gg.groupby("year"))})
        print(pd.DataFrame(out).to_string(index=False, float_format=lambda vv: f"{vv:6.2f}"))
print("\n===== срезы (фрактал+канал): FVG в ноге слома и глубина B · S3")
x = f[f.fc].copy(); x["depth"] = pd.cut(x.w2, [0, .382, .618, .786, 1.01], labels=["<0.382", "0.382-0.618", "0.618-0.786", ">0.786"])
for col in ("fvg", "depth"):
    print(x.groupby(["v", col], observed=True).agg(n=("risk", "size"), S3=("S3 50 T1 + 50 T1.618", "mean"), ctl=("ctl S3 50 T1 + 50 T1.618", "mean"),
          S1=("S1 100% T1", "mean"), T1=("hit_T1", "mean"), T1618=("hit_T1618", "mean")).round(2).to_string())
