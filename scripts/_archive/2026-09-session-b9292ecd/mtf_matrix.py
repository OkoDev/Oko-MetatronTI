# -*- coding: utf-8 -*-
"""MTF-МАТРИЦА ДЕТЕКТОРОВ × ТФ + ВОСХОДЯЩЕЕ РАСПРОСТРАНЕНИЕ (Егор, 09.09.2026).

Панель со скриншота: строки — детекторы, столбцы — ТФ (3m 5m 15m 45m 1H 4H D).

Две оси, которые Егор назвал:
  1. СОГЛАСИЕ: сколько клеток матрицы смотрят в одну сторону (+ к весу за OB/SC/FVG на LTF)
  2. ВОСХОДЯЩЕЕ РАСПРОСТРАНЕНИЕ: признак появился сначала на младшем ТФ, потом на старшем.
     Порядок снизу вверх = «++++». Это ДИНАМИКА, а не статика.

Якорь — завершение импульса на 15m (нога ≥K·ATR, экстремум больше не обновляется).

🔴 Каузально: каждая клетка по ЗАКРЫТОМУ бару своего ТФ.
🔴 Зеркальность проверяется сразу: long и short обязаны быть симметричны.
"""
import os, sys, glob, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure
from core.indicators.indicators import calculate_wt
from core.calculators.combinator_core import _wtx_divergences
from core.calculators.swing_bridge import etl_fvg, etl_order_blocks

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [1, 3, 5, 15, 45, 60, 240, 1440]      # 🔴 1m добавлен — лестница расширена вниз
TFN = ["1m", "3m", "5m", "15m", "45m", "1H", "4H", "D"]
SWING = 10
ANCHOR_TF = 15
K_ATR = 3.0
FWD = {"6ч": 6, "24ч": 24, "72ч": 72}
NSYM = 40
COST = 0.35
FRESH = 5          # признак считается «свежим» N баров своего ТФ
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | ТФ панели: {TFN}\n", flush=True)


def resample(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def spread_flag(flag_pos, flag_neg, idx, tf):
    """Момент последнего срабатывания признака (для порядка появления)."""
    t_pos = np.full(len(idx), np.datetime64("NaT"), dtype="datetime64[ns]")
    t_neg = t_pos.copy()
    last_p = last_n = np.datetime64("NaT")
    for i in range(len(idx)):
        if flag_pos[i]:
            last_p = idx[i]
        if flag_neg[i]:
            last_n = idx[i]
        t_pos[i] = last_p
        t_neg[i] = last_n
    return t_pos, t_neg


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    cell, appear = {}, {}
    for tf in TFS:
        d = resample(d1, tf)
        if len(d) < 200:
            continue
        idx = d.index.values
        ct = list(d.index + pd.Timedelta(minutes=tf))
        n = len(d)
        # TREND
        st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
        tr = np.zeros(n, np.int8); t_ = 0; p = 0
        ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
        choch_b = np.zeros(n, bool); choch_s = np.zeros(n, bool)
        for e in st.events:
            if e.kind == "CHoCH" and not e.internal:
                (choch_b if e.bull else choch_s)[e.i] = True
        for b in range(n):
            while p < len(ev) and ev[p].i <= b:
                t_ = 1 if ev[p].bull else -1; p += 1
            tr[b] = t_
        # WT + ZONE + DIV
        w = calculate_wt(d.reset_index(drop=True))
        wt1, wt2 = w["wt1"].values, w["wt2"].values
        wt = np.where(wt1 > wt2, 1, -1).astype(np.int8)
        zone = np.where(wt1 < -60, 1, np.where(wt1 > 60, -1, 0)).astype(np.int8)
        br, ber, _, _ = _wtx_divergences(wt1, d["low"].values, d["high"].values)
        dv = np.zeros(n, np.int8)
        for i in np.where(br)[0]:
            dv[i:min(i + FRESH, n)] = 1
        for i in np.where(ber)[0]:
            dv[i:min(i + FRESH, n)] = -1
        # OB / FVG (зоны)
        dd = d.reset_index(drop=True)
        try:
            fv = etl_fvg(dd); ob = etl_order_blocks(dd)
            fvg_b = np.asarray(fv["bull_fvg"], bool); fvg_s = np.asarray(fv["bear_fvg"], bool)
            ob_b = np.asarray(ob["bull_ob"], bool); ob_s = np.asarray(ob["bear_ob"], bool)
        except Exception:
            fvg_b = fvg_s = ob_b = ob_s = np.zeros(n, bool)
        zval = np.zeros(n, np.int8)
        for i in np.where(fvg_b | ob_b)[0]:
            zval[i:min(i + FRESH, n)] = 1
        for i in np.where(fvg_s | ob_s)[0]:
            zval[i:min(i + FRESH, n)] = -1
        cell[("Trend", tf)] = (ct, tr)
        cell[("WT", tf)] = (ct, wt)
        cell[("Zone", tf)] = (ct, zone)
        cell[("Div", tf)] = (ct, dv)
        cell[("OBFVG", tf)] = (ct, zval)
        # моменты появления — для порядка снизу вверх
        appear[("OBFVG", tf)] = (ct, *spread_flag(fvg_b | ob_b, fvg_s | ob_s, idx, tf))
        appear[("SC", tf)] = (ct, *spread_flag(choch_b, choch_s, idx, tf))
    if ("Trend", ANCHOR_TF) not in cell:
        continue
    da = resample(d1, ANCHOR_TF)
    hi, lo, cl = da["high"].values, da["low"].values, da["close"].values
    atr = ((da["high"] - da["low"]) / da["close"]).rolling(50, min_periods=20).mean().values
    n = len(da); M = 20
    anchors = []
    for t in range(M + 5, n - 5):
        if np.isnan(atr[t]) or atr[t] <= 0:
            continue
        s = t - M
        if (hi[s:t + 1].max() - lo[s]) / lo[s] >= K_ATR * atr[t] \
                and hi[t - 1:t + 1].max() < hi[s:t].max():
            anchors.append((t, 1))
        elif (hi[s] - lo[s:t + 1].min()) / hi[s] >= K_ATR * atr[t] \
                and lo[t - 1:t + 1].min() > lo[s:t].min():
            anchors.append((t, -1))
    ts_a = da.index.values
    m1_t, m1_c = d1.index.values, d1["close"].values
    for t, imp_side in anchors:
        t_now = pd.Timestamp(ts_a[t] + np.timedelta64(ANCHOR_TF, "m"))
        row = {}
        for (det, tf), (ct, vals) in cell.items():
            j = bisect.bisect_right(ct, t_now) - 1
            row[(det, tf)] = int(vals[j]) if 0 <= j < len(vals) else 0
        i1 = int(np.searchsorted(m1_t, t_now.to_datetime64()))
        if i1 >= len(m1_c) - max(FWD.values()) * 60 - 5:
            continue
        e = m1_c[i1]
        rec = dict(sym=sym, imp=imp_side, half=int(t >= n // 2))
        for det in ["Trend", "WT", "Zone", "Div", "OBFVG"]:
            v = [row.get((det, tf), 0) for tf in TFS]
            rec[f"{det}_sum"] = int(sum(v))
        allv = [row.get((det, tf), 0) for det in ["Trend", "WT", "Zone", "Div", "OBFVG"]
                for tf in TFS]
        rec["M_sum"] = int(sum(allv))
        # ВОСХОДЯЩЕЕ РАСПРОСТРАНЕНИЕ: порядок появления признака снизу вверх
        for det in ["OBFVG", "SC"]:
            for sgn, sname in [(1, "up"), (-1, "dn")]:
                times = []
                for tf in TFS:
                    key = (det, tf)
                    if key not in appear:
                        continue
                    ct, tp, tn = appear[key]
                    j = bisect.bisect_right(ct, t_now) - 1
                    if j < 0:
                        continue
                    tt = (tp if sgn == 1 else tn)[j]
                    if not np.isnat(tt):
                        times.append((tf, tt))
                if len(times) >= 3:
                    order = [tt for _, tt in times]
                    asc = sum(1 for a, b in zip(order[:-1], order[1:]) if a <= b)
                    rec[f"{det}_{sname}_n"] = len(times)
                    rec[f"{det}_{sname}_asc"] = asc / max(len(order) - 1, 1)
                else:
                    rec[f"{det}_{sname}_n"] = len(times)
                    rec[f"{det}_{sname}_asc"] = np.nan
        for hn, hh in FWD.items():
            k = i1 + hh * 60
            rec[f"f{hn}"] = (m1_c[k] - e) / e * 100 if k < len(m1_c) else np.nan
        rows.append(rec)
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] якорей {len(rows):,}", flush=True)

R = pd.DataFrame(rows)
R.to_pickle(D + r"\mtf_matrix.pkl")
print(f"\nякорей (завершений импульса): {len(R):,}\n")

print("=== 1. СОГЛАСИЕ ВСЕЙ МАТРИЦЫ (5 детекторов × 7 ТФ = 35 клеток) ===")
print(f"{'M_sum':>10} {'n':>8} {'доля':>7} " + " ".join(f"{h:>10}" for h in FWD))
for a, b in [(-40, -15), (-15, -8), (-8, -3), (-3, 3), (3, 8), (8, 15), (15, 40)]:
    m = (R.M_sum >= a) & (R.M_sum < b)
    if m.sum() < 200:
        continue
    print(f"{f'{a}..{b}':>10} {m.sum():>8,} {m.mean()*100:6.1f}% "
          + " ".join(f"{R[m][f'f{h}'].mean():+9.3f}%" for h in FWD))

print("\n=== 2. ЗЕРКАЛЬНОСТЬ СОГЛАСИЯ (горизонт 24ч) ===")
print(f"{'|M|≥':>6} {'сторона':>8} {'n':>8} {'ход':>10} {'мед':>9} {'нетто':>9} "
      f"{'IS→OOS':>8} {'монет+':>8}")
for thr in [8, 12, 16, 20]:
    for sgn, nm in [(1, "вверх"), (-1, "вниз")]:
        g = R[R.M_sum * sgn >= thr]
        if len(g) < 150:
            continue
        v = g["f24ч"] * sgn
        i_, o_ = v[g.half == 0], v[g.half == 1]
        tag = "✓" if len(i_) > 40 and len(o_) > 40 and i_.mean() * o_.mean() > 0 \
            and i_.mean() > 0 else "✗"
        per = g.assign(v=v).groupby("sym").v.mean()
        print(f"{thr:>6} {nm:>8} {len(g):>8,} {v.mean():+9.3f}% {v.median():+8.3f}% "
              f"{v.mean()-COST:+8.3f}% {tag:>8} {int((per>0).sum())}/{len(per)}")
    print()

print("=== 3. ВОСХОДЯЩЕЕ РАСПРОСТРАНЕНИЕ признака снизу вверх (24ч) ===")
print(f"{'признак':>8} {'сторона':>8} {'доля asc':>10} {'n':>8} {'ход':>10} {'мед':>9}")
for det in ["OBFVG", "SC"]:
    for sname, sgn in [("up", 1), ("dn", -1)]:
        col = f"{det}_{sname}_asc"
        if col not in R.columns:
            continue
        sub = R[R[col].notna()]
        if len(sub) < 300:
            continue
        for a, b in [(0.0, 0.34), (0.34, 0.67), (0.67, 1.01)]:
            m = (sub[col] >= a) & (sub[col] < b)
            if m.sum() < 150:
                continue
            v = sub[m]["f24ч"] * sgn
            print(f"{det:>8} {sname:>8} {f'{a:.2f}-{b:.2f}':>10} {m.sum():>8,} "
                  f"{v.mean():+9.3f}% {v.median():+8.3f}%")
    print()

print("=== 4. ПО ДЕТЕКТОРАМ ОТДЕЛЬНО (сумма по 7 ТФ, 24ч) ===")
print(f"{'детектор':>10} {'|сумма|≥':>9} {'сторона':>8} {'n':>8} {'ход':>10} {'мед':>9}")
for det in ["Trend", "WT", "Zone", "Div", "OBFVG"]:
    for thr in [4, 6]:
        for sgn, nm in [(1, "вверх"), (-1, "вниз")]:
            g = R[R[f"{det}_sum"] * sgn >= thr]
            if len(g) < 200:
                continue
            v = g["f24ч"] * sgn
            print(f"{det:>10} {thr:>9} {nm:>8} {len(g):>8,} {v.mean():+9.3f}% "
                  f"{v.median():+8.3f}%")
