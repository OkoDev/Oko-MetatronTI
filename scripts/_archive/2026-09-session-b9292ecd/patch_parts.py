import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")


def rep(s, old, new, cnt=1):
    assert s.count(old) == cnt, (old[:80], s.count(old))
    return s.replace(old, new)


# ── wave_analyst.render: режим parts (три отдельные картинки для TG)
p = "core/waves/wave_analyst.py"; s = open(p, encoding="utf-8").read()
s = rep(s, "FIG_W = 16.0\n", "FIG_W = 16.0\n# TG (Егор 15.09: «очень мелко в TG») — каждая панель отдельной картинкой: 8×4.6 дюйма при 225 dpi ≈ 1800×1035 px,\n# шрифты относительно кадра вдвое крупнее, чем в общей схеме шириной 16 дюймов\nPART_W, PART_H, PART_DPI = 8.0, 4.6, 225\n")
s = rep(s, "def render(rep: Dict[str, Any], dh: pd.DataFrame, dl: Optional[pd.DataFrame], out: Path) -> Path:",
        "def render(rep: Dict[str, Any], dh: pd.DataFrame, dl: Optional[pd.DataFrame], out: Path, parts: bool = False):")
s = rep(s, """        ax.set_title(title, color=FG, fontsize=9.5, loc="left")""",
        """        ax.set_title((f"{rep['sym']} · " if parts else "") + title, color=FG, fontsize=9.5, loc="left")""")
s = rep(s, """    fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 1.2, 0.95], hspace=0.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
""", """    if parts:
        figs = [plt.figure(figsize=(PART_W, PART_H), facecolor=BG) for _ in range(3)]
        axes = [f_.add_axes([0.085, 0.1, 0.88, 0.8]) for f_ in figs]
    else:
        fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
        gs = fig.add_gridspec(3, 1, height_ratios=[1, 1.2, 0.95], hspace=0.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
        axes = [fig.add_subplot(gs[i]) for i in range(3)]
""")
s = rep(s, "    ax1 = fig.add_subplot(gs[0]); dd = to_daily(dh); w = dd.iloc[-200:]; candles(ax1, w)",
        "    ax1 = axes[0]; dd = to_daily(dh); w = dd.iloc[-200:]; candles(ax1, w)")
s = rep(s, """    ax2 = fig.add_subplot(gs[1]); i0 = max(0, st["wave_idx"][0] - 25)""", """    ax2 = axes[1]; i0 = max(0, st["wave_idx"][0] - 25)""")
s = rep(s, """    ax3 = fig.add_subplot(gs[2]); ls = rep.get("ltf_state") or {}""", """    ax3 = axes[2]; ls = rep.get("ltf_state") or {}""")
SAVE = """    draw_text_columns(fig, TL, TR, 0.2, th)
    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)
    return out
"""
SAVE_NEW = """    if parts:
        return save_parts(figs, out, BG)
    draw_text_columns(fig, TL, TR, 0.2, th)
    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)
    return out
"""
s = rep(s, SAVE, SAVE_NEW)
s = rep(s, "\n\ndef time_axis(", '''

def save_parts(figs, out: Path, bg: str) -> List[Path]:
    """Панели по отдельным файлам <stem>_1.png, _2.png, _3.png (для альбома в TG)."""
    import matplotlib.pyplot as plt
    paths = []
    for i, f_ in enumerate(figs, 1):
        pth = Path(out).with_name(f"{Path(out).stem}_{i}.png")
        f_.savefig(pth, dpi=PART_DPI, facecolor=bg); plt.close(f_); paths.append(pth)
    return paths


def time_axis(''')
# report_for: parts + сценарии с пояснением
s = rep(s, "def report_for(sym: str, ltf: str = \"3m\", out_dir: Optional[Path] = None, now: Optional[pd.Timestamp] = None) -> Dict[str, Any]:",
        "def report_for(sym: str, ltf: str = \"3m\", out_dir: Optional[Path] = None, now: Optional[pd.Timestamp] = None,\n               parts: bool = False) -> Dict[str, Any]:")
s = rep(s, """    png = None
    if rep["structure"] is not None:
        render(rep, dh, dl, out_dir / f"{stem}.png"); png = f"{stem}.png"
    elif rep.get("mode") == "progress" and rep.get("progress"):
        from core.waves.wave_progress import render_progress
        render_progress(rep, dh, d1, dl15, out_dir / f"{stem}.png", dl3=dl); png = f"{stem}.png"
""", """    png = None; part_names = []
    if rep["structure"] is not None:
        render(rep, dh, dl, out_dir / f"{stem}.png"); png = f"{stem}.png"
        if parts:
            part_names = [x.name for x in render(rep, dh, dl, out_dir / f"{stem}.png", parts=True)]
    elif rep.get("mode") == "progress" and rep.get("progress"):
        from core.waves.wave_progress import render_progress
        render_progress(rep, dh, d1, dl15, out_dir / f"{stem}.png", dl3=dl); png = f"{stem}.png"
        if parts:
            part_names = [x.name for x in render_progress(rep, dh, d1, dl15, out_dir / f"{stem}.png", dl3=dl, parts=True)]
""")
s = rep(s, """            "state": state,""", """            "state": state, "parts": part_names, "now": rep.get("now"),""")
s = rep(s, """            "scenarios": [{"name": sc["name"], "targets": [(n, (float(v) if v == v else None)) for n, v in sc["targets"]], "invalid": sc["invalid"]} for sc in rep["scenarios"]]}""",
        """            "scenarios": [{"name": sc["name"], "side": sc.get("side"), "why": sc.get("why"), "fork": sc.get("fork"),
                           "targets": [(n, (float(v) if v == v else None)) for n, v in sc["targets"]], "invalid": sc["invalid"]} for sc in rep["scenarios"]]}""")
if "from typing import" in s and "List" not in s.split("from typing import", 1)[1].split("\n", 1)[0]:
    s = s.replace("from typing import ", "from typing import List, ", 1)
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

# ── wave_progress.render_progress: тот же режим parts
p = "core/waves/wave_progress.py"; s = open(p, encoding="utf-8").read()
s = rep(s, """                    dl3: Optional[pd.DataFrame] = None) -> Path:""", """                    dl3: Optional[pd.DataFrame] = None, parts: bool = False):""")
s = rep(s, """ax.set_title(t_, color=FG, fontsize=9.5, loc="left")""", """ax.set_title((f"{rep['sym']} · " if parts else "") + t_, color=FG, fontsize=9.5, loc="left")""")
s = rep(s, "FIG_W, fit_y, time_axis, draw_micro", "FIG_W, fit_y, time_axis, draw_micro, PART_W, PART_H, save_parts")
s = rep(s, """    fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[.9, 1.3, .85], hspace=.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
""", """    if parts:
        figs = [plt.figure(figsize=(PART_W, PART_H), facecolor=BG) for _ in range(3)]
        axes = [f_.add_axes([0.085, 0.1, 0.88, 0.8]) for f_ in figs]
    else:
        fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
        gs = fig.add_gridspec(3, 1, height_ratios=[.9, 1.3, .85], hspace=.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
        axes = [fig.add_subplot(gs[i]) for i in range(3)]
""")
s = rep(s, "    ax1 = fig.add_subplot(gs[0]); dd = to_daily(dh)", "    ax1 = axes[0]; dd = to_daily(dh)")
s = rep(s, "    ax2 = fig.add_subplot(gs[1])\n", "    ax2 = axes[1]\n")
s = rep(s, """    ax3 = fig.add_subplot(gs[2]); tri = rep.get("triangle")""", """    ax3 = axes[2]; tri = rep.get("triangle")""")
s = rep(s, SAVE, SAVE_NEW)
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

# ── тень: разбор с частями для TG
p = "scripts/wave5_shadow.py"; s = open(p, encoding="utf-8").read()
s = rep(s, """            r = report_for(prev["sym"], "3m", ROOT / "data" / "wave_analyst", now=NOW)""",
        """            r = report_for(prev["sym"], "3m", ROOT / "data" / "wave_analyst", now=NOW, parts=True)""")
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
