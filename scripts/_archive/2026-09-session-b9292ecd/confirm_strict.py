# -*- coding: utf-8 -*-
"""ПРИЗНАКИ ПОДТВЕРЖДЕНИЯ — СТРОГИЙ ПРОТОКОЛ (последняя выжившая линия, 09.09.2026).

Конструкция чистая: всё считается на СВОЁМ таймфрейме, склейки слоёв нет — значит
look-ahead вида 6 (открытие вместо закрытия бара) сюда попасть не может.

Обязательные срезы проекта: сторона · IS→OOS · охват монет · хрупкость без верхних 10% ·
контроль случайным баром той же монеты в том же квинтиле ATR.
"""
import os, sys, glob, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.calculators.combinator_core import compute_flags

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [90, 240]                 # окна 900 и 2400 мин
NSYM = 50
RNG = np.random.default_rng(20260909)
PAIRS = [
    # 🔴 ПОЧИНЕНЫ 10.09: wt_div (сравнение с историей фракталов), liq_near и ob_near
    # (порог в долях ATR вместо абсолютных %). Прошлые замеры по ним недействительны.
    ("wt_div_bull_regular", "wt_div_bear_regular", "WT дивергенция ★"),
    ("wt_div_bull_hidden", "wt_div_bear_hidden", "WT див. скрытая ★"),
    ("liq_near_dn", "liq_near_up", "цена у ликвидности ★"),
    ("bull_ob_near", "bear_ob_near", "цена у OB ★"),
    ("rsi_div_bull_regular", "rsi_div_bear_regular", "RSI дивергенция"),
    ("bull_choch_i", "bear_choch_i", "CHoCH internal"),
    ("bull_choch", "bear_choch", "CHoCH swing"),
    ("liq_sweep_dn", "liq_sweep_up", "снятие ликвидности"),
    ("eql_sweep", "eqh_sweep", "снятие EQL/EQH"),
    ("bull_breaker", "bear_breaker", "breaker"),
    ("bull_fvg_overlap", "bear_fvg_overlap", "FVG overlap (iFVG)"),
    ("bull_fvg", "bear_fvg", "FVG свежий"),
    ("bull_ob", "bear_ob", "OB свежий"),
    ("bull_mom", "bear_mom", "моментум"),
]


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last(),
                         "volume": r["volume"].sum()}).dropna()


rows = []          # (lbl, tf, side, sym, half, ret, ctl)
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | окна: {[t*10 for t in TFS]} мин\n", flush=True)
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 300:
            continue
        d.index.name = "ts"
        try:
            fl = compute_flags(d, label="x")
        except Exception as e:
            print(f"  {sym} {tf}m: {type(e).__name__}", flush=True); continue
        fl.columns = [c[:-2] if c.endswith("_x") else c for c in fl.columns]
        c = d["close"].values
        n = len(c)
        h = 10                                   # горизонт = 1 окно слоя
        fwd = np.full(n, np.nan)
        fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
        atr = ((d["high"] - d["low"]) / d["close"]).rolling(100, min_periods=30).mean().values
        ok = ~np.isnan(fwd) & ~np.isnan(atr)
        if ok.sum() < 200:
            continue
        q = np.zeros(n, np.int8)
        q[ok] = np.digitize(atr[ok], np.nanpercentile(atr[ok], [20, 40, 60, 80]))
        pools = {b: np.where(ok & (q == b))[0] for b in range(5)}
        cut = n // 2
        for bull, bear, lbl in PAIRS:
            for side, col in [(1, bull), (-1, bear)]:
                if col not in fl.columns:
                    continue
                ii = np.where(fl[col].values.astype(bool) & ok)[0]
                if len(ii) < 20:
                    continue
                for i in ii:
                    pl = pools[q[i]]
                    ctl = fwd[pl[RNG.integers(len(pl))]] * side if len(pl) else 0.0
                    rows.append((lbl, tf * 10, side, sym, int(i >= cut),
                                 float(fwd[i] * side), float(ctl)))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] событий {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["lbl", "win", "side", "sym", "half", "ret", "ctl"])
R["net"] = R.ret - R.ctl
R.to_pickle(D + r"\confirm_strict.pkl")
print(f"\nсобытий всего: {len(R):,}\n", flush=True)

print("=== ПОЛНЫЙ ПРОТОКОЛ ===")
print(f"{'признак':>22} {'окно':>6} {'стор':>5} {'n':>7} {'сила':>9} {'мед':>9} "
      f"{'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>8} {'без топ10%':>11}")
out = []
for (lbl, win, side), g in R.groupby(["lbl", "win", "side"]):
    if len(g) < 200:
        continue
    a = g.net.mean(); med = g.net.median()
    i_, o_ = g[g.half == 0].net, g[g.half == 1].net
    if len(i_) < 80 or len(o_) < 80:
        continue
    ok = "✓" if i_.mean() * o_.mean() > 0 and a > 0 else "✗"
    per = g.groupby("sym").net.mean()
    good = int((per > 0).sum())
    srt = np.sort(g.net.values)[::-1]
    frag = srt[int(len(srt) * .1):].mean()
    nm = "long" if side == 1 else "short"
    print(f"{lbl:>22} {win:>6} {nm:>5} {len(g):>7,} {a:+8.4f}% {med:+8.4f}% "
          f"{i_.mean():+8.4f}% {o_.mean():+8.4f}% {ok:>8} {good:>3}/{len(per)} "
          f"{frag:+10.4f}%")
    out.append(dict(lbl=lbl, win=int(win), side=nm, n=len(g), a=a, med=med,
                    is_=i_.mean(), oos=o_.mean(), ok=ok == "✓", good=good,
                    tot=len(per), frag=frag))

print("\n=== ЗЕРКАЛЬНОСТЬ: обе стороны обязаны работать (иначе это режим) ===")
print(f"{'признак':>22} {'окно':>6} {'long':>9} {'short':>9} {'обе>0':>7} "
      f"{'IS→OOS обе':>11} {'мин.охват':>10}")
mirror_ok = []
for lbl in {r["lbl"] for r in out}:
    for win in {r["win"] for r in out if r["lbl"] == lbl}:
        L_ = [r for r in out if r["lbl"] == lbl and r["win"] == win and r["side"] == "long"]
        S_ = [r for r in out if r["lbl"] == lbl and r["win"] == win and r["side"] == "short"]
        if not L_ or not S_:
            continue
        l, s = L_[0], S_[0]
        both = l["a"] > 0 and s["a"] > 0
        both_ok = l["ok"] and s["ok"]
        cov = min(l["good"] / l["tot"], s["good"] / s["tot"])
        print(f"{lbl:>22} {win:>6} {l['a']:+8.4f}% {s['a']:+8.4f}% "
              f"{'ДА' if both else 'нет':>7} {'ДА' if both_ok else 'нет':>11} "
              f"{cov*100:9.0f}%")
        if both and both_ok and cov > 0.6:
            mirror_ok.append((lbl, win, l, s))

print("\n=== ВЫЖИЛИ ВСЕ СРЕЗЫ (обе стороны · IS→OOS обе · охват>60% · медианы>0) ===")
final = [(lbl, win, l, s) for lbl, win, l, s in mirror_ok
         if l["med"] > 0 and s["med"] > 0]
if not final:
    print("  НИ ОДИН")
for lbl, win, l, s in sorted(final, key=lambda x: -(x[2]["a"] + x[3]["a"])):
    print(f"  {lbl:>22} {win:>5} мин | long {l['a']:+.4f}% (мед {l['med']:+.4f}%, "
          f"OOS {l['oos']:+.4f}%, {l['good']}/{l['tot']}) | "
          f"short {s['a']:+.4f}% (мед {s['med']:+.4f}%, OOS {s['oos']:+.4f}%, "
          f"{s['good']}/{s['tot']})")
json.dump(out, open(D + r"\confirm_strict.json", "w", encoding="utf-8"), ensure_ascii=False)
