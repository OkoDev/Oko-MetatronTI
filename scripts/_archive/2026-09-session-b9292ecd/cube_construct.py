# -*- coding: utf-8 -*-
"""КОНСТРУКЦИЯ ПО РЕШЁТКЕ ГИПЕРКУБА (поправка Егора: «мы в гиперкубе»).

Не одна пара ТФ, а ВСЕ пары слоёв лестницы. Для каждой:
  контекст = тренд структуры слоя-старшего (по ЗАКРЫТОМУ бару)
  триггер  = WT-дивергенция на слое-младшем
  стоп     = экстремум SWING баров МЛАДШЕГО слоя   (масштаб входа)
  цель     = ближайший прошлый swing старшего слоя (масштаб контекста)
Отбираются пары, где отношение окон R ≥ 0.85 — измеренная область вложенности.

🔴 Опорная точка сравнения: случайное блуждание даёт WR ≈ 1/(1+RR). Всё, что не
   отличается от этой линии, — не находка, а геометрия.
"""
import os, sys, glob, warnings, itertools
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure, _swings
from core.calculators.combinator_core import _wtx_divergences
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [5, 15, 60, 240]
SWING = 10
MAXBARS = 400
NSYM = 40
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
PAIRS = [(c, t) for c, t in itertools.product(TFS, TFS)
         if c > t and (c * SWING) / (t * SWING) >= 0.85]
print(f"монет: {len(files)} | пар слоёв: {len(PAIRS)} → "
      f"{[(f'{c}m',f'{t}m') for c,t in PAIRS]}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    cache = {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 400:
            continue
        w = calculate_wt(d.reset_index(drop=True))
        br, ber, _, _ = _wtx_divergences(w["wt1"].values, d["low"].values, d["high"].values)
        st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
        n = len(d)
        tr = np.zeros(n, np.int8); t_ = 0; p = 0
        ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
        for b in range(n):
            while p < len(ev) and ev[p].i <= b:
                t_ = 1 if ev[p].bull else -1; p += 1
            tr[b] = t_
        sw = _swings(d["high"], d["low"], SWING)
        cache[tf] = dict(d=d, tr=tr, br=br, ber=ber,
                         top=[(c_, p_) for c_, _, p_, is_t in sw if is_t],
                         btm=[(c_, p_) for c_, _, p_, is_t in sw if not is_t])
    for tc, tt in PAIRS:
        if tc not in cache or tt not in cache:
            continue
        C, T = cache[tc], cache[tt]
        dc, dt = C["d"], T["d"]
        ct = dc.index.values + np.timedelta64(tc, "m")      # ВРЕМЯ ЗАКРЫТИЯ
        ch, cl_, cc = dc["high"].values, dc["low"].values, dc["close"].values
        th, tl = dt["high"].values, dt["low"].values
        tcl = dt["close"].values
        ti = np.array([c_ for c_, _ in C["top"]]); tp = np.array([p_ for _, p_ in C["top"]])
        bi = np.array([c_ for c_, _ in C["btm"]]); bp = np.array([p_ for _, p_ in C["btm"]])
        for side, trig in ((1, T["br"]), (-1, T["ber"])):
            for j in np.where(trig)[0]:
                if j < SWING + 2:
                    continue
                t0 = dt.index.values[j]
                k = int(np.searchsorted(ct, t0, "right")) - 1
                if k < 60 or k >= len(dc) - 5 or C["tr"][k] != side:
                    continue
                entry = tcl[j]
                # СТОП — в масштабе МЛАДШЕГО слоя (там же, где триггер)
                stop = tl[max(0, j - SWING):j + 1].min() if side == 1 \
                    else th[max(0, j - SWING):j + 1].max()
                # ЦЕЛЬ — в масштабе СТАРШЕГО слоя
                cand = tp[(ti <= k) & (tp > entry)] if side == 1 \
                    else bp[(bi <= k) & (bp < entry)]
                if len(cand) == 0:
                    continue
                target = float(cand[-1])
                risk = abs(entry - stop) / entry * 100
                rew = abs(target - entry) / entry * 100
                if risk < 0.1 or rew / max(risk, 1e-9) < 0.5:
                    continue
                res = None
                for b in range(k + 1, min(k + 1 + MAXBARS, len(dc))):
                    if side == 1:
                        if cl_[b] <= stop: res = -risk; break
                        if ch[b] >= target: res = rew; break
                    else:
                        if ch[b] >= stop: res = -risk; break
                        if cl_[b] <= target: res = rew; break
                if res is None:
                    res = (cc[min(k + MAXBARS, len(dc) - 1)] - entry) / entry * 100 * side
                rows.append((f"{tc}m/{tt}m", sym, side, risk, rew, res,
                             int(k >= len(dc) // 2)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["pair", "sym", "side", "risk", "rew", "pnl", "half"])
R["net"] = R.pnl - COST
R.to_pickle(D + r"\cube_construct.pkl")
print(f"\nсделок: {len(R):,}\n")
print("=== ПО ПАРАМ СЛОЁВ · опора: WR случайного блуждания = 1/(1+RR) ===")
print(f"{'пара':>10} {'стор':>6} {'n':>7} {'стоп%':>7} {'цель%':>7} {'RR':>5} "
      f"{'WR':>6} {'WR случ.':>8} {'Δ WR':>7} {'ср нетто':>9} {'PF':>6} {'монет+':>8}")
for (pair, side), g in R.groupby(["pair", "side"]):
    if len(g) < 200:
        continue
    rr = g.rew.median() / g.risk.median()
    wr = (g.pnl > 0).mean() * 100
    wr0 = 1 / (1 + rr) * 100
    pf = g.net[g.net > 0].sum() / abs(g.net[g.net < 0].sum()) if (g.net < 0).any() else np.inf
    per = g.groupby("sym").net.mean()
    nm = "long" if side == 1 else "short"
    print(f"{pair:>10} {nm:>6} {len(g):>7,} {g.risk.median():6.2f}% {g.rew.median():6.2f}% "
          f"{rr:5.2f} {wr:5.1f}% {wr0:7.1f}% {wr-wr0:+6.1f} {g.net.mean():+8.3f}% "
          f"{pf:6.2f} {int((per>0).sum())}/{len(per)}")
print("\n🔑 Δ WR — насколько доля достижения цели выше случайной при той же геометрии.")
print("   Всё, что около нуля, — не эдж, а арифметика стопа и цели.")
