# -*- coding: utf-8 -*-
"""ЭТАЛОН ЕГОРА В ГИПЕРКУБЕ: HYPE, разворот 02.08.2026 (минимум 51.539).

Полный срез по всей лестнице ТФ от 1m до 4h: что каждый слой знал В МОМЕНТ разворота,
когда именно он развернулся, и что было после.

Всё каузально: состояние слоя берётся по времени ЗАКРЫТИЯ его бара.
"""
import os, sys, bisect
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure
from core.calculators.combinator_core import _wtx_divergences
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TFS = [1, 3, 5, 15, 30, 60, 240]
SWING = 10
d1 = pd.read_parquet(r"C:\oko_history\1m\HYPEUSDT.parquet")
print(f"HYPE 1m: {len(d1):,} баров, {d1.index[0]} → {d1.index[-1]}")

# точный минимум разворота (окно 01-03 августа)
w = d1.loc["2026-08-01":"2026-08-03"]
t_low = w["low"].idxmin(); p_low = w["low"].min()
print(f"\n🎯 ЭТАЛОН: минимум {p_low:.3f} в {t_low} UTC   (Егор: 51.539)\n")


def resample(tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


rows = []
for tf in TFS:
    d = resample(tf)
    if len(d) < 100:
        continue
    st = run_structure(d.reset_index(drop=True), swing_len=SWING, internal_len=3)
    n = len(d)
    tr = np.zeros(n, np.int8); t_ = 0; p = 0
    ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
    flips = []
    for b in range(n):
        while p < len(ev) and ev[p].i <= b:
            nt = 1 if ev[p].bull else -1
            if nt != t_:
                flips.append((b, nt, ev[p].kind))
            t_ = nt; p += 1
        tr[b] = t_
    close_t = d.index + pd.Timedelta(minutes=tf)
    # состояние на момент минимума (по ЗАКРЫТОМУ бару)
    k = bisect.bisect_right(list(close_t), t_low) - 1
    # первый разворот ВВЕРХ после минимума
    up = [(b, kd) for b, s_, kd in flips if s_ == 1 and b >= k]
    first_up = up[0] if up else None
    # WT и дивергенция
    wd = calculate_wt(d.reset_index(drop=True))
    br, ber, bh, beh = _wtx_divergences(wd["wt1"].values, d["low"].values, d["high"].values)
    div_before = [i for i in np.where(br)[0] if i <= k]
    last_div = div_before[-1] if div_before else None
    lo10 = d["low"].values[max(0, k - SWING):k + 1].min()
    hi10 = d["high"].values[max(0, k - SWING):k + 1].max()
    pos = (d["close"].values[k] - lo10) / (hi10 - lo10) if hi10 > lo10 else np.nan
    rows.append(dict(
        tf=tf, win=tf * SWING, bar=k, bar_time=d.index[k],
        trend="▲" if tr[k] == 1 else ("▼" if tr[k] == -1 else "·"),
        wt=wd["wt1"].values[k], pos=pos,
        flip_bar=first_up[0] if first_up else None,
        flip_kind=first_up[1] if first_up else None,
        flip_time=d.index[first_up[0]] if first_up else None,
        flip_delay_h=((d.index[first_up[0]] - t_low).total_seconds() / 3600)
        if first_up else np.nan,
        div_time=d.index[last_div] if last_div is not None else None,
        div_age_h=((t_low - d.index[last_div]).total_seconds() / 3600)
        if last_div is not None else np.nan))

R = pd.DataFrame(rows)
print("=== СОСТОЯНИЕ КАЖДОГО СЛОЯ В МОМЕНТ МИНИМУМА (каузально) ===")
print(f"{'ТФ':>5} {'окно':>6} {'тренд':>6} {'WT':>8} {'позиция':>8} "
      f"{'посл. бычья див.':>18} {'давность':>9}")
for _, r in R.iterrows():
    dv = r.div_time.strftime("%d.%m %H:%M") if r.div_time is not None else "—"
    ag = f"{r.div_age_h:.1f} ч" if r.div_age_h == r.div_age_h else "—"
    print(f"{r.tf:>4}m {r.win:>6} {r.trend:>6} {r.wt:+8.1f} {r.pos:8.2f} "
          f"{dv:>18} {ag:>9}")

print("\n=== КОГДА КАЖДЫЙ СЛОЙ РАЗВЕРНУЛСЯ ВВЕРХ (после минимума) ===")
print(f"{'ТФ':>5} {'окно':>6} {'тип':>7} {'время':>16} {'задержка':>10} "
      f"{'цена тогда':>11} {'от дна':>8}")
for _, r in R.iterrows():
    if r.flip_time is None:
        print(f"{r.tf:>4}m {r.win:>6} {'—':>7} {'не развернулся':>16}")
        continue
    d_ = resample(r.tf)
    pr = d_["close"].values[r.flip_bar]
    print(f"{r.tf:>4}m {r.win:>6} {r.flip_kind:>7} "
          f"{r.flip_time.strftime('%d.%m %H:%M'):>16} {r.flip_delay_h:9.1f}ч "
          f"{pr:11.3f} {(pr - p_low)/p_low*100:+7.2f}%")

print("\n=== ЧТО БЫЛО ПОСЛЕ (факт) ===")
fut = d1.loc[t_low:]
for h in [6, 12, 24, 48, 96, 168, 336]:
    seg = fut.iloc[:h * 60]
    if len(seg) < h * 30:
        continue
    print(f"  +{h:>4} ч: цена {seg['close'].iloc[-1]:8.3f} "
          f"({(seg['close'].iloc[-1]-p_low)/p_low*100:+6.2f}%) | "
          f"максимум {seg['high'].max():8.3f} ({(seg['high'].max()-p_low)/p_low*100:+6.2f}%) | "
          f"минимум {seg['low'].min():8.3f} ({(seg['low'].min()-p_low)/p_low*100:+6.2f}%)")
R.to_pickle(D + r"\hype_slice.pkl")
