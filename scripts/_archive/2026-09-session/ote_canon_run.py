# -*- coding: utf-8 -*-
"""OTE ПО КАНОНУ НА ЭТАЛОННОЙ НОГЕ + ТРИГГЕР МИКРОСТРУКТУРЫ (05.09.2026).

Егор: «ты ведь понимаешь по структуре и мультиструктуре, где импульс, где слом и где искать
OTE по теории? У нас нет 2-3 недель».

Канон, собранный из ЭТАЛОНА (`oko_sm_engine.run_structure`, swing_len=50 + internal_len=5):
  1. СТАРШИЙ ТФ (1h) даёт НОГУ: `leg_history[t]` = {origin, extreme, trend} — ровно так,
     как Егор размечает руками (origin = HL/Weak Low, extreme = Strong High для лонга).
  2. ЗОНА OTE строится ОТ ЭТОЙ НОГИ: 0.618-0.786 отката от extreme к origin.
  3. МЛАДШИЙ ТФ (15m) даёт ТРИГГЕР: слом ВНУТРЕННЕЙ структуры (internal CHoCH/BOS,
     len=5) в сторону ноги — «вход по слому на 3m», о котором Егор говорил.
  4. ОПРАВА из стенда геометрии: стоп за origin ноги (структурный), цель — на выбор:
     ближайший swing / extreme ноги / фибо-расширение / 1R (для сравнения).

🔴 Причинность: нога берётся с ЗАКРЫТОГО бара 1h (shift+ffill), события младшего — по бару
их подтверждения. Контроль — случайный вход той же оправы. Косты явной ставкой, счёт в %.

Отличие от `ote_zone_no_edge_even_on_correct_leg` (10.08, PF 0.87): там был вход ПО ЗОНЕ без
триггера и до сведения SMC на эталон (02.09). Здесь зона + триггер микроструктуры + оправа.
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
HOLD = 96                    # 24 ч на 15m
OTE_LO, OTE_HI = 0.618, 0.786


def leg_series(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Нога эталона на каждом баре 1h (origin/extreme/trend), каузально."""
    from core.smc.oko_sm_engine import run_structure
    d = df_1h.reset_index(drop=True)
    st = run_structure(d, swing_len=50, internal_len=5, record_legs=True)
    rows = []
    for lg in st.leg_history:
        if not lg:
            rows.append((np.nan, np.nan, 0))
        else:
            rows.append((float(lg["origin"]), float(lg["extreme"]),
                         1 if lg["trend"] == "long" else -1))
    out = pd.DataFrame(rows, columns=["origin", "extreme", "ltrend"], index=df_1h.index[:len(rows)])
    return out


def micro_breaks(df_15m: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Сломы ВНУТРЕННЕЙ структуры (len=5) на 15m: (бычий, медвежий) по бару подтверждения."""
    from core.smc.oko_sm_engine import run_structure
    d = df_15m.reset_index(drop=True)
    st = run_structure(d, swing_len=50, internal_len=5)
    n = len(d)
    up = np.zeros(n, dtype=bool)
    dn = np.zeros(n, dtype=bool)
    # SMEvent(i, kind='BOS'|'CHoCH', bull: bool, level, internal: bool, level_i)
    for ev in st.events:
        if not getattr(ev, "internal", False):      # берём ТОЛЬКО микроструктуру (len=5)
            continue
        bar = int(getattr(ev, "i", -1))
        if 0 <= bar < n:
            (up if getattr(ev, "bull", False) else dn)[bar] = True
    return up, dn


def micro_levels(df_15m: pd.DataFrame, length: int = 5):
    """Последний ПОДТВЕРЖДЁННЫЙ микро-экстремум на каждом баре (тот же масштаб, что триггер).

    🔴 Егор: «триггер сломом микроструктуры len=5, а стоп за структуру len=50?» — масштабы
    обязаны совпадать. Вход по микро-слому ⇒ стоп за МИКРО-экстремум, иначе стоп 4-8%
    вместо долей процента и RR рушится (та же ошибка стоила RR 7:1 → 0.33 в июне).
    """
    from core.smc.oko_sm_engine import _swings
    n = len(df_15m)
    hi = np.full(n, np.nan)
    lo = np.full(n, np.nan)
    cur_hi = cur_lo = np.nan
    conf: dict[int, list] = {}
    for conf_i, sw_i, price, is_top in _swings(df_15m["high"], df_15m["low"], length):
        conf.setdefault(int(conf_i), []).append((float(price), bool(is_top)))
    for t in range(n):
        for price, is_top in conf.get(t, ()):
            if is_top:
                cur_hi = price
            else:
                cur_lo = price
        hi[t], lo[t] = cur_hi, cur_lo
    return hi, lo


def simulate(H, L, C, pos, e, d, sl, tp, hold=HOLD):
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hs = (lo <= sl) if d > 0 else (hi >= sl)
    ht = (hi >= tp) if d > 0 else (lo <= tp)
    i_s = int(np.argmax(hs)) if hs.any() else 10 ** 9
    i_t = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if i_s == 10 ** 9 and i_t == 10 ** 9:
        return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d
    return (sl - e) / e * 100.0 * d if i_s <= i_t else (tp - e) / e * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--max-stop", type=float, default=15.0)
    ap.add_argument("--no-trigger", action="store_true", help="без триггера — как было 10.08")
    a = ap.parse_args()

    syms = core_universe("15m", n=a.symbols)
    print(f"OTE ПО КАНОНУ · {len(syms)} монет · нога с 1h (эталон swing_len=50) · "
          f"зона {OTE_LO}-{OTE_HI} · триггер: {'НЕТ' if a.no_trigger else 'слом internal len=5 на 15m'}")
    print(f"горизонт {HOLD} баров (24 ч) · косты {a.cost}%\n")

    rng = np.random.default_rng(53)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        try:
            d15 = load(sym, "15m")
            d1h = load(sym, "1h")
        except Exception:                                   # noqa: BLE001
            continue
        if d15 is None or d1h is None or len(d15) < 5000 or len(d1h) < 1000:
            continue
        flat = float(((d15.open == d15.high) & (d15.high == d15.low) & (d15.low == d15.close)).mean())
        if flat > 0.10:
            continue
        try:
            LEG = leg_series(d1h)
            up, dn = micro_breaks(d15)
            m_hi, m_lo = micro_levels(d15)
        except Exception as e:                              # noqa: BLE001
            print(f"  ⚠ {sym}: {type(e).__name__}: {str(e)[:60]}")
            continue
        # 🔴 нога с ЗАКРЫТОГО бара 1h → shift(1), затем на сетку 15m
        LG = LEG.shift(1).reindex(d15.index, method="ffill")
        H, L, C = d15.high.values, d15.low.values, d15.close.values
        org, ext, ltr = LG.origin.values, LG.extreme.values, LG.ltrend.values
        years = d15.index.year.values
        n = len(C)
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        last = -10 ** 9
        for p in range(300, n - HOLD - 1):
            t = int(ltr[p]) if ltr[p] == ltr[p] else 0
            if t == 0 or not (org[p] == org[p] and ext[p] == ext[p]):
                continue
            o, x = float(org[p]), float(ext[p])
            amp = abs(x - o)
            if amp <= 0:
                continue
            # зона OTE: откат от extreme к origin на 0.618-0.786
            if t > 0:
                z_hi, z_lo = x - OTE_LO * amp, x - OTE_HI * amp
            else:
                z_lo, z_hi = x + OTE_LO * amp, x + OTE_HI * amp
            c = float(C[p])
            if not (min(z_lo, z_hi) <= c <= max(z_lo, z_hi)):
                continue
            if not a.no_trigger:                            # ТРИГГЕР: слом младшего в сторону ноги
                if not (up[p] if t > 0 else dn[p]):
                    continue
            if p - last < 4:
                continue
            last = p
            d = t
            # 🔴 СТОП В МАСШТАБЕ ТРИГГЕРА: за последний МИКРО-экстремум (len=5), а не за
            # origin ноги len=50 — иначе вход микро, а риск макро (поймал Егор 05.09).
            mk = m_lo[p] if d > 0 else m_hi[p]
            if not (mk == mk):
                continue
            sl = mk * (1 - 0.002) if d > 0 else mk * (1 + 0.002)
            if (d > 0 and sl >= c) or (d < 0 and sl <= c):
                continue
            sp = abs(c - sl) / c * 100.0
            if not (0.15 <= sp <= a.max_stop):
                continue
            targets = {
                "extreme ноги": x,
                "фибо −0.618": (x + 0.618 * amp) if d > 0 else (x - 0.618 * amp),
                "1R": c * (1 + d * sp / 100.0),
                "2R": c * (1 + d * 2 * sp / 100.0),
            }
            for tname, tp in targets.items():
                if (d > 0 and tp <= c) or (d < 0 and tp >= c):
                    continue
                r = simulate(H, L, C, p, c, d, sl, tp)
                if r is None:
                    continue
                rows.append((sym, oos, int(years[p]), "LONG" if d > 0 else "SHORT",
                             tname, sp, r - a.cost, 0))
                q = int(rng.integers(300, n - HOLD - 1))    # контроль: та же оправа, случайный бар
                ec = float(C[q])
                slc = ec * (1 - d * sp / 100.0)
                tpc = ec * (1 + d * abs(tp - c) / c * 100.0 / 100.0 * (1 if d > 0 else 1))
                tpc = ec * (1 + d * (abs(tp - c) / c))
                rc = simulate(H, L, C, q, ec, d, slc, tpc)
                if rc is not None:
                    rows.append((sym, oos, int(years[q]), "LONG" if d > 0 else "SHORT",
                                 tname, sp, rc - a.cost, 1))
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сигналов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "target", "sp", "r", "ctrl"])
    R.to_parquet(ROOT / "cache" / "ote_canon.parquet")
    S, K = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nсобрано: сигналов {len(S):,} · {S.sym.nunique()} монет · {S.year.min()}-{S.year.max()}\n")

    def st(x, nm, ind="   "):
        if len(x) < 50:
            print(f"{ind}{nm:26s} n={len(x)} — мало")
            return
        v = np.sort(x.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"{ind}{nm:26s} n={len(x):>6,} медиана={np.median(v):>+7.3f}% среднее={v.mean():>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")

    print("=" * 118)
    print("ЦЕЛИ: СИГНАЛ против КОНТРОЛЯ")
    print("=" * 118)
    for tname in S.target.unique():
        st(S[S.target == tname], f"{tname} · СИГНАЛ")
        st(K[K.target == tname], f"{tname} · контроль")
        print()

    best = max(S.target.unique(), key=lambda t: S[S.target == t].r.mean())
    B = S[S.target == best]
    print("=" * 118)
    print(f"РАЗРЕЗЫ ЛУЧШЕЙ ЦЕЛИ: {best}")
    print("=" * 118)
    for d in ("SHORT", "LONG"):
        st(B[B.dir == d], d)
    print()
    for y in sorted(B.year.unique()):
        st(B[B.year == y], f"год {y}")
    print()
    st(B[~B.oos], "IS (половина монет)")
    st(B[B.oos], "OOS (другая половина)")
    st(K[(K.target == best) & K.oos], "OOS контроль")
    print()
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        st(B[(B.sp >= lo) & (B.sp < hi)], f"стоп {lo}-{hi}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
