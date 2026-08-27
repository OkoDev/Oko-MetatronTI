# -*- coding: utf-8 -*-
"""ЧТО ПОДНИМАЕТ PF И WR МЕХАНИКИ CHoCH → ВОЛНА C (18.08.2026, Даат).

Егор: «PF и WR нужно тянуть вверх! ищи смежные инструменты и зависимости по jsonSchema».

База: механика прошла OOS ([[choch_pullback_waveC_oos_passed]]) — swing-CHoCH →
структурная нога OKO-SM → откат 0.236 → лимит → волна C ×1.0, 1h.
OOS×OOS: WR 53.1%, PF 1.17. Задача — найти признаки, которые тянут это вверх.

Источники признаков (те самые «смежные инструменты»):
  • флаги compute_flags на рабочем 1h (149 шт, включая пивоты после правки 17.08);
  • HTF-конфлюэнция: те же флаги с 4h и 1d, выровненные ТОЛЬКО с закрытого бара;
  • геометрия самого сетапа: длина ноги в % и в ATR, глубина фактического отката,
    сколько баров ждали заполнения лимита, размер стопа, час входа.

🔴 ЗАЩИТА ОТ ПЕРЕБОРА. Признаков ~200. Если искать «лучший» на всей выборке,
он найдётся случайно ([[arch104_remeasured_causal_fvg]]: из 14 789 паттернов
причинно живых 5 из 153). Поэтому:
    ищем на IS-половине монет (хэш символа) → ПРОВЕРЯЕМ на OOS-половине.
В отчёт попадают только те, кто выжил на OOS.

Метрика — лифт PF и WR против БАЗЫ механики на той же половине.

Запуск:  python scripts/choch_feature_boosters.py [--coins 250] [--min-n 150]
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


def pf_wr(net):
    net = np.asarray(net, float)
    if len(net) == 0:
        return None
    neg = abs(net[net < 0].sum())
    return dict(n=len(net), wr=100 * (net > 0).mean(),
                pf=(net[net > 0].sum() / neg if neg > 0 else 99.0), mean=float(net.mean()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=250)
    ap.add_argument("--since", type=int, default=2024)
    ap.add_argument("--side", type=str, default="short")
    ap.add_argument("--min-n", type=int, default=150)
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 122)
    print(f"УСИЛИТЕЛИ ДЛЯ CHoCH → ВОЛНА C · {a.side.upper()} · {len(syms)} монет с {a.since}")
    print(f"поиск на IS-монетах → проверка на OOS-монетах (защита от перебора)")
    print("═" * 122)

    rows = []          # dict: net, grp, + признаки
    want_bull = (a.side == "long")

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
        try:
            st = run_structure(dd, swing_len=50, internal_len=5, record_legs=True)
            F1 = compute_flags(d, "1h", include_pivots=True)
        except Exception:
            continue
        legs = st.leg_history
        if not legs or len(legs) != len(dd):
            continue
        # HTF только с ЗАКРЫТОГО бара
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
        # ATR для нормировки длины ноги
        tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                        (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 43, adjust=False).mean().values
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
            tp = entry + A_len * K if want_bull else entry - A_len * K
            end = min(jf + TTL, n - 1)
            fl, fh_ = L[jf + 1:end + 1], H[jf + 1:end + 1]
            if len(fl) == 0:
                continue
            if want_bull:
                hs, ht = fl <= sl, fh_ >= tp
                lo, hi_ = (sl - entry) / entry * 100, (tp - entry) / entry * 100
                tail = (C[end] - entry) / entry * 100
            else:
                hs, ht = fh_ >= sl, fl <= tp
                lo, hi_ = (entry - sl) / entry * 100, (entry - tp) / entry * 100
                tail = (entry - C[end]) / entry * 100
            js = int(np.argmax(hs)) if hs.any() else 10 ** 9
            jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
            pr = lo if (js <= jt and js < 10 ** 9) else (hi_ if jt < 10 ** 9 else tail)

            r = {"net": pr - COST, "grp": grp}
            # ── геометрия сетапа ──
            r["#leg_pct"] = A_len / entry * 100
            r["#leg_atr"] = A_len / max(atr[i], 1e-12)
            r["#stop_pct"] = sp
            r["#wait_bars"] = jf - i
            r["#hour"] = int(d.index[jf].hour)
            r["#leg_bars"] = abs(int(leg.get("extreme_i") or i) - int(leg.get("origin_i") or i))
            # ── флаги 1h на баре ВХОДА ──
            try:
                row1 = F1.iloc[jf]
                for col in F1.columns:
                    v = row1[col]
                    if isinstance(v, (bool, np.bool_)):
                        r[f"1h:{col}"] = bool(v)
            except Exception:
                pass
            # ── HTF-конфлюэнция ──
            for tf, fh2 in HTF.items():
                try:
                    row2 = fh2.iloc[jf]
                    for col in fh2.columns:
                        v = row2[col]
                        if isinstance(v, (bool, np.bool_)):
                            r[f"{tf}:{col}"] = bool(v)
                except Exception:
                    pass
            rows.append(r)
        if si % 40 == 0:
            print(f"  … монет: {si}/{len(syms)} · сделок {len(rows)}")

    if len(rows) < 500:
        print(f"\nсделок мало: {len(rows)}")
        return 1
    T = pd.DataFrame(rows)
    base_is = pf_wr(T[T.grp == "IS"].net.values)
    base_oos = pf_wr(T[T.grp == "OOS"].net.values)
    print(f"\nвсего сделок {len(T)} · признаков {T.shape[1] - 2}")
    print(f"БАЗА механики: IS  n={base_is['n']} WR {base_is['wr']:.1f}% PF {base_is['pf']:.2f}")
    print(f"               OOS n={base_oos['n']} WR {base_oos['wr']:.1f}% PF {base_oos['pf']:.2f}")

    cand = []
    for col in T.columns:
        if col in ("net", "grp"):
            continue
        s = T[col]
        if col.startswith("#"):
            # числовой → верхний и нижний терциль
            q = s.quantile([0.33, 0.66]).values
            if not np.isfinite(q).all() or q[0] == q[1]:
                continue
            variants = [(f"{col} ≥{q[1]:.3g}", s >= q[1]), (f"{col} ≤{q[0]:.3g}", s <= q[0])]
        else:
            if s.dtype != bool:
                continue
            if s.sum() < a.min_n:
                continue
            variants = [(col, s)]
        for nm, mask in variants:
            m_is = mask & (T.grp == "IS")
            m_oos = mask & (T.grp == "OOS")
            if m_is.sum() < a.min_n or m_oos.sum() < a.min_n // 2:
                continue
            a_is = pf_wr(T.loc[m_is, "net"].values)
            a_oos = pf_wr(T.loc[m_oos, "net"].values)
            if not a_is or not a_oos:
                continue
            # отбор на IS: PF выше базы и WR выше базы
            if a_is["pf"] > base_is["pf"] + 0.05 and a_is["wr"] > base_is["wr"]:
                cand.append((nm, a_is, a_oos))

    print(f"\nкандидатов, прошедших отбор на IS: {len(cand)}")
    survived = [(nm, i_, o_) for nm, i_, o_ in cand
                if o_["pf"] > base_oos["pf"] + 0.03 and o_["wr"] > base_oos["wr"]]
    print(f"из них ВЫЖИЛИ на OOS: {len(survived)}")

    if survived:
        survived.sort(key=lambda x: -(x[2]["pf"] - base_oos["pf"]))
        print(f"\n{'признак':<42} {'IS: n / WR / PF':>26} {'OOS: n / WR / PF':>26} {'ΔPF oos':>9}")
        print("─" * 122)
        for nm, i_, o_ in survived[:25]:
            print(f"🟢{nm[:40]:<42} {i_['n']:>6} {i_['wr']:>5.1f}% {i_['pf']:>5.2f}   "
                  f"{o_['n']:>6} {o_['wr']:>5.1f}% {o_['pf']:>5.2f}   "
                  f"{o_['pf'] - base_oos['pf']:>+8.2f}")
    else:
        print("\nни один признак не удержал прибавку на OOS — усилителей не найдено")

    print(f"\n=== ЛУЧШИЕ ПО IS, НО ПРОВАЛИВШИЕСЯ НА OOS (иллюстрация перебора) ===")
    failed = [(nm, i_, o_) for nm, i_, o_ in cand if (nm, i_, o_) not in survived]
    failed.sort(key=lambda x: -(x[1]["pf"] - base_is["pf"]))
    for nm, i_, o_ in failed[:8]:
        print(f"  {nm[:40]:<42} IS PF {i_['pf']:>5.2f} (+{i_['pf'] - base_is['pf']:.2f}) → "
              f"OOS PF {o_['pf']:>5.2f} ({o_['pf'] - base_oos['pf']:+.2f})")

    print("\n" + "═" * 122)
    print("Признак засчитан ТОЛЬКО если поднял и PF, и WR на НЕЗНАКОМЫХ монетах.")
    print("Секция «провалившиеся» показывает, сколько ложных усилителей даёт перебор.")
    print("═" * 122)
    return 0


if __name__ == "__main__":
    sys.exit(main())
