"""
long_regime_axis.py — ГДЕ LONG ЖИВЁТ: ищем ПРИЧИННУЮ ось режима (30.08.2026).

Инвентаризация (`long_inventory.py`) показала то, что переворачивает вердикт «связок в long нет»:

    2023  дрейф +11.31%   long PF 1.53   short PF 0.13   🐂 БЫК
    2024  дрейф  -6.48%   long PF 1.35   short PF 1.57   🐻
    2025  дрейф -17.51%   long PF 0.64   short PF 1.17   🐻
    2026  дрейф  -6.38%   long PF 0.48   short PF 0.83   🐻

Рынок ДВУСТОРОННИЙ — зеркало в 2023 идеальное. Односторонне ОКНО: три медвежьих года
из четырёх. Перебор признаков по всему окну усредняет 1.53 с 0.48 и возвращает шум —
верный ответ на неверный вопрос.

Но «разрезать по 2023» = подгонка под один год (мой же флаг 🔴 ОДИН ГОД это ловит).
Нужна ПРИЧИННАЯ мера режима, которая:
    · отделяет 2023-подобные условия НЕ по календарю;
    · находит бычьи участки ВНУТРИ медвежьих лет — иначе это тот же год под другим именем;
    · считается только по прошлым барам.

Короткая мера уже провалилась: `drift30>3` даёт long PF 0.95 — то есть 2023 отличается
не 30-барным окном. Проверяем длинные: drift90/drift180, breadth_ma200, btc_above_ma200.

Обязательная проверка каждой оси — РАСПРЕДЕЛЕНИЕ ПО ГОДАМ: если срез на 80% состоит
из 2023, ось бесполезна, это переименованный календарь.

    python scripts/long_regime_axis.py
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
AXES = ["mkt_drift180", "mkt_drift90", "mkt_drift30", "mkt_breadth_ma200",
        "btc_above_ma200", "btc_ret30", "mkt_drift_slope", "mkt_breadth_up30"]


def year_mix(sub: pd.DataFrame) -> tuple[str, float]:
    """Состав среза по годам + доля доминирующего. Ловит «переименованный календарь»."""
    if not len(sub):
        return "—", 1.0
    vc = sub.year.value_counts(normalize=True).sort_index()
    txt = " ".join(f"{int(y)}:{v*100:.0f}%" for y, v in vc.items())
    return txt, float(vc.max())


def main() -> int:
    X = pd.read_parquet(PQ)
    lo, sh = X.side == "long", X.side == "short"
    L, S = X[lo], X[sh]
    bl, bs = stat(L), stat(S)

    print("=" * 108)
    print(f"ПОИСК ПРИЧИННОЙ ОСИ РЕЖИМА ДЛЯ LONG · база long PF {bl['pf']:.2f} · short {bs['pf']:.2f}")
    print("=" * 108)
    print("критерий годности оси: PF>1 · НЕ один год · зеркало short слабее · охват монет >35%")

    good = []
    for ax in AXES:
        if ax not in X.columns:
            continue
        v = L[ax].dropna()
        if v.nunique() < 3:
            qs = [(f"{ax}=1", L[ax] == 1, S[ax] == 1), (f"{ax}=0", L[ax] == 0, S[ax] == 0)]
        else:
            qs = []
            for q in (0.5, 0.7, 0.85):
                t = float(v.quantile(q))
                qs.append((f"{ax}>={t:.3g}", L[ax] >= t, S[ax] >= t))
        print(f"\n── {ax} ──")
        for nm, ml, ms in qs:
            a, m = stat(L[ml]), stat(S[ms])
            if not a or a["n"] < 250:
                continue
            mix, top = year_mix(L[ml])
            mirror = f"short {m['pf']:.2f} (×{m['pf']/bs['pf']:.2f})" if m else "short —"
            flag = " 🔴 ОДИН ГОД" if top >= 0.7 else ""
            ok = a["pf"] >= 1.0 and top < 0.7 and a["cov"] >= 35
            print(f"   {nm:<28} n={a['n']:>5} PF {a['pf']:5.2f} ×{a['pf']/bl['pf']:.2f}"
                  f"  безтоп10% {a['bt']:+7.0f} охват {a['cov']:3.0f}%  {mirror}{flag}"
                  + ("  🟢 ГОДНА" if ok else ""))
            print(f"      состав: {mix}")
            if ok:
                good.append((nm, ml, a))

    print("\n" + "=" * 108)
    if not good:
        print("НИ ОДНА причинная ось не даёт long PF>1 при составе из нескольких лет.")
        print("→ 2023 отличается чем-то, чего в макро-признаках матрицы НЕТ.")
        print("  Гипотезы: (1) мера должна быть по МОНЕТЕ, а не по вселенной;")
        print("            (2) нужна ПРОИЗВОДНАЯ режима, а не уровень (закон cycle_derivative);")
        print("            (3) 2023 = высокий фандинг + рост, отдельная связка.")
        return 0

    print(f"ГОДНЫХ ОСЕЙ: {len(good)}")
    for nm, ml, a in good:
        print(f"   🟢 {nm}: PF {a['pf']:.2f} n={a['n']} охват {a['cov']:.0f}%")

    print("\n── ПО ГОДАМ внутри лучшей оси (не держится ли всё на одном) ──")
    nm, ml, _ = max(good, key=lambda g: g[2]["pf"])
    print(f"ось: {nm}")
    for y in sorted(X.year.dropna().unique()):
        g = L[L.year == y]
        a, b = stat(g[ml[g.index]]), stat(g)
        if a and b and b["pf"]:
            print(f"   {int(y)}: PF {a['pf']:5.2f} (n={a['n']:>4}) против базы года {b['pf']:5.2f}"
                  f"  ×{a['pf']/b['pf']:.2f}  безтоп10% {a['bt']:+7.0f}")
        else:
            print(f"   {int(y)}: мало данных")
    return 0


if __name__ == "__main__":
    sys.exit(main())
