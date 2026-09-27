# -*- coding: utf-8 -*-
"""🎯 ПРАВИЛО ЕГОРА ДОСЛОВНО (11.09.2026, после сверки на его графике):

  «ожидание кросса на часовике, после которого на 15m и ниже берутся кроссы вверх;
   хоть на 3m хоть на 1m можно пробовать ... направление есть — торгуем»

  НАПРАВЛЕНИЕ  кросс wt1×wt2 ВВЕРХ на 1h → лонг-режим до ВСТРЕЧНОГО кросса вниз на 1h
               варианты контекста: A — любой кросс вверх · B — кросс вверх в OS (wt1 < −60)
  ТОРГОВЛЯ     внутри режима на LTF ∈ {15m, 5m, 3m, 1m}: каждый кросс вверх → лонг,
               выход по встречному кроссу на ТОМ ЖЕ LTF (или по концу режима 1h)
  ЗЕРКАЛО      то же для шорта (кросс вниз на 1h → шорты на LTF)
  КОНТРОЛЬ     те же LTF-отрезки ВНЕ режима часовика — что добавляет направление

Разрезы: цвет бара LTF на входе (наклон EMA(wt1,200) — окраска у Егора) · цвет бара 1h.
Косты: печатаю грязными и нетто при 0.35% (наш тариф с проскальзыванием), 0.15% и 0.08%
(мейкер) — на 1m-3m именно косты решают, торгуемо ли.
Данные: 1m-паркеты Binance, 50 монет, 2025-01…2026-08; 1h и LTF собираются из 1m.
"""
import sys, os, glob, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
import numpy as np, pandas as pd
from core.indicators.indicators import calculate_wt

D = os.path.dirname(os.path.abspath(__file__))
LTFS = [15, 5, 3, 1]
COSTS = [0.35, 0.15, 0.08]
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))


def bars(d1, tf):
    if tf == 1:
        return d1[["open", "high", "low", "close"]]
    return d1.resample(f"{tf}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def wtx(d):
    w = calculate_wt(d.reset_index(drop=True))
    w1, w2 = w.wt1.values, w.wt2.values
    ma = pd.Series(w1).ewm(span=200, adjust=False).mean().values
    x = w1 - w2
    cu = np.concatenate(([False], (x[:-1] <= 0) & (x[1:] > 0)))
    cd = np.concatenate(([False], (x[:-1] >= 0) & (x[1:] < 0)))
    green = np.concatenate(([False], ma[1:] > ma[:-1]))
    return w1, cu, cd, green


rows = []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if d1.index.tz is not None:
        d1.index = d1.index.tz_localize(None)
    d1 = d1[~d1.index.duplicated()].sort_index()
    if len(d1) < 200000:
        continue
    h = bars(d1, 60)
    hw1, hcu, hcd, hgreen = wtx(h)
    h_close_t = (h.index + pd.Timedelta(minutes=60)).values   # режим известен после ЗАКРЫТИЯ бара 1h
    # режимы 1h: (t_start, t_end, side, in_os, green_1h)
    regimes = []
    idx = np.where(hcu | hcd)[0]
    for a, b in zip(idx[:-1], idx[1:]):
        if a < 400:
            continue
        side = 1 if hcu[a] else -1
        in_zone = (hw1[a] < -60) if side == 1 else (hw1[a] > 60)
        regimes.append((h_close_t[a], h_close_t[b], side, bool(in_zone), bool(hgreen[a])))
    if not regimes:
        continue
    rs = np.array([r[0] for r in regimes], dtype="datetime64[ns]")
    re_ = np.array([r[1] for r in regimes], dtype="datetime64[ns]")
    for tf in LTFS:
        l = bars(d1, tf)
        w1, cu, cd, green = wtx(l)
        op = l.open.values
        t_open = l.index.values
        n = len(op)
        cross = np.where(cu | cd)[0]
        for a, b in zip(cross[:-1], cross[1:]):
            if a < 400 or b + 1 >= n:
                continue
            side = 1 if cu[a] else -1
            t_sig = t_open[a] + np.timedelta64(tf, "m")          # кросс известен после закрытия бара
            k = np.searchsorted(rs, t_sig, "right") - 1
            inside = k >= 0 and t_sig < re_[k]
            if inside:
                rside, r_os, r_green = regimes[k][2], regimes[k][3], regimes[k][4]
                # выход: встречный кросс LTF или конец режима 1h — что раньше
                t_end_reg = re_[k]
                jb = b
                if rside == side:
                    je = np.searchsorted(t_open, t_end_reg, "left")
                    jb = min(b, max(je - 1, a + 1))
            else:
                rside, r_os, r_green, jb = 0, False, False, b
            e, xp = op[a + 1], op[min(jb + 1, n - 1)]
            g = (xp - e) / e * 100 * side
            rows.append((sym, tf, side, rside, r_os, r_green, bool(green[a]), g, jb - a,
                         pd.Timestamp(t_open[a]).year))
    if fi % 10 == 0:
        print(f"  [{fi}/{len(files)}] {len(rows):,}", flush=True)

T = pd.DataFrame(rows, columns=["sym", "tf", "side", "rside", "r_os", "r_green", "green",
                                "gross", "bars", "year"])
T.to_pickle(os.path.join(D, "dir_window.pkl"))
print(f"\nотрезков {len(T):,} · монет {T.sym.nunique()}\n")


def line(g, lbl):
    if len(g) < 50:
        return
    per = g.groupby("sym").gross.mean()
    nets = " · ".join(f"нетто@{c:.2f} {g.gross.mean()-c:+.3f}%" for c in COSTS)
    print(f"  {lbl:>46}: n={len(g):>8,} · грязн {g.gross.mean():+.3f}% · {nets} · "
          f"WR@0.35 {(g.gross>0.35).mean()*100:4.1f}% · бар мед {g.bars.median():.0f} · "
          f"монет+ @0.35 {int(((per-0.35)>0).sum())}/{len(per)}")


for tf in LTFS:
    G = T[T.tf == tf]
    print(f"{'='*120}\n=== LTF {tf}m ===")
    line(G[(G.side == 1) & (G.rside == 0)], "LONG вне режима 1h (контроль)")
    line(G[(G.side == 1) & (G.rside == -1)], "LONG против режима 1h")
    line(G[(G.side == 1) & (G.rside == 1)], "LONG по режиму 1h (A: любой кросс ▲)")
    line(G[(G.side == 1) & (G.rside == 1) & G.r_os], "LONG по режиму 1h (B: кросс ▲ в OS)")
    line(G[(G.side == 1) & (G.rside == 1) & G.green], "  └ + бар LTF зелёный")
    line(G[(G.side == 1) & (G.rside == 1) & ~G.green], "  └ + бар LTF красный")
    line(G[(G.side == 1) & (G.rside == 1) & G.r_green], "  └ + бар 1h зелёный")
    line(G[(G.side == 1) & (G.rside == 1) & G.r_os & G.r_green], "  └ B + бар 1h зелёный")
    line(G[(G.side == -1) & (G.rside == -1)], "SHORT по режиму 1h (зеркало A)")
    line(G[(G.side == -1) & (G.rside == -1) & G.r_os], "SHORT по режиму 1h (зеркало B: в OB)")
    print()

print("=== ПО ГОДАМ: LONG по режиму 1h (A), грязными ===")
for tf in LTFS:
    G = T[(T.tf == tf) & (T.side == 1) & (T.rside == 1)]
    print(f"  {tf:>2}m: " + " · ".join(f"{y}: {G[G.year==y].gross.mean():+.3f}% (n={int((G.year==y).sum()):,})"
                                    for y in sorted(G.year.unique())))
