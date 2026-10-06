# -*- coding: utf-8 -*-
"""ПЕРЕНОС ФИЛЬТРА ПОЗИЦИОНИРОВАНИЯ НА ДРУГУЮ МЕХАНИКУ (Егор 07.10: «пробуй»).

Найдено на `wave_a_retrace`: лонг при ШОРТЯЩЕЙ рознице (нижние 30% по
`count_long_short_ratio`) даёт PF 1.45 против 1.06 базы, перестановка P=0.0025
([[positioning_retail_contrarian_filter]]).

🔴 Но перенос между механиками у нас НЕ состоялся уже дважды: «стоп 30-50% импульса»
оказался свойством ЯДРА ВОЛН, а не рынка; гейт BOS помог лонгу и навредил шорту.
Поэтому переносим не веря, а МЕРЯЯ.

Вторая механика — волновой разбор (`wave_analyst_bt_tz.parquet`, 13 623 сделки,
30 монет, 2022-2026). Она независима: другой детектор, другой ТФ входа, другая
геометрия стопа и цели.

⚠️ Ограничение против первой базы: здесь НЕТ контроля той же геометрии (`ctl`),
поэтому сравнение идёт против БАЗЫ, а не против случайного входа.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                        # noqa: BLE001
    pass

MET = Path("C:/oko_data/history/metrics")
SRC = "oko_feed/wave_analyst_bt_tz.parquet"
Q_LOW = 0.30          # тот же порог, что в находке: нижние 30% long/short


def attach(D: pd.DataFrame) -> pd.DataFrame:
    """Метрика на последнем баре, закрытом СТРОГО до входа."""
    D = D.copy()
    D["entry_utc"] = pd.to_datetime(D["t"]).dt.tz_localize("UTC")
    D["base"] = D.sym.str.split("/").str[0] + "USDT"
    out, miss = [], []
    for s, g in D.groupby("base"):
        p = MET / f"{s}.parquet"
        if not p.exists():
            miss.append(s)
            continue
        try:
            m = pd.read_parquet(p, columns=["time", "count_long_short_ratio",
                                            "sum_open_interest",
                                            "sum_taker_long_short_vol_ratio"])
        except Exception:                                # noqa: BLE001
            miss.append(s)
            continue
        m = m.sort_values("time")
        m["ts"] = pd.to_datetime(m.time, unit="ms", utc=True)
        g = pd.merge_asof(g.sort_values("entry_utc"),
                          m[["ts", "count_long_short_ratio",
                             "sum_open_interest", "sum_taker_long_short_vol_ratio"]],
                          left_on="entry_utc", right_on="ts", direction="backward",
                          allow_exact_matches=False, tolerance=pd.Timedelta("4h"))
        out.append(g)
    if miss:
        print(f"  без метрик: {len(miss)} монет — {', '.join(miss[:8])}")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def st(v: pd.DataFrame, mn: int = 40):
    p = v["pnl"].dropna().values
    if len(p) < mn:
        return None
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    return dict(n=len(p), wr=(p > 0).mean() * 100,
                pf=pos / neg if neg > 0 else 9.99, mean=p.mean(),
                med=float(np.median(p)), total=p.sum(),
                frail=float(np.sort(p)[:max(1, int(len(p) * 0.9))].sum()),
                cov=(v.groupby("sym")["pnl"].sum() > 0).mean() * 100)


def pr(nm, s, b=None):
    if s is None:
        print(f"  {nm:<34} — мало")
        return
    fl = f"{s['n'] / b['n'] * 100:>6.0f}%" if b else "  база"
    print(f"  {nm:<34}{fl}{s['n']:>6}{s['wr']:>6.1f}%{s['pf']:>7.2f}"
          f"{s['mean']:>+8.3f}{s['med']:>+8.3f}{s['frail']:>+10.0f}{s['cov']:>7.0f}%")


HEAD = (f"  {'клетка':<34}{'поток':>6}{'n':>6}{'WR':>7}{'PF':>7}{'средн':>8}"
        f"{'медиана':>8}{'безтоп10%':>10}{'монет+':>7}")


def main() -> int:
    D = pd.read_parquet(SRC)
    print(f"механика 2: волновой разбор · {len(D)} сделок · {D.sym.nunique()} монет\n")
    D = attach(D)
    if D.empty:
        print("🔴 сопоставление пустое — отказ, а не вывод")
        return 1
    cov = D.count_long_short_ratio.notna().mean() * 100
    print(f"сопоставлено {len(D)} · покрытие long/short = {cov:.1f}%")
    if cov < 50:
        print("🔴 покрытие ниже половины — считать нельзя")
        return 1
    D = D[D.count_long_short_ratio.notna()]

    for side in ("long", "short"):
        S = D[D.side == side]
        b = st(S)
        if b is None:
            continue
        thr = S.count_long_short_ratio.quantile(Q_LOW)
        thr_hi = S.count_long_short_ratio.quantile(1 - Q_LOW)
        print("\n" + "=" * 104)
        print(f"{side.upper()} · перенос фильтра «розница шортит» (порог {thr:.2f})")
        print("=" * 104)
        print(HEAD)
        pr("вся база", b)
        pr("розница в нижних 30% (ШОРТИТ)", st(S[S.count_long_short_ratio < thr]), b)
        pr("розница в верхних 30% (ЛОНГУЕТ)", st(S[S.count_long_short_ratio > thr_hi]), b)

        # то же поверх ОТОБРАННОЙ выборки механики (score>=4 и один сценарий)
        sel = S[(S.score >= 4) & (S.clear == 1)]
        bs = st(sel)
        if bs:
            print(f"  {'— поверх score≥4 и ясно —':<34}")
            pr("  отбор механики", bs)
            pr("  отбор × розница ШОРТИТ",
               st(sel[sel.count_long_short_ratio < thr]), bs)
            pr("  отбор × розница ЛОНГУЕТ",
               st(sel[sel.count_long_short_ratio > thr_hi]), bs)

        # по годам — обязательный срез
        K = S[S.count_long_short_ratio < thr]
        print(f"  {'— клетка по годам (против базы года) —':<34}")
        for y in sorted(S.year.unique()):
            sy, by = st(K[K.year == y], 25), st(S[S.year == y], 25)
            if sy is None or by is None:
                continue
            print(f"    {int(y)}: клетка n={sy['n']:>4} PF {sy['pf']:>5.2f} ср {sy['mean']:>+7.3f}"
                  f"   │ база n={by['n']:>5} PF {by['pf']:>5.2f} ср {by['mean']:>+7.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
