# -*- coding: utf-8 -*-
"""ГИПОТЕЗА ЕГОРА: ЛОНГ ОТ НЕДЕЛЬНОГО S3 + ДИВЕРГЕНЦИЯ + WT OS (14.08.2026, Даат).

Егор (14.08, по GRT): «рынок падает и готовится к развороту, скоро будут сетапы в покупку.
GRT от недельного S3 отскок — с дивергенцией и WT OS».

Это ПРОТИВОРЕЧИТ моему замеру: голый `near S3 1W + atr_cross_up` → LONG дал
PF 0.32 / −19.10%/сд — худшая ячейка всей таблицы (ловля падающего ножа).
НО там был один триггер. Егор добавляет ДВА условия, которых в замере не было:
бычью дивергенцию и WT в перепроданности. Это другая конфлюэнция.

Проверяется послойно, чтобы видеть вклад КАЖДОГО условия:
  0. база LONG (вход на каждом баре)          — контроль
  1. near S 1W (голый уровень)
  2. + WT OS
  3. + дивергенция (bull, RSI или WT)
  4. + WT OS И дивергенция (полная связка Егора)
  5. та же связка, но БЕЗ уровня — чтобы понять, уровень ли даёт вклад

Разрезы: уровень (S1/S2/S3) · год · режим года · размер стопа · охват монет · хрупкость.
Отдельно печатается «режим года» (медианная годовая доходность вселенной), потому что
гипотеза Егора — про РАЗВОРОТ рынка, и в падающем окне лонг-отскок обязан проигрывать.

Запуск:  python scripts/long_at_support_confluence.py [--coins 250]
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


def sim_long(df):
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out = np.full(n, np.nan); sp = np.full(n, np.nan)
    for i in range(SL_LOOKBACK + 2, n - 2):
        e = C[i]
        end = min(i + TTL, n - 1)
        fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
        if len(fl) == 0:
            continue
        sl = L[i - SL_LOOKBACK:i + 1].min() * 0.999
        if sl >= e:
            continue
        sp[i] = (e - sl) / e * 100
        tp = e + TP_R * (e - sl)
        hs, ht = fl <= sl, fh >= tp
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        out[i] = ((sl - e) if (js <= jt and js < 10 ** 9)
                  else ((tp - e) if jt < 10 ** 9 else (C[end] - e))) / e * 100
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


def show(nm, s, base=None, ind="  "):
    if not s or s["n"] < 20:
        print(f"{ind}  {nm:<34} — мало данных")
        return
    lift = f"{s['mean'] - base['mean']:>+7.2f}" if base else "      —"
    mark = "🟢" if s["mean"] > 0 else "  "
    print(f"{ind}{mark}{nm:<34} n={s['n']:>6} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
          f"{s['mean']:>+8.2f}%/сд лифт {lift} безтоп10% {s['frag']:>+8.0f}")


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

    print("═" * 116)
    print(f"ЛОНГ ОТ ПОДДЕРЖКИ + ДИВЕРГЕНЦИЯ + WT OS (гипотеза Егора) · 1d · {len(syms)} монет "
          f"с {a.since}")
    print(f"TP={TP_R}R TTL={TTL}б · косты {COST}% · послойная проверка вклада каждого условия")
    print("═" * 116)

    L = {k: {"net": [], "yr": [], "sym": [], "sp": [], "lvl": []}
         for k in ("lvl", "lvl_wt", "lvl_div", "full", "nolvl_full",
                   "os_div_trendup", "os_div_trenddown")}
    base = []
    yearly_ret = {}          # для режима года

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
        r, sp = sim_long(d)
        ok = ~np.isnan(r)
        base.extend((r[ok] - COST).tolist())
        yrs = d.index.year.values
        for y, g in d.groupby(d.index.year):
            if len(g) > 30:
                yearly_ret.setdefault(y, []).append(
                    float(g.close.iloc[-1] / g.close.iloc[0] - 1) * 100)

        def arr(col):
            if col not in F.columns:
                return np.zeros(len(d), dtype=bool)
            try:
                return np.asarray(F[col].fillna(False), dtype=bool)
            except Exception:
                return np.zeros(len(d), dtype=bool)

        wt_os = arr("wt_os_1d")
        div = (arr("rsi_div_bull_regular_1d") | arr("rsi_div_bull_hidden_1d")
               | arr("wt_div_bull_regular_1d") | arr("wt_div_bull_hidden_1d"))

        def push(key, mask, lvl_tag):
            m = mask & ok
            if not m.any():
                return
            idx = np.flatnonzero(m)
            L[key]["net"].extend((r[idx] - COST).tolist())
            L[key]["yr"].extend(yrs[idx].tolist())
            L[key]["sym"].extend([sym] * len(idx))
            L[key]["sp"].extend(sp[idx].tolist())
            L[key]["lvl"].extend([lvl_tag] * len(idx))

        near_any = np.zeros(len(d), dtype=bool)
        for lvl in ("S1", "S2", "S3"):
            nr = arr(f"pivot_near_{lvl}_1W")
            near_any |= nr
            push("lvl", nr, lvl)
            push("lvl_wt", nr & wt_os, lvl)
            push("lvl_div", nr & div, lvl)
            push("full", nr & wt_os & div, lvl)
        push("nolvl_full", (~near_any) & wt_os & div, "—")
        # НОВОЕ 14.08 (наблюдение с графиков): перепроданность в ПАДАЮЩЕМ тренде =
        # продолжение падения (нож), в боковике/растущем = разворот. Режим как разделитель.
        atr_up_f = arr("atr_up_1d")
        push("os_div_trendup", wt_os & div & atr_up_f, "—")
        push("os_div_trenddown", wt_os & div & (~atr_up_f), "—")
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)}")

    b = stat(base)
    print(f"\n=== РЕЖИМ ГОДА (медианная доходность монеты за год) ===")
    for y in sorted(yearly_ret):
        v = np.array(yearly_ret[y])
        print(f"  {y}: медиана {np.median(v):+7.1f}% · растущих {100 * (v > 0).mean():>4.0f}% "
              f"({len(v)} монет)  → {'БЫК' if np.median(v) > 10 else ('МЕДВЕДЬ' if np.median(v) < -10 else 'нейтраль')}")

    print(f"\n=== ПОСЛОЙНО: вклад каждого условия (LONG) ===")
    show("0. база (каждый бар)", b, None, "")
    show("1. near S 1W (голый уровень)", stat(L["lvl"]["net"]), b, "")
    show("2. + WT OS", stat(L["lvl_wt"]["net"]), b, "")
    show("3. + дивергенция", stat(L["lvl_div"]["net"]), b, "")
    show("4. ПОЛНАЯ СВЯЗКА (уровень+WT OS+див)", stat(L["full"]["net"]), b, "")
    show("5. WT OS+див БЕЗ уровня", stat(L["nolvl_full"]["net"]), b, "")
    print()
    show("6. WT OS+див при ATRTrend ВВЕРХ", stat(L["os_div_trendup"]["net"]), b, "")
    show("7. WT OS+див при ATRTrend ВНИЗ", stat(L["os_div_trenddown"]["net"]), b, "")

    for key, title in (("os_div_trendup", "WT OS+ДИВ при ТРЕНДЕ ВВЕРХ"),
                       ("full", "ПОЛНАЯ СВЯЗКА"), ("lvl_div", "уровень + дивергенция")):
        net = np.array(L[key]["net"]); yr = np.array(L[key]["yr"])
        sy = np.array(L[key]["sym"]); sp = np.array(L[key]["sp"]); lv = np.array(L[key]["lvl"])
        if len(net) < 30:
            continue
        print(f"\n=== {title}: РАЗРЕЗЫ ===")
        print("  по уровню:")
        for l_ in ("S1", "S2", "S3"):
            show(l_, stat(net[lv == l_]), b)
        print("  по годам:")
        for y in sorted(set(yr.tolist())):
            show(str(y), stat(net[yr == y]), b)
        print("  по размеру стопа:")
        for lo, hi in ((0, 8), (8, 15), (15, 100)):
            show(f"стоп {lo}-{hi}%", stat(net[(sp > lo) & (sp <= hi)]), b)
        per = pd.Series(net).groupby(pd.Series(sy)).mean()
        print(f"  охват монет: плюс на {int((per > 0).sum())} из {len(per)} "
              f"({100 * (per > 0).mean():.0f}%)")

    print("\n" + "═" * 116)
    print("Гипотеза Егора про РАЗВОРОТ рынка: если лонг-отскок работает только в бычьи/нейтральные")
    print("годы, то его включение = ставка на смену режима, и это надо признать явно.")
    print("═" * 116)
    return 0


if __name__ == "__main__":
    sys.exit(main())
