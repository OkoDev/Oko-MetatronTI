# -*- coding: utf-8 -*-
"""КОНТРОЛЬ ДЛЯ ЕДИНСТВЕННОЙ ЖИВОЙ СТРОКИ: шорт 240m→60m без стопа (10.09.2026).

Строка: n=465, нетто +1.925%, медиана +3.765%, WR 70.1%, монет+ 39/49, безтоп10% +0.469%.
Удержание 122 бара 60m = 5 суток. В 2025-26 альты падали ⇒ это может быть
«шорти альту и держи», а не эдж схемы.

ЗАКОН: контроль = СЛУЧАЙНЫЙ ВХОД ТОЙ ЖЕ ГЕОМЕТРИИ.

Четыре контроля на тех же монетах:
    C0  сигнал схемы (как есть)
    C1  случайный бар той же монеты ±30 дней от сигнала, то же правило выхода
    C2  каждый бар монеты (полная база): «шорти всегда», то же правило выхода
    C3  фиксированное удержание = медиане жизни сигнала, от случайного бара
Плюс разрезы, которых не было: ГОД · РЕЖИМ ГОДА · КЛАСТЕР (сколько монет в сигнале
в тот же день) · ЛИКВИДНОСТЬ (оборот) · зеркало (long теми же правилами).
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_CTX, TF_IN = 240, 60
MED_LEN, OS, OB, LIFE, TIMEOUT, COST = 34, -60.0, 60.0, 12, 200, 0.35
RNG = np.random.default_rng(7)
NRAND = 6          # случайных дублей на каждый сигнал
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет: {len(files)} · {TF_CTX}m → {TF_IN}m · контролей на сигнал: {NRAND}\n",
      flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "vol": r["volume"].sum() if "volume" in d1 else r["close"].count()
                         }).dropna()


sig_rows, ctl_rows, base_rows = [], [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    dc = resample(d1, TF_CTX); di = resample(d1, TF_IN)
    if len(dc) < 200 or len(di) < 600:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    ccu = np.zeros(len(c1), bool); ccd = np.zeros(len(c1), bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    os_c, ob_c = ccu & (c1 < OS), ccd & (c1 > OB)
    ct_c = list(dc.index + pd.Timedelta(minutes=TF_CTX))

    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    med = pd.Series(w1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    zone_up = cd & (w1 > OB)        # выход лонга
    zone_dn = cu & (w1 < OS)        # выход шорта
    med_up = np.concatenate(([False], (w1[:-1] <= med[:-1]) & (w1[1:] > med[1:])))
    med_dn = np.concatenate(([False], (w1[:-1] >= med[:-1]) & (w1[1:] < med[1:])))
    cl, op = di["close"].values, di["open"].values
    ts = di.index
    yr = ts.year.values
    # оборот монеты: медианный объём в деньгах за бар 60m
    turn = float(np.nanmedian(di["vol"].values * cl)) if "vol" in di else np.nan

    def trade(ii, side):
        """E2: выход по развороту в противоположной зоне, иначе таймаут."""
        if ii >= n - 3:
            return None
        zone = zone_up if side == 1 else zone_dn
        lim = min(ii + TIMEOUT, n - 1)
        jz = np.where(zone[ii + 1:lim + 1])[0]
        end = ii + 1 + int(jz[0]) if len(jz) else lim
        e = op[ii]
        return (cl[end] - e) / e * 100 * side - COST, end - ii, int(len(jz) > 0)

    ctx = []
    for arr, sd in ((os_c, 1), (ob_c, -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(ct_c):
                ctx.append((ct_c[k], ct_c[k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); starts = [x[0] for x in ctx]

    busy = {1: -1, -1: -1}
    for i in range(MED_LEN + 5, n - 5):
        for sig, side in ((med_up[i], 1), (med_dn[i], -1)):
            if not sig:
                continue
            t_now = ts[i] + pd.Timedelta(minutes=TF_IN)
            p = bisect.bisect_right(starts, t_now) - 1
            if not any(ctx[q][2] == side and ctx[q][0] <= t_now <= ctx[q][1]
                       for q in range(max(0, p - 3), p + 1) if 0 <= q < len(ctx)):
                continue
            ii = i + 1
            if ii <= busy[side]:
                continue
            r = trade(ii, side)
            if r is None:
                continue
            pn, bars, reached = r
            busy[side] = ii + bars
            sig_rows.append(dict(sym=sym, side=side, pnl=pn, bars=bars,
                                 reached=reached, year=int(yr[i]), turn=turn,
                                 day=ts[i].normalize(), half=int(i >= n // 2)))
            # ── C1: случайный бар ±30 дней (720 баров 60m), та же сторона и выход
            for _ in range(NRAND):
                j = int(RNG.integers(max(MED_LEN + 6, ii - 720),
                                     min(n - 4, ii + 720)))
                rr = trade(j, side)
                if rr:
                    ctl_rows.append(dict(sym=sym, side=side, pnl=rr[0], bars=rr[1],
                                         reached=rr[2], year=int(yr[j]), kind="C1"))
    # ── C2: полная база — каждый 20-й бар, обе стороны
    for side in (1, -1):
        for j in range(MED_LEN + 6, n - 4, 20):
            rr = trade(j, side)
            if rr:
                base_rows.append(dict(sym=sym, side=side, pnl=rr[0], bars=rr[1],
                                      reached=rr[2], year=int(yr[j]), kind="C2"))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] сигналов {len(sig_rows):,}", flush=True)

S = pd.DataFrame(sig_rows); C1 = pd.DataFrame(ctl_rows); C2 = pd.DataFrame(base_rows)
S.to_pickle(D + r"\egor_ctl_sig.pkl"); C1.to_pickle(D + r"\egor_ctl_c1.pkl")
C2.to_pickle(D + r"\egor_ctl_c2.pkl")
print(f"\nсигналов {len(S):,} · C1 {len(C1):,} · C2 {len(C2):,}\n")

print("=== ГЛАВНЫЙ ТЕСТ: СИГНАЛ ПРОТИВ СЛУЧАЙНОГО ВХОДА ТОЙ ЖЕ ГЕОМЕТРИИ ===")
print(f"{'что':>34} {'стор':>6} {'n':>8} {'нетто':>9} {'мед':>9} {'WR':>6} "
      f"{'баров':>7} {'долёт':>7}")
for side, sn in [(-1, "short"), (1, "long")]:
    for lbl, g in [("C0 сигнал схемы", S[S.side == side]),
                   ("C1 случайный бар ±30д", C1[C1.side == side]),
                   ("C2 полная база (каждый бар)", C2[C2.side == side])]:
        if len(g) < 50:
            continue
        print(f"{lbl:>34} {sn:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% "
              f"{g.bars.median():>7.0f} {g.reached.mean()*100:6.1f}%")
    s_ = S[S.side == side].pnl; c_ = C1[C1.side == side].pnl
    if len(s_) > 30 and len(c_) > 30:
        from scipy import stats
        t, p = stats.ttest_ind(s_, c_, equal_var=False)
        print(f"{'':>34} {'':>6} превышение над C1: "
              f"{s_.mean()-c_.mean():+.3f} п.п. · t={t:.2f} p={p:.4f}")
    print()

print("=== ГОД (сигнал против C1) ===")
print(f"{'стор':>6} {'год':>5} {'n сиг':>7} {'сигнал':>9} {'C1':>9} {'дельта':>9} "
      f"{'монет+':>8}")
for side, sn in [(-1, "short"), (1, "long")]:
    for y in sorted(S.year.unique()):
        g = S[(S.side == side) & (S.year == y)]
        c = C1[(C1.side == side) & (C1.year == y)]
        if len(g) < 40:
            continue
        per = g.groupby("sym").pnl.mean()
        print(f"{sn:>6} {y:>5} {len(g):>7,} {g.pnl.mean():+8.3f}% "
              f"{c.pnl.mean() if len(c) else float('nan'):+8.3f}% "
              f"{g.pnl.mean()-(c.pnl.mean() if len(c) else 0):+8.3f}% "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== КЛАСТЕР: сколько монет дали сигнал в тот же день ===")
cnt = S.groupby(["side", "day"]).sym.nunique().rename("k").reset_index()
S2 = S.merge(cnt, on=["side", "day"])
print(f"{'стор':>6} {'кластер':>16} {'n':>7} {'нетто':>9} {'мед':>9} {'монет+':>8}")
for side, sn in [(-1, "short"), (1, "long")]:
    for lbl, cond in [("одиночка k=1", S2.k == 1), ("2-4 монеты", S2.k.between(2, 4)),
                      ("5-9 монет", S2.k.between(5, 9)), ("10+ монет", S2.k >= 10)]:
        g = S2[cond & (S2.side == side)]
        if len(g) < 40:
            continue
        per = g.groupby("sym").pnl.mean()
        print(f"{sn:>6} {lbl:>16} {len(g):>7,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {int((per>0).sum())}/{len(per)}")
    print()

print("=== ЛИКВИДНОСТЬ (оборот монеты, медиана $ за бар 60m) ===")
S["tq"] = pd.qcut(S.turn, 3, labels=["низкая", "средняя", "высокая"], duplicates="drop")
for side, sn in [(-1, "short"), (1, "long")]:
    for q in ["низкая", "средняя", "высокая"]:
        g = S[(S.side == side) & (S.tq == q)]
        if len(g) < 40:
            continue
        print(f"  {sn:>5} {q:>9}: n={len(g):>5,} {g.pnl.mean():+.3f}% "
              f"мед {g.pnl.median():+.3f}% монет+ "
              f"{int((g.groupby('sym').pnl.mean()>0).sum())}/{g.sym.nunique()}")
    print()

print("=== ХРУПКОСТЬ И ОХВАТ (сигнал) ===")
for side, sn in [(-1, "short"), (1, "long")]:
    g = S[S.side == side]
    if len(g) < 50:
        continue
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    print(f"  {sn:>5}: n={len(g):>5,} всё {g.pnl.mean():+.3f}% · "
          f"безтоп10% {v[int(len(v)*.1):].mean():+.3f}% · "
          f"безтоп25% {v[int(len(v)*.25):].mean():+.3f}% · "
          f"монет+ {int((per>0).sum())}/{len(per)} · "
          f"IS {g[g.half==0].pnl.mean():+.3f}% → OOS {g[g.half==1].pnl.mean():+.3f}%")
