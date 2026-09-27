# -*- coding: utf-8 -*-
"""СХЕМА ЕГОРА НА ПОЛНОМ ОКНЕ 2022-2026 (1h кэш) + РЕЖИМ ГОДА (10.09.2026).

Замер на 1m-паркетах покрывал только 2025-2026 — бычьего года в окне НЕТ,
поэтому «шорт работает, лонг нет» частично тавтология. 1h кэш идёт с 2022,
а схема 240m→60m целиком в него влезает (вход 1h, контекст 4h ресемплом).

  контекст 4h:  кросс wt1×wt2 в зоне OS(<-60)/OB(>+60) → жив LIFE баров
  вход     1h:  пересечение медианы WT(34) в сторону контекста, серией
  выход:        разворот в противоположной зоне, иначе таймаут 200 баров

Печатается ОБЯЗАТЕЛЬНОЕ: режим каждого года (медиана годовой доходности монет,
доля растущих), сигнал против случайного контроля ПО КАЖДОМУ ГОДУ, зеркальность,
хрупкость, охват. Без этого вердикт по протоколу запрещён.
"""
import os, sys, sqlite3, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
MED_LEN, OS, OB, LIFE, TIMEOUT, COST = 34, -60.0, 60.0, 12, 200, 0.35
CTX_MULT = 4              # контекст = 4h при входе 1h
RNG = np.random.default_rng(11)
NRAND = 4
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='1h' "
    "group by symbol having count(*) > 12000 order by symbol")]
print(f"символов с 1h ≥12000 баров: {len(syms)}\n", flush=True)

sig, ctl, regime = [], [], []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close,volume from ohlcv_cache "
                    "where symbol=? and timeframe='1h' order by time",
                    con, params=(sym,))
    if len(d) < 12000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    # режим по годам этой монеты
    for y, g in d.groupby(d.index.year):
        if len(g) > 2000:
            regime.append((sym, int(y),
                           (g.close.iloc[-1] - g.close.iloc[0]) / g.close.iloc[0] * 100))
    dc = d.resample(f"{CTX_MULT}h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 300:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    ccu = np.zeros(len(c1), bool); ccd = np.zeros(len(c1), bool)
    ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ccd[1:] = (c1[:-1] >= c2[:-1]) & (c1[1:] < c2[1:])
    ct_c = list(dc.index + pd.Timedelta(hours=CTX_MULT))

    wi = calculate_wt(d.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    med = pd.Series(w1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    zone_up, zone_dn = cd & (w1 > OB), cu & (w1 < OS)
    med_up = np.concatenate(([False], (w1[:-1] <= med[:-1]) & (w1[1:] > med[1:])))
    med_dn = np.concatenate(([False], (w1[:-1] >= med[:-1]) & (w1[1:] < med[1:])))
    cl, op = d.close.values, d.open.values
    ts = d.index; yr = ts.year.values

    def trade(ii, side):
        if ii >= n - 3:
            return None
        zone = zone_up if side == 1 else zone_dn
        lim = min(ii + TIMEOUT, n - 1)
        jz = np.where(zone[ii + 1:lim + 1])[0]
        end = ii + 1 + int(jz[0]) if len(jz) else lim
        e = op[ii]
        return (cl[end] - e) / e * 100 * side - COST, end - ii, int(len(jz) > 0)

    ctx = []
    for arr, sd in ((ccu & (c1 < OS), 1), (ccd & (c1 > OB), -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(ct_c):
                ctx.append((ct_c[k], ct_c[k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); starts = [x[0] for x in ctx]
    busy = {1: -1, -1: -1}
    for i in range(MED_LEN + 5, n - 5):
        for s_, side in ((med_up[i], 1), (med_dn[i], -1)):
            if not s_:
                continue
            t_now = ts[i] + pd.Timedelta(hours=1)
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
            busy[side] = ii + r[1]
            sig.append(dict(sym=sym, side=side, pnl=r[0], bars=r[1], reached=r[2],
                            year=int(yr[i]), day=ts[i].normalize()))
            for _ in range(NRAND):
                j = int(RNG.integers(max(MED_LEN + 6, ii - 720), min(n - 4, ii + 720)))
                rr = trade(j, side)
                if rr:
                    ctl.append(dict(sym=sym, side=side, pnl=rr[0], year=int(yr[j]),
                                    bars=rr[1]))
    if fi % 20 == 0:
        print(f"  [{fi}/{len(syms)}] сигналов {len(sig):,}", flush=True)

S = pd.DataFrame(sig); C = pd.DataFrame(ctl)
G = pd.DataFrame(regime, columns=["sym", "year", "ret"])
S.to_pickle(D + r"\egor_years_sig.pkl"); C.to_pickle(D + r"\egor_years_ctl.pkl")
print(f"\nсигналов {len(S):,} · контролей {len(C):,} · монет {S.sym.nunique()}\n")

print("=== ИНВЕНТАРИЗАЦИЯ: РЕЖИМ КАЖДОГО ГОДА (1h кэш) ===")
print(f"{'год':>6} {'монет':>7} {'медиана год. дох.':>18} {'доля растущих':>15} {'режим':>10}")
for y, g in G.groupby("year"):
    m = g.ret.median(); up = (g.ret > 0).mean()
    rg = "БЫК" if m > 20 else ("МЕДВЕДЬ" if m < -20 else "нейтраль")
    print(f"{y:>6} {len(g):>7} {m:>17.1f}% {up*100:>14.1f}% {rg:>10}")

print("\n=== СИГНАЛ ПРОТИВ СЛУЧАЙНОГО ВХОДА — ПО ГОДАМ И СТОРОНАМ ===")
print(f"{'стор':>6} {'год':>5} {'n':>7} {'сигнал':>9} {'контроль':>10} {'дельта':>9} "
      f"{'мед сиг':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for y in sorted(S.year.unique()):
        g = S[(S.side == side) & (S.year == y)]
        c = C[(C.side == side) & (C.year == y)]
        if len(g) < 40:
            continue
        per = g.groupby("sym").pnl.mean()
        cm = c.pnl.mean() if len(c) > 20 else np.nan
        print(f"{sn:>6} {y:>5} {len(g):>7,} {g.pnl.mean():+8.3f}% {cm:+9.3f}% "
              f"{g.pnl.mean()-cm:+8.3f}% {g.pnl.median():+8.3f}% "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== ИТОГО ПО СТОРОНАМ (всё окно) ===")
print(f"{'стор':>6} {'n':>8} {'сигнал':>9} {'контроль':>10} {'дельта':>9} {'мед':>9} "
      f"{'WR':>6} {'безтоп10':>9} {'безтоп25':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    g = S[S.side == side]; c = C[C.side == side]
    if len(g) < 100:
        continue
    v = np.sort(g.pnl.values)[::-1]; per = g.groupby("sym").pnl.mean()
    print(f"{sn:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% {c.pnl.mean():+9.3f}% "
          f"{g.pnl.mean()-c.pnl.mean():+8.3f}% {g.pnl.median():+8.3f}% "
          f"{(g.pnl>0).mean()*100:5.1f}% {v[int(len(v)*.1):].mean():+8.3f}% "
          f"{v[int(len(v)*.25):].mean():+8.3f}% {int((per>0).sum())}/{len(per)}")

print("\n=== РЕЖИМ ГОДА × СТОРОНА (главный вопрос: спасает ли лонг бычий год) ===")
rmap = {}
for y, g in G.groupby("year"):
    m = g.ret.median()
    rmap[int(y)] = "БЫК" if m > 20 else ("МЕДВЕДЬ" if m < -20 else "нейтраль")
S["rg"] = S.year.map(rmap); C["rg"] = C.year.map(rmap)
print(f"{'режим':>10} {'стор':>6} {'n':>8} {'сигнал':>9} {'контроль':>10} {'дельта':>9} "
      f"{'монет+':>9}")
for rg in ["БЫК", "нейтраль", "МЕДВЕДЬ"]:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = S[(S.rg == rg) & (S.side == side)]; c = C[(C.rg == rg) & (C.side == side)]
        if len(g) < 50:
            continue
        per = g.groupby("sym").pnl.mean()
        print(f"{rg:>10} {sn:>6} {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{c.pnl.mean():+9.3f}% {g.pnl.mean()-c.pnl.mean():+8.3f}% "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== КЛАСТЕР (воспроизводится ли на полном окне) ===")
cnt = S.groupby(["side", "day"]).sym.nunique().rename("k").reset_index()
S2 = S.merge(cnt, on=["side", "day"])
print(f"{'стор':>6} {'кластер':>14} {'n':>8} {'нетто':>9} {'мед':>9} {'монет+':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for lbl, cond in [("k=1", S2.k == 1), ("2-4", S2.k.between(2, 4)),
                      ("5-14", S2.k.between(5, 14)), ("15+", S2.k >= 15)]:
        g = S2[cond & (S2.side == side)]
        if len(g) < 50:
            continue
        per = g.groupby("sym").pnl.mean()
        print(f"{sn:>6} {lbl:>14} {len(g):>8,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {int((per>0).sum())}/{len(per)}")
    print()
