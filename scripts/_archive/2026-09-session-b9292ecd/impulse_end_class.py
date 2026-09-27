# -*- coding: utf-8 -*-
"""ЗАВЕРШЕНИЕ ИЛИ ПАУЗА: различает ли матрица согласия (Егор, 09.09.2026).

Якорь — ПРЕДПОЛАГАЕМОЕ завершение импульса (нога ≥K·ATR, экстремум не обновлялся 2 бара).
Факт становится известен позже:
    экстремум НЕ превышен за N баров  →  завершение настоящее
    экстремум превышен                →  была пауза, импульс продолжился

Вопрос: различает ли эти два исхода MTF-матрица детекторов × ТФ (с 1m).
Метрика — доля «настоящих завершений» в зависимости от согласия, против базовой доли.
Плюс деньги: вход против импульса при высоком согласии, с контролем и зеркальностью.
"""
import os, sys, glob, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [1, 3, 5, 15, 45, 60, 240, 1440]
SWING = 10
ANCHOR_TFS = [3, 15, 60, 240]   # слой якоря — ОСЬ замера, не константа
K_LIST = [2.0, 3.0, 5.0]        # проверка чувствительности к порогу
CONFIRM_BARS = 40          # сколько баров ANCHOR_TF ждём обновления экстремума (10 часов)
LTF_TRIG = [1, 3]          # ЭТАП 3: на каких LTF ищем триггер входа
TRIG_WAIT_H = 6.0          # сколько часов ждём триггер после подтверждения
FWD_H = 24
NSYM = 40
COST = 0.35
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | ТФ: {TFS} | подтверждение {CONFIRM_BARS} баров "
      f"{ANCHOR_TF}m\n", flush=True)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    cell, trig = {}, {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 200:
            continue
        ct = list(d.index + pd.Timedelta(minutes=tf))
        n = len(d)
        st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
        tr = np.zeros(n, np.int8); t_ = 0; p = 0
        ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
        for b in range(n):
            while p < len(ev) and ev[p].i <= b:
                t_ = 1 if ev[p].bull else -1; p += 1
            tr[b] = t_
        w = calculate_wt(d.reset_index(drop=True))
        wt1, wt2 = w["wt1"].values, w["wt2"].values
        wt = np.where(wt1 > wt2, 1, -1).astype(np.int8)
        zone = np.where(wt1 < -60, 1, np.where(wt1 > 60, -1, 0)).astype(np.int8)
        br, ber, _, _ = _wtx_divergences(wt1, d["low"].values, d["high"].values)
        dv = np.zeros(n, np.int8)
        for i in np.where(br)[0]:
            dv[i:min(i + 5, n)] = 1
        for i in np.where(ber)[0]:
            dv[i:min(i + 5, n)] = -1
        cell[("Trend", tf)] = (ct, tr)
        cell[("WT", tf)] = (ct, wt)
        cell[("Zone", tf)] = (ct, zone)
        cell[("Div", tf)] = (ct, dv)
        # ЭТАП 3: триггеры входа на LTF — CHoCH в сторону разворота
        if tf in LTF_TRIG:
            ch_b, ch_s = [], []
            for e_ in st.events:
                if e_.kind == "CHoCH":
                    (ch_b if e_.bull else ch_s).append(ct[e_.i] if e_.i < len(ct) else None)
            trig[tf] = (sorted([x for x in ch_b if x is not None]),
                        sorted([x for x in ch_s if x is not None]))
    if ("Trend", ANCHOR_TF) not in cell:
        continue
    da = resample(d1, ANCHOR_TF)
    hi, lo, cl = da["high"].values, da["low"].values, da["close"].values
    atr = ((da["high"] - da["low"]) / da["close"]).rolling(50, min_periods=20).mean().values
    n = len(da); M = 20
    ts_a = da.index.values
    m1_t, m1_c = d1.index.values, d1["close"].values
    for t in range(M + 5, n - CONFIRM_BARS - 5):
        if np.isnan(atr[t]) or atr[t] <= 0:
            continue
        s = t - M
        side = 0
        if (hi[s:t + 1].max() - lo[s]) / lo[s] >= K_ATR * atr[t] \
                and hi[t - 1:t + 1].max() < hi[s:t].max():
            side = 1
        elif (hi[s] - lo[s:t + 1].min()) / hi[s] >= K_ATR * atr[t] \
                and lo[t - 1:t + 1].min() > lo[s:t].min():
            side = -1
        if side == 0:
            continue
        # ФАКТ: превышен ли экстремум импульса за CONFIRM_BARS
        if side == 1:
            peak = hi[s:t + 1].max()
            ended = int(hi[t + 1:t + 1 + CONFIRM_BARS].max() < peak)
        else:
            trough = lo[s:t + 1].min()
            ended = int(lo[t + 1:t + 1 + CONFIRM_BARS].min() > trough)
        t_now = pd.Timestamp(ts_a[t] + np.timedelta64(ANCHOR_TF, "m"))
        row = {}
        for (det, tf), (ct, vals) in cell.items():
            j = bisect.bisect_right(ct, t_now) - 1
            row[(det, tf)] = int(vals[j]) if 0 <= j < len(vals) else 0
        i1 = int(np.searchsorted(m1_t, t_now.to_datetime64()))
        if i1 >= len(m1_c) - FWD_H * 60 - 5:
            continue
        e = m1_c[i1]
        allv = [row.get((det, tf), 0) for det in ["Trend", "WT", "Zone", "Div"]
                for tf in TFS]
        # согласие ПРОТИВ импульса: сколько клеток смотрят в сторону разворота
        against = sum(1 for x in allv if x == -side)
        along = sum(1 for x in allv if x == side)
        rec = dict(sym=sym, side=side, ended=ended, against=against,
                   along=along, msum=sum(allv) * -side, half=int(t >= n // 2),
                   fwd=(m1_c[i1 + FWD_H * 60] - e) / e * 100 * -side)
        # ЭТАП 3: первый CHoCH на LTF в сторону разворота, в пределах окна ожидания
        for ltf in LTF_TRIG:
            rec[f"trig{ltf}_h"] = np.nan
            rec[f"trig{ltf}_fwd"] = np.nan
            if ltf not in trig:
                continue
            lst = trig[ltf][1] if side == 1 else trig[ltf][0]   # разворот против импульса
            j = bisect.bisect_right(lst, t_now)
            if j >= len(lst):
                continue
            t_tr = lst[j]
            wait_h = (t_tr - t_now).total_seconds() / 3600
            if wait_h > TRIG_WAIT_H:
                continue
            i2 = int(np.searchsorted(m1_t, t_tr.to_datetime64()))
            if i2 >= len(m1_c) - FWD_H * 60 - 5:
                continue
            e2 = m1_c[i2]
            rec[f"trig{ltf}_h"] = wait_h
            rec[f"trig{ltf}_fwd"] = (m1_c[i2 + FWD_H * 60] - e2) / e2 * 100 * -side
        rows.append(rec)
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] якорей {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\impulse_end_class.pkl")
base = R.ended.mean()
print(f"\nякорей: {len(R):,} | базовая доля НАСТОЯЩИХ завершений: {base*100:.1f}%\n")

print("=== РАЗЛИЧАЕТ ЛИ МАТРИЦА: завершение или пауза ===")
print(f"{'согласие ПРОТИВ':>16} {'n':>8} {'доля завершений':>17} {'lift':>7} "
      f"{'форвард против':>15} {'нетто':>9}")
for a, b in [(0, 6), (6, 12), (12, 18), (18, 24), (24, 40)]:
    m = (R.against >= a) & (R.against < b)
    if m.sum() < 300:
        continue
    g = R[m]
    print(f"{f'{a}-{b}':>16} {m.sum():>8,} {g.ended.mean()*100:16.1f}% "
          f"{g.ended.mean()/base:7.2f} {g.fwd.mean():+14.3f}% "
          f"{g.fwd.mean()-COST:+8.3f}%")

print("\n=== ЗЕРКАЛЬНОСТЬ (согласие против ≥18) ===")
print(f"{'импульс':>10} {'n':>8} {'доля заверш.':>14} {'lift':>7} {'форвард':>10} "
      f"{'IS→OOS':>8} {'монет+':>8}")
for side, nm in [(1, "вверх"), (-1, "вниз")]:
    g = R[(R.against >= 18) & (R.side == side)]
    if len(g) < 150:
        continue
    b0 = R[R.side == side].ended.mean()
    i_, o_ = g[g.half == 0].fwd, g[g.half == 1].fwd
    tag = "✓" if len(i_) > 40 and len(o_) > 40 and i_.mean() * o_.mean() > 0 \
        and i_.mean() > 0 else "✗"
    per = g.groupby("sym").fwd.mean()
    print(f"{nm:>10} {len(g):>8,} {g.ended.mean()*100:13.1f}% "
          f"{g.ended.mean()/b0:7.2f} {g.fwd.mean():+9.3f}% {tag:>8} "
          f"{int((per>0).sum())}/{len(per)}")

print("\n=== ЕСЛИ РАЗЛИЧАЕТ: деньги по факту исхода ===")
for lab, sub in [("настоящее завершение", R[R.ended == 1]),
                 ("пауза (импульс продолжился)", R[R.ended == 0])]:
    print(f"  {lab:>30}: n={len(sub):>7,} · форвард против импульса "
          f"{sub.fwd.mean():+.3f}% · медиана {sub.fwd.median():+.3f}%")

print("\n=== ЭТАП 3: ВХОД НА LTF ПОСЛЕ ПОДТВЕРЖДЕНИЯ ===")
print("(вход по первому CHoCH на LTF в сторону разворота, ожидание ≤%.0f ч)" % TRIG_WAIT_H)
print(f"{'LTF':>5} {'фильтр':>18} {'сигналов':>9} {'дошло до входа':>15} "
      f"{'ждали, ч':>9} {'ход':>9} {'мед':>9} {'нетто':>9} {'IS→OOS':>8} {'монет+':>8}")
for ltf in LTF_TRIG:
    col_h, col_f = f"trig{ltf}_h", f"trig{ltf}_fwd"
    if col_f not in R.columns:
        continue
    for nm, sub in [("без фильтра", R),
                    ("согласие ≥12", R[R.against >= 12]),
                    ("согласие ≥18", R[R.against >= 18]),
                    ("согласие ≥18 + заверш.", R[(R.against >= 18) & (R.ended == 1)])]:
        g = sub[sub[col_f].notna()]
        if len(g) < 120:
            continue
        i_, o_ = g[g.half == 0][col_f], g[g.half == 1][col_f]
        tag = "✓" if len(i_) > 30 and len(o_) > 30 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.groupby("sym")[col_f].mean()
        print(f"{ltf:>4}m {nm:>18} {len(sub):>9,} {len(g)/max(len(sub),1)*100:14.1f}% "
              f"{g[col_h].median():8.2f} {g[col_f].mean():+8.3f}% "
              f"{g[col_f].median():+8.3f}% {g[col_f].mean()-COST:+8.3f}% {tag:>8} "
              f"{int((per>0).sum())}/{len(per)}")
    print()

print("=== СРАВНЕНИЕ: вход сразу против входа по триггеру LTF (согласие ≥18) ===")
S = R[R.against >= 18]
print(f"  вход сразу на 15m:      n={len(S):>6,} · ход {S.fwd.mean():+.3f}% · "
      f"мед {S.fwd.median():+.3f}%")
for ltf in LTF_TRIG:
    c = f"trig{ltf}_fwd"
    if c in S.columns:
        g = S[S[c].notna()]
        if len(g) > 100:
            print(f"  вход по CHoCH на {ltf}m:   n={len(g):>6,} · ход {g[c].mean():+.3f}% · "
                  f"мед {g[c].median():+.3f}%")
