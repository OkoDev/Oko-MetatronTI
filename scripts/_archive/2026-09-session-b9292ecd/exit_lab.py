# -*- coding: utf-8 -*-
"""ЛАБОРАТОРИЯ ВЫХОДА (13.09, Егор: «если поиграть с защитой сделки и целью — выжмем что-то стоящее?»).

Входы НЕ пересчитываются: берём уже найденные (wave5ltf_*.pkl — импульс на 4h, кросс на LTF),
перезагружаем LTF-бары после входа и прогоняем СЕТКУ правил выхода на одних и тех же входах.
Это честно: вход зафиксирован, меняется только управление позицией.

Правила (комбинируются):
  target   : w4 (зона волны 4) · f382 · w4x1.5 (дальше зоны w4 на 50% её расстояния) · none
  be_r     : перенос стопа в безубыток при достижении +be_r R (0 = нет)
  partial  : зафиксировать 50% на +partial R, остаток — по остальным правилам (0 = нет)
  trail_r  : после +trail_r R включить трейлинг за экстремумом последних TRAIL_N LTF-баров (0 = нет)
Стоп исходный — за экстремум w5 (как в замере). Кост 0.10% на КАЖДУЮ закрываемую часть.

Метрики: на сделку %, в R, медиана, WR, безтоп10, монет+, по годам, ДИ по эпизодам для лучших.
🔴 Перебор политик = ОТБОР: лучшая из N политик обязана пройти поправку (печатаем N и порог).
"""
from __future__ import annotations
import argparse, itertools, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from research_harness import load  # noqa: E402

D = Path(__file__).parent
COST = 0.10
TRAIL_N = 8


def sim(h, l, c, j, e, sl0, up_imp, tgt_px, end, be_r, partial, trail_r):
    """Одна сделка под одним правилом. up_imp=True → ШОРТ. Возвращает pnl% (взвешенный по частям)."""
    sgn = -1 if up_imp else 1
    one_r = abs(e - sl0)
    if one_r <= 0:
        return np.nan
    sl = sl0
    size = 1.0
    pnl = 0.0
    be_done = trail_on = part_done = False
    for k in range(j, end + 1):
        hi, lo = h[k], l[k]
        # 1) стоп первым
        if (hi >= sl) if up_imp else (lo <= sl):
            pnl += size * ((sl - e) / e * 100 * sgn - COST)
            return pnl
        # текущее «лучшее» достижение в R на этом баре
        best = ((e - lo) if up_imp else (hi - e)) / one_r
        # 2) частичная фиксация
        if partial and not part_done and best >= partial:
            px = e - partial * one_r if up_imp else e + partial * one_r
            pnl += 0.5 * ((px - e) / e * 100 * sgn - COST)
            size = 0.5; part_done = True
        # 3) цель
        if tgt_px is not None and ((lo <= tgt_px) if up_imp else (hi >= tgt_px)):
            pnl += size * ((tgt_px - e) / e * 100 * sgn - COST)
            return pnl
        # 4) безубыток
        if be_r and not be_done and best >= be_r:
            sl = e * (1 - 0.0005) if up_imp else e * (1 + 0.0005)   # чуть в плюс, чтобы покрыть кост
            be_done = True
        # 5) трейлинг за экстремумом последних TRAIL_N баров
        if trail_r and best >= trail_r:
            trail_on = True
        if trail_on:
            k0 = max(j, k - TRAIL_N + 1)
            tsl = h[k0:k + 1].max() if up_imp else l[k0:k + 1].min()
            if (tsl < sl) if up_imp else (tsl > sl):
                sl = tsl
    px = float(c[end])
    pnl += size * ((px - e) / e * 100 * sgn - COST)
    return pnl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="wave5ltf_4h_15m_z45.pkl")
    a = ap.parse_args()
    d = pd.read_pickle(D / a.file)
    d = d[d.pnl_w4.notna()].copy()
    print(f"входов: {len(d)} · монет {d.sym.nunique()} · {d.ts.min():%Y-%m-%d} → {d.ts.max():%Y-%m-%d}")
    span_y = (d.ts.max() - d.ts.min()).days / 365.25
    print(f"периодичность: {len(d)/span_y:.0f} сделок/год на {d.sym.nunique()} монет · "
          f"{len(d)/span_y/d.sym.nunique():.2f} на монету в год · {len(d)/span_y/12:.1f} в месяц\n")

    # кэш LTF-баров по символу
    bars = {}
    for s in d.sym.unique():
        df = load(s, d.ltf.iloc[0]).reset_index(drop=True)
        bars[s] = (df.high.values.astype(float), df.low.values.astype(float), df.close.values.astype(float))

    GRID = []
    for target in ("w4", "f382", "w4x1.5", "none"):
        for be_r in (0, 0.5, 1.0):
            for partial in (0, 1.0):
                for trail_r in (0, 1.0, 2.0):
                    GRID.append((target, be_r, partial, trail_r))
    print(f"политик в сетке: {len(GRID)} → лучшая из них ОБЯЗАНА пройти отбор; порог с поправкой "
          f"{100 - 5/len(GRID):.2f}-й перцентиль\n")

    rows = []
    for target, be_r, partial, trail_r in GRID:
        res = np.full(len(d), np.nan)
        for i, r in enumerate(d.itertuples()):
            h, l, c = bars[r.sym]
            j = int(r.j) + 1
            end = min(j + int(r.hold), len(c) - 1)
            up_imp = r.dir == "up"
            if target == "w4":
                tp = r.tgt_w4
            elif target == "f382":
                tp = r.tgt_f382
            elif target == "w4x1.5":
                tp = r.entry + 1.5 * (r.tgt_w4 - r.entry)
            else:
                tp = None
            if tp is not None and not np.isfinite(tp):
                continue
            res[i] = sim(h, l, c, j, float(r.entry), float(r.sl), up_imp, tp, end, be_r, partial, trail_r)
        d["_p"] = res
        g = d[d._p.notna()]
        pnl = g._p
        one_r = (g.entry - g.sl).abs() / g.entry * 100
        keep = pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):]
        by = g.groupby("sym")._p.sum()
        rows.append({"цель": target, "БУ@R": be_r, "част@R": partial, "трейл@R": trail_r,
                     "n": len(g), "на сделку%": pnl.mean(), "в R": (pnl / one_r).mean(),
                     "медиана%": pnl.median(), "WR%": (pnl > 0).mean() * 100,
                     "безтоп10": keep.mean(), "монет+%": (by > 0).mean() * 100,
                     "сумма%": pnl.sum()})
    t = pd.DataFrame(rows).sort_values("в R", ascending=False)
    print("=== ТОП-15 ПОЛИТИК ПО R НА СДЕЛКУ")
    print(t.head(15).to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    print("\n=== БАЗА (цель w4, без защиты) и ХУДШИЕ 5")
    print(t[(t.цель == "w4") & (t["БУ@R"] == 0) & (t["част@R"] == 0) & (t["трейл@R"] == 0)]
          .to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    print(t.tail(5).to_string(index=False, float_format=lambda x: f"{x:7.3f}"))

    # лучшая политика: годы + ДИ по эпизодам + тест «случайная политика»
    best = t.iloc[0]
    print(f"\n=== ЛУЧШАЯ: цель={best.цель} БУ@{best['БУ@R']} част@{best['част@R']} трейл@{best['трейл@R']}")
    target, be_r, partial, trail_r = best.цель, best["БУ@R"], best["част@R"], best["трейл@R"]
    res = np.full(len(d), np.nan)
    for i, r in enumerate(d.itertuples()):
        h, l, c = bars[r.sym]; j = int(r.j) + 1; end = min(j + int(r.hold), len(c) - 1)
        tp = {"w4": r.tgt_w4, "f382": r.tgt_f382, "w4x1.5": r.entry + 1.5 * (r.tgt_w4 - r.entry), "none": None}[target]
        if tp is not None and not np.isfinite(tp):
            continue
        res[i] = sim(h, l, c, j, float(r.entry), float(r.sl), r.dir == "up", tp, end, be_r, partial, trail_r)
    d["_p"] = res
    g = d[d._p.notna()].copy()
    g["ep"] = g.sym + "_" + g.ts.dt.strftime("%Y%m")
    ep = g.groupby("ep")._p.mean()
    rs = np.random.RandomState(7)
    bs = [ep.sample(len(ep), replace=True, random_state=rs.randint(1e6)).mean() for _ in range(3000)]
    print(f"  ДИ по эпизодам [{np.percentile(bs,2.5):+.2f}, {np.percentile(bs,97.5):+.2f}]  эпизодов {ep.size}")
    yr = g.groupby(g.ts.dt.year)._p.agg(["size", "mean", "median"])
    print("  по годам:", {int(y): (int(v["size"]), round(v["mean"], 2), round(v["median"], 2)) for y, v in yr.iterrows()})
    base = t[(t.цель == "w4") & (t["БУ@R"] == 0) & (t["част@R"] == 0) & (t["трейл@R"] == 0)].iloc[0]
    print(f"  прирост к базе: {best['в R'] - base['в R']:+.3f} R/сд · {best['на сделку%'] - base['на сделку%']:+.2f} %/сд")
    print(f"  🔴 множественность: {len(GRID)} политик; разброс по сетке в R: "
          f"{t['в R'].min():+.3f} … {t['в R'].max():+.3f}, медиана сетки {t['в R'].median():+.3f}")


if __name__ == "__main__":
    main()
