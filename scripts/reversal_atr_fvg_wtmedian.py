# -*- coding: utf-8 -*-
"""РАЗВОРОТ: СМЕНА ATR-ТРЕНДА + FVG + МЕДИАНА WT ПО ТФ (14.08.2026, Даат).

Указания Егора 14.08:
  • «проверяй СМЕНУ тренда ATR и наличие FVG как подтверждение направления движения»
  • «смотри медиану WT на разных ТФ»

Это его MTF-концепция в чистом виде: перепроданность подтверждается на нескольких
таймфреймах сразу (медиана WT), разворот подтверждается СМЕНОЙ режима (atr_cross_up,
а не просто atr_up), а направление — свежим FVG в сторону сделки.

Почему это осмысленно (из наблюдения по графикам 14.08): фильтр по одной лишь
перепроданности выдаёт падающие ножи — из 16 монет с WT OS на 1h+4h тринадцать были
в TREND_DOWN. Перепроданность в падении = продолжение, в развороте = вход.
Замер это подтвердил: WT OS + дивергенция при ATRTrend ВВЕРХ дали в 2024 PF 1.81,
при ATRTrend вниз — минус.

Проверяется послойно, ЛОНГ (разворот вверх), на дневном:
  0. база
  1. WT OS (1d)
  2. + медиана WT по 1h/4h/1d ниже порога  (MTF-перепроданность)
  3. + СМЕНА ATR-тренда вверх              (триггер разворота)
  4. + bull FVG                            (подтверждение направления)
  5. полная связка
  6. зеркало для SHORT (WT OB + медиана + смена вниз + bear FVG)

Разрезы: год · режим года · размер стопа · охват монет · хрупкость · лифт над базой.

Запуск:  python scripts/reversal_atr_fvg_wtmedian.py [--coins 250] [--wt-med -45]
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

from core.calculators.combinator_core import compute_flags, wavetrend  # noqa: E402

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
                mean=float(v.mean()), frag=float(s[:-cut].sum()))


def show(nm, s, base=None, ind="  ", minn=20):
    if not s or s["n"] < minn:
        print(f"{ind}  {nm:<38} — мало данных ({0 if not s else s['n']})")
        return
    lift = f"{s['mean'] - base['mean']:>+7.2f}" if base else "      —"
    mark = "🟢" if s["mean"] > 0 else "  "
    print(f"{ind}{mark}{nm:<38} n={s['n']:>6} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"{s['mean']:>+8.2f}%/сд лифт {lift} безтоп10% {s['frag']:>+8.0f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--wt-med", type=float, default=-45.0,
                    help="порог медианы WT по ТФ для лонга (зеркально для шорта)")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 120)
    print(f"РАЗВОРОТ: СМЕНА ATR-ТРЕНДА + FVG + МЕДИАНА WT ПО ТФ · 1d · {len(syms)} монет "
          f"с {a.since}")
    print(f"порог медианы WT: лонг ≤ {a.wt_med}, шорт ≥ {-a.wt_med} · TP={TP_R}R TTL={TTL}б · "
          f"косты {COST}%")
    print("═" * 120)

    KEYS = ("os", "os_med", "os_med_cross", "os_med_cross_fvg", "cross_only", "cross_fvg",
            "sh_full", "sh_cross_fvg")
    A = {k: {"net": [], "yr": [], "sym": [], "sp": []} for k in KEYS}
    base = {"long": [], "short": []}

    for si, sym in enumerate(syms, 1):
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 3000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        h1 = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        h4 = h1.resample("4h").agg(agg).dropna()
        d1 = h1.resample("1D").agg(agg).dropna()
        if len(d1) < 200 or len(h4) < 400:
            continue
        try:
            F = compute_flags(d1, "1d", include_pivots=False)
        except Exception:
            continue

        # ── МЕДИАНА WT ПО ТФ (указание Егора) — HTF выравнивается на дневной индекс ──
        # wavetrend возвращает pd.Series
        wt_d = pd.Series(np.asarray(wavetrend(d1)), index=d1.index)
        def wt_on_daily(df_, rule_shift):
            s_ = pd.Series(np.asarray(wavetrend(df_)), index=df_.index)
            s_.index = s_.index + rule_shift          # только с ЗАКРЫТОГО бара
            return s_.reindex(d1.index, method="ffill")
        wt_1h = wt_on_daily(h1, pd.Timedelta(hours=1))
        wt_4h = wt_on_daily(h4, pd.Timedelta(hours=4))
        wt_med = pd.concat([wt_1h, wt_4h, wt_d], axis=1).median(axis=1).values

        rl, spl = sim(d1, "long")
        rs, sps = sim(d1, "short")
        okl, oks = ~np.isnan(rl), ~np.isnan(rs)
        base["long"].extend((rl[okl] - COST).tolist())
        base["short"].extend((rs[oks] - COST).tolist())
        yrs = d1.index.year.values

        def arr(col):
            if col not in F.columns:
                return np.zeros(len(d1), dtype=bool)
            try:
                return np.asarray(F[col].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d1), dtype=bool)

        wt_os, wt_ob = arr("wt_os_1d"), arr("wt_ob_1d")
        cross_up, cross_dn = arr("atr_cross_up_1d"), arr("atr_cross_down_1d")
        fvg_b, fvg_s = arr("bull_fvg_1d"), arr("bear_fvg_1d")
        med_lo = wt_med <= a.wt_med
        med_hi = wt_med >= -a.wt_med

        def push(key, mask, side):
            r, sp, ok = (rl, spl, okl) if side == "long" else (rs, sps, oks)
            m = mask & ok
            if not m.any():
                return
            idx = np.flatnonzero(m)
            A[key]["net"].extend((r[idx] - COST).tolist())
            A[key]["yr"].extend(yrs[idx].tolist())
            A[key]["sym"].extend([sym] * len(idx))
            A[key]["sp"].extend(sp[idx].tolist())

        push("os", wt_os, "long")
        push("os_med", wt_os & med_lo, "long")
        push("os_med_cross", wt_os & med_lo & cross_up, "long")
        push("os_med_cross_fvg", wt_os & med_lo & cross_up & fvg_b, "long")
        push("cross_only", cross_up, "long")
        push("cross_fvg", cross_up & fvg_b, "long")
        push("sh_full", wt_ob & med_hi & cross_dn & fvg_s, "short")
        push("sh_cross_fvg", cross_dn & fvg_s, "short")
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    bl, bs = stat(base["long"]), stat(base["short"])
    print(f"\nБАЗА: LONG {bl['mean']:+.2f}% PF {bl['pf']:.2f} (n={bl['n']}) · "
          f"SHORT {bs['mean']:+.2f}% PF {bs['pf']:.2f} (n={bs['n']})")

    print(f"\n=== ЛОНГ-РАЗВОРОТ ПОСЛОЙНО ===")
    show("0. база (каждый бар)", bl, None, "")
    show("1. WT OS (1d)", stat(A["os"]["net"]), bl, "")
    show("2. + медиана WT по 1h/4h/1d", stat(A["os_med"]["net"]), bl, "")
    show("3. + СМЕНА ATR-тренда вверх", stat(A["os_med_cross"]["net"]), bl, "")
    show("4. + bull FVG (полная связка)", stat(A["os_med_cross_fvg"]["net"]), bl, "")
    print()
    show("контроль: только смена ATR вверх", stat(A["cross_only"]["net"]), bl, "")
    show("контроль: смена ATR + FVG", stat(A["cross_fvg"]["net"]), bl, "")

    print(f"\n=== ЗЕРКАЛО SHORT ===")
    show("полная связка (OB+мед+смена вниз+FVG)", stat(A["sh_full"]["net"]), bs, "")
    show("смена ATR вниз + bear FVG", stat(A["sh_cross_fvg"]["net"]), bs, "")

    for key, title, b in (("os_med_cross_fvg", "ЛОНГ: ПОЛНАЯ СВЯЗКА", bl),
                          ("cross_fvg", "ЛОНГ: смена ATR + FVG", bl),
                          ("sh_cross_fvg", "SHORT: смена ATR вниз + FVG", bs)):
        net = np.array(A[key]["net"])
        if len(net) < 40:
            continue
        yr = np.array(A[key]["yr"]); sy = np.array(A[key]["sym"]); sp = np.array(A[key]["sp"])
        print(f"\n=== {title}: РАЗРЕЗЫ ===")
        print("  по годам:")
        for y in sorted(set(yr.tolist())):
            show(str(y), stat(net[yr == y]), b, "  ", minn=15)
        print("  по размеру стопа:")
        for lo, hi in ((0, 8), (8, 15), (15, 100)):
            show(f"стоп {lo}-{hi}%", stat(net[(sp > lo) & (sp <= hi)]), b, "  ", minn=15)
        per = pd.Series(net).groupby(pd.Series(sy)).mean()
        print(f"  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
              f"({100 * (per > 0).mean():.0f}%)")

    print("\n" + "═" * 120)
    print("Каждый слой добавляется к предыдущему — видно, что реально даёт вклад,")
    print("а что просто режет выборку. Контрольные строки показывают вклад БЕЗ перепроданности.")
    print("═" * 120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
