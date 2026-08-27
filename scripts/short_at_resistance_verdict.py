# -*- coding: utf-8 -*-
"""ШОРТ ОТ СОПРОТИВЛЕНИЯ — ПОЛНЫЙ ПРОТОКОЛ ВЕРДИКТА (14.08.2026, Даат).

Егор: «ты шортишь внизу а покупаешь наверху! А НУЖНО НАОБОРОТ! Трейдинг — это купить
дёшево чтобы продать дорого, и наоборот».

Он поймал системную ошибку: факторы без стороны в имени мерились в обе стороны,
и в таблицу попадала лучшая по результату. Так «шорт у поддержки S3» (продать дёшево)
дал PF 3.63 — но это был momentum падающего рынка, а не эдж: тот же шорт у S3
прибылен и при развороте тренда ВВЕРХ (PF 2.97), то есть триггер вообще не важен.

После разворота в осмысленную сторону остаётся: ШОРТ У СОПРОТИВЛЕНИЯ при развороте
тренда вниз (продать дорого). Лучший — R2 1D: PF 1.97, лифт +3.31 п.п. над базой.
ЛОНГ у поддержки работает хуже (1 из 6): у S3 1W он даёт PF 0.32 / −19.1% —
ловля падающего ножа.

Здесь сетап проверяется по полному протоколу: год · режим года · размер стопа ·
кластер · ликвидность · хрупкость · охват монет + контроль на базе и зеркало.

Запуск:  python scripts/short_at_resistance_verdict.py [--coins 250]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

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
    out = np.full(n, np.nan); sp = np.full(n, np.nan)
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
            sp[i] = (e - sl) / e * 100
            tp = e + TP_R * (e - sl)
            hs, ht = fl <= sl, fh >= tp
            lo, hi_, tail = (sl - e) / e * 100, (tp - e) / e * 100, (C[end] - e) / e * 100
        else:
            sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
            if sl <= e:
                continue
            sp[i] = (sl - e) / e * 100
            tp = e - TP_R * (sl - e)
            hs, ht = fh >= sl, fl <= tp
            lo, hi_, tail = (e - sl) / e * 100, (e - tp) / e * 100, (e - C[end]) / e * 100
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        out[i] = lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)
    return out, sp


def stat(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    s = np.sort(v); cut = max(1, int(len(s) * 0.10))
    return dict(n=len(v), wr=100 * (v > 0).mean(),
                pf=(v[v > 0].sum() / neg if neg > 0 else 99.0),
                mean=float(v.mean()), med=float(np.median(v)), frag=float(s[:-cut].sum()))


def line(nm, s, base=None, ind="  "):
    if not s or s["n"] < 25:
        return
    lift = f"{s['mean'] - base['mean']:>+7.2f}" if base else "      —"
    mark = "🟢" if s["mean"] > 0 else "  "
    print(f"{ind}{mark}{nm:<30} n={s['n']:>6} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"{s['mean']:>+8.2f}%/сд  лифт {lift}  безтоп10% {s['frag']:>+9.1f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2023)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 118)
    print(f"ШОРТ ОТ СОПРОТИВЛЕНИЯ (продать дорого) · 1d · {len(syms)} монет с {a.since} · "
          f"TP={TP_R}R TTL={TTL}б · косты {COST}%")
    print("═" * 118)

    S = {"net": [], "yr": [], "sym": [], "sp": [], "lvl": [], "vol": [], "cl": []}
    Lg = {"net": [], "yr": [], "sym": [], "sp": [], "lvl": []}
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
        rl, spl = sim(d, "long")
        rs, sps = sim(d, "short")
        okl, oks = ~np.isnan(rl), ~np.isnan(rs)
        base["long"].extend((rl[okl] - COST).tolist())
        base["short"].extend((rs[oks] - COST).tolist())
        yrs = d.index.year.values
        dv = (d.close * d.volume).rolling(30).median().values     # долларовый оборот

        def arr(col):
            if col not in F.columns:
                return np.zeros(len(d), dtype=bool)
            try:
                return np.asarray(F[col].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d), dtype=bool)

        down = arr("atr_cross_down_1d")
        up = arr("atr_cross_up_1d")
        for lvl in ("R1", "R2", "R3"):
            m = arr(f"pivot_near_{lvl}_1D") & down & oks
            if m.any():
                idx = np.flatnonzero(m)
                S["net"].extend((rs[idx] - COST).tolist())
                S["yr"].extend(yrs[idx].tolist()); S["sym"].extend([sym] * len(idx))
                S["sp"].extend(sps[idx].tolist()); S["lvl"].extend([lvl] * len(idx))
                S["vol"].extend(dv[idx].tolist())
                S["cl"].extend([int(np.sum(np.abs(idx - i) <= 3) - 1) for i in idx])
        for lvl in ("S1", "S2", "S3"):        # зеркало: лонг у поддержки
            m = arr(f"pivot_near_{lvl}_1D") & up & okl
            if m.any():
                idx = np.flatnonzero(m)
                Lg["net"].extend((rl[idx] - COST).tolist())
                Lg["yr"].extend(yrs[idx].tolist()); Lg["sym"].extend([sym] * len(idx))
                Lg["sp"].extend(spl[idx].tolist()); Lg["lvl"].extend([lvl] * len(idx))
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    bl, bs = stat(base["long"]), stat(base["short"])
    print(f"\nБАЗА 1d: LONG {bl['mean']:+.3f}% PF {bl['pf']:.2f} (n={bl['n']}) · "
          f"SHORT {bs['mean']:+.3f}% PF {bs['pf']:.2f} (n={bs['n']})")

    net = np.array(S["net"]); yr = np.array(S["yr"]); sy = np.array(S["sym"])
    sp = np.array(S["sp"]); lv = np.array(S["lvl"]); vol = np.array(S["vol"])
    cl = np.array(S["cl"])
    print(f"\n=== ШОРТ у R1/R2/R3 (1D) при развороте тренда вниз ===")
    line("ВСЕ УРОВНИ ВМЕСТЕ", stat(net), bs, "")
    print(f"\n  по уровню:")
    for l_ in ("R1", "R2", "R3"):
        line(l_, stat(net[lv == l_]), bs)
    print(f"\n  по годам:")
    for y in sorted(set(yr.tolist())):
        line(str(y), stat(net[yr == y]), bs)
    print(f"\n  по размеру стопа:")
    for lo, hi in ((0, 4), (4, 8), (8, 15), (15, 100)):
        line(f"стоп {lo}-{hi}%", stat(net[(sp > lo) & (sp <= hi)]), bs)
    print(f"\n  одиночка против кластера:")
    line("одиночка", stat(net[cl == 0]), bs)
    line("кластер ≥2", stat(net[cl >= 1]), bs)
    print(f"\n  ликвидность (медиана оборота):")
    if len(vol) > 50:
        q = np.nanmedian(vol)
        line("ликвидная половина", stat(net[vol >= q]), bs)
        line("неликвидная", stat(net[vol < q]), bs)
    per = pd.Series(net).groupby(pd.Series(sy)).mean()
    print(f"\n  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
          f"({100 * (per > 0).mean():.0f}%)")

    nl = np.array(Lg["net"]); yl = np.array(Lg["yr"]); ll = np.array(Lg["lvl"])
    print(f"\n=== ЗЕРКАЛО: ЛОНГ у S1/S2/S3 (1D) при развороте вверх ===")
    line("ВСЕ УРОВНИ ВМЕСТЕ", stat(nl), bl, "")
    for l_ in ("S1", "S2", "S3"):
        line(l_, stat(nl[ll == l_]), bl)
    print(f"\n  по годам:")
    for y in sorted(set(yl.tolist())):
        line(str(y), stat(nl[yl == y]), bl)

    print("\n" + "═" * 118)
    print("лифт = сколько сетап добавляет к входу на каждом баре ТОЙ ЖЕ стороны.")
    print("Сетап с плюсом, но нулевым лифтом просто повторяет дрейф рынка, а не даёт эдж.")
    print("═" * 118)
    return 0


if __name__ == "__main__":
    sys.exit(main())
