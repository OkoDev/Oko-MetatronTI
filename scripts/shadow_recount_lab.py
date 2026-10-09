# -*- coding: utf-8 -*-
"""ПЕРЕСЧЁТ ТЕНЕЙ ПОСЛЕ ПОЧИНКИ РЕЗОЛВЕРА (09.10.2026, Егор «1-3», п.1).

`shadow_resolve.py` до 09.10 засчитывал TP, даже если стоп сработал раньше цели. Здесь:
  1. переходы старый исход → новый (бэкап oko_feed/shadow_backup_20261009.db против рабочей базы);
  2. калибровка: окно вердикта 11.08 (method_shadow 05.07–09.08) по СТАРЫМ исходам должно дать записанное
     (LONG PF 0.83 · SHORT PF 1.47, n=135) — тогда понятно, каким кодом считался тот вердикт;
  3. то же окно и вся выборка по НОВЫМ исходам;
  4. карточки (scripts/research_verify.card): «шорт лучше лонга» в обеих тенях и «толпа против лучше
     толпы за» в method_shadow — оба прежних утверждения.
Слой: L1+L3 (сигнал + геометрия), исполнения нет. Кост 0.35 вычитается из валового pct_1r.
Запуск: python scripts/shadow_recount_lab.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from research_verify import card, normalize, save_md  # noqa: E402

COST = 0.35
LIVE = ROOT / "oko_feed" / "external_data.db"
BAK = ROOT / "oko_feed" / "shadow_backup_20261009.db"
KEY = ["ts", "symbol", "direction"]


def ro(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)


def load(t: str) -> pd.DataFrame:
    a = pd.read_sql(f"SELECT * FROM {t}", ro(LIVE))
    b = pd.read_sql(f"SELECT {', '.join(KEY)}, outcome AS old_outcome, pct_1r AS old_pct FROM {t}", ro(BAK))
    assert not a.duplicated(KEY).any() and not b.duplicated(KEY).any(), "ключ (ts, symbol, direction) не уникален"
    m = a.merge(b, on=KEY, how="left")
    assert len(m) == len(a), "merge изменил число строк"
    return m


def stat(p: pd.Series) -> str:
    p = p.dropna()
    if not len(p):
        return "n=0"
    s = p.sort_values()
    gl = -s[s < 0].sum()
    top = s.iloc[int(len(s) * 0.9):].sum()
    return (f"n={len(p):>3} · доля>0 {(p > 0).mean()*100:3.0f}% · медиана {p.median():+.2f}% · среднее {p.mean():+.2f}% · "
            f"PF {s[s > 0].sum() / gl if gl else float('nan'):.2f} · сумма {p.sum():+.1f}% · без верхних 10% {p.sum() - top:+.1f}%")


def main():
    cards = []
    for t in ("method_shadow", "ote_cell_shadow"):
        D = load(t)
        D["sym"] = D.symbol.str.replace("/USDT:USDT", "", regex=False).str.replace("USDT", "", regex=False)
        D["t"] = pd.to_datetime(D.ts, unit="s", utc=True)
        D["net_new"] = D.pct_1r - COST
        D["net_old"] = D.old_pct - COST
        D["src"] = D.src.fillna("binance")
        if "stop_pct" not in D or D.stop_pct.isna().all():
            D["stop_pct"] = (D.entry - D.sl).abs() / D.entry * 100
        print("═" * 110)
        print(f"{t}: строк {len(D)} · разрешено {int(D.resolved.sum())} · {D.t.min():%Y-%m-%d} → {D.t.max():%Y-%m-%d} · "
              f"биржа {D.src.value_counts().to_dict()}")
        print("переходы исходов (строки — старый, столбцы — новый):")
        print(pd.crosstab(D.old_outcome.fillna("—"), D.outcome.fillna("в игре"), margins=True).to_string())
        flip = D[(D.old_outcome == "TP") & (D.outcome == "SL")]
        print(f"TP → SL: {len(flip)} ({len(flip) / max((D.old_outcome == 'TP').sum(), 1) * 100:.0f}% старых TP). Примеры:")
        for _, r in flip.head(4).iterrows():
            print(f"   {r.t:%d.%m %H:%M} {r.sym:10} {r.direction:5} вход {r.entry:.6g} стоп {r.sl:.6g} → было {r.old_pct:+.2f}% стало {r.pct_1r:+.2f}%")

        if t == "method_shadow":
            w = D[(D.t >= "2026-07-05") & (D.t < "2026-08-10")]
            print("\nКАЛИБРОВКА: окно вердикта 11.08 (05.07–09.08), записано: LONG PF 0.83 · SHORT PF 1.47 · n=135")
            for side in ("LONG", "SHORT"):
                print(f"  {side:5} старые исходы: {stat(w[w.direction == side].net_old)}")
            for side in ("LONG", "SHORT"):
                print(f"  {side:5} НОВЫЕ исходы:  {stat(w[w.direction == side].net_new)}")

        R = D[D.resolved == 1].copy()
        print("\nВСЯ ВЫБОРКА, новые исходы, net = % − 0.35:")
        for side in ("LONG", "SHORT"):
            print(f"  {side:5} {stat(R[R.direction == side].net_new)}")
        print("по месяцам (медиана net · n):")
        R["mon"] = R.t.dt.strftime("%Y-%m")
        print(R.pivot_table(index="mon", columns="direction", values="net_new", aggfunc=["median", "size"]).round(2).to_string())
        print("по бирже исхода (src):")
        for (s, side), X in R.groupby(["src", "direction"]):
            print(f"  {s:8} {side:5} {stat(X.net_new)}")
        R["stop_bin"] = pd.qcut(R.stop_pct, 3, labels=["узкий", "средний", "широкий"])
        print("по размеру стопа (терцили):")
        for (b, side), X in R.groupby(["stop_bin", "direction"], observed=True):
            print(f"  {b:8} {side:5} {stat(X.net_new)}")

        N = normalize(R.assign(pnl=R.net_new, ts=R.t.dt.tz_localize(None), side=R.direction), pnl="pnl")
        cards.append(card(N, N.side.values == "SHORT", name=f"{t}: SHORT лучше LONG",
                          study="shadow_recount_09_10", geo=("stop_pct",) if "stop_pct" in N else ()))
        if t == "method_shadow" and "fuel" in R:
            print("\nтолпа (fuel):", R.fuel.value_counts().to_dict())
            for f, X in R.groupby("fuel"):
                print(f"  {f:10} {stat(X.net_new)}")
            cards.append(card(N, N.fuel.str.contains("against", case=False, na=False).values,   # маска из N: normalize роняет строки
                              name="method_shadow: толпа против лучше толпы за", study="shadow_recount_09_10"))

    out = ROOT / "obsidian" / "Research" / "2026-10-09-Shadow-Recount-Cards.md"
    save_md(cards, out, "Тени после починки резолвера — карточки",
            "Пересчёт method_shadow и ote_cell_shadow после исправления порядка «стоп/цель» (09.10.2026)")
    print(f"\nкарточки → {out}")


if __name__ == "__main__":
    main()
