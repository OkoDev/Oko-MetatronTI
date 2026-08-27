# -*- coding: utf-8 -*-
"""ВСЕ ФАКТОРЫ НА ДНЕВНОМ ГОРИЗОНТЕ, В ДЕНЬГАХ (14.08.2026, Даат).

Егор: «ты опять ухватился только за дивергенции! в комбинаторе у нас факторы fvg, ob,
bos, choch, ote, discount/premium, ATR, WT, EQ-свипы, объём, momentum — а в v1 даже
пивотов нет».

Справедливо. Здесь СПЛОШНОЙ перебор ВСЕХ 149 флагов `compute_flags` (включая пивоты
1D/1W, Elliott, EQH/EQL, объём, momentum), но с тремя отличиями от старого комбинатора:

  1. МЕТРИКА — % net с костами 0.35%, а не avgR без костов
     (старый WR считал победой любой плюсовой ход → отбор шёл не по деньгам);
  2. ГОРИЗОНТ — 1d, где голая база уже PF 1.00-1.27, а не 15m/1h, где 0.49-0.84;
  3. КОНТРОЛЬ — каждый фактор мерится ПРОТИВ полной базы того же горизонта,
     иначе фильтр подменяет базу и врёт.

Сначала ОДИНОЧНЫЕ факторы (честная карта «что работает вообще»), затем пары из топа.
Глубже не идём: greedy до 5 факторов на тех же данных — машина ложных находок
(14 789 паттернов старого комбинатора, причинно плюсовых 5 из 153).

Запуск:  python scripts/all_factors_1d_scan.py [--coins 150] [--pairs]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations

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

# направление фактора: по имени понятно, какую сторону он предполагает
BULLISH = ("bull", "_up", "up_", "os_", "_os", "discount", "above", "eql", "long")
BEARISH = ("bear", "_down", "down_", "_ob", "ob_", "premium", "below", "eqh", "short")


def side_of(flag: str) -> str | None:
    f = flag.lower()
    b = any(k in f for k in BULLISH)
    s = any(k in f for k in BEARISH)
    if b and not s:
        return "long"
    if s and not b:
        return "short"
    return None                      # нейтральный — меряем обе стороны


def sim(df, side):
    n = len(df)
    H, L, C = df.high.values, df.low.values, df.close.values
    out = np.full(n, np.nan)
    sp = np.full(n, np.nan)
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
        else:
            sl = H[i - SL_LOOKBACK:i + 1].max() * 1.001
            if sl <= e:
                continue
            sp[i] = (sl - e) / e * 100
            tp = e - TP_R * (sl - e)
            hs, ht = fh >= sl, fl <= tp
        js = int(np.argmax(hs)) if hs.any() else 10 ** 9
        jt = int(np.argmax(ht)) if ht.any() else 10 ** 9
        if js <= jt and js < 10 ** 9:
            out[i] = -sp[i]
        elif jt < 10 ** 9:
            out[i] = TP_R * sp[i]
        else:
            out[i] = ((C[end] - e) if side == "long" else (e - C[end])) / e * 100
    return out, sp


def stat(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0:
        return None
    neg = abs(v[v < 0].sum())
    s = np.sort(v); cut = max(1, int(len(s) * 0.10))
    return dict(n=len(v), wr=100 * (v > 0).mean(),
                pf=(v[v > 0].sum() / neg if neg > 0 else 99.0),
                mean=float(v.mean()), med=float(np.median(v)),
                frag=float(s[:-cut].sum()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", type=int, default=150)
    ap.add_argument("--since", type=int, default=2023)
    ap.add_argument("--min-n", type=int, default=150)
    ap.add_argument("--pairs", action="store_true", help="добавить пары из топ-20")
    a = ap.parse_args()

    t0 = int(dt.datetime(a.since, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    syms = [r[0] for r in con.execute(
        "SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' AND time>=? "
        "GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?", (t0, a.coins)).fetchall()]
    con.close()

    print("═" * 122)
    print(f"ВСЕ ФАКТОРЫ НА 1d · {len(syms)} монет с {a.since} · TP={TP_R}R · TTL={TTL}б · "
          f"косты {COST}% · метрика % net")
    print("одиночные факторы против ПОЛНОЙ базы того же горизонта (контроль подмены базы)")
    print("═" * 122)

    acc = defaultdict(lambda: {"net": [], "yr": [], "sym": []})
    base = {"long": [], "short": []}
    flag_cols = None
    per_sym_flags = {}

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
        if flag_cols is None:
            flag_cols = [c_ for c_ in F.columns]
        rl, _ = sim(d, "long")
        rs, _ = sim(d, "short")
        ok_l, ok_s = ~np.isnan(rl), ~np.isnan(rs)
        base["long"].extend((rl[ok_l] - COST).tolist())
        base["short"].extend((rs[ok_s] - COST).tolist())
        yrs = d.index.year.values

        keep = {}
        for col in flag_cols:
            try:
                arr = np.asarray(F[col].fillna(False), dtype=bool)
            except Exception:
                continue
            if arr.sum() < 3 or arr.sum() > 0.6 * len(arr):
                continue
            keep[col] = arr
            sd = side_of(col)
            sides = [sd] if sd else ["long", "short"]
            for s_ in sides:
                r, ok = (rl, ok_l) if s_ == "long" else (rs, ok_s)
                m = arr & ok
                if not m.any():
                    continue
                key = f"{col}|{s_}"
                acc[key]["net"].extend((r[m] - COST).tolist())
                acc[key]["yr"].extend(yrs[m].tolist())
                acc[key]["sym"].extend([sym] * int(m.sum()))
        per_sym_flags[sym] = (keep, rl, rs, ok_l, ok_s, yrs)
        if si % 25 == 0:
            print(f"  … монет обработано: {si}/{len(syms)}")

    bl, bs = stat(base["long"]), stat(base["short"])
    print(f"\n=== БАЗА 1d (вход на каждом баре) ===")
    for nm, s in (("LONG", bl), ("SHORT", bs)):
        if s:
            print(f"  {nm:<6} n={s['n']:>7} WR {s['wr']:>5.1f}% PF {s['pf']:>5.2f} "
                  f"{s['mean']:>+8.3f}%/сд")

    rows = []
    for key, d_ in acc.items():
        s = stat(d_["net"])
        if not s or s["n"] < a.min_n:
            continue
        col, sd = key.split("|")
        b = bl if sd == "long" else bs
        s["lift"] = s["mean"] - (b["mean"] if b else 0)
        rows.append((col, sd, s, d_))
    rows.sort(key=lambda x: -x[2]["mean"])

    print(f"\n=== ОДИНОЧНЫЕ ФАКТОРЫ (n ≥ {a.min_n}) — всего {len(rows)} ===")
    print(f"{'фактор':<34} {'стор':<6} {'n':>7} {'WR':>7} {'PF':>7} {'%/сд net':>11} "
          f"{'над базой':>11} {'безтоп10%':>11}")
    print("─" * 122)
    for col, sd, s, _ in rows[:30]:
        mark = "🟢" if s["mean"] > 0 else "  "
        print(f"{mark}{col[:32]:<32} {sd:<6} {s['n']:>7} {s['wr']:>6.1f}% {s['pf']:>7.2f} "
              f"{s['mean']:>+10.3f}% {s['lift']:>+10.3f}% {s['frag']:>+10.1f}")
    pos = [r for r in rows if r[2]["mean"] > 0]
    print(f"\nплюсовых факторов: {len(pos)} из {len(rows)}")

    print(f"\n=== ТОП-10: РАЗРЕЗ ПО ГОДАМ + ОХВАТ ===")
    for col, sd, s, d_ in rows[:10]:
        net = np.array(d_["net"]); yr = np.array(d_["yr"]); sy = np.array(d_["sym"])
        line = f"  {col[:30]:<32}{sd:<6}"
        for y in sorted(set(yr.tolist())):
            ss = stat(net[yr == y])
            if ss and ss["n"] >= 30:
                line += f" {y}:{ss['mean']:+.2f}%"
        per = pd.Series(net).groupby(pd.Series(sy)).mean()
        line += f"  охват {int((per > 0).sum())}/{len(per)}"
        print(line)

    if a.pairs and len(pos) >= 2:
        print(f"\n=== ПАРЫ ИЗ ТОП-14 ОДИНОЧНЫХ (той же стороны) ===")
        top = [(c_, s_) for c_, s_, _, _ in pos[:14]]
        pair_rows = []
        for (c1, s1), (c2, s2) in combinations(top, 2):
            if s1 != s2:
                continue
            vals, yrs_, syms_ = [], [], []
            for sym, (keep, rl, rs, ok_l, ok_s, yrs) in per_sym_flags.items():
                if c1 not in keep or c2 not in keep:
                    continue
                r, ok = (rl, ok_l) if s1 == "long" else (rs, ok_s)
                m = keep[c1] & keep[c2] & ok
                if not m.any():
                    continue
                vals.extend((r[m] - COST).tolist())
                yrs_.extend(yrs[m].tolist()); syms_.extend([sym] * int(m.sum()))
            s = stat(vals)
            if s and s["n"] >= max(60, a.min_n // 3):
                b = bl if s1 == "long" else bs
                s["lift"] = s["mean"] - (b["mean"] if b else 0)
                pair_rows.append((c1, c2, s1, s, np.array(vals), np.array(yrs_), np.array(syms_)))
        pair_rows.sort(key=lambda x: -x[3]["mean"])
        print(f"{'пара':<52} {'стор':<6} {'n':>6} {'WR':>7} {'PF':>7} {'%/сд net':>11} "
              f"{'над базой':>11}")
        print("─" * 122)
        for c1, c2, sd, s, _, _, _ in pair_rows[:20]:
            mark = "🟢" if s["mean"] > 0 else "  "
            nm = f"{c1[:24]} + {c2[:22]}"
            print(f"{mark}{nm:<50} {sd:<6} {s['n']:>6} {s['wr']:>6.1f}% {s['pf']:>7.2f} "
                  f"{s['mean']:>+10.3f}% {s['lift']:>+10.3f}%")
        print(f"\nплюсовых пар: {sum(1 for r in pair_rows if r[3]['mean'] > 0)} из {len(pair_rows)}")
        if pair_rows:
            print(f"\n=== ТОП-5 ПАР: ГОДЫ + ОХВАТ ===")
            for c1, c2, sd, s, net, yr, sy in pair_rows[:5]:
                line = f"  {c1[:22]}+{c2[:20]} [{sd}]"
                for y in sorted(set(yr.tolist())):
                    ss = stat(net[yr == y])
                    if ss and ss["n"] >= 20:
                        line += f"  {y}:{ss['mean']:+.2f}%"
                per = pd.Series(net).groupby(pd.Series(sy)).mean()
                line += f"  охват {int((per > 0).sum())}/{len(per)} · безтоп10% {s['frag']:+.0f}"
                print(line)

    print("\n" + "═" * 122)
    print("«над базой» = сколько фактор добавляет к входу на каждом баре той же стороны.")
    print("Фактор с большим %/сд, но нулевым lift — просто повторяет базу, а не даёт эдж.")
    print("═" * 122)
    return 0


if __name__ == "__main__":
    sys.exit(main())
