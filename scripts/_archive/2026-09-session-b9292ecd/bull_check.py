# -*- coding: utf-8 -*-
"""🐂 КАНДИДАТ НА БЫЧЬЕМ РЫНКЕ 2020-2021 (Binance Vision, 15m) — 11.09.2026.

Открытый вопрос: в единственном бычьем году кэша (2023) кластер-фильтр работал ПРОТИВ
(−1.381% против +0.582% у остальных). OOS 2025-26 — только медвежий ⇒ вердикт односторонний.
Егор: «в медвежьем понятно, что это отскок». Проверяем на ВТОРОМ, независимом бычьем периоде.

Окно 2020-01…2021-12 содержит все режимы: ковид-обвал (март 2020), бычий рост (2020-Q4…
2021-Q1), майский обвал 2021, второй рост (лето-осень 2021), начало медведя (декабрь 2021).
⇒ режим размечается по BTC КАУЗАЛЬНО: доходность за 30 и 90 дней ДО входа.

Правило то же, что у кандидата, без изменений:
  1h: кросс wt1×wt2 вверх при wt1 < −IZ → 15m: первый кросс вверх в окне 12 баров →
  выход wt1 ≥ +EZ на 15m · только LONG · одна позиция на монету · косты 0.35%
Контроль: случайный вход без перекрытия, та же политика выхода.
"""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
SRC = r"C:\oko_history_bull\15m"
TIMEOUT, COST, LIFE = 400, 0.35, 12
CONFS = [(70.0, 60.0), (75.0, 70.0)]
RNG = np.random.default_rng(2021)
files = sorted(glob.glob(os.path.join(SRC, "*.parquet")))
btc_f = os.path.join(SRC, "BTCUSDT.parquet")
print(f"файлов {len(files)} · BTC есть: {os.path.exists(btc_f)}\n", flush=True)


def load(f):
    d = pd.read_parquet(f)
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
    d = d[~d.index.duplicated(keep="last")].sort_index()
    return d[(d.index >= "2020-01-01") & (d.index < "2022-01-01")]


b = load(btc_f).close
btc30 = (b / b.shift(30 * 96) - 1) * 100
btc90 = (b / b.shift(90 * 96) - 1) * 100

rows, ctl = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    di = load(f)
    if len(di) < 20000:
        continue
    dc = di.resample("60min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(dc) < 500:
        continue
    wc = calculate_wt(dc.reset_index(drop=True))
    c1, c2 = wc["wt1"].values, wc["wt2"].values
    nc = len(c1)
    ccu = np.zeros(nc, bool); ccu[1:] = (c1[:-1] <= c2[:-1]) & (c1[1:] > c2[1:])
    ct_c = (dc.index + pd.Timedelta(minutes=60)).values
    wi = calculate_wt(di.reset_index(drop=True))
    w1, w2 = wi["wt1"].values, wi["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cl, op = di.close.values, di.open.values
    ct_i = (di.index + pd.Timedelta(minutes=15)).values
    b30 = btc30.reindex(di.index, method="ffill").to_numpy()
    b90 = btc90.reindex(di.index, method="ffill").to_numpy()
    own30 = (pd.Series(cl) / pd.Series(cl).shift(30 * 96) - 1).to_numpy() * 100
    for IZ, EZ in CONFS:
        zone = w1 >= EZ

        def ex(ii):
            lim = min(ii + TIMEOUT, n - 1)
            j = np.where(zone[ii + 1:lim + 1])[0]
            return (ii + 1 + int(j[0])) if len(j) else lim

        ents = []
        for k in np.where(ccu & (c1 < -IZ))[0]:
            if k + LIFE >= nc:
                continue
            i0 = int(np.searchsorted(ct_i, ct_c[k], "left"))
            i1 = int(np.searchsorted(ct_i, ct_c[k + LIFE], "right")) - 1
            if i0 < 60 or i1 >= n - 5 or i1 <= i0:
                continue
            ins = np.where(cu[i0:i1 + 1])[0]
            if len(ins):
                ents.append(i0 + int(ins[0]) + 1)
        busy, taken = -1, 0
        for ii in sorted(set(e for e in ents if e < n - 5)):
            if ii <= busy:
                continue
            jx = ex(ii); busy = jx; taken += 1
            rows.append((sym, IZ, EZ, (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                         di.index[ii], float(b30[ii - 1]), float(b90[ii - 1]),
                         float(own30[ii - 1])))
        cb, cn = -1, 0
        for ii in np.sort(RNG.integers(60, max(61, n - TIMEOUT - 5), size=max(taken, 1) * 4)):
            if cn >= taken:
                break
            if ii <= cb:
                continue
            jx = ex(int(ii)); cb = jx; cn += 1
            ctl.append((sym, IZ, EZ, (cl[jx] - op[ii]) / op[ii] * 100 - COST,
                        di.index[int(ii)], float(b30[ii - 1]), float(b90[ii - 1])))
    if fi % 25 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "iz", "ez", "pnl", "ts", "btc30", "btc90", "own30"])
C = pd.DataFrame(ctl, columns=["sym", "iz", "ez", "pnl", "ts", "btc30", "btc90"])
R.to_pickle(D + r"\bull_check.pkl"); C.to_pickle(D + r"\bull_check_ctl.pkl")
R["day"] = R.ts.dt.normalize()
R["half"] = R.ts.dt.year.astype(str) + "H" + ((R.ts.dt.month > 6) + 1).astype(str)
C["half"] = C.ts.dt.year.astype(str) + "H" + ((C.ts.dt.month > 6) + 1).astype(str)
print(f"\nсделок {len(R):,} · контролей {len(C):,} · монет {R.sym.nunique()}\n")


def st(g):
    if len(g) < 30:
        return None
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return len(g), g.pnl.mean(), g.pnl.median(), v[int(len(v)*.1):].mean(), \
        int((per > 0).sum()), len(per)


def pr(lbl, g, c=None):
    s = st(g)
    if not s:
        return
    cm = f" · контр {c.pnl.mean():+.3f}% · НАД {s[1]-c.pnl.mean():+.3f}" \
        if c is not None and len(c) > 30 else ""
    print(f"  {lbl:>34}: n={s[0]:>5,} · {s[1]:+7.3f}%{cm} · мед {s[2]:+7.3f}% · "
          f"безтоп10 {s[3]:+7.3f}% · монет+ {s[4]}/{s[5]}")


for IZ, EZ in CONFS:
    G = R[(R["iz"] == IZ) & (R["ez"] == EZ)].dropna(subset=["btc30"])
    Cc = C[(C["iz"] == IZ) & (C["ez"] == EZ)].dropna(subset=["btc30"])
    G = G.join(G.groupby("day").sym.nunique().rename("k"), on="day")
    kth = 15 if IZ == 70 else 30
    print(f"{'='*80}\n=== вход ±{IZ:.0f} / выход +{EZ:.0f} · кластер k≥{kth} "
          f"(порог из слепого теста 2022-26) ===\n{'='*80}")
    pr("ВСЁ ОКНО 2020-2021", G, Cc)
    print("\n ПО ПОЛУГОДИЯМ:")
    for h in sorted(G.half.unique()):
        pr(h, G[G.half == h], Cc[Cc.half == h])
    print("\n 🔴 РЕЖИМ BTC ЗА 90 ДНЕЙ (главный вопрос — бык):")
    for lbl, cond, ccond in [
            ("БЫК: BTC +30% и выше за 90д", G.btc90 > 30, Cc.btc90 > 30),
            ("рост 0…+30%", G.btc90.between(0, 30), Cc.btc90.between(0, 30)),
            ("падение 0…−30%", G.btc90.between(-30, 0), Cc.btc90.between(-30, 0)),
            ("МЕДВЕДЬ: BTC −30% и хуже", G.btc90 < -30, Cc.btc90 < -30)]:
        pr(lbl, G[cond], Cc[ccond])
    print(f"\n 🔔 КЛАСТЕР k≥{kth} ПРОТИВ ОСТАЛЬНЫХ — В КАЖДОМ РЕЖИМЕ:")
    cl = G.k >= kth
    for lbl, cond in [("БЫК (BTC90 > +30%)", G.btc90 > 30),
                      ("рост (0…+30%)", G.btc90.between(0, 30)),
                      ("падение (0…−30%)", G.btc90.between(-30, 0)),
                      ("все режимы", G.btc90 == G.btc90)]:
        pr(f"{lbl} · кластер", G[cond & cl])
        pr(f"{lbl} · остальные", G[cond & ~cl])
    print("\n 🔔 КЛАСТЕР × BTC упал >10% за 30 дней (синергия из 2022-26):")
    bd = G.btc30 < -10
    pr("кластер И BTC упал", G[cl & bd])
    pr("кластер, BTC НЕ упал", G[cl & ~bd])
    pr("BTC упал, НЕ кластер", G[~cl & bd])
    pr("ни то ни другое", G[~cl & ~bd])
    print()
