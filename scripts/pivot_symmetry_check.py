# -*- coding: utf-8 -*-
"""ПРОВЕРКА ТОРГОВОГО СМЫСЛА: ПИВОТЫ × СТОРОНА, ЗЕРКАЛО S↔R (14.08.2026, Даат).

Егор поймал: «`pivot_near_S3_1W + atr_cross_down_1d` — ты шортишь ВНИЗУ, а не наверху
где R3. Трейдинг — это купить дёшево чтобы продать дорого, и наоборот».

Он прав, и ошибка методологическая: в `all_factors_1d_scan.py` факторы без явной стороны
в имени мерились в ОБЕ стороны, а в таблицу попадала лучшая по результату. Это отбор
по максимуму, а не проверка гипотезы. «Шорт у сильной поддержки» = продать дёшево;
такой результат означает «в 2023-25 поддержки пробивало вниз», то есть momentum
падающего рынка, а не разворотную торговлю.

Здесь КАЖДЫЙ уровень мерится в ОБЕ стороны и печатаются ОБЕ, плюс проверка зеркала:
  • у поддержки (S1-S3) осмыслен ЛОНГ (отскок) либо ШОРТ на пробое;
  • у сопротивления (R1-R3) осмыслен ШОРТ (отбой) либо ЛОНГ на пробое.
Если механика настоящая, зеркало обязано работать симметрично. Если плюс только внизу
и только в шорт — это эпоха, а не эдж.

Запуск:  python scripts/pivot_symmetry_check.py [--coins 150]
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
TP_R = 2.0
TTL = 192
SL_LOOKBACK = 10


def sim(df, side):
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out = np.full(n, np.nan)
    for i in range(SL_LOOKBACK + 2, n - 2):
        e = C[i]
        end = min(i + TTL, n - 1)
        fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
        if len(fl) == 0:
            continue
        if side == "long":
            sl = L[i - SL_LOOKBACK:i + 1].min() * 0.999
            if sl >= e:
                continue
            tp = e + TP_R * (e - sl)
            hs, ht = fl <= sl, fh >= tp
            lo = (sl - e) / e * 100; hi_ = (tp - e) / e * 100
            tail = (C[end] - e) / e * 100
        else:
            sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
            if sl <= e:
                continue
            tp = e - TP_R * (sl - e)
            hs, ht = fh >= sl, fl <= tp
            lo = (e - sl) / e * 100; hi_ = (e - tp) / e * 100
            tail = (e - C[end]) / e * 100
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        out[i] = lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)
    return out


def stat(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    s = np.sort(v); cut = max(1, int(len(s) * 0.10))
    return dict(n=len(v), wr=100 * (v > 0).mean(),
                pf=(v[v > 0].sum() / neg if neg > 0 else 99.0),
                mean=float(v.mean()), frag=float(s[:-cut].sum()))


LEVELS = ["S3", "S2", "S1", "PP", "R1", "R2", "R3"]
TRIG = {"atr_cross_down_1d": "short-триггер (разворот тренда вниз)",
        "atr_cross_up_1d": "long-триггер (разворот тренда вверх)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=150)
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--min-n", type=int, default=60)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 120)
    print(f"ПИВОТЫ × СТОРОНА · ЗЕРКАЛО S↔R · {len(syms)} монет с {a.since} · 1d · "
          f"TP={TP_R}R TTL={TTL}б · косты {COST}%")
    print("каждый уровень мерится в ОБЕ стороны — обе печатаются, лучшая НЕ выбирается")
    print("═" * 120)

    acc = defaultdict(lambda: defaultdict(list))    # acc[key][side] = список net
    base = {"long": [], "short": []}

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                        "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                        c, params=(sym, t0))
        c.close()
        if len(d) < 3000:
            continue
        d["ts"] = pd.to_datetime(d.time, unit="ms", utc=True)
        d = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
        d = d.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()
        if len(d) < 200:
            continue
        try:
            F = compute_flags(d, "1d", include_pivots=True)
        except Exception:
            continue
        rl, rs = sim(d, "long"), sim(d, "short")
        okl, oks = ~np.isnan(rl), ~np.isnan(rs)
        base["long"].extend((rl[okl] - COST).tolist())
        base["short"].extend((rs[oks] - COST).tolist())

        def arr(col):
            if col not in F.columns:
                return None
            try:
                return np.asarray(F[col].fillna(False), dtype=bool)
            except Exception:
                return None

        for lvl in LEVELS:
            for tf_ in ("1D", "1W"):
                near = arr(f"pivot_near_{lvl}_{tf_}")
                if near is None:
                    continue
                for trig, _ in TRIG.items():
                    t_ = arr(trig)
                    if t_ is None:
                        continue
                    m = near & t_
                    if not m.any():
                        continue
                    key = f"near {lvl} {tf_} + {trig.replace('_1d', '')}"
                    acc[key]["long"].extend((rl[m & okl] - COST).tolist())
                    acc[key]["short"].extend((rs[m & oks] - COST).tolist())
        if si % 30 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    bl, bs = stat(base["long"]), stat(base["short"])
    print(f"\nбаза 1d: LONG {bl['mean']:+.3f}% PF {bl['pf']:.2f} · "
          f"SHORT {bs['mean']:+.3f}% PF {bs['pf']:.2f}")

    print(f"\n{'сетап':<42} {'LONG':>32} {'SHORT':>32}")
    print(f"{'':<42} {'n / PF / %сд':>32} {'n / PF / %сд':>32}")
    print("─" * 120)
    for key in sorted(acc.keys()):
        sl_, ss_ = stat(acc[key]["long"]), stat(acc[key]["short"])
        if not sl_ and not ss_:
            continue
        if (sl_ or {"n": 0})["n"] < a.min_n and (ss_ or {"n": 0})["n"] < a.min_n:
            continue

        def fmt(s, b):
            if not s or s["n"] < a.min_n:
                return f"{'—':>32}"
            mark = "🟢" if s["mean"] > 0 else "  "
            return f"{mark}{s['n']:>6} PF{s['pf']:>5.2f} {s['mean']:>+8.2f}%(+{s['mean'] - b['mean']:>6.2f})"
        print(f"{key:<42} {fmt(sl_, bl):>32} {fmt(ss_, bs):>32}")

    print("\n" + "═" * 120)
    print("ЧИТАТЬ ТАК: у поддержки (S) осмыслен ЛОНГ-отскок, у сопротивления (R) — ШОРТ-отбой.")
    print("Если плюс только 'шорт у S' и 'лонг у R' — это ПРОБОЙ (momentum), и тогда зеркало")
    print("обязано быть симметричным. Плюс только внизу и только в шорт = эпоха, а не эдж.")
    print("═" * 120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
