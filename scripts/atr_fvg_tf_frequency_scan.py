# -*- coding: utf-8 -*-
"""ЧАСТОТА И МЛАДШИЕ ТФ: ГДЕ БОЛЬШЕ R В ДЕНЬ (14.08.2026, Даат).

Егор: «переходи к поиску частоты и меньшим ТФ для сокращения стопа».

🔑 СМЕНА МЕТРИКИ. Раньше ТФ сравнивались в «% от цены», но при ФИКСИРОВАННОМ риске
на сделку это некорректно: стоп 15% и стоп 3% при риске 1% депозита дают одинаковые
2% депозита на ходе 2R. Разница только в КОСТАХ:
    0.35% от цены = 2.3% риска при стопе 15%
    0.35% от цены = 11.7% риска при стопе 3%
Поэтому честная метрика — R ПОСЛЕ КОСТОВ: (profit% − COST) / stop%.
Итог дня = R на сделку × частота. Это и решает, окупает ли частота младших ТФ их косты.

Механика — подтверждённая конструкция Егора (`reversal_atr_fvg_wtmedian.py`):
    СМЕНА ATR-тренда + FVG в сторону сделки.
На 1d она дала SHORT PF 1.36, 2025 PF 1.74 / 2026 PF 1.81, охват 67% монет.

Считается два класса:
  A. механика НА КАЖДОМ ТФ отдельно (15m/1h/4h/1d) — частота против костов;
  B. MTF: сигнал на СТАРШЕМ ТФ, вход и стоп на МЛАДШЕМ (сокращение стопа —
     изначальная концепция проекта: сетап на 1h/4h, вход на 15m/5m).

Запуск:  python scripts/atr_fvg_tf_frequency_scan.py [--coins 150]
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

DB = "ohlcv_cache.db"
COST = 0.35   # перекрывается --cost
TP_R = 2.0
SL_LOOKBACK = 10
TFS = ["15m", "1h", "4h", "1d"]
RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
BAR_H = {"15m": 0.25, "1h": 1.0, "4h": 4.0, "1d": 24.0}
# горизонт удержания ~8 суток в барах своего ТФ
TTL = {"15m": 768, "1h": 192, "4h": 48, "1d": 8}
# множители горизонта: 8 суток × [0.5, 1, 3, 8] → от 4 суток до ~2 месяцев
TTL_MULT = [0.5, 1.0, 3.0, 8.0]
# окно входа на младшем ТФ после сигнала старшего (в барах младшего)
ENTRY_WIN = {"15m": 96, "1h": 24, "4h": 6}


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
    """FVG на баре ОБНАРУЖЕНИЯ (после фикса 13.08: f[4], а не f[0])."""
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


def run(df, i, side, ttl):
    """Возврат: (profit% от цены, stop% от цены). SL проверяется первым."""
    H, L, C = df.high.values, df.low.values, df.close.values
    n = len(C)
    if i < SL_LOOKBACK + 1 or i >= n - 2:
        return None
    e = C[i]
    end = min(i + ttl, n - 1)
    fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
    if len(fl) == 0:
        return None
    if side == "long":
        sl = L[i - SL_LOOKBACK:i + 1].min() * 0.999
        if sl >= e:
            return None
        sp = (e - sl) / e * 100
        tp = e + TP_R * (e - sl)
        hs, ht = fl <= sl, fh >= tp
        lo, hi_, tail = (sl - e) / e * 100, (tp - e) / e * 100, (C[end] - e) / e * 100
    else:
        sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
        if sl <= e:
            return None
        sp = (sl - e) / e * 100
        tp = e - TP_R * (sl - e)
        hs, ht = fh >= sl, fl <= tp
        lo, hi_, tail = (e - sl) / e * 100, (e - tp) / e * 100, (e - C[end]) / e * 100
    if sp <= 0 or sp > 40:                # потолок: стоп >40% — брак, не торгуемо
        return None
    js = int(np.argmax(hs)) if hs.any() else 10 ** 9
    jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
    pr = lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)
    return pr, sp


def stat(rows, days):
    """rows = список (profit%, stop%). Метрики и в %, и в R после костов."""
    if not rows:
        return None
    pr = np.array([r[0] for r in rows], float)
    sp = np.array([r[1] for r in rows], float)
    net_pct = pr - COST
    net_r = net_pct / sp                       # 🔑 результат в единицах РИСКА
    neg = abs(net_pct[net_pct < 0].sum())
    pf = net_pct[net_pct > 0].sum() / neg if neg > 0 else 99.0
    freq = len(rows) / max(days, 1)
    return dict(n=len(rows), wr=100 * (net_pct > 0).mean(), pf=pf,
                pct=float(net_pct.mean()), r=float(net_r.mean()),
                stop=float(np.median(sp)), freq=freq,
                r_day=float(net_r.mean()) * freq,
                cost_share=100 * COST / max(float(np.median(sp)), 1e-9))


def line(nm, s):
    if not s or s["n"] < 40:
        print(f"  {nm:<26} — мало данных ({0 if not s else s['n']})")
        return
    mark = "🟢" if s["r_day"] > 0 else "  "
    print(f"{mark}{nm:<26} n={s['n']:>6} стоп {s['stop']:>5.2f}% косты={s['cost_share']:>4.0f}% "
          f"WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} {s['pct']:>+7.2f}%/сд "
          f"{s['r']:>+6.3f}R/сд {s['freq']:>6.2f}сд/дн {s['r_day']:>+7.3f}R/день")


def main() -> int:
    global COST
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=150)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--cost", type=float, default=0.35,
                    help="косты за круг, %: 0.35 комиссия · 0.79 с фактическим исполнением")
    a = ap.parse_args()
    COST = a.cost

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' AND time>=? "
        "GROUP BY symbol HAVING n>8000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 126)
    print(f"ЧАСТОТА × ТФ · механика «смена ATR-тренда + FVG» · {len(syms)} монет с {a.since}")
    print(f"🔑 метрика R = (profit% − {COST}%) / stop% — сравнение ТФ при ФИКСИРОВАННОМ риске")
    print("═" * 126)

    A = defaultdict(list)          # A[(tf, side)] — механика на своём ТФ
    B = defaultdict(list)          # B[(htf, ltf, side)] — сигнал старший, вход младший
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
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        bars = {"15m": m15}
        for tf in ("1h", "4h", "1d"):
            bars[tf] = m15.resample(RULE[tf]).agg(agg).dropna()
        days = max(days, (m15.index.max() - m15.index.min()).days)

        sig = {}
        for tf in TFS:
            d = bars[tf]
            if len(d) < 300:
                continue
            td = atr_dir(d)
            bull, bear = fvg_flags(d)
            up = np.zeros(len(d), dtype=bool); dn = np.zeros(len(d), dtype=bool)
            for i in range(1, len(d)):
                if td[i] == 1 and td[i - 1] == -1:
                    up[i] = True
                elif td[i] == -1 and td[i - 1] == 1:
                    dn[i] = True
            # FVG в сторону сделки в пределах 8 баров ДО сигнала (только прошлое)
            def recent(flag, i, w=8):
                lo = max(0, i - w)
                return flag[lo:i + 1].any()
            long_i = [i for i in np.flatnonzero(up) if recent(bull, i)]
            short_i = [i for i in np.flatnonzero(dn) if recent(bear, i)]
            sig[tf] = (long_i, short_i)
            # ── A: вход на своём ТФ, СЕТКА горизонтов удержания ──
            for side, idxs in (("long", long_i), ("short", short_i)):
                for mult in TTL_MULT:
                    ttl = max(4, int(TTL[tf] * mult))
                    for i in idxs:
                        res = run(d, int(i), side, ttl)
                        if res:
                            A[(tf, side, mult)].append(res)

        # ── B: сигнал на старшем ТФ, вход и стоп на МЛАДШЕМ ──
        for htf in ("1d", "4h", "1h"):
            if htf not in sig:
                continue
            for ltf in ("4h", "1h", "15m"):
                if BAR_H[ltf] >= BAR_H[htf] or ltf not in bars:
                    continue
                dl = bars[ltf]
                if len(dl) < 500:
                    continue
                pos = dl.index
                for side, idxs in (("long", sig[htf][0]), ("short", sig[htf][1])):
                    for i in idxs:
                        ts = bars[htf].index[i] + pd.Timedelta(hours=BAR_H[htf])
                        j0 = int(pos.searchsorted(ts))
                        if j0 <= SL_LOOKBACK or j0 >= len(dl) - 3:
                            continue
                        # вход на первом баре младшего ТФ после закрытия бара старшего
                        res = run(dl, j0, side, TTL[ltf])
                        if res:
                            B[(htf, ltf, side)].append(res)
        if si % 25 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    print(f"\nокно: {days} дней\n")
    print("=== A. МЕХАНИКА НА СВОЁМ ТФ · СЕТКА ГОРИЗОНТА УДЕРЖАНИЯ ===")
    for side in ("short", "long"):
        print(f"\n  --- {side.upper()} ---")
        for tf in TFS:
            for mult in TTL_MULT:
                dsut = TTL[tf] * mult * BAR_H[tf] / 24.0
                line(f"{tf} · держим ~{dsut:.0f}сут", stat(A[(tf, side, mult)], days))
            print()

    print(f"\n=== B. MTF: СИГНАЛ НА СТАРШЕМ → ВХОД НА МЛАДШЕМ (сокращение стопа) ===")
    for side in ("short", "long"):
        print(f"\n  --- {side.upper()} ---")
        for htf in ("1d", "4h", "1h"):
            for ltf in ("4h", "1h", "15m"):
                if BAR_H[ltf] >= BAR_H[htf]:
                    continue
                s = stat(B[(htf, ltf, side)], days)
                if s and s["n"] >= 40:
                    line(f"{htf} → {ltf}", s)

    print("\n" + "═" * 126)
    print("R/день — итоговая метрика: сколько единиц риска приносит день на всей вселенной.")
    print("«косты» = доля костов в стопе. Чем меньше ТФ, тем выше доля и тем больше")
    print("частота должна её перекрыть.")
    print("═" * 126)
    return 0


if __name__ == "__main__":
    sys.exit(main())
