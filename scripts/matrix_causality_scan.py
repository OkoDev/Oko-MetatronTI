# -*- coding: utf-8 -*-
"""ЯРУС 0: ПРИЦЕЛЬНЫЙ ТЕСТ ПРИЧИННОСТИ МАТРИЦЫ — на тех барах, где флаг СТОИТ (07.10.2026).

Повод. Поиск «триггер × наборы» на журнале общего состояния нашёл `ll_1h` / `hh_1h` / `ll_4h`:
+5…+8% за сутки, ярус 2 P 0.005, карточка ✅, OOS 2025 ✅. Это заглядывание вперёд:
`swing_bridge.etl_swing_structure` ставит HH/HL/LH/LL на бар САМОГО экстремума, а экстремум окна 50
подтверждается через 50 баров. Префиксный тест журнала (6 случайных часов) его пропустил — редкий флаг
в случайные часы просто не попал. 🔴 СТАТИСТИКА ЗАГЛЯДЫВАНИЕ ВПЕРЁД НЕ ЛОВИТ: будущее в данных
выглядит как настоящий сигнал и держится в OOS. Ловит только причинность — и только прицельно.

Метод. Для каждой монеты: полная матрица `mtf_flags(1h)` → набор баров, покрывающий КАЖДЫЙ булев
признак минимум K раз там, где он =1 (жадное покрытие) → на каждом таком баре матрица заново по
истории, обрезанной на этом баре (окно 8000 баров — хватает на 300 дневок для старшего блока) →
сравнение значений в последней строке. Флаг, который в полной истории =1, а в обрезанной =0 на
заметной доле своих баров, — НЕ ПРИЧИННЫЙ. Числовые сравниваются на тех же барах.

Запуск: python scripts/matrix_causality_scan.py [монет] [K] [процессов]
"""
from __future__ import annotations

import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

WINDOW = 8000
SYMS = ("ADA/USDT", "LINK/USDT", "DOGE/USDT", "AVAX/USDT", "XRP/USDT", "LTC/USDT")


def _one(args):
    sym, t = args[:2]
    full_prefix = len(args) > 2 and args[2]
    from research_harness import load, mtf_flags
    import logging
    logging.disable(logging.CRITICAL)
    df = load(sym, "1h")
    part = mtf_flags(df.iloc[(0 if full_prefix else max(0, t - WINDOW)):t + 1], "1h")
    return sym, t, part.iloc[-1]


def main() -> int:
    n_coins = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    K = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    procs = int(sys.argv[3]) if len(sys.argv) > 3 else max(1, (os.cpu_count() or 2) - 6)
    from research_harness import load, mtf_flags
    rng = np.random.default_rng(11)
    jobs, fulls = [], {}
    for sym in SYMS[:n_coins]:
        df = load(sym, "1h")
        F = mtf_flags(df, "1h")
        fulls[sym] = F
        lo = WINDOW + 10                                  # обрезка не должна упираться в начало ряда
        B = F.iloc[lo:]
        binc = [c for c in B.columns if set(np.unique(B[c].dropna().values)) <= {0.0, 1.0}
                and (B[c] == 1).any()]
        cover = {c: 0 for c in binc}
        rows = set()
        for c in sorted(binc, key=lambda c: (B[c] == 1).sum()):          # редкие — первыми
            pos = np.flatnonzero((B[c] == 1).values)
            for i in rng.permutation(pos)[:max(0, K - cover[c])]:
                t = int(i) + lo
                if t in rows:
                    continue
                rows.add(t)
                hit = F.iloc[t]
                for cc in binc:
                    if hit[cc] == 1:
                        cover[cc] += 1
        jobs += [(sym, t) for t in sorted(rows)]
        print(f"{sym}: булевых {len(binc)} · баров на проверку {len(rows)}", flush=True)

    t0 = time.time()
    res = []
    with Pool(procs) as pool:
        for i, r in enumerate(pool.imap_unordered(_one, jobs), 1):
            res.append(r)
            if i % 50 == 0:
                print(f"  ... {i}/{len(jobs)} · {time.time() - t0:.0f} с", flush=True)

    pos_n, pos_bad, num_n, num_bad = {}, {}, {}, {}
    for sym, t, row in res:
        full = fulls[sym].iloc[t]
        for c in full.index:
            if c not in row.index:
                continue
            a, b = float(full[c]), float(row[c])
            if a in (0.0, 1.0) and b in (0.0, 1.0, ) or (np.isnan(b) and a in (0.0, 1.0)):
                if a == 1.0:
                    pos_n[c] = pos_n.get(c, 0) + 1
                    if not (b == 1.0):
                        pos_bad[c] = pos_bad.get(c, 0) + 1
            elif np.isfinite(a) or np.isfinite(b):
                num_n[c] = num_n.get(c, 0) + 1
                if not np.isclose(a, b, rtol=1e-3, atol=1e-6, equal_nan=True):
                    num_bad[c] = num_bad.get(c, 0) + 1

    # ── перепроверка частичных расхождений на ПОЛНОЙ истории до бара (без окна 8000) ──
    # отделяет заглядывание вперёд от недосчитанной истории (EMA200 дневок, старые пулы ликвидности)
    # ВСЕ расходящиеся, включая 100%: `bear_breaker_1d` при 40% оказался обрезкой — 100% тоже может ею быть
    partial = set(pos_bad) | set(num_bad)
    redo = []
    for sym, t, row in res:
        full = fulls[sym].iloc[t]
        for c in partial:
            if c in row.index and not np.isclose(float(full[c]), float(row[c]), rtol=1e-3, atol=1e-6,
                                                 equal_nan=True):
                redo.append((sym, t, True))
                break
    print(f"\nперепроверка на полной истории: баров {len(redo)} (столбцов с частичным расхождением {len(partial)})",
          flush=True)
    confirmed = {}
    with Pool(procs) as pool:
        for sym, t, row in pool.imap_unordered(_one, redo):
            full = fulls[sym].iloc[t]
            for c in partial:
                if c in row.index and not np.isclose(float(full[c]), float(row[c]), rtol=1e-3, atol=1e-6,
                                                     equal_nan=True):
                    confirmed[c] = confirmed.get(c, 0) + 1
    print("  подтвердились на полной истории (= заглядывание, а не обрезка):")
    for c in sorted(confirmed, key=lambda c: -confirmed[c]):
        print(f"    🔴 {c:<52} {confirmed[c]}")
    gone = sorted(partial - set(confirmed))
    print(f"  ушли на полной истории (= обрезка окна): {len(gone)}" + (f" → {gone[:20]}" if gone else ""))

    print("\n" + "=" * 100)
    print(f"ФЛАГИ: «в полной истории =1, в обрезанной ≠1» · проверено баров {len(res)}")
    print("=" * 100)
    bad = sorted(((c, pos_bad[c], pos_n[c]) for c in pos_bad), key=lambda x: -x[1] / x[2])
    for c, k, n in bad:
        print(f"  🔴 {c:<52} {k:>3} из {n:<3} ({k / n * 100:3.0f}%)")
    print(f"  флагов проверено на позитивах: {len(pos_n)} · расходятся: {len(bad)}")
    print("\nЧИСЛОВЫЕ: расхождение значения на тех же барах")
    nb = sorted(((c, num_bad[c], num_n[c]) for c in num_bad), key=lambda x: -x[1] / x[2])
    for c, k, n in nb[:40]:
        print(f"  ⚠️ {c:<52} {k:>3} из {n:<3} ({k / n * 100:3.0f}%)")
    print(f"  числовых проверено: {len(num_n)} · расходятся: {len(nb)}")
    out = Path("G:/oko_lab/out/matrix_causality_scan.csv")
    D = pd.DataFrame([(c, "flag", k, n) for c, k, n in bad] + [(c, "num", k, n) for c, k, n in nb],
                     columns=["col", "kind", "bad", "n"])
    # вердикт по столбцу: 100% расхождений — непричинный; частичное — только если подтвердилось без обрезки
    D["confirmed"] = D.col.map(confirmed).fillna(0).astype(int)
    D["verdict"] = np.where(D.confirmed > 0, "НЕПРИЧИННЫЙ", "обрезка окна")
    D.to_csv(out, index=False)
    print(f"\nсписок → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
