"""Вложенный вход Егора + ПРОГНОЗНЫЕ цели от микроструктуры (14.09: «куда идёт стандартная ABC? а если разворот —
что дают следующие 5 волн? думай про прогнозирование, а не просто держать»).
Вход: CHoCH swing (микро-w1/A) → откат выше пятой (микро-w2/B) → internal bull CHoCH; стоп под B.
A = от пятой (p5) до максимума перед B.  Цели от B:  T1 = B+1.0·A (C=A — общая для ABC и для w3-минимума)
T1618 = B+1.618·A (C растянутая / типичная w3) · T2618 = B+2.618·A (растянутая w3) · W4 = конец волны 4 старшей пятёрки.
Стратегии выхода (косты 0.10% за круг, стоп проверяется прежде целей, ≤240 ч):
  S1  100% на T1                          S2  100% на T1618
  S3  50% T1 + 50% T1618, стоп→вход после T1
  S4  50% T1 + 50% T2618, стоп→вход после T1
  S5  ⅓ T1 · ⅓ T1618 · ⅓ T2618, стоп→вход после T1, →T1 после T1618
  S0  100% на W4 (как было)
Лестница: доля сделок, дошедших до цели ДО стопа (прогноз).
Контроль: 30 случайных входов в том же окне, тот же % стопа, те же % расстояния до целей."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure

COST, BUF, WIN_H, HOLD_H, NCTL = 0.10, 0.0015, 72, 240, 30
rng = np.random.default_rng(11)
STRATS = {"S1 100% T1": [(1.0, "T1")], "S2 100% T1.618": [(1.0, "T1618")],
          "S3 50 T1 + 50 T1.618": [(.5, "T1"), (.5, "T1618")], "S4 50 T1 + 50 T2.618": [(.5, "T1"), (.5, "T2618")],
          "S5 ⅓ T1·⅓ T1.618·⅓ T2.618": [(1/3, "T1"), (1/3, "T1618"), (1/3, "T2618")], "S0 100% W4": [(1.0, "W4")]}


def run_exit(h, l, c, k0, e, sl0, tg, legs, end):
    """legs: [(доля, имя цели)] по возрастанию; после i-й взятой цели стоп → вход, после 2-й → первая цель."""
    lv = [(fr, tg[n]) for fr, n in legs]
    if any(p <= e for _, p in lv):
        return None
    sl, taken, pnl = sl0, 0, 0.0
    for k in range(k0, end + 1):
        if l[k] <= sl:
            rest = sum(fr for fr, _ in lv[taken:])
            return pnl + rest * (sl - e) / e * 100 - COST
        while taken < len(lv) and h[k] >= lv[taken][1]:
            pnl += lv[taken][0] * (lv[taken][1] - e) / e * 100; taken += 1
            if len(lv) > 1:
                sl = e if taken == 1 else lv[taken - 2][1]
        if taken == len(lv):
            return pnl - COST
    rest = sum(fr for fr, _ in lv[taken:])
    return pnl + rest * (c[end] - e) / e * 100 - COST


def ladder(h, l, k0, e, sl, tg, end):
    """До какой цели дошла цена ДО стопа (стоп неподвижен)."""
    out = {n: False for n in tg}
    for k in range(k0, end + 1):
        if l[k] <= sl:
            break
        for n, p in tg.items():
            if h[k] >= p:
                out[n] = True
    return out


d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl")
d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
d["altern"] = d.alt_sharp_flat | d.alt_form
d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
d["fc"] = d.fractal_ok & (d.depth5 >= 0.5)
d["full"] = d.fc & d.altern & d.count_ok
htf = d.htf.iloc[0]
rows = []
for LTF, SCALES in (("15m", [(20, 3), (50, 5)]), ("5m", [(30, 3), (60, 5)])):
    bpm = 60 // TF_MIN[LTF]
    for sym, g in d.groupby("sym"):
        try:
            dl = load(sym, LTF); dh = load(sym, htf)
        except Exception:
            continue
        if len(dl) < 1000:
            continue
        h, l, c, o = (dl[k].values.astype(float) for k in ("high", "low", "close", "open"))
        lt = dl.index.values.astype("datetime64[ns]"); ih = dh.index.values.astype("datetime64[ns]")
        for _, r in g.iterrows():
            t5 = ih[int(r.b)]; a5 = int(np.searchsorted(lt, t5)); b5 = int(np.searchsorted(lt, t5 + np.timedelta64(TF_MIN[htf], "m")))
            j0 = int(np.searchsorted(lt, ih[int(r.t)] + np.timedelta64(TF_MIN[htf], "m")))
            if b5 <= a5 or a5 < 500 or j0 + (WIN_H + HOLD_H) * bpm >= len(dl) or lt[a5] - t5 > np.timedelta64(1, "D"):
                continue
            i5 = a5 + int(l[a5:b5].argmin()); p5 = float(l[i5]); jw = j0 + WIN_H * bpm; w0 = i5 - 400
            for S, I in SCALES:
                st = run_structure(dl.iloc[w0:jw + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=S, internal_len=I)
                sw = sorted(x.i + w0 for x in st.events if not x.internal and x.bull and x.kind == "CHoCH" and x.i + w0 > i5)
                it = sorted(x.i + w0 for x in st.events if x.internal and x.bull and x.kind == "CHoCH" and x.i + w0 > i5)
                if not sw:
                    continue
                c1 = sw[0]; prev = c1; ent = None
                for k in it:
                    if k <= c1:
                        continue
                    ib = prev + int(l[prev:k + 1].argmin()); lo = float(l[ib])
                    if j0 <= k < jw and lo > p5:
                        ent = (k, ib, lo); break
                    prev = k
                if ent is None or ent[0] + 1 >= len(o):
                    continue
                k, ib, B = ent
                a_top = float(h[i5:ib + 1].max()); A = a_top - p5
                e = float(o[k + 1]); sl = B * (1 - BUF)
                if A <= 0 or not (sl < e):
                    continue
                tg = {"T1": B + A, "T1618": B + 1.618 * A, "T2618": B + 2.618 * A, "W4": float(r.p4)}
                end = min(len(dl) - 1, k + 1 + HOLD_H * bpm)
                risk = (e - sl) / e * 100
                w2_depth = (a_top - B) / A
                base = dict(sym=sym, ts=r.ts, year=r.year, v=f"{LTF} s{S}/i{I}", fc=bool(r.fc), full=bool(r.full), risk=risk,
                            w2=w2_depth, day=str(pd.Timestamp(r.ts).date()), rr1=(tg["T1"] - e) / (e - sl))
                lad = ladder(h, l, k + 1, e, sl, tg, end)
                rec = {**base, **{f"hit_{n}": v for n, v in lad.items()}}
                dist = {n: (p / e - 1) for n, p in tg.items()}
                for sn, legs in STRATS.items():
                    p = run_exit(h, l, c, k + 1, e, sl, tg, legs, end)
                    rec[sn] = p
                    cp = []
                    for kr in rng.integers(j0, jw, NCTL):
                        er = float(o[kr + 1]); tgr = {n: er * (1 + dd) for n, dd in dist.items()}
                        pr = run_exit(h, l, c, kr + 1, er, er * (1 - risk / 100), tgr, legs, min(len(dl) - 1, kr + 1 + HOLD_H * bpm))
                        if pr is not None:
                            cp.append(pr)
                    rec["ctl " + sn] = np.mean(cp) if cp else np.nan
                rows.append(rec)
    print(f"[{LTF}] готово", flush=True)

f = pd.DataFrame(rows); f.to_pickle("nested_targets.pkl")
for tag, m in (("вся база", None), ("фрактал+канал", "fc"), ("полный набор", "full")):
    x = f if m is None else f[f[m]]
    print(f"\n===== {tag} · вложенный вход (CHoCH swing → откат выше 5 → CHoCH internal) · стоп под B · лонг")
    for v, g in x.groupby("v", sort=False):
        print(f"\n--- {v}: n={len(g)} · стоп мед {g.risk.median():.2f}% · RR до T1 мед {g.rr1.median():.1f} · глубина B мед {g.w2.median():.2f}")
        print("    ЛЕСТНИЦА (дошли до цели раньше стопа): " + " · ".join(f"{n} {g['hit_' + n].mean() * 100:.0f}%" for n in ("T1", "T1618", "T2618", "W4")))
        out = []
        for sn in STRATS:
            s = g[sn].dropna()
            if len(s) < 5:
                continue
            R = s / g.loc[s.index, "risk"]; ep = g.loc[s.index].assign(p=s).groupby("day").p.mean()
            out.append({"выход": sn, "n": len(s), "на сд%": s.mean(), "контроль%": g.loc[s.index, "ctl " + sn].mean(), "R": R.mean(), "медR": R.median(),
                        "WR%": (s > 0).mean() * 100, "безтоп10%": s.sort_values(ascending=False).iloc[int(len(s) * .1):].mean(),
                        "дней+%": (ep > 0).mean() * 100, "монет+%": (g.loc[s.index].assign(p=s).groupby("sym").p.sum() > 0).mean() * 100,
                        "годы %": " ".join(f"{str(y)[2:]}:{vv.mean():+.1f}/{len(vv)}" for y, vv in s.groupby(g.loc[s.index, "year"]))})
        print(pd.DataFrame(out).to_string(index=False, float_format=lambda vv: f"{vv:6.2f}"))
# срез по глубине B (микро-w2) на лучшей стратегии
print("\n===== срез: глубина отката B от A (фрактал+канал, все LTF), S3")
x = f[f.fc].copy(); x["depth"] = pd.cut(x.w2, [0, .382, .5, .786, 1.01], labels=["<0.382", "0.382-0.5", "0.5-0.786", ">0.786"])
print(x.groupby(["v", "depth"], observed=True).agg(n=("risk", "size"), s3=("S3 50 T1 + 50 T1.618", "mean"), ctl=("ctl S3 50 T1 + 50 T1.618", "mean"),
      t1=("hit_T1", "mean"), t1618=("hit_T1618", "mean")).round(2).to_string())
