# -*- coding: utf-8 -*-
"""
Multi-TF Pyramiding Test — ARCH-113 + Scale strategy.

Тест двух вещей:

1. FVG reach rates на всех ТФ (5m, 15m, 1h, 4h) как TP магниты.
   Вопрос: какой ТФ FVG лучший ближний TP? какой дальний?

2. Conditional probability пирамидинга:
   P(HTF_target reached | LTF_target reached first)
   Если >P(HTF alone) → LTF entry + HTF target = синергия.

Пирамидинг логика:
  - HTF магнит (4h FVG / PWH / R1_1W) = главная цель, держим долго
  - LTF (5m/15m FVG) = быстрая добавка в ту же сторону, TP = LTF FVG
  - Условие: LTF и HTF в одном направлении, LTF ближе к entry
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path("E:/MTF BOT/CURSOR/crypto_volume_bot/data/history")

PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "AAVEUSDT", "ARBUSDT", "ATOMUSDT", "INJUSDT", "NEARUSDT",
    "OPUSDT", "SUIUSDT", "TIAUSDT", "TRXUSDT", "UNIUSDT",
]

ATR_PERIOD = 14

# Горизонты для каждого ТФ FVG
LTF_HOURS = [2, 4, 8, 12, 24, 48]        # 5m/15m FVG — быстрые цели
HTF_HOURS = [24, 48, 72, 120, 168, 336]  # 1h/4h FVG — медленные цели


def atr_daily_pct(df1d, period=ATR_PERIOD):
    hi, lo, cl = df1d["high"].values, df1d["low"].values, df1d["close"].values
    prev_cl = np.roll(cl, 1); prev_cl[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - prev_cl), np.abs(lo - prev_cl)))
    return pd.Series(tr).ewm(span=period, adjust=False).mean().values / cl * 100


def find_bear_fvg_active(H, L, C, cur, lookback):
    """Активные Bear FVG выше C[cur]: list of (mid, age_bars)."""
    entry = C[cur]; out = []
    for i in range(max(2, cur - lookback), cur):
        if H[i] < L[i-2]:
            mid = (H[i] + L[i-2]) / 2
            if mid <= entry: continue
            if len(H) > i+1 and H[i+1:cur+1].max() >= H[i]: continue
            out.append((mid, cur - i))
    return out


def load_pair(symbol):
    p5  = BASE / "5m"  / f"{symbol}.parquet"
    p15 = BASE / "15m" / f"{symbol}.parquet"
    p1h = BASE / "1h"  / f"{symbol}.parquet"
    if not (p5.exists() and p15.exists() and p1h.exists()):
        return None
    df5m  = pd.read_parquet(p5)
    df15m = pd.read_parquet(p15)
    df1h  = pd.read_parquet(p1h)
    df1d  = df1h.resample("1D").agg(
        high=("high","max"), low=("low","min"),
        close=("close","last")).dropna()
    return df5m, df15m, df1h, df1d


def test_pair(symbol):
    data = load_pair(symbol)
    if data is None: return None, None
    df5m, df15m, df1h, df1d = data

    H5,  L5,  C5  = df5m["high"].values,  df5m["low"].values,  df5m["close"].values
    H15, L15, C15 = df15m["high"].values, df15m["low"].values, df15m["close"].values
    H1,  L1,  C1  = df1h["high"].values,  df1h["low"].values,  df1h["close"].values

    dates_5m  = df5m.index
    dates_15m = df15m.index
    dates_1h  = df1h.index
    dates_1d  = df1d.index

    atr_pct = atr_daily_pct(df1d)

    fvg_rows = []     # отдельные FVG по ТФ
    pyramid_rows = [] # пары LTF+HTF для conditional probability

    # Стартуем с бара где есть достаточно истории
    start_1h = 480 + 10  # 20 дней 1h данных

    for i_1h in range(start_1h, len(H1) - 340 - 5):
        today_ts = dates_1h[i_1h]
        i_d = np.searchsorted(dates_1d, today_ts.normalize()) - 1
        if i_d < 0 or i_d >= len(atr_pct): continue
        atr = atr_pct[i_d]
        if atr <= 0: continue

        entry = C1[i_1h]

        # Будущие highs для разных горизонтов
        def future_high(hours):
            end = min(i_1h + 1 + hours, len(H1))
            return H1[i_1h+1:end].max() if end > i_1h+1 else entry

        fh = {h: future_high(h) for h in HTF_HOURS}

        # ── 1h FVG (lookback 200 баров = ~8 дней) ──
        for mid, age in find_bear_fvg_active(H1, L1, C1, i_1h, 200):
            dist_pct = (mid - entry) / entry * 100
            dist_atr = dist_pct / atr
            if dist_pct <= 0 or dist_pct > 20: continue
            row = dict(tf="fvg_1h", dist_pct=dist_pct, dist_atr=dist_atr,
                       age_bars=age, entry=entry)
            for h in HTF_HOURS:
                row[f"reach_{h}h"] = int(fh[h] >= mid)
            fvg_rows.append(row)

        # ── 4h FVG (из 1h → каждые 4 бара) ──
        i_4h = i_1h // 4
        if i_4h > 10:
            H4 = H1[::4][:i_4h+1]
            L4 = L1[::4][:i_4h+1]
            C4 = C1[::4][:i_4h+1]
            for mid, age in find_bear_fvg_active(H4, L4, C4, len(C4)-1, 50):
                dist_pct = (mid - entry) / entry * 100
                dist_atr = dist_pct / atr
                if dist_pct <= 0 or dist_pct > 20: continue
                row = dict(tf="fvg_4h", dist_pct=dist_pct, dist_atr=dist_atr,
                           age_bars=age, entry=entry)
                for h in HTF_HOURS:
                    row[f"reach_{h}h"] = int(fh[h] >= mid)
                fvg_rows.append(row)

        # ── 15m FVG — из 15m данных ──
        i_15m = np.searchsorted(dates_15m, today_ts)
        if i_15m < 100 or i_15m >= len(H15) - 50: continue

        # Будущие highs на 15m для быстрых горизонтов
        def future_high_15m(hours):
            bars = hours * 4  # 4 бара 15m = 1h
            end = min(i_15m + 1 + bars, len(H15))
            return H15[i_15m+1:end].max() if end > i_15m+1 else entry

        fh_ltf = {h: future_high_15m(h) for h in LTF_HOURS}

        ltf_fvg_found = []
        for mid, age in find_bear_fvg_active(H15, L15, C15, i_15m, 96):
            dist_pct = (mid - entry) / entry * 100
            dist_atr = dist_pct / atr
            if dist_pct <= 0 or dist_pct > 10: continue
            row = dict(tf="fvg_15m", dist_pct=dist_pct, dist_atr=dist_atr,
                       age_bars=age, entry=entry)
            for h in LTF_HOURS:
                row[f"reach_{h}h"] = int(fh_ltf[h] >= mid)
            fvg_rows.append(row)
            ltf_fvg_found.append((mid, age, fh_ltf))

        # ── 5m FVG ──
        i_5m = np.searchsorted(dates_5m, today_ts)
        if i_5m < 300 or i_5m >= len(H5) - 300: continue

        def future_high_5m(hours):
            bars = hours * 12  # 12 баров 5m = 1h
            end = min(i_5m + 1 + bars, len(H5))
            return H5[i_5m+1:end].max() if end > i_5m+1 else entry

        fh_5m = {h: future_high_5m(h) for h in LTF_HOURS}

        ltf_5m_found = []
        for mid, age in find_bear_fvg_active(H5, L5, C5, i_5m, 288):
            dist_pct = (mid - entry) / entry * 100
            dist_atr = dist_pct / atr
            if dist_pct <= 0 or dist_pct > 5: continue
            row = dict(tf="fvg_5m", dist_pct=dist_pct, dist_atr=dist_atr,
                       age_bars=age, entry=entry)
            for h in LTF_HOURS:
                row[f"reach_{h}h"] = int(fh_5m[h] >= mid)
            fvg_rows.append(row)
            ltf_5m_found.append((mid, age, fh_5m))

        # ── Пирамидинг: LTF (15m FVG) + HTF (4h FVG) в одну сторону ──
        # Для каждой пары: LTF_mid < HTF_mid (оба выше entry)
        if i_4h > 10:
            htf_fvgs = find_bear_fvg_active(H4, L4, C4, len(C4)-1, 30)
            for ltf_mid, ltf_age, ltf_fh in ltf_fvg_found:
                ltf_dist = (ltf_mid - entry) / entry * 100
                for htf_mid, htf_age in htf_fvgs:
                    htf_dist = (htf_mid - entry) / entry * 100
                    if htf_mid <= ltf_mid: continue  # HTF должен быть дальше
                    if htf_dist > 15: continue
                    if ltf_dist > htf_dist * 0.8: continue  # LTF должен быть заметно ближе

                    ltf_reached_24h = ltf_fh[24] >= ltf_mid
                    htf_reached_168h = fh[168] >= htf_mid  # HTF через неделю
                    htf_reached_336h = fh[336] >= htf_mid  # HTF через 2 недели

                    pyramid_rows.append(dict(
                        ltf_dist=ltf_dist, htf_dist=htf_dist,
                        ltf_reached=int(ltf_reached_24h),
                        htf_reach_168h=int(htf_reached_168h),
                        htf_reach_336h=int(htf_reached_336h),
                        dist_ratio=htf_dist / ltf_dist if ltf_dist > 0 else 0,
                    ))

    return pd.DataFrame(fvg_rows) if fvg_rows else None, \
           pd.DataFrame(pyramid_rows) if pyramid_rows else None


# ─────────────────────────────────────────────────────────────────────
print("=" * 90)
print("MULTI-TF PYRAMIDING TEST — FVG 5m/15m/1h/4h + conditional probability")
print("=" * 90)

all_fvg, all_pyramid = [], []
for sym in PAIRS:
    fvg_df, pyr_df = test_pair(sym)
    if fvg_df is not None and len(fvg_df) > 0:
        all_fvg.append(fvg_df)
    if pyr_df is not None and len(pyr_df) > 0:
        all_pyramid.append(pyr_df)
    sys.stdout.write(f"  ✓ {sym}\n"); sys.stdout.flush()

fvg_all = pd.concat(all_fvg, ignore_index=True)
pyr_all = pd.concat(all_pyramid, ignore_index=True) if all_pyramid else pd.DataFrame()
print(f"\nFVG уровней: {len(fvg_all)}")
print(f"Pyramid пар: {len(pyr_all)}\n")


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 1: FVG reach по ТФ с правильными горизонтами
# ─────────────────────────────────────────────────────────────────────
print("=" * 90)
print("FVG REACH RATE по таймфреймам (правильный горизонт для каждого ТФ)")
print()

for tf, hours, label in [
    ("fvg_5m",  LTF_HOURS, "5m FVG  (быстрые цели, 2-48h)"),
    ("fvg_15m", LTF_HOURS, "15m FVG (средние цели, 2-48h)"),
    ("fvg_1h",  HTF_HOURS, "1h FVG  (медленные цели, 24-336h)"),
    ("fvg_4h",  HTF_HOURS, "4h FVG  (HTF цели, 24-336h)"),
]:
    sub = fvg_all[fvg_all["tf"] == tf]
    if len(sub) < 20: continue
    print(f"  {label}  (n={len(sub)}, avg_dist={sub['dist_pct'].mean():.2f}%)")
    print(f"    {'горизонт:':>12}", end="")
    for h in hours: print(f"  {h}h", end="")
    print()
    print(f"    {'все dist:':>12}", end="")
    for h in hours:
        col = f"reach_{h}h"
        if col in sub.columns:
            print(f"  {sub[col].mean()*100:>4.0f}%", end="")
        else:
            print(f"  {'?':>5}", end="")
    print()
    # По dist_atr
    for d_lo, d_hi, dlbl in [(0, 0.3, "<0.3R"), (0.3, 0.7, "0.3-0.7R"), (0.7, 1.5, "0.7-1.5R")]:
        band = sub[(sub["dist_atr"] >= d_lo) & (sub["dist_atr"] < d_hi)]
        if len(band) < 10: continue
        print(f"    {dlbl:>12}", end="")
        for h in hours:
            col = f"reach_{h}h"
            if col in band.columns:
                print(f"  {band[col].mean()*100:>4.0f}%", end="")
            else:
                print(f"  {'?':>5}", end="")
        print(f"  (n={len(band)})")
    print()


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 2: FVG decay по всем ТФ
# ─────────────────────────────────────────────────────────────────────
print("=" * 90)
print("FVG DECAY: как быстро стареют FVG (в % за первые 24h)")
print()

for tf, ref_h in [("fvg_5m", 24), ("fvg_15m", 24), ("fvg_1h", 48), ("fvg_4h", 72)]:
    sub = fvg_all[fvg_all["tf"] == tf].dropna(subset=["age_bars"])
    col = f"reach_{ref_h}h"
    if col not in sub.columns or len(sub) < 20: continue

    print(f"  {tf} (reach за {ref_h}h):")
    total = sub[col].mean() * 100
    print(f"    Все возрасты: {total:.1f}%")

    age_bins = [(0,3),(3,10),(10,25),(25,60),(60,200)]
    for lo, hi in age_bins:
        band = sub[(sub["age_bars"] >= lo) & (sub["age_bars"] < hi)]
        if len(band) < 10: continue
        r = band[col].mean() * 100
        avg_dist = band["dist_atr"].mean()
        bar = "█" * int(r/4)
        print(f"    age {lo:>3}-{hi:<3} bars: {r:>5.1f}%  dist={avg_dist:.2f}R  n={len(band)}  {bar}")
    print()


# ─────────────────────────────────────────────────────────────────────
# ТАБЛИЦА 3: ПИРАМИДИНГ — conditional probability
# ─────────────────────────────────────────────────────────────────────
if len(pyr_all) > 100:
    print("=" * 90)
    print("ПИРАМИДИНГ: P(HTF_target | LTF_target_reached)")
    print("LTF = 15m Bear FVG, HTF = 4h Bear FVG (оба выше entry, HTF дальше)")
    print()

    total = len(pyr_all)
    ltf_reached = pyr_all[pyr_all["ltf_reached"] == 1]
    ltf_missed  = pyr_all[pyr_all["ltf_reached"] == 0]

    print(f"  Всего LTF+HTF пар: {total}")
    print(f"  LTF (15m FVG) достигнут за 24h: {len(ltf_reached)} ({len(ltf_reached)/total*100:.1f}%)")
    print()

    for htf_col, label in [("htf_reach_168h","HTF за 7 дней"), ("htf_reach_336h","HTF за 14 дней")]:
        htf_all  = pyr_all[htf_col].mean() * 100
        htf_cond = ltf_reached[htf_col].mean() * 100 if len(ltf_reached) > 10 else 0
        htf_miss = ltf_missed[htf_col].mean() * 100 if len(ltf_missed) > 10 else 0

        print(f"  {label}:")
        print(f"    P(HTF) безусловно:                  {htf_all:>5.1f}%")
        print(f"    P(HTF | LTF достигнут за 24h):      {htf_cond:>5.1f}%  ← синергия пирамидинга")
        print(f"    P(HTF | LTF НЕ достигнут за 24h):   {htf_miss:>5.1f}%")
        lift = htf_cond - htf_all
        print(f"    Lift (условный - безусловный):       {lift:>+5.1f}%")
        print()

    # По дистанции HTF
    print("  P(HTF_336h) по дистанции от LTF до HTF (dist_ratio = htf/ltf):")
    for lo, hi, lbl in [(1.5,2.5,"1.5-2.5x"), (2.5,4.0,"2.5-4x"), (4.0,99,"4x+")]:
        sub = pyr_all[(pyr_all["dist_ratio"] >= lo) & (pyr_all["dist_ratio"] < hi)]
        if len(sub) < 10: continue
        htf_all_sub = sub["htf_reach_336h"].mean() * 100
        ltf_r = sub[sub["ltf_reached"]==1]
        htf_cond_sub = ltf_r["htf_reach_336h"].mean() * 100 if len(ltf_r) > 10 else 0
        print(f"    ratio {lbl}: P(HTF)={htf_all_sub:.1f}%, P(HTF|LTF)={htf_cond_sub:.1f}%  n={len(sub)}")

else:
    print(f"  Pyramid пар недостаточно ({len(pyr_all)}), пропускаем анализ")


print()
print("=" * 90)
print("ИТОГ: стратегия пирамидинга работает если P(HTF|LTF) > P(HTF) на >10%")
print("FVG иерархия: 5m (мин.цель) → 15m → 1h → 4h (максимальная цель)")
print("Decay: чем свежее FVG, тем выше его вес в gravity scoring")
