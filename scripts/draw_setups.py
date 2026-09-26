# -*- coding: utf-8 -*-
"""ОТРИСОВКА СЕТАПОВ ГЛАЗАМИ (05.09.2026).

Егор: «нарисуй мне 3-4 сетапа на одной монете, а я посмотрю глазами, что ты там тестируешь».

Рисуется РОВНО то, что считает `ote_canon_run.py`:
  · нога эталона с 1h (origin → extreme, `run_structure(swing_len=50).leg_history`);
  · зона OTE 0.618-0.786 от этой ноги;
  · бар ТРИГГЕРА — слом внутренней структуры len=5 на 15m в сторону ноги;
  · стоп за микро-экстремум (тот же масштаб, что триггер);
  · цель (extreme ноги / фибо −0.618);
  · ФАКТ: что сработало раньше и с каким результатом за 24 ч.

🔴 Правило проекта: посмотреть на свои картинки ДО отдачи ([[feedback_look_at_own_charts]]).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
from matplotlib.patches import Rectangle            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load                   # noqa: E402
from ote_canon_run import leg_series, micro_breaks, micro_levels, simulate, OTE_LO, OTE_HI, HOLD  # noqa: E402

BG, FG = "#131722", "#d1d4dc"
UP, DN = "#26a69a", "#ef5350"


def draw(ax, df, p, o, x, d, sl, tp, tname, res, sym, pad=90):
    a, b = max(0, p - pad), min(len(df), p + HOLD + 20)
    part = df.iloc[a:b]
    idx = np.arange(len(part))
    O, H, L, C = part.open.values, part.high.values, part.low.values, part.close.values
    w = 0.6
    for i in idx:                                       # свечи
        col = UP if C[i] >= O[i] else DN
        ax.plot([i, i], [L[i], H[i]], color=col, linewidth=0.6, zorder=2)
        ax.add_patch(Rectangle((i - w / 2, min(O[i], C[i])), w, max(abs(C[i] - O[i]), 1e-12),
                               facecolor=col, edgecolor=col, linewidth=0.4, zorder=3))
    pi = p - a                                          # позиция входа внутри окна
    amp = abs(x - o)
    z1 = x - OTE_LO * amp if d > 0 else x + OTE_LO * amp
    z2 = x - OTE_HI * amp if d > 0 else x + OTE_HI * amp
    lo_z, hi_z = min(z1, z2), max(z1, z2)
    ax.add_patch(Rectangle((0, lo_z), len(part), hi_z - lo_z, facecolor="#2962ff",
                           alpha=0.13, edgecolor="#2962ff", linewidth=0.8, zorder=1))
    ax.text(1, hi_z, f" зона OTE {OTE_LO}–{OTE_HI}", color="#5b8dff", fontsize=7, va="bottom", zorder=6)

    ax.axhline(o, color="#787b86", linewidth=0.9, linestyle=":", zorder=4)
    ax.text(len(part) - 1, o, "origin ноги ", color="#787b86", fontsize=7, ha="right", va="bottom")
    ax.axhline(x, color="#f0b90b", linewidth=0.9, linestyle=":", zorder=4)
    ax.text(len(part) - 1, x, "extreme ноги ", color="#f0b90b", fontsize=7, ha="right", va="bottom")

    ax.axhline(sl, color=DN, linewidth=1.2, zorder=5)
    ax.text(len(part) - 1, sl, f"стоп {abs(C[pi]-sl)/C[pi]*100:.2f}% ", color=DN,
            fontsize=7, ha="right", va="top")
    ax.axhline(tp, color=UP, linewidth=1.2, zorder=5)
    ax.text(len(part) - 1, tp, f"цель {tname} {abs(tp-C[pi])/C[pi]*100:.1f}% ", color=UP,
            fontsize=7, ha="right", va="bottom")

    ax.axvline(pi, color="#ffffff", linewidth=0.9, alpha=0.55, zorder=5)
    mark = "▲" if d > 0 else "▼"
    ax.plot([pi], [C[pi]], marker=mark, color="#ffffff", markersize=9, zorder=7)
    ax.text(pi, C[pi], f"  вход по слому len=5 ({'LONG' if d>0 else 'SHORT'})",
            color="#ffffff", fontsize=7.5, va="center", zorder=7)
    ax.axvspan(pi, min(pi + HOLD, len(part) - 1), color="#ffffff", alpha=0.04, zorder=0)

    ok = res > 0
    ax.set_title(f"{sym} · 15m · итог за 24 ч: {res:+.2f}% (косты учтены) "
                 f"{'✓ плюс' if ok else '✗ минус'}",
                 color=UP if ok else DN, fontsize=9, loc="left")
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color("#2a2e39")
    ax.tick_params(colors="#787b86", labelsize=6)
    ax.grid(color="#1e2130", linestyle="--", linewidth=0.4)
    step = max(1, len(part) // 8)
    ax.set_xticks(idx[::step])
    ax.set_xticklabels([part.index[i].strftime("%d.%m %H:%M") for i in idx[::step]], rotation=0)
    ax.set_xlim(-1, len(part))
    pad_y = (H.max() - L.min()) * 0.06
    ax.set_ylim(min(L.min(), lo_z, sl, tp) - pad_y, max(H.max(), hi_z, sl, tp) + pad_y)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ETH/USDT")
    ap.add_argument("--count", type=int, default=4)
    ap.add_argument("--out", default="tmp_charts/setups.png")
    ap.add_argument("--cost", type=float, default=0.35)
    a = ap.parse_args()

    d15, d1h = load(a.symbol, "15m"), load(a.symbol, "1h")
    LEG = leg_series(d1h)
    up, dn = micro_breaks(d15)
    m_hi, m_lo = micro_levels(d15)
    LG = LEG.shift(1).reindex(d15.index, method="ffill")
    H, L, C = d15.high.values, d15.low.values, d15.close.values
    org, ext, ltr = LG.origin.values, LG.extreme.values, LG.ltrend.values
    n = len(C)

    found = []
    last = -10 ** 9
    for p in range(n - 4000, n - HOLD - 1):            # свежий кусок истории
        t = int(ltr[p]) if ltr[p] == ltr[p] else 0
        if t == 0 or not (org[p] == org[p] and ext[p] == ext[p]):
            continue
        o, x = float(org[p]), float(ext[p])
        amp = abs(x - o)
        if amp <= 0:
            continue
        z1 = x - OTE_LO * amp if t > 0 else x + OTE_LO * amp
        z2 = x - OTE_HI * amp if t > 0 else x + OTE_HI * amp
        c = float(C[p])
        if not (min(z1, z2) <= c <= max(z1, z2)):
            continue
        if not (up[p] if t > 0 else dn[p]):
            continue
        if p - last < 200:                              # разные сетапы, не соседние бары
            continue
        mk = m_lo[p] if t > 0 else m_hi[p]
        if not (mk == mk):
            continue
        sl = mk * (1 - 0.002) if t > 0 else mk * (1 + 0.002)
        if (t > 0 and sl >= c) or (t < 0 and sl <= c):
            continue
        sp = abs(c - sl) / c * 100.0
        if not (0.15 <= sp <= 15.0):
            continue
        tp = x                                          # цель = extreme ноги
        if (t > 0 and tp <= c) or (t < 0 and tp >= c):
            tp = c * (1 + t * sp * 2 / 100.0)
            tname = "2R"
        else:
            tname = "extreme"
        r = simulate(H, L, C, p, c, t, sl, tp)
        if r is None:
            continue
        last = p
        found.append((p, o, x, t, sl, tp, tname, r - a.cost))
        if len(found) >= a.count:
            break

    if not found:
        print("🔴 сетапов не найдено")
        return 1
    rows = len(found)
    fig, axes = plt.subplots(rows, 1, figsize=(15, 4.6 * rows), facecolor=BG)
    if rows == 1:
        axes = [axes]
    for ax, (p, o, x, t, sl, tp, tname, res) in zip(axes, found):
        draw(ax, d15, p, o, x, t, sl, tp, tname, res, a.symbol)
    plt.tight_layout()
    out = ROOT / a.out
    out.parent.mkdir(exist_ok=True, parents=True)
    plt.savefig(out, dpi=115, facecolor=BG)
    print(f"сохранено: {out}")
    for i, (p, o, x, t, sl, tp, tname, res) in enumerate(found, 1):
        print(f"  сетап {i}: {d15.index[p]:%Y-%m-%d %H:%M} · {'LONG' if t>0 else 'SHORT'} · "
              f"вход {C[p]:.6g} · стоп {abs(C[p]-sl)/C[p]*100:.2f}% · "
              f"цель {tname} {abs(tp-C[p])/C[p]*100:.1f}% · итог {res:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
