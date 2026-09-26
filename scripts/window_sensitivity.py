"""
window_sensitivity.py — КАКИЕ ПРИЗНАКИ ЗАВИСЯТ ОТ ОКНА РАСЧЁТА (29.08.2026).

Повод — отменённая находка. EQH мерился с детектором, получавшим ПОЛНУЮ историю символа
(~60k баров), а боевой runner подаёт `bars: 1000`. Перемер боевым окном обрушил подъём
с ×2.11 до ×1.20, а Жаккар между двумя версиями признака составил 0.131 — то есть это
разные признаки ([[eqh_liquidity_short_works_in_2026]]).

🔑 Дефект СИСТЕМНЫЙ, а не про один признак: вся матрица считается на полной истории.
Но зависят от окна НЕ ВСЕ. Rolling-метрики (ATR, WT, EMA, объёмные отношения, дистанции
до скользящих) по построению смотрят на последние N баров и от длины ряда не меняются.
Зависят те, что копят СОБЫТИЯ и УРОВНИ: свинги, структура, ордер-блоки, FVG, EQH,
эллиоттовские импульсы, ноги.

Скрипт считает КАЖДЫЙ признак двумя способами на одних и тех же барах:
  A. полная история (как считалось до сих пор)
  B. скользящее окно `--bars` (как видит бой)
и печатает расхождение. Пересчитывать всю матрицу вслепую дорого и не нужно — сначала
надо знать, что именно ломается.

    python scripts/window_sensitivity.py --symbols 3 --bars 1000
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

from research_harness import load, universe        # noqa: E402

# Точки, в которых сравниваем. Меньше точек — быстрее; для вердикта хватает десятков,
# потому что нас интересует СИСТЕМАТИЧЕСКОЕ расхождение, а не редкий выброс.
PROBES = 40


def feature_frames(df: pd.DataFrame, tf: str, symbol: str):
    """Полный набор признаков одного символа — тот же путь, что в матрице."""
    from core.calculators.combinator_core import compute_flags
    from matrix_full import (smc_state_features, structure_scales_features,
                             symbol_features, wave_features)
    # 04.09: `candle_volume_features` НЕ вызывать — семья CANDLE+VOL переехала
    # в `compute_flags`, второй вызов дал бы 14 дублирующихся колонок и 2D в `F[c].values`.
    parts = [compute_flags(df, tf, include_pivots=False)]
    for fn in (symbol_features, structure_scales_features,
               wave_features, smc_state_features):
        try:
            parts.append(fn(df, tf))
        except Exception:                          # noqa: BLE001
            pass
    return pd.concat(parts, axis=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=3)
    ap.add_argument("--bars", type=int, default=1000)
    ap.add_argument("--tf", default="15m")
    a = ap.parse_args()

    print("=" * 104)
    print(f"ЧУВСТВИТЕЛЬНОСТЬ ПРИЗНАКОВ К ОКНУ · ТФ {a.tf} · боевое окно {a.bars} баров")
    print("=" * 104)
    print("A = полная история (как считалось), B = скользящее окно (как видит бой)\n")

    diff_share: dict[str, list[float]] = {}
    for sym in universe(a.tf, n=a.symbols):
        try:
            d = load(sym, a.tf)
        except Exception:                          # noqa: BLE001
            continue
        if d is None or len(d) < a.bars * 3:
            continue
        full = feature_frames(d, a.tf, sym)
        # точки проверки равномерно по второй половине ряда
        idxs = np.linspace(a.bars + 50, len(d) - 2, PROBES).astype(int)
        rows_a, rows_b = [], []
        for i in idxs:
            w = d.iloc[i - a.bars:i + 1]
            part = feature_frames(w, a.tf, sym)
            rows_b.append(part.iloc[-1])
            rows_a.append(full.iloc[i])
        A = pd.DataFrame(rows_a).reset_index(drop=True)
        B = pd.DataFrame(rows_b).reset_index(drop=True)
        common = [c for c in A.columns if c in B.columns]
        for c in common:
            x, y = A[c].values.astype(float), B[c].values.astype(float)
            both_nan = np.isnan(x) & np.isnan(y)
            neq = ~(both_nan | np.isclose(x, y, rtol=1e-3, atol=1e-9, equal_nan=True))
            share = float(neq.mean())
            # 🔴 ПОПРАВКА: для РЕДКОГО булева доля расхождений обманывает. Признак,
            # срабатывающий на 5% баров, может совпадать в 95% точек и при этом почти
            # не пересекаться по самим срабатываниям — что и случилось с EQH (5% здесь
            # против Жаккара 0.131 на реальных сделках). Для булевых считаем НЕсовпадение
            # срабатываний (1 − Жаккар), это и есть та величина, которая ломает выводы.
            u = np.nansum((x == 1.0) | (y == 1.0))
            if u > 0 and np.nanmax(np.abs(np.concatenate([x, y]))) <= 1.0:
                inter = np.nansum((x == 1.0) & (y == 1.0))
                share = max(share, 1.0 - inter / u)
            diff_share.setdefault(c, []).append(share)
        print(f"  {sym}: сверено {len(common)} признаков в {len(idxs)} точках")

    if not diff_share:
        print("\n🔴 нечего сравнивать — символы не загрузились")
        return 1

    res = pd.Series({c: float(np.mean(v)) for c, v in diff_share.items()}).sort_values()
    stable = res[res <= 0.02]
    shaky = res[(res > 0.02) & (res <= 0.20)]
    broken = res[res > 0.20]

    print("\n" + "=" * 104)
    print("ИТОГ: доля точек, где значение признака РАЗОШЛОСЬ между A и B")
    print("=" * 104)
    print(f"  🟢 УСТОЙЧИВЫЕ  (≤2%):   {len(stable):>4} признаков — окно им не важно")
    print(f"  🟡 ШАТКИЕ      (2-20%): {len(shaky):>4}")
    print(f"  🔴 ЗАВИСИМЫЕ   (>20%):  {len(broken):>4} — мерить их на полной истории НЕЛЬЗЯ")

    if len(broken):
        print("\n🔴 ХУДШИЕ 25 (расхождение → имя):")
        for c, v in broken.sort_values(ascending=False).head(25).items():
            print(f"    {v*100:5.1f}%  {c}")
    if len(shaky):
        print("\n🟡 ШАТКИЕ, топ-10:")
        for c, v in shaky.sort_values(ascending=False).head(10).items():
            print(f"    {v*100:5.1f}%  {c}")

    out = ROOT / "cache" / "window_sensitivity.csv"
    res.rename("diff_share").to_csv(out, encoding="utf-8")
    print(f"\nполная таблица → {out}")
    print("🔑 Пересчитывать окном нужно ТОЛЬКО зависимые — остальное не изменится.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
