# -*- coding: utf-8 -*-
"""ЛОНГ-КАНДИДАТЫ × MTF-ДИВЕРГЕНЦИИ (14.08.2026, Даат).

Егор: «55 лонгов проверь на наличие MTF дивергенций».

Берём тех же кандидатов, что нашёл `live_1h_level_reaction_ltf_fvg.py`
(реакция от поддержки на 1h + bull FVG на младшем ТФ), и для каждого считаем
бычьи дивергенции на 5m / 15m / 1h / 4h / 1d — RSI и WT, regular и hidden.

Почему именно дивергенции: аудит лага 13.08 показал, что ВСЕ дивергенции
(RSI и WT, regular и hidden) — причинные, лаг 0, ни одного смещённого события.
В отличие от FVG (был смещён на 2 бара) и OTE-зоны (лаг >20) им можно верить.

Замер 13.08 на 1d: дивергенции дают эдж, но только медвежьи в медвежьем режиме
(WT hidden bear PF 1.75, RSI hidden bear 1.53). Бычьи в 2025-26 были в минусе.
Поэтому MTF-дивергенция здесь — проверка СИЛЫ разворота, а не готовый сигнал.

Запуск:  python scripts/live_long_mtf_divergence.py [--top 120]
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
from core.calculators.combinator_core import compute_flags  # noqa: E402

JUNK = re.compile(r"^(NC|FX|IDX)|EUR|GBP|JPY|XAU|XAG|OIL|SPX|NDX|META2|USD1", re.I)
TFS = ["5m", "15m", "1h", "4h", "1d"]
LIMITS = {"5m": 300, "15m": 300, "1h": 300, "4h": 260, "1d": 220}
DIVS = ["rsi_div_bull_regular", "rsi_div_bull_hidden",
        "wt_div_bull_regular", "wt_div_bull_hidden"]


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
    high, low, close = df.high.values, df.low.values, df.close.values
    n = len(df)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(2, n)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(max(2, n - window), n):
        if side == "bull" and low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                return True
    return False


def pivots(h, l, c):
    pp = (h + l + c) / 3
    return {"PP": pp, "S1": 2 * pp - h, "S2": pp - (h - l), "S3": l - 2 * (h - pp)}


def mk(o):
    d = pd.DataFrame(o, columns=["time", "open", "high", "low", "close", "volume"])
    d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
    return d.set_index("ts")[["open", "high", "low", "close", "volume"]]


def div_on(df, tf, lookback):
    """Какие бычьи дивергенции сработали в последние lookback баров."""
    out = []
    try:
        F = compute_flags(df, tf, include_pivots=False)
    except Exception:
        return out
    for nm in DIVS:
        col = f"{nm}_{tf}"
        if col not in F.columns:
            continue
        try:
            arr = np.asarray(F[col].fillna(False), dtype=bool)
        except Exception:
            continue
        idx = np.flatnonzero(arr[-lookback:])
        if len(idx):
            age = lookback - 1 - int(idx[-1])
            out.append((nm.replace("_div_bull_", "-").replace("rsi", "RSI").replace("wt", "WT"),
                        age))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=120)
    ap.add_argument("--zone", type=float, default=0.8)
    ap.add_argument("--react-bars", type=int, default=6)
    ap.add_argument("--div-look", type=int, default=10, help="дивергенция в N посл. барах")
    a = ap.parse_args()

    ex = ccxt.bingx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    print("═" * 122)
    print("ЛОНГ-КАНДИДАТЫ (реакция от поддержки 1h + bull FVG на LTF) × MTF-ДИВЕРГЕНЦИИ")
    print(f"дивергенции: RSI и WT, regular и hidden, в пределах {a.div_look} последних баров ТФ")
    print("детекторы дивергенций проверены на причинность (аудит 13.08: лаг 0)")
    print("═" * 122)

    try:
        tk = ex.fetch_tickers()
    except Exception as e:
        print(f"тикеры недоступны: {e}")
        return 1
    rows = []
    for sym, t in tk.items():
        if not sym.endswith(":USDT") or JUNK.search(sym.split("/")[0]):
            continue
        qv = float(t.get("quoteVolume") or 0)
        if qv > 0:
            rows.append((sym, qv))
    rows.sort(key=lambda x: -x[1])
    top = rows[:a.top]

    cands = []
    for i, (sym, qv) in enumerate(top, 1):
        try:
            h1 = mk(ex.fetch_ohlcv(sym, timeframe="1h", limit=200))
            d1 = mk(ex.fetch_ohlcv(sym, timeframe="1d", limit=10))
            m15 = mk(ex.fetch_ohlcv(sym, timeframe="15m", limit=120))
        except Exception:
            continue
        if len(h1) < 60 or len(d1) < 3:
            continue
        prev = d1.iloc[-2]
        piv = pivots(float(prev.high), float(prev.low), float(prev.close))
        price = float(h1.close.iloc[-1])
        td = atr_dir(h1)
        hit = None
        for k in range(1, min(a.react_bars + 1, len(h1))):
            bar = h1.iloc[-k]
            for lvl, lp in piv.items():
                zone = lp * a.zone / 100
                if float(bar.low) <= lp + zone and float(bar.low) >= lp - zone * 3 \
                        and float(bar.close) > lp:
                    if fvg_recent(m15, 12, "bull"):
                        sl = float(h1.low.iloc[-min(k + 6, len(h1)):].min()) * 0.999
                        if sl < price:
                            hit = dict(sym=sym, lvl=lvl, lp=lp, price=price, bars=k - 1,
                                       sp=(price - sl) / price * 100,
                                       atr="↑" if td[-1] > 0 else "↓", v=qv)
                    break
            if hit:
                break
        if hit:
            cands.append(hit)
        if i % 40 == 0:
            print(f"  … отбор {i}/{len(top)} · найдено {len(cands)}")
        time.sleep(ex.rateLimit / 1000)

    print(f"\nлонг-кандидатов найдено: {len(cands)}\n")
    if not cands:
        return 0

    res = []
    for j, c in enumerate(cands, 1):
        sym = c["sym"]
        per_tf = {}
        for tf in TFS:
            try:
                d = mk(ex.fetch_ohlcv(sym, timeframe=tf, limit=LIMITS[tf]))
            except Exception:
                continue
            if len(d) < 60:
                continue
            per_tf[tf] = div_on(d, tf, a.div_look)
            time.sleep(ex.rateLimit / 1000)
        n_tf = sum(1 for tf, v in per_tf.items() if v)
        n_div = sum(len(v) for v in per_tf.values())
        res.append((c, per_tf, n_tf, n_div))
        if j % 15 == 0:
            print(f"  … дивергенции {j}/{len(cands)}")

    res.sort(key=lambda x: (-x[2], -x[3], -x[0]["v"]))
    print(f"\n{'символ':<13} {'ур':<3} {'стоп%':>6} {'ATR':>4} {'ТФ':>3} "
          f"{'5m':>10} {'15m':>10} {'1h':>10} {'4h':>10} {'1d':>10} {'оборот$':>12}")
    print("─" * 122)
    for c, per_tf, n_tf, n_div in res:
        cells = []
        for tf in TFS:
            v = per_tf.get(tf) or []
            if not v:
                cells.append("—")
            else:
                kinds = sorted({("h" if "hidden" in k else "r") for k, _ in v})
                cells.append("+".join(kinds) + f"({min(x[1] for x in v)})")
        mark = "⭐" if (n_tf >= 3 and c["atr"] == "↑") else ("🟢" if n_tf >= 3 else "  ")
        print(f"{mark}{c['sym'].split('/')[0][:11]:<11} {c['lvl']:<3} {c['sp']:>5.1f}% "
              f"{c['atr']:>4} {n_tf:>3} " + " ".join(f"{x:>10}" for x in cells) +
              f" {c['v']:>11,.0f}")

    with3 = [r for r in res if r[2] >= 3]
    with3up = [r for r in with3 if r[0]["atr"] == "↑"]
    print(f"\nитого: кандидатов {len(res)} · с дивергенцией на ≥3 ТФ: {len(with3)} · "
          f"из них с ATR-трендом вверх: {len(with3up)}")
    print("r = regular, h = hidden, в скобках — сколько баров назад сработала")
    print("\n⚠️ По замеру 13.08 на 1d БЫЧЬИ дивергенции в 2025-26 были убыточны")
    print("   (RSI hidden bull PF 0.70, WT hidden bull 0.58). MTF-совпадение — признак")
    print("   силы разворота, но статистикой текущего режима оно НЕ подтверждено.")
    print("═" * 122)
    return 0


if __name__ == "__main__":
    sys.exit(main())
