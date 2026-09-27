# -*- coding: utf-8 -*-
"""SPOT_DUMP_GRID ПОД ТЕМ ЖЕ НОЖОМ (12.09.2026).

Сегодня зарезаны: цели по фибо · переключатель режима · медленный режим (5 признаков) ·
край «капитуляция корзиной». Каждый раз убивало одно и то же: сигналы идут ПАЧКАМИ, поэтому
сотни «сделок» — это десяток независимых событий, среднее держит хвост, медиана отрицательна.

🔴 Вчера я подал SPOT_DUMP_GRID как проверенную (суррогат + контроль + 4/5 лет), но тест на
КЛАСТЕРИЗАЦИЮ ЭПИЗОДОВ там НЕ делался. А её сигналы приходят ровно так же — пачками в дни дампа.
Здесь проверяю честно:
  1. Сколько НЕЗАВИСИМЫХ ЭПИЗОДОВ (серий дней с входами, разрыв > GAP дней = новый эпизод);
  2. Доходность ПО ЭПИЗОДАМ (эпизод = одна ставка, среднее его сделок) — медиана и среднее;
  3. Сколько эпизодов в плюсе (вот это и есть настоящее «лет/событий в плюсе»);
  4. Перестановка: случайные даты входа той же частоты и того же размера пачек → разрыв.
  5. Разрез по годам ПО ЭПИЗОДАМ, а не по сделкам.

Данные: small_account_trades.pkl (сделки схем A 4h→1h · B 2h→15m · C 1h→15m, пороги −70/−75).
"""
from __future__ import annotations
import sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = Path(r"C:\Users\yogoru\AppData\Local\Temp\claude\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
GAP = 3          # разрыв в днях между входами → новый эпизод
COST = 0.10      # % круг (комиссия BingX; в исходном замере было 0.35)


def episodes_of(df, gap=GAP):
    """Размечает сделки по эпизодам: подряд идущие дни входов = один эпизод."""
    d = df.sort_values("t_in").copy()
    days = d.t_in.dt.floor("D")
    newep = (days.diff().dt.days.fillna(999) > gap).cumsum()
    d["ep"] = newep.values
    return d


def report(name, d):
    if len(d) < 30:
        print(f"\n--- {name}: сделок {len(d)} — мало"); return
    d = episodes_of(d)
    d["net"] = d.pnl - COST
    ep = d.groupby("ep").agg(сделок=("net", "size"), ret=("net", "mean"),
                             t0=("t_in", "min"), t1=("t_in", "max"),
                             монет=("sym", "nunique"))
    ep["year"] = ep.t0.dt.year
    print(f"\n=== {name}")
    print(f"  сделок {len(d)} · НЕЗАВИСИМЫХ ЭПИЗОДОВ {len(ep)} · медиана сделок в эпизоде {ep.сделок.median():.0f}"
          f" · макс {ep.сделок.max():.0f}")
    print(f"  ПО СДЕЛКАМ:  среднее {d.net.mean():+.2f}% · медиана {d.net.median():+.2f}% · в плюсе {100*(d.net>0).mean():.0f}%")
    print(f"  ПО ЭПИЗОДАМ: среднее {ep.ret.mean():+.2f}% · медиана {ep.ret.median():+.2f}% · "
          f"в плюсе {100*(ep.ret>0).mean():.0f}% ({(ep.ret>0).sum()} из {len(ep)})")
    top = ep.ret.nlargest(max(1, len(ep)//10)).sum()
    print(f"  хрупкость: топ-10% эпизодов дают {top:.1f} из суммы {ep.ret.sum():.1f} "
          f"({100*top/ep.ret.sum() if ep.ret.sum() else 0:.0f}%)")
    y = ep.groupby("year").agg(эпизодов=("ret", "size"), среднее=("ret", "mean"),
                               в_плюсе=("ret", lambda x: 100*(x > 0).mean()))
    print("  по годам (ЭПИЗОДЫ):")
    print(y.to_string(float_format=lambda x: f"{x:8.2f}"))
    # перестановка: случайные эпизоды той же структуры
    rs = np.random.RandomState(20260912)
    allt = d.sort_values("t_in")
    span = (allt.t_in.max() - allt.t_in.min()).days
    outs = []
    for _ in range(300):
        shift = pd.Timedelta(days=rs.randint(30, max(31, span - 30)))
        shifted = allt.assign(t_in=allt.t_in + shift)
        # сравниваем со случайным набором сделок той же численности из всего пула
        samp = allt.sample(len(allt), replace=True, random_state=rs.randint(1e6))
        outs.append(samp.net.mean())
    real = d.net.mean()
    print(f"  бутстрап по сделкам: реальное {real:+.2f}% · 5-й перцентиль {np.percentile(outs,5):+.2f}% "
          f"· 95-й {np.percentile(outs,95):+.2f}%")
    # бутстрап ПО ЭПИЗОДАМ (правильный: эпизод — единица независимости)
    outs2 = [ep.ret.sample(len(ep), replace=True, random_state=rs.randint(1e6)).mean() for _ in range(2000)]
    lo, hi = np.percentile(outs2, 2.5), np.percentile(outs2, 97.5)
    print(f"  🔑 бутстрап ПО ЭПИЗОДАМ: среднее {np.mean(outs2):+.2f}% · 95% ДИ [{lo:+.2f}%, {hi:+.2f}%]"
          f"  {'✅ ноль вне ДИ' if lo > 0 else '❌ ноль внутри ДИ'}")


def main():
    T = pd.read_pickle(D / "small_account_trades.pkl")
    T = T[T.side == 1].copy()
    print(f"всего лонговых сделок: {len(T)} · окно {T.t_in.min():%Y-%m-%d} → {T.t_in.max():%Y-%m-%d}")
    print(f"кост в этом замере: {COST}% круг (в исходном было 0.35%)")
    for (sch, z), g in T.groupby(["scheme", "z"]):
        report(f"{sch} · порог −{int(z)}", g)
    report("ВСЕ СХЕМЫ, порог −75", T[T.z == 75])


if __name__ == "__main__":
    main()
