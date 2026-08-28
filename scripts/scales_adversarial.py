"""
scales_adversarial.py — СОСТЯЗАТЕЛЬНЫЙ ПРОХОД по находке двух структур (28.08.2026).

Прицельный замер дал 9 выживших из 12 при P(шум) = 0.000 — первый результат за
сессию, отличимый от шума. Протокол вердикта требует ломать такое, а не докладывать.

Проверяются ЧЕТЫРЕ способа оказаться артефактом, в порядке убывания вероятности:

  1. ЭТО РЕЖИМ. Режим — сильнейший известный рычаг (медведь 0.55 против быка 2.15).
     Если «старший слом давно» просто чаще случается в быке, то находка — переоткрытие
     дрейф-гейта, который УЖЕ стоит в бою. Проверка: признак ВНУТРИ каждого режима.
  2. ЭТО ОДНА НАХОДКА, А НЕ ДЕВЯТЬ. Корреляция `sc_minor_since_major`↔`st50_age` = 0.95.
     Считаем независимые кластеры и меряем каждый как одну гипотезу.
  3. ЭТО ЭПОХА. IS и OOS разбиты по МОНЕТАМ, окна времени совпадают полностью
     (2023-01 → 2026-08 обе половины). Признак, живущий в одном годе, пройдёт такой
     OOS. Проверка: разрез по годам.
  4. ЭТО ХВОСТ. Безтоп10% отрицательный у ВСЕХ выживших — закон требует назвать это
     прямо, а не спрятать за PF.

    python scripts/scales_adversarial.py
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

# Три НЕЗАВИСИМЫХ кластера (по корреляции и Жаккару), а не девять «находок».
# Внутри кластера взят представитель с наибольшей выборкой — не с лучшим PF,
# иначе выбор представителя сам становится подгонкой.
CLUSTERS_SCALES = {
    "A · старший слом ДАВНО":      lambda R: R.st50_age_15m >= 108,
    "B · младшая ПИЛИТ (часто)":   lambda R: R.st5_count20_15m >= 2,
    "C · цена УШЛА от младшего":   lambda R: R.st5_dist_atr_15m <= -0.9212,
}

# Волны. Здесь коллинеарность ещё грубее, чем у SCALES: `leg_pos`, `leg_retr` и
# `leg_in_disc` — ОДНО И ТО ЖЕ по построению (retr = 1 − pos, in_disc = retr > 0.5),
# и все три попали в выживших по отдельности. Берём один представитель.
# `leg_speed_atr` = амплитуда / длина, поэтому «медленная нога» и «длинная нога» —
# тоже почти одно; разводим их явной проверкой корреляции ниже.
CLUSTERS_WAVES = {
    "A · ГЛУБОКИЙ ОТКАТ (дисконт)":  lambda R: R.leg_in_disc_15m == 1.0,
    "B · ДЛИННАЯ нога":              lambda R: R.leg_span_bars_15m >= 159,
    "C · МНОГО младших волн в ноге": lambda R: R.leg_minor_breaks_15m >= 11,
}

FAMILIES = {"scales": CLUSTERS_SCALES, "waves": CLUSTERS_WAVES}


def regime_of(R):
    return pd.cut(R.mkt_drift30, [-np.inf, -15, 0, 15, np.inf],
                  labels=["медведь", "слабый−", "слабый+", "бык"])


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", default="scales", choices=list(FAMILIES))
    args = ap.parse_args()
    FAMILY = args.family
    CLUSTERS = FAMILIES[FAMILY]

    R = pd.read_parquet(PQ)
    R["_rg"] = regime_of(R)
    base = stat(R)

    print("=" * 104)
    print(f"СОСТЯЗАТЕЛЬНЫЙ ПРОХОД: ломаем находку · {FAMILY.upper()}")
    print("=" * 104)
    print(line(R, "  БАЗА ВСЁ"))
    print("\n🔴 ПОДОЗРЕНИЕ 0 (заявлено сразу): IS/OOS разбиты ПО МОНЕТАМ, окна времени")
    print("   совпадают целиком — 2023-01→2026-08 в ОБЕИХ половинах. Такой OOS проверяет")
    print("   перенос между монетами, но НЕ между эпохами.")

    for name, fn in CLUSTERS.items():
        m = fn(R)
        s, sc = stat(R[m]), stat(R[~m])
        print("\n" + "=" * 104)
        print(f"{name}   (доля сделок {m.mean()*100:.1f}%)")
        print("=" * 104)
        print(line(R[m], "  ПРИЗНАК=1"))
        print(line(R[~m], "  контроль=0"))
        lift = (s["pf"] / sc["pf"]) if sc and sc["pf"] else float("nan")
        print(f"  подъём против контроля: ×{lift:.2f}   "
              f"хрупкость (безтоп10%) {s['bt']:+.0f} "
              f"{'🔴 ОТРИЦАТЕЛЬНАЯ — без верхних 10% сделок это убыток' if s['bt'] < 0 else '🟢'}")

        print("\n  ── 1. ЭТО РЕЖИМ? признак ВНУТРИ каждого режима ──")
        for rg in ("медведь", "слабый−", "слабый+", "бык"):
            g = R[R._rg == rg]
            a, b = stat(g[fn(g)]), stat(g[~fn(g)])
            if a is None or b is None:
                print(f"    {rg:<10} мало данных"); continue
            d = a["pf"] - b["pf"]
            print(f"    {rg:<10} PF признак {a['pf']:5.2f} (n={a['n']:<5}) против "
                  f"контроль {b['pf']:5.2f} (n={b['n']:<5})  Δ {d:+.2f}"
                  f"{'  ← добавляет' if d > 0.15 else '  ← НЕ добавляет' if d < 0.05 else ''}")
        # доля признака по режимам: если признак = прокси быка, доля в быке будет резко выше
        sh = R.groupby("_rg", observed=True).apply(lambda g: fn(g).mean() * 100)
        print(f"    доля признака по режимам: " +
              " · ".join(f"{k} {v:.0f}%" for k, v in sh.items()))

        print("\n  ── 2. ЭТО ЭПОХА? разрез по годам ──")
        for y in sorted(R.year.unique()):
            g = R[R.year == y]
            a, b = stat(g[fn(g)]), stat(g[~fn(g)])
            if a is None or b is None:
                print(f"    {y}  мало данных"); continue
            print(f"    {y}  PF признак {a['pf']:5.2f} (n={a['n']:<5}) против "
                  f"контроль {b['pf']:5.2f} (n={b['n']:<5})  Δ {a['pf']-b['pf']:+.2f}")

        print("\n  ── 3. СТОРОНА (обе обязательны) ──")
        for side in ("long", "short"):
            g = R[R.side == side]
            a, b = stat(g[fn(g)]), stat(g[~fn(g)])
            if a is None or b is None:
                print(f"    {side:<6} мало"); continue
            print(f"    {side:<6} PF признак {a['pf']:5.2f} (n={a['n']:<5}) против "
                  f"контроль {b['pf']:5.2f} (n={b['n']:<5})  Δ {a['pf']-b['pf']:+.2f}"
                  f"  безтоп10% {a['bt']:+.0f}")

    # ── 4. СТОПКА: три кластера вместе, и они же ПОВЕРХ боевого дрейф-гейта ──
    print("\n" + "=" * 104)
    print("4. ТРИ КЛАСТЕРА ВМЕСТЕ · и ПОВЕРХ боевого дрейф-гейта")
    print("=" * 104)
    allm = np.logical_and.reduce([fn(R).values for fn in CLUSTERS.values()])
    print(line(R[allm], "  все три сразу"))
    gate = R.mkt_drift_slope > 0            # боевой гейт 15m
    print(line(R[gate], "  боевой дрейф-гейт"))
    print(line(R[gate & allm], "  гейт + все три"))
    for name, fn in CLUSTERS.items():
        m = gate & fn(R).values
        s = stat(R[m])
        if s:
            print(line(R[m], f"  гейт + {name[:22]}"))

    # ── 5. ТОЛЬКО ДЛЯ ВОЛН: не тавтология ли «дисконт» со стороной сделки ────
    if FAMILY == "waves" and "leg_dir_15m" in R.columns:
        print("\n" + "=" * 104)
        print("5. 🔴 ГЛАВНОЕ ПОДОЗРЕНИЕ ВОЛН: «дисконт» = сторона относительно НОГИ?")
        print("=" * 104)
        print("   Если сделка short при бычьей ноге, то «глубокий откат» означает")
        print("   «входим ПО откату». Тогда признак кодирует не зону, а согласие")
        print("   стороны с направлением отката — и это надо назвать своим именем.")
        disc = R.leg_in_disc_15m == 1.0
        for ld, lname in ((1.0, "нога БЫЧЬЯ"), (-1.0, "нога МЕДВЕЖЬЯ")):
            for side in ("long", "short"):
                m = (R.leg_dir_15m == ld) & (R.side == side)
                a_, b_ = stat(R[m & disc]), stat(R[m & ~disc])
                tag = "ПО откату" if ((ld > 0) == (side == "short")) else "против отката"
                if a_ is None or b_ is None:
                    print(f"   {lname} · {side:<6} ({tag:<14}) мало данных")
                    continue
                print(f"   {lname} · {side:<6} ({tag:<14}) "
                      f"дисконт PF {a_['pf']:5.2f} (n={a_['n']:<4}) против "
                      f"{b_['pf']:5.2f} (n={b_['n']:<4})  Δ {a_['pf']-b_['pf']:+.2f}")
        print("\n   ── и корреляция «медленная» ↔ «длинная» (развести два кластера) ──")
        for c1, c2 in (("leg_speed_atr_15m", "leg_span_bars_15m"),
                       ("leg_span_bars_15m", "leg_age_origin_15m"),
                       ("leg_minor_breaks_15m", "leg_span_bars_15m")):
            print(f"     {c1} ↔ {c2}: r = {R[c1].corr(R[c2]):+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
