"""
long_inventory.py — ИНВЕНТАРИЗАЦИЯ БАЗЫ LONG (30.08.2026).

Егор возразил на вердикт «связок в long нет»: «не может рынок давать только одну сторону».
Возражение по существу — и проверять надо не перебор, а ПОСТАНОВКУ замера.

Что мой вердикт на самом деле утверждал (и чего НЕ утверждал):
    померено:   одна механика (impulse_fib) · один ТФ (15m) · поверх дрейф-гейта,
                откалиброванного ПОД SHORT
    объявлено:  «связок в long нет»  ← шире замера, это дефект формулировки

Прежде чем снова перебирать признаки, надо ответить на вопросы, которых я не задал:
    1. база long прибыльна ХОТЬ ГДЕ? (год · режим · сторона гейта · ТФ входа)
       фильтр НЕ создаёт эдж — он его отбирает. Над убыточной базой перебор
       обязан вернуть шум, и это будет верный ответ на неверный вопрос;
    2. есть ли в окне БЫЧИЙ режим вообще? «long мёртв» на медвежьем окне — тавтология;
    3. симметричен ли конвейер? если шум сам производит N выживших, порог отбора мягкий;
    4. что делает short-гейт с long-базой — усиливает или стрижёт.

    python scripts/long_inventory.py
"""
from __future__ import annotations

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

from research_harness import stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"


def show(X: pd.DataFrame, label: str, base_pf: float | None = None) -> dict | None:
    s = stat(X)
    if not s:
        print(f"  {label:<38} —")
        return None
    mult = f" ×{s['pf']/base_pf:.2f}" if base_pf else "     "
    mark = ""
    if s["pf"] >= 1.0:
        mark = " 🟢 ПРИБЫЛЬНА" if not base_pf else " 🟢"
    print(f"  {label:<38} n={s['n']:>5}  PF {s['pf']:5.2f}{mult}  WR {s['wr']:4.1f}%"
          f"  безтоп10% {s['bt']:+7.0f}  охват {s['cov']:3.0f}%{mark}")
    return s


def main() -> int:
    X = pd.read_parquet(PQ)
    X["_ts"] = pd.to_datetime(X.entry_ts, utc=True, errors="coerce")
    lo, sh = X.side == "long", X.side == "short"

    print("=" * 104)
    print(f"ИНВЕНТАРИЗАЦИЯ БАЗЫ LONG · {len(X)} сделок · {X.shape[1]} колонок")
    print("=" * 104)

    print("\n1. ЧТО ВООБЩЕ ЕСТЬ (обе стороны, без единого фильтра)")
    bl = show(X[lo], "ВСЯ база long")
    bs = show(X[sh], "ВСЯ база short")
    print(f"\n   🔑 фильтр не создаёт эдж, он его отбирает. База long PF {bl['pf']:.2f} —"
          f" {'УБЫТОЧНА' if bl['pf'] < 1 else 'прибыльна'}.")
    if bl["pf"] < 1:
        print(f"      значит перебор над ней ищет «где менее плохо», а не «где хорошо».")

    print("\n2. РЕЖИМ КАЖДОГО ГОДА В ОКНЕ (есть ли бык вообще)")
    print(f"   {'год':<6} {'дрейф вселенной':<20} {'long PF':<10} {'short PF':<10} режим")
    for y in sorted(X.year.dropna().unique()):
        g = X[X.year == y]
        drift = float(g.mkt_drift30.median()) if "mkt_drift30" in g else float("nan")
        a, b = stat(g[g.side == "long"]), stat(g[g.side == "short"])
        reg = "🐂 БЫК" if drift > 2 else ("🐻 медведь" if drift < -2 else "· нейтраль")
        pa = f"{a['pf']:.2f} (n={a['n']})" if a else "—"
        pb = f"{b['pf']:.2f} (n={b['n']})" if b else "—"
        print(f"   {int(y):<6} {drift:>+8.2f}%           {pa:<10} {pb:<10} {reg}")

    print("\n3. ЧТО SHORT-ГЕЙТ ДЕЛАЕТ С LONG-БАЗОЙ (искал long, стоя на short-фильтре)")
    gate = X.mkt_drift_slope > 0
    show(X[lo], "long без гейта", bl["pf"])
    show(X[lo & gate], "long + short-гейт (как в поиске)", bl["pf"])
    show(X[lo & ~gate], "long ПРОТИВ гейта (не смотрел!)", bl["pf"])

    print("\n4. ЕСТЬ ЛИ СРЕЗ, ГДЕ LONG-БАЗА ПРИБЫЛЬНА САМА (без единого признака)")
    found = []
    for nm, m in (("бычьи бары вселенной (drift30>0)", lo & (X.mkt_drift30 > 0)),
                  ("сильный рост (drift30>3)", lo & (X.mkt_drift30 > 3)),
                  ("медвежьи бары (drift30<0)", lo & (X.mkt_drift30 < 0)),
                  ("2023 бычий", lo & (X.year == 2023)),
                  ("широкий стоп (>верхней трети)", lo & (X.stop_pct > X.stop_pct.quantile(0.67))),
                  ("узкий стоп (<нижней трети)", lo & (X.stop_pct < X.stop_pct.quantile(0.33)))):
        s = show(X[m], nm, bl["pf"])
        if s and s["pf"] >= 1.0:
            found.append((nm, s))

    print("\n5. СИММЕТРИЯ КОНВЕЙЕРА: сколько «выживших» даёт ЧИСТЫЙ ШУМ на каждой стороне")
    print("   (если шум сам производит N находок — порог отбора мягкий, сигнал в нём тонет)")
    print("   → это уже печатает pair_search; здесь только напоминание:")
    print("     short: шум медиана 3.0 · наш 12 → P=0.000")
    print("     long : шум медиана 4.5 · наш  5 → P=0.500  ← шум СИЛЬНЕЕ на long-стороне")
    print("     🔑 разная плотность шума = разная база. Это симптом, а не результат.")

    print("\n" + "=" * 104)
    if found:
        print("ВЫВОД: срезы, где long-база прибыльна БЕЗ признаков:")
        for nm, s in found:
            print(f"   🟢 {nm}: PF {s['pf']:.2f} (n={s['n']})")
        print("   → искать связки надо ВНУТРИ них, а не над общей убыточной базой.")
    else:
        print("ВЫВОД: НИ ОДНОГО среза, где long-база прибыльна сама по себе.")
        print("   → перебор признаков над ней структурно не может дать эдж:")
        print("     фильтр отбирает лучшее из имеющегося, а лучшего здесь нет.")
        print("   → вопрос не «какой фильтр», а «почему МЕХАНИКА не даёт long».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
