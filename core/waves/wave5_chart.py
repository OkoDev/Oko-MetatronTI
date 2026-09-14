"""Картинка сетапа ядра волн: свечи HTF + волны 0-5, коррекции 2/4 подсвечены, линия 2-4, канал,
вход/стоп/цель, фибо-прогноз пятой и коррекции, подпись правил ядра. Без внешних зависимостей кроме matplotlib."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

BG, FG, GRID, UP, DN, WAVE, ACC, LINE = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#ff8f00"


def draw_setup(s: Dict[str, Any], dh: pd.DataFrame, ls: Optional[Dict[str, Any]], out: Path, title_extra: str = "") -> Path:
    a, b = int(s["a"]), int(s["b"]); w_idx = list(s["wave_idx"]); w_px = list(s["wave_px"])
    long_ = s["side"] == "LONG"
    lo_i, hi_i = max(0, a - 20), len(dh) - 1
    w = dh.iloc[lo_i:hi_i + 1]; x = np.arange(len(w)); o, h, l, c = w.open.values, w.high.values, w.low.values, w.close.values
    fig, ax = plt.subplots(figsize=(12, 5.8), facecolor=BG); ax.set_facecolor(BG)
    for sp in ax.spines.values(): sp.set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8); ax.grid(True, color=GRID, lw=0.5, alpha=0.5)
    for i in range(len(w)):
        col = UP if c[i] >= o[i] else DN
        ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
        ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, alpha=0.9, lw=0))
    xs = [i - lo_i for i in w_idx]
    p5e = float(ls["p5_ext"]) if ls else float(s["p5"]); wp = w_px[:5] + [p5e]
    ax.plot(xs, wp, color=WAVE, lw=1.7, alpha=0.95, label="импульс 0-1-2-3-4-5"); ax.scatter(xs, wp, color=WAVE, s=40, zorder=5)
    for k, (xk, pk) in enumerate(zip(xs, wp)):
        ax.annotate(str(k), (xk, pk), color=WAVE, fontsize=10, fontweight="bold", xytext=(-3, 10 if (k % 2 == (1 if long_ else 0)) else -16), textcoords="offset points")
    for k0 in (1, 3):
        ax.plot([xs[k0], xs[k0 + 1]], [wp[k0], wp[k0 + 1]], color=LINE, lw=3.2, alpha=0.5, solid_capstyle="round")
    # линия 2-4 и параллель канала через 3 — до последнего бара
    x2, x4, y2, y4 = xs[2], xs[4], wp[2], wp[4]
    if x4 > x2:
        sl_ = (y4 - y2) / (x4 - x2); xe = len(w) - 1
        ax.plot([x2, xe], [y2, y4 + sl_ * (xe - x4)], color=LINE, lw=1.2, ls="--", alpha=0.9, label="линия 2-4" + (" — ПРОБИТА" if ls and ls["line24_broken"] else ""))
        x3, y3 = xs[3], wp[3]
        ax.plot([x3, xe], [y3, y3 + sl_ * (xe - x3)], color=LINE, lw=0.9, ls="-.", alpha=0.7, label="параллель канала (цель пятой)")
    ax.axhline(s["p4_target"], color=ACC, lw=1.2, ls="-.", label="цель: конец волны 4")
    if ls:
        ax.axhline(ls["stop"], color=DN, lw=1.1, ls=":", label=f"стоп за экстремум пятой")
        ax.axhline(ls["last_close"], color=FG, lw=0.9, alpha=0.8, label=f"текущая {ls['last_close']:.6g}")
    for k, lb, col, st in (("w5_618", "5 = 0.618×1", "#c8791a", ":"), ("w5_eq1", "5 = 1", "#c8791a", ":"), ("w5_1618", "5 = 1.618×1", "#c8791a", "--"),
                           ("corr_382", "коррекция 0.382", "#7e57c2", "--"), ("corr_500", "коррекция 0.5", "#7e57c2", ":"), ("corr_618", "коррекция 0.618", "#43a047", "--")):
        v = s.get(k)
        if v is None: continue
        ax.axhline(v, color=col, lw=0.8, ls=st, alpha=0.85)
        ax.annotate(lb, (len(w) - 1, v), color=col, fontsize=7.5, xytext=(-2, 2), textcoords="offset points", ha="right")
    ns = s.get("ns") or [0] * 5
    txt = (f"w2 откат {s['w2_retr']:.2f} · w4 откат {s['w4_retr']:.2f} · w3/w1 {s['w3_ext']:.2f} · импульс {s['imp_pct']}% · WT {s['wt_top']}\n"
           f"фрактал {'✓' if s['fractal'] else '✗'} (сломы 1/3 = {s['bos1']}/{s['bos3']}) · канал {s['depth5']} · чередование тип {'✓' if s['altern_type'] else '✗'} форма {'✓' if s['altern_form'] else '✗'} "
           f"(подсвингов 2/4 = {ns[1]}/{ns[3]}) · счёт {'✓' if s['count_ok'] else '✗ (подволны)'}\n"
           f"1D: структура {'бычья' if s['d_bull'] else ('медвежья' if s['d_bull'] is not None else '?')}, дневной свинг {'пробит' if s['d_broke'] else 'не пробит'}, WT1D {s['d_wt']}"
           + (f" · прогноз пятой достигнут: {', '.join(ls['w5_reached']) or '—'} · коррекция показала: {', '.join(ls['corr_reached']) or '—'}" if ls else ""))
    ax.annotate(txt, (0.01, 0.02), xycoords="axes fraction", color=WAVE, fontsize=8, va="bottom")
    tag = "ЯДРО" if s["core_full"] else ("канал" if s["core"] else "разметка")
    ax.set_title(f"{s.get('sym','')} · {s['tf']} · {s['side']} · вершина {pd.Timestamp(s['top_time']):%Y-%m-%d %H:%M} ({s['hours_from_top']:.0f} ч) · {tag} {title_extra}", color=FG, fontsize=10)
    lg = ax.legend(loc="best", fontsize=7, facecolor=BG, edgecolor=GRID)
    for t_ in lg.get_texts(): t_.set_color(FG)
    fig.tight_layout(); out.parent.mkdir(parents=True, exist_ok=True); fig.savefig(out, dpi=110, facecolor=BG); plt.close(fig)
    return out
