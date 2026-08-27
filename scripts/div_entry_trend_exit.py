# -*- coding: utf-8 -*-
"""МЕХАНИКА ЕГОРА: ВХОД ПО ДИВЕРГЕНЦИИ 1h → ВЫХОД ПО СМЕНЕ ATR-ТРЕНДА (13.08.2026).

Егор (скрин GRT/USDT 1h): «дивергенция на часовике даёт отскок 4.36%, скрытая медвежья
от зоны даёт шорт 2.73%. Если даже после такой дивергенции заходить по смене ATR-тренда,
всё равно будет пару процентов плюсом. Зашли на часовике и держим до победного,
пока тренд не сменится».

Он прав в том, что ЭТО НЕ МЕРИЛОСЬ. Все замеры сессии — выход по TP=2R/SL с TTL 24ч.
Здесь выход другой: ТРЕЙЛИНГ ПО РЕЖИМУ (смена направления ATRTrend), удержание до конца.
Горизонт-скан это косвенно подтвердил: на 1d TTL 24→192 баров поднимает +0.158% → +1.950%.

Детекторы взяты ЧИСТЫЕ (аудит лага 13.08: дивергенции RSI/WT и ATRTrend — лаг 0,
переписывания нет). FVG/OTE/overlap сюда НЕ входят — они чинились сегодня.

Сравниваются 5 схем выхода на одних и тех же входах:
  A. смена ATR-тренда (механика Егора, без стопа)
  B. смена ATR-тренда + структурный стоп
  C. TP=2R / SL (как мерили весь день) — контроль
  D. TP=2R / SL, но TTL 192 бара вместо 24
  E. только структурный стоп, держим пока не выбьет (без цели)

Метрика — % net с костами 0.35%. Разрезы: сторона · год · тип дивергенции · охват монет.

Запуск:  python scripts/div_entry_trend_exit.py [--coins 40] [--tf 1h]
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
COST = 0.35
SL_LOOKBACK = 10
MAX_HOLD = 500          # предохранитель, чтобы не висеть вечно


def atr_dir(df, period=43, factor=1.25):
    """ATRTrend направление (эталон проекта: atr_period=43, factor=1.25)."""
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


def run_trade(H, L, C, tdir, i, side, mode):
    """Возврат в % от входа (без костов) + сколько баров держали."""
    e = C[i]
    n = len(C)
    end = min(i + MAX_HOLD, n - 1)
    if side == "long":
        sl = L[max(0, i - SL_LOOKBACK):i + 1].min() * 0.999
        if sl >= e:
            return None, 0
    else:
        sl = H[max(0, i - SL_LOOKBACK):i + 1].max() * 1.001
        if sl <= e:
            return None, 0
    risk = abs(e - sl)
    tp = e + 2 * risk if side == "long" else e - 2 * risk
    ttl_cap = {"C": 24, "D": 192}.get(mode, MAX_HOLD)
    want = 1 if side == "long" else -1

    for j in range(i + 1, end + 1):
        hit_sl = (L[j] <= sl) if side == "long" else (H[j] >= sl)
        hit_tp = (H[j] >= tp) if side == "long" else (L[j] <= tp)
        flip = tdir[j] != want                      # смена режима на закрытии бара j

        if mode in ("B", "E") and hit_sl:
            return (sl - e) / e * 100 * (1 if side == "long" else -1), j - i
        if mode in ("C", "D") and hit_sl:
            return (sl - e) / e * 100 * (1 if side == "long" else -1), j - i
        if mode in ("C", "D") and hit_tp:
            return (tp - e) / e * 100 * (1 if side == "long" else -1), j - i
        if mode in ("A", "B") and flip:
            return (C[j] - e) / e * 100 * (1 if side == "long" else -1), j - i
        if mode in ("C", "D") and (j - i) >= ttl_cap:
            return (C[j] - e) / e * 100 * (1 if side == "long" else -1), j - i
    return (C[end] - e) / e * 100 * (1 if side == "long" else -1), end - i


def stat(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    s = np.sort(v); cut = max(1, int(len(s) * 0.10))
    return dict(n=len(v), wr=100 * (v > 0).mean(),
                pf=(v[v > 0].sum() / neg if neg > 0 else 99.0),
                mean=float(v.mean()), med=float(np.median(v)),
                frag=float(s[:-cut].sum()), total=float(v.sum()))


MODES = {
    "A": "смена ATR-тренда (Егор, без стопа)",
    "B": "смена ATR-тренда + структурный стоп",
    "C": "TP=2R / SL, TTL 24б  (контроль дня)",
    "D": "TP=2R / SL, TTL 192б",
    "E": "только стоп, держим до выбива",
}
DIVS = {
    "rsi_div_bull_regular": ("long", "RSI regular bull"),
    "rsi_div_bear_regular": ("short", "RSI regular bear"),
    "rsi_div_bull_hidden": ("long", "RSI hidden bull"),
    "rsi_div_bear_hidden": ("short", "RSI hidden bear"),
    "wt_div_bull_regular": ("long", "WT regular bull"),
    "wt_div_bear_regular": ("short", "WT regular bear"),
    "wt_div_bull_hidden": ("long", "WT hidden bull"),
    "wt_div_bear_hidden": ("short", "WT hidden bear"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=40)
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--tf", type=str, default="1h")
    ap.add_argument("--wait", type=int, default=24,
                    help="сколько баров ждать смену ATR-тренда после дивергенции")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    # 1d в кэше отдельной таблицей не лежит — грузим 1h и агрегируем
    src_tf = "1h" if a.tf == "1d" else a.tf
    agg_rule = "1D" if a.tf == "1d" else None
    min_bars = 3000 if src_tf != a.tf else 3000
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe=? AND time>=? "
        "GROUP BY symbol HAVING n>? ORDER BY n DESC LIMIT ?",
        (src_tf, t0, min_bars, a.coins)).fetchall()]
    con.close()

    print("═" * 116)
    print(f"ВХОД ПО ДИВЕРГЕНЦИИ → ВЫХОД ПО СМЕНЕ ATR-ТРЕНДА · {a.tf} · {len(syms)} монет "
          f"с {a.since} · косты {COST}%")
    print("детекторы чистые (аудит лага: дивергенции и ATRTrend — лаг 0)")
    print("═" * 116)

    # acc[mode] и acc_div[(mode, div)] и cuts
    acc = defaultdict(list)
    acc_div = defaultdict(list)
    bars_held = defaultdict(list)
    cuts = defaultdict(lambda: {"net": [], "yr": [], "sym": [], "side": []})

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe=? AND time>=? ORDER BY time",
                        c, params=(sym, src_tf, t0))
        c.close()
        if len(d) < 1000:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
        if agg_rule:
            d = d.resample(agg_rule).agg({"open": "first", "high": "max", "low": "min",
                                          "close": "last", "volume": "sum"}).dropna()
        if len(d) < 200:
            continue
        try:
            F = compute_flags(d, a.tf, include_pivots=False)
        except Exception:
            continue
        tdir = atr_dir(d)
        H, L, C = d.high.values, d.low.values, d.close.values
        yrs = d.index.year.values

        for col, (side, label) in DIVS.items():
            key = f"{col}_{a.tf}"
            if key not in F.columns:
                continue
            try:
                arr = np.asarray(F[key].fillna(False), dtype=bool)
            except Exception:
                continue
            idx = np.flatnonzero(arr)
            idx = idx[(idx > 60) & (idx < len(d) - 5)]
            last = -10 ** 9
            want = 1 if side == "long" else -1
            for i0 in idx:
                if i0 - last < 6:         # кулдаун, чтобы одна дивергенция не считалась 5 раз
                    continue
                last = i0
                # 🔑 МЕХАНИКА ЕГОРА: дивергенция — это КОНТЕКСТ, а вход — по СМЕНЕ
                # ATR-тренда в нужную сторону ПОСЛЕ неё (в окне ожидания).
                # Прошлая версия входила на самой дивергенции — и, поскольку дивергенция
                # идёт ПРОТИВ тренда, выход по смене срабатывал через 1-2 бара.
                i = None
                for k in range(int(i0) + 1, min(int(i0) + 1 + a.wait, len(d) - 2)):
                    if tdir[k] == want and tdir[k - 1] != want:
                        i = k
                        break
                if i is None:
                    continue
                for mode in MODES:
                    r, hb = run_trade(H, L, C, tdir, int(i), side, mode)
                    if r is None:
                        continue
                    net = r - COST
                    acc[mode].append(net)
                    acc_div[(mode, label)].append(net)
                    bars_held[mode].append(hb)
                    ck = cuts[mode]
                    ck["net"].append(net); ck["yr"].append(int(yrs[int(i)]))
                    ck["sym"].append(sym); ck["side"].append(side)
        if si % 10 == 0:
            print(f"  … монет обработано: {si}/{len(syms)}")

    print(f"\n=== СХЕМЫ ВЫХОДА НА ОДНИХ И ТЕХ ЖЕ ВХОДАХ ===")
    print(f"{'схема':<40} {'n':>7} {'WR':>7} {'PF':>7} {'%/сд net':>11} "
          f"{'медиана':>9} {'держим':>9} {'безтоп10%':>11}")
    print("─" * 116)
    for mode, name in MODES.items():
        s = stat(acc[mode])
        if not s:
            continue
        hb = np.median(bars_held[mode]) if bars_held[mode] else 0
        mark = "🟢" if s["mean"] > 0 else "  "
        print(f"{mark}{name:<38} {s['n']:>7} {s['wr']:>6.1f}% {s['pf']:>7.2f} "
              f"{s['mean']:>+10.3f}% {s['med']:>+8.3f}% {hb:>8.0f}б {s['frag']:>+10.1f}")

    best = max(MODES, key=lambda m: (stat(acc[m]) or {"mean": -99})["mean"])
    print(f"\n=== ЛУЧШАЯ СХЕМА «{MODES[best]}» — РАЗРЕЗЫ ===")
    ck = cuts[best]
    net = np.array(ck["net"]); yr = np.array(ck["yr"])
    sy = np.array(ck["sym"]); sd = np.array(ck["side"])
    for side in ("long", "short"):
        s = stat(net[sd == side])
        if s:
            flag = "🟢" if s["mean"] > 0 else "🔴"
            print(f"  {flag} {side.upper():<6} n={s['n']:>6} WR {s['wr']:>5.1f}% "
                  f"PF {s['pf']:>5.2f} {s['mean']:>+8.3f}%/сд")
    line = "  по годам: "
    for y in sorted(set(yr.tolist())):
        s = stat(net[yr == y])
        if s and s["n"] >= 50:
            line += f"{y}: {s['mean']:+.2f}%(PF{s['pf']:.2f})  "
    print(line)
    per = pd.Series(net).groupby(pd.Series(sy)).mean()
    print(f"  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
          f"({100 * (per > 0).mean():.0f}%)")

    print(f"\n=== ПО ТИПУ ДИВЕРГЕНЦИИ (схема «{MODES[best]}») ===")
    print(f"{'дивергенция':<22} {'n':>7} {'WR':>7} {'PF':>7} {'%/сд net':>11} {'медиана':>10}")
    rows = []
    for (m, label), v in acc_div.items():
        if m != best:
            continue
        s = stat(v)
        if s and s["n"] >= 50:
            rows.append((label, s))
    for label, s in sorted(rows, key=lambda x: -x[1]["mean"]):
        mark = "🟢" if s["mean"] > 0 else "  "
        print(f"{mark}{label:<20} {s['n']:>7} {s['wr']:>6.1f}% {s['pf']:>7.2f} "
              f"{s['mean']:>+10.3f}% {s['med']:>+9.3f}%")

    print("\n" + "═" * 116)
    print("Вход один и тот же — меняется ТОЛЬКО выход. Разница между схемами = цена")
    print("решения «где выходить», а не «где входить».")
    print("═" * 116)
    return 0


if __name__ == "__main__":
    sys.exit(main())
