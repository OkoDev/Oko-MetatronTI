"""Картинки второго входа: 1h-свечи от дна ядра, волна 1 (L0→H1), откат волны 2, лимит, стоп, цели."""
import sys, numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pathlib import Path
sys.path.insert(0, ".")
from wave5_sm import load, _swings
from channel_depth import SP

BG, FG, GRID, UP, DN, WARN, ACC = "#0d1117", "#e6edf3", "#30363d", "#3fb950", "#f85149", "#79c0ff", "#ffd33d"
PKL = sys.argv[1] if len(sys.argv) > 1 else "wave3_after_core_sw6_r0.618.pkl"
SW1 = int(sys.argv[2]) if len(sys.argv) > 2 else 6
RETR = float(sys.argv[3]) if len(sys.argv) > 3 else 0.618
syms = sys.argv[4].split(",") if len(sys.argv) > 4 else None
e = pd.read_pickle(SP + PKL)
out = Path(SP) / "charts_wave3"; out.mkdir(exist_ok=True)
rs = np.random.RandomState(4)
if syms:
    pick = pd.concat([e[e.sym == s].head(1) for s in syms])
else:
    pick = pd.concat([e[e.pnl_t1 > 0].sample(2, random_state=rs), e[e.pnl_t1 <= 0].sample(2, random_state=rs)])
for _, r in pick.iterrows():
    d1 = load(r.sym, "1h"); t = d1.index
    ie = int(np.searchsorted(t.values, np.datetime64(pd.Timestamp(r.entry_ts).to_datetime64())))
    i0 = ie - int(r.lag_h); lo, hi = max(0, i0 - 30), min(len(d1) - 1, ie + 130)
    w = d1.iloc[lo:hi + 1]; x = np.arange(len(w)); o, h, l, c = w.open.values, w.high.values, w.low.values, w.close.values
    fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=BG); ax.set_facecolor(BG)
    for s_ in ax.spines.values(): s_.set_color(GRID)
    ax.tick_params(colors=FG, labelsize=8); ax.grid(color=GRID, lw=0.4, alpha=0.5)
    for i in range(len(w)):
        col = UP if c[i] >= o[i] else DN
        ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
        ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, alpha=0.9, lw=0))
    # волна 1 и уровень отката
    L0 = float(l[i0 - lo]); seg_h = pd.Series(d1.high.values[i0:ie + 60]); seg_l = pd.Series(d1.low.values[i0:ie + 60])
    sw = _swings(seg_h, seg_l, SW1); tops = [s for s in sw if s[3] and s[1] > 0 and s[2] > L0]
    if tops:
        conf, si, H1, _ = tops[0]; xi1 = i0 + si - lo
        ax.plot([i0 - lo, xi1], [L0, H1], color=WARN, lw=1.8, label="волна 1 нового импульса")
        ax.scatter([i0 - lo, xi1], [L0, H1], color=WARN, s=40, zorder=5)
        ax.annotate("дно (точка 5 ядра)", (i0 - lo, L0), color=WARN, fontsize=8, xytext=(4, -14), textcoords="offset points")
        ax.annotate("1", (xi1, H1), color=WARN, fontsize=10, fontweight="bold", xytext=(-3, 8), textcoords="offset points")
        lvl = H1 - RETR * (H1 - L0)
        ax.axhline(lvl, color=ACC, lw=1.0, ls="--", label=f"откат {RETR} волны 1 = лимит")
        ax.axvline(i0 + conf - lo, color=GRID, lw=0.8, ls=":"); ax.annotate("волна 1 подтверждена", (i0 + conf - lo, ax.get_ylim()[1]), color=GRID, fontsize=7, rotation=90, va="top", xytext=(-9, -6), textcoords="offset points")
        ax.axhline(H1, color="#7e57c2", lw=0.9, ls="--", label="цель 1 = вершина волны 1")
        ax.axhline(H1 + 0.618 * (H1 - L0), color=UP, lw=0.9, ls="--", label="цель 2 = 1.618 волны 1")
    ax.axhline(L0 * (1 - 0.002), color=DN, lw=1.0, ls=":", label=f"стоп под дно ({r.sl_pct:.2f}%)")
    ax.axvline(ie - lo, color=FG, lw=1.0, alpha=0.7); ax.annotate("вход 2 (лимит на откате)", (ie - lo, ax.get_ylim()[1]), color=FG, fontsize=8, rotation=90, va="top", xytext=(4, -6), textcoords="offset points")
    verdict = {"t1": "ЦЕЛЬ 1 ВЗЯТА", "stop": "СТОП", "time": "выход по времени"}[r.how_t1]
    ax.set_title(f"{r.sym} · 1h · второй вход: откат волны 2 нового импульса · сигнал ядра {pd.Timestamp(r.core_ts):%Y-%m-%d} → {verdict} {r.pnl_t1:+.2f}%  (до 1.618: {r.pnl_t2:+.2f}%)", color=FG, fontsize=10)
    lg = ax.legend(loc="best", fontsize=7, facecolor=BG, edgecolor=GRID)
    for tx in lg.get_texts(): tx.set_color(FG)
    fig.tight_layout(); fn = out / f"w3_{r.sym.replace('/', '')}_{r.pnl_t1:+.1f}.png"; fig.savefig(fn, dpi=115, facecolor=BG); plt.close(fig); print(fn.name)
