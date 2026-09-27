def render(rep: Dict[str, Any], dh: pd.DataFrame, dl: Optional[pd.DataFrame], out: Path) -> Path:
    """Схема разбора. Правило Егора 14.09: фибо и сломы — ОТРЕЗКАМИ между точками замера (не через весь экран);
    прогноз — штрихпунктирной стрелкой к зоне развилки и двумя пунктирными стрелками вариантов A/B из неё."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, FancyArrowPatch
    BG, FG, GRID, UP, DN, WAVE, ACC, LINE, VIO, GRN = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#ff8f00", "#9575cd", "#66bb6a"

    def candles(ax, w):
        x = np.arange(len(w)); o, h, l, c = (w[k].values.astype(float) for k in ("open", "high", "low", "close"))
        for i in range(len(w)):
            col = UP if c[i] >= o[i] else DN
            ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
            ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, alpha=0.9, lw=0))

    def style(ax, title):
        ax.set_facecolor(BG); [sp.set_color(GRID) for sp in ax.spines.values()]
        ax.tick_params(colors=FG, labelsize=7.5); ax.grid(True, color=GRID, lw=0.5, alpha=0.4)
        ax.set_title(title, color=FG, fontsize=9.5, loc="left")

    def seg(ax, x0, x1, y, txt, col, ls="--", lw=0.9, side="right"):
        xa, xb = sorted((x0, x1))
        ax.hlines(y, xa, xb, colors=col, linestyles=ls, lw=lw, alpha=0.95)
        if txt:
            ax.annotate(f"{txt} {y:.5g}", (xb if side == "right" else xa, y), color=col, fontsize=6.8,
                        ha="left" if side == "right" else "right", va="center",
                        xytext=(3 if side == "right" else -3, 0), textcoords="offset points")

    def xi(w, tt):
        return int(w.index.get_indexer([pd.Timestamp(tt)], method="nearest")[0])

    def arrow(ax, x0, y0, x1, y1, col, ls, txt=None, lw=1.6):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=14, color=col, lw=lw, linestyle=ls, zorder=7))
        if txt:
            ax.annotate(f"{txt}\n{y1:.5g}", (x1, y1), color=col, fontsize=7.5, fontweight="bold", xytext=(4, 0), textcoords="offset points", va="center")

    st, leg = rep["structure"], rep["leg"]; up_ = st["up"]
    fig = plt.figure(figsize=(14, 13), facecolor=BG)
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1.15, 0.95], width_ratios=[1.35, 1], hspace=0.28, wspace=0.12)

    # 1D: нога, фибо отрезками от начала до конца ноги
    ax1 = fig.add_subplot(gs[0, 0]); dd = to_daily(dh); w = dd.iloc[-200:]; candles(ax1, w)
    style(ax1, "1D · дневная нога (фибо от её начала до конца) и где закончилась пятая")
    if leg:
        xo, xe = xi(w, leg["origin_t"]), xi(w, leg["ext_t"])
        ax1.plot([xo, xe], [leg["origin"], leg["ext"]], color=WAVE, lw=1.1, ls="--", alpha=0.8)
        for k, v in leg["levels"].items():
            seg(ax1, xo, xe, v, k, ACC if k in ("0.618", "0.705", "0.79") else VIO, "-" if k == "0.705" else ":", 0.8, side="left")
        for k, v in leg["extensions"].items():
            seg(ax1, xo, xe, v, k, GRN, "-.", 0.7, side="left")
        y1_, y2_ = sorted((leg["levels"]["0.618"], leg["levels"]["0.79"]))
        ax1.add_patch(Rectangle((min(xo, xe), y1_), abs(xe - xo), y2_ - y1_, color=ACC, alpha=0.10, lw=0))
        x5 = xi(w, st["t5x"]); ax1.scatter([x5], [st["p5x"]], color=WAVE, s=36, zorder=6)
        ax1.annotate(f"5 · глубина {leg['depth']:.2f} · {leg['zone']}", (x5, st["p5x"]), color=ACC, fontsize=8,
                     xytext=(-6, -14 if not up_ else 8), textcoords="offset points", ha="right")
    ax1.set_xlim(-12, len(w) + 8)

    # 4h: счёт, коррекции отрезком 0→5, развилка, прогноз стрелками
    ax2 = fig.add_subplot(gs[1, 0]); i0 = max(0, st["wave_idx"][0] - 25); w4 = dh.iloc[i0:]; candles(ax2, w4)
    style(ax2, f"4h · {'импульс' if st['kind'] == 'impulse' else 'конечная диагональ · ' + st['form']} 0-5 · прогноз из зоны развилки")
    xs = [i - i0 for i in st["wave_idx"]]; ys = list(st["wave_px"][:5]) + [st["p5x"]]; xs[5] = xi(w4, st["t5x"])
    ax2.plot(xs, ys, color=WAVE, lw=1.7); ax2.scatter(xs, ys, color=WAVE, s=30, zorder=5)
    for kk, (xk, yk) in enumerate(zip(xs, ys)):
        ax2.annotate(str(kk), (xk, yk), color=WAVE, fontsize=10, fontweight="bold",
                     xytext=(-3, 9 if (kk % 2 == (0 if up_ else 1)) else -15), textcoords="offset points")
    if st["kind"] == "diagonal":
        for a_, b_ in ((1, 3), (2, 4)):
            ax2.plot([xs[a_], xs[b_]], [ys[a_], ys[b_]], color=LINE, lw=1, ls="--")
    for k, v in rep["corr"].items():
        seg(ax2, xs[0], xs[5], v, f"{k}", GRN if k in ("0.5", "0.618") else VIO, "--", 0.8, side="left")
    n4 = len(w4) - 1; F = max(18, int(0.45 * len(w4)))
    fc = rep.get("forecast") or {}
    lo, hi = sorted(fc.get("fork", (rep["corr"]["0.5"], rep["corr"]["0.618"])))
    xf0, xf1 = n4 + int(F * 0.30), n4 + int(F * 0.45)
    ax2.add_patch(Rectangle((xf0, lo), xf1 - xf0, hi - lo, color=GRN, alpha=0.18, lw=0))
    ax2.annotate("развилка A/B", (xf0, hi), color=GRN, fontsize=8, xytext=(0, 3), textcoords="offset points")
    ym = (lo + hi) / 2; price = rep["price"]
    ax2.scatter([n4], [price], color=FG, s=18, zorder=6)
    arrow(ax2, n4, price, xf0, ym, FG, "-.", None, 1.3)                       # штрихпунктир — путь к развилке
    if fc.get("A"):
        ya, ta = fc["A"]; arrow(ax2, xf1, ym, n4 + F, ya, ACC, "--", ta)       # пунктир — вариант A
    if fc.get("B"):
        yb, tb = fc["B"]; arrow(ax2, xf1, ym, n4 + int(F * 0.9), yb, DN if not up_ else UP, "--", tb)
    ax2.set_xlim(-12, n4 + F + 16)

    # младший ТФ: сломы от свинга до пересечения, фибо A отрезком 5→A, зона от A до касания
    ax3 = fig.add_subplot(gs[2, 0]); ls = rep.get("ltf_state") or {}
    if dl is not None and len(dl):
        w3 = dl[dl.index >= st["t5x"] - pd.Timedelta(hours=3)]
        step = max(1, int(np.ceil(len(w3) / 360)))
        if step > 1:
            w3 = w3.resample(pd.Timedelta(w3.index.to_series().diff().median() * step), label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        candles(ax3, w3); n3 = len(w3) - 1
        tfm = int((w3.index.to_series().diff().median()).total_seconds() // 60)
        style(ax3, f"{rep['ltf']} (свечи {tfm}m) · от пятой: слом, волна A, зона отката")
        x5 = xi(w3, st["t5x"]); ax3.scatter([x5], [st["p5x"]], color=WAVE, s=40, zorder=6)
        ax3.annotate("5", (x5, st["p5x"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
        for key_, nm, col in (("choch_int", "CHoCH", LINE), ("choch_sw", "CHoCH старший", UP if not up_ else DN)):
            c = ls.get(key_)
            if c:
                seg(ax3, xi(w3, c["t0"]), xi(w3, c["t"]), c["level"], nm, col, "-", 1.2)
        if ls.get("A"):
            xa = xi(w3, ls["a_t"]); ax3.scatter([xa], [ls["a_top"]], color=WAVE, s=40, zorder=6)
            ax3.annotate("A", (xa, ls["a_top"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
            ax3.plot([x5, xa], [st["p5x"], ls["a_top"]], color=WAVE, lw=1, alpha=0.8)
            z = ls["zone"]
            for f_, v in z.items():
                seg(ax3, x5, xa, v, f"{f_}", ACC, ":", 0.9, side="left")
            xt_ = xi(w3, ls["zone_touch_t"]) if ls.get("zone_touch_t") is not None else n3
            ax3.add_patch(Rectangle((xa, min(z[0.5], z[0.705])), max(1, xt_ - xa), abs(z[0.5] - z[0.705]), color=ACC, alpha=0.22, lw=0))
            seg(ax3, xa, n3, ls["stop_886"], "стоп 0.886", DN, "--", 0.9)
        ax3.set_xlim(-25, n3 + 30)
    else:
        style(ax3, "младший ТФ не загружен")

    # текст
    axt = fig.add_subplot(gs[:, 1]); axt.axis("off"); axt.set_facecolor(BG)
    y = 0.99
    axt.text(0, y, f"{rep['sym']} · волновой разбор", color=FG, fontsize=15, fontweight="bold", va="top"); y -= 0.035
    axt.text(0, y, f"{pd.Timestamp(rep['now']):%d.%m.%Y %H:%M} UTC · цена {rep['price']:.6g}", color="#9aa3b2", fontsize=9, va="top"); y -= 0.035
    for para in rep["text"]:
        for ln in textwrap.wrap(para, 58):
            axt.text(0, y, ln, color=FG, fontsize=8.8, va="top"); y -= 0.0215
        y -= 0.008
    best = rep.get("best_since5", rep["price"])
    for sc in rep["scenarios"]:
        y -= 0.01
        axt.text(0, y, sc["name"], color=ACC, fontsize=10.5, fontweight="bold", va="top"); y -= 0.026
        for ln in textwrap.wrap(f"сторона: {sc['side']}. {sc['why']}", 58):
            axt.text(0, y, ln, color=FG, fontsize=8.6, va="top"); y -= 0.0205
        for nm, v in sc["targets"]:
            took = (best <= v) if up_ else (best >= v)
            d = (v / rep["price"] - 1) * 100
            axt.text(0.03, y, f"{'✓' if took else '→'} {nm}: {v:.6g}  " + ("взята" if took else f"({d:+.1f}%)"),
                     color="#6b7485" if took else GRN, fontsize=8.6, va="top", family="monospace"); y -= 0.0195
        if sc.get("fork"):
            axt.text(0.03, y, f"развилка: {min(sc['fork']):.6g} – {max(sc['fork']):.6g}", color=ACC, fontsize=8.6, va="top", family="monospace"); y -= 0.0195
        for ln in textwrap.wrap(f"отмена: {sc['invalid']}", 56):
            axt.text(0.03, y, ln, color=DN, fontsize=8.6, va="top"); y -= 0.0195
    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out
