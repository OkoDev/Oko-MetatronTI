"""
macro_regime_sign.py — ОБЪЯСНЯЕТ ЛИ МАКРО-РЕЖИМ ЗНАК НАХОДОК (29.08.2026).

Повод — график LINK 1D от Егора: с начала 2026 обвал −51%, затем **239 дней боковика**
7000-10000, и «весь рынок примерно такой».

Это вскрывает ошибку масштаба во всём, что мерилось сегодня. Тип волны я считал на
`15m × length 50` = **12.5 часов**. Старший масштаб проекта `4h × 5` = 20 часов.
А режим, который на самом деле решает, длится **восемь месяцев**. Классификация волн
внутри дня физически не может увидеть многомесячный боковик.

Второе следствие, более важное: механика `impulse_fib` входит на откате 0.382 и целится
в −1.618 (РАСШИРЕНИЕ хода). В 239-дневном диапазоне такая цель структурно недостижима —
цена доходит до границы и возвращается. Никакой фильтр этого не чинит: фильтр выбирает
сделки, но не меняет того, что цель лежит за пределами диапазона.

Проверяем два макро-признака на масштабе МЕСЯЦЕВ (4h-бары, окна 30/90/180 дней):
  ER  — Kaufman Efficiency Ratio: |чистый ход| / сумма модулей. Низкий = боковик;
  POS — где цена внутри многомесячного диапазона (0 у дна, 1 у вершины);
  WIDTH — ширина диапазона в %.

Вопрос ровно один: объясняют ли они ЗНАК, который не объяснили ни режим по дрейфу,
ни тип волны, ни CHoCH ([[choch_separates_but_not_the_sign]]).

    python scripts/macro_regime_sign.py
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

from research_harness import load, line, stat        # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
BARS_PER_DAY_4H = 6


def macro_features(sym: str) -> pd.DataFrame | None:
    """ER / положение в диапазоне / ширина на окнах 30-90-180 дней, ПРИЧИННО (shift 1)."""
    try:
        d = load(sym, "4h")
    except Exception:              # noqa: BLE001
        return None
    if d is None or len(d) < 300:
        return None
    c = d.close
    out = {}
    for days in (30, 90, 180):
        w = days * BARS_PER_DAY_4H
        if len(d) < w + 10:
            continue
        net = (c - c.shift(w)).abs()
        path = c.diff().abs().rolling(w).sum()
        out[f"er{days}"] = (net / path.replace(0, np.nan)).values
        hi = d.high.rolling(w).max(); lo = d.low.rolling(w).min()
        rng = (hi - lo).replace(0, np.nan)
        out[f"pos{days}"] = ((c - lo) / rng).values
        out[f"width{days}"] = (rng / lo * 100).values
    if not out:
        return None
    return pd.DataFrame(out, index=d.index).shift(1)      # 🔴 закрытый бар


def main() -> int:
    R = pd.read_parquet(PQ)
    R["_ts"] = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    R = R[R._ts.notna()].copy()

    parts = []
    for sym, g in R.groupby("sym"):
        M = macro_features(sym)
        if M is None:
            continue
        j = pd.merge_asof(g.sort_values("_ts"), M.reset_index().rename(
            columns={M.index.name or "index": "_ts"}).sort_values("_ts"),
            on="_ts", direction="backward")
        parts.append(j)
    R = pd.concat(parts, ignore_index=True)
    print(f"сделок с макро-контекстом: {R.er180.notna().sum()} из {len(R)}")

    sp = R.leg_speed_atr_15m
    churn = R.st5_count20_15m >= 2
    ch = R.st50_is_choch_15m == 1.0
    gate = R.mkt_drift_slope > 0
    best = gate & ch & (R.side == "short")          # лучшая клетка сессии

    print("\n" + "=" * 104)
    print("1. КАКОЙ МАКРО-РЕЖИМ БЫЛ В КАЖДОМ ГОДУ (проверка картинки Егора)")
    print("=" * 104)
    for y in sorted(R.year.unique()):
        g = R[R.year == y]
        print(f"  {y}:  ER180 медиана {g.er180.median():.3f} · ER90 {g.er90.median():.3f}"
              f" · ширина180 {g.width180.median():5.1f}% · положение в диапазоне180 "
              f"{g.pos180.median():.2f}")
    print("\n  🔑 ER (Kaufman): ~1.0 = чистый тренд, ~0.0 = топтание. Ниже 0.2 — боковик.")

    print("\n" + "=" * 104)
    print("2. 🔑 ОБЪЯСНЯЕТ ЛИ ER ЗНАК? Лучшая клетка (гейт+CHoCH+short) по корзинам ER180")
    print("=" * 104)
    q = pd.qcut(R.er180, 3, labels=["ER низкий (боковик)", "ER средний", "ER высокий (тренд)"])
    for lab in q.cat.categories:
        m = (q == lab)
        a, b = stat(R[m & best]), stat(R[m & gate])
        if a is None or b is None:
            print(f"  {lab:<24} мало"); continue
        print(f"  {lab:<24} клетка PF {a['pf']:5.2f} (n={a['n']:>4}) против "
              f"гейт {b['pf']:5.2f} (n={b['n']:>4})  ×{a['pf']/b['pf']:.2f}"
              f"  безтоп10% {a['bt']:+.0f}")

    print("\n  то же для churn:")
    for lab in q.cat.categories:
        m = (q == lab)
        a, b = stat(R[m & churn]), stat(R[m & ~churn])
        if a and b and b["pf"]:
            print(f"  {lab:<24} churn PF {a['pf']:5.2f} (n={a['n']:>4}) против "
                  f"контроль {b['pf']:5.2f}  ×{a['pf']/b['pf']:.2f}")

    print("\n" + "=" * 104)
    print("3. 🔴 ГЛАВНОЕ: достижима ли ЦЕЛЬ механики в боковике")
    print("=" * 104)
    print("   Механика целится в −1.618 хода. Если цель лежит за границей многомесячного")
    print("   диапазона, никакой фильтр её не приблизит — это свойство ГЕОМЕТРИИ.")
    for lab in q.cat.categories:
        m = (q == lab)
        g = R[m]
        if len(g) < 100:
            continue
        wr = (g.pnl > 0).mean() * 100
        print(line(g, f"  {lab:<24}") + f"   WR {wr:.1f}%")

    print("\n" + "=" * 104)
    print("4. ER ПО ГОДАМ × ЗНАК — совпадает ли переворот с падением ER")
    print("=" * 104)
    for y in sorted(R.year.unique()):
        g = R[R.year == y]
        a, b = stat(g[best[g.index] if hasattr(best, "index") else best]), stat(g[gate[g.index]])
        er = g.er180.median()
        if a and b and b["pf"]:
            print(f"  {y}: ER180 {er:.3f} → клетка ×{a['pf']/b['pf']:5.2f} "
                  f"(PF {a['pf']:.2f}, n={a['n']})")
        else:
            print(f"  {y}: ER180 {er:.3f} → мало данных")
    return 0


if __name__ == "__main__":
    sys.exit(main())
