# -*- coding: utf-8 -*-
"""ПЕРЕСБОРКА МЕТОДА: КОНТЕКСТ СТАРШИЙ → ВХОД МЛАДШИЙ → ЦЕЛЬ СТАРШАЯ (06.09.2026).

Собрано под четыре поправки Егора, каждая — его словами:

  1. «Волатильностные уровни — это НАШИ ПИВОТЫ»: PP = разворотный (выше long, ниже short),
     R1/S1 = границы ФЛЭТА, R2/S2 = поддержка/сопротивление. Не «дистанция до ближайшего».
  2. «Зайдя на минутном ТФ, могу ставить цель часовую или четырёхчасовую» —
     ВХОД И СТОП В МАСШТАБЕ МЛАДШЕГО, ЦЕЛЬ В МАСШТАБЕ СТАРШЕГО. Отсюда RR 7:1.
  3. «Смотрю дневной → 4h → часовой, если интересно — спускаюсь ниже» — контекст сверху.
  4. «Косты: песочница имеет большой спред, наши результаты ЗАНИЖЕНЫ» — считаем при
     двух ставках: 0.35% (лимит) и 0.10% (мейкер), чтобы видеть обе границы.

СХЕМА:
  КОНТЕКСТ (4h): структура эталона — тренд (лои/хаи не обновляются) + сторона от PP дневного
  ЗОНА    (1h): фибо-коррекция 0.5-0.786 импульса 1h, совпавшая с пивотом D/W/4h
  ВХОД    (5m): слом микроструктуры в сторону контекста ВНУТРИ зоны
  СТОП    (5m): за микро-экстремум — масштаб входа
  ЦЕЛЬ    (1h/4h): ближайший пивот по ходу ИЛИ фибо-расширение импульса 1h

Контроль: случайный вход той же геометрии в том же окне. Счёт в % цены.
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

from research_harness import load, core_universe, universe   # noqa: E402

HOLD = 576              # 48 ч на 5m — цель старшего ТФ требует времени
SW_MICRO = 5            # микроструктура на входном ТФ
SW_MAJOR = 50           # структура старшего


def pivot_levels(df: pd.DataFrame, rule: str):
    """PP/R1/R2/S1/S2 периода `rule` на сетке df. Только ПРОШЛЫЙ закрытый период."""
    agg = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(agg) < 3:
        return None
    pp = (agg.high + agg.low + agg.close) / 3.0
    lv = pd.DataFrame({
        "PP": pp,
        "R1": 2 * pp - agg.low, "S1": 2 * pp - agg.high,
        "R2": pp + (agg.high - agg.low), "S2": pp - (agg.high - agg.low),
    }).shift(1)
    return lv.reindex(df.index, method="ffill")


def struct_trend(df: pd.DataFrame, swing_len: int = SW_MAJOR):
    """Тренд структуры эталона: +1 пока лои не обновляются, −1 пока не обновляются хаи."""
    from core.smc.oko_sm_engine import run_structure
    st = run_structure(df.reset_index(drop=True), swing_len=swing_len, internal_len=5)
    n = len(df)
    tr = np.zeros(n, dtype=int)
    cur = 0
    ev = {int(e.i): (1 if bool(e.bull) else -1)
          for e in st.events if not bool(getattr(e, "internal", False))}
    for i in range(n):
        if i in ev:
            cur = ev[i]
        tr[i] = cur
    return pd.Series(tr, index=df.index)


def last_leg(df: pd.DataFrame, swing_len: int = 20):
    """Последний импульс origin→extreme на каждом баре (для сетки фибо)."""
    from core.smc.oko_sm_engine import pivot_points
    n = len(df)
    o = np.full(n, np.nan); e = np.full(n, np.nan); d = np.zeros(n, dtype=int)
    conf: dict[int, list] = {}
    for ci, si, price, is_top in pivot_points(df["high"], df["low"], swing_len):
        conf.setdefault(int(ci), []).append((float(price), bool(is_top)))
    hi = lo = np.nan
    hi_t = lo_t = -1
    for t in range(n):
        for price, is_top in conf.get(t, ()):
            if is_top:
                hi, hi_t = price, t
            else:
                lo, lo_t = price, t
        if hi == hi and lo == lo:
            if hi_t > lo_t:
                o[t], e[t], d[t] = lo, hi, 1
            else:
                o[t], e[t], d[t] = hi, lo, -1
    return o, e, d


def micro_breaks_and_levels(df: pd.DataFrame):
    """Сломы микроструктуры (len=5) + последний микро-экстремум — на ВХОДНОМ ТФ."""
    from core.smc.oko_sm_engine import run_structure, pivot_points
    n = len(df)
    st = run_structure(df.reset_index(drop=True), swing_len=SW_MAJOR, internal_len=SW_MICRO)
    up = np.zeros(n, dtype=bool); dn = np.zeros(n, dtype=bool)
    for e in st.events:
        if not bool(getattr(e, "internal", False)):
            continue
        i = int(e.i)
        if 0 <= i < n:
            (up if bool(e.bull) else dn)[i] = True
    m_hi = np.full(n, np.nan); m_lo = np.full(n, np.nan)
    cur_hi = cur_lo = np.nan
    conf: dict[int, list] = {}
    for ci, si, price, is_top in pivot_points(df["high"], df["low"], SW_MICRO):
        conf.setdefault(int(ci), []).append((float(price), bool(is_top)))
    for t in range(n):
        for price, is_top in conf.get(t, ()):
            if is_top:
                cur_hi = price
            else:
                cur_lo = price
        m_hi[t], m_lo[t] = cur_hi, cur_lo
    return up, dn, m_hi, m_lo


def sim(H, L, C, p, e, d, sl, tp, hold=HOLD):
    lo, hi = L[p:p + hold], H[p:p + hold]
    if len(lo) == 0:
        return None, None
    hs = (lo <= sl) if d > 0 else (hi >= sl)
    ht = (hi >= tp) if d > 0 else (lo <= tp)
    i_s = int(np.argmax(hs)) if hs.any() else 10 ** 9
    i_t = int(np.argmax(ht)) if ht.any() else 10 ** 9
    if i_s == 10 ** 9 and i_t == 10 ** 9:
        return (float(C[min(p + hold, len(C) - 1)]) - e) / e * 100.0 * d, "время"
    if i_s <= i_t:
        return (sl - e) / e * 100.0 * d, "стоп"
    return (tp - e) / e * 100.0 * d, "цель"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=25)
    ap.add_argument("--entry-tf", default="5m")
    ap.add_argument("--zone-tf", default="1h")
    ap.add_argument("--ctx-tf", default="4h")
    ap.add_argument("--max-stop", type=float, default=6.0)
    ap.add_argument("--min-rr", type=float, default=1.5)
    a = ap.parse_args()

    # 🔴 кэш 5m покрывает только 2025-2026 → core_universe(5m) падает по покрытию окна.
    # Вселенную берём по ЗОНЕ-ТФ (там покрытие полное), данные входного ТФ грузим по факту.
    try:
        syms = core_universe(a.entry_tf, n=a.symbols)
    except Exception:                                       # noqa: BLE001
        syms = universe(a.entry_tf, n=a.symbols)
    print(f"ПЕРЕСБОРКА · {len(syms)} монет · контекст {a.ctx_tf} → зона {a.zone_tf} → "
          f"вход {a.entry_tf}")
    print(f"стоп в масштабе ВХОДА · цель в масштабе СТАРШЕГО · держим {HOLD} баров · "
          f"косты 0.35% и 0.10%\n")

    rng = np.random.default_rng(97)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        try:
            d_in = load(sym, a.entry_tf)
            d_zone = load(sym, a.zone_tf)
            d_ctx = load(sym, a.ctx_tf)
        except Exception:                                   # noqa: BLE001
            continue
        if any(x is None or len(x) < 500 for x in (d_in, d_zone, d_ctx)):
            continue
        if float(((d_in.open == d_in.high) & (d_in.high == d_in.low) &
                  (d_in.low == d_in.close)).mean()) > 0.10:
            continue
        try:
            # КОНТЕКСТ: тренд структуры 4h + положение относительно дневного PP
            ctx = struct_trend(d_ctx).shift(1).reindex(d_in.index, method="ffill").fillna(0)
            pivD = pivot_levels(d_in, "1D")
            pivW = pivot_levels(d_in, "1W")
            piv4 = pivot_levels(d_in, "4h")
            # ЗОНА: импульс старшего ТФ под сетку фибо
            zo, ze, zd = last_leg(d_zone)
            ZO = pd.Series(zo, index=d_zone.index).shift(1).reindex(d_in.index, method="ffill")
            ZE = pd.Series(ze, index=d_zone.index).shift(1).reindex(d_in.index, method="ffill")
            ZD = pd.Series(zd, index=d_zone.index).shift(1).reindex(d_in.index, method="ffill")
            # ВХОД: микроструктура на входном ТФ
            up, dn, m_hi, m_lo = micro_breaks_and_levels(d_in)
        except Exception as e:                              # noqa: BLE001
            print(f"  ⚠ {sym}: {type(e).__name__}: {str(e)[:50]}")
            continue

        H, L, C = d_in.high.values, d_in.low.values, d_in.close.values
        years = d_in.index.year.values
        n = len(C)
        ctxv, zov, zev, zdv = ctx.values, ZO.values, ZE.values, ZD.values
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        last = -10 ** 9
        for t in range(300, n - HOLD - 1):
            d = int(ctxv[t]) if ctxv[t] == ctxv[t] else 0
            if d == 0 or t - last < 12:
                continue
            if not (zov[t] == zov[t] and zev[t] == zev[t]) or int(zdv[t]) != d:
                continue                                     # импульс зоны — в сторону контекста
            c = float(C[t])
            # 🔴 ПИВОТ СТРУКТУРНО: сторона от дневного PP должна совпадать с направлением
            if pivD is None:
                continue
            pp = pivD["PP"].values[t]
            if not (pp == pp):
                continue
            if (d > 0 and c < pp) or (d < 0 and c > pp):
                continue
            # ЗОНА: фибо-коррекция импульса старшего 0.5-0.786
            o, x = float(zov[t]), float(zev[t])
            amp = abs(x - o)
            if amp <= 0:
                continue
            z1 = x - 0.5 * amp if d > 0 else x + 0.5 * amp
            z2 = x - 0.786 * amp if d > 0 else x + 0.786 * amp
            if not (min(z1, z2) <= c <= max(z1, z2)):
                continue
            # ТРИГГЕР: слом микроструктуры на ВХОДНОМ ТФ в сторону контекста
            if not (up[t] if d > 0 else dn[t]):
                continue
            # СТОП — масштаб ВХОДА (микро-экстремум)
            mk = m_lo[t] if d > 0 else m_hi[t]
            if not (mk == mk):
                continue
            sl = float(mk) * (1 - 0.002) if d > 0 else float(mk) * (1 + 0.002)
            if (d > 0 and sl >= c) or (d < 0 and sl <= c):
                continue
            sp = abs(c - sl) / c * 100.0
            if not (0.1 <= sp <= a.max_stop):
                continue
            # ЦЕЛЬ — масштаб СТАРШЕГО: ближайший пивот по ходу, иначе фибо-расширение
            cands = []
            for pv in (pivD, pivW, piv4):
                if pv is None:
                    continue
                for col in ("PP", "R1", "R2", "S1", "S2"):
                    v = pv[col].values[t]
                    if v == v and ((v > c) if d > 0 else (v < c)):
                        cands.append(float(v))
            tp_piv = (min(cands) if d > 0 else max(cands)) if cands else None
            tp_fib = x + d * 1.0 * amp
            for tname, tp in (("пивот старшего", tp_piv), ("фибо −1 старшего", tp_fib)):
                if tp is None or not (tp == tp):
                    continue
                if (d > 0 and tp <= c) or (d < 0 and tp >= c):
                    continue
                rr = abs(tp - c) / abs(c - sl)
                if rr < a.min_rr:
                    continue
                r, how = sim(H, L, C, t, c, d, sl, tp)
                if r is None:
                    continue
                q = int(rng.integers(300, n - HOLD - 1))
                ec = float(C[q])
                rc, _ = sim(H, L, C, q, ec, d, ec * (1 - d * sp / 100.0),
                            ec * (1 + d * sp * rr / 100.0))
                rows.append((sym, oos, int(years[t]), "LONG" if d > 0 else "SHORT",
                             tname, sp, rr, r, how, 0))
                if rc is not None:
                    rows.append((sym, oos, int(years[q]), "LONG" if d > 0 else "SHORT",
                                 tname, sp, rr, rc, "-", 1))
            last = t
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сетапов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "tp", "sp", "rr",
                                    "gross", "how", "ctrl"])
    R.to_parquet(ROOT / "cache" / "mtf_rebuild.parquet")
    S, K = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nсетапов {len(S):,} · монет {S.sym.nunique()} · {S.year.min()}-{S.year.max()}")
    print(f"медиана RR {S.rr.median():.2f} · медиана стопа {S.sp.median():.2f}%\n")

    def st(x, nm, cost):
        if len(x) < 40:
            print(f"   {nm:30s} n={len(x)} — мало")
            return
        v = np.sort(x.gross.values - cost)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"   {nm:30s} n={len(x):>5,} ср={v.mean():>+7.3f}% мед={np.median(v):>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")

    for cost, label in ((0.35, "косты 0.35% (лимит, VST-оценка)"),
                        (0.10, "косты 0.10% (мейкер — реальная цель)")):
        print("=" * 112)
        print(label)
        print("=" * 112)
        for tname in S.tp.unique():
            T, KT = S[S.tp == tname], K[K.tp == tname]
            st(T, f"ЦЕЛЬ {tname}", cost)
            st(KT, "   контроль", cost)
        print()
    best = max(S.tp.unique(), key=lambda t: (S[S.tp == t].gross.mean()
                                             if len(S[S.tp == t]) > 40 else -9))
    B = S[S.tp == best]
    print("=" * 112)
    print(f"РАЗРЕЗЫ ЛУЧШЕЙ ЦЕЛИ: {best} (косты 0.35%)")
    print("=" * 112)
    for d in ("LONG", "SHORT"):
        st(B[B.dir == d], d, 0.35)
    for y in sorted(B.year.unique()):
        st(B[B.year == y], f"год {y}", 0.35)
    st(B[~B.oos], "IS (половина монет)", 0.35)
    st(B[B.oos], "OOS (другая половина)", 0.35)
    st(K[(K.tp == best) & K.oos], "OOS контроль", 0.35)
    print("\nисходы:", B.how.value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
