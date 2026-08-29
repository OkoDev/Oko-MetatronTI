"""
rs_rank_verdict.py — ПРОТОКОЛ ПО НАХОДКЕ rs_rank30 (30.08.2026).

Находка: long живёт на монете во ВТОРОЙ СНИЗУ ЧЕТВЕРТИ по силе за 30 дней.

    26.24 <= rs_rank30 <= 48.47   n=732  PF 1.33 (база 0.89, ×1.49)  зеркало short ×0.62
    2023 ×0.93 · 2024 ×1.54 · 2025 ×1.56 · 2026 ×2.67   train ×1.22 → test ×1.95

Контекст, почему это важно: Егор возразил на вердикт «связок в long нет» словами
«не может рынок давать только одну сторону». Он был прав, и причина оказалась не в
переборе, а в МАТРИЦЕ — семьи «относительная сила монеты» в ней не было НИКОГДА.
Все 753 колонки описывали либо монету саму по себе, либо вселенную целиком; ни одна
не отвечала на вопрос «сильнее ли эта монета рынка».

Здесь закрываются обязательные пункты протокола, которых проба не делала:
    1. НЕ ТЕ ЖЕ ЛИ СДЕЛКИ, что у известной long-находки (пробой swing-минимума);
    2. связки: с пробоем · с боевым дрейф-гейтом · с обоими;
    3. МНОЖЕСТВЕННОСТЬ: находка — N-я нарезка, назвать N и дать поправку;
    4. срезы протокола: размер стопа · ликвидность · кластер · охват монет;
    5. три способа быть артефактом, самый вероятный — проверить.

    python scripts/rs_rank_verdict.py
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

from research_harness import stat, line              # noqa: E402
from scripts.rs_probe import attach                  # noqa: E402

PQ = ROOT / "cache" / "matrix_run_15m.parquet"
LO, HI = 26.24, 48.47
BREAK_COL = "smc_swing_major_l_dist_atr_15m"          # знаковая дистанция до swing-минимума


def main() -> int:
    X = attach(pd.read_parquet(PQ))
    L = X[X.side == "long"]
    bl = stat(L)
    m = (L.rs_rank30 >= LO) & (L.rs_rank30 <= HI)

    print("=" * 104)
    print(f"ПРОТОКОЛ · rs_rank30 ∈ [{LO}, {HI}] · база long PF {bl['pf']:.2f} n={bl['n']}")
    print("=" * 104)
    print(line(L[m], "  находка"))

    # ── 1. пересечение с известной long-находкой ────────────────────────────
    print("\n1. НЕ ТЕ ЖЕ ЛИ ЭТО СДЕЛКИ, что «пробой swing-минимума»")
    if BREAK_COL in L.columns:
        mb = (L[BREAK_COL] >= -1.0) & (L[BREAK_COL] < 0)
        inter = int((m & mb).sum())
        union = int((m | mb).sum())
        print(f"   пробой n={int(mb.sum())} · находка n={int(m.sum())} · пересечение {inter}")
        print(f"   Жаккар = {inter/union:.3f}  →  "
              + ("🔴 ОДНО И ТО ЖЕ" if inter / union >= 0.5 else "🟢 РАЗНЫЕ явления"))
        for nm, mm in (("только пробой", mb & ~m), ("только rs_rank", m & ~mb),
                       ("оба (связка)", m & mb)):
            print(line(L[mm], f"   {nm:<18}"))
    else:
        print(f"   🔴 колонки {BREAK_COL} нет в этой матрице — пересечение не проверено")

    # ── 2. связки ───────────────────────────────────────────────────────────
    print("\n2. СВЯЗКИ С БОЕВЫМ ДРЕЙФ-ГЕЙТОМ")
    gate = L.mkt_drift_slope > 0
    for nm, mm in (("гейт один", gate), ("находка одна", m),
                   ("находка + гейт", m & gate), ("находка БЕЗ гейта", m & ~gate)):
        print(line(L[mm], f"   {nm:<22}"))

    # ── 3. множественность ──────────────────────────────────────────────────
    print("\n3. МНОЖЕСТВЕННОЕ ТЕСТИРОВАНИЕ (честно: сколько клеток перебрано)")
    n_tests = 10 * 8            # 10 признаков RS × 8 диапазонов в rs_probe
    print(f"   перебрано клеток: {n_tests} (10 признаков RS × 8 диапазонов)")
    rng = np.random.default_rng(2026)
    real = stat(L[m])["pf"] / bl["pf"]
    # 🔴 перестановка МАКСИМУМА по всему перебору, а не одной клетки:
    #    иначе P занижен ровно во столько раз, сколько клеток просмотрено
    cols = [c for c in ("rs30", "rs90", "rs180", "rs_rank30", "rs_rank90", "rs_slope",
                        "own_above_ma200", "rs_days_up30", "beta_btc", "corr_btc90")
            if c in L.columns]
    masks = []
    for c in cols:
        v = L[c].dropna()
        for q1, q2 in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0),
                       (0.2, 0.6), (0.3, 0.7), (0.4, 0.8)):
            lo_, hi_ = float(v.quantile(q1)), float(v.quantile(q2))
            mm = (L[c] >= lo_) & (L[c] <= hi_)
            if mm.sum() >= 300:
                masks.append(mm)
    worst = []
    for _ in range(50):
        Ls = L.assign(pnl=rng.permutation(L.pnl.values))
        b = stat(Ls)
        best = 0.0
        for mm in masks:
            s = stat(Ls[mm])
            if s and b["pf"]:
                best = max(best, s["pf"] / b["pf"])
        worst.append(best)
    worst = np.array(worst)
    p_fam = float((worst >= real).mean())
    print(f"   наш ×{real:.2f} против ЛУЧШЕГО ИЗ {len(masks)} клеток на перемешанном:")
    print(f"   шум: медиана ×{np.median(worst):.2f} · 95-й ×{np.quantile(worst,0.95):.2f}"
          f" · максимум ×{worst.max():.2f}")
    print(f"   P(шум ≥ нашего) с поправкой на семью = {p_fam:.3f} "
          + ("🟢 переживает" if p_fam < 0.05 else "🟡 на границе" if p_fam <= 0.15
             else "🔴 НЕ переживает поправку"))

    # ── 4. срезы протокола ──────────────────────────────────────────────────
    print("\n4. ОБЯЗАТЕЛЬНЫЕ СРЕЗЫ")
    q33, q67 = L.stop_pct.quantile(0.33), L.stop_pct.quantile(0.67)
    for nm, mm in (("узкий стоп", m & (L.stop_pct < q33)),
                   ("средний стоп", m & (L.stop_pct >= q33) & (L.stop_pct <= q67)),
                   ("широкий стоп", m & (L.stop_pct > q67))):
        print(line(L[mm], f"   {nm:<22}"))
    if "mkt_drift30" in L.columns:
        for nm, mm in (("в бычьих барах", m & (L.mkt_drift30 > 0)),
                       ("в медвежьих барах", m & (L.mkt_drift30 < 0))):
            print(line(L[mm], f"   {nm:<22}"))

    per = L[m].groupby("sym").pnl.sum().sort_values(ascending=False)
    print(f"\n   охват: {int((per>0).sum())}/{len(per)} монет · сумма {per.sum():+.0f}%"
          f" · без лучших трёх {per.iloc[3:].sum():+.0f}%")
    print(f"   топ-5: " + ", ".join(f"{i} {v:+.0f}%" for i, v in per.head(5).items()))

    # ── 5. 2026 крупным планом ──────────────────────────────────────────────
    print("\n5. 2026 КРУПНЫМ ПЛАНОМ (год, который ломает все правила)")
    g = L[L.year == 2026]
    print(line(g, "   вся база long 2026"))
    print(line(g[m[g.index]], "   находка 2026"))
    if len(g[m[g.index]]):
        pm = g[m[g.index]].groupby("sym").pnl.sum().sort_values(ascending=False)
        print(f"   монет в плюсе {int((pm>0).sum())}/{len(pm)} · без лучших трёх"
              f" {pm.iloc[3:].sum():+.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
