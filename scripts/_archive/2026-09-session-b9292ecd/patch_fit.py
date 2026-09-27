import ast, os
os.chdir(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
HELP = '''

def fit_y(ax, w: pd.DataFrame, extra=(), pad: float = 0.06) -> None:
    """Ось цены по свечам окна + уровни, лежащие рядом (не дальше ×3 вниз / ×1.5 вверх). Размах > 6 раз — лог-шкала
    (Егор 14.09: после взрывного пампа свечи сплющивались в линию, а расширения ноги растягивали ось)."""
    lo, hi = float(w.low.min()), float(w.high.max())
    vals = [float(v) for v in extra if v is not None and np.isfinite(v) and lo / 3 <= float(v) <= hi * 1.5]
    lo2, hi2 = min([lo] + vals), max([hi] + vals)
    if lo2 > 0 and hi2 / lo2 > 6:
        ax.set_yscale("log"); ax.set_ylim(lo2 / 1.08, hi2 * 1.08)
    else:
        r = (hi2 - lo2) or abs(hi2) * 0.01
        ax.set_ylim(lo2 - r * pad, hi2 + r * pad)
'''
p = "core/waves/wave_analyst.py"; s = open(p, encoding="utf-8").read()
anchor = "\n\n# ─── текстовый блок схемы"
assert anchor in s
s = s.replace(anchor, HELP.rstrip("\n") + anchor, 1)
old = "    ax1.set_xlim(-12, len(w) + 8)\n\n    # 4h: счёт"
assert old in s
s = s.replace(old, '''    ax1.set_xlim(-12, len(w) + 8)
    fit_y(ax1, w, (list(leg["levels"].values()) + list(leg["extensions"].values()) + [st["p5x"]]) if leg else [st["p5x"]])

    # 4h: счёт''')
old = "    ax2.set_xlim(-12, n4 + F + 34)\n"
assert old in s
s = s.replace(old, '''    ax2.set_xlim(-12, n4 + F + 34)
    fit_y(ax2, w4, list(rep["corr"].values()) + [price, lo, hi] + [v[0] for v in (fc.get("A"), fc.get("B")) if v])
''')
old = "        ax3.set_xlim(-25, n3 + 30)\n"
assert old in s
s = s.replace(old, '''        ax3.set_xlim(-25, n3 + 30)
        fit_y(ax3, w3, [st["p5x"]] + ([ls["a_top"], ls["stop_886"]] + list(ls["zone"].values()) if ls.get("A") else []))
''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)

p = "core/waves/wave_progress.py"; s = open(p, encoding="utf-8").read()
s = s.replace("    from core.waves.wave_analyst import build_text_columns, text_height_in, draw_text_columns, FIG_W",
              "    from core.waves.wave_analyst import build_text_columns, text_height_in, draw_text_columns, FIG_W, fit_y")
old = "    ax1.set_xlim(-12, len(w) + 8)\n"
assert old in s
s = s.replace(old, '''    ax1.set_xlim(-12, len(w) + 8)
    fit_y(ax1, w, list(leg["levels"].values()) if leg else [])
''')
old = '''        ys_all = [v for _, v, _ in rep.get("levels", []) if abs(v / pr - 1) <= .2] + list(cnt["px"]) + [pr]
        ax2.set_ylim(min(ys_all) * .97, max(ys_all) * 1.02)'''
assert old in s
s = s.replace(old, '''        fit_y(ax2, w1, [v for _, v, _ in rep.get("levels", []) if abs(v / pr - 1) <= .2] + list(cnt["px"]) + [pr])''')
ast.parse(s); open(p, "w", encoding="utf-8").write(s)
print("ok")
