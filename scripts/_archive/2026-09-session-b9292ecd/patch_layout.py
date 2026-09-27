import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")

HELPER = '''

# ─── текстовый блок схемы: под графиками, две колонки, крупный шрифт (Егор 14.09: «текст крупнее и читабельнее») ───
FIG_W = 16.0
TXT_FS, TXT_H = 12.0, 14.5
LINE_IN = 12.0 * 1.55 / 72          # высота строки основного текста, дюймы


def build_text_columns(rep: Dict[str, Any], title: str, up_: Optional[bool] = None, best: Optional[float] = None, wrap: int = 66):
    """→ (левая колонка «Разбор», правая «Сценарии»): списки (текст, стиль). Стили: h1, meta, h2, body, bullet, target, took, fork, bad."""
    import textwrap
    L = [(title, "h1"), (f"{pd.Timestamp(rep['now']):%d.%m.%Y %H:%M} UTC · цена {rep.get('price', float('nan')):.6g}", "meta"), ("", "gap"),
         ("Разбор", "h2")]
    for para in rep.get("text", []):
        lines = textwrap.wrap(para, wrap - 2)
        for i, ln in enumerate(lines):
            L.append((("• " if i == 0 else "  ") + ln, "body"))
        L.append(("", "small"))
    R = [("Сценарии", "h2")]
    price = rep.get("price") or 0
    for sc in rep.get("scenarios", []):
        R.append(("", "small"))
        for i, ln in enumerate(textwrap.wrap(sc["name"], wrap - 6)):
            R.append((ln, "h3"))
        for ln in textwrap.wrap(f"{sc['side']}. {sc['why']}", wrap):
            R.append((ln, "body"))
        for nm, v in sc["targets"]:
            took = best is not None and up_ is not None and ((best <= v) if up_ else (best >= v))
            d = (v / price - 1) * 100 if price else 0
            R.append((f"  {'✓' if took else '→'} {nm}: {v:.6g}  " + ("взята" if took else f"({d:+.1f}%)"), "took" if took else "target"))
        if sc.get("fork"):
            R.append((f"  развилка: {min(sc['fork']):.6g} – {max(sc['fork']):.6g}", "fork"))
        for i, ln in enumerate(textwrap.wrap(f"отмена: {sc['invalid']}", wrap - 2)):
            R.append(("  " + ln, "bad"))
    return L, R


def text_height_in(L, R) -> float:
    def h(col):
        return sum({"h1": 1.7, "meta": 1.1, "h2": 1.55, "h3": 1.3, "gap": .6, "small": .45}.get(st, 1.0) for _, st in col) * LINE_IN
    return max(h(L), h(R)) + 0.4


def draw_text_columns(fig, L, R, bottom_in: float, height_in: float):
    """Рисует две колонки в нижней части фигуры (координаты в дюймах от низа)."""
    BG, FG, ACC, GRN, DN, MUT = "#0f1116", "#e6e8ee", "#f5c542", "#66bb6a", "#ef5350", "#9aa3b2"
    H = fig.get_size_inches()[1]
    sty = {"h1": dict(fontsize=18, color=FG, fontweight="bold"), "meta": dict(fontsize=11, color=MUT),
           "h2": dict(fontsize=14.5, color=ACC, fontweight="bold"), "h3": dict(fontsize=13, color=ACC, fontweight="bold"),
           "body": dict(fontsize=TXT_FS, color=FG), "target": dict(fontsize=TXT_FS, color=GRN, family="monospace"),
           "took": dict(fontsize=TXT_FS, color="#6b7485", family="monospace"), "fork": dict(fontsize=TXT_FS, color=ACC, family="monospace"),
           "bad": dict(fontsize=TXT_FS, color=DN)}
    step = {"h1": 1.7, "meta": 1.1, "h2": 1.55, "h3": 1.3, "gap": .6, "small": .45}
    for col, x0 in ((L, 0.04), (R, 0.53)):
        ax = fig.add_axes([x0, bottom_in / H, 0.45, height_in / H]); ax.axis("off"); ax.set_facecolor(BG)
        y = height_in
        for txt, st in col:
            if txt and st in sty:
                ax.text(0, y / height_in, txt, va="top", transform=ax.transAxes, **sty[st])
            y -= step.get(st, 1.0) * LINE_IN
    fig.add_artist(__import__("matplotlib").lines.Line2D([0.04, 0.97], [(bottom_in + height_in + 0.15) / H] * 2, color="#2a2f3a", lw=1))
'''

p = "core/waves/wave_analyst.py"; s = open(p, encoding="utf-8").read()
anchor = "# ─── разбор ─────"
assert anchor in s
s = s.replace(anchor, HELPER.strip("\n") + "\n\n\n" + anchor, 1)
old = '''    st, leg = rep["structure"], rep["leg"]; up_ = st["up"]
    fig = plt.figure(figsize=(14, 13), facecolor=BG)
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1.15, 0.95], width_ratios=[1.35, 1], hspace=0.28, wspace=0.12)
'''
assert old in s
s = s.replace(old, '''    st, leg = rep["structure"], rep["leg"]; up_ = st["up"]
    TL, TR = build_text_columns(rep, f"{rep['sym']} · волновой разбор", up_, rep.get("best_since5", rep.get("price")))
    th = text_height_in(TL, TR); CH_H = 12.0; H = CH_H + th + 0.6
    fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 1.2, 0.95], hspace=0.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
''')
old_text = s[s.index("    # текст\n    axt = fig.add_subplot(gs[:, 1])"):s.index("    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches=\"tight\"); plt.close(fig)")]
s = s.replace(old_text, "    draw_text_columns(fig, TL, TR, 0.2, th)\n")
s = s.replace('    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches="tight"); plt.close(fig)', '    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)')
for a, b in (("ax1 = fig.add_subplot(gs[0, 0]); dd = to_daily(dh)", "ax1 = fig.add_subplot(gs[0]); dd = to_daily(dh)"),
             ("ax2 = fig.add_subplot(gs[1, 0]); i0 = max(0", "ax2 = fig.add_subplot(gs[1]); i0 = max(0"),
             ("ax3 = fig.add_subplot(gs[2, 0]); ls = rep.get", "ax3 = fig.add_subplot(gs[2]); ls = rep.get")):
    assert a in s, a; s = s.replace(a, b)
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "core/waves/wave_progress.py"; s = open(p, encoding="utf-8").read()
old = '''    cnt = rep.get("progress"); leg = rep.get("leg")
    fig = plt.figure(figsize=(14, 13), facecolor=BG)
    gs = fig.add_gridspec(3, 2, height_ratios=[.9, 1.25, .8], width_ratios=[1.35, 1], hspace=.28, wspace=.12)
    ax1 = fig.add_subplot(gs[0, 0])'''
assert old in s
s = s.replace(old, '''    from core.waves.wave_analyst import build_text_columns, text_height_in, draw_text_columns, FIG_W
    cnt = rep.get("progress"); leg = rep.get("leg")
    TL, TR = build_text_columns(rep, f"{rep['sym']} · волновой разбор · ход в процессе")
    th = text_height_in(TL, TR); CH_H = 12.0; H = CH_H + th + 0.6
    fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[.9, 1.3, .85], hspace=.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
    ax1 = fig.add_subplot(gs[0])''')
s = s.replace("    ax2 = fig.add_subplot(gs[1, 0])\n", "    ax2 = fig.add_subplot(gs[1])\n")
s = s.replace("    ax3 = fig.add_subplot(gs[2, 0]); tri = rep.get(\"triangle\")", "    ax3 = fig.add_subplot(gs[2]); tri = rep.get(\"triangle\")")
old_text = s[s.index("    at = fig.add_subplot(gs[:, 1]); at.axis(\"off\"); y = .99"):s.index("    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches=\"tight\"); plt.close(fig)")]
s = s.replace(old_text, "    draw_text_columns(fig, TL, TR, 0.2, th)\n")
s = s.replace('    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches="tight"); plt.close(fig)', '    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

# зум по клику на /waves: на всю ширину экрана с прокруткой, а не «вписать в высоту»
p = "web/structure_terminal.py"; s = open(p, encoding="utf-8").read()
old = '''.lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;justify-content:center;z-index:9;cursor:zoom-out}.lb img{max-width:98vw;max-height:96vh}'''
assert old in s
s = s.replace(old, '''.lb{position:fixed;inset:0;background:rgba(0,0,0,.94);display:none;align-items:flex-start;justify-content:center;z-index:9;cursor:zoom-out;overflow:auto;padding:12px}.lb img{width:min(98vw,1840px);max-width:none;max-height:none;height:auto}''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
