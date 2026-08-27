# -*- coding: utf-8 -*-
"""КОНТРОЛЬ ДЛЯ КЛЕТКИ «три гейта + стоп ≤3.2%» (20.08.2026).

Клетка пережила перекрёстный OOS (OOS-монеты × OOS-время: n=272, PF 1.88, безтоп10% ≈ 0),
но это ~20-я нарезка датасета за сессию. Закон Егора: без строки «контроль» замер не
проведён ([[law_control_group_random_entry]]) — «в любом месте со стопом 15% WR будет 50%».

Контроль = та же монета, тот же % стопа и цели, тот же горизонт, СЛУЧАЙНЫЙ бар входа.
Считается для КАЖДОЙ сделки клетки, поэтому сравнение идёт на одинаковой геометрии.
"""
import hashlib
import random
import sqlite3
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from core.smc.impulse_fib import (ENTRY_FIB, HOLD_BARS, STOP_ATR_K,  # noqa: E402
                                  TARGET_FIB, WAIT_BARS, _atr, find_impulses, is_junk)

DB, COST, PEN, RISK = "ohlcv_cache.db", 0.35, 0.15, 2.0
MAX_STOP = 3.234      # верхняя граница клетки (плато 2.5-3.5 проверено)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 250
N_CTRL = 3            # контрольных входов на каждую сделку — снижает дисперсию контроля


def load(sym):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe='1h' ORDER BY time", c, params=(sym,))
    c.close()
    if len(d) < 1500:
        return None
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def run(sym):
    df = load(sym)
    if df is None:
        return []
    dd = df.reset_index(drop=True)
    H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
    n = len(dd)
    aa = _atr(dd)
    atr = aa.values
    regime = (aa / aa.rolling(100).mean()).values
    ema200 = dd.close.ewm(span=200, adjust=False).mean().values
    volma = pd.Series(V).rolling(120).mean().values
    oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
    rnd = random.Random(hashlib.md5(sym.encode()).hexdigest()[:8])

    def outcome(e, s_, t_, j0, up):
        end = min(j0 + HOLD_BARS, n - 1)
        fh, flw = H[j0 + 1:end + 1], L[j0 + 1:end + 1]
        if len(fh) == 0:
            return None
        if up:
            jt = next((k for k in range(len(fh)) if fh[k] >= t_), 10 ** 9)
            js = next((k for k in range(len(flw)) if flw[k] <= s_), 10 ** 9)
        else:
            jt = next((k for k in range(len(flw)) if flw[k] <= t_), 10 ** 9)
            js = next((k for k in range(len(fh)) if fh[k] >= s_), 10 ** 9)
        if js <= jt and js < 10 ** 9:
            r = ((s_ - e) if up else (e - s_)) / e * 100
        elif jt < 10 ** 9:
            r = ((t_ - e) if up else (e - t_)) / e * 100
        else:
            o2 = float(C[end])
            r = ((o2 - e) if up else (e - o2)) / e * 100
        return r - COST

    out = []
    for a, b, up in find_impulses(H, L, C, atr, n):
        if b < 250 or b >= n - HOLD_BARS - WAIT_BARS - 2:
            continue
        x_ = float(C[b])
        amp = abs(x_ - float(C[a]))
        if amp <= 0:
            continue
        sign = -1.0 if up else 1.0
        entry = x_ + sign * ENTRY_FIB * amp
        tp = x_ + sign * TARGET_FIB * amp
        sl = entry - STOP_ATR_K * atr[b] if up else entry + STOP_ATR_K * atr[b]
        if (up and sl >= entry) or (not up and sl <= entry):
            continue
        sp = abs(entry - sl) / entry * 100
        if sp <= 0 or sp > MAX_STOP:          # ← клетка: только малый стоп
            continue
        # три гейта
        vr = float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0
        rg = float(regime[b]) if not np.isnan(regime[b]) else 1.0
        if not (1.0 <= vr < 1.5 and (C[b] > ema200[b]) == up and rg >= 1.1):
            continue
        deep = entry * (1 - PEN / 100) if up else entry * (1 + PEN / 100)
        w = range(b + 1, min(b + 1 + WAIT_BARS, n))
        if up:
            jf = next((q for q in w if L[q] <= entry), None)
            jd = next((q for q in w if L[q] <= deep), None)
        else:
            jf = next((q for q in w if H[q] >= entry), None)
            jd = next((q for q in w if H[q] >= deep), None)
        if jf is None or jd is None:
            continue
        r = outcome(entry, sl, tp, jf, up)
        if r is None:
            continue
        tgt_pct = abs(tp - entry) / entry
        ctrl = []
        for _ in range(N_CTRL):
            jc = rnd.randrange(300, n - HOLD_BARS - 2)
            ec = float(C[jc])
            sc_ = ec * (1 - sp / 100) if up else ec * (1 + sp / 100)
            tc = ec * (1 + tgt_pct) if up else ec * (1 - tgt_pct)
            v = outcome(ec, sc_, tc, jc, up)
            if v is not None:
                ctrl.append(v)
        out.append({"sym": sym, "oos": oos, "year": df.index[b].year,
                    "side": "long" if up else "short", "sp": sp, "pnl": r,
                    "ctrl": float(np.mean(ctrl)) if ctrl else np.nan,
                    "liq": float(np.nanmedian(V[max(0, b - 500):b] * C[max(0, b - 500):b]))})
    return out


def rep(v, name, col="pnl", span=4.6):
    p = v[col].dropna().values
    if len(p) < 25:
        return f"  {name:<40} n={len(p):<5} — мало"
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    cov = (v.groupby("sym")[col].sum() > 0).mean() * 100
    freq = len(p) / max(v.sym.nunique(), 1) / (span * 12) * 250
    depo = p.mean() / v.sp.median() * RISK
    return (f"  {name:<40} n={len(p):<5} WR {len(w) / len(p) * 100:5.1f}%  "
            f"PF {(w.sum() / gl if gl else 0):5.2f}  ср {p.mean():+6.2f}%  "
            f"безтоп10% {s[int(len(s) * 0.1):].sum():+7.0f}  {freq:5.1f} сд/мес  "
            f"{depo * freq:+6.2f}% депо/мес  охват {cov:3.0f}%")


c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
                 "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()
c.close()
_all = [s for s, _ in rows if not is_junk(s)]
random.Random(19).shuffle(_all)
syms = _all[:N]

R = []
for i, sym in enumerate(syms, 1):
    R += run(sym)
    if i % 40 == 0:
        print(f"  ... {i}/{len(syms)} · {len(R)}", flush=True)

D = pd.DataFrame(R)
D.to_pickle("scratch_cell_control.pkl")
print("\n" + "=" * 136)
print(f"КЛЕТКА «три гейта + стоп ≤{MAX_STOP}%» ПРОТИВ КОНТРОЛЯ · {D.sym.nunique()} монет · {len(D)} сделок")
print("=" * 136)
for nm, sub in (("вся выборка", D), ("OOS × OOS", D[D.oos & (D.year >= 2025)]),
                ("OOS-время 2025-26", D[D.year >= 2025]), ("2026", D[D.year == 2026])):
    print(rep(sub, f"{nm} · МЕХАНИКА"))
    print(rep(sub, f"{nm} · контроль", col="ctrl"))
print("\nпо годам (механика / контроль):")
for y in sorted(D.year.unique()):
    print(rep(D[D.year == y], f"{y} механика"))
    print(rep(D[D.year == y], f"{y} контроль", col="ctrl"))
print("\nпо сторонам и ликвидности (механика / контроль):")
med = D.liq.median()
for nm, sub in (("long", D[D.side == "long"]), ("short", D[D.side == "short"]),
                ("ликвидная половина", D[D.liq >= med]), ("неликвидная", D[D.liq < med])):
    print(rep(sub, f"{nm} механика"))
    print(rep(sub, f"{nm} контроль", col="ctrl"))
