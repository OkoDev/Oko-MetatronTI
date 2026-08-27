# -*- coding: utf-8 -*-
"""ФИЛЬТР ПО ПОТОКУ КАПИТАЛА: USDT.D НА 1h (14.08.2026, Даат).

Егор: «usdt.d на 1h! ищи идеальные механики, WR нужно повышать до лучше чем монетка».

Идея: USDT.D — доля стейблкоина в капитализации. Растёт → деньги уходят в стейблы,
альты падают. Падает → деньги идут в риск, альты растут. Сделка ПРОТИВ потока капитала
обречена независимо от качества сетапа — значит фильтр должен поднять WR.

Данные: `ohlcv_cache.db` → `usdtd_1h` (1948 баров, 04.07–14.08.2026) и `usdtd` (дневной).
🔴 ОГРАНИЧЕНИЕ: истории USDT.D всего ~6 недель на 1h. Полное окно 2024-26 недоступно.
Зато окно СВЕЖЕЕ и в отборе механик не участвовало → это естественный OOS.

Проверяются обе найденные механики:
  A. CHoCH → коррекция → вход лимитом (поток мелкого профита, механика Егора)
  B. смена ATR-тренда + FVG (найдена 14.08)
и для каждой — WR/PF БЕЗ фильтра и С фильтром по направлению USDT.D.

Косты: LIMIT 0.35% (комиссия) для A, MARKET 0.79% (с налогом на исполнение) для B.

Запуск:  python scripts/usdtd_flow_filter.py [--coins 150] [--usdtd-win 6]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
COST_LIMIT = 0.35
COST_MARKET = 0.79
SL_LOOKBACK = 10


def load_usdtd():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT time, close FROM usdtd_1h ORDER BY time", con)
    con.close()
    d["t"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("t")["close"]


def atr_dir(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().values
    up, dn = hl2 - factor * atr, hl2 + factor * atr
    n, cv = len(c), c.values
    u = np.zeros(n); d_ = np.zeros(n); dirn = np.zeros(n)
    u[0], d_[0], dirn[0] = up[0], dn[0], 1
    for i in range(1, n):
        u[i] = max(up[i], u[i - 1]) if cv[i - 1] > u[i - 1] else up[i]
        d_[i] = min(dn[i], d_[i - 1]) if cv[i - 1] < d_[i - 1] else dn[i]
        dirn[i] = 1 if cv[i] > d_[i - 1] else (-1 if cv[i] < u[i - 1] else dirn[i - 1])
    return dirn


def fvg_flags(df):
    high, low, close = df.high.values, df.low.values, df.close.values
    n = len(df)
    bull = np.zeros(n, dtype=bool); bear = np.zeros(n, dtype=bool)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(2, n)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(2, n):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                bull[i] = True
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                bear[i] = True
    return bull, bear


def trade(H, L, C, i, side, sl, tp_r, ttl):
    e = C[i]
    if side == "long" and sl >= e:
        return None
    if side == "short" and sl <= e:
        return None
    sp = abs(e - sl) / e * 100
    if sp <= 0 or sp > 25:
        return None
    risk = abs(e - sl)
    end = min(i + ttl, len(C) - 1)
    fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        tp = e + tp_r * risk
        hs, ht = fl <= sl, fh >= tp
        lo, hi_, tail = (sl - e) / e * 100, (tp - e) / e * 100, (C[end] - e) / e * 100
    else:
        tp = e - tp_r * risk
        hs, ht = fh >= sl, fl <= tp
        lo, hi_, tail = (e - sl) / e * 100, (e - tp) / e * 100, (e - C[end]) / e * 100
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    pr = lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)
    return pr, sp


def stat(rows, cost):
    if not rows or len(rows) < 25:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net = pr - cost
    neg = abs(net[net < 0].sum())
    return dict(n=len(rows), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
                pct=float(net.mean()), r=float((net / sp).mean()))


def show(nm, s, base=None):
    if not s:
        print(f"    {nm:<34} — мало данных")
        return
    dwr = f"{s['wr'] - base['wr']:+5.1f}" if base else "     "
    mark = "🟢" if s["wr"] > 50 else ("  " if s["pct"] > 0 else "  ")
    print(f"  {mark}{nm:<34} n={s['n']:>5} WR {s['wr']:>5.1f}% ({dwr}) "
          f"PF {s['pf']:>5.2f} {s['pct']:>+7.2f}%/сд {s['r']:>+6.3f}R/сд")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=150)
    ap.add_argument("--usdtd-win", type=int, default=6, help="окно дельты USDT.D, часов")
    ap.add_argument("--tf", type=str, default="1h")
    ap.add_argument("--ttl", type=int, default=48)
    a = ap.parse_args()

    ud = load_usdtd()
    print("═" * 118)
    print(f"ФИЛЬТР ПО USDT.D · окно данных {ud.index.min():%d.%m} → {ud.index.max():%d.%m} "
          f"({len(ud)} баров 1h)")
    print(f"дельта USDT.D за {a.usdtd_win}ч · растёт → деньги в стейблы (ШОРТ альты) · "
          f"падает → в риск (ЛОНГ)")
    print(f"🔴 окно ~6 недель — но оно СВЕЖЕЕ и в отборе механик не участвовало (OOS)")
    print("═" * 118)

    d_ud = ud.diff(a.usdtd_win)
    print(f"\nUSDT.D сейчас {ud.iloc[-1]:.3f}% · за {a.usdtd_win}ч "
          f"{d_ud.iloc[-1]:+.4f} п.п. · медиана |дельты| {d_ud.abs().median():.4f}")
    print(f"доля времени: рост {100 * (d_ud > 0).mean():.0f}% · падение {100 * (d_ud < 0).mean():.0f}%")

    t0ms = int(ud.index.min().timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>400 ORDER BY n DESC LIMIT ?", (t0ms, a.coins)).fetchall()]
    con.close()
    print(f"вселенная: {len(syms)} монет с данными в окне\n")

    # ключ: (механика, сторона, фильтр) → список (profit%, stop%)
    A = defaultdict(list)
    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                          c, params=(sym, t0ms - 400 * 3600_000))
        c.close()
        if len(raw) < 400:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        d = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        try:
            F = compute_flags(d, "1h", include_pivots=False)
        except Exception:
            continue

        def arr(col):
            k = f"{col}_1h"
            if k not in F.columns:
                return np.zeros(len(d), dtype=bool)
            try:
                return np.asarray(F[k].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d), dtype=bool)

        bull_ch, bear_ch = arr("bull_choch"), arr("bear_choch")
        td = atr_dir(d)
        bull_f, bear_f = fvg_flags(d)
        H, L, C = d.high.values, d.low.values, d.close.values
        # дельта USDT.D, выровненная на бары монеты (только прошлое)
        dud = d_ud.reindex(d.index, method="ffill").values

        for i in range(30, len(d) - a.ttl - 2):
            if np.isnan(dud[i]):
                continue
            flow_short = dud[i] > 0          # USDT.D растёт → шорт альты
            flow_long = dud[i] < 0

            # ── A: CHoCH → коррекция 0.236 → лимитный вход ──
            for side, ch in (("long", bull_ch), ("short", bear_ch)):
                if not ch[i]:
                    continue
                if side == "long":
                    lo_ = float(L[max(0, i - 20):i + 1].min()); hi_ = float(C[i])
                else:
                    hi_ = float(H[max(0, i - 20):i + 1].max()); lo_ = float(C[i])
                if hi_ <= lo_:
                    continue
                rng = hi_ - lo_
                entry = hi_ - rng * 0.236 if side == "long" else lo_ + rng * 0.236
                jf = None
                for j in range(i + 1, min(i + 13, len(d))):
                    if (side == "long" and L[j] <= entry) or (side == "short" and H[j] >= entry):
                        jf = j; break
                if jf is None:
                    continue
                sl = lo_ * 0.999 if side == "long" else hi_ * 1.001
                r = trade(H, L, np.concatenate([C[:jf], [entry], C[jf + 1:]]),
                          jf, side, sl, 2.0, a.ttl)
                if r:
                    ok = flow_long if side == "long" else flow_short
                    A[("CHoCH", side, "все")].append(r)
                    A[("CHoCH", side, "по потоку")].append(r) if ok else \
                        A[("CHoCH", side, "против")].append(r)

            # ── B: смена ATR-тренда + FVG ──
            for side, want, fvg in (("long", 1, bull_f), ("short", -1, bear_f)):
                if td[i] != want or td[i - 1] == want:
                    continue
                if not fvg[max(0, i - 8):i + 1].any():
                    continue
                sl = float(L[i - SL_LOOKBACK:i + 1].min()) * 0.999 if side == "long" \
                    else float(H[i - SL_LOOKBACK:i + 1].max()) * 1.001
                r = trade(H, L, C, i, side, sl, 2.0, a.ttl)
                if r:
                    ok = flow_long if side == "long" else flow_short
                    A[("ATR+FVG", side, "все")].append(r)
                    A[("ATR+FVG", side, "по потоку")].append(r) if ok else \
                        A[("ATR+FVG", side, "против")].append(r)
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    for mech, cost, cname in (("CHoCH", COST_LIMIT, "LIMIT 0.35%"),
                              ("ATR+FVG", COST_MARKET, "MARKET 0.79%")):
        print(f"\n{'=' * 118}")
        print(f"=== {mech} · косты {cname} ===")
        for side in ("short", "long"):
            base = stat(A[(mech, side, "все")], cost)
            print(f"\n  --- {side.upper()} ---")
            show("без фильтра", base)
            show("ПО ПОТОКУ USDT.D", stat(A[(mech, side, "по потоку")], cost), base)
            show("против потока", stat(A[(mech, side, "против")], cost), base)

    print("\n" + "═" * 118)
    print("🟢 = WR выше 50% (цель Егора: лучше монетки). В скобках — Δ WR к строке «без фильтра».")
    print("Если фильтр работает, «по потоку» обязан быть ВЫШЕ базы, а «против» — НИЖЕ.")
    print("═" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
