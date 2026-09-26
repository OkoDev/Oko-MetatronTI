# -*- coding: utf-8 -*-
"""СЕТКА МЕТОДА ЕГОРА: ВСЕ УРОВНИ ВХОДА × ВСЕ ЦЕЛИ (05.09.2026).

Егор: «добавь и проверь все уровни фибо! средние 0.5-0.62» + цели «по фибо / имбалансы /
обновление хаёв».

Конфигурация зафиксирована предыдущими прогонами:
  · импульс-сломщик = слом СТАРШЕЙ структуры (len=50). На микро-сломах (len=5) метод
    не работает: 53 503 сетапа, всё в минусе — вход на каждом шевелении.
  · КОНТЕКСТ: сетап только в сторону тренда старшего слоя («лои не обновлялись»).
  · оба слоя берутся ОДНИМ прогоном `run_structure` (Егор: «на то тебе и дано две структуры»).

Здесь перебираются:
  ВХОД  — 0.382 · 0.5 · 0.618 · 0.705 · 0.786 (каждый отдельно, лимит на уровне)
  ЦЕЛЬ  — extreme (обновление хая) · фибо −0.27 / −0.62 / −1.0 / −1.618 · ИМБАЛАНС (FVG)
🔴 множественность: 5 × 6 = 30 ячеек, названа явно.

Стоп — за структуру (основание импульса). Косты явной ставкой, счёт в % цены,
контроль = случайный вход той же геометрии.
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
WAIT = 96
HOLD = 384
ENTRIES = [0.382, 0.5, 0.618, 0.705, 0.786]
# 🔴 Егор: «имбаланс НЕ цель! имбаланс МАГНИТ! по фибо вход и выход тоже по фибо минусовым».
# Цели — только минусовые фибо. Имбаланс старшего ТФ = МАГНИТ, идёт разрезом (тянет ли туда).
TARGETS = ["fib-0.27", "fib-0.62", "fib-1.0", "fib-1.618", "fib-2.618"]


def fvg_levels(df: pd.DataFrame):
    """Ближайшая НЕЗАКРЫТАЯ FVG сверху и снизу на каждом баре (эталон detect_fvg)."""
    n = len(df)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    try:
        from core.smc.smc_engine import detect_fvg
        d = df.reset_index(drop=True)
        if "time" not in d.columns:
            d = d.assign(time=(df.index.astype("int64") // 10 ** 6))
        zones = detect_fvg(d)
    except Exception:                                       # noqa: BLE001
        return up, dn
    H, L, C = df.high.values, df.low.values, df.close.values
    born: dict[int, list] = {}
    # 🔴 detect_fvg отдаёт КОРТЕЖИ (index, top, bottom, 'bull'|'bear', ...), не объекты.
    for z in zones:
        try:
            i = int(z[0]); top = float(z[1]); bot = float(z[2])
            bull = str(z[3]).lower().startswith("bull")
        except Exception:                                   # noqa: BLE001
            continue
        if i < 0 or i >= n or not (top == top and bot == bot):
            continue
        born.setdefault(i, []).append((min(top, bot), max(top, bot), bull))
    live: list[list] = []
    for t in range(n):
        for lo_, hi_, bull in born.get(t, ()):
            live.append([lo_, hi_, bull])
        c = C[t]
        keep = []
        for z in live:
            if z[1] < c * 0.5 or z[0] > c * 2.0:            # ушли слишком далеко — забыть
                continue
            keep.append(z)
        live = keep[-40:]
        ups = [z[0] for z in live if z[0] > c]
        dns = [z[1] for z in live if z[1] < c]
        if ups:
            up[t] = min(ups)
        if dns:
            dn[t] = max(dns)
    return up, dn


def htf_fvg_on_grid(sym: str, idx: pd.DatetimeIndex, tf: str):
    """FVG СТАРШЕГО ТФ, перенесённый на сетку младшего.

    🔴 Егор: «мы ведь анализируем от старшего к младшему! имбаланс СТАРШЕГО нужен».
    Имбаланс 15m стоит слишком близко (RR 0.12) — цель берётся в 97.6% случаев и это
    сбор пятаков. Имбаланс 1h/4h даёт реальный ход.
    🔴 Причинность: значения сдвинуты на 1 бар старшего ТФ (только ЗАКРЫТЫЙ бар).
    """
    try:
        d = load(sym, tf)
    except Exception:                                       # noqa: BLE001
        return None, None
    if d is None or len(d) < 200:
        return None, None
    up, dn = fvg_levels(d)
    su = pd.Series(up, index=d.index).shift(1).reindex(idx, method="ffill")
    sd = pd.Series(dn, index=d.index).shift(1).reindex(idx, method="ffill")
    return su.values, sd.values


def pivot_grid(df: pd.DataFrame):
    """Все уровни пивотов D / W / 4h на сетке бара (PP, R1-R3, S1-S3), только ПРОШЛЫЙ период.

    🔴 Егор: «входы также можешь искать вблизи пивотов дневных, недельных, четырёхчасовых».
    Возвращает список массивов уровней — потом считаем дистанцию от уровня входа до
    ближайшего пивота (конфлюэнция).
    """
    out = []
    for rule, tag in (("1D", "D"), ("1W", "W"), ("4h", "4h")):
        try:
            agg = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
            if len(agg) < 3:
                continue
            pp = (agg.high + agg.low + agg.close) / 3.0
            lv = pd.DataFrame({
                "PP": pp,
                "R1": 2 * pp - agg.low, "S1": 2 * pp - agg.high,
                "R2": pp + (agg.high - agg.low), "S2": pp - (agg.high - agg.low),
                "R3": agg.high + 2 * (pp - agg.low), "S3": agg.low - 2 * (agg.high - pp),
            }).shift(1).reindex(df.index, method="ffill")
            out.append(lv.values)
        except Exception:                                   # noqa: BLE001
            continue
    return out


def micro_extremes(df: pd.DataFrame, length: int = 5):
    """Последний подтверждённый МИКРО-экстремум на каждом баре (для короткого стопа).

    🔴 Егор: «стоп КОРОТКИЙ, за ближайшую вершину». Стоп за основание импульса (2.71%
    медиана) режет RR — вход микро, а риск макро.
    """
    from core.smc.oko_sm_engine import pivot_points
    n = len(df)
    hi = np.full(n, np.nan); lo = np.full(n, np.nan)
    cur_hi = cur_lo = np.nan
    conf: dict[int, list] = {}
    for conf_i, sw_i, price, is_top in pivot_points(df["high"], df["low"], length):
        conf.setdefault(int(conf_i), []).append((float(price), bool(is_top)))
    for t in range(n):
        for price, is_top in conf.get(t, ()):
            if is_top:
                cur_hi = price
            else:
                cur_lo = price
        hi[t], lo[t] = cur_hi, cur_lo
    return hi, lo


def build(df: pd.DataFrame, sym: str = ""):
    """Сетапы: импульс-сломщик старшего слоя + контекст + все уровни входа и целей."""
    from core.smc.oko_sm_engine import run_structure
    d = df.reset_index(drop=True)
    st = run_structure(d, swing_len=50, internal_len=5)
    H, L, C = d.high.values, d.low.values, d.close.values
    n = len(C)
    fvg_up, fvg_dn = fvg_levels(df)
    m_hi, m_lo = micro_extremes(df)
    PIV = pivot_grid(df)          # ближайший пивот D/W/4h к каждому бару
    fvg1_up, fvg1_dn = htf_fvg_on_grid(sym, df.index, "1h")
    fvg4_up, fvg4_dn = htf_fvg_on_grid(sym, df.index, "4h")

    ctx = np.zeros(n, dtype=int)
    cur = 0
    major = {int(e.i): (1 if bool(e.bull) else -1)
             for e in st.events if not bool(getattr(e, "internal", False))}
    for t in range(n):
        if t in major:
            cur = major[t]
        ctx[t] = cur

    out = []
    for ev in st.events:
        if bool(getattr(ev, "internal", False)):
            continue
        i = int(ev.i)
        bull = bool(ev.bull)
        if i < 50 or i >= n - WAIT - HOLD - 2:
            continue
        if ctx[i] == 0 or (ctx[i] > 0) != bull:             # контекст старшего порядка
            continue
        a = max(0, min(int(getattr(ev, "level_i", 0) or 0), i - 1))
        origin = float(L[a:i + 1].min()) if bull else float(H[a:i + 1].max())
        ext, ext_j = (float(H[i]), i) if bull else (float(L[i]), i)
        j = i + 1
        while j < min(i + WAIT, n):
            if bull:
                if H[j] > ext:
                    ext, ext_j = float(H[j]), j
                if (ext - L[j]) >= 0.5 * (ext - origin) and ext > origin:
                    break
            else:
                if L[j] < ext:
                    ext, ext_j = float(L[j]), j
                if (H[j] - ext) >= 0.5 * (origin - ext) and origin > ext:
                    break
            j += 1
        amp = abs(ext - origin)
        if amp <= 0 or ext_j >= n - HOLD - 2:
            continue
        d_ = 1 if bull else -1
        # ── ищем касание КАЖДОГО уровня входа ───────────────────────────
        for fib in ENTRIES:
            lvl = ext - fib * amp if bull else ext + fib * amp
            hit = None
            for q in range(ext_j + 1, min(ext_j + WAIT, n - HOLD - 1)):
                px = L[q] if bull else H[q]
                if (px <= lvl) if bull else (px >= lvl):
                    hit = q
                    break
                if bull and L[q] < origin:
                    break
                if (not bull) and H[q] > origin:
                    break
            if hit is None:
                continue
            # КОНФЛЮЭНЦИЯ С ПИВОТОМ: дистанция от уровня входа до ближайшего пивота, %
            _pd = 99.0
            for arr in PIV:
                row = arr[hit]
                for v in row:
                    if v == v and v > 0:
                        _pd = min(_pd, abs(lvl - float(v)) / lvl * 100.0)
            # ТРИ ВАРИАНТА СТОПА (Егор: «стоп короткий, за ближайшую вершину»)
            _mk = m_lo[hit] if bull else m_hi[hit]
            stops = {
                "структура": origin * (1 - 0.002) if bull else origin * (1 + 0.002),
                "0.786":     (ext - 0.786 * amp) * (1 - 0.002) if bull
                             else (ext + 0.786 * amp) * (1 + 0.002),
                "ближняя вершина": (float(_mk) * (1 - 0.002) if bull else float(_mk) * (1 + 0.002))
                                   if _mk == _mk else None,
            }

            def _f(a_up, a_dn):
                if a_up is None or a_dn is None:
                    return None
                v = a_up[hit] if bull else a_dn[hit]
                return float(v) if v == v else None
            tg = {
                "fib-0.27":  ext + d_ * 0.27 * amp,
                "fib-0.62":  ext + d_ * 0.62 * amp,
                "fib-1.0":   ext + d_ * 1.0 * amp,
                "fib-1.618": ext + d_ * 1.618 * amp,
                "fib-2.618": ext + d_ * 2.618 * amp,
            }
            # МАГНИТ: незакрытый имбаланс старшего ТФ ПО НАПРАВЛ�ению сделки.
            # mag=0 нет · 1 есть на 1h · 2 есть на 4h · 3 есть на обоих
            m1, m4 = _f(fvg1_up, fvg1_dn), _f(fvg4_up, fvg4_dn)
            mag = 0
            if m1 is not None and ((m1 > lvl) if bull else (m1 < lvl)):
                mag += 1
            if m4 is not None and ((m4 > lvl) if bull else (m4 < lvl)):
                mag += 2
            for sname, sval in stops.items():
                if sval is None:
                    continue
                if (bull and sval >= lvl) or ((not bull) and sval <= lvl):
                    continue
                out.append(dict(i=hit, d=d_, entry=lvl, sl=sval, slname=sname, fib=fib,
                                tg=tg, mag=mag, piv=_pd, kind=str(ev.kind), amp=amp))
    return out


def sim(H, L, C, pos, e, d, sl, tp, hold=HOLD):
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
    ap.add_argument("--symbols", type=int, default=25)
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--max-stop", type=float, default=20.0)
    a = ap.parse_args()

    syms = core_universe(a.tf, n=a.symbols)
    print(f"СЕТКА МЕТОДА · {len(syms)} монет · {a.tf} · импульс-сломщик СТАРШЕГО слоя + контекст")
    print(f"вход: {ENTRIES} · цели: {TARGETS} · 🔴 {len(ENTRIES)*len(TARGETS)} ячеек · "
          f"косты {a.cost}%\n")

    rng = np.random.default_rng(71)
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
            S = build(df, sym)
        except Exception as e:                              # noqa: BLE001
            print(f"  ⚠ {sym}: {type(e).__name__}: {str(e)[:50]}")
            continue
        H, L, C = df.high.values, df.low.values, df.close.values
        years = df.index.year.values
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1
        for s in S:
            sp = abs(s["entry"] - s["sl"]) / s["entry"] * 100.0
            if not (0.15 <= sp <= a.max_stop):
                continue
            for tname, tp in s["tg"].items():
                if tp is None or not (tp == tp):
                    continue
                if (s["d"] > 0 and tp <= s["entry"]) or (s["d"] < 0 and tp >= s["entry"]):
                    continue
                r = sim(H, L, C, s["i"], s["entry"], s["d"], s["sl"], tp)
                if r is None:
                    continue
                rr = abs(tp - s["entry"]) / abs(s["entry"] - s["sl"])
                rows.append((sym, oos, int(years[s["i"]]), "LONG" if s["d"] > 0 else "SHORT",
                             s["kind"], s["fib"], tname, sp, rr, r - a.cost, 0, s["mag"],
                             s["slname"], s["piv"]))
                q = int(rng.integers(300, len(C) - HOLD - 1))
                ec = float(C[q])
                rc = sim(H, L, C, q, ec, s["d"], ec * (1 - s["d"] * sp / 100.0),
                         ec * (1 + s["d"] * sp * rr / 100.0))
                if rc is not None:
                    rows.append((sym, oos, int(years[q]), "LONG" if s["d"] > 0 else "SHORT",
                                 s["kind"], s["fib"], tname, sp, rr, rc - a.cost, 1, s["mag"],
                                 s["slname"], s["piv"]))
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сетапов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "kind", "fib", "tp",
                                    "sp", "rr", "r", "ctrl", "mag", "sl", "piv"])
    R.to_parquet(ROOT / "cache" / "egor_fib_grid.parquet")
    S_, K_ = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nстрок {len(S_):,} · монет {S_.sym.nunique()} · {S_.year.min()}-{S_.year.max()}\n")

    print("=" * 116)
    print("КАРТА: УРОВЕНЬ ВХОДА × ЦЕЛЬ — СРЕДНЕЕ net % (в скобках n)")
    print("=" * 116)
    print(f"{'вход':>8}" + "".join(f"{t:>17}" for t in TARGETS))
    for f in ENTRIES:
        line = f"{f:>8.3f}"
        for t in TARGETS:
            g = S_[(S_.fib == f) & (S_.tp == t)]
            line += f"{g.r.mean():>+11.3f}% ({len(g):>3})" if len(g) >= 60 else f"{'—':>17}"
        print(line)
    print()
    print(f"{'КОНТРОЛЬ':>8}" + f"{K_.r.mean():>+11.3f}% ({len(K_):>5}) — случайный вход той же геометрии")

    print("\n" + "=" * 116)
    print("ЛУЧШИЕ ЯЧЕЙКИ (n≥100), со слепой проверкой по монетам")
    print("=" * 116)
    res = []
    for f in ENTRIES:
        for t in TARGETS:
            g = S_[(S_.fib == f) & (S_.tp == t)]
            if len(g) >= 100:
                res.append((g.r.mean(), f, t, len(g)))
    for m, f, t, nn in sorted(res, reverse=True)[:8]:
        g = S_[(S_.fib == f) & (S_.tp == t)]
        o = g[g.oos]
        ko = K_[(K_.fib == f) & (K_.tp == t) & (K_.oos)]
        v = np.sort(g.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"  вход {f:.3f} → {t:10s} n={nn:>5} среднее={m:>+7.3f}% RR={g.rr.median():>4.2f} "
              f"безтоп10%={cut.mean():>+7.3f}% | OOS={o.r.mean():>+7.3f}% (n={len(o)}) "
              f"контроль={ko.r.mean():>+7.3f}%")

    print("\n" + "=" * 116)
    print("СРЕДНИЕ УРОВНИ 0.5-0.62 (Егор), разрезы")
    print("=" * 116)
    M = S_[S_.fib.isin([0.5, 0.618])]
    KM = K_[K_.fib.isin([0.5, 0.618])]

    def st(x, nm):
        if len(x) < 60:
            print(f"   {nm:28s} n={len(x)} — мало")
            return
        v = np.sort(x.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"   {nm:28s} n={len(x):>6,} среднее={v.mean():>+7.3f}% медиана={np.median(v):>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")
    for t in TARGETS:
        st(M[M.tp == t], f"цель {t}")
    print()
    print("🎯 ВАРИАНТ СТОПА × ЦЕЛЬ (вход 0.5-0.618):")
    for sn in ("структура", "0.786", "ближняя вершина"):
        for t in TARGETS:
            st(M[(M.sl == sn) & (M.tp == t)], f"стоп {sn} → {t}")
        print()
    print("📍 БЛИЗОСТЬ ВХОДА К ПИВОТУ D/W/4h (вход 0.5-0.618, стоп «ближняя вершина»):")
    _B = M[M.sl == "ближняя вершина"]
    for t in ("fib-0.62", "fib-1.0", "fib-1.618"):
        for lo_, hi_, nm in ((0, 0.2, "у пивота <0.2%"), (0.2, 0.5, "0.2-0.5%"),
                             (0.5, 1.0, "0.5-1%"), (1.0, 99, "далеко >1%")):
            st(_B[(_B.tp == t) & (_B.piv >= lo_) & (_B.piv < hi_)], f"{t} · {nm}")
        print()
    print("🧲 МАГНИТ (незакрытый имбаланс СТАРШЕГО ТФ по направлению):")
    for t in TARGETS:
        for mg, nm in ((0, "нет магнита"), (1, "магнит 1h"), (2, "магнит 4h"), (3, "магнит 1h+4h")):
            st(M[(M.tp == t) & (M.mag == mg)], f"{t} · {nm}")
        print()
    print()
    best_t = max(TARGETS, key=lambda t: M[M.tp == t].r.mean() if len(M[M.tp == t]) > 60 else -9)
    B = M[M.tp == best_t]
    print(f"лучшая цель среди 0.5-0.62: {best_t}")
    for d in ("LONG", "SHORT"):
        st(B[B.dir == d], d)
    for y in sorted(B.year.unique()):
        st(B[B.year == y], f"год {y}")
    st(B[~B.oos], "IS"); st(B[B.oos], "OOS")
    st(KM[(KM.tp == best_t) & KM.oos], "OOS контроль")
    return 0


if __name__ == "__main__":
    sys.exit(main())
