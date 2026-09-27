# -*- coding: utf-8 -*-
"""СТРУКТУРНЫЙ СТОП ВМЕСТО ВЫХОДА ПО МЕДИАНЕ (Егор, 10.09.2026).

    «и тут нам в помощь структура! стоп короткий — структурный!
     и входы ищем вблизи структурных пиков или от OB/OS, а не просто в воздухе»

Прошлый замер: выход по обратной медиане = 63% сделок по −0.744% за 13 баров.
Дошедшие до перекупленности: 36.6% по +1.727% за 91 бар. Значит выход по медиане
надо заменить, а не оптимизировать.

ЧЕТЫРЕ ПОЛИТИКИ на ОДНИХ И ТЕХ ЖЕ входах:
    E1  обратная медиана (старая, baseline)
    E2  только зона + таймаут (без стопа — сколько стоит «просто держать»)
    E3  зона + СТРУКТУРНЫЙ стоп (последний подтверждённый internal swing, len=5)
    E4  зона + структурный стоп с буфером 0.25·ATR

Плюс вторая мысль Егора — «вход не в воздухе»: расстояние входа до структурного
уровня в ATR. Близко к свингу = короткий стоп. Разрез по размеру стопа обязателен
(ЗАКОН: весь эдж прошлых находок сидел в размере стопа).

🔴 Свинг берётся ТОЛЬКО с бара ПОДТВЕРЖДЕНИЯ (_swings отдаёт conf_i отдельно).
🔴 Вход по OPEN следующего бара · одна позиция · косты 0.35% на круг.
🔴 Если на баре и стоп и цель — считается СТОП (консервативно).
"""
import os, sys, glob, bisect, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt
from core.smc.oko_sm_engine import _swings

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
PAIRS = [(60, 15), (240, 60)]
MED_LEN = 34
OS, OB = -60.0, 60.0
LIFE = 12
TIMEOUT = 200
SW_LEN = 5          # короткий структурный свинг
COST = 0.35
BUF = 0.25          # буфер стопа в ATR
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))
print(f"монет: {len(files)} · пары {PAIRS} · структурный свинг len={SW_LEN}\n", flush=True)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def atr_pct(h, l, c, period=14):
    prev = np.concatenate(([c[0]], c[:-1]))
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))
    return pd.Series(np.where(c > 0, tr / c * 100, np.nan)).rolling(
        period, min_periods=5).mean().to_numpy(float)


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
        hi, lo, cl, op = (d["high"].values, d["low"].values,
                          d["close"].values, d["open"].values)
        # ── структурные уровни, известные КАУЗАЛЬНО (с бара подтверждения)
        last_top = np.full(n, np.nan); last_btm = np.full(n, np.nan)
        for conf_i, sw_i, price, is_top in _swings(d["high"], d["low"], SW_LEN):
            if is_top:
                last_top[conf_i] = price
            else:
                last_btm[conf_i] = price
        last_top = pd.Series(last_top).ffill().to_numpy(float)
        last_btm = pd.Series(last_btm).ffill().to_numpy(float)
        cache[tf] = dict(
            w1=w1, med=med, cu=cu, cd=cd, hi=hi, lo=lo, cl=cl, op=op,
            os_cross=cu & (w1 < OS), ob_cross=cd & (w1 > OB),
            med_up=np.concatenate(([False], (w1[:-1] <= med[:-1]) & (w1[1:] > med[1:]))),
            med_dn=np.concatenate(([False], (w1[:-1] >= med[:-1]) & (w1[1:] < med[1:]))),
            top=last_top, btm=last_btm, atr=atr_pct(hi, lo, cl),
            ct=list(d.index + pd.Timedelta(minutes=tf)))
    for tf_ctx, tf_in in PAIRS:
        if tf_ctx not in cache or tf_in not in cache:
            continue
        C_, I_ = cache[tf_ctx], cache[tf_in]
        n = len(I_["cl"])
        ctx = []
        for arr, sd in ((C_["os_cross"], 1), (C_["ob_cross"], -1)):
            for k in np.where(arr)[0]:
                if k + LIFE < len(C_["ct"]):
                    ctx.append((C_["ct"][k], C_["ct"][k + LIFE], sd))
        if not ctx:
            continue
        ctx.sort(); starts = [x[0] for x in ctx]
        busy = {1: -1, 2: -1, 3: -1, 4: -1}
        for i in range(MED_LEN + 5, n - 5):
            for sig, side in ((I_["med_up"][i], 1), (I_["med_dn"][i], -1)):
                if not sig:
                    continue
                t_now = I_["ct"][i]
                p = bisect.bisect_right(starts, t_now) - 1
                live = any(ctx[q][2] == side and ctx[q][0] <= t_now <= ctx[q][1]
                           for q in range(max(0, p - 3), p + 1) if 0 <= q < len(ctx))
                if not live:
                    continue
                ii = i + 1
                if ii >= n - 3:
                    continue
                e = I_["op"][ii]
                a = I_["atr"][i]
                if not np.isfinite(a) or a <= 0:
                    continue
                lvl = I_["btm"][i] if side == 1 else I_["top"][i]
                if not np.isfinite(lvl):
                    continue
                # размер структурного стопа в % от входа (до буфера)
                raw = (e - lvl) / e * 100 * side
                zone = I_["ob_cross"] if side == 1 else I_["os_cross"]
                opp = I_["med_dn"] if side == 1 else I_["med_up"]
                lim = min(ii + TIMEOUT, n - 1)
                jz = np.where(zone[ii + 1:lim + 1])[0]
                j_zone = ii + 1 + int(jz[0]) if len(jz) else None
                jo = np.where(opp[ii + 1:lim + 1])[0]
                j_med = ii + 1 + int(jo[0]) if len(jo) else None

                def run(stop_pct):
                    """вернуть (pnl%, как, баров). stop_pct=None → без стопа."""
                    end = j_zone if j_zone is not None else lim
                    if stop_pct is not None and stop_pct > 0:
                        sp = e * (1 - stop_pct / 100) if side == 1 else e * (1 + stop_pct / 100)
                        for k in range(ii, end + 1):
                            if (side == 1 and I_["lo"][k] <= sp) or \
                               (side == -1 and I_["hi"][k] >= sp):
                                return (sp - e) / e * 100 * side - COST, "stop", k - ii
                    how = "zone" if j_zone is not None else "timeout"
                    return (I_["cl"][end] - e) / e * 100 * side - COST, how, end - ii

                out = {}
                # E1 обратная медиана
                end1 = min(x for x in [j_zone, j_med, lim] if x is not None)
                how1 = "zone" if end1 == j_zone else ("med" if end1 == j_med else "timeout")
                out[1] = ((I_["cl"][end1] - e) / e * 100 * side - COST, how1, end1 - ii)
                out[2] = run(None)                      # E2 без стопа
                out[3] = run(raw)                       # E3 структурный
                out[4] = run(raw + BUF * a)             # E4 + буфер
                rec = dict(sym=sym, ctx=tf_ctx, tin=tf_in, side=side,
                           atr=float(a), stop_raw=float(raw), stop_buf=float(raw + BUF * a),
                           dist_atr=float(raw / a), half=int(i >= n // 2))
                for k, (pn, hw, bb) in out.items():
                    rec[f"p{k}"] = pn; rec[f"h{k}"] = hw; rec[f"b{k}"] = bb
                    rec[f"ok{k}"] = int(ii > busy[k])
                    if ii > busy[k]:
                        busy[k] = ii + bb
                rows.append(rec)
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\egor_stop.pkl")
print(f"\nсделок (сигналов): {len(R):,} · монет {R.sym.nunique()}\n")

NAMES = {1: "E1 обратная медиана", 2: "E2 без стопа (зона/таймаут)",
         3: "E3 структурный стоп", 4: f"E4 структурный +{BUF}ATR"}
print("=== ПОЛИТИКИ ВЫХОДА (только неперекрывающиеся сделки каждой политики) ===")
for tf_ctx, tf_in in PAIRS:
    print(f"\n  ── {tf_ctx}m → {tf_in}m ──")
    print(f"{'политика':>28} {'стор':>6} {'n':>7} {'нетто':>9} {'мед':>9} {'WR':>6} "
          f"{'баров':>7} {'IS':>9} {'OOS':>9} {'пер':>4} {'монет+':>8} {'безтоп10':>9}")
    for k in [1, 2, 3, 4]:
        for side, sn in [(1, "long"), (-1, "short")]:
            g = R[(R.ctx == tf_ctx) & (R.tin == tf_in) & (R.side == side) &
                  (R[f"ok{k}"] == 1)]
            if len(g) < 100:
                continue
            pn = g[f"p{k}"]
            i_, o_ = g[g.half == 0][f"p{k}"], g[g.half == 1][f"p{k}"]
            tag = "✓" if len(i_) > 30 and len(o_) > 30 and i_.mean() > 0 \
                and o_.mean() > 0 else "✗"
            per = g.groupby("sym")[f"p{k}"].mean()
            v = np.sort(pn.values)[::-1]
            print(f"{NAMES[k]:>28} {sn:>6} {len(g):>7,} {pn.mean():+8.3f}% "
                  f"{pn.median():+8.3f}% {(pn>0).mean()*100:5.1f}% "
                  f"{g[f'b{k}'].median():>7.0f} {i_.mean():+8.3f}% {o_.mean():+8.3f}% "
                  f"{tag:>4} {int((per>0).sum())}/{len(per)} "
                  f"{v[int(len(v)*.1):].mean():+8.3f}%")
        print()

print("=== КАК ЗАКАНЧИВАЮТСЯ СДЕЛКИ ===")
for k in [1, 3, 4]:
    g = R[R[f"ok{k}"] == 1]
    print(f"\n  {NAMES[k]}:")
    for hw in ["zone", "stop", "med", "timeout"]:
        s = g[g[f"h{k}"] == hw]
        if len(s) < 50:
            continue
        print(f"    {hw:>8} {len(s):>7,} {len(s)/len(g)*100:5.1f}% "
              f"{s[f'p{k}'].mean():+8.3f}% мед {s[f'p{k}'].median():+8.3f}% "
              f"баров {s[f'b{k}'].median():>4.0f}")

print("\n=== РАЗМЕР СТРУКТУРНОГО СТОПА (ЗАКОН РАЗМЕРА) — политика E3 ===")
g = R[R.ok3 == 1].copy()
g = g[g.stop_raw > 0]
g["q"] = pd.qcut(g.stop_raw, 5, labels=False, duplicates="drop")
print(f"{'квинт':>6} {'стоп %':>8} {'в ATR':>7} {'n':>7} {'нетто':>9} {'мед':>9} "
      f"{'WR':>6} {'стопов':>8}")
for q in sorted(g.q.dropna().unique()):
    s = g[g.q == q]
    print(f"{int(q)+1:>6} {s.stop_raw.median():7.2f}% {s.dist_atr.median():6.2f} "
          f"{len(s):>7,} {s.p3.mean():+8.3f}% {s.p3.median():+8.3f}% "
          f"{(s.p3>0).mean()*100:5.1f}% {(s.h3=='stop').mean()*100:7.1f}%")

print("\n=== ВХОД «НЕ В ВОЗДУХЕ»: расстояние до структуры в ATR ===")
print(f"{'близость':>22} {'n':>7} {'доля':>7} {'нетто E3':>10} {'мед':>9} {'монет+':>8}")
for lbl, cond in [("вплотную ≤0.5 ATR", g.dist_atr <= 0.5),
                  ("близко 0.5-1 ATR", (g.dist_atr > 0.5) & (g.dist_atr <= 1.0)),
                  ("далеко 1-2 ATR", (g.dist_atr > 1.0) & (g.dist_atr <= 2.0)),
                  ("в воздухе >2 ATR", g.dist_atr > 2.0)]:
    s = g[cond]
    if len(s) < 100:
        continue
    per = s.groupby("sym").p3.mean()
    print(f"{lbl:>22} {len(s):>7,} {len(s)/len(g)*100:6.1f}% {s.p3.mean():+9.3f}% "
          f"{s.p3.median():+8.3f}% {int((per>0).sum())}/{len(per)}")
