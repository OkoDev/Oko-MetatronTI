# -*- coding: utf-8 -*-
"""ЖИВОЙ СКАН: СМЕНА ATR-ТРЕНДА + FVG (механика Егора) — 14.08.2026, Даат.

Механика подтверждена бэктестом (`scripts/reversal_atr_fvg_wtmedian.py`, 250 монет, 1d):
  SHORT (смена ATR вниз + bear FVG): PF 1.36, лифт +2.70, 2025 PF 1.74 / 2026 PF 1.81,
      безтоп10% ПОЛОЖИТЕЛЬНЫЙ, охват 168 из 249 монет.
  LONG  (смена ATR вверх + bull FVG): 2023 PF 1.46 / 2024 PF 1.21 — работал в бычьи годы.
Механика одна, направление задаёт режим рынка.

Кэш обрывается на 31.07.2026 — тянем свежие дневные бары с BingX.
Мусорные инструменты (форекс/синтетика вроде NCFXEUR2GBP, NCSKMETA2USD) отсеиваются.

Запуск:  python scripts/live_scan_atr_flip_fvg.py [--top 250] [--fresh 3]
"""
from __future__ import annotations

import argparse
import re
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
# мусор в вселенной BingX: форекс, индексы, синтетика — не крипта
JUNK = re.compile(r"^(NC|FX|IDX)|EUR|GBP|JPY|XAU|XAG|OIL|SPX|NDX|META2|USD1", re.I)


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


def fvg_bars(df, n_last=8):
    """Свежие FVG за последние n_last баров. Флаг на баре ОБНАРУЖЕНИЯ (фикс 13.08)."""
    high, low, close = df.high.values, df.low.values, df.close.values
    n = len(df)
    bull = np.zeros(n, dtype=bool); bear = np.zeros(n, dtype=bool)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(2, n)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(max(2, n - n_last), n):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                bull[i] = True
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                bear[i] = True
    return bull, bear


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=250)
    ap.add_argument("--fresh", type=int, default=3, help="смена тренда не старше N баров")
    ap.add_argument("--fvg-window", type=int, default=8, help="FVG в пределах N баров")
    a = ap.parse_args()

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print("═" * 108)
    print(f"ЖИВОЙ СКАН · СМЕНА ATR-ТРЕНДА + FVG · дневной ТФ · BingX swap")
    print(f"смена тренда не старше {a.fresh} баров · FVG в сторону сделки в пределах "
          f"{a.fvg_window} баров")
    print("═" * 108)

    try:
        tk = ex.fetch_tickers()
    except Exception as e:
        print(f"тикеры недоступны: {e}")
        return 1
    rows = []
    for sym, t in tk.items():
        if not sym.endswith(":USDT"):
            continue
        core = sym.split("/")[0]
        if JUNK.search(core):
            continue
        qv = float(t.get("quoteVolume") or 0)
        if qv > 0:
            rows.append((sym, qv))
    rows.sort(key=lambda x: -x[1])
    syms = [s for s, _ in rows[:a.top]]
    vol = dict(rows)
    print(f"вселенная: {len(syms)} крипто-пар (мусор отфильтрован)\n")

    longs, shorts = [], []
    checked = 0
    for i, sym in enumerate(syms, 1):
        try:
            o = ex.fetch_ohlcv(sym, timeframe="1d", limit=220)
        except Exception:
            continue
        if not o or len(o) < 90:
            continue
        d = pd.DataFrame(o, columns=["time", "open", "high", "low", "close", "volume"])
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")
        checked += 1
        td = atr_dir(d)
        bull, bear = fvg_bars(d, a.fvg_window)
        price = float(d.close.iloc[-1])

        flip_up = flip_dn = None
        for k in range(1, min(a.fresh + 1, len(td))):
            if td[-k] == 1 and td[-k - 1] == -1 and flip_up is None:
                flip_up = k - 1
            if td[-k] == -1 and td[-k - 1] == 1 and flip_dn is None:
                flip_dn = k - 1

        if flip_up is not None and bull[-a.fvg_window:].any():
            sl = float(d.low.iloc[-SL_LOOKBACK - 1:].min()) * 0.999
            if sl < price:
                sp = (price - sl) / price * 100
                longs.append(dict(sym=sym, price=price, sl=sl, sp=sp,
                                  tp=price + 2 * (price - sl), age=flip_up, v=vol.get(sym, 0)))
        if flip_dn is not None and bear[-a.fvg_window:].any():
            sl = float(d.high.iloc[-SL_LOOKBACK - 1:].max()) * 1.001
            if sl > price:
                sp = (sl - price) / price * 100
                shorts.append(dict(sym=sym, price=price, sl=sl, sp=sp,
                                   tp=price - 2 * (sl - price), age=flip_dn, v=vol.get(sym, 0)))
        if i % 50 == 0:
            print(f"  … проверено {i}/{len(syms)}")
        time.sleep(ex.rateLimit / 1000)

    def dump(title, hits, note):
        print(f"\n=== {title}: {len(hits)} шт ===")
        if not hits:
            print("  сетапов нет")
            return
        print(f"  {note}")
        hits.sort(key=lambda h: -h["sp"])
        print(f"  {'символ':<20} {'цена':>12} {'стоп':>12} {'стоп%':>7} {'цель 2R':>12} "
              f"{'смена':>6} {'оборот $':>13}")
        for h in hits[:25]:
            star = "⭐" if h["sp"] > 15 else "  "
            print(f"  {star}{h['sym'].split('/')[0][:17]:<17} {h['price']:>12.6g} "
                  f"{h['sl']:>12.6g} {h['sp']:>6.1f}% {h['tp']:>12.6g} {h['age']:>5}д "
                  f"{h['v']:>12,.0f}")

    dump("SHORT: смена ATR вниз + bear FVG", shorts,
         "бэктест: PF 1.36 · 2025 PF 1.74 · 2026 PF 1.81 · охват 67% монет")
    dump("LONG: смена ATR вверх + bull FVG", longs,
         "бэктест: 2023 PF 1.46 · 2024 PF 1.21 · в 2025-26 НЕ работал (ждём смены режима)")

    print(f"\nпроверено пар: {checked}")
    print("⭐ = стоп >15% (в бэктесте лучшая зона: SHORT PF 1.40 против 0.85-0.90 у тесных)")
    print("\n⚠️ Механика НЕ прошла OOS и форвард. Лонги сейчас против режима — по данным")
    print("   2025-26 они убыточны; включать их = ставка на разворот рынка, а не на статистику.")
    print("═" * 108)
    return 0


if __name__ == "__main__":
    sys.exit(main())
