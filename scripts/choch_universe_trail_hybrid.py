# -*- coding: utf-8 -*-
"""ГИПОТЕЗЫ РОЯ: ВСЕЛЕННАЯ · ТРЕЙЛИНГ · ГИБРИДНОЕ ИСПОЛНЕНИЕ (18.08.2026, Даат).

Опрос роя (7 моделей, 18.08) дал 6 консенсусных гипотез. Комбинации и частичные
выходы считаются в `choch_combo_and_exits.py`. Здесь — три оставшиеся:

  1. ОТБОР ВСЕЛЕННОЙ (консенсус 5/7): ликвидность, волатильность (ATR%),
     корреляция с BTC. Гипотеза: мусорные пары портят и статистику, и fill-rate.
  2. ТРЕЙЛИНГ ПО СТРУКТУРЕ (консенсус 5/7): после прохода половины пути двигать
     стоп за экстремум последних N баров, вместо фиксированного стопа за origin.
  3. ГИБРИДНОЕ ИСПОЛНЕНИЕ (2/7, но самая практичная): лимит исполняется лишь
     в 45% случаев — остальные сигналы теряются. Если у сетапа сильный фильтр
     (PF 1.84), возможно выгоднее войти ПО РЫНКУ и заплатить налог 0.44%,
     получив 100% исполнения. Считается прямое сравнение:
        лимит  = 0.35% косты, но берём только заполненные (45%)
        market = 0.79% косты, зато берутся ВСЕ сломы (100%)

Всё на IS/OOS половинах вселенной; докладываются OOS-числа.
Механика зафиксирована: swing-CHoCH → структурная нога → откат 0.236 → волна C ×1.0.

Запуск:  python scripts/choch_universe_trail_hybrid.py [--coins 250]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.smc.oko_sm_engine import run_structure  # noqa: E402

DB = "ohlcv_cache.db"
COST_LIMIT, COST_MARKET = 0.35, 0.79
TTL, WAIT = 96, 12
PB, K = 0.236, 1.0
TRAIL_BARS = 6          # трейлинг за экстремум N баров


def split_of(sym: str) -> str:
    return "IS" if int(hashlib.md5(sym.encode()).hexdigest()[:8], 16) % 2 == 0 else "OOS"


def st_(net, days=None):
    net = np.asarray(net, float)
    if len(net) < 60:
        return None
    neg = abs(net[net < 0].sum())
    s = np.sort(net); cut = max(1, int(len(s) * 0.10))
    o = dict(n=len(net), wr=100 * (net > 0).mean(),
             pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
             mean=float(net.mean()), frag=float(s[:-cut].sum()))
    if days:
        o["fd"] = len(net) / max(days, 1)
    return o


def line(nm, s, base=None, days=None):
    if not s:
        print(f"    {nm:<46} — мало данных")
        return
    d = f"{s['pf'] - base['pf']:>+6.2f}" if base else "      "
    mark = "🟢" if (s["wr"] > 53 and s["pf"] > 1.2) else ("💰" if s["pf"] > 1.1 else "  ")
    fd = f"{s.get('fd', 0):>5.2f}сд/дн" if days else ""
    print(f"{mark}{nm:<46} n={s['n']:>5} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} {d} "
          f"{s['mean']:>+7.2f}%/сд {fd} безтоп10% {s['frag']:>+8.1f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2024)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    # BTC как эталон корреляции
    btc = None
    for cand in ("BTC/USDT", "BTC/USDT:USDT"):
        b = pd.read_sql("SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe='1h' "
                        "AND time>=? ORDER BY time", con, params=(cand, t0))
        if len(b) > 1000:
            b["ts"] = pd.to_datetime(b.time, unit="ms", utc=True)
            btc = b.set_index("ts")["close"].pct_change()
            break
    con.close()

    print("═" * 126)
    print(f"ГИПОТЕЗЫ РОЯ · вселенная · трейлинг · гибридное исполнение · SHORT · "
          f"{len(syms)} монет с {a.since}")
    print(f"BTC для корреляции: {'найден' if btc is not None else 'НЕ найден'}")
    print("═" * 126)

    R = []
    days = 1
    for si, sym in enumerate(syms, 1):
        grp = split_of(sym)
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        raw = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache "
                          "WHERE symbol=? AND timeframe='1h' AND time>=? ORDER BY time",
                          c, params=(sym, t0))
        c.close()
        if len(raw) < 3000:
            continue
        raw["ts"] = pd.to_datetime(raw.time, unit="ms", utc=True)
        d = raw.set_index("ts")[["open", "high", "low", "close", "volume"]]
        dd = d.reset_index(drop=True)
        days = max(days, (d.index.max() - d.index.min()).days)
        try:
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)
        # характеристики монеты (для отбора вселенной)
        dv = float((d.close * d.volume).median())            # медианный оборот за бар
        tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                        (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
        atr_pct = float((tr.ewm(alpha=1 / 43, adjust=False).mean() / d.close * 100).median())
        corr = np.nan
        if btc is not None:
            j = pd.concat([d.close.pct_change().rename("a"), btc.rename("b")], axis=1).dropna()
            if len(j) > 500:
                corr = float(j["a"].corr(j["b"]))

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal or ev.bull:      # только SHORT
                continue
            i = int(ev.i)
            if i < 60 or i >= n - TTL - WAIT - 2:
                continue
            leg = legs[i]
            if not leg or leg["trend"] == "long":
                continue
            origin, extreme = float(leg["origin"]), float(leg["extreme"])
            A_len = abs(extreme - origin)
            if A_len <= 0:
                continue

            # ── ВАРИАНТ MARKET: вход сразу на баре слома, стоп за origin ──
            e_mkt = float(C[i])
            sl = origin * 1.001
            if sl > e_mkt:
                sp_m = (sl - e_mkt) / e_mkt * 100
                if 0 < sp_m <= 25:
                    tp_m = e_mkt - A_len * K
                    end = min(i + TTL, n - 1)
                    fl, fh = L[i + 1:end + 1], H[i + 1:end + 1]
                    if len(fl):
                        hs, ht = fh >= sl, fl <= tp_m
                        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
                        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
                        pr = ((e_mkt - sl) if (js <= jt and js < 10 ** 9)
                              else ((e_mkt - tp_m) if jt < 10 ** 9
                                    else (e_mkt - C[end]))) / e_mkt * 100
                        R.append(dict(grp=grp, sym=sym, kind="market",
                                      net=pr - COST_MARKET, sp=sp_m,
                                      dv=dv, atr=atr_pct, corr=corr))

            # ── ВАРИАНТ LIMIT: ждём откат ──
            entry = extreme + A_len * PB
            jf = None
            for j in range(i + 1, min(i + 1 + WAIT, n)):
                if H[j] >= entry:
                    jf = j; break
            if jf is None:
                continue
            if sl <= entry:
                continue
            sp = (sl - entry) / entry * 100
            if sp <= 0 or sp > 25:
                continue
            tp = entry - A_len * K
            end = min(jf + TTL, n - 1)
            fl, fh = L[jf + 1:end + 1], H[jf + 1:end + 1]
            if len(fl) == 0:
                continue
            hs, ht = fh >= sl, fl <= tp
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            pr = ((entry - sl) if (js <= jt and js < 10 ** 9)
                  else ((entry - tp) if jt < 10 ** 9 else (entry - C[end]))) / entry * 100

            # ── ТРЕЙЛИНГ ПО СТРУКТУРЕ: после половины пути стоп за экстремум N баров ──
            half = entry - A_len * 0.5
            cur_sl = sl
            armed = False
            pr_tr = None
            for j in range(jf + 1, end + 1):
                if H[j] >= cur_sl:
                    pr_tr = (entry - cur_sl) / entry * 100
                    break
                if L[j] <= tp:
                    pr_tr = (entry - tp) / entry * 100
                    break
                if not armed and L[j] <= half:
                    armed = True
                if armed:
                    lo = max(0, j - TRAIL_BARS + 1)
                    new_sl = float(H[lo:j + 1].max()) * 1.001
                    cur_sl = min(cur_sl, new_sl)
            if pr_tr is None:
                pr_tr = (entry - C[end]) / entry * 100

            R.append(dict(grp=grp, sym=sym, kind="limit", net=pr - COST_LIMIT,
                          net_trail=pr_tr - COST_LIMIT, sp=sp,
                          dv=dv, atr=atr_pct, corr=corr))
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)} · записей {len(R)}")

    T = pd.DataFrame(R)
    if len(T) < 500:
        print(f"\nмало данных: {len(T)}")
        return 1
    LIM = T[T.kind == "limit"]
    MKT = T[T.kind == "market"]
    base = st_(LIM[LIM.grp == "OOS"].net.values, days)
    print(f"\nзаписей {len(T)} · лимитных {len(LIM)} · рыночных {len(MKT)} · окно {days} дней")
    print(f"fill-rate лимита: {100 * len(LIM) / max(len(MKT), 1):.0f}% от всех сломов\n")

    print("═" * 126)
    print("▌ 3. ГИБРИДНОЕ ИСПОЛНЕНИЕ — лимит (45%, косты 0.35) против рынка (100%, косты 0.79)")
    print("═" * 126)
    line("ЛИМИТ — только заполненные", base, None, days)
    line("РЫНОК — все сломы", st_(MKT[MKT.grp == "OOS"].net.values, days), base, days)

    print(f"\n{'=' * 126}")
    print("▌ 2. ТРЕЙЛИНГ ПО СТРУКТУРЕ (стоп за экстремум 6 баров после половины пути)")
    print(f"{'=' * 126}")
    line("фиксированный стоп (контроль)", base, None, days)
    line("трейлинг по структуре", st_(LIM[LIM.grp == "OOS"].net_trail.values, days), base, days)

    print(f"\n{'=' * 126}")
    print("▌ 1. ОТБОР ВСЕЛЕННОЙ")
    print(f"{'=' * 126}")
    O = LIM[LIM.grp == "OOS"]
    print("\n  — по обороту (медианный $ за бар) —")
    q = O.dv.quantile([0.25, 0.5, 0.75]).values
    for nm, m in (("Q1 неликвид", O.dv <= q[0]), ("Q2", (O.dv > q[0]) & (O.dv <= q[1])),
                  ("Q3", (O.dv > q[1]) & (O.dv <= q[2])), ("Q4 ликвид", O.dv > q[2])):
        line(nm, st_(O[m].net.values, days), base, days)
    print("\n  — по волатильности (медианный ATR%) —")
    q = O.atr.quantile([0.33, 0.66]).values
    for nm, m in ((f"низкая ≤{q[0]:.2f}%", O.atr <= q[0]),
                  ("средняя", (O.atr > q[0]) & (O.atr <= q[1])),
                  (f"высокая >{q[1]:.2f}%", O.atr > q[1])):
        line(nm, st_(O[m].net.values, days), base, days)
    if O["corr"].notna().any():
        print("\n  — по корреляции с BTC —")
        q = O["corr"].quantile([0.33, 0.66]).values
        for nm, m in ((f"низкая ≤{q[0]:.2f}", O["corr"] <= q[0]),
                      ("средняя", (O["corr"] > q[0]) & (O["corr"] <= q[1])),
                      (f"высокая >{q[1]:.2f}", O["corr"] > q[1])):
            line(nm, st_(O[m].net.values, days), base, days)

    print("\n" + "═" * 126)
    print("Все числа — на OOS-половине вселенной. 🟢 WR>53% и PF>1.2 · 💰 PF>1.1")
    print("═" * 126)
    print("")
    print("=" * 126)
    print("| 4. СВЯЗКА ЛУЧШИХ НАХОДОК (высокая волатильность x трейлинг x ликвидность)")
    print("=" * 126)
    qa = O.atr.quantile(0.66)
    hv = O[O.atr > qa]
    line("контроль: вся вселенная, фикс-стоп", base, None, days)
    line("высокая волатильность, фикс-стоп", st_(hv.net.values, days), base, days)
    line("высокая волатильность + ТРЕЙЛИНГ", st_(hv.net_trail.values, days), base, days)
    lowdv = O[(O.atr > qa) & (O.dv <= O.dv.median())]
    line("выс.волат + неликвид, фикс", st_(lowdv.net.values, days), base, days)
    line("выс.волат + неликвид + трейлинг", st_(lowdv.net_trail.values, days), base, days)
    O.to_csv("scripts/_uth_dump.csv", index=False)
    print("[dump] -> scripts/_uth_dump.csv")

    return 0


if __name__ == "__main__":
    sys.exit(main())
