# -*- coding: utf-8 -*-
"""OTE НА ИСТОРИИ 2022-2026 С НАЙДЕННОЙ ОПРАВОЙ (05.09.2026).

Кандидат из стенда геометрии: `ote_nested` + стоп по зоне ликвидности / origin импульса +
цель = ближайший swing + горизонт 24 ч → +0.343% против контроля −0.404%, безтоп10% = 0.000,
слепая проверка по монетам пройдена ([[geometry_bench_stop_wide_target_swing]]).
Не хватало ОДНОГО: годов и режимов — боевых данных всего 120 дней.

Здесь вход воспроизводится на истории ПРИЧИННО: флаги `ote_long` / `ote_short` из
`swing_bridge.etl_ote_premium` (эталонный `build_ote`, тот же код, что в матрице —
закон reuse). Живой `detect_ote_signal` не используется: он требует SMCContext на каждом
баре, что для истории неподъёмно, а ядро входа (цена в OTE-зоне импульса) — то же самое.

Оправа и уровни — из `geometry_bench.build_levels` (тот же код, что дал находку).

🔴 Обязательное: причинность (уровни только из прошлого), косты явной ставкой, счёт в %
цены, контроль = случайный вход той же оправы, разрезы по годам/сторонам, хрупкость.
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
from geometry_bench import build_levels, simulate         # noqa: E402

COST = 0.35
HOLD = 96          # 24 ч на 15m — горизонт находки
CHUNK = 22000      # build_levels растёт квадратично → режем историю на куски
WARM = 2000        # прогрев на стыке кусков

# оправа-победитель и её конкуренты (для контроля выбора)
FRAMES = [
    ("liq×swing",     "liq_dn",     "liq_up",     "swing",   "swing_lo"),
    ("origin×swing",  "origin_lo",  "origin_hi",  "swing",   "swing_lo"),
    ("atr4×swing",    "atr4.0_dn",  "atr4.0_up",  "swing",   "swing_lo"),
    ("liq×magnet",    "liq_dn",     "liq_up",     "magnet_up", "magnet_dn"),
    ("swing×RR1",     "swing_lo",   "swing",      None,      None),      # боевая форма: цель 1R
]


def ote_flags(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Причинные флаги «цена в OTE-зоне» из эталона (тот же код, что в матрице)."""
    from core.calculators.swing_bridge import etl_ote_premium
    e = etl_ote_premium(df)
    return np.asarray(e["ote_long"], dtype=bool), np.asarray(e["ote_short"], dtype=bool)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--cost", type=float, default=COST)
    ap.add_argument("--max-stop", type=float, default=15.0)
    ap.add_argument("--min-gap", type=int, default=8, help="не брать сигналы чаще чем раз в N баров")
    a = ap.parse_args()

    syms = core_universe("15m", n=a.symbols)
    print(f"OTE НА ИСТОРИИ · {len(syms)} монет ядра · ТФ 15m · горизонт {HOLD} баров (24 ч)")
    print(f"оправы: {[f[0] for f in FRAMES]} · косты {a.cost}%\n")

    rng = np.random.default_rng(41)
    rows = []
    t0 = time.time()
    for k, sym in enumerate(syms, 1):
        try:
            df = load(sym, "15m")
        except Exception:                                   # noqa: BLE001
            continue
        if df is None or len(df) < 5000:
            continue
        # санитайзер источника: плоские свечи = битые данные
        flat = float(((df.open == df.high) & (df.high == df.low) & (df.low == df.close)).mean())
        if flat > 0.10:
            print(f"  ⚠ {sym}: {flat*100:.0f}% плоских свечей → пропуск")
            continue
        oos = int(hashlib.md5(sym.encode()).hexdigest(), 16) % 2 == 1

        starts = list(range(0, len(df), CHUNK - WARM))
        for s0 in starts:
            part = df.iloc[s0:s0 + CHUNK]
            if len(part) < 3000:
                continue
            try:
                LV = build_levels(part)
                fl, fs = ote_flags(part)
            except Exception:                               # noqa: BLE001
                continue
            H, L, C = part.high.values, part.low.values, part.close.values
            years = part.index.year.values
            n = len(C)
            lo_bound = WARM if s0 > 0 else 400              # не считать дважды зону перекрытия
            last_sig = -10 ** 9
            for p in range(lo_bound, n - HOLD - 1):
                d = 1 if fl[p] else (-1 if fs[p] else 0)
                if d == 0 or p - last_sig < a.min_gap:
                    continue
                last_sig = p
                e = float(C[p])
                for nm, k_lo, k_hi, t_up, t_dn in FRAMES:
                    sl = LV.get(k_lo if d > 0 else k_hi, np.full(n, np.nan))[p]
                    if not (sl == sl):
                        continue
                    if (d > 0 and sl >= e) or (d < 0 and sl <= e):
                        continue
                    sp = abs(e - sl) / e * 100.0
                    if not (0.15 <= sp <= a.max_stop):
                        continue
                    if t_up is None:                        # цель 1R
                        tp = e * (1 + d * sp / 100.0)
                    else:
                        tp = LV.get(t_up if d > 0 else t_dn, np.full(n, np.nan))[p]
                        if not (tp == tp):
                            continue
                        if (d > 0 and tp <= e) or (d < 0 and tp >= e):
                            continue
                    r = simulate(H, L, C, p, e, d, sl, tp, HOLD)
                    if r is None:
                        continue
                    rows.append((sym, oos, int(years[p]), "LONG" if d > 0 else "SHORT",
                                 nm, sp, r - a.cost, 0))
                    # контроль: случайный бар той же монеты, та же оправа и сторона
                    q = int(rng.integers(400, n - HOLD - 1))
                    slc = LV.get(k_lo if d > 0 else k_hi, np.full(n, np.nan))[q]
                    ec = float(C[q])
                    if not (slc == slc) or (d > 0 and slc >= ec) or (d < 0 and slc <= ec):
                        continue
                    spc = abs(ec - slc) / ec * 100.0
                    if not (0.15 <= spc <= a.max_stop):
                        continue
                    if t_up is None:
                        tpc = ec * (1 + d * spc / 100.0)
                    else:
                        tpc = LV.get(t_up if d > 0 else t_dn, np.full(n, np.nan))[q]
                        if not (tpc == tpc) or (d > 0 and tpc <= ec) or (d < 0 and tpc >= ec):
                            continue
                    rc = simulate(H, L, C, q, ec, d, slc, tpc, HOLD)
                    if rc is not None:
                        rows.append((sym, oos, int(years[q]), "LONG" if d > 0 else "SHORT",
                                     nm, spc, rc - a.cost, 1))
        if k % 5 == 0:
            print(f"  ... {k}/{len(syms)} · строк {len(rows):,} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сигналов нет")
        return 1
    R = pd.DataFrame(rows, columns=["sym", "oos", "year", "dir", "frame", "sp", "r", "ctrl"])
    R.to_parquet(ROOT / "cache" / "ote_history_geometry.parquet")
    S, K = R[R.ctrl == 0], R[R.ctrl == 1]
    print(f"\nсобрано: сигналов {len(S):,} · контролей {len(K):,} · {S.sym.nunique()} монет · "
          f"{S.year.min()}-{S.year.max()}\n")

    def st(x, nm, ind="   "):
        if len(x) < 60:
            print(f"{ind}{nm:26s} n={len(x)} — мало")
            return
        v = np.sort(x.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"{ind}{nm:26s} n={len(x):>6,} медиана={np.median(v):>+7.3f}% среднее={v.mean():>+7.3f}% "
              f"WR={100*(v>0).mean():>4.1f}% безтоп10%={cut.mean():>+7.3f}% монет={x.sym.nunique():>3}")

    print("=" * 118)
    print("ОПРАВЫ: СИГНАЛ против КОНТРОЛЯ (вся история)")
    print("=" * 118)
    for nm in [f[0] for f in FRAMES]:
        st(S[S.frame == nm], f"{nm} · СИГНАЛ")
        st(K[K.frame == nm], f"{nm} · контроль")
        print()

    best = None
    for nm in [f[0] for f in FRAMES]:
        g = S[S.frame == nm]
        c = K[K.frame == nm]
        if len(g) >= 200 and len(c) >= 200 and g.r.mean() > c.r.mean():
            best = nm
            break
    if best is None:
        best = "liq×swing"
    print("=" * 118)
    print(f"РАЗРЕЗЫ ЛУЧШЕЙ ОПРАВЫ: {best}")
    print("=" * 118)
    B = S[S.frame == best]
    for d in ("SHORT", "LONG"):
        st(B[B.dir == d], d)
    print()
    for y in sorted(B.year.unique()):
        st(B[B.year == y], f"год {y}")
    print()
    st(B[~B.oos], "IS (половина монет)")
    st(B[B.oos], "OOS (другая половина)")
    st(K[(K.frame == best) & (K.oos)], "OOS контроль")
    return 0


if __name__ == "__main__":
    sys.exit(main())
