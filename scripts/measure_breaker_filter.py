# -*- coding: utf-8 -*-
"""BREAKER КАК ФИЛЬТР импульсной механики — перемер на БОЕВОМ детекторе (20.08.2026).

В замере конфлюэнции 19.08 breaker был лучшим ОДИНОЧНЫМ фактором по OOS (1.80), но
считался УПРОЩЁННО (последняя противоположная свеча, пробитая импульсом), потому что
детектора в проекте не было — `OrderBlock.is_breaker` объявлен, но никогда не
выставлялся. 20.08 детектор реализован (`is_breaker=(mit != -1)` + `active_breakers`).

Здесь механика меряется с НАСТОЯЩИМ breaker'ом. Отдельно считается контроль: та же
геометрия со случайным баром входа — иначе не отличить фильтр от общего дрейфа
([[law_control_group_random_entry]]).
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
from core.smc.smc_engine import (active_breakers, breaker_side,  # noqa: E402
                                 detect_order_blocks, detect_structure_breaks)

DB, COST, PEN, RISK = "ohlcv_cache.db", 0.35, 0.15, 2.0
NEAR_ATR = 0.4        # окно схождения зоны входа и breaker'а, в ATR (как в замере зон)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200


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

    try:
        obs = detect_order_blocks(dd, detect_structure_breaks(dd, length=5))
    except Exception:                                          # noqa: BLE001
        return []
    brk = sorted([o for o in obs if o.mitigated_idx != -1], key=lambda o: o.mitigated_idx)
    b_mit = np.array([o.mitigated_idx for o in brk], dtype=int) if brk else np.zeros(0, int)

    def near_breaker(bar: int, price: float, want: str, tol: float) -> int:
        """Сколько breaker'ов нужной стороны накрывают цену, будучи пробитыми до bar."""
        if not brk:
            return 0
        k = int(np.searchsorted(b_mit, bar, side="right"))
        cnt = 0
        for o in brk[max(0, k - 40):k]:
            if breaker_side(o) != want:
                continue
            lo, hi = min(o.top, o.bottom) - tol, max(o.top, o.bottom) + tol
            if lo <= price <= hi:
                cnt += 1
        return cnt

    out = []
    rnd = random.Random(hash(sym) & 0xFFFF)
    for a, b, up in find_impulses(H, L, C, atr, n):
        if b < 250 or b >= n - HOLD_BARS - WAIT_BARS - 2:
            continue
        side = "long" if up else "short"
        o_, x_ = float(C[a]), float(C[b])
        amp = abs(x_ - o_)
        if amp <= 0:
            continue
        sign = -1.0 if up else 1.0
        entry = x_ + sign * ENTRY_FIB * amp
        tp = x_ + sign * TARGET_FIB * amp
        sl = entry - STOP_ATR_K * atr[b] if up else entry + STOP_ATR_K * atr[b]
        if (up and sl >= entry) or (not up and sl <= entry):
            continue
        sp = abs(entry - sl) / entry * 100
        if sp <= 0 or sp > 30:
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

        # breaker нужной стороны в зоне входа; для long поддержку даёт bull-breaker
        want = "bull" if up else "bear"
        nb = near_breaker(b, entry, want, NEAR_ATR * atr[b])
        nb_any = near_breaker(b, entry, want, NEAR_ATR * atr[b]) + \
            near_breaker(b, entry, "bear" if up else "bull", NEAR_ATR * atr[b])

        def outcome(e, s_, t_, j0):
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

        r = outcome(entry, sl, tp, jf)
        if r is None:
            continue
        # КОНТРОЛЬ: та же геометрия (% стопа, % цели, горизонт), случайный бар входа
        jc = rnd.randrange(300, n - HOLD_BARS - 2)
        ec = float(C[jc])
        sc_ = ec * (1 - sp / 100) if up else ec * (1 + sp / 100)
        tc = ec * (1 + abs(tp - entry) / entry) if up else ec * (1 - abs(tp - entry) / entry)
        rc = outcome(ec, sc_, tc, jc)

        out.append({"sym": sym, "oos": oos, "year": df.index[b].year, "side": side,
                    "sp": sp, "pnl": r, "ctrl": rc, "nb": nb, "nb_any": nb_any,
                    "vratio": float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0,
                    "regime": float(regime[b]) if not np.isnan(regime[b]) else 1.0,
                    "with_trend": (C[b] > ema200[b]) == up,
                    "liq": float(np.nanmedian(V[max(0, b - 500):b] * C[max(0, b - 500):b]))})
    return out


def rep(v, name, col="pnl", span_years=4.6):
    if len(v) < 25:
        return f"  {name:<42} n={len(v):<5} — мало"
    p = v[col].dropna().values
    if len(p) < 25:
        return f"  {name:<42} n={len(p):<5} — мало"
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    cov = (v.groupby("sym")[col].sum() > 0).mean() * 100
    freq = len(p) / max(v.sym.nunique(), 1) / (span_years * 12) * 250
    depo = p.mean() / v.sp.median() * RISK
    return (f"  {name:<42} n={len(p):<5} WR {len(w) / len(p) * 100:5.1f}%  "
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
    if i % 25 == 0:
        print(f"  ... {i}/{len(syms)} · {len(R)}", flush=True)

D = pd.DataFrame(R)
D.to_pickle("scratch_breaker.pkl")
D["g3"] = (D.vratio >= 1.0) & (D.vratio < 1.5) & D.with_trend & (D.regime >= 1.1)

print("\n" + "=" * 136)
print(f"BREAKER КАК ФИЛЬТР · {D.sym.nunique()} монет · {len(D)} входов · окно ±{NEAR_ATR} ATR")
print("=" * 136)
print(rep(D, "БАЗА (вся выборка)"))
print(rep(D, "  КОНТРОЛЬ случайный вход", col="ctrl"))
print(rep(D[D.nb == 0], "breaker своей стороны НЕТ"))
print(rep(D[D.nb >= 1], "breaker своей стороны ЕСТЬ"))
print(rep(D[D.nb >= 2], "  breaker ≥2"))
print(rep(D[D.nb_any == 0], "любого breaker'а нет"))
print(rep(D[D.nb_any >= 1], "любой breaker в зоне"))

print("\nС ТРЕМЯ ГЕЙТАМИ:")
G = D[D.g3]
print(rep(G, "гейты (без breaker)"))
print(rep(G[G.nb >= 1], "гейты + breaker"))
print(rep(G[G.nb == 0], "гейты, breaker'а нет"))

print("\nOOS-ПРОТОКОЛ (breaker без гейтов — частота выше):")
B = D[D.nb >= 1]
print(rep(B[~B.oos], "IS-монеты"))
print(rep(B[B.oos], "OOS-монеты"))
print(rep(B[B.year <= 2024], "IS-время 2022-24"))
print(rep(B[B.year >= 2025], "OOS-время 2025-26"))
print(rep(B[B.oos & (B.year >= 2025)], "OOS × OOS"))

print("\nПО СТОРОНАМ · ГОДАМ · РЕЖИМУ (breaker есть):")
for side in ("long", "short"):
    print(rep(B[B.side == side], f"{side}"))
for y in sorted(B.year.unique()):
    print(rep(B[B.year == y], str(y)))

print("\nПО РАЗМЕРУ СТОПА и ЛИКВИДНОСТИ (breaker есть):")
for lab, sub in B.groupby(pd.qcut(B.sp, 4, duplicates="drop"), observed=True):
    print(rep(sub, f"стоп {lab}"))
med = D.liq.median()
print(rep(B[B.liq >= med], "ликвидная половина"))
print(rep(B[B.liq < med], "неликвидная половина"))
