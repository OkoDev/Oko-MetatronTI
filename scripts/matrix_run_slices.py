"""
matrix_run_slices.py — срезы, которых НЕТ в обязательном отчёте харнесса.

`report()` печатает сторону · год · размер стопа · хрупкость · охват. Протокол
вердикта требует ещё три оси, и харнесс сам честно пишет «НЕ проверено»:
    · РЕЖИМ ГОДА (бык/медведь/нейтраль) — иначе «лонг мёртв» на медвежьем окне тавтология
    · КЛАСТЕР (одиночка против массовости) — одиночка 0.67-1.02 против кластера 1.83-2.24
    · ЛИКВИДНОСТЬ — ликвидная половина ведёт себя иначе

Режим года берётся ПРИЧИННО из `cache/market_context.parquet` (дрейф вселенной,
посчитанный из кэша 4h), а не по календарю: календарная метка «2023 = бык» в бою
недоступна.

    python scripts/matrix_run_slices.py --tf 15m
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

from research_harness import stat, line     # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="15m")
    a = ap.parse_args()
    p = ROOT / "cache" / f"matrix_run_{a.tf}.parquet"
    if not p.exists():
        print(f"🔴 нет {p} — сначала прогон `matrix_global_run.py --tf {a.tf}`")
        return 1
    R = pd.read_parquet(p)
    print(f"выборка: {len(R)} сделок · {R.sym.nunique()} монет · ТФ {a.tf}")

    print("\n" + "=" * 104)
    print("РЕЖИМ ГОДА — ПРИЧИННО (дрейф вселенной за 30д на баре входа), а не по календарю")
    print("=" * 104)
    if "mkt_drift30" not in R.columns:
        print("🔴 колонки mkt_drift30 нет — расширение матрицы не подключалось")
    else:
        for lo, hi, nm in ((-1e9, -15, "медведь (дрейф < −15%)"),
                           (-15, 0, "слабый минус (−15…0%)"),
                           (0, 15, "слабый плюс (0…+15%)"),
                           (15, 1e9, "бык (дрейф > +15%)")):
            v = R[(R.mkt_drift30 >= lo) & (R.mkt_drift30 < hi)]
            print(line(v, f"  {nm}"))
        print("\n  то же, но по СТОРОНЕ (полярность переворачивала вывод трижды):")
        for side in sorted(R.side.unique()):
            for lo, hi, nm in ((-1e9, 0, "минус"), (0, 1e9, "плюс")):
                v = R[(R.side == side) & (R.mkt_drift30 >= lo) & (R.mkt_drift30 < hi)]
                print(line(v, f"    {side} · дрейф {nm}"))

    print("\n" + "=" * 104)
    print("КЛАСТЕР — сколько НАШИХ сетапов в тот же день по вселенной")
    print("=" * 104)
    R = R.copy()
    if "entry_ts" in R.columns:
        R["day"] = pd.to_datetime(R.entry_ts).dt.floor("D")
    else:
        # входного времени механика не отдала — приближаем годом+символом нельзя,
        # честно говорим об этом, а не подменяем суррогатом
        R["day"] = np.nan
    if R.day.isna().all():
        print("  🔴 НЕ ПРОВЕРЕНО: механика не вернула время входа (`entry_ts`).")
        print("     Кластер по дню посчитать нечем — суррогат подставлять не буду.")
    else:
        cnt = R.groupby("day").size().rename("n_day")
        R = R.join(cnt, on="day")
        for lo, hi, nm in ((0, 2, "одиночка (1 сетап в день)"),
                           (2, 4, "малый кластер (2-3)"),
                           (4, 1e9, "кластер (4+)")):
            print(line(R[(R.n_day >= lo) & (R.n_day < hi)], f"  {nm}"))

    print("\n" + "=" * 104)
    print("ЛИКВИДНОСТЬ — прокси: медианный оборот монеты в выборке")
    print("=" * 104)
    if "amp_pct" not in R.columns:
        print("  🔴 нет колонки для прокси ликвидности")
    else:
        # прокси: медианная амплитуда импульса по монете. Неликвид ходит шире.
        med = R.groupby("sym").amp_pct.median()
        thr = med.median()
        liq = set(med[med <= thr].index)
        print(f"  порог по медианной амплитуде импульса: {thr:.2f}% "
              f"(ликвидных монет {len(liq)}, хвост {R.sym.nunique()-len(liq)})")
        print(line(R[R.sym.isin(liq)], "  ликвидная половина"))
        print(line(R[~R.sym.isin(liq)], "  хвост"))
        print("  🔴 это ПРОКСИ, а не оборот в долларах — настоящий объём в выборке не собран")

    print("\n" + "=" * 104)
    print("ХРУПКОСТЬ ПО ГОДАМ (безтоп10% — отличает эдж от одного хвоста)")
    print("=" * 104)
    for y in sorted(R.year.unique()):
        print(line(R[R.year == y], f"  {y}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
