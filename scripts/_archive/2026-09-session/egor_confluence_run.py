# -*- coding: utf-8 -*-
"""КОНФЛЮЭНЦИЯ ЕГОРА: ПИВОТ + ФИБО + WT/RSI (06.09.2026).

Егор: «я в анализе опираюсь только на уровни пивотов, фибо и WT/RSI».

🔴 Егор: «структура ОЧЕНЬ ВАЖНА! одно моё утверждение НЕ отменяет остальных».
Поэтому здесь ВСЁ ВМЕСТЕ, и меряется РОСТ КАЧЕСТВА ПО ЧИСЛУ СОВПАВШИХ УСЛОВИЙ:

  1. ПИВОТ    — цена у уровня D / W / 4h (PP, R1-R3, S1-S3), дистанция ≤ порога;
  2. ФИБО     — та же точка лежит в зоне коррекции 0.5-0.786 последнего импульса;
  3. WT/RSI   — осциллятор подтверждает: OS/OB + разворот линий;
  4. СТРУКТУРА — контекст старшего слоя (лои/хаи не обновлялись) совпадает с направлением;
  5. МАГНИТ   — незакрытый имбаланс старшего ТФ по ходу сделки.

Вход по касанию, стоп за экстремум импульса, цели — фибо-расширения и ближайший пивот.
Меряется вклад КАЖДОГО условия по отдельности и всех вместе (конфлюэнция).

Контроль — случайный вход той же геометрии. Косты явной ставкой, счёт в % цены.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load, core_universe          # noqa: E402

COST = 0.35
HOLD = 384
PIV_NEAR = 0.3          # «у пивота», % цены
SW = 20                 # длина свингов для импульса под фибо


def pivots(df: pd.DataFrame):
    """Уровни пивотов D/W/4h на сетке бара (только ПРОШЛЫЙ закрытый период)."""
    arrs = []
    for rule in ("1D", "1W", "4h"):
        try:
            agg = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
            if len(agg) < 3:
                continue
            pp = (agg.high + agg.low + agg.close) / 3.0
            lv = pd.DataFrame({
                "PP": pp, "R1": 2 * pp - agg.low, "S1": 2 * pp - agg.high,
                "R2": pp + (agg.high - agg.low), "S2": pp - (agg.high - agg.low),
                "R3": agg.high + 2 * (pp - agg.low), "S3": agg.low - 2 * (agg.high - pp),
            }).shift(1).reindex(df.index, method="ffill")
            arrs.append(lv.values)
        except Exception:                                   # noqa: BLE001
            continue
    return arrs


def osc(df: pd.DataFrame):
    """WT и RSI + дивергенции — три инструмента Егора (эталонные функции)."""
    from core.indicators.indicators import calculate_wt
    from core.calculators.combinator_core import rsi as _rsi
    w = calculate_wt(df)
    wt1 = np.asarray(w["wt1"].values, dtype=float)
    wt2 = np.asarray(w["wt2"].values, dtype=float)
    rs = np.asarray(_rsi(df.close.values, 14), dtype=float)
    return wt1, wt2, rs


def legs(df: pd.DataFrame):
    """Последний импульс (origin→extreme) на каждом баре — под сетку фибо.

    Импульс = ход между соседними подтверждёнными свингами (эталон _swings).
    """
    from core.smc.oko_sm_engine import _swings
    n = len(df)
    o = np.full(n, np.nan); e = np.full(n, np.nan); dr = np.zeros(n, dtype=int)
    conf: dict[int, list] = {}
    for conf_i, sw_i, price, is_top in _swings(df["high"], df["low"], SW):
        conf.setdefault(int(conf_i), []).append((float(price), bool(is_top)))
    last_hi = last_lo = np.nan
    hi_t = lo_t = -1
    for t in range(n):
        for price, is_top in conf.get(t, ()):
            if is_top:
                last_hi, hi_t = price, t
            else:
                last_lo, lo_t = price, t
        if last_hi == last_hi and last_lo == last_lo:
            if hi_t > lo_t:                     # импульс ВВЕРХ: low → high
                o[t], e[t], dr[t] = last_lo, last_hi, 1
            else:                               # импульс ВНИЗ: high → low
                o[t], e[t], dr[t] = last_hi, last_lo, -1
    return o, e, dr


def sim(H, L, C, p, entry, d, sl, tp, hold=HOLD):
    lo, hi = L[p:p + hold], H[p:p + hold]
    if len(lo) == 0:
        return None
    hs = (lo <= sl) if d > 0 else (hi >= sl)
    ht = (hi >= tp) if d > 0 else (lo <= tp)
    i_s = int(np.argmax(hs)) if hs.any() else 10 ** 9
    i_t = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if i_s == 10 ** 9 and i_t == 10 ** 9:
        return (float(C[min(p + hold, len(C) - 1)]) - entry) / entry * 100.0 * d
    return (sl - entry) / entry * 100.0 * d if i_s <= i_t else (tp - entry) / entry * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=25)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--max-stop", type=float, default=15.0)
    a = ap.parse_args()

    syms = core_universe(a.tf, n=a.symbols)
    print(f"КОНФЛЮЭНЦИЯ ЕГОРА · {len(syms)} монет · {a.tf} · ТОЛЬКО пивоты + фибо + WT/RSI")
    print(f"(без структуры и имбалансов) · косты {a.cost}% · держим {HOLD} баров\n")

    rng = np.random.default_rng(83)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        try:
            df = load(sym, a.tf)
        except Exception:                                   # noqa: BLE001
            continue
        if df is None or len(df) < 4000:
            continue
        if float(((df.open == df.high) & (df.high == df.low) & (df.low == df.close)).mean()) > 0.10:
            continue
        try:
            PV = pivots(df)
            wt1, wt2, rs = osc(df)
            og, ex, dr = legs(df)
            # СТРУКТУРА: контекст старшего слоя эталона (Егор: «структура ОЧЕНЬ ВАЖНА»)
            from core.smc.oko_sm_engine import run_structure
            _st = run_structure(df.reset_index(drop=True), swing_len=50, internal_len=5)
            ctx = np.zeros(len(df), dtype=int)
            _cur = 0
            _maj = {int(e_.i): (1 if bool(e_.bull) else -1)
                    for e_ in _st.events if not bool(getattr(e_, "internal", False))}
            for _t in range(len(df)):
                if _t in _maj:
                    _cur = _maj[_t]
                ctx[_t] = _cur
            # МАГНИТ: имбаланс 1h по направлению
            from egor_fib_grid import htf_fvg_on_grid
            mg_up, mg_dn = htf_fvg_on_grid(sym, df.index, "1h")
        except Exception as e:                              # noqa: BLE001
            print(f"  ⚠ {sym}: {type(e).__name__}: {str(e)[:50]}")
            continue
        H, L, C = df.high.values, df.low.values, df.close.values
        years = df.index.year.values
        n = len(C)
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        last = -10 ** 9
        for t in range(300, n - HOLD - 1):
            d = int(dr[t])
            if d == 0 or not (og[t] == og[t] and ex[t] == ex[t]):
                continue
            if t - last < 8:
                continue
            o, x = float(og[t]), float(ex[t])
            amp = abs(x - o)
            if amp <= 0:
                continue
            c = float(C[t])
            # ── 1. ФИБО: цена в зоне коррекции 0.5-0.786 импульса ────────
            z1 = x - 0.5 * amp if d > 0 else x + 0.5 * amp
            z2 = x - 0.786 * amp if d > 0 else x + 0.786 * amp
            in_fib = min(z1, z2) <= c <= max(z1, z2)
            # ── 2. ПИВОТ: дистанция до ближайшего уровня ─────────────────
            pd_ = 99.0
            for arr in PV:
                for v in arr[t]:
                    if v == v and v > 0:
                        pd_ = min(pd_, abs(c - float(v)) / c * 100.0)
            near_piv = pd_ <= PIV_NEAR
            # ── 3. WT/RSI: осциллятор подтверждает разворот ──────────────
            if not (wt1[t] == wt1[t] and rs[t] == rs[t]):
                continue
            if d > 0:
                osc_ok = (wt1[t] < -45 or rs[t] < 38) and wt1[t] > wt2[t]
            else:
                osc_ok = (wt1[t] > 45 or rs[t] > 62) and wt1[t] < wt2[t]
            # ── 4. СТРУКТУРА: контекст совпадает с направлением сделки ───
            struct_ok = ctx[t] != 0 and (ctx[t] > 0) == (d > 0)
            # ── 5. МАГНИТ: имбаланс старшего ТФ по ходу ──────────────────
            mag_ok = False
            if mg_up is not None and mg_dn is not None:
                mv = mg_up[t] if d > 0 else mg_dn[t]
                mag_ok = bool(mv == mv and ((mv > c) if d > 0 else (mv < c)))
            n_conf = int(in_fib) + int(near_piv) + int(osc_ok) + int(struct_ok) + int(mag_ok)
            if n_conf == 0:
                continue
            last = t
            sl = (o * (1 - 0.002)) if d > 0 else (o * (1 + 0.002))
            if (d > 0 and sl >= c) or (d < 0 and sl <= c):
                continue
            sp = abs(c - sl) / c * 100.0
            if not (0.15 <= sp <= a.max_stop):
                continue
            tps = {"fib-0.62": x + d * 0.62 * amp, "fib-1.0": x + d * 1.0 * amp,
                   "extreme": x}
            for tn, tp in tps.items():
                if (d > 0 and tp <= c) or (d < 0 and tp >= c):
                    continue
                r = sim(H, L, C, t, c, d, sl, tp)
                if r is None:
                    continue
                rr = abs(tp - c) / abs(c - sl)
                rows.append((sym, oos, int(years[t]), "LONG" if d > 0 else "SHORT", tn,
                             int(in_fib), int(near_piv), int(osc_ok), int(struct_ok),
                             int(mag_ok), n_conf, sp, rr, r - a.cost, 0))
                q = int(rng.integers(300, n - HOLD - 1))
                ec = float(C[q])
                rc = sim(H, L, C, q, ec, d, ec * (1 - d * sp / 100.0),
                         ec * (1 + d * sp * rr / 100.0))
                if rc is not None:
                    rows.append((sym, oos, int(years[q]), "LONG" if d > 0 else "SHORT", tn,
                                 int(in_fib), int(near_piv), int(osc_ok), int(struct_ok),
                                 int(mag_ok), n_conf, sp, rr, rc - a.cost, 1))
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сетапов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "tp", "fib", "piv", "osc",
                                    "struct", "mag", "nconf", "sp", "rr", "r", "ctrl"])
    R.to_parquet(ROOT / "cache" / "egor_confluence.parquet")
    S, K = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nстрок {len(S):,} · монет {S.sym.nunique()} · {S.year.min()}-{S.year.max()}\n")

    def st(x, nm):
        if len(x) < 60:
            print(f"   {nm:36s} n={len(x)} — мало")
            return
        v = np.sort(x.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"   {nm:36s} n={len(x):>6,} ср={v.mean():>+7.3f}% мед={np.median(v):>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")

    for tname in ("fib-0.62", "fib-1.0", "extreme"):
        T = S[S.tp == tname]; KT = K[K.tp == tname]
        if len(T) < 100:
            continue
        print("=" * 116)
        print(f"ЦЕЛЬ {tname}")
        print("=" * 116)
        st(T, "ВСЁ"); st(KT, "контроль")
        print("   ── вклад КАЖДОГО условия ──")
        for col, nm in (("fib", "фибо-зона"), ("piv", "пивот"), ("osc", "WT/RSI"),
                        ("struct", "СТРУКТУРА"), ("mag", "магнит")):
            st(T[T[col] == 1], f"{nm} = да")
            st(T[T[col] == 0], f"{nm} = нет")
        print("   ── 🎯 РОСТ ПО ЧИСЛУ СОВПАВШИХ УСЛОВИЙ ──")
        for nc in range(1, 6):
            st(T[T.nconf == nc], f"сошлось {nc} из 5")
            st(KT[KT.nconf == nc], f"   контроль {nc}")
        C3 = T[T.nconf >= 4]
        K3 = KT[KT.nconf >= 4]
        st(C3, "🎯 4-5 УСЛОВИЙ"); st(K3, "   контроль 4-5")
        if len(C3) >= 100:
            st(C3[~C3.oos], "   IS"); st(C3[C3.oos], "   OOS")
            st(K3[K3.oos], "   OOS контроль")
            for d in ("LONG", "SHORT"):
                st(C3[C3.dir == d], f"   {d}")
            for y in sorted(C3.year.unique()):
                st(C3[C3.year == y], f"   год {y}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
