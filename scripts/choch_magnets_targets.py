# -*- coding: utf-8 -*-
"""МАГНИТЫ КАК ЦЕЛЬ + КЛАСТЕРЫ + ЧАСТОТА (18.08.2026, Даат).

Егор: «PF 2.00 это очень хорошо! но частота нужна» + «вспомни про магниты для цены
и кластеры».

Две задачи разом:

1. МАГНИТЫ КАК ЦЕЛЬ вместо фиксированной волны C ×1.0.
   Механика из `core/smc/tp_selector.py`: собираем уровни притяжения в сторону сделки
   (FVG-midpoint, swing, пивоты 1D/1W, экстремумы структуры), кластеризуем по близости
   (eps%), вес кластера = сумма весов источников (gravity). Цель — ближайший кластер
   либо самый тяжёлый.
   Гипотеза: до реального уровня цена доходит ЧАЩЕ, чем до абстрактной волны C →
   WR и частота закрытий растут.

2. ЧАСТОТА. Сейчас связки дают 0.19–0.28 сделки/день. Проверяются два способа:
   • ВСЕЛЕННАЯ: 250 → 500 монет (все, что есть в кэше);
   • INTERNAL-СЛОМЫ (len5) вдобавок к swing (len50) — их примерно втрое больше.
     🔴 Осторожно: 15.08 замер показал, что internal-CHoCH с ногой len50 даёт PF 0.55
     (смешение масштабов). Здесь для internal берётся своя, internal-нога.

Всё на IS/OOS половинах вселенной, докладываются OOS-числа. Косты 0.35% (лимитный вход).

Запуск:  python scripts/choch_magnets_targets.py [--coins 500] [--internal]
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

DB = "ohlcv_cache.db"
COST = 0.35
TTL, WAIT = 96, 12
PB = 0.236
EPS = 0.6            # ширина кластера магнитов, % цены
# веса источников — как в tp_selector (порядок важности, не абсолют)
W = {"fvg": 3.0, "swing": 2.5, "pivot_1D": 2.0, "pivot_1W": 3.0, "struct": 2.0}


def split_of(sym: str) -> str:
    return "IS" if int(hashlib.md5(sym.encode()).hexdigest()[:8], 16) % 2 == 0 else "OOS"


def st_(net, days=None):
    net = np.asarray(net, float)
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
        print(f"    {nm:<44} — мало данных")
        return
    d = f"{s['pf'] - base['pf']:>+6.2f}" if base else "      "
    mark = "🟢" if (s["wr"] > 56 and s["pf"] > 1.3) else \
           ("✅" if s["pf"] > 1.2 else ("💰" if s["pf"] > 1.05 else "  "))
    pd_ = f"{s.get('per_day', 0):>+7.3f}%/дн" if "per_day" in s else ""
    print(f"{mark}{nm:<44} n={s['n']:>5} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} {d} "
          f"{s['mean']:>+7.2f}%/сд {s.get('fd', 0):>5.2f}сд/дн {pd_} "
          f"безтоп10% {s['frag']:>+8.1f}")


def fvg_mids(df, upto):
    """Midpoint'ы FVG до бара upto (флаг на баре обнаружения — после фикса 13.08)."""
    high, low, close = df.high.values, df.low.values, df.close.values
    out = []
    lo = max(2, upto - 300)
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
    """Классические пивоты по ПРЕДЫДУЩЕМУ периоду (1D/1W) на момент бара upto."""
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


def cluster_targets(levels, entry, want_bull):
    """[(price, weight)] → кластеры в сторону сделки, отсортированы по близости."""
    side = [(p, w) for p, w in levels
            if p > 0 and ((want_bull and p > entry) or ((not want_bull) and p < entry))]
    if not side:
        return []
    side.sort(key=lambda x: x[0])
    out, used = [], [False] * len(side)
    for i, (p, w) in enumerate(side):
        if used[i]:
            continue
        grp = [(p, w)]
        used[i] = True
        for j in range(i + 1, len(side)):
            if used[j]:
                continue
            if abs(side[j][0] - p) / p * 100 <= EPS:
                grp.append(side[j]); used[j] = True
        tw = sum(g[1] for g in grp)
        center = sum(g[0] * g[1] for g in grp) / tw
        out.append((center, tw, len(grp)))
    out.sort(key=lambda x: abs(x[0] - entry))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=500)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--internal", action="store_true", help="добавить internal-сломы (len5)")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 128)
    print(f"МАГНИТЫ КАК ЦЕЛЬ + КЛАСТЕРЫ + ЧАСТОТА · SHORT · {len(syms)} монет с {a.since}")
    print(f"сломы: swing(len50){' + internal(len5)' if a.internal else ''} · "
          f"eps кластера {EPS}% · косты {COST}%")
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
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)
        tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                        (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
        atr_pct = float((tr.ewm(alpha=1 / 43, adjust=False).mean() / d.close * 100).median())

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.bull:
                continue
            if ev.internal and not a.internal:
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

            # ── МАГНИТЫ (только прошлое, до бара входа) ──
            lv = []
            for p in fvg_mids(dd, jf):
                lv.append((p, W["fvg"]))
            for idx_, price_, is_top in [(x[0], x[1], x[2]) for x in sw50 if x[0] <= jf][-12:]:
                lv.append((float(price_), W["swing"]))
            for idx_, price_, is_top in [(x[0], x[1], x[2]) for x in sw5 if x[0] <= jf][-20:]:
                lv.append((float(price_), W["struct"]))
            for p in pivots_from(d, jf, "1D"):
                lv.append((p, W["pivot_1D"]))
            for p in pivots_from(d, jf, "1W"):
                lv.append((p, W["pivot_1W"]))
            cl = cluster_targets(lv, entry, want_bull=False)

            tp_wave = entry - A_len * 1.0
            tp_near = cl[0][0] if cl else None
            tp_heavy = max(cl, key=lambda x: x[1])[0] if cl else None
            # сколько магнитов лежит МЕЖДУ входом и целью-волной (помеха пути)
            in_path = sum(1 for p, w, k in cl if p > tp_wave)

            end = min(jf + TTL, n - 1)

            def run(tp):
                if tp is None or tp >= entry:
                    return None
                fl, fh = L[jf + 1:end + 1], H[jf + 1:end + 1]
                if len(fl) == 0:
                    return None
                hs, ht = fh >= sl, fl <= tp
                js = int(np.argmax(hs)) if hs.any() else 10 ** 9
                jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
                if js <= jt and js < 10 ** 9:
                    return (entry - sl) / entry * 100
                if jt < 10 ** 9:
                    return (entry - tp) / entry * 100
                return (entry - C[end]) / entry * 100

            rec = dict(grp=grp_, sym=sym, sp=sp, atr=atr_pct,
                       internal=bool(ev.internal), in_path=in_path,
                       n_cl=len(cl), heavy_w=(max(x[1] for x in cl) if cl else 0.0))
            rec["wave"] = (run(tp_wave) or 0) - COST
            v = run(tp_near)
            rec["near"] = (v - COST) if v is not None else np.nan
            v = run(tp_heavy)
            rec["heavy"] = (v - COST) if v is not None else np.nan
            # цель: ближайший магнит, но не ближе 0.5 ноги (чтобы не резать в ноль)
            floor_ = entry - A_len * 0.5
            far = [p for p, w, k in cl if p <= floor_]
            v = run(far[0] if far else tp_wave)
            rec["near_far"] = (v - COST) if v is not None else np.nan
            R.append(rec)
        if si % 50 == 0:
            print(f"  … монет: {si}/{len(syms)} · сделок {len(R)}")

    T = pd.DataFrame(R)
    if len(T) < 300:
        print(f"\nмало сделок: {len(T)}")
        return 1
    O = T[T.grp == "OOS"]
    base = st_(O.wave.values, days)
    print(f"\nсделок {len(T)} · OOS {len(O)} · окно {days} дней")
    print(f"swing-сломов {int((~T.internal).sum())} · internal {int(T.internal.sum())}\n")

    print("═" * 128)
    print("▌ 1. ЦЕЛЬ: ВОЛНА C ПРОТИВ МАГНИТОВ")
    print("═" * 128)
    line("волна C ×1.0 (контроль)", base)
    line("ближайший кластер магнитов", st_(O.near.dropna().values, days), base)
    line("самый тяжёлый кластер", st_(O.heavy.dropna().values, days), base)
    line("ближайший, но дальше 0.5 ноги", st_(O.near_far.dropna().values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 2. КЛАСТЕРЫ НА ПУТИ К ЦЕЛИ (помеха движению)")
    print(f"{'=' * 128}")
    for nm, m in (("чистый путь (0 магнитов)", O.in_path == 0),
                  ("1 магнит на пути", O.in_path == 1),
                  ("2-3 магнита", (O.in_path >= 2) & (O.in_path <= 3)),
                  ("4+ магнитов", O.in_path >= 4)):
        line(nm, st_(O[m].wave.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 3. ВЕС БЛИЖАЙШЕГО КЛАСТЕРА (сила притяжения)")
    print(f"{'=' * 128}")
    q = O.heavy_w.quantile([0.33, 0.66]).values
    for nm, m in ((f"лёгкий ≤{q[0]:.1f}", O.heavy_w <= q[0]),
                  ("средний", (O.heavy_w > q[0]) & (O.heavy_w <= q[1])),
                  (f"тяжёлый >{q[1]:.1f}", O.heavy_w > q[1])):
        line(nm, st_(O[m].wave.values, days), base)

    if a.internal:
        print(f"\n{'=' * 128}")
        print("▌ 4. ЧАСТОТА: SWING ПРОТИВ INTERNAL-СЛОМОВ")
        print(f"{'=' * 128}")
        line("swing (len50)", st_(O[~O.internal].wave.values, days), base)
        line("internal (len5)", st_(O[O.internal].wave.values, days), base)
        line("оба вместе", st_(O.wave.values, days), base)

    print(f"\n{'=' * 128}")
    print("▌ 5. ЛУЧШАЯ ЦЕЛЬ × ВЫСОКАЯ ВОЛАТИЛЬНОСТЬ")
    print(f"{'=' * 128}")
    qa = O.atr.quantile(0.66)
    hv = O[O.atr > qa]
    line("выс.волат × волна C", st_(hv.wave.values, days), base)
    line("выс.волат × ближайший магнит", st_(hv.near.dropna().values, days), base)
    line("выс.волат × дальше 0.5 ноги", st_(hv.near_far.dropna().values, days), base)

    print("\n" + "═" * 128)
    print("🟢 WR>56% и PF>1.3 · ✅ PF>1.2 · 💰 PF>1.05 · «%/дн» = доход в день с учётом частоты")
    print("═" * 128)
    return 0


if __name__ == "__main__":
    sys.exit(main())
