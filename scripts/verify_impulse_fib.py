# -*- coding: utf-8 -*-
"""Регрессия + перемер боевого калькулятора `core/smc/impulse_fib.py` (20.08.2026).

Часть A — ЭКВИВАЛЕНТНОСТЬ: боевой `find_setup(df[:b+2])` обязан выдать тот же сетап,
что эталонный детектор замера видит на баре b. Ловит ровно тот класс бага, который
уже случился с `choch_wavec_loop` (резолвер искал фил по всей истории → 1086 из 1807
сетапов расходились). Проверяется до боя, а не после.

Часть B — ПЕРЕМЕР: боевая геометрия отличается от замера ОДНИМ местом — стоп берётся
от ATR на баре конца импульса, а не на баре фила (в момент постановки лимита ATR
будущего бара неизвестен). Считаем, что это меняет, полным OOS-протоколом.
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

from core.smc.impulse_fib import (       # noqa: E402
    ENTRY_FIB, HOLD_BARS, STOP_ATR_K, TARGET_FIB, WAIT_BARS,
    _atr, find_impulses, find_setup, gates, is_junk, score, size_mult,
)

DB, COST, PEN = "ohlcv_cache.db", 0.35, 0.15
RISK = 2.0
N = int(sys.argv[1]) if len(sys.argv) > 1 else 250


def load(sym, tf="1h"):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe=? ORDER BY time", c, params=(sym, tf))
    c.close()
    if len(d) < 1500:
        return None
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


# ─────────────────────────── ЧАСТЬ A: эквивалентность ────────────────────────
def part_a(syms):
    print("=" * 100)
    print("A. ЭКВИВАЛЕНТНОСТЬ: боевой find_setup(df[:b+2]) == эталон на баре b")
    print("=" * 100)
    checked = mism = 0
    for sym in syms:
        df = load(sym)
        if df is None:
            continue
        dd = df.reset_index(drop=True)
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        atr = _atr(dd).values
        imps = find_impulses(H, L, C, atr, len(dd))
        imps = [x for x in imps if x[1] >= 300]
        if not imps:
            continue
        for a, b, up in random.Random(7).sample(imps, min(6, len(imps))):
            # df[:b+2] = история по бар b включительно + незакрытый бар b+1.
            # 🔑 Сверяется НАЧАЛО импульса и геометрия от него: после перехода на дедуп
            # по origin бар b перестал быть частью контракта (детектор видит импульс
            # на нескольких соседних барах, побеждает первый записанный).
            s = find_setup(df.iloc[:b + 2], symbol=sym)
            checked += 1
            if "reason" in s:
                mism += 1
                print(f"  ✗ {sym} b={b}: боевой молчит — {s['reason']}")
                continue
            bb = s["b"]
            amp = abs(C[bb] - C[s["a"]])
            sign = -1.0 if s["side"] == "long" else 1.0
            e_ref = C[bb] + sign * ENTRY_FIB * amp
            t_ref = C[bb] + sign * TARGET_FIB * amp
            ok = (s["a"] == a and s["side"] == ("long" if up else "short")
                  and abs(s["entry"] - e_ref) < 1e-9 and abs(s["tp"] - t_ref) < 1e-9)
            if not ok:
                mism += 1
                print(f"  ✗ {sym} эталон a={a} b={b} {'long' if up else 'short'} → "
                      f"боевой a={s['a']} b={bb} {s['side']} entry={s['entry']:.6f}")
    verdict = "ЧИСТО" if mism == 0 else f"РАСХОЖДЕНИЙ {mism}"
    print(f"\n  проверено сетапов: {checked} · {verdict}")
    return mism == 0


# ─────────────────────────── ЧАСТЬ B: перемер геометрии ──────────────────────
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

    out = []
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
        deep = entry * (1 - PEN / 100) if up else entry * (1 + PEN / 100)
        w = range(b + 1, min(b + 1 + WAIT_BARS, n))
        if up:
            jf = next((q for q in w if L[q] <= entry), None)
            jd = next((q for q in w if L[q] <= deep), None)
        else:
            jf = next((q for q in w if H[q] >= entry), None)
            jd = next((q for q in w if H[q] >= deep), None)
        if jf is None or jd is None:      # консервативный фил: только пробитые глубже
            continue

        row = {"sym": sym, "oos": oos, "year": df.index[b].year, "side": side,
               "vratio": float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0,
               "regime": float(regime[b]) if not np.isnan(regime[b]) else 1.0,
               "with_trend": (C[b] > ema200[b]) == up,
               "amp_pct": amp / x_ * 100}
        end = min(jf + HOLD_BARS, n - 1)
        fh, flw = H[jf + 1:end + 1], L[jf + 1:end + 1]
        if len(fh) == 0:
            continue
        jt = (next((k for k in range(len(fh)) if fh[k] >= tp), 10 ** 9) if up
              else next((k for k in range(len(flw)) if flw[k] <= tp), 10 ** 9))

        # три геометрии стопа: эталон замера · боевая · старый стоп за origin
        for tag, sl in (("ref_jf", entry - STOP_ATR_K * atr[jf] if up else entry + STOP_ATR_K * atr[jf]),
                        ("live_b", entry - STOP_ATR_K * atr[b] if up else entry + STOP_ATR_K * atr[b]),
                        ("origin", o_ * (0.999 if up else 1.001))):
            if (up and sl >= entry) or (not up and sl <= entry):
                continue
            sp = abs(entry - sl) / entry * 100
            if sp <= 0 or sp > 30:
                continue
            js = (next((k for k in range(len(flw)) if flw[k] <= sl), 10 ** 9) if up
                  else next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9))
            if js <= jt and js < 10 ** 9:
                r = ((sl - entry) if up else (entry - sl)) / entry * 100
            elif jt < 10 ** 9:
                r = ((tp - entry) if up else (entry - tp)) / entry * 100
            else:
                o2 = float(C[end])
                r = ((o2 - entry) if up else (entry - o2)) / entry * 100
            row[tag] = r - COST
            row[f"sp_{tag}"] = sp
        if "live_b" in row:
            out.append(row)
    return out


def rep(v, col, name, span_years=4.6):
    if len(v) < 25 or col not in v.columns:
        return f"  {name:<42} n={len(v):<5} — мало"
    m = v[col].notna()
    v = v[m]
    p = v[col].values
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    cov = (v.groupby("sym")[col].sum() > 0).mean() * 100
    freq = len(p) / max(v.sym.nunique(), 1) / (span_years * 12) * 250
    depo = p.mean() / v[f"sp_{col}"].median() * RISK
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

ok = part_a(syms[:8])

R = []
for i, sym in enumerate(syms, 1):
    R += run(sym)
    if i % 40 == 0:
        print(f"  ... {i}/{len(syms)} · {len(R)}")

D = pd.DataFrame(R)
D.to_pickle("scratch_impulse_live.pkl")
D["g3"] = (D.vratio >= 1.0) & (D.vratio < 1.5) & D.with_trend & (D.regime >= 1.1)
D["score"] = [score(r) for r in D.to_dict("records")]

print("\n" + "=" * 136)
print(f"B. ПЕРЕМЕР БОЕВОЙ ГЕОМЕТРИИ · {D.sym.nunique()} монет · {len(D)} входов · косты {COST}%")
print("=" * 136)
print("ГЕОМЕТРИЯ СТОПА (вся выборка, без гейтов):")
for tag, nm in (("origin", "старый: за начало импульса"),
                ("ref_jf", "замер: 2.5·ATR на баре фила"),
                ("live_b", "БОЕВОЙ: 2.5·ATR на баре импульса")):
    print(rep(D, tag, nm))

G = D[D.g3]
print("\nС ТРЕМЯ ГЕЙТАМИ:")
for tag, nm in (("origin", "старый стоп + гейты"),
                ("ref_jf", "замер + гейты"),
                ("live_b", "БОЕВОЙ + гейты")):
    print(rep(G, tag, nm))

print("\nOOS-ПРОТОКОЛ (боевая геометрия + три гейта):")
print(rep(G[~G.oos], "live_b", "IS-монеты"))
print(rep(G[G.oos], "live_b", "OOS-монеты"))
print(rep(G[G.year <= 2024], "live_b", "IS-время 2022-24"))
print(rep(G[G.year >= 2025], "live_b", "OOS-время 2025-26"))
print(rep(G[G.oos & (G.year >= 2025)], "live_b", "OOS × OOS"))

print("\nПО СТОРОНАМ:")
for side in ("long", "short"):
    S = G[G.side == side]
    print(rep(S, "live_b", f"{side} итог"))
    print(rep(S[S.oos], "live_b", f"   {side} OOS-монеты"))

print("\nПО ГОДАМ:")
for y in sorted(G.year.unique()):
    print(rep(G[G.year == y], "live_b", str(y)))

print("\nПО РАЗМЕРУ СТОПА (закон размера):")
q = pd.qcut(G["sp_live_b"], 4, duplicates="drop")
for lab, sub in G.groupby(q, observed=True):
    print(rep(sub, "live_b", f"стоп {lab}"))

print("\nСТУПЕНИ РАЗМЕРА ПО СКОРУ (на всей базе, гейты не применяются):")
for lo, hi in ((0, 1.0), (1.0, 1.7), (1.7, 2.3), (2.3, 9)):
    sub = D[(D.score >= lo) & (D.score < hi)]
    print(rep(sub, "live_b", f"скор [{lo};{hi}) ×{size_mult((lo + hi) / 2 if hi < 9 else 2.5)}"))
