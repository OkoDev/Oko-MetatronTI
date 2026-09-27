# -*- coding: utf-8 -*-
"""ЧЕТЫРЕ РАСХОЖДЕНИЯ МЕЖДУ СЛОВАМИ ЕГОРА И МОИМ КОДОМ (10.09.2026).

Егор: «оно работает, мне просто руками сложно отслеживать» ⇒ искать недочёт
в МОЕЙ формализации, а не в его схеме.

  ОСЬ M — что такое «медиана»:
      zero   wt1 пересекает НОЛЬ (средняя линия осциллятора WT) ← его вероятный смысл
      sma34  wt1 пересекает SMA(wt1,34)                         ← что я взял от себя
  ОСЬ X — что такое «выход в перекупленности»:
      touch  wt1 ДОШЁЛ до зоны (>= +60 для лонга)               ← его вероятный смысл
      cross  кросс wt1×wt2 вниз ПРИ wt1 > +60                   ← что я взял
  ОСЬ C — сколько живёт разрешение старшего:
      until  от кросса в OS до прихода старшего в OB (отработка хода) ← естественнее
      life12 фиксированные 12 баров старшего                    ← я придумал
  ОСЬ P — пары ТФ: (60,15) как он говорит · (240,60) · (240,15)

2×2×2×3 = 24 конфигурации. Данные: 15m-кэш 2022-2026, ресемпл в 1h и 4h.
🔴 Вход по OPEN следующего бара · одна позиция на конфигурацию · косты 0.35%.
🔴 Контроль: ПОЛНАЯ БАЗА той же геометрии (не ±30 дней — он смещён вниз).
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
OS_, OB_ = -60.0, 60.0
MED_LEN, LIFE, TIMEOUT, COST = 34, 12, 400, 0.35
PAIRS = [(60, 15), (240, 60), (240, 15)]
NSYM = 160
con = sqlite3.connect("ohlcv_cache.db")
syms = [r[0] for r in con.execute(
    "select symbol from ohlcv_cache where timeframe='15m' "
    "group by symbol having count(*) > 50000 order by count(*) desc")][:NSYM]
print(f"символов: {len(syms)} · 24 конфигурации (M×X×C×P)\n", flush=True)


def prep(d, tf):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w["wt1"].values, w["wt2"].values
    n = len(w1)
    cu = np.zeros(n, bool); cd = np.zeros(n, bool)
    cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
    cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
    sma = pd.Series(w1).rolling(MED_LEN, min_periods=MED_LEN // 2).mean().values
    out = dict(w1=w1, cu=cu, cd=cd,
               os_cross=cu & (w1 < OS_), ob_cross=cd & (w1 > OB_),
               touch_up=w1 >= OB_, touch_dn=w1 <= OS_,
               ct=list(d.index + pd.Timedelta(minutes=tf)),
               cl=d.close.values, op=d.open.values, year=d.index.year.values)
    for name, ref in (("zero", np.zeros(n)), ("sma34", sma)):
        out[f"up_{name}"] = np.concatenate(([False], (w1[:-1] <= ref[:-1]) &
                                            (w1[1:] > ref[1:])))
        out[f"dn_{name}"] = np.concatenate(([False], (w1[:-1] >= ref[:-1]) &
                                            (w1[1:] < ref[1:])))
        out[f"above_{name}"] = w1 > ref
    return out


rows, base = [], []
for fi, sym in enumerate(syms, 1):
    d = pd.read_sql("select time,open,high,low,close from ohlcv_cache "
                    "where symbol=? and timeframe='15m' order by time",
                    con, params=(sym,))
    if len(d) < 50000:
        continue
    d["ts"] = pd.to_datetime(d.time, unit="ms")
    d = d.drop_duplicates("ts").set_index("ts")
    cache = {}
    for tf in sorted({t for p in PAIRS for t in p}):
        dd = d if tf == 15 else d.resample(f"{tf}min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        if len(dd) < 500:
            continue
        cache[tf] = prep(dd, tf)

    def exit_bar(I_, ii, side, xv, lim):
        """вернуть (бар выхода, как)."""
        if xv == "touch":
            arr = I_["touch_up"] if side == 1 else I_["touch_dn"]
        else:
            arr = I_["ob_cross"] if side == 1 else I_["os_cross"]
        j = np.where(arr[ii + 1:lim + 1])[0]
        return (ii + 1 + int(j[0]), "zone") if len(j) else (lim, "timeout")

    for tf_ctx, tf_in in PAIRS:
        if tf_ctx not in cache or tf_in not in cache:
            continue
        C_, I_ = cache[tf_ctx], cache[tf_in]
        n = len(I_["cl"])
        # ── окна разрешения: два варианта
        ctxs = {}
        for cv in ("until", "life12"):
            lst = []
            for arr, sd in ((C_["os_cross"], 1), (C_["ob_cross"], -1)):
                tch = C_["touch_up"] if sd == 1 else C_["touch_dn"]
                for k in np.where(arr)[0]:
                    if cv == "life12":
                        if k + LIFE < len(C_["ct"]):
                            lst.append((C_["ct"][k], C_["ct"][k + LIFE], sd))
                    else:
                        nxt = np.where(tch[k + 1:])[0]
                        end = k + 1 + int(nxt[0]) if len(nxt) else len(C_["ct"]) - 1
                        if end < len(C_["ct"]):
                            lst.append((C_["ct"][k], C_["ct"][end], sd))
            lst.sort()
            ctxs[cv] = (lst, [x[0] for x in lst])
        busy = {}
        for i in range(MED_LEN + 5, n - 5):
            for mv in ("zero", "sma34"):
                for s_, side in ((I_[f"up_{mv}"][i], 1), (I_[f"dn_{mv}"][i], -1)):
                    if not s_:
                        continue
                    t_now = I_["ct"][i]
                    for cv in ("until", "life12"):
                        lst, st = ctxs[cv]
                        if not lst:
                            continue
                        p = bisect.bisect_right(st, t_now) - 1
                        if not any(lst[q][2] == side and lst[q][0] <= t_now <= lst[q][1]
                                   for q in range(max(0, p - 4), p + 1)
                                   if 0 <= q < len(lst)):
                            continue
                        ii = i + 1
                        if ii >= n - 3:
                            continue
                        for xv in ("touch", "cross"):
                            key = (tf_ctx, tf_in, mv, cv, xv, side)
                            if ii <= busy.get(key, -1):
                                continue
                            lim = min(ii + TIMEOUT, n - 1)
                            jx, how = exit_bar(I_, ii, side, xv, lim)
                            e = I_["op"][ii]
                            busy[key] = jx
                            rows.append((sym, tf_ctx, tf_in, mv, cv, xv, side,
                                         (I_["cl"][jx] - e) / e * 100 * side - COST,
                                         jx - ii, how, int(I_["year"][i])))
        # ── контроль: полная база той же геометрии (каждый 30-й бар)
        for xv in ("touch", "cross"):
            for side in (1, -1):
                for ii in range(MED_LEN + 6, n - 4, 30):
                    lim = min(ii + TIMEOUT, n - 1)
                    jx, how = exit_bar(I_, ii, side, xv, lim)
                    e = I_["op"][ii]
                    base.append((sym, tf_in, xv, side,
                                 (I_["cl"][jx] - e) / e * 100 * side - COST,
                                 jx - ii, int(I_["year"][ii])))
    if fi % 20 == 0:
        print(f"  [{fi}/{len(syms)}] сигналов {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "ctx", "tin", "mv", "cv", "xv", "side",
                                "pnl", "bars", "how", "year"])
B = pd.DataFrame(base, columns=["sym", "tin", "xv", "side", "pnl", "bars", "year"])
R.to_pickle(D + r"\egor_variants.pkl"); B.to_pickle(D + r"\egor_variants_base.pkl")
print(f"\nсигналов {len(R):,} · база {len(B):,} · монет {R.sym.nunique()}\n")
RG = {2022: "МЕДВ", 2023: "БЫК", 2024: "нейтр", 2025: "МЕДВ", 2026: "МЕДВ"}

bmean = B.groupby(["tin", "xv", "side"]).pnl.mean()
print("=== 24 КОНФИГУРАЦИИ, ОТСОРТИРОВАНЫ ПО безтоп10% (обе стороны вместе) ===")
print(f"{'пара':>10} {'медиана':>8} {'выход':>7} {'контекст':>8} {'стор':>6} {'n':>7} "
      f"{'нетто':>9} {'база':>9} {'над базой':>10} {'мед':>9} {'WR':>6} {'баров':>6} "
      f"{'безтоп10':>9} {'монет+':>9} {'лет+':>5}")
out = []
for (ctx, tin, mv, cv, xv, side), g in R.groupby(["ctx", "tin", "mv", "cv", "xv",
                                                  "side"]):
    if len(g) < 300:
        continue
    bm = float(bmean.get((tin, xv, side), np.nan))
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    yrs = g.groupby("year").pnl.mean()
    out.append(dict(ctx=ctx, tin=tin, mv=mv, cv=cv, xv=xv, side=side, n=len(g),
                    mean=g.pnl.mean(), base=bm, over=g.pnl.mean() - bm,
                    med=g.pnl.median(), wr=(g.pnl > 0).mean(),
                    bars=g.bars.median(), top10=v[int(len(v)*.1):].mean(),
                    sp=int((per > 0).sum()), sn=len(per),
                    yp=int((yrs > 0).sum()), yn=len(yrs)))
O = pd.DataFrame(out).sort_values("top10", ascending=False)
for _, r in O.iterrows():
    print(f"{f'{int(r.ctx)}→{int(r.tin)}':>10} {r.mv:>8} {r.xv:>7} {r.cv:>8} "
          f"{'long' if r.side==1 else 'short':>6} {int(r.n):>7,} {r['mean']:+8.3f}% "
          f"{r.base:+8.3f}% {r.over:+9.3f}% {r.med:+8.3f}% {r.wr*100:5.1f}% "
          f"{r.bars:>6.0f} {r.top10:+8.3f}% {int(r.sp)}/{int(r.sn)} "
          f"{int(r.yp)}/{int(r.yn)}")

print("\n=== ВКЛАД КАЖДОЙ ОСИ (средний безтоп10% по всем прочим настройкам) ===")
for ax, nm in [("mv", "медиана"), ("xv", "выход"), ("cv", "контекст"), ("tin", "ТФ входа")]:
    print(f"\n  {nm}:")
    for v_ in sorted(O[ax].unique(), key=str):
        s = O[O[ax] == v_]
        print(f"    {str(v_):>8}: безтоп10% {s.top10.mean():+.3f}% · над базой "
              f"{s.over.mean():+.3f}% · нетто {s['mean'].mean():+.3f}% "
              f"(ячеек {len(s)})")

print("\n=== ЛУЧШАЯ КОНФИГУРАЦИЯ: РАЗРЕЗ ПО ГОДУ ===")
b = O.iloc[0]
g = R[(R.ctx == b.ctx) & (R.tin == b.tin) & (R.mv == b.mv) & (R.cv == b.cv) &
      (R.xv == b.xv) & (R.side == b.side)]
print(f"  {int(b.ctx)}m→{int(b.tin)}m · медиана={b.mv} · выход={b.xv} · "
      f"контекст={b.cv} · {'long' if b.side==1 else 'short'} · n={len(g):,}")
print(f"{'год':>7} {'режим':>7} {'n':>7} {'нетто':>9} {'база':>9} {'над':>9} "
      f"{'мед':>9} {'безтоп10':>9} {'монет+':>9}")
for y in sorted(g.year.unique()):
    s = g[g.year == y]
    bb = B[(B.tin == b.tin) & (B.xv == b.xv) & (B.side == b.side) & (B.year == y)]
    if len(s) < 40:
        continue
    v = np.sort(s.pnl.values)[::-1]; per = s.groupby("sym").pnl.mean()
    bm = bb.pnl.mean() if len(bb) > 20 else np.nan
    print(f"{y:>7} {RG.get(y,'?'):>7} {len(s):>7,} {s.pnl.mean():+8.3f}% {bm:+8.3f}% "
          f"{s.pnl.mean()-bm:+8.3f}% {s.pnl.median():+8.3f}% "
          f"{v[int(len(v)*.1):].mean():+8.3f}% {int((per>0).sum())}/{len(per)}")

print("\n=== ЗЕРКАЛЬНОСТЬ ЛУЧШИХ КОНФИГУРАЦИЙ ===")
for (ctx, tin, mv, cv, xv), g in O.groupby(["ctx", "tin", "mv", "cv", "xv"]):
    if len(g) < 2:
        continue
    l = g[g.side == 1]; s = g[g.side == -1]
    if not len(l) or not len(s):
        continue
    print(f"  {int(ctx)}→{int(tin)} {mv:>6} {xv:>6} {cv:>6}: "
          f"long над базой {float(l.over.iloc[0]):+.3f}% безтоп10 "
          f"{float(l.top10.iloc[0]):+.3f}% · short над базой "
          f"{float(s.over.iloc[0]):+.3f}% безтоп10 {float(s.top10.iloc[0]):+.3f}%")
