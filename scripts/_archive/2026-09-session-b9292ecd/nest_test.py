# -*- coding: utf-8 -*-
"""ТЕСТ ВЛОЖЕННОСТИ: воспроизводит ли слой internal(5) старшего ТФ слой swing(50) младшего?
Если гиперкуб ТФ реален, ломаные обязаны совпадать. Совпадение = один и тот же экстремум:
та же сторона (top/btm), то же время (±допуск), та же цена.
Считаем БЕЗ подгонки: перебираем все пары ТФ и обе комбинации len."""
import os, sys, sqlite3
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import _swings

DB = "ohlcv_cache.db"
TFMIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
T0, T1 = "2025-01-01", "2026-05-31"


def load(cn, sym, tf):
    q = ("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
         "AND time>=? AND time<? ORDER BY time")
    a = int(pd.Timestamp(T0, tz="UTC").timestamp() * 1000)
    b = int(pd.Timestamp(T1, tz="UTC").timestamp() * 1000)
    d = pd.read_sql(q, cn, params=(sym, tf, a, b))
    if len(d) < 500:
        return None
    d.index = pd.to_datetime(d["time"], unit="ms", utc=True)
    return d


def swings_ts(d, length):
    """-> DataFrame(ts, price, is_top) по подтверждённым свингам."""
    out = _swings(d["high"], d["low"], length)
    if not out:
        return pd.DataFrame(columns=["ts", "price", "is_top"])
    return pd.DataFrame({"ts": [d.index[sw_i] for _, sw_i, _, _ in out],
                         "price": [p for _, _, p, _ in out],
                         "is_top": [t for _, _, _, t in out]})


def match(a, b, tol_min, tol_pct):
    """Доля свингов a, которым нашёлся свинг b той же стороны в допуске по времени и цене."""
    if len(a) == 0 or len(b) == 0:
        return 0.0, 0
    hit = 0
    tol = pd.Timedelta(minutes=tol_min)
    for _, r in a.iterrows():
        c = b[b["is_top"] == r["is_top"]]
        c = c[(c["ts"] >= r["ts"] - tol) & (c["ts"] <= r["ts"] + tol)]
        if len(c) and (abs(c["price"] - r["price"]) / r["price"] <= tol_pct).any():
            hit += 1
    return hit / len(a), len(a)


cn = sqlite3.connect(DB)
syms = [r[0] for r in cn.execute(
    "SELECT symbol FROM ohlcv_cache WHERE timeframe='5m' AND symbol NOT LIKE 'binance:%' "
    "GROUP BY symbol HAVING COUNT(*)>60000 ORDER BY COUNT(*) DESC LIMIT 20")]
print("монет:", len(syms), "| окно", T0, "→", T1)

PAIRS = [("1h", "5m"), ("1h", "15m"), ("4h", "15m"), ("4h", "1h"), ("15m", "5m")]
res = {}
for hi, lo in PAIRS:
    for lhi, llo, tag in [(5, 50, "int(5)↑ vs swing(50)↓"), (50, 50, "swing↑ vs swing↓"),
                          (5, 5, "int↑ vs int↓")]:
        rates, ns = [], 0
        for s in syms:
            dhi, dlo = load(cn, s, hi), load(cn, s, lo)
            if dhi is None or dlo is None:
                continue
            a = swings_ts(dhi, lhi)
            b = swings_ts(dlo, llo)
            tol = TFMIN[hi] * 1.5          # допуск по времени = 1.5 бара старшего ТФ
            r, n = match(a, b, tol, 0.0015)
            if n >= 20:
                rates.append(r); ns += n
        if rates:
            res[(hi, lo, tag)] = (np.mean(rates), ns, len(rates))

print(f"\n{'старший':>6} {'младший':>7}  {'слои':<26} {'совпало':>8} {'свингов':>9}")
print("-" * 62)
for (hi, lo, tag), (r, n, k) in res.items():
    print(f"{hi:>6} {lo:>7}  {tag:<26} {r*100:7.1f}% {n:9,}")

# окна в минутах — теоретическое предсказание
print("\nокна детектора, мин:")
for tf in ["5m", "15m", "1h", "4h"]:
    print(f"  {tf:>3}: internal(5)={TFMIN[tf]*5:>5}  swing(50)={TFMIN[tf]*50:>6}")
