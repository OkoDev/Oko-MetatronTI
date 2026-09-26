# -*- coding: utf-8 -*-
"""OKO-OTE НА ИСТОРИИ 2022-2026 С НАЙДЕННОЙ ГЕОМЕТРИЕЙ (05.09.2026).

Кандидат (боевые сделки июня 2026): SHORT + стоп 6% + удержание 6 ч + выход по рынку
даёт +2.638% net против −0.335% у случайного входа той же стороны. Ограничение:
ОДИН МЕСЯЦ. Здесь закрываем эпоху — тот же детектор на всей истории.

Боевая конфигурация детектора (`bot/loops/oko_ote_observer_loop.py:231`):
  links = [(4h,1h), (4h,15m), (1h,15m)] · min_confs=3 · ENTRY_FIB=0.62
🔴 `pit_zone=True` ОБЯЗАТЕЛЕН: без него зона старшего выбирается на полном df —
хиндсайт конца датасета, 67% сделок-артефактов (PIT-CHECK 25.06, докстринг детектора).

Геометрия выхода — как в находке: стоп 6% от входа, горизонт 24 бара 15m (6 ч),
выход по рынку на конце горизонта. Косты 0.35% явной ставкой.
Контроль — случайный вход той же стороны и геометрии на той же монете.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load, universe, core_universe          # noqa: E402

LINKS = [("4h", "1h"), ("4h", "15m"), ("1h", "15m")]
STOP_PCT = 6.0
HOLD_15M = 24          # 6 ч
COST = 0.35


def outcome(H, L, C, pos, e, d, stop_pct=STOP_PCT, hold=HOLD_15M):
    """Стоп 6% или выход по рынку через hold баров. В % цены, БЕЗ костов."""
    sl = e * (1 - d * stop_pct / 100.0)
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hit = (lo <= sl) if d > 0 else (hi >= sl)
    if hit.any():
        return -stop_pct
    return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=30)
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--min-confs", type=int, default=3)
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()

    from core.smc.oko_ote import detect_oko_ote

    syms = core_universe("15m", n=a.symbols) if a.core else universe("15m", n=a.symbols)
    print(f"OKO-OTE НА ИСТОРИИ · {len(syms)} монет · связки {LINKS} · confs>={a.min_confs}")
    print(f"геометрия: стоп {STOP_PCT}% · удержание {HOLD_15M} баров 15m (6 ч) · "
          f"выход по рынку · косты {a.cost}%  · pit_zone=True\n")

    rows = []
    t0 = time.time()
    for i, sym in enumerate(syms, 1):
        try:
            d15 = load(sym, "15m")
            d1h = load(sym, "1h")
            d4h = load(sym, "4h")
        except Exception:                                   # noqa: BLE001
            continue
        if d15 is None or len(d15) < 3000:
            continue
        dfs = {"15m": d15, "1h": d1h, "4h": d4h}
        idx15 = d15.index
        H15, L15, C15 = d15.high.values, d15.low.values, d15.close.values
        for zone_tf, break_tf in LINKS:
            dz, db = dfs.get(zone_tf), dfs.get(break_tf)
            if dz is None or db is None or len(dz) < 100 or len(db) < 300:
                continue
            try:
                sigs = detect_oko_ote(sym, dz, db, zone_tf, break_tf,
                                      False,            # only_latest=False → список
                                      a.min_confs, dfs,
                                      None, None, 0.62,
                                      True)             # pit_zone=True — БЕЗ ХИНДСАЙТА
            except Exception as e:                          # noqa: BLE001
                continue
            if not sigs:
                continue
            for s in (sigs if isinstance(sigs, list) else [sigs]):
                ts = getattr(s, "entry_ts", "") or getattr(s, "choch_ts", "")
                if not ts:
                    continue
                try:
                    t = pd.Timestamp(ts)
                    if t.tzinfo is None:
                        t = t.tz_localize("UTC")
                except Exception:                           # noqa: BLE001
                    continue
                pos = int(idx15.searchsorted(t))
                if pos <= 0 or pos >= len(C15) - HOLD_15M - 1:
                    continue
                d = 1 if str(s.direction).lower() == "long" else -1
                e = float(s.entry)
                if e <= 0:
                    continue
                r = outcome(H15, L15, C15, pos, e, d)
                if r is None:
                    continue
                rows.append(dict(sym=sym, link=f"{zone_tf}>{break_tf}", dir=s.direction,
                                 year=int(t.year), r=r - a.cost, pos=pos, d=d))
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · сигналов {len(rows)} · {time.time()-t0:.0f}с", flush=True)

    if not rows:
        print("🔴 сигналов нет")
        return 1
    R = pd.DataFrame(rows)
    print(f"\nсобрано: {len(R)} сигналов · {R.sym.nunique()} монет · "
          f"{R.year.min()}-{R.year.max()}\n")

    def st(g, name):
        if len(g) < 25:
            print(f"   {name:26s} n={len(g)} — мало")
            return
        v = np.sort(g.r.values)
        cut = v[:max(1, int(len(v) * 0.9))]
        print(f"   {name:26s} n={len(g):>5} net={v.mean():>+7.3f}% медиана={np.median(v):>+7.3f}% "
              f"WR={100*(v>0).mean():4.1f}% безтоп10%={cut.sum():>+8.0f} монет={g.sym.nunique()}")

    print("ВСЁ:");            st(R, "все сигналы")
    print("\nПО СТОРОНЕ:")
    for d in ("short", "long"):
        st(R[R.dir.str.lower() == d], d.upper())
    print("\nПО ГОДАМ (обе стороны):")
    for y in sorted(R.year.unique()):
        st(R[R.year == y], str(y))
    print("\nSHORT ПО ГОДАМ (кандидат):")
    for y in sorted(R.year.unique()):
        st(R[(R.year == y) & (R.dir.str.lower() == "short")], f"SHORT {y}")
    print("\nПО СВЯЗКАМ:")
    for l, g in R.groupby("link"):
        st(g, l)

    # ── контроль: случайный вход той же стороны/геометрии ──────────────
    print("\nКОНТРОЛЬНАЯ ГРУППА (случайный бар той же монеты, та же сторона):")
    rng = np.random.default_rng(11)
    ctrl_means = []
    cache = {}
    for it in range(3):
        vals = []
        for sym, g in R.groupby("sym"):
            if sym not in cache:
                try:
                    d15 = load(sym, "15m")
                    cache[sym] = (d15.high.values, d15.low.values, d15.close.values)
                except Exception:                           # noqa: BLE001
                    cache[sym] = None
            if cache[sym] is None:
                continue
            H, L, C = cache[sym]
            for _, row in g.iterrows():
                p = int(rng.integers(300, len(C) - HOLD_15M - 1))
                r = outcome(H, L, C, p, float(C[p]), int(row["d"]))
                if r is not None:
                    vals.append(r - a.cost)
        v = np.array(vals)
        ctrl_means.append(v.mean())
        print(f"   контроль #{it+1}: n={len(v):>5} net={v.mean():+7.3f}% WR={100*(v>0).mean():4.1f}%")
    print(f"\n   контроль среднее {np.mean(ctrl_means):+.3f}%  ·  "
          f"ПРЕВЫШЕНИЕ сигнала: {R.r.mean()-np.mean(ctrl_means):+.3f} п.п.")

    out = ROOT / "cache" / "oko_ote_history.parquet"
    try:
        R.to_parquet(out)
        print(f"\nсырые сигналы → {out}")
    except Exception as e:                                  # noqa: BLE001
        print(f"(parquet не сохранён: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
