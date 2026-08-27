# -*- coding: utf-8 -*-
"""КОМБИНАЦИИ УСИЛИТЕЛЕЙ + УПРАВЛЕНИЕ ПОЗИЦИЕЙ (18.08.2026, Даат).

Продолжение `choch_feature_boosters.py`, где 19 усилителей пережили OOS поодиночке.
Проверяется то, чего там НЕ было:

  A. КОМБИНАЦИИ усилителей (2 и 3 штуки) — с ценой в ЧАСТОТЕ. Одиночный
     `pivot_below_S1_1W` даёт PF 1.84, но всего 263 сделки против 1788 в базе.
     Стопка фильтров легко срежет выборку до сотни, где PF 1.8 ничего не значит.
  B. УПРАВЛЕНИЕ ПОЗИЦИЕЙ на одних и тех же входах:
       • одна цель (контроль)
       • частичный выход: половина на ×0.5 ноги, остаток на ×1.0
       • безубыток после ×0.5 ноги
       • трейлинг по структуре (за экстремум последних N баров)
       • комбинация «частичный + БУ»
     Это отвечает на хрупкость: если плюс держат верхние 10%, то БУ и частичные
     выходы должны переносить массу сделок из минуса в ноль.
  C. КЛАСТЕРНОСТЬ СЛОМА: сколько монет вселенной дали CHoCH в том же направлении
     в окне ±6ч. Одиночный слом против рыночного события.

Всё считается раздельно на IS/OOS половинах монет (хэш символа) — цифры без
OOS-подтверждения не докладываются.

Запуск:  python scripts/choch_combo_and_exits.py [--coins 250]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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

from core.smc.oko_sm_engine import run_structure  # noqa: E402
from core.calculators.combinator_core import compute_flags  # noqa: E402

DB = "ohlcv_cache.db"
COST = 0.35
TTL, WAIT = 96, 12
PB, K = 0.236, 1.0


def split_of(sym: str) -> str:
    return "IS" if int(hashlib.md5(sym.encode()).hexdigest()[:8], 16) % 2 == 0 else "OOS"


def st_(net):
    net = np.asarray(net, float)
    if len(net) < 60:
        return None
    neg = abs(net[net < 0].sum())
    s = np.sort(net); cut = max(1, int(len(s) * 0.10))
    return dict(n=len(net), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0),
                mean=float(net.mean()), frag=float(s[:-cut].sum()))


def line(nm, s_is, s_oos, days, base_oos=None):
    if not s_oos:
        return
    d = f"{s_oos['pf'] - base_oos['pf']:>+6.2f}" if base_oos else "      "
    mark = "🟢" if (s_oos["wr"] > 53 and s_oos["pf"] > 1.2) else \
           ("💰" if s_oos["pf"] > 1.1 else "  ")
    isp = f"{s_is['pf']:.2f}" if s_is else "  — "
    print(f"{mark}{nm:<44} IS PF {isp:>5} │ OOS n={s_oos['n']:>5} WR {s_oos['wr']:>5.1f}% "
          f"PF {s_oos['pf']:>5.2f} {d} {s_oos['mean']:>+7.2f}%/сд "
          f"{s_oos['n'] / days:>5.2f}сд/дн безтоп10% {s_oos['frag']:>+8.1f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--side", type=str, default="short")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    want_bull = (a.side == "long")
    print("═" * 128)
    print(f"КОМБИНАЦИИ + УПРАВЛЕНИЕ ПОЗИЦИЕЙ · {a.side.upper()} · {len(syms)} монет с {a.since}")
    print("IS/OOS — половины вселенной по хэшу символа; докладываются OOS-числа")
    print("═" * 128)

    R = []      # словари по сделке
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
            F1 = compute_flags(d, "1h", include_pivots=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        HTF = {}
        for tf, rule, shift in (("4h", "4h", pd.Timedelta(hours=4)),
                                ("1d", "1D", pd.Timedelta(days=1))):
            try:
                h = d.resample(rule).agg(agg).dropna()
                if len(h) < 60:
                    continue
                fh = compute_flags(h, tf, include_pivots=False)
                fh.index = fh.index + shift
                HTF[tf] = fh.reindex(d.index, method="ffill")
            except Exception:
                pass
        H, L, C = dd.high.values, dd.low.values, dd.close.values
        n = len(dd)

        for ev in st.events:
            if ev.kind != "CHoCH" or ev.internal or ev.bull != want_bull:
                continue
            i = int(ev.i)
            if i < 60 or i >= n - TTL - WAIT - 2:
                continue
            leg = legs[i]
            if not leg or (leg["trend"] == "long") != ev.bull:
                continue
            origin, extreme = float(leg["origin"]), float(leg["extreme"])
            A_len = abs(extreme - origin)
            if A_len <= 0:
                continue
            entry = extreme - A_len * PB if want_bull else extreme + A_len * PB
            jf = None
            for j in range(i + 1, min(i + 1 + WAIT, n)):
                if (want_bull and L[j] <= entry) or ((not want_bull) and H[j] >= entry):
                    jf = j; break
            if jf is None:
                continue
            sl = origin * 0.999 if want_bull else origin * 1.001
            sp = abs(entry - sl) / entry * 100
            if sp <= 0 or sp > 25:
                continue

            sgn = 1.0 if want_bull else -1.0
            tp_full = entry + sgn * A_len * K
            tp_half = entry + sgn * A_len * 0.5
            end = min(jf + TTL, n - 1)

            # ── проход по барам: единая логика для всех схем выхода ──
            hit_half = None; hit_full = None; hit_sl = None
            trail_exit = None; trail_ext = None
            for j in range(jf + 1, end + 1):
                if want_bull:
                    if hit_half is None and H[j] >= tp_half: hit_half = j
                    if hit_full is None and H[j] >= tp_full: hit_full = j
                    if hit_sl is None and L[j] <= sl: hit_sl = j
                    trail_ext = L[j] if trail_ext is None else min(trail_ext, L[j])
                else:
                    if hit_half is None and L[j] <= tp_half: hit_half = j
                    if hit_full is None and L[j] <= tp_full: hit_full = j
                    if hit_sl is None and H[j] >= sl: hit_sl = j
                    trail_ext = H[j] if trail_ext is None else max(trail_ext, H[j])
                if hit_sl is not None and (hit_full is None or hit_sl <= hit_full):
                    break

            def pct(px):
                return (px - entry) / entry * 100 * sgn

            first_sl = hit_sl if hit_sl is not None else 10 ** 9
            first_full = hit_full if hit_full is not None else 10 ** 9
            first_half = hit_half if hit_half is not None else 10 ** 9

            # 🔴 ФИКС 18.08: раньше при «ничего не сработало» обе переменные были 10**9,
            # и условие first_sl <= first_full давало True → сделка засчитывалась как СТОП.
            # Из-за этого база показывала PF 0.27 вместо 1.15. Теперь исход определяется явно.
            NOTHING = 10 ** 9
            sl_first = first_sl < NOTHING and first_sl <= first_full
            tp_first = first_full < NOTHING and first_full < first_sl
            half_before_sl = first_half < first_sl

            # 1) одна цель (контроль)
            if sl_first:
                r_base = pct(sl)
            elif tp_first:
                r_base = pct(tp_full)
            else:
                r_base = pct(C[end])
            # 2) частичный выход: 50% на ×0.5, остаток по обычной схеме
            if half_before_sl and first_half < NOTHING:
                r_part = 0.5 * pct(tp_half) + 0.5 * r_base
            else:
                r_part = r_base
            # 3) безубыток после ×0.5: если половина взята раньше стопа — остаток в ноль
            if half_before_sl and first_half < NOTHING:
                r_be = pct(tp_full) if tp_first else (0.0 if sl_first else pct(C[end]))
            else:
                r_be = r_base
            # 4) частичный + БУ
            if half_before_sl and first_half < NOTHING:
                tail_part = pct(tp_full) if tp_first else (0.0 if sl_first else pct(C[end]))
                r_pbe = 0.5 * pct(tp_half) + 0.5 * tail_part
            else:
                r_pbe = r_base

            rec = dict(grp=grp, sym=sym, ts=d.index[jf],
                       base=r_base - COST, part=r_part - COST,
                       be=r_be - COST, pbe=r_pbe - COST, sp=sp)
            # признаки-усилители (пережившие OOS поодиночке)
            def fl(src, col):
                try:
                    return bool(src.iloc[jf][col])
                except Exception:
                    return False
            rec["f_s1w"] = fl(F1, "pivot_below_S1_1W") if not want_bull else fl(F1, "pivot_above_R1_1W")
            rec["f_ovh"] = fl(F1, "bear_fvg_overlap_held_1h") if not want_bull else fl(F1, "bull_fvg_overlap_held_1h")
            rec["f_ema1d"] = HTF.get("1d") is not None and fl(HTF["1d"], "ema50_above_ema200_1d")
            rec["f_div4h"] = HTF.get("4h") is not None and fl(
                HTF["4h"], "rsi_div_bear_hidden_4h" if not want_bull else "rsi_div_bull_hidden_4h")
            rec["f_atr4h"] = HTF.get("4h") is not None and fl(
                HTF["4h"], "atr_cross_down_4h" if not want_bull else "atr_cross_up_4h")
            rec["f_hour"] = int(d.index[jf].hour) <= 7
            R.append(rec)
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)} · сделок {len(R)}")

    if len(R) < 500:
        print(f"\nмало сделок: {len(R)}")
        return 1
    T = pd.DataFrame(R).sort_values("ts")

    # ── C. кластерность слома по рынку (±6ч) ──
    ts = T.ts.values.astype("datetime64[ns]").astype(np.int64) // 10 ** 9
    win = 6 * 3600
    order = np.argsort(ts)
    ts_s = ts[order]
    cnt = np.zeros(len(T), dtype=int)
    lo = 0
    for k in range(len(ts_s)):
        while ts_s[k] - ts_s[lo] > win:
            lo += 1
        cnt[order[k]] = k - lo
    T["cluster"] = cnt

    B_is, B_oos = st_(T[T.grp == "IS"].base.values), st_(T[T.grp == "OOS"].base.values)
    print(f"\nсделок {len(T)} · окно {days} дней")
    print(f"БАЗА: IS PF {B_is['pf']:.2f} WR {B_is['wr']:.1f}% │ "
          f"OOS n={B_oos['n']} WR {B_oos['wr']:.1f}% PF {B_oos['pf']:.2f} "
          f"{B_oos['mean']:+.2f}%/сд безтоп10% {B_oos['frag']:+.1f}")

    print(f"\n{'=' * 128}")
    print("▌ B. УПРАВЛЕНИЕ ПОЗИЦИЕЙ (одни и те же входы, разный выход)")
    print(f"{'=' * 128}")
    for col, nm in (("base", "одна цель ×1.0 (контроль)"),
                    ("part", "частичный: 50% на ×0.5, остаток ×1.0"),
                    ("be", "безубыток после ×0.5"),
                    ("pbe", "частичный 50% + БУ на остаток")):
        line(nm, st_(T[T.grp == "IS"][col].values), st_(T[T.grp == "OOS"][col].values),
             days, B_oos)

    print(f"\n{'=' * 128}")
    print("▌ C. КЛАСТЕРНОСТЬ СЛОМА ПО РЫНКУ (сколько монет сломались в ±6ч)")
    print(f"{'=' * 128}")
    for nm, m in (("одиночка (0 других)", T.cluster == 0),
                  ("1-3 других", (T.cluster >= 1) & (T.cluster <= 3)),
                  ("4-9 других", (T.cluster >= 4) & (T.cluster <= 9)),
                  ("10+ (рыночное событие)", T.cluster >= 10)):
        line(nm, st_(T[m & (T.grp == "IS")].base.values),
             st_(T[m & (T.grp == "OOS")].base.values), days, B_oos)

    print(f"\n{'=' * 128}")
    print("▌ A. КОМБИНАЦИИ УСИЛИТЕЛЕЙ — с ценой в частоте")
    print(f"{'=' * 128}")
    F = ["f_s1w", "f_ovh", "f_ema1d", "f_div4h", "f_atr4h", "f_hour"]
    NAMES = {"f_s1w": "под S1(1W)", "f_ovh": "fvg_overlap_held", "f_ema1d": "ema50>200(1d)",
             "f_div4h": "скрыт.див 4h", "f_atr4h": "atr_cross 4h", "f_hour": "час≤7"}
    print("\n  — по одному —")
    for f in F:
        line(NAMES[f], st_(T[T[f] & (T.grp == "IS")].base.values),
             st_(T[T[f] & (T.grp == "OOS")].base.values), days, B_oos)
    print("\n  — пары —")
    pairs = []
    for x in range(len(F)):
        for y in range(x + 1, len(F)):
            m = T[F[x]] & T[F[y]]
            s_oos = st_(T[m & (T.grp == "OOS")].base.values)
            if s_oos:
                pairs.append((f"{NAMES[F[x]]} + {NAMES[F[y]]}",
                              st_(T[m & (T.grp == "IS")].base.values), s_oos))
    pairs.sort(key=lambda x: -x[2]["pf"])
    for nm, s_is, s_oos in pairs[:12]:
        line(nm, s_is, s_oos, days, B_oos)
    print("\n  — тройки —")
    tri = []
    for x in range(len(F)):
        for y in range(x + 1, len(F)):
            for z in range(y + 1, len(F)):
                m = T[F[x]] & T[F[y]] & T[F[z]]
                s_oos = st_(T[m & (T.grp == "OOS")].base.values)
                if s_oos:
                    tri.append((f"{NAMES[F[x]]}+{NAMES[F[y]]}+{NAMES[F[z]]}",
                                st_(T[m & (T.grp == "IS")].base.values), s_oos))
    tri.sort(key=lambda x: -x[2]["pf"])
    for nm, s_is, s_oos in tri[:10]:
        line(nm, s_is, s_oos, days, B_oos)

    print(f"\n{'=' * 128}")
    print("▌ ЛУЧШАЯ СХЕМА ВЫХОДА × ЛУЧШИЙ ФИЛЬТР")
    print(f"{'=' * 128}")
    best_f = max(F, key=lambda f: (st_(T[T[f] & (T.grp == "OOS")].base.values) or {"pf": 0})["pf"])
    for col, nm in (("base", "одна цель"), ("part", "частичный"),
                    ("be", "БУ"), ("pbe", "частичный+БУ")):
        m = T[best_f]
        line(f"{NAMES[best_f]} × {nm}", st_(T[m & (T.grp == "IS")][col].values),
             st_(T[m & (T.grp == "OOS")][col].values), days, B_oos)

    print("\n" + "═" * 128)
    print("🟢 WR>53% и PF>1.2 на OOS · 💰 PF>1.1 · все числа — на НЕЗНАКОМЫХ монетах")
    print("«сд/дн» — цена фильтра в частоте: база даёт ~2 сделки/день на половине вселенной")
    print("═" * 128)
    return 0


if __name__ == "__main__":
    sys.exit(main())
