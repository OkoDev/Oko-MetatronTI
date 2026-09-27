# -*- coding: utf-8 -*-
"""СЕТКА ВЛОЖЕННОСТИ: где ещё смыкаются масштабы, включая НЕСТАНДАРТНЫЕ ТФ.

Гипотеза H1 (окно): совпадение слоёв = f(R), R = окно_старшего/окно_младшего,
                    окно = len × ТФ_мин. Максимум при R=1, ОТ ОТНОШЕНИЯ ТФ НЕ ЗАВИСИТ.
Гипотеза H0 (ТФ):  совпадение = f(ТФ_hi/ТФ_lo), окна ни при чём.
Разделяются парами, где R≈1 достигнут при разном отношении ТФ (4× … 16×).

🔴 КОНТРОЛЬ обязателен: свинги младшего ТФ плотные, случайное попадание в допуск
неизбежно. Контроль = те же свинги, сдвинутые на случайный лаг >> допуска.
"""
import os, sys, sqlite3, itertools, pickle
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings

DB = "ohlcv_cache.db"
T0, T1 = "2025-01-01", "2026-05-31"
# нестандартные включены намеренно: 10/20/45/90/180/360/720
TFS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 720]
LENS = [3, 5, 8, 13, 21, 34, 55]          # фибо-ряд
RMIN, RMAX = 0.25, 4.0                     # какие пары вообще считать
OUT = r"C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad\grid_nest.pkl"


def load5m(cn, sym):
    a = int(pd.Timestamp(T0, tz="UTC").timestamp() * 1000)
    b = int(pd.Timestamp(T1, tz="UTC").timestamp() * 1000)
    d = pd.read_sql("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='5m' AND time>=? AND time<? ORDER BY time",
                    cn, params=(sym, a, b))
    if len(d) < 40000:
        return None
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d[["open", "high", "low", "close"]]


def resample(d5, tf):
    if tf == 5:
        return d5
    r = d5.resample(f"{tf}min", label="left", closed="left")
    o = pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                      "low": r["low"].min(), "close": r["close"].last()}).dropna()
    return o


def swings_of(d, length):
    out = _swings(d["high"], d["low"], length)
    if len(out) < 10:
        return None
    return pd.DataFrame({
        "ts": [d.index[i] for _, i, _, _ in out],
        "px": [p for _, _, p, _ in out],
        "top": [t for _, _, _, t in out]}).sort_values("ts").reset_index(drop=True)


def match_rate(a, b, tol_min, tol_pct, shift_min=0.0):
    """Доля свингов a, нашедших свинг b той же стороны в допуске (время И цена)."""
    if a is None or b is None or len(a) == 0 or len(b) == 0:
        return np.nan
    tol = pd.Timedelta(minutes=tol_min)
    hit = 0
    for is_top in (True, False):
        aa = a[a["top"] == is_top]
        bb = b[b["top"] == is_top]
        if len(aa) == 0 or len(bb) == 0:
            continue
        bts = bb["ts"].values
        if shift_min:
            bts = bts + np.timedelta64(int(shift_min * 60), "s")
        bpx = bb["px"].values
        lo = np.searchsorted(bts, (aa["ts"] - tol).values, "left")
        hi = np.searchsorted(bts, (aa["ts"] + tol).values, "right")
        apx = aa["px"].values
        for k in range(len(aa)):
            if hi[k] > lo[k]:
                seg = bpx[lo[k]:hi[k]]
                if np.min(np.abs(seg - apx[k])) / apx[k] <= tol_pct:
                    hit += 1
    return hit / len(a)


cn = sqlite3.connect(DB)
syms = [r[0] for r in cn.execute(
    "SELECT symbol FROM ohlcv_cache WHERE timeframe='5m' AND symbol NOT LIKE 'binance:%' "
    "GROUP BY symbol HAVING COUNT(*)>100000 ORDER BY COUNT(*) DESC LIMIT 12")]
print(f"монет: {len(syms)} | ТФ: {TFS} | len: {LENS}", flush=True)

rows = []
for si, sym in enumerate(syms, 1):
    d5 = load5m(cn, sym)
    if d5 is None:
        continue
    layers = {}
    for tf in TFS:
        d = resample(d5, tf)
        if len(d) < 300:
            continue
        for L in LENS:
            s = swings_of(d, L)
            if s is not None:
                layers[(tf, L)] = s
    keys = sorted(layers)
    for (tfh, Lh), (tfl, Ll) in itertools.product(keys, keys):
        if tfh <= tfl:
            continue
        Wh, Wl = tfh * Lh, tfl * Ll
        R = Wh / Wl
        if not (RMIN <= R <= RMAX):
            continue
        tol = tfh * 1.5                    # допуск = 1.5 бара старшего ТФ
        real = match_rate(layers[(tfh, Lh)], layers[(tfl, Ll)], tol, 0.0015)
        ctl = match_rate(layers[(tfh, Lh)], layers[(tfl, Ll)], tol, 0.0015,
                         shift_min=tfh * 37.0)     # сдвиг >> допуска
        rows.append(dict(sym=sym, tfh=tfh, Lh=Lh, tfl=tfl, Ll=Ll, Wh=Wh, Wl=Wl,
                         R=R, tfr=tfh / tfl, n=len(layers[(tfh, Lh)]),
                         real=real, ctl=ctl))
    print(f"[{si}/{len(syms)}] {sym}: слоёв {len(layers)}, пар всего {len(rows)}", flush=True)

df = pd.DataFrame(rows)
df.to_pickle(OUT)
print("\nсохранено:", OUT, "| строк:", len(df), flush=True)
