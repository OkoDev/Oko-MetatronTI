"""Вход Егора по CHoCH младшего слоя после пятой (14.09: «захожу глазами на сломе 3m — лучшие сделки, RR крутой»).
Сетапы = пятёрки ядра (кросс-pkl, все 658 лонгов 2023-26). Раннее время входа — закрытие 4h-бара детекции (t).
Входы (по закрытию бара события, исполнение open следующего):
  peak   — первый internal bull CHoCH после пятой; стоп под минимум от пятой до слома
  nested — swing bull CHoCH (микро-w1) → откат держится выше пятой → internal bull CHoCH; стоп под минимум отката (микро-w2)
Цель = конец w4, удержание ≤240 ч, косты 0.10% за круг, стоп проверяется прежде цели.
Контроль: 30 случайных входов в том же окне (72 ч от детекции) с ТЕМ ЖЕ % стопа и той же целью.
LTF: 15m (swing20/int3, swing50/int5) на всей базе; 5m (swing60/int5, swing30/int3) — где есть кэш 5m (2025-01…2026-05)."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure

COST, BUF, WIN_H, HOLD_H, NCTL = 0.10, 0.0015, 72, 240, 30
rng = np.random.default_rng(7)


def outcome(h, l, c, k0, e, sl, tp, end):
    for k in range(k0, end + 1):
        if l[k] <= sl: return (sl - e) / e * 100 - COST, "stop"
        if h[k] >= tp: return (tp - e) / e * 100 - COST, "tp"
    return (c[end] - e) / e * 100 - COST, "time"


d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl")
d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
d["altern"] = d.alt_sharp_flat | d.alt_form
d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
d["fc"] = d.fractal_ok & (d.depth5 >= 0.5)
d["full"] = d.fc & d.altern & d.count_ok
htf = d.htf.iloc[0]
rows = []
for LTF, SCALES in (("15m", [(20, 3), (50, 5)]), ("5m", [(60, 5), (30, 3)])):
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
            if b5 <= a5 or a5 < 500 or j0 + WIN_H * bpm + HOLD_H * bpm >= len(dl) or lt[a5] - t5 > np.timedelta64(1, "D"):
                continue
            i5 = a5 + int(l[a5:b5].argmin()); p5 = float(l[i5]); tp = float(r.p4)
            jw = j0 + WIN_H * bpm
            w0 = i5 - 400
            base = dict(sym=sym, ts=r.ts, year=r.year, ltf=LTF, fc=bool(r.fc), full=bool(r.full))
            for S, I in SCALES:
                st = run_structure(dl.iloc[w0:jw + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=S, internal_len=I)
                sw = sorted(x.i + w0 for x in st.events if not x.internal and x.bull and x.kind == "CHoCH" and x.i + w0 > i5)
                it = sorted(x.i + w0 for x in st.events if x.internal and x.bull and x.kind == "CHoCH" and x.i + w0 > i5)
                for mode in ("peak", "nested"):
                    ent = None
                    if mode == "peak":
                        for k in it:
                            if j0 <= k < jw:
                                ent = (k, float(l[i5:k + 1].min())); break
                    else:
                        c1 = sw[0] if sw else None
                        if c1 is not None:
                            prev = c1
                            for k in it:
                                if k <= c1: continue
                                lo = float(l[prev:k + 1].min())
                                if j0 <= k < jw and lo > p5:
                                    ent = (k, lo); break
                                prev = k
                    if ent is None:
                        rows.append({**base, "v": f"{LTF} {mode} s{S}/i{I}", "entered": False}); continue
                    k, lo = ent
                    if k + 1 >= len(o): continue
                    e = float(o[k + 1]); sl = lo * (1 - BUF)
                    if not (sl < e < tp):
                        rows.append({**base, "v": f"{LTF} {mode} s{S}/i{I}", "entered": False}); continue
                    end = min(len(dl) - 1, k + 1 + HOLD_H * bpm)
                    pnl, how = outcome(h, l, c, k + 1, e, sl, tp, end)
                    risk = (e - sl) / e * 100
                    # контроль: случайный бар в окне, тот же % стопа, та же цель
                    cp = []
                    for kr in rng.integers(j0, jw, NCTL):
                        er = float(o[kr + 1]); slr = er * (1 - risk / 100)
                        if er >= tp: continue
                        cp.append(outcome(h, l, c, kr + 1, er, slr, tp, min(len(dl) - 1, kr + 1 + HOLD_H * bpm))[0])
                    rows.append({**base, "v": f"{LTF} {mode} s{S}/i{I}", "entered": True, "pnl": pnl, "how": how, "risk": risk,
                                 "rr_plan": (tp - e) / (e - sl), "R": pnl / risk, "ctl_pnl": np.mean(cp) if cp else np.nan,
                                 "ctl_R": (np.mean(cp) / risk) if cp else np.nan, "h_after5": (k - i5) / bpm, "day": str(pd.Timestamp(r.ts).date())})
    print(f"[{LTF}] готово", flush=True)

f = pd.DataFrame(rows); f.to_pickle("entry_choch.pkl")
for tag, m in (("вся база", None), ("фрактал+канал", "fc"), ("полный набор", "full")):
    x = f if m is None else f[f[m]]
    print(f"\n===== {tag} · лонг · цель w4 · ≤240 ч · косты 0.10%")
    out = []
    for name, g in x.groupby("v", sort=False):
        e = g[g.entered == True]
        if len(e) < 5: continue
        ep = e.groupby("day").pnl.mean()
        out.append({"вход": name, "сетапов": len(g), "вход%": len(e) / len(g) * 100, "стоп%мед": e.risk.median(), "RRплан мед": e.rr_plan.median(),
                    "R": e.R.mean(), "медR": e.R.median(), "WR%": (e.pnl > 0).mean() * 100, "цель%": (e.how == "tp").mean() * 100,
                    "стоп-аут%": (e.how == "stop").mean() * 100, "на сд%": e.pnl.mean(), "контроль%": e.ctl_pnl.mean(), "контрольR": e.ctl_R.mean(),
                    "безтоп10%": e.pnl.sort_values(ascending=False).iloc[int(len(e) * .1):].mean(), "дней+%": (ep > 0).mean() * 100,
                    "монет+%": (e.groupby("sym").pnl.sum() > 0).mean() * 100, "ч от 5": e.h_after5.median(),
                    "годы R": " ".join(f"{str(y)[2:]}:{v.R.mean():+.2f}/{len(v)}" for y, v in e.groupby("year"))})
    print(pd.DataFrame(out).to_string(index=False, float_format=lambda v: f"{v:6.2f}"))
