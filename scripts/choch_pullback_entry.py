# -*- coding: utf-8 -*-
"""МЕХАНИКА ЕГОРА: CHoCH → КОРРЕКЦИЯ → ВХОД → ПРОФИТ (14.08.2026, Даат).

Егор: «мы ищем поток сделок по несколько процентов каждая… нам нужно постоянство
мелкого профита на дистанции, а не купил/держи. Коррекция после CHoCH — вход — профит».

Почему это правильная постановка (а не то, что мерилось раньше):
  • ЧАСТОТА — CHoCH случается регулярно на 15m/1h, а не раз в месяц;
  • КОРОТКОЕ удержание — берём кусок движения, не ждём ракету;
  • ВХОД НА ОТКАТЕ = естественная точка для ЛИМИТНОГО ордера. Замер 14.08 показал:
    налог на исполнение по рынку +0.44% за круг (5796 ордеров). Лимитный вход его
    НЕ платит — эта механика обходит налог по своей природе.

Механика:
  1. CHoCH на рабочем ТФ (детектор причинный: аудит лага 13.08 — bull/bear_choch лаг 0);
  2. КОРРЕКЦИЯ — цена откатывает против направления слома на N% от импульса слома;
  3. ВХОД лимитом в зоне коррекции, в сторону CHoCH;
  4. ПРОФИТ — фиксированная цель в % или R, короткий TTL.

Считается сетка: ТФ × глубина коррекции × цель. Косты — ДВА варианта:
  market 0.79% (комиссия 0.35 + налог 0.44) и limit 0.35% (только комиссия).

Запуск:  python scripts/choch_pullback_entry.py [--coins 120] [--tf 1h]
"""
from __future__ import annotations

import argparse
import datetime as dt
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
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BAR_H = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}
COST_MARKET = 0.79
COST_LIMIT = 0.35
PULLBACKS = [0.236, 0.382, 0.5, 0.618]      # глубина коррекции от импульса слома
TARGETS = [1.0, 2.0, 3.0]                    # цель в R (R = риск до стопа)


def stat(rows, days, cost):
    if not rows:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net = pr - cost
    r = net / sp
    neg = abs(net[net < 0].sum())
    return dict(n=len(rows), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
                pct=float(net.mean()), r=float(r.mean()),
                stop=float(np.median(sp)), freq=len(rows) / max(days, 1),
                r_day=float(r.mean()) * len(rows) / max(days, 1),
                med_pct=float(np.median(net)))


def line(nm, s, cost):
    if not s or s["n"] < 50:
        print(f"    {nm:<30} — мало ({0 if not s else s['n']})")
        return
    mark = "🟢" if s["r_day"] > 0 else "  "
    print(f"  {mark}{nm:<30} n={s['n']:>6} стоп {s['stop']:>5.2f}% "
          f"косты={100 * cost / s['stop']:>4.0f}% WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"{s['pct']:>+7.2f}%/сд {s['freq']:>6.2f}сд/дн {s['r_day']:>+7.3f}R/день")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=120)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--tf", type=str, default="1h")
    ap.add_argument("--wait", type=int, default=12, help="сколько баров ждать коррекцию")
    ap.add_argument("--ttl", type=int, default=48, help="горизонт удержания, баров")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 122)
    print(f"CHoCH → КОРРЕКЦИЯ → ВХОД → ПРОФИТ · {a.tf} · {len(syms)} монет с {a.since}")
    print(f"ждём откат до {a.wait} баров · удержание до {a.ttl} баров "
          f"(~{a.ttl * BAR_H[a.tf] / 24:.1f} сут)")
    print(f"косты: MARKET {COST_MARKET}% (с налогом на исполнение) · LIMIT {COST_LIMIT}% (только комиссия)")
    print("═" * 122)

    A = defaultdict(list)      # A[(pb, tgt, side)] = [(profit%, stop%)]
    NOFILL = defaultdict(int)  # сколько раз коррекция не пришла
    TOTAL = defaultdict(int)
    days = 1

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='15m' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 8000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        m15 = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        d = m15 if a.tf == "15m" else m15.resample(RULE[a.tf]).agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}).dropna()
        if len(d) < 300:
            continue
        days = max(days, (d.index.max() - d.index.min()).days)
        try:
            F = compute_flags(d, a.tf, include_pivots=False)
        except Exception:
            continue

        def arr(col):
            k = f"{col}_{a.tf}"
            if k not in F.columns:
                return np.zeros(len(d), dtype=bool)
            try:
                return np.asarray(F[k].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d), dtype=bool)

        bull_ch, bear_ch = arr("bull_choch"), arr("bear_choch")
        H, L, C = d.high.values, d.low.values, d.close.values
        n = len(d)

        for side, flags in (("long", bull_ch), ("short", bear_ch)):
            for i in np.flatnonzero(flags):
                i = int(i)
                if i < 25 or i >= n - a.ttl - 2:
                    continue
                # импульс слома: от экстремума перед CHoCH до цены слома
                if side == "long":
                    imp_lo = float(L[max(0, i - 20):i + 1].min())
                    imp_hi = float(C[i])
                    if imp_hi <= imp_lo:
                        continue
                    rng = imp_hi - imp_lo
                else:
                    imp_hi = float(H[max(0, i - 20):i + 1].max())
                    imp_lo = float(C[i])
                    if imp_hi <= imp_lo:
                        continue
                    rng = imp_hi - imp_lo

                for pb in PULLBACKS:
                    TOTAL[(pb, side)] += 1
                    entry = (imp_hi - rng * pb) if side == "long" else (imp_lo + rng * pb)
                    # ждём коррекцию: лимит исполняется, если цена дошла до уровня
                    j_fill = None
                    for j in range(i + 1, min(i + 1 + a.wait, n)):
                        if side == "long" and L[j] <= entry:
                            j_fill = j; break
                        if side == "short" and H[j] >= entry:
                            j_fill = j; break
                    if j_fill is None:
                        NOFILL[(pb, side)] += 1
                        continue
                    # стоп за начало импульса (инвалидация слома)
                    sl = imp_lo * 0.999 if side == "long" else imp_hi * 1.001
                    sp = abs(entry - sl) / entry * 100
                    if sp <= 0 or sp > 25:
                        continue
                    risk = abs(entry - sl)
                    end = min(j_fill + a.ttl, n - 1)
                    fl, fh = L[j_fill + 1:end + 1], H[j_fill + 1:end + 1]
                    if len(fl) == 0:
                        continue
                    for tgt in TARGETS:
                        tp = entry + tgt * risk if side == "long" else entry - tgt * risk
                        if side == "long":
                            hs, ht = fl <= sl, fh >= tp
                            lo_, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
                            tail = (C[end] - entry) / entry * 100
                        else:
                            hs, ht = fh >= sl, fl <= tp
                            lo_, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
                            tail = (entry - C[end]) / entry * 100
                        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
                        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
                        pr = lo_ if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)
                        A[(pb, tgt, side)].append((pr, sp))
        if si % 30 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    print(f"\nокно {days} дней")
    for side in ("short", "long"):
        print(f"\n{'=' * 122}")
        print(f"=== {side.upper()} ===")
        for pb in PULLBACKS:
            tot, nf = TOTAL[(pb, side)], NOFILL[(pb, side)]
            fill = 100 * (1 - nf / tot) if tot else 0
            print(f"\n  коррекция {pb:.3f} от импульса · лимит исполнился в {fill:.0f}% случаев "
                  f"({tot - nf} из {tot})")
            for tgt in TARGETS:
                s = stat(A[(pb, tgt, side)], days, COST_LIMIT)
                line(f"цель {tgt:.0f}R · LIMIT {COST_LIMIT}%", s, COST_LIMIT)
            for tgt in TARGETS:
                s = stat(A[(pb, tgt, side)], days, COST_MARKET)
                line(f"цель {tgt:.0f}R · MARKET {COST_MARKET}%", s, COST_MARKET)

    print("\n" + "═" * 122)
    print("Вход в коррекцию = ЛИМИТНЫЙ ордер → налог на исполнение (+0.44% за круг) НЕ платится.")
    print("Строки LIMIT и MARKET показывают цену этого различия на одних и тех же сделках.")
    print("═" * 122)
    return 0


if __name__ == "__main__":
    sys.exit(main())
