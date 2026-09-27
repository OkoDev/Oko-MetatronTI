# -*- coding: utf-8 -*-
"""СОГЛАСИЕ ЛЕСТНИЦЫ — ДЛЯ УДЕРЖАНИЯ, А НЕ ДЛЯ ВХОДА (Егор, 11.09.2026).

«Согласие всей лестницы нужно для удержания а не для входа» — и это объясняет
прошлый замер: на ВХОДЕ много согласных слоёв = худший результат (ход уже прошёл),
15m long 3 слоя −0.058% против 8 слоёв −0.472%.

Всё по эталону OkoTrend (исходник прислан Егором):
  · медиана = EMA(wt1, 43), наклон = ta.rising/falling(ma, 1) → красит бары
  · дивергенция сравнивается с ОДНИМ предыдущим фракталом (откат моей правки 10.09)
  · контекст = стрелка индикатора: кросс вверх при wt1 < −60 (arrowUp) на 1h

ВХОД  — пересечение EMA-медианы на 15m внутри живого контекста 1h.
УДЕРЖАНИЕ (главная ось, 6 вариантов):
  H0  до противоположной зоны (базовый)
  H1  выход, когда согласных слоёв < 4
  H2  выход, когда согласных слоёв < 6
  H3  выход, когда наклон медианы 15m развернулся против
  H4  выход, когда наклон медианы 1h развернулся против
  H5  до зоны, но досрочно если согласных < 4
ФИЛЬТР ВХОДА: с R+ / без / все.

🔴 Состояние каждого слоя — по времени ЗАКРЫТИЯ его бара. Вход по OPEN следующего.
🔴 Контроль — полная база той же геометрии для каждого варианта удержания.
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
LADDER = [3, 5, 15, 30, 45, 60, 120, 240]
TF_CTX, TF_IN = 60, 15
MA_LEN, MA_REACT = 43, 1
OS_, OB_, LIFE, TIMEOUT, COST = -60.0, 60.0, 12, 300, 0.35
HOLDS = ["H0 до зоны", "H1 согл<4", "H2 согл<6", "H3 наклон 15m",
         "H4 наклон 1h", "H5 зона+согл<4"]
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет {len(files)} · EMA({MA_LEN}) · лестница {LADDER}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows, base = [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    L = {}
    for tf in LADDER:
        dd = resample(d1, tf)
        if len(dd) < 600:
            continue
        w = calculate_wt(dd.reset_index(drop=True))
        w1, w2 = w["wt1"].values, w["wt2"].values
        n_ = len(w1)
        cu = np.zeros(n_, bool); cd = np.zeros(n_, bool)
        cu[1:] = (w1[:-1] <= w2[:-1]) & (w1[1:] > w2[1:])
        cd[1:] = (w1[:-1] >= w2[:-1]) & (w1[1:] < w2[1:])
        ma = pd.Series(w1).ewm(span=MA_LEN, adjust=False).mean().to_numpy()
        # ta.rising(ma, 1) / ta.falling(ma, 1) → dirMa с переносом предыдущего
        rise = np.concatenate(([False], ma[1:] > ma[:-1]))
        fall = np.concatenate(([False], ma[1:] < ma[:-1]))
        dirma = np.zeros(n_, np.int8)
        cur = 0
        for k in range(n_):
            cur = 1 if rise[k] else (-1 if fall[k] else cur)
            dirma[k] = cur
        bull, bear, bull_h, bear_h = _wtx_divergences(w1, dd["low"].values,
                                                      dd["high"].values)
        L[tf] = dict(w1=w1, ma=ma, dirma=dirma,
                     arrow_up=cu & (w1 < OS_), arrow_dn=cd & (w1 > OB_),
                     up=np.concatenate(([False], (w1[:-1] <= ma[:-1]) & (w1[1:] > ma[1:]))),
                     dn=np.concatenate(([False], (w1[:-1] >= ma[:-1]) & (w1[1:] < ma[1:]))),
                     above=w1 > ma, touch_up=w1 >= OB_, touch_dn=w1 <= OS_,
                     div_up=bull, div_dn=bear,
                     ct=(dd.index + pd.Timedelta(minutes=tf)).values,
                     cl=dd.close.values, op=dd.open.values, ts=dd.index)
    if TF_IN not in L or TF_CTX not in L:
        continue
    I_, C_ = L[TF_IN], L[TF_CTX]
    n = len(I_["cl"])
    idx = {tf: np.searchsorted(L[tf]["ct"], I_["ct"], "right") - 1
           for tf in LADDER if tf in L}
    # согласие лестницы на каждом баре ТФ входа, для обеих сторон
    agree_up = np.zeros(n, np.int8)
    for tf in LADDER:
        if tf not in L:
            continue
        j = np.clip(idx[tf], 0, len(L[tf]["above"]) - 1)
        agree_up += L[tf]["above"][j].astype(np.int8)
    nlad = sum(1 for tf in LADDER if tf in L)
    dm_in = I_["dirma"]
    j_ctx = np.clip(idx[TF_CTX], 0, len(C_["dirma"]) - 1)
    dm_ctx = C_["dirma"][j_ctx]

    def exit_at(ii, side, mode):
        lim = min(ii + TIMEOUT, n - 1)
        zone = I_["touch_up"] if side == 1 else I_["touch_dn"]
        ag = agree_up if side == 1 else (nlad - agree_up)
        for k in range(ii + 1, lim + 1):
            if zone[k] and mode in (0, 5):
                return k
            if mode == 1 and ag[k] < 4:
                return k
            if mode == 2 and ag[k] < 6:
                return k
            if mode == 3 and dm_in[k] != side:
                return k
            if mode == 4 and dm_ctx[k] != side:
                return k
            if mode == 5 and ag[k] < 4:
                return k
        return lim

    ctx = []
    for arr, sd in ((C_["arrow_up"], 1), (C_["arrow_dn"], -1)):
        for k in np.where(arr)[0]:
            if k + LIFE < len(C_["ct"]):
                ctx.append((C_["ct"][k], C_["ct"][k + LIFE], sd))
    if not ctx:
        continue
    ctx.sort(); st = [x[0] for x in ctx]
    busy = {(m, s): -1 for m in range(6) for s in (1, -1)}
    for i in range(max(120, MA_LEN + 5), n - 5):
        for sig, side in ((I_["up"][i], 1), (I_["dn"][i], -1)):
            if not sig:
                continue
            t_now = I_["ct"][i]
            q = bisect.bisect_right(st, t_now) - 1
            if not any(ctx[z][2] == side and ctx[z][0] <= t_now <= ctx[z][1]
                       for z in range(max(0, q - 4), q + 1) if 0 <= z < len(ctx)):
                continue
            ii = i + 1
            if ii >= n - 3:
                continue
            dT = int((I_["div_up"] if side == 1 else I_["div_dn"])[i])
            ag0 = int(agree_up[i] if side == 1 else nlad - agree_up[i])
            e = I_["op"][ii]
            for m in range(6):
                if ii <= busy[(m, side)]:
                    continue
                jx = exit_at(ii, side, m)
                busy[(m, side)] = jx
                rows.append((sym, side, m, dT, ag0,
                             (I_["cl"][jx] - e) / e * 100 * side - COST, jx - ii,
                             int(I_["ts"][i].year)))
    for side in (1, -1):
        for m in range(6):
            for ii in range(120, n - 4, 60):
                jx = exit_at(ii, side, m)
                e = I_["op"][ii]
                base.append((sym, side, m,
                             (I_["cl"][jx] - e) / e * 100 * side - COST, jx - ii))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "hold", "div", "agree", "pnl",
                                "bars", "year"])
B = pd.DataFrame(base, columns=["sym", "side", "hold", "pnl", "bars"])
R.to_pickle(D + r"\egor_hold.pkl"); B.to_pickle(D + r"\egor_hold_base.pkl")
bm = B.groupby(["side", "hold"]).pnl.mean()
print(f"\nсигналов {len(R):,} · монет {R.sym.nunique()}\n")


def blk(g):
    v = np.sort(g.pnl.values)[::-1]
    per = g.groupby("sym").pnl.mean()
    return v[int(len(v)*.1):].mean(), int((per > 0).sum()), len(per)


print("=== ВАРИАНТЫ УДЕРЖАНИЯ (все входы) ===")
print(f"{'удержание':>16} {'стор':>6} {'n':>7} {'нетто':>9} {'база':>9} {'над':>9} "
      f"{'мед':>9} {'WR':>6} {'баров':>6} {'безтоп10':>9} {'монет+':>7}")
for m in range(6):
    for side, sn in [(1, "long"), (-1, "short")]:
        g = R[(R.hold == m) & (R.side == side)]
        if len(g) < 150:
            continue
        t10, sp, sn_ = blk(g)
        b = float(bm.get((side, m), np.nan))
        print(f"{HOLDS[m]:>16} {sn:>6} {len(g):>7,} {g.pnl.mean():+8.3f}% {b:+8.3f}% "
              f"{g.pnl.mean()-b:+8.3f}% {g.pnl.median():+8.3f}% "
              f"{(g.pnl>0).mean()*100:5.1f}% {g.bars.median():>6.0f} {t10:+8.3f}% "
              f"{sp}/{sn_}")
    print()

print("=== + ДИВЕРГЕНЦИЯ R+ НА ВХОДЕ (эталонный детектор) ===")
print(f"{'удержание':>16} {'стор':>6} {'R+':>4} {'n':>7} {'доля':>7} {'нетто':>9} "
      f"{'над базой':>10} {'мед':>9} {'безтоп10':>9} {'монет+':>7}")
for m in range(6):
    for side, sn in [(1, "long"), (-1, "short")]:
        tot = len(R[(R.hold == m) & (R.side == side)])
        if tot < 150:
            continue
        b = float(bm.get((side, m), np.nan))
        for dv in (1, 0):
            g = R[(R.hold == m) & (R.side == side) & (R.div == dv)]
            if len(g) < 60:
                continue
            t10, sp, sn_ = blk(g)
            print(f"{HOLDS[m]:>16} {sn:>6} {'да' if dv else 'нет':>4} {len(g):>7,} "
                  f"{len(g)/tot*100:6.1f}% {g.pnl.mean():+8.3f}% "
                  f"{g.pnl.mean()-b:+9.3f}% {g.pnl.median():+8.3f}% {t10:+8.3f}% "
                  f"{sp}/{sn_}")
    print()

print("=== СОГЛАСИЕ НА ВХОДЕ × УДЕРЖАНИЕ ПО СОГЛАСИЮ (H1) ===")
print(f"{'стор':>6} {'согл. на входе':>16} {'n':>7} {'нетто H0':>10} {'нетто H1':>10} "
      f"{'разница':>9}")
for side, sn in [(1, "long"), (-1, "short")]:
    for lo, hi, lbl in [(0, 3, "мало (≤3)"), (4, 5, "средне (4-5)"),
                        (6, 8, "много (≥6)")]:
        g0 = R[(R.hold == 0) & (R.side == side) & R.agree.between(lo, hi)]
        g1 = R[(R.hold == 1) & (R.side == side) & R.agree.between(lo, hi)]
        if len(g0) < 100 or len(g1) < 100:
            continue
        print(f"{sn:>6} {lbl:>16} {len(g0):>7,} {g0.pnl.mean():+9.3f}% "
              f"{g1.pnl.mean():+9.3f}% {g1.pnl.mean()-g0.pnl.mean():+8.3f}%")
    print()
