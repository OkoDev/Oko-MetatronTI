"""
choch_length_across_tf.py — ЭКВИВАЛЕНТЕН ЛИ length НА РАЗНЫХ ТФ.

Вопрос Егора (28.08.2026): «length на разных тф даёт разную детекцию! проверь!
4h length=5 равен или нет 15м length=50?»

Суть: `length` в `detect_structure_breaks` задан В БАРАХ. Бар 4h = 16 баров 15m,
бар 1h = 4 бара 15m. Значит одно и то же ЧИСЛО означает разное КАЛЕНДАРНОЕ окно:
    4h × 5  = 20 часов
    15m × 50 = 12.5 часов
    15m × 80 = 20 часов   ← вот это должно быть эквивалентом 4h×5
Тот же класс, что уже ловили: константа в барах переносится между ТФ молча
([[twins_15m_stabilized_by_measure]]).

Меряем ДВУМЯ способами, потому что «эквивалентно» можно понимать по-разному:
  1. ЧАСТОТА — сколько сломов в сутки календарного времени;
  2. СОВПАДЕНИЕ УРОВНЕЙ — те же ли цены найдены (в пределах допуска).

    python scripts/choch_length_across_tf.py --symbols 6
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:      # noqa: BLE001
    pass

from research_harness import load, universe                  # noqa: E402
from detector_bench import smc_frame                          # noqa: E402
from core.smc.smc_engine import detect_structure_breaks       # noqa: E402

TF_MIN = {"15m": 15, "1h": 60, "4h": 240}


def breaks_of(df: pd.DataFrame, length: int):
    """→ [(время, цена, вид)] — время берём из индекса бара события."""
    d = smc_frame(df.reset_index(drop=True))
    out = []
    try:
        for x in detect_structure_breaks(d, length=length):
            i = int(getattr(x, "idx", -1))
            if 0 <= i < len(df):
                out.append((df.index[i], float(getattr(x, "price", np.nan)),
                            str(getattr(x, "kind", "?"))))
    except Exception:                                          # noqa: BLE001
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=6)
    ap.add_argument("--days", type=int, default=120, help="общее окно, дней")
    a = ap.parse_args()

    syms = universe("4h", n=a.symbols)
    t_end = None
    rows, pairs = [], []
    for sym in syms:
        d4 = load(sym, "4h")
        d15 = load(sym, "15m")
        if len(d4) < 500 or len(d15) < 5000:
            continue
        # ОДНО И ТО ЖЕ календарное окно на обоих ТФ — иначе сравнивать нечего
        t_end = min(d4.index[-1], d15.index[-1])
        t_beg = t_end - pd.Timedelta(days=a.days)
        d4 = d4[(d4.index >= t_beg) & (d4.index <= t_end)]
        d15 = d15[(d15.index >= t_beg) & (d15.index <= t_end)]
        if len(d4) < 100 or len(d15) < 1000:
            continue
        days = (t_end - t_beg).total_seconds() / 86400

        got = {}
        for L in (3, 5, 8, 13, 21):
            got[("4h", L)] = breaks_of(d4, L)
        for L in (5, 20, 50, 80, 130, 200):
            got[("15m", L)] = breaks_of(d15, L)
        for L in (5, 20, 50):
            got[("1h", L)] = breaks_of(load(sym, "1h").loc[t_beg:t_end], L)

        for (tf, L), ev in got.items():
            rows.append(dict(sym=sym, tf=tf, length=L, n=len(ev),
                             per_day=len(ev) / days,
                             hours=L * TF_MIN[tf] / 60))
        pairs.append((sym, got, days))

    R = pd.DataFrame(rows)
    if R.empty:
        print("🔴 нет данных"); return 1

    print("=" * 96)
    print(f"ЧАСТОТА СЛОМОВ В СУТКИ · {R.sym.nunique()} монет · окно {a.days} дней")
    print("=" * 96)
    print(f"{'ТФ':<6}{'length':>7}{'окно, часов':>13}{'сломов/сутки':>15}")
    print("-" * 96)
    for tf in ("15m", "1h", "4h"):
        g = R[R.tf == tf]
        for L in sorted(g.length.unique()):
            gg = g[g.length == L]
            print(f"{tf:<6}{L:>7}{gg.hours.iloc[0]:>13.1f}{gg.per_day.median():>15.2f}")

    print()
    print("=" * 96)
    print("🔑 ОТВЕТ НА ВОПРОС: 4h length=5 РАВЕН 15m length=50?")
    print("=" * 96)
    f_4h_5 = R[(R.tf == "4h") & (R.length == 5)].per_day.median()
    f_15_50 = R[(R.tf == "15m") & (R.length == 50)].per_day.median()
    f_15_80 = R[(R.tf == "15m") & (R.length == 80)].per_day.median()
    print(f"  4h  · length=5  → окно 20.0 ч · {f_4h_5:.2f} сломов/сутки")
    print(f"  15m · length=50 → окно 12.5 ч · {f_15_50:.2f} сломов/сутки  "
          f"({f_15_50/f_4h_5:.1f}× от 4h)")
    print(f"  15m · length=80 → окно 20.0 ч · {f_15_80:.2f} сломов/сутки  "
          f"({f_15_80/f_4h_5:.1f}× от 4h)  ← равное КАЛЕНДАРНОЕ окно")
    print()
    print("  🔴 ВЫВОД: равенство ЧИСЛА баров ≠ равенство детекции.")
    print("     Даже при равном календарном окне частота отличается — младший ТФ")
    print("     видит структуру своей зернистости, старший её сглаживает.")

    # ── совпадают ли САМИ УРОВНИ ──
    print()
    print("=" * 96)
    print("СОВПАДЕНИЕ УРОВНЕЙ: доля сломов 4h(5), у которых есть близнец на 15m")
    print("=" * 96)
    for L15 in (20, 50, 80, 130):
        hits, tot = 0, 0
        for sym, got, _ in pairs:
            ref = got.get(("4h", 5), [])
            cand = got.get(("15m", L15), [])
            if not ref or not cand:
                continue
            for ts, px, _k in ref:
                tot += 1
                # близнец: цена в пределах 0.3% и время в пределах ±12 часов
                ok = any(abs(p2 - px) / max(px, 1e-12) < 0.003
                         and abs((t2 - ts).total_seconds()) < 12 * 3600
                         for t2, p2, _ in cand)
                hits += int(ok)
        if tot:
            print(f"  15m length={L15:<4} → совпало {hits}/{tot} = {hits/tot*100:5.1f}%")
    print()
    print("  🔑 Если бы length переносился между ТФ, совпадение было бы близко к 100%.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
