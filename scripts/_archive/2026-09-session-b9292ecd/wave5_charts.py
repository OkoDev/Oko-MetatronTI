# -*- coding: utf-8 -*-
"""КАРТИНКИ по замеру коррекции после 5 волн (требование Егора: «я вижу только текст»).

Строит:
  1. Примеры сделок — свечи + разметка волн 1-2-3-4-5, вход, стоп, цели (зона волны 4 и фибо),
     подписан исход. Берутся и выигрышные, и проигрышные — без отбора «красивых».
  2. Сводка: доля достижения каждой цели, распределение результата, кривая по эпизодам.

Вход: wave5_rows_<tf>.pkl (из wave5_correction.py). Выход: PNG в подпапке charts_<tf>/.
Запуск: python wave5_charts.py --tf 1h [--n 8]
"""
from __future__ import annotations
import argparse, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from research_harness import load  # noqa: E402

D = Path(__file__).parent
BG, FG, GRID = "#0f1116", "#e6e8ee", "#2a2f3a"
UP, DN = "#26a69a", "#ef5350"
ACC, WARN = "#f5c542", "#8ab4f8"


def style(ax):
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.grid(True, color=GRID, lw=0.5, alpha=0.5)
    ax.yaxis.label.set_color(FG); ax.xaxis.label.set_color(FG)
    ax.title.set_color(FG)


def draw_trade(r, tf, out: Path, df=None, levels=None):
    """Один сетап: свечи вокруг импульса + волны + вход/стоп/цели."""
    # ВЛОЖЕННЫЙ вход (wave5_wt_ltf): волны и индексы a/b/t — в барах HTF, вход — на LTF.
    # Рисуем по HTF-свечам, а бар входа находим ПО ВРЕМЕНИ r["ts"] в HTF-индексе.
    nested = "htf" in r and isinstance(r.get("htf"), str)
    tf_draw = r["htf"] if nested else tf
    df = load(r["sym"], tf_draw) if df is None else df.copy()
    if df.empty:
        return False
    idx_time = df.index
    df = df.reset_index()
    a, b, t = int(r["a"]), int(r["b"]), int(r["t"])
    hold = int(r["hold"])
    if nested:
        ratio = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}[tf_draw] / {"5m": 288, "15m": 96, "1h": 24, "4h": 6}[r["ltf"]]
        hold = max(10, int(hold * ratio))            # hold был в LTF-барах → в HTF
        entry_bar = int(np.searchsorted(idx_time.values, np.datetime64(pd.Timestamp(r["ts"]).to_datetime64())))
        entry_bar = min(max(entry_bar, 0), len(df) - 1)
        entry_label = f"вход по кроссу на {r['ltf']}"
    else:
        # 🔴 вход: в правиле Егора это бар КРОССА (j+1), а не бар обнаружения импульса (t).
        _j = r.get("j")
        entry_bar = int(_j) + 1 if _j is not None and pd.notna(_j) else t
        entry_label = "вход по кроссу WT" if (_j is not None and pd.notna(_j)) \
            else "вход (первое появление импульса)"
    lo_i, hi_i = max(0, a - 20), min(len(df) - 1, entry_bar + hold + 10)
    w = df.iloc[lo_i:hi_i + 1]
    x = np.arange(len(w))
    fig, ax = plt.subplots(figsize=(11, 5.5), facecolor=BG)
    style(ax)
    o, h, l, c = w.open.values, w.high.values, w.low.values, w.close.values
    for i in range(len(w)):
        col = UP if c[i] >= o[i] else DN
        ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
        ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64,
                               max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3),
                               color=col, alpha=0.9, lw=0))
    # волны 1-2-3-4-5 по ВСЕМ шести точкам разметки
    wi = list(r.get("wave_idx") or [a, b])
    wp = list(r.get("wave_px") or [r["p0"], r["p5"]])
    xs = [i - lo_i for i in wi]
    ax.plot(xs, wp, color=WARN, lw=1.6, alpha=0.9, label="импульс 1-2-3-4-5")
    ax.scatter(xs, wp, color=WARN, s=42, zorder=5)
    for k, (xk, pk) in enumerate(zip(xs, wp)):
        dy = 10 if (k % 2 == (0 if wp[-1] > wp[0] else 1)) else -16
        ax.annotate(str(k), (xk, pk), color=WARN, fontsize=10, fontweight="bold",
                    xytext=(-3, dy), textcoords="offset points")
    # линия 2-4 (канон: закрытие за ней = импульс завершён), продлеваем от точки 2 до бара входа
    if len(wi) >= 5 and "line24_break" in r:
        x2, x4 = xs[2], xs[4]; y2, y4 = wp[2], wp[4]
        if x4 > x2:
            sl_ = (y4 - y2) / (x4 - x2)
            xe = entry_bar - lo_i
            ax.plot([x2, xe], [y2, y4 + sl_ * (xe - x4)], color="#ff8f00", lw=1.2, ls="--", alpha=0.9,
                    label="линия 2-4 " + ("ПРОБИТА" if r["line24_break"] else "не пробита"))
    if np.isfinite(r.get("w2_retr", np.nan)) and np.isfinite(r.get("w4_retr", np.nan)):
        txt = f"w2 откат {r['w2_retr']:.2f} · w4 откат {r['w4_retr']:.2f} · w3 расш. {r['w3_ext']:.2f}"
        # чередование: тип (глубина×время) и форма (сложность коррекций по подсвингам младшего слоя)
        if len(wi) >= 5 and "ns2" in r and pd.notna(r.get("ns2")):
            t2, t4 = wi[2] - wi[1], wi[4] - wi[3]
            alt_type = (r["w2_retr"] > r["w4_retr"] and t2 < t4) or (r["w2_retr"] < r["w4_retr"] and t2 > t4)
            alt_form = abs(int(r["ns2"]) - int(r["ns4"])) >= 2
            txt += (f"\nволна 2: {t2} баров, подсвингов {int(r['ns2'])} · волна 4: {t4} баров, подсвингов {int(r['ns4'])}"
                    f"\nчередование по типу {'✓' if alt_type else '✗'} · по форме {'✓' if alt_form else '✗'}")
            # подсветка коррекций 2 и 4
            for k0 in (1, 3):
                ax.plot([xs[k0], xs[k0 + 1]], [wp[k0], wp[k0 + 1]], color="#ff8f00", lw=3.2, alpha=0.55, solid_capstyle="round")
        ax.annotate(txt, (0.01, 0.02), xycoords="axes fraction", color=WARN, fontsize=8, va="bottom")
    # уровни
    ax.axhline(r["entry"], color=FG, lw=1.1, label=f"вход {r['entry']:.6g}")
    ax.axhline(r["sl"], color=DN, lw=1.1, ls=":", label=f"стоп за волну 5 ({r['sl_pct']:.2f}%)")
    ax.axhline(r["p4"], color=ACC, lw=1.2, ls="-.", label="конец волны 4 = цель")
    for k, lbl, col in (("f382", "0.382", "#7e57c2"), ("f618", "0.618", "#43a047")):
        v = r.get(f"tgt_{k}")
        if v is not None and np.isfinite(v):
            ax.axhline(v, color=col, lw=0.9, ls="--", alpha=0.8, label=f"откат {lbl}")
    for lv in (levels or []):        # дополнительные уровни: (цена, подпись, цвет, стиль)
        px_, lb_, col_ = lv[0], lv[1], (lv[2] if len(lv) > 2 else "#9e9e9e")
        ax.axhline(px_, color=col_, lw=0.8, ls=(lv[3] if len(lv) > 3 else ":"), alpha=0.9)
        ax.annotate(lb_, (len(w) - 1, px_), color=col_, fontsize=7.5, xytext=(-2, 2), textcoords="offset points", ha="right")
    ax.axvline(entry_bar - lo_i, color=FG, lw=1.0, alpha=0.7)
    ax.annotate(entry_label, (entry_bar - lo_i, ax.get_ylim()[1]),
                color=FG, fontsize=8, rotation=90, va="top", xytext=(4, -6),
                textcoords="offset points")
    if entry_bar != t:      # виден разрыв «импульс подтверждён → дождались кросса»
        ax.axvline(t - lo_i, color=GRID, lw=0.8, ls=":", alpha=0.8)
        ax.annotate("импульс подтверждён", (t - lo_i, ax.get_ylim()[1]),
                    color=GRID, fontsize=7, rotation=90, va="top", xytext=(-9, -6),
                    textcoords="offset points")
    res = r.get("pnl_w4", np.nan)
    hit = r.get("hit_w4", False)
    verdict = "ЦЕЛЬ ВЗЯТА" if hit else ("СТОП" if r["stopped"] else "выход по времени")
    if "fractal_ok" in r and pd.notna(r.get("fractal_ok")):
        kind_lbl = ("фрактал ✓" if r["fractal_ok"] else "фрактал ✗") + \
                   (f" · сломы 1/3/5 = {int(r.get('bos1', 0))}/{int(r.get('bos3', 0))}/{int(r.get('bos5', 0))}") + \
                   ((" · линия 2-4 ✓" if r["line24_break"] else " · линия 2-4 ✗") if "line24_break" in r else "")
    else:
        kind_lbl = "textbook" if r.get("textbook") else "обычный"
    ax.set_title(f"{r['sym']} · {tf_draw} · импульс {r['dir']} · {kind_lbl} · {r['ts']:%Y-%m-%d %H:%M}"
                 f"   →   {verdict}   {res:+.2f}%", fontsize=10)
    lg = ax.legend(loc="best", fontsize=7, facecolor=BG, edgecolor=GRID)
    for txt in lg.get_texts():
        txt.set_color(FG)
    fig.tight_layout()
    fig.savefig(out, dpi=115, facecolor=BG)
    plt.close(fig)
    return True


def summary(d, tf, out: Path):
    TG = [("w4", "зона волны 4"), ("f382", "0.382"), ("f500", "0.5"), ("f618", "0.618")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), facecolor=BG)
    for ax in axes:
        style(ax)
    # 1) доля достижения
    names, vals, ctl = [], [], []
    for k, lbl in TG:
        if f"hit_{k}" not in d:
            continue
        g = d[d[f"pnl_{k}"].notna()]
        if len(g) < 30:
            continue
        names.append(lbl); vals.append(g[f"hit_{k}"].mean() * 100)
        ctl.append(g[f"ctlhit_{k}"].mean() * 100 if f"ctlhit_{k}" in g else np.nan)
    xx = np.arange(len(names))
    axes[0].bar(xx - 0.2, vals, 0.4, color=UP, label="сетап")
    axes[0].bar(xx + 0.2, ctl, 0.4, color=GRID, label="случайный вход")
    axes[0].set_xticks(xx); axes[0].set_xticklabels(names, color=FG)
    axes[0].set_title("Доля достижения цели, %")
    lg = axes[0].legend(fontsize=8, facecolor=BG, edgecolor=GRID)
    for t2 in lg.get_texts():
        t2.set_color(FG)
    # 2) распределение результата по цели «зона волны 4»
    if "pnl_w4" in d:
        v = d.pnl_w4.dropna()
        axes[1].hist(v, bins=60, color=WARN, alpha=0.85)
        axes[1].axvline(0, color=FG, lw=1)
        axes[1].axvline(v.mean(), color=UP, lw=1.2, ls="--", label=f"среднее {v.mean():+.2f}%")
        axes[1].axvline(v.median(), color=DN, lw=1.2, ls=":", label=f"медиана {v.median():+.2f}%")
        axes[1].set_title("Результат сделки, цель = зона волны 4")
        lg = axes[1].legend(fontsize=8, facecolor=BG, edgecolor=GRID)
        for t2 in lg.get_texts():
            t2.set_color(FG)
    # 3) накопление по эпизодам
    if "pnl_w4" in d:
        g = d[d.pnl_w4.notna()].sort_values("ts")
        axes[2].plot(np.arange(len(g)), g.pnl_w4.cumsum().values, color=ACC, lw=1.3)
        axes[2].axhline(0, color=FG, lw=0.8)
        axes[2].set_title("Накопленный результат, % (по сделкам)")
    fig.tight_layout()
    fig.savefig(out, dpi=115, facecolor=BG)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--file", default=None,
                    help="pkl со сделками; по умолчанию wave5_rows_<tf>.pkl "
                         "(для правила Егора: wave5wt_<tf>_z60.pkl)")
    ap.add_argument("--tag", default=None, help="имя подпапки для картинок")
    a = ap.parse_args()
    src = D / (a.file or f"wave5_rows_{a.tf}.pkl")
    d = pd.read_pickle(src)
    outdir = D / f"charts_{a.tag or a.tf}"
    outdir.mkdir(exist_ok=True)
    print(f"сделок {len(d)} · монет {d.sym.nunique()}")
    summary(d, a.tf, outdir / "summary.png")
    print("собрана сводка:", outdir / "summary.png")
    g = d[d.pnl_w4.notna()].copy()
    # без отбора «красивых»: половина лучших, половина худших, вперемешку по монетам
    take = pd.concat([g.nlargest(a.n // 2, "pnl_w4"), g.nsmallest(a.n - a.n // 2, "pnl_w4")])
    made = 0
    for i, (_, r) in enumerate(take.iterrows(), 1):
        p = outdir / f"trade_{i:02d}_{r['sym'].replace('/', '')}_{r['pnl_w4']:+.1f}.png"
        try:
            if draw_trade(r, a.tf, p):
                made += 1
                print("  ", p.name)
        except Exception as e:
            print(f"  [skip] {r['sym']}: {e}")
    print(f"готово: {made} примеров в {outdir}")


if __name__ == "__main__":
    main()
