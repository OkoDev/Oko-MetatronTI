# -*- coding: utf-8 -*-
"""ЦЕЛЬ: СВОЙСТВО СТОРОНЫ ИЛИ СОГЛАСИЯ С РЕЖИМОМ? (возражение Егора 20.08.2026)

Егор: «мне не нравится, что цель по стороне мы ставим ЖЁСТКО — сегодня рынок дал сильные
разворотные импульсы, картина лонга может измениться, а мы поедем на хардкоде».

Возражение по существу. «LONG −1.0 · SHORT −1.618» измерено на окне 2022-2026, которое
почти целиком снос альтов вниз. Наша карта режимов ([[regime_map_four_setups_downdrift]])
уже показывала, что ось — не сторона, а СОГЛАСИЕ СО СНОСОМ. Переворот стороны в 08.2025
тоже был периодом, а не составом ([[fade_side_flip_2026_period_not_survivorship]]).

Разводим три гипотезы на одних и тех же сделках:
  H1 «сторона»  — дальняя цель принадлежит шорту как таковому;
  H2 «режим»    — дальняя цель принадлежит движению ПО режиму рынка (согласному с дрейфом);
  H3 «ни то»    — оптимум цели одинаков везде, различие 19.08 было шумом окна.

Метка режима — ПРИЧИННАЯ (`core/context/market_drift.regime_series`: расширяющиеся
терцили + shift(1)), не «доходность за год». Панель для режима строится на 4h
(дефолты модуля), метка переносится на 1h-бары назад по времени.
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

from core.context.market_drift import BEAR, BULL, FLAT, regime_series  # noqa: E402
from core.smc.impulse_fib import (ENTRY_FIB, HOLD_BARS, STOP_ATR_K,    # noqa: E402
                                  WAIT_BARS, _atr, find_impulses, is_junk)

DB, COST, PEN, RISK = "ohlcv_cache.db", 0.35, 0.15, 2.0
GRID = [-0.5, -0.786, -1.0, -1.272, -1.618, -2.0, -2.618]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def load(sym, tf="1h"):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                    "AND timeframe=? ORDER BY time", c, params=(sym, tf))
    c.close()
    if len(d) < 1500:
        return None
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
                 "GROUP BY symbol HAVING n>3000 ORDER BY n DESC").fetchall()
c.close()
_all = [s for s, _ in rows if not is_junk(s)]
random.Random(19).shuffle(_all)
syms = _all[:N]

# ── ПРИЧИННАЯ МЕТКА РЕЖИМА ───────────────────────────────────────────────────
print("панель 4h для режима...", flush=True)
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cols = {}
for s in syms:
    d = pd.read_sql("SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe='4h' "
                    "ORDER BY time", c, params=(s,))
    if len(d) > 500:
        cols[s] = pd.Series(d.close.values, index=pd.to_datetime(d.time, unit="ms", utc=True))
c.close()
panel = pd.DataFrame(cols).sort_index()
# regime_series возвращает DataFrame (drift, breadth, label_drift, label_breadth, label)
# и уже сдвинут на 1 бар внутри модуля — берём готовую метку.
reg = regime_series(panel)["label"].dropna()
print(f"  панель {panel.shape} · режим: "
      + " · ".join(f"{k} {v}" for k, v in reg.value_counts().items()), flush=True)


def run(sym):
    df = load(sym)
    if df is None:
        return []
    dd = df.reset_index(drop=True)
    H, L, C, V = dd.high.values, dd.low.values, dd.close.values, dd.volume.values
    n = len(dd)
    aa = _atr(dd)
    atr = aa.values
    regime_vol = (aa / aa.rolling(100).mean()).values
    ema200 = dd.close.ewm(span=200, adjust=False).mean().values
    volma = pd.Series(V).rolling(120).mean().values
    oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
    # метка рынка на каждый 1h-бар: последняя известная 4h-метка (asof, без будущего)
    mkt = reg.reindex(reg.index.union(df.index)).ffill().reindex(df.index).values

    out = []
    for a, b, up in find_impulses(H, L, C, atr, n):
        if b < 250 or b >= n - HOLD_BARS - WAIT_BARS - 2:
            continue
        m = mkt[b]
        if not isinstance(m, str):
            continue
        side = "long" if up else "short"
        o_, x_ = float(C[a]), float(C[b])
        amp = abs(x_ - o_)
        if amp <= 0:
            continue
        sign = -1.0 if up else 1.0
        entry = x_ + sign * ENTRY_FIB * amp
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

        end = min(jf + HOLD_BARS, n - 1)
        fh, flw = H[jf + 1:end + 1], L[jf + 1:end + 1]
        if len(fh) == 0:
            continue
        js = (next((k for k in range(len(flw)) if flw[k] <= sl), 10 ** 9) if up
              else next((k for k in range(len(fh)) if fh[k] >= sl), 10 ** 9))

        row = {"sym": sym, "oos": oos, "year": df.index[b].year, "side": side, "sp": sp,
               "mkt": m,
               # согласие: лонг в быка / шорт в медведя = ПО режиму
               "agree": (up and m == BULL) or (not up and m == BEAR),
               "against": (up and m == BEAR) or (not up and m == BULL),
               "vratio": float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0,
               "vol_regime": float(regime_vol[b]) if not np.isnan(regime_vol[b]) else 1.0,
               "with_trend": (C[b] > ema200[b]) == up,
               "liq": float(np.nanmedian(V[max(0, b - 500):b] * C[max(0, b - 500):b]))}
        for lv in GRID:
            tp = x_ + sign * lv * amp
            jt = (next((k for k in range(len(fh)) if fh[k] >= tp), 10 ** 9) if up
                  else next((k for k in range(len(flw)) if flw[k] <= tp), 10 ** 9))
            if js <= jt and js < 10 ** 9:
                r = ((sl - entry) if up else (entry - sl)) / entry * 100
            elif jt < 10 ** 9:
                r = ((tp - entry) if up else (entry - tp)) / entry * 100
            else:
                o2 = float(C[end])
                r = ((o2 - entry) if up else (entry - o2)) / entry * 100
            row[f"t{lv}"] = r - COST
        out.append(row)
    return out


R = []
for i, sym in enumerate(syms, 1):
    R += run(sym)
    if i % 25 == 0:
        print(f"  ... {i}/{len(syms)} · {len(R)}", flush=True)

D = pd.DataFrame(R)
D.to_pickle("scratch_target_regime.pkl")
D["g3"] = (D.vratio >= 1.0) & (D.vratio < 1.5) & D.with_trend & (D.vol_regime >= 1.1)


def pf(v, col):
    p = v[col].values
    if len(p) < 25:
        return None
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    return w.sum() / gl if gl else 0.0


def line(v, name):
    if len(v) < 25:
        return f"  {name:<34} n={len(v):<5} — мало"
    best, bpf = None, -1
    cells = []
    for lv in GRID:
        x = pf(v, f"t{lv}")
        cells.append("  —  " if x is None else f"{x:5.2f}")
        if x is not None and x > bpf:
            best, bpf = lv, x
    return f"  {name:<34} n={len(v):<5} " + " ".join(cells) + f"   ← лучшая {best}"


def money(v, lv, name, span_years=4.6):
    col = f"t{lv}"
    if len(v) < 25:
        return f"  {name:<40} n={len(v):<5} — мало"
    p = v[col].values
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    cov = (v.groupby("sym")[col].sum() > 0).mean() * 100
    freq = len(p) / max(v.sym.nunique(), 1) / (span_years * 12) * 250
    depo = p.mean() / v.sp.median() * RISK
    return (f"  {name:<40} n={len(p):<5} WR {len(w) / len(p) * 100:5.1f}%  "
            f"PF {(w.sum() / gl if gl else 0):5.2f}  ср {p.mean():+6.2f}%  "
            f"безтоп10% {s[int(len(s) * 0.1):].sum():+7.0f}  {freq:5.1f} сд/мес  "
            f"{depo * freq:+6.2f}% депо/мес  охват {cov:3.0f}%")


hdr = "  " + " " * 34 + " " * 8 + " ".join(f"{lv:>5}" for lv in GRID)
print("\n" + "=" * 130)
print(f"ЦЕЛЬ ПО СТОРОНЕ ИЛИ ПО РЕЖИМУ · {D.sym.nunique()} монет · {len(D)} входов · PF по сетке целей")
print("=" * 130)
print(hdr)
print(line(D, "ВСЯ БАЗА"))

print("\nH1 «СТОРОНА» — если верна, оптимумы long и short РАЗНЫЕ во всех режимах:")
for side in ("long", "short"):
    print(line(D[D.side == side], f"{side}"))

print("\nH2 «РЕЖИМ» — если верна, оптимум идёт за согласием, а не за стороной:")
print(line(D[D.agree], "ПО режиму (лонг в быка / шорт в медведя)"[:34]))
print(line(D[D.against], "ПРОТИВ режима"))
print(line(D[D.mkt == FLAT], "нейтраль"))

print("\nРАЗВЁРТКА режим × сторона (ключевая таблица):")
for m in (BULL, BEAR, FLAT):
    for side in ("long", "short"):
        print(line(D[(D.mkt == m) & (D.side == side)], f"{m} · {side}"))

print("\nТО ЖЕ С ТРЕМЯ ГЕЙТАМИ:")
G = D[D.g3]
for m in (BULL, BEAR, FLAT):
    for side in ("long", "short"):
        print(line(G[(G.mkt == m) & (G.side == side)], f"{m} · {side}"))

print("\nOOS-ПРОВЕРКА H2 (только OOS-монеты и OOS-время):")
O = D[D.oos & (D.year >= 2025)]
print(line(O[O.agree], "OOS×OOS · ПО режиму"))
print(line(O[O.against], "OOS×OOS · ПРОТИВ режима"))
print(line(O[O.mkt == FLAT], "OOS×OOS · нейтраль"))

print("\nПО ГОДАМ (проверка «оптимум кочует вслед за эпохой»):")
for y in sorted(D.year.unique()):
    for side in ("long", "short"):
        print(line(D[(D.year == y) & (D.side == side)], f"{y} · {side}"))

print("\nДЕНЬГИ: ТРИ ПРАВИЛА ЦЕЛИ НА ОДНИХ СДЕЛКАХ (с гейтами):")
print(money(G, -1.272, "фикс −1.272 для всех"))
print(money(G, -1.0, "фикс −1.0 для всех"))
print(money(G, -1.618, "фикс −1.618 для всех"))
sub_l = G[G.side == "long"]
sub_s = G[G.side == "short"]
p_side = np.concatenate([sub_l["t-1.0"].values, sub_s["t-1.618"].values])
p_reg = np.concatenate([G[G.agree]["t-1.618"].values, G[~G.agree]["t-1.0"].values])
for nm, p in (("ПО СТОРОНЕ (хардкод 19.08)", p_side), ("ПО РЕЖИМУ (правило Егора)", p_reg)):
    w = p[p > 0]
    gl = -p[p <= 0].sum()
    s = np.sort(p)[::-1]
    print(f"  {nm:<40} n={len(p):<5} WR {len(w) / len(p) * 100:5.1f}%  "
          f"PF {(w.sum() / gl if gl else 0):5.2f}  ср {p.mean():+6.2f}%  "
          f"безтоп10% {s[int(len(s) * 0.1):].sum():+7.0f}")
