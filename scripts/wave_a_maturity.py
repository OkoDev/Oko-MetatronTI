# -*- coding: utf-8 -*-
"""ВХОД В ЗОНУ ОТКАТА A — РАЗРЕЗ ПО ЗРЕЛОСТИ ИМПУЛЬСА (Егор 06.10).

Вердикт 22.09 «вход ≈ ноль» был вынесен ПО ОБЩЕЙ СТРОКЕ: 3893 сетапа нарезаны по
стороне, годам, режиму, `core_full`, продлённой пятой и размеру стопа — но НЕ по
зрелости импульса. Егор: «когда импульс УЖЕ выдохся, индикатор показывает зону для
входа в обратную импульсу сторону». В Pine это условие `ctxCnt >= minLegs and
strDir развернулся`, и по умолчанию оно ВЫКЛЮЧЕНО (`useWave = false`).

Здесь донарезаем СОХРАНЁННЫЕ данные того же замера (`G:/oko_lab/out/wave_a_retrace/`,
223 монеты) по трём доступным признакам зрелости:
    h_from_5  — часов от пятой волны до входа (свежесть: «только что выдохся» или неделю назад)
    imp_pct   — какую долю импульса прошла цена
    ext_pct   — продление пятой

Мерим по законам: % net, медиана, хрупкость (сумма без верхних 10%), охват монет,
и ПРОТИВ КОНТРОЛЯ той же геометрии (`ctl` — он в данных уже есть).
"""
from __future__ import annotations

import glob
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass


def stat(v: pd.DataFrame, col: str = "pnl"):
    p = v[col].dropna().values
    if len(p) < 30:
        return None
    pos, neg = p[p > 0].sum(), -p[p < 0].sum()
    ctl = v["ctl"].dropna().values
    return dict(n=len(p), wr=(p > 0).mean() * 100,
                pf=pos / neg if neg > 0 else 9.99,
                mean=p.mean(), med=float(np.median(p)), total=p.sum(),
                frail=float(np.sort(p)[:max(1, int(len(p) * 0.9))].sum()),
                cov=(v.groupby("sym")[col].sum() > 0).mean() * 100,
                ctl=ctl.mean() if len(ctl) else np.nan)


def line(nm, s, flow=None):
    if s is None:
        print(f"  {nm:<26} — мало")
        return
    d = s["mean"] - s["ctl"] if s["ctl"] == s["ctl"] else np.nan
    f = f"{flow:>6.0f}%" if flow is not None else "      "
    print(f"  {nm:<26}{f}{s['n']:>6}{s['wr']:>7.1f}%{s['pf']:>7.2f}"
          f"{s['mean']:>+8.3f}{s['med']:>+8.3f}{s['total']:>+9.0f}"
          f"{s['frail']:>+10.0f}{s['cov']:>7.0f}%{s['ctl']:>+8.3f}{d:>+8.3f}")


HEAD = (f"  {'клетка':<26}{'поток':>6}{'n':>6}{'WR':>8}{'PF':>7}{'средн':>8}"
        f"{'медиана':>8}{'сумма':>9}{'безтоп10%':>10}{'монет+':>7}"
        f"{'контр':>8}{'Δ':>8}")


def main() -> int:
    rows = []
    for f in glob.glob("G:/oko_lab/out/wave_a_retrace/*.pkl"):
        try:
            rows += pd.read_pickle(f)
        except Exception:                            # noqa: BLE001
            continue
    R = pd.DataFrame(rows)
    print(f"сетапов: {len(R)} · монет: {R.sym.nunique()} · цели: {sorted(R.target.unique())}")
    print(f"уровни входа: {sorted(R.lvl.unique())} · стороны: {R.side.value_counts().to_dict()}")
    print(f"\nh_from_5 (часов от пятой волны до входа): "
          f"медиана {R.h_from_5.median():.1f} · "
          f"квартили {R.h_from_5.quantile([.25, .5, .75]).round(1).tolist()} · "
          f"макс {R.h_from_5.max():.0f}")
    print(f"imp_pct: медиана {R.imp_pct.median():.1f} · "
          f"ext_pct>0 у {(R.ext_pct > 0).mean()*100:.0f}% строк")

    # цель 2R — та, по которой выносился вердикт
    for tgt in ("2R", "A"):
        T = R[R.target == tgt]
        if len(T) < 100:
            continue
        for side in ("SHORT", "LONG"):
            S = T[T.side == side]
            b = stat(S)
            if b is None:
                continue
            print(f"\n{'=' * 118}")
            print(f"ЦЕЛЬ {tgt} · {side} · ПОЛНАЯ БАЗА (это и есть строка вердикта 22.09)")
            print(f"{'=' * 118}")
            print(HEAD)
            line("вся база", b)

            print(f"  {'— СВЕЖЕСТЬ: часов от пятой волны —':<26}")
            for lo, hi, nm in ((0, 6, "≤ 6 ч (только выдохся)"),
                               (6, 24, "6–24 ч"), (24, 72, "1–3 суток"),
                               (72, 168, "3–7 суток"), (168, 1e9, "> 7 суток")):
                g = S[(S.h_from_5 >= lo) & (S.h_from_5 < hi)]
                line(nm, stat(g), len(g) / len(S) * 100)

            print(f"  {'— ДОЛЯ ПРОЙДЕННОГО ИМПУЛЬСА —':<26}")
            for lo, hi, nm in ((0, 25, "imp < 25%"), (25, 50, "imp 25–50%"),
                               (50, 75, "imp 50–75%"), (75, 1e9, "imp ≥ 75%")):
                g = S[(S.imp_pct >= lo) & (S.imp_pct < hi)]
                line(nm, stat(g), len(g) / len(S) * 100)

            print(f"  {'— ПРОДЛЕНИЕ ПЯТОЙ —':<26}")
            for nm, m in (("без продления", S.ext_pct <= 0),
                          ("с продлением", S.ext_pct > 0)):
                g = S[m]
                line(nm, stat(g), len(g) / len(S) * 100)

            # пересечение: свежесть × размер стопа (закон размера)
            print(f"  {'— СВЕЖО (≤24 ч) × ШИРИНА СТОПА —':<26}")
            fresh = S[S.h_from_5 < 24]
            for lo, hi, nm in ((0, 1.5, "свежо · стоп < 1.5%"),
                               (1.5, 3.0, "свежо · стоп 1.5–3%"),
                               (3.0, 1e9, "свежо · стоп ≥ 3%")):
                g = fresh[(fresh.risk_pct >= lo) & (fresh.risk_pct < hi)]
                line(nm, stat(g), len(g) / len(S) * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
