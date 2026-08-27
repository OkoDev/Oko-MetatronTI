# -*- coding: utf-8 -*-
"""ЖИВОЙ СКАН: ГДЕ СЕЙЧАС ШОРТ ОТ СОПРОТИВЛЕНИЯ (14.08.2026, Даат).

Егор: «открывай TW и ищи по всем монетам и всем нужным ТФ сетапы».

Кэш `ohlcv_cache.db` обрывается на 31.07.2026, сегодня 14.08 — для ЖИВОГО поиска
он не годится. Тянем свежие дневные бары прямо с BingX через ccxt.

Ищем сетап, прошедший протокол вердикта (`scripts/short_at_resistance_verdict.py`):
    цена у дневного пивота R1/R2/R3  +  ATRTrend развернулся ВНИЗ  →  ШОРТ
То есть «продать дорого» — принцип Егора, а не шорт у поддержки.

Из протокола известно, что усиливает сетап:
  • R2 сильнее R1/R3 (PF 1.99 против 1.35/1.11, безтоп10% положительный);
  • стоп >15% даёт PF 1.94 против 0.77 у стопа <4% (закон размера);
  • ОДИНОЧКА лучше кластера (PF 1.48 против 0.24) — обратно фейду.

Запуск:  python scripts/live_scan_short_at_resistance.py [--top 250]
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import ccxt  # noqa: E402

COST = 0.35
SL_LOOKBACK = 10


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


def pivots_classic(h, l, c):
    """Классические пивоты от ПРЕДЫДУЩЕГО периода (как в combinator_core)."""
    pp = (h + l + c) / 3
    return {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h,
            "R2": pp + (h - l), "S2": pp - (h - l),
            "R3": h + 2 * (pp - l), "S3": l - 2 * (h - pp)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=250, help="сколько пар по обороту")
    ap.add_argument("--near-pct", type=float, default=1.5, help="что считать «у уровня», %")
    ap.add_argument("--fresh-bars", type=int, default=3, help="разворот тренда не старше N дней")
    a = ap.parse_args()

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print("═" * 104)
    print(f"ЖИВОЙ СКАН · ШОРТ ОТ СОПРОТИВЛЕНИЯ (продать дорого) · BingX swap · дневной ТФ")
    print(f"условие: цена в пределах {a.near_pct}% от дневного R1/R2/R3 + разворот ATRTrend вниз "
          f"не старше {a.fresh_bars} баров")
    print("═" * 104)

    try:
        tickers = ex.fetch_tickers()
    except Exception as e:
        print(f"не удалось получить тикеры: {e}")
        return 1
    rows = []
    for sym, t in tickers.items():
        if not sym.endswith(":USDT"):
            continue
        qv = t.get("quoteVolume") or 0
        if qv:
            rows.append((sym, float(qv)))
    rows.sort(key=lambda x: -x[1])
    syms = [s for s, _ in rows[:a.top]]
    print(f"вселенная: {len(syms)} пар по обороту\n")

    hits = []
    checked = 0
    for i, sym in enumerate(syms, 1):
        try:
            o = ex.fetch_ohlcv(sym, timeframe="1d", limit=200)
        except Exception:
            continue
        if not o or len(o) < 80:
            continue
        d = pd.DataFrame(o, columns=["time", "open", "high", "low", "close", "volume"])
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")
        checked += 1
        tdir = atr_dir(d)
        # разворот вниз произошёл недавно?
        flip_age = None
        for k in range(1, min(a.fresh_bars + 1, len(tdir))):
            if tdir[-k] == -1 and tdir[-k - 1] == 1:
                flip_age = k - 1
                break
        if flip_age is None:
            continue
        prev = d.iloc[-2]                      # пивоты от ПРЕДЫДУЩЕГО дня
        piv = pivots_classic(float(prev.high), float(prev.low), float(prev.close))
        price = float(d.close.iloc[-1])
        best = None
        for lvl in ("R1", "R2", "R3"):
            dist = abs(price - piv[lvl]) / price * 100
            if dist <= a.near_pct and (best is None or dist < best[1]):
                best = (lvl, dist)
        if not best:
            continue
        lvl, dist = best
        sl = float(d.high.iloc[-SL_LOOKBACK - 1:].max()) * 1.001
        stop_pct = (sl - price) / price * 100
        tp = price - 2 * (sl - price)
        hits.append(dict(symbol=sym, level=lvl, dist=dist, price=price, lvl_price=piv[lvl],
                         sl=sl, tp=tp, stop_pct=stop_pct, flip_age=flip_age,
                         vol=dict(rows).get(sym, 0)))
        if i % 40 == 0:
            print(f"  … проверено {i}/{len(syms)}")
        time.sleep(ex.rateLimit / 1000)

    if not hits:
        print(f"\nпроверено {checked} пар — сетапов СЕЙЧАС нет")
        print("это нормально: по бэктесту частота ~1354 сигнала на 250 монет за 3.6 года")
        return 0

    hits.sort(key=lambda h: (h["level"] != "R2", -h["stop_pct"]))
    print(f"\n=== НАЙДЕНО {len(hits)} СЕТАПОВ (проверено {checked} пар) ===")
    print(f"{'символ':<20} {'ур':<4} {'до ур.':>7} {'цена':>12} {'стоп':>12} {'стоп%':>7} "
          f"{'цель 2R':>12} {'разв.':>6} {'оборот $':>12}")
    print("─" * 104)
    for h in hits[:30]:
        star = "⭐" if (h["level"] == "R2" and h["stop_pct"] > 15) else "  "
        print(f"{star}{h['symbol'][:18]:<18} {h['level']:<4} {h['dist']:>6.2f}% "
              f"{h['price']:>12.6g} {h['sl']:>12.6g} {h['stop_pct']:>6.1f}% "
              f"{h['tp']:>12.6g} {h['flip_age']:>5}д {h['vol']:>11,.0f}")

    r2 = [h for h in hits if h["level"] == "R2"]
    big = [h for h in hits if h["stop_pct"] > 15]
    print(f"\n⭐ = R2 + стоп >15% (лучшая ячейка протокола: PF 1.99 и 1.94)")
    print(f"   у R2: {len(r2)} · со стопом >15%: {len(big)} · "
          f"пересечение: {len([h for h in hits if h['level'] == 'R2' and h['stop_pct'] > 15])}")
    print(f"\n⚠️ Сетап НЕ прошёл OOS и форвард. 2023 у него отрицателен (PF 0.71),")
    print(f"   основной вклад дал 2025 (+9.16%). Торговать только shadow/малым размером.")
    print("═" * 104)
    return 0


if __name__ == "__main__":
    sys.exit(main())
