"""
wave_flat_hypothesis.py — ВОЛНЫ НЕ ВСЕГДА ИМПУЛЬСНЫЕ (Егор, 29.08.2026).

Замечание, которое объясняет мой собственный результат. Обе волновые оси оказались
мертвы в 2023 и 2026 (Δ −0.88 и −1.05), и я записал это как «эпоха». Егор возразил
по существу: **в 2023 и 2026 много БОКОВЫХ движений**, а признак «глубокий откат ноги»
в боковике означает совсем не то же, что в тренде — там откат это норма, а не сигнал.

То есть найденное затухание может быть не свойством ГОДА, а свойством ТИПА ДВИЖЕНИЯ,
которое с годом лишь коррелирует. Разница принципиальная: год не признак и в бой его
не поставить, а тип движения — признак, и его можно считать в реальном времени.

Гипотеза проверяется в три шага:
  1. РАЗМЕТИТЬ ноги на импульсные / боковые ПРИЧИННО (по свойствам самой ноги на баре
     входа, без будущего);
  2. посмотреть, правда ли 2023 и 2026 богаче боковиком;
  3. главное — прогнать находки ВНУТРИ импульсных и ВНУТРИ боковых отдельно. Если
     затухание объясняется составом, то внутри импульсных 2023 и 2026 оживут.

🔴 Что НЕ делается: разметка по будущему движению (это был бы look-ahead вида 5),
и подгонка порога флэта под результат — порог берётся из распределения, не из PnL.

    python scripts/wave_flat_hypothesis.py
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

from research_harness import line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"


def classify_wave(R: pd.DataFrame) -> pd.Series:
    """
    UP / DOWN / FLAT по свойствам НОГИ, известным на баре входа.

    Импульс от боковика отличает не размер, а КРУТИЗНА: сколько ATR нога прошла на
    бар. Медленная нога той же амплитуды — это перепиливание, а не ход.
    Порог берётся терцилями РАСПРЕДЕЛЕНИЯ, а не подбором под результат.
    """
    sp = R.leg_speed_atr_15m
    lo = sp.quantile(1 / 3)
    d = R.leg_dir_15m
    out = pd.Series("FLAT", index=R.index, dtype=object)
    fast = sp > lo
    out[fast & (d > 0)] = "UP"
    out[fast & (d < 0)] = "DOWN"
    return out


def main() -> int:
    R = pd.read_parquet(PQ)
    R["_wave"] = classify_wave(R)
    R["_rg"] = pd.cut(R.mkt_drift30, [-np.inf, -15, 0, 15, np.inf],
                      labels=["медведь", "слабый−", "слабый+", "бык"])
    churn = R.st5_count20_15m >= 2
    disc = R.leg_in_disc_15m == 1.0
    gate = R.mkt_drift_slope > 0

    print("=" * 104)
    print("ВОЛНЫ НЕ ВСЕГДА ИМПУЛЬСНЫЕ · UP / DOWN / FLAT")
    print("=" * 104)
    print(line(R, "  БАЗА ВСЁ"))

    print("\n── 1. СОСТАВ ПО ТИПУ ВОЛНЫ ──")
    for w in ("UP", "DOWN", "FLAT"):
        print(line(R[R._wave == w], f"  {w:<26}"))

    print("\n── 2. ПРАВДА ЛИ 2023 и 2026 БОГАЧЕ БОКОВИКОМ? ──")
    tab = pd.crosstab(R.year, R._wave, normalize="index") * 100
    print(tab.round(1).to_string())
    print("\n  доля FLAT по годам: " +
          " · ".join(f"{y} {tab.loc[y, 'FLAT']:.0f}%" for y in tab.index
                     if "FLAT" in tab.columns))

    print("\n── 3. 🔑 НАХОДКИ ВНУТРИ КАЖДОГО ТИПА ВОЛНЫ ──")
    for name, m in (("churn (частота сломов)", churn),
                    ("disc (глубокий откат)", disc),
                    ("churn + disc", churn & disc)):
        print(f"\n▸ {name}")
        for w in ("UP", "DOWN", "FLAT"):
            g = R[R._wave == w]
            a, b = stat(g[m[g.index]]), stat(g[~m[g.index]])
            if a is None or b is None:
                print(f"    {w:<6} мало данных"); continue
            print(f"    {w:<6} признак PF {a['pf']:5.2f} (n={a['n']:<5}) против "
                  f"контроль {b['pf']:5.2f} (n={b['n']:<5})  Δ {a['pf']-b['pf']:+.2f}"
                  f"  безтоп10% {a['bt']:+.0f}")

    print("\n── 4. 🔴 ГЛАВНОЕ: оживают ли 2023 и 2026 ВНУТРИ импульсных волн? ──")
    imp = R._wave != "FLAT"
    for y in sorted(R.year.unique()):
        gy = R[R.year == y]
        row = []
        for tag, sub in (("всё", gy), ("импульс", gy[imp[gy.index]]),
                         ("флэт", gy[~imp[gy.index]])):
            a, b = stat(sub[disc[sub.index]]), stat(sub[~disc[sub.index]])
            row.append(f"{tag} Δ {a['pf']-b['pf']:+5.2f} (n={a['n']:>4})"
                       if a is not None and b is not None else f"{tag} мало     ")
        print(f"    {y}  disc: " + "  |  ".join(row))
    print()
    for y in sorted(R.year.unique()):
        gy = R[R.year == y]
        row = []
        for tag, sub in (("всё", gy), ("импульс", gy[imp[gy.index]]),
                         ("флэт", gy[~imp[gy.index]])):
            a, b = stat(sub[churn[sub.index]]), stat(sub[~churn[sub.index]])
            row.append(f"{tag} Δ {a['pf']-b['pf']:+5.2f} (n={a['n']:>4})"
                       if a is not None and b is not None else f"{tag} мало     ")
        print(f"    {y}  churn: " + "  |  ".join(row))

    print("\n── 5. ТИП ВОЛНЫ КАК ГЕЙТ поверх боевого ──")
    print(line(R[gate], "  боевой гейт"))
    for w in ("UP", "DOWN", "FLAT"):
        s = stat(R[gate & (R._wave == w)])
        if s:
            print(line(R[gate & (R._wave == w)], f"  гейт + волна {w}"))
    print(line(R[gate & imp], "  гейт + импульс (не FLAT)"))
    print(line(R[gate & imp & churn & disc], "  гейт + импульс + обе находки"))
    print(line(R[gate & ~imp & churn & disc], "  гейт + ФЛЭТ + обе находки"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
