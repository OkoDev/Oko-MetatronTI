# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА КАК ОН ЕГО ОПИСАЛ (10.09.2026).

    «1h даёт кросс в зоне OS → на младших вхожу в лонг при пересечении медианы
     и так гоняю лонги»

  КОНТЕКСТ — СОБЫТИЕ на старшем: кросс wt1×wt2 вверх при wt1 < −60 (перепроданность).
             Включает бычий контекст на LIFE баров старшего ТФ.
  ВХОД     — на младшем: wt1 пересекает МЕДИАНУ вверх. Каждое пересечение = новый вход,
             пока контекст жив («так гоняю»).
  ВЫХОД    — разворот в перекупленности (кросс вниз при wt1 > +60) либо конец контекста.

Зеркально для шорта: кросс вниз в OB на старшем → входы по пересечению медианы вниз.

🔴 Вход по OPEN следующего бара · одна позиция за раз · косты 0.35% · зеркальность.
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
PAIRS = [(60, 5), (60, 15), (240, 15), (240, 60)]   # (контекст, вход)
MED_LEN = 34
OS, OB = -60.0, 60.0
LIFE = 12          # сколько баров старшего ТФ живёт контекст
TIMEOUT = 200
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет: {len(files)} · пары (контекст→вход): {PAIRS} · жизнь контекста "
      f"{LIFE} баров\n", flush=True)


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
    for tf in sorted({t for p in PAIRS for t in p}):
        d = resample(d1, tf)
        if len(d) < 600:
            continue
        w = calculate_wt(d.reset_index(drop=True))
        w1, w2 = w["wt1"].values, w["wt2"].values
        med = pd.Series(w1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
        n = len(w1)
        cu = np.zeros(n, bool); cd = np.zeros(n, bool)
        cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
        cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
        cache[tf] = dict(w1=w1, w2=w2, med=med, cu=cu, cd=cd,
                         os_cross=cu & (w1 < OS),      # КОНТЕКСТ бычий
                         ob_cross=cd & (w1 > OB),      # КОНТЕКСТ медвежий
                         med_up=np.concatenate(([False], (w1[:-1] <= med[:-1]) &
                                                (w1[1:] > med[1:]))),
                         med_dn=np.concatenate(([False], (w1[:-1] >= med[:-1]) &
                                                (w1[1:] < med[1:]))),
                         ct=list(d.index + pd.Timedelta(minutes=tf)),
                         idx=d.index, close=d["close"].values, open=d["open"].values)
    for tf_ctx, tf_in in PAIRS:
        if tf_ctx not in cache or tf_in not in cache:
            continue
        C_, I_ = cache[tf_ctx], cache[tf_in]
        c = I_["close"]; o = I_["open"]; n = len(c)
        # окна жизни контекста в календарном времени
        ctx = []      # (t_start, t_end, side)
        for k in np.where(C_["os_cross"])[0]:
            if k + LIFE < len(C_["ct"]):
                ctx.append((C_["ct"][k], C_["ct"][min(k + LIFE, len(C_["ct"]) - 1)], 1))
        for k in np.where(C_["ob_cross"])[0]:
            if k + LIFE < len(C_["ct"]):
                ctx.append((C_["ct"][k], C_["ct"][min(k + LIFE, len(C_["ct"]) - 1)], -1))
        if not ctx:
            continue
        ctx.sort()
        starts = [x[0] for x in ctx]
        busy = -1
        for i in range(MED_LEN + 5, n - 5):
            for sig, side in ((I_["med_up"][i], 1), (I_["med_dn"][i], -1)):
                if not sig:
                    continue
                t_now = I_["ct"][i]
                # активен ли контекст нужной стороны
                p = bisect.bisect_right(starts, t_now) - 1
                live = False
                for q in range(max(0, p - 3), p + 1):
                    if q < 0 or q >= len(ctx):
                        continue
                    s0, s1, sd = ctx[q]
                    if sd == side and s0 <= t_now <= s1:
                        live = True; break
                if not live:
                    continue
                ii = i + 1
                if ii >= n - 3 or ii <= busy:
                    continue
                exit_arr = I_["ob_cross"] if side == 1 else I_["os_cross"]
                lim = min(ii + TIMEOUT, n - 1)
                jz = np.where(exit_arr[ii + 1:lim + 1])[0]
                if len(jz):
                    jx, how = ii + 1 + int(jz[0]), "zone"
                else:
                    opp = I_["med_dn"] if side == 1 else I_["med_up"]
                    jo = np.where(opp[ii + 1:lim + 1])[0]
                    jx, how = (ii + 1 + int(jo[0]), "med") if len(jo) else (lim, "timeout")
                e = o[ii]
                rows.append(dict(sym=sym, ctx=tf_ctx, tin=tf_in, side=side,
                                 pnl=(c[jx] - e) / e * 100 * side - COST,
                                 bars=jx - ii, how=how, half=int(i >= n // 2)))
                busy = jx
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\egor_method.pkl")
print(f"\nсделок: {len(R):,} · монет {R.sym.nunique()}\n")

print("=== МЕТОД ЕГОРА: контекст (кросс в зоне) → вход (пересечение медианы) ===")
print(f"{'контекст':>9} {'вход':>6} {'стор':>6} {'n':>7} {'нетто':>9} {'мед':>9} "
      f"{'WR':>6} {'баров':>7} {'IS':>9} {'OOS':>9} {'перенос':>8} {'монет+':>9}")
for tf_ctx, tf_in in PAIRS:
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.ctx == tf_ctx) & (R.tin == tf_in) & (R.side == side)]
        if len(g) < 100:
            continue
        i_, o_ = g[g.half == 0].pnl, g[g.half == 1].pnl
        tag = "✓" if len(i_) > 30 and len(o_) > 30 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym").pnl.mean()
        print(f"{tf_ctx:>8}m {tf_in:>5}m {sn:>6} {len(g):>7,} {g.pnl.mean():+8.3f}% "
              f"{g.pnl.median():+8.3f}% {(g.pnl>0).mean()*100:5.1f}% "
              f"{g.bars.median():>7.0f} {i_.mean():+8.3f}% {o_.mean():+8.3f}% "
              f"{tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== СПОСОБ ВЫХОДА ===")
print(f"{'выход':>10} {'n':>8} {'доля':>7} {'нетто':>9} {'мед':>9} {'баров':>7}")
for how in ["zone", "med", "timeout"]:
    g = R[R.how == how]
    if len(g) < 100:
        continue
    print(f"{how:>10} {len(g):>8,} {len(g)/len(R)*100:6.1f}% {g.pnl.mean():+8.3f}% "
          f"{g.pnl.median():+8.3f}% {g.bars.median():>7.0f}")

print("\n=== ЗЕРКАЛЬНОСТЬ ПО ПАРАМ ===")
for tf_ctx, tf_in in PAIRS:
    l = R[(R.ctx == tf_ctx) & (R.tin == tf_in) & (R.side == 1)].pnl
    s = R[(R.ctx == tf_ctx) & (R.tin == tf_in) & (R.side == -1)].pnl
    if len(l) < 100 or len(s) < 100:
        continue
    print(f"  {tf_ctx:>4}m→{tf_in:<4}m: long {l.mean():+.3f}% · short {s.mean():+.3f}% · "
          f"{'ЗЕРКАЛЬНО' if l.mean() > 0 and s.mean() > 0 else 'нет'}")

print("\n=== ХРУПКОСТЬ (лучшая пара) ===")
best = R.groupby(["ctx", "tin"]).pnl.mean().idxmax()
g = R[(R.ctx == best[0]) & (R.tin == best[1])]
v = np.sort(g.pnl.values)[::-1]
print(f"  пара {best[0]}m→{best[1]}m · n={len(g):,}")
print(f"  всё {g.pnl.mean():+.3f}% · без топ-10% {v[int(len(v)*.1):].mean():+.3f}% "
      f"· без топ-25% {v[int(len(v)*.25):].mean():+.3f}%")
