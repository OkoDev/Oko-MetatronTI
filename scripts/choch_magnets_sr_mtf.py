# -*- coding: utf-8 -*-
"""МАГНИТЫ КАК ПОДДЕРЖКА/СОПРОТИВЛЕНИЕ + SMC MTF-КОНФЛЮЭНЦИЯ (18.08.2026, Даат).

Егор: «проверить инвертированность магнитов как поддержки для цены или сопротивления!
конфлюенции + SMC MTF наборы».

ИДЕЯ ИНВЕРСИИ. Замер 18.08 показал: тяжёлый кластер магнитов НА ПУТИ к цели мешает
(PF 0.93 против 1.46 у лёгкого). Логичное следствие: тот же кластер СО СТОРОНЫ СТОПА
должен ЗАЩИЩАТЬ. Для SHORT:
    магниты НИЖЕ входа (между входом и целью)  = ПОДДЕРЖКА → мешает падению → плохо
    магниты ВЫШЕ входа (между входом и стопом) = СОПРОТИВЛЕНИЕ → держит цену → ХОРОШО
Это не проверялось: раньше считались только магниты в сторону сделки.

Считается:
  1. вес магнитов МЕЖДУ ВХОДОМ И СТОПОМ (защита стопа) — главная гипотеза;
  2. отношение «защита / помеха» — асимметрия окружения;
  3. дистанция до ближайшего магнита ЗА стопом (насколько далеко «щит»);
  4. SMC MTF-КОНФЛЮЭНЦИЯ: сколько ТФ (5m/15m/1h/4h/1d) дают медвежий SMC-сигнал
     одновременно (bear FVG / bear OB / bear CHoCH / bear BOS / premium);
  5. связка лучшего из (1)-(3) с лучшим из (4).

Всё на IS/OOS половинах вселенной, докладываются OOS-числа. Косты 0.35%.
Механика зафиксирована: swing-CHoCH → структурная нога → откат 0.236 → волна C ×1.0.

Запуск:  python scripts/choch_magnets_sr_mtf.py [--coins 250]
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
from core.smc.smc_engine import confirmed_swings  # noqa: E402
from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.35
TTL, WAIT = 96, 12
PB, K = 0.236, 1.0
EPS = 0.6
W = {"fvg": 3.0, "swing": 2.5, "pivot_1D": 2.0, "pivot_1W": 3.0, "struct": 2.0}


def split_of(sym: str) -> str:
    return "IS" if int(hashlib.md5(sym.encode()).hexdigest()[:8], 16) % 2 == 0 else "OOS"


def st_(net, days=None):
    net = np.asarray(net, float); net = net[~np.isnan(net)]
    if len(net) < 50:
        return None
    neg = abs(net[net < 0].sum())
    s = np.sort(net); cut = max(1, int(len(s) * 0.10))
    o = dict(n=len(net), wr=100 * (net > 0).mean(),
             pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
             mean=float(net.mean()), frag=float(s[:-cut].sum()))
    if days:
        o["fd"] = len(net) / max(days, 1)
        o["per_day"] = o["mean"] * o["fd"]
    return o


def line(nm, s, base=None):
    if not s:
        print(f"    {nm:<46} — мало данных")
        return
    d = f"{s['pf'] - base['pf']:>+6.2f}" if base else "      "
    mark = "🟢" if (s["wr"] > 56 and s["pf"] > 1.3) else \
           ("✅" if s["pf"] > 1.2 else ("💰" if s["pf"] > 1.05 else "  "))
    pdd = f"{s.get('per_day', 0):>+7.3f}%/дн" if "per_day" in s else ""
    print(f"{mark}{nm:<46} n={s['n']:>5} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} {d} "
          f"{s['mean']:>+7.2f}%/сд {s.get('fd', 0):>5.2f}сд/дн {pdd} "
          f"безтоп10% {s['frag']:>+8.1f}")


def fvg_mids(df, upto):
    high, low, close = df.high.values, df.low.values, df.close.values
    out, lo = [], max(2, upto - 300)
    gaps = [max(0.0, low[i] - high[i - 2], low[i - 2] - high[i]) / close[i] * 100
            for i in range(lo, upto + 1)]
    thr = (sum(gaps) / len(gaps)) * 2 if gaps else 0.0
    for i in range(lo, upto + 1):
        if low[i] > high[i - 2] and close[i - 1] > high[i - 2]:
            if (low[i] - high[i - 2]) / high[i - 2] * 100 > thr:
                out.append((high[i - 2] + low[i]) / 2)
        elif high[i] < low[i - 2] and close[i - 1] < low[i - 2]:
            if (low[i - 2] - high[i]) / high[i] * 100 > thr:
                out.append((high[i] + low[i - 2]) / 2)
    return out


def pivots_from(df, upto, rule):
    sub = df.iloc[:upto + 1]
    if len(sub) < 30:
        return []
    g = sub.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(g) < 2:
        return []
    h, l, c = float(g.high.iloc[-2]), float(g.low.iloc[-2]), float(g.close.iloc[-2])
    pp = (h + l + c) / 3
    return [pp, 2 * pp - l, 2 * pp - h, pp + (h - l), pp - (h - l),
            h + 2 * (pp - l), l - 2 * (h - pp)]


def clusters(levels, lo, hi):
    """Кластеры в ценовом коридоре [lo, hi] → [(center, weight)]."""
    side = [(p, w) for p, w in levels if lo <= p <= hi and p > 0]
    if not side:
        return []
    side.sort()
    out, used = [], [False] * len(side)
    for i, (p, w) in enumerate(side):
        if used[i]:
            continue
        grp = [(p, w)]; used[i] = True
        for j in range(i + 1, len(side)):
            if not used[j] and abs(side[j][0] - p) / p * 100 <= EPS:
                grp.append(side[j]); used[j] = True
        tw = sum(g[1] for g in grp)
        out.append((sum(g[0] * g[1] for g in grp) / tw, tw))
    return out


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
    con.close()

    print("═" * 128)
    print(f"МАГНИТЫ КАК S/R (инверсия) + SMC MTF-КОНФЛЮЭНЦИЯ · SHORT · {len(syms)} монет")
    print("для SHORT: магниты НИЖЕ входа = поддержка (помеха) · ВЫШЕ = сопротивление (щит)")
    print("═" * 128)

    R = []
    days = 1
    for si, sym in enumerate(syms, 1):
        grp_ = split_of(sym)
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
            sw50 = confirmed_swings(dd, 50)
            sw5 = confirmed_swings(dd, 5)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        # ── SMC-флаги по ТФ для MTF-конфлюэнции ──
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        SM = {}
        try:
            SM["1h"] = compute_flags(d, "1h", include_pivots=False)
        except Exception:
            continue
        for tf, rule, shift in (("4h", "4h", pd.Timedelta(hours=4)),
                                ("1d", "1D", pd.Timedelta(days=1))):
            try:
                h = d.resample(rule).agg(agg).dropna()
                if len(h) < 60:
                    continue
                fh = compute_flags(h, tf, include_pivots=False)
                fh.index = fh.index + shift
                SM[tf] = fh.reindex(d.index, method="ffill")
            except Exception:
                pass
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal or ev.bull:
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
            entry = extreme + A_len * PB
            jf = None
            for j in range(i + 1, min(i + 1 + WAIT, n)):
                if H[j] >= entry:
                    jf = j; break
            if jf is None:
                continue
            sl = origin * 1.001
            if sl <= entry:
                continue
            sp = (sl - entry) / entry * 100
            if sp <= 0 or sp > 25:
                continue
            tp = entry - A_len * K

            lv = [(p, W["fvg"]) for p in fvg_mids(dd, jf)]
            lv += [(float(x[1]), W["swing"]) for x in sw50 if x[0] <= jf][-12:]
            lv += [(float(x[1]), W["struct"]) for x in sw5 if x[0] <= jf][-20:]
            lv += [(p, W["pivot_1D"]) for p in pivots_from(d, jf, "1D")]
            lv += [(p, W["pivot_1W"]) for p in pivots_from(d, jf, "1W")]

            # 🔑 ИНВЕРСИЯ: щит между входом и стопом vs помеха между входом и целью
            shield = clusters(lv, entry, sl)          # ВЫШЕ входа (сопротивление)
            block = clusters(lv, tp, entry)           # НИЖЕ входа (поддержка)
            w_shield = sum(w for _, w in shield)
            w_block = sum(w for _, w in block)
            # ближайший щит: насколько близко к входу стоит сопротивление
            near_sh = min((abs(p - entry) / entry * 100 for p, _ in shield), default=np.nan)

            end = min(jf + TTL, n - 1)
            fl, fh = L[jf + 1:end + 1], H[jf + 1:end + 1]
            if len(fl) == 0:
                continue
            hs, ht = fh >= sl, fl <= tp
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            pr = ((entry - sl) if (js <= jt and js < 10 ** 9)
                  else ((entry - tp) if jt < 10 ** 9 else (entry - C[end]))) / entry * 100

            # ── SMC MTF-конфлюэнция ──
            def bear_on(tf):
                f = SM.get(tf)
                if f is None:
                    return 0
                try:
                    row = f.iloc[jf]
                except Exception:
                    return 0
                cols = [f"bear_fvg_{tf}", f"bear_ob_{tf}", f"bear_choch_{tf}",
                        f"bear_bos_{tf}", f"premium_{tf}"]
                return sum(1 for c_ in cols if c_ in f.columns and bool(row[c_]))
            mtf = sum(1 for tf in ("1h", "4h", "1d") if bear_on(tf) > 0)
            mtf_w = sum(bear_on(tf) for tf in ("1h", "4h", "1d"))

            R.append(dict(grp=grp_, net=pr - COST, sp=sp,
                          w_shield=w_shield, w_block=w_block,
                          ratio=(w_shield / w_block) if w_block > 0 else np.nan,
                          near_sh=near_sh, mtf=mtf, mtf_w=mtf_w))
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)} · сделок {len(R)}")

    T = pd.DataFrame(R)
    if len(T) < 300:
        print(f"\nмало сделок: {len(T)}")
        return 1
    O = T[T.grp == "OOS"]
    base = st_(O.net.values, days)
    print(f"\nсделок {len(T)} · OOS {len(O)} · окно {days} дней")
    print(f"медиана веса: щит {O.w_shield.median():.1f} · помеха {O.w_block.median():.1f}\n")

    print("═" * 128)
    print("▌ 1. ЩИТ: вес магнитов МЕЖДУ ВХОДОМ И СТОПОМ (гипотеза инверсии)")
    print("═" * 128)
    line("контроль (все сделки)", base)
    q = O.w_shield.quantile([0.33, 0.66]).values
    for nm, m in ((f"слабый щит ≤{q[0]:.1f}", O.w_shield <= q[0]),
                  ("средний щит", (O.w_shield > q[0]) & (O.w_shield <= q[1])),
                  (f"СИЛЬНЫЙ щит >{q[1]:.1f}", O.w_shield > q[1])):
        line(nm, st_(O[m].net.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 2. ПОМЕХА: вес магнитов МЕЖДУ ВХОДОМ И ЦЕЛЬЮ (контроль, знак известен)")
    print(f"{'=' * 128}")
    q = O.w_block.quantile([0.33, 0.66]).values
    for nm, m in ((f"мало помех ≤{q[0]:.1f}", O.w_block <= q[0]),
                  ("средне", (O.w_block > q[0]) & (O.w_block <= q[1])),
                  (f"много помех >{q[1]:.1f}", O.w_block > q[1])):
        line(nm, st_(O[m].net.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 3. АСИММЕТРИЯ ОКРУЖЕНИЯ: щит / помеха")
    print(f"{'=' * 128}")
    ok = O[O.ratio.notna()]
    q = ok.ratio.quantile([0.33, 0.66]).values
    for nm, m in ((f"помеха давит ≤{q[0]:.2f}", ok.ratio <= q[0]),
                  ("баланс", (ok.ratio > q[0]) & (ok.ratio <= q[1])),
                  (f"ЩИТ давит >{q[1]:.2f}", ok.ratio > q[1])):
        line(nm, st_(ok[m].net.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 4. БЛИЗОСТЬ БЛИЖАЙШЕГО ЩИТА К ВХОДУ")
    print(f"{'=' * 128}")
    ok = O[O.near_sh.notna()]
    q = ok.near_sh.quantile([0.33, 0.66]).values
    for nm, m in ((f"щит вплотную ≤{q[0]:.2f}%", ok.near_sh <= q[0]),
                  ("средне", (ok.near_sh > q[0]) & (ok.near_sh <= q[1])),
                  (f"щит далеко >{q[1]:.2f}%", ok.near_sh > q[1])):
        line(nm, st_(ok[m].net.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 5. SMC MTF-КОНФЛЮЭНЦИЯ (сколько ТФ дают медвежий SMC-сигнал)")
    print(f"{'=' * 128}")
    for nm, m in (("0 ТФ", O.mtf == 0), ("1 ТФ", O.mtf == 1),
                  ("2 ТФ", O.mtf == 2), ("3 ТФ (все)", O.mtf == 3)):
        line(nm, st_(O[m].net.values, days), base)
    print("\n  — по СУММЕ медвежьих SMC-флагов на всех ТФ —")
    q = O.mtf_w.quantile([0.33, 0.66]).values
    for nm, m in ((f"мало ≤{q[0]:.0f}", O.mtf_w <= q[0]),
                  ("средне", (O.mtf_w > q[0]) & (O.mtf_w <= q[1])),
                  (f"много >{q[1]:.0f}", O.mtf_w > q[1])):
        line(nm, st_(O[m].net.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 6. СВЯЗКА: сильный щит × MTF-конфлюэнция")
    print(f"{'=' * 128}")
    qs = O.w_shield.quantile(0.66)
    hi_sh = O[O.w_shield > qs]
    line("сильный щит (контроль)", st_(hi_sh.net.values, days), base)
    line("сильный щит + ≥2 ТФ", st_(hi_sh[hi_sh.mtf >= 2].net.values, days), base)
    qb = O.w_block.quantile(0.33)
    line("сильный щит + мало помех", st_(O[(O.w_shield > qs) & (O.w_block <= qb)].net.values,
                                         days), base)
    line("сильный щит + мало помех + ≥2ТФ",
         st_(O[(O.w_shield > qs) & (O.w_block <= qb) & (O.mtf >= 2)].net.values, days), base)

    print("\n" + "═" * 128)
    print("🟢 WR>56% и PF>1.3 · ✅ PF>1.2 · 💰 PF>1.05 · «%/дн» — доход в день с учётом частоты")
    print("═" * 128)
    return 0


if __name__ == "__main__":
    sys.exit(main())
