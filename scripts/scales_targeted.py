"""
scales_targeted.py — ПРИЦЕЛЬНАЯ проверка семьи двух структур (28.08.2026).

Зачем отдельно от глобального прогона. Слепой отбор по 605 признакам четырежды
подряд дал ноль, и семья SCALES утонула в нём вместе со всеми. Но это НЕ проверка
семьи: перебор ищет иголку в стоге и штрафуется за множественность 605 гипотез.

`sc_pullback` и `sc_resume` — не кандидаты для перебора. Это ДВЕ НАЗВАННЫЕ ЗАРАНЕЕ
геометрии входа из метода Егора ([[method_egor_two_scale_entry]]): старшая структура
даёт сторону, младшая — момент. Названную гипотезу мерят прямо, а не выкапывают.

Плюс два разреза, которых в глобальном отборе нет по построению:
  · РЕЖИМ — он делит выборку надвое (медведь PF 0.55 против быка 2.15), и признак,
    живущий в одной половине, в общем котле гаснет ([[regime_map_four_setups_downdrift]]);
  · КЛАСТЕР — `entry_ts` наконец собран механикой (в прошлых прогонах его не было).

Множественность честная: гипотез 20, а не 605, и перестановочный контроль гоняется
ровно по этим 20.

    python scripts/scales_targeted.py
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

# Семьи, которые можно проверить прицельно. Ключ → (префиксы колонок, НАЗВАННЫЕ
# ЗАРАНЕЕ гипотезы). Названные гипотезы не отбираются перебором — они объявлены до
# замера и меряются прямо, поэтому не платят штраф за множественность.
FAM = {
    "scales": (("st5_", "st50_", "sc_"),
               ["sc_pullback_15m", "sc_resume_15m", "sc_resume_vol_15m"]),
    # волны: канон ICT (вход в OTE), закон дисконта (глубокий откат) и перевод
    # находки [[two_scale_structure_minor_churn]] на волновой язык (ступенчатая нога)
    "waves":  (("leg_",),
               ["leg_in_ote_15m", "leg_in_disc_15m"]),
}
SCALES, NAMED = FAM["scales"]


def regime_of(R: pd.DataFrame) -> pd.Series:
    """Режим ПРИЧИННО: дрейф вселенной за 30 дней на баре входа, не по календарю."""
    d = R.mkt_drift30
    return pd.cut(d, [-np.inf, -15, 0, 15, np.inf],
                  labels=["медведь", "слабый−", "слабый+", "бык"])


def slice_report(R: pd.DataFrame, mask: pd.Series, title: str) -> None:
    """Один признак во ВСЕХ обязательных разрезах протокола вердикта."""
    sub = R[mask]
    if len(sub) < 40:
        print(f"  {title:<26} n={len(sub)} — мало")
        return
    print(line(sub, f"  {title:<26}"))
    for side in ("long", "short"):
        s = sub[sub.side == side]
        if len(s) >= 40:
            print(line(s, f"     · {side:<20}"))
    for rg in ("медведь", "бык"):
        s = sub[sub._rg == rg]
        if len(s) >= 40:
            print(line(s, f"     · {rg:<20}"))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="scales", choices=list(FAM))
    a = ap.parse_args()
    prefixes, named = FAM[a.family]

    R = pd.read_parquet(PQ)
    R["_rg"] = regime_of(R)
    cols = [c for c in R.columns if c.startswith(prefixes)]
    named = [c for c in named if c in R.columns]
    if not cols:
        print(f"семья {a.family} в parquet отсутствует — сначала прогон матрицы")
        return 1

    print("=" * 104)
    print(f"ПРИЦЕЛЬНАЯ ПРОВЕРКА: {a.family.upper()}")
    print("=" * 104)
    print(f"сделок {len(R)} · признаков семьи {len(cols)} · "
          f"IS {int((~R.oos).sum())} / OOS {int(R.oos.sum())}")
    print(line(R, "  БАЗА ВСЁ"))
    print(line(R[~R.oos], "  БАЗА IS"))
    print(line(R[R.oos], "  БАЗА OOS"))

    # ── 1. НАЗВАННЫЕ ГЕОМЕТРИИ ──────────────────────────────────────────────
    print("\n" + "=" * 104)
    print("1. ДВЕ НАЗВАННЫЕ ГЕОМЕТРИИ ВХОДА (гипотезы, а не находки перебора)")
    print("=" * 104)
    for c in named:
        print(f"\n▸ {c}  (доля баров-сделок {R[c].mean()*100:.1f}%)")
        slice_report(R, R[c] == 1.0, "ПРИЗНАК=1")
        slice_report(R, R[c] == 0.0, "ПРИЗНАК=0 (контроль)")

    # ── 2. ВСЯ СЕМЬЯ ЧЕСТНЫМ IS→OOS, множественность 20 ─────────────────────
    print("\n" + "=" * 104)
    print("2. ВСЯ СЕМЬЯ · IS→OOS · множественность 20 гипотез (не 605)")
    print("=" * 104)
    IS, OOS = R[~R.oos], R[R.oos]
    b_is, b_oos = stat(IS), stat(OOS)
    surv, cand = [], []
    for c in cols:
        v = IS[c].dropna()
        if v.nunique() < 2:
            continue
        # булев → f>0; числовой → лучший дециль в ОБЕ стороны
        if v.nunique() <= 2:
            tests = [(f"{c} = 1", IS[c] == 1.0, OOS[c] == 1.0)]
        else:
            tests = []
            for q in (0.1, 0.2, 0.3, 0.7, 0.8, 0.9):
                t = float(v.quantile(q))
                if q <= 0.3:
                    tests.append((f"{c} ≤ {t:.4g}", IS[c] <= t, OOS[c] <= t))
                else:
                    tests.append((f"{c} ≥ {t:.4g}", IS[c] >= t, OOS[c] >= t))
        for name, mi, mo in tests:
            s = stat(IS[mi])
            if s is None or s["n"] < 120 or s["pf"] <= b_is["pf"] * 1.15:
                continue
            cand.append((s["pf"], name, mo, s))
    cand.sort(reverse=True, key=lambda x: x[0])
    top = cand[:12]
    print(f"кандидатов на IS: {len(cand)} (показаны 12 лучших)")
    for pf, name, mo, s in top:
        o = stat(OOS[mo])
        if o is None:
            print(f"  {name:<40} IS PF {pf:5.2f} n={s['n']:<5} → OOS мало данных")
            continue
        ok = o["pf"] > b_oos["pf"] * 1.15 and o["n"] >= 80
        if ok:
            surv.append(name)
        print(f"  {name:<40} IS PF {pf:5.2f} n={s['n']:<5} → "
              f"OOS PF {o['pf']:5.2f} n={o['n']:<5} безтоп10% {o['bt']:>+8.0f}"
              f"{'  ✅' if ok else ''}")
    print(f"\nПЕРЕЖИЛО OOS: {len(surv)} из {len(top)}   "
          f"(база OOS {b_oos['pf']:.2f}, порог {b_oos['pf']*1.15:.2f})")

    # ── 3. ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ по этим же 20 признакам ─────────────────
    print("\n🎲 ПЕРЕСТАНОВОЧНЫЙ КОНТРОЛЬ (20 перемешиваний, тот же конвейер):")
    rng = np.random.default_rng(7)
    noise = []
    for _ in range(20):
        Rs = R.copy()
        Rs["pnl"] = rng.permutation(Rs.pnl.values)
        Is, Os = Rs[~Rs.oos], Rs[Rs.oos]
        bi, bo = stat(Is), stat(Os)
        cs = []
        for c in cols:
            v = Is[c].dropna()
            if v.nunique() < 2:
                continue
            if v.nunique() <= 2:
                ts = [(Is[c] == 1.0, Os[c] == 1.0)]
            else:
                ts = []
                for q in (0.1, 0.2, 0.3, 0.7, 0.8, 0.9):
                    t = float(v.quantile(q))
                    ts.append((Is[c] <= t, Os[c] <= t) if q <= 0.3
                              else (Is[c] >= t, Os[c] >= t))
            for mi, mo in ts:
                s = stat(Is[mi])
                if s is not None and s["n"] >= 120 and s["pf"] > bi["pf"] * 1.15:
                    cs.append((s["pf"], mo))
        cs.sort(reverse=True, key=lambda x: x[0])
        k = 0
        for pf, mo in cs[:12]:
            o = stat(Os[mo])
            if o is not None and o["pf"] > bo["pf"] * 1.15 and o["n"] >= 80:
                k += 1
        noise.append(k)
    noise = np.array(noise)
    p = float((noise >= len(surv)).mean())
    print(f"   ШУМ переживает: медиана {np.median(noise):.1f} · "
          f"95-й перцентиль {np.percentile(noise, 95):.1f} · максимум {noise.max()}")
    print(f"   наш результат {len(surv)} · P(шум ≥ нашего) = {p:.3f}")
    print("   " + ("🟢 ОТЛИЧИМО ОТ ШУМА" if p < 0.05 else
                   "🔴 НЕ отличимо от шума" if p > 0.15 else "🟡 на границе"))

    # ── 4. КЛАСТЕР — впервые считается, entry_ts наконец собран ──────────────
    print("\n" + "=" * 104)
    print("4. КЛАСТЕР (одиночка против компании ≥2 в окне 2ч) — ВПЕРВЫЕ")
    print("=" * 104)
    t = pd.to_datetime(R.entry_ts, utc=True, errors="coerce")
    if t.notna().sum() < len(R) * 0.5:
        print("  entry_ts не собран — срез невозможен")
    else:
        bucket = t.dt.floor("2h")
        cnt = bucket.map(bucket.value_counts())
        R["_clu"] = np.where(cnt >= 2, "кластер≥2", "одиночка")
        for g in ("одиночка", "кластер≥2"):
            print(line(R[R._clu == g], f"  {g:<26}"))
        print("\n  · те же группы ВНУТРИ названных геометрий:")
        for c in named:
            for g in ("одиночка", "кластер≥2"):
                m = (R[c] == 1.0) & (R._clu == g)
                if m.sum() >= 40:
                    print(line(R[m], f"    {c.replace('_15m','')} · {g:<12}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
