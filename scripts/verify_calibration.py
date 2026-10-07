# -*- coding: utf-8 -*-
"""КАЛИБРОВКА ПРОВЕРЯЛЬЩИКА — карточка вердикта на случаях с ИЗВЕСТНЫМ ответом (Егор 07.10:
«точно ли все эти проверки актуальны?»).

Идея: проверку, которая не ловит ни одного известного артефакта, понижаем или убираем; проверку,
которая убивает известного выжившего, разбираем — либо она ошибается, либо выживший был завышен.

Случаи (данные строк есть на диске):
  ВЫЖИВШИЕ
    S1  клетка лонга ядра волн (полное ядро ∧ стоп ≥6%) против всех лонгов ядра
    S2  лонг откатов после A при шортящей рознице (нижняя треть long/short Binance) — P 0.0025 по СДЕЛКАМ
  АРТЕФАКТЫ (разобраны 07.10 вручную)
    A1  клетка лонга × дневная перепроданность WT — скученность дней капитуляции
    A2  все лонги ядра × ATR-тренд 1h по ходу — повтор размера стопа
    A3  клетка шорта ядра (полное ядро ∧ стоп ≥6%) — PF 0.64, денег нет
  ОЖИДАНИЕ ИЗ ПАМЯТИ
    M1  полное ядро сверх размера стопа у лонгов — «core_full не нужен»
  КАНДИДАТ (ответ неизвестен)
    C1  клетка лонга × ATR-тренд 1h ещё вниз
  ЯРУС 2
    T2  поиск по 12 WT-срезам среди всех лонгов ядра и внутри клетки

Все доходы приведены к косту 0.35 (линейка проекта). 🔴 В wave_a_retrace доход за вычетом 0.10
(`triangle_lab.COST`) — вычитаем ещё 0.25.

Запуск: python scripts/verify_calibration.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

import research_verify as V                               # noqa: E402

WAVES = Path("G:/oko_lab/out/wt_context_waves/rows.pkl")
CACHE = Path("G:/oko_lab/out/verify_calib")
REG = {2022: "МЕДВЕДЬ", 2023: "БЫК", 2024: "нейтраль", 2025: "МЕДВЕДЬ", 2026: "МЕДВЕДЬ"}
STUDY = "calibration-2026-10-07"


def waves() -> pd.DataFrame:
    R = pd.DataFrame(pickle.load(open(WAVES, "rb")))
    return V.normalize(R, pnl="pnl_0", ts="entry_time", liq="turnover")


def positioning() -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "positioning_long_2R_raw.pkl"
    if f.exists():
        D = pd.read_pickle(f)
    else:
        from positioning_filter_lab import load_setups, attach_metrics
        R = load_setups()
        D = attach_metrics(R, coins=R.sym.nunique())
        D = D[(D.target == "2R") & (D.side == "LONG")].copy()
        D.to_pickle(f)
    D = D.copy()
    D["pnl"] = D["pnl"] - 0.25                            # 0.10 → линейка 0.35
    D["ctl"] = D["ctl"] - 0.25
    return V.normalize(D, pnl="pnl", ts="entry_t", ctrl="ctl")


def main() -> int:
    W = waves()
    L = W[W.side == "LONG"].reset_index(drop=True)
    Sh = W[W.side == "SHORT"].reset_index(drop=True)
    cell = (L.core_full & (L.stop_pct >= 6.0)).values
    C = L[cell].reset_index(drop=True)

    cases = []                                            # (код, ожидание, карточка, найден поиском в)

    def run(code, expect, D, mask, name, search=None, **kw):
        print()
        c = V.card(D, mask, name=f"{code} {name}", study=STUDY, regimes=REG, **kw)
        cases.append((code, expect, c, search))

    run("S1", "ПРОШЛО", L, cell, "клетка лонга ядра против всех лонгов")
    run("M1", "НЕ ПРОШЛО", L, L.core_full.values, "полное ядро сверх стопа (лонги)", geo=("stop_pct",))
    # A1 и C1 найдены перебором WT-срезов внутри клетки → итог решает ярус 2 этого перебора
    run("A1", "НЕ ПРОШЛО", C, (C["1d_zone"] < 0).values, "клетка × 1d WT < −60", search="клетка лонга")
    run("A2", "НЕ ПРОШЛО", L, (L["1h_atr"] > 0).values, "лонги × 1h ATR-тренд по ходу", geo=("stop_pct",))
    run("A3", "НЕ ПРОШЛО", Sh, (Sh.core_full & (Sh.stop_pct >= 6.0)).values, "клетка шорта ядра")
    run("C1", "?", C, (C["1h_atr"] < 0).values, "клетка × 1h ATR-тренд ещё вниз", search="клетка лонга")

    P = positioning()
    q = P.count_long_short_ratio.quantile(1 / 3)
    run("S2", "ПРОШЛО", P, (P.count_long_short_ratio < q).values,
        f"откаты A, лонг 2R × розница шортит (<{q:.2f})")

    # ── ярус 2: поиск по 12 WT-срезам ──
    print()
    t2 = []
    for nm, D in (("все лонги ядра", L), ("клетка лонга", C)):
        masks = []
        for tf in ("15m", "1h", "4h", "1d"):
            masks += [(f"{tf} зона ЗА", (D[f"{tf}_zone"] < 0).values),
                      (f"{tf} зона ПРОТИВ", (D[f"{tf}_zone"] > 0).values),
                      (f"{tf} тренд по ходу", (D[f"{tf}_atr"] > 0).values),
                      (f"{tf} тренд против", (D[f"{tf}_atr"] < 0).values)]
        masks = [(k, m) for k, m in masks if m.sum() >= 10 and (~m).sum() >= 10]

        def search(p, masks=masks):
            best = max(((k, p[m].mean() - p[~m].mean()) for k, m in masks), key=lambda x: x[1])
            return best

        t2.append(V.search_null(D, search, name=f"T2 WT-срезы · {nm} ({len(masks)} гипотез)", study=STUDY))
    t2_by = {"все лонги ядра": t2[0], "клетка лонга": t2[1]}

    # ── сводка ──
    print("\n" + "=" * 100)
    print("СВОДКА КАЛИБРОВКИ")
    print("=" * 100)
    gates = []
    for _, _, c, _ in cases:
        for g in c.get("gates", {}):
            if g not in gates:
                gates.append(g)
    for code, expect, c, src in cases:
        ok = c["passed"] and (src is None or t2_by[src]["passed"])
        got = "ПРОШЛО" if ok else "НЕ ПРОШЛО"
        why = list(c.get("failed", []))
        if src and not t2_by[src]["passed"]:
            why.append(f"ярус 2: найден перебором, P {t2_by[src]['p']:.3f}")
        mark = "✅" if expect in ("?", got) else "⚠️ РАСХОЖДЕНИЕ"
        print(f"  {code}  ожидали {expect:<10} получили {got:<10} {mark}  · не прошло: {', '.join(why) or '—'}")
    print("\nЧТО ЛОВИТ КАЖДАЯ ПРОВЕРКА (❌ = не пропустила):")
    print(f"  {'проверка':<44}" + "".join(f"{code:>5}" for code, _, _, _ in cases))
    for g in gates + ["ярус 2 (если найден перебором)"]:
        row = ""
        for _, _, c, src in cases:
            v = (t2_by[src]["passed"] if src else None) if g.startswith("ярус 2") else c.get("gates", {}).get(g)
            row += f"{'—' if v is None else ('✅' if v else '❌'):>5}"
        print(f"  {g:<44}{row}")

    V.save_md([c for _, _, c, _ in cases] + [dict(text=t["text"]) for t in t2],
              ROOT / "obsidian/Research/2026-10-07-Verify-Calibration.md",
              "Калибровка карточки вердикта",
              "Карточка вердикта на известных случаях: выжившие, артефакты, кандидат; ярус 2 на WT-срезах")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
