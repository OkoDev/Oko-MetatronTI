# -*- coding: utf-8 -*-
"""ЖИВОЙ СКАН 1h: РЕАКЦИЯ ОТ УРОВНЯ + FVG НА МЛАДШЕМ ТФ (14.08.2026, Даат).

Егор: «проверь состояние рынка и графики на 1h — реакции от уровней и наличие FVG на LTF».

Это MTF-концепция проекта: уровень и реакция на 1h, подтверждение входа на 15m/5m.
Кэш обрывается 31.07 — данные тянутся живьём с BingX.

РЕАКЦИЯ ОТ УРОВНЯ (а не пробой) определяется строго:
  • для поддержки: минимум бара заходил в зону уровня, а ЗАКРЫТИЕ вернулось ВЫШЕ уровня;
  • для сопротивления: максимум заходил в зону, а закрытие вернулось НИЖЕ.
Пробой (закрытие за уровнем) реакцией НЕ считается — это принципиально: на замерах
14.08 «шорт у поддержки» и «лонг у сопротивления» оказались momentum падающего рынка,
а не торговлей от уровня.

FVG НА LTF — свежий гэп в сторону реакции на 15m и 5m, флаг на баре ОБНАРУЖЕНИЯ
(после фикса 13.08: берётся ts_i, а не ts_left).

Запуск:  python scripts/live_1h_level_reaction_ltf_fvg.py [--top 200]
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

JUNK = re.compile(r"^(NC|FX|IDX)|EUR|GBP|JPY|XAU|XAG|OIL|SPX|NDX|META2|USD1", re.I)


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean()
    d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


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


def fvg_recent(df, window, side):
    """Свежий FVG нужной стороны в пределах window последних баров. Бар обнаружения."""
    high, low, close = df.high.values, df.low.values, df.close.values
    n = len(df)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(2, n)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(max(2, n - window), n):
        if side == "bull" and low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                return True, (high[i - 2], low[i]), n - 1 - i
        if side == "bear" and high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                return True, (high[i], low[i - 2]), n - 1 - i
    return False, None, None


def pivots(h, l, c):
    pp = (h + l + c) / 3
    return {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h, "R2": pp + (h - l),
            "S2": pp - (h - l), "R3": h + 2 * (pp - l), "S3": l - 2 * (h - pp)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--zone", type=float, default=0.8, help="ширина зоны уровня, %")
    ap.add_argument("--react-bars", type=int, default=6, help="искать реакцию в N посл. барах 1h")
    ap.add_argument("--fvg-window", type=int, default=12, help="FVG в пределах N баров LTF")
    a = ap.parse_args()

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print("═" * 118)
    print("ЖИВОЙ СКАН · 1h: РЕАКЦИЯ ОТ УРОВНЯ + FVG НА МЛАДШЕМ ТФ · BingX")
    print(f"реакция = фитиль в зону уровня ±{a.zone}%, закрытие ВЕРНУЛОСЬ (пробой не считается)")
    print("═" * 118)

    try:
        tk = ex.fetch_tickers()
    except Exception as e:
        print(f"тикеры недоступны: {e}")
        return 1
    rows = []
    for sym, t in tk.items():
        if not sym.endswith(":USDT"):
            continue
        if JUNK.search(sym.split("/")[0]):
            continue
        qv = float(t.get("quoteVolume") or 0)
        ch = t.get("percentage")
        if qv > 0:
            rows.append((sym, qv, float(ch) if ch is not None else np.nan))
    rows.sort(key=lambda x: -x[1])
    top = rows[:a.top]

    # ── СОСТОЯНИЕ РЫНКА ──
    ch = np.array([r[2] for r in top if not np.isnan(r[2])])
    print(f"\n=== СОСТОЯНИЕ РЫНКА (24ч, {len(ch)} пар) ===")
    print(f"  медиана изменения: {np.median(ch):+6.2f}%")
    print(f"  растущих: {100 * (ch > 0).mean():.0f}%   ·   падающих: {100 * (ch < 0).mean():.0f}%")
    print(f"  сильный рост >5%: {int((ch > 5).sum())}   ·   сильное падение <−5%: {int((ch < -5).sum())}")
    regime = "МЕДВЕДЬ" if np.median(ch) < -1.5 else ("БЫК" if np.median(ch) > 1.5 else "нейтраль")
    print(f"  → режим суток: {regime}")

    longs, shorts = [], []
    checked = 0
    for i, (sym, qv, _) in enumerate(top, 1):
        try:
            o1 = ex.fetch_ohlcv(sym, timeframe="1h", limit=200)
            if not o1 or len(o1) < 60:
                continue
            od = ex.fetch_ohlcv(sym, timeframe="1d", limit=10)
            o15 = ex.fetch_ohlcv(sym, timeframe="15m", limit=120)
            o5 = ex.fetch_ohlcv(sym, timeframe="5m", limit=120)
        except Exception:
            continue
        checked += 1

        def mk(o):
            d = pd.DataFrame(o, columns=["time", "open", "high", "low", "close", "volume"])
            d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
            return d.set_index("ts")
        h1, d1 = mk(o1), mk(od)
        m15 = mk(o15) if o15 and len(o15) > 30 else None
        m5 = mk(o5) if o5 and len(o5) > 30 else None
        if len(d1) < 3:
            continue

        prev = d1.iloc[-2]
        piv = pivots(float(prev.high), float(prev.low), float(prev.close))
        td = atr_dir(h1)
        w = wt(h1)
        price = float(h1.close.iloc[-1])

        # ── ПОИСК РЕАКЦИИ в последних барах 1h ──
        for k in range(1, min(a.react_bars + 1, len(h1))):
            bar = h1.iloc[-k]
            for lvl, lp in piv.items():
                zone = lp * a.zone / 100
                touched_dn = float(bar.low) <= lp + zone and float(bar.low) >= lp - zone * 3
                touched_up = float(bar.high) >= lp - zone and float(bar.high) <= lp + zone * 3
                # поддержка: фитиль вниз в зону, закрытие ВЫШЕ уровня
                if lvl.startswith("S") or lvl == "PP":
                    if touched_dn and float(bar.close) > lp:
                        okf, zn, age = (fvg_recent(m15, a.fvg_window, "bull")
                                        if m15 is not None else (False, None, None))
                        okf5, _, age5 = (fvg_recent(m5, a.fvg_window, "bull")
                                         if m5 is not None else (False, None, None))
                        if okf or okf5:
                            sl = float(h1.low.iloc[-min(k + 6, len(h1)):].min()) * 0.999
                            if sl < price:
                                longs.append(dict(sym=sym, lvl=lvl, lp=lp, price=price,
                                                  bars=k - 1, sl=sl,
                                                  sp=(price - sl) / price * 100,
                                                  f15=okf, f5=okf5, wt=w[-1],
                                                  atr="↑" if td[-1] > 0 else "↓", v=qv))
                        break
                # сопротивление: фитиль вверх в зону, закрытие НИЖЕ уровня
                if lvl.startswith("R") or lvl == "PP":
                    if touched_up and float(bar.close) < lp:
                        okf, zn, age = (fvg_recent(m15, a.fvg_window, "bear")
                                        if m15 is not None else (False, None, None))
                        okf5, _, age5 = (fvg_recent(m5, a.fvg_window, "bear")
                                         if m5 is not None else (False, None, None))
                        if okf or okf5:
                            sl = float(h1.high.iloc[-min(k + 6, len(h1)):].max()) * 1.001
                            if sl > price:
                                shorts.append(dict(sym=sym, lvl=lvl, lp=lp, price=price,
                                                   bars=k - 1, sl=sl,
                                                   sp=(sl - price) / price * 100,
                                                   f15=okf, f5=okf5, wt=w[-1],
                                                   atr="↑" if td[-1] > 0 else "↓", v=qv))
                        break
            else:
                continue
            break
        if i % 40 == 0:
            print(f"  … проверено {i}/{len(top)}")
        time.sleep(ex.rateLimit / 1000)

    def dump(title, hits, want_atr):
        print(f"\n=== {title}: {len(hits)} ===")
        if not hits:
            print("  нет")
            return
        hits.sort(key=lambda h: (h["bars"], -h["v"]))
        print(f"  {'символ':<14} {'ур':<3} {'уровень':>11} {'цена':>11} {'стоп%':>6} "
              f"{'назад':>6} {'FVG15':>6} {'FVG5':>5} {'WT':>7} {'ATR':>4} {'оборот$':>12}")
        for h in hits[:22]:
            fit = "⭐" if h["atr"] == want_atr else "  "
            print(f"  {fit}{h['sym'].split('/')[0][:11]:<11} {h['lvl']:<3} {h['lp']:>11.6g} "
                  f"{h['price']:>11.6g} {h['sp']:>5.1f}% {h['bars']:>5}ч "
                  f"{'да' if h['f15'] else '—':>6} {'да' if h['f5'] else '—':>5} "
                  f"{h['wt']:>7.1f} {h['atr']:>4} {h['v']:>11,.0f}")

    dump("ЛОНГ: реакция ОТ ПОДДЕРЖКИ + bull FVG на LTF", longs, "↑")
    dump("ШОРТ: реакция ОТ СОПРОТИВЛЕНИЯ + bear FVG на LTF", shorts, "↓")

    print(f"\nпроверено пар: {checked}")
    print("⭐ = ATR-тренд 1h согласован со стороной сделки (по замерам 14.08 согласие тренда —")
    print("     единственное, что давало лифт; перепроданность у уровня давала ловлю ножа).")
    print("═" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
