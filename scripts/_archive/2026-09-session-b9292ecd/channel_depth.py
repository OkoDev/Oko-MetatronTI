"""Канал Эллиотта: базовая линия 2-4 + параллель через точку 3. Глубина точки 5 в канале
depth5 = (линия24(x5) − p5) / ширина канала (по направлению импульса). 1.0 = волна 5 у параллели (канон),
~0 = у базовой линии (усечение / ошибка разметки: ARKM 0.37, DOGE 0.30, ROSE 0.17; HBAR 0.99).
Считается из готовой разметки в pkl, перепрогон не нужен. Плюс w5/w1."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import block

SP = "C:/Users/yogoru/AppData/Local/Temp/claude/e--MTF-BOT-CURSOR-crypto-volume-bot/b9292ecd-40bf-480f-b583-11c47310bf19/scratchpad/"
pd.set_option("display.width", 220)


def add_geom(d):
    dep, w51, w5t, w5w3 = [], [], [], []
    for _, r in d.iterrows():
        xi = [float(v) for v in r.wave_idx]; px = [float(v) for v in r.wave_px]
        sgn = 1.0 if r.dir == "up" else -1.0
        slope = (px[4] - px[2]) / (xi[4] - xi[2]) if xi[4] > xi[2] else 0.0
        l3 = px[2] + slope * (xi[3] - xi[2]); width = sgn * (px[3] - l3)        # ширина канала у точки 3
        l5 = px[4] + slope * (xi[5] - xi[4]); depth = sgn * (px[5] - l5)        # выход точки 5 за базовую линию
        dep.append(depth / width if width > 0 else np.nan)
        w1 = abs(px[1] - px[0]); w3 = abs(px[3] - px[2]); w5 = abs(px[5] - px[4])
        w51.append(w5 / w1 if w1 > 0 else np.nan); w5w3.append(w5 / w3 if w3 > 0 else np.nan)
        w5t.append((xi[5] - xi[4]) / (xi[1] - xi[0]) if xi[1] > xi[0] else np.nan)   # время w5 / время w1
    d = d.copy(); d["depth5"] = dep; d["w5_w1"] = w51; d["w5_w3"] = w5w3; d["t5_t1"] = w5t
    return d


def line(g, label):
    r = block(g, "w4") if len(g) >= 20 else None
    if r is None:
        print(f"{label:<40} n={len(g):4d}  (мало)" + (f" на сд {g.pnl_w4.mean():+5.2f}% дошли {g.hit_w4.mean()*100:4.0f}%" if len(g) else "")); return
    yrs = g.groupby("year").pnl_w4.mean()
    print(f"{label:<40} n={len(g):4d} дошли {r['дошли%']:5.1f}% на сд {r['на сделку%']:+5.2f}% R {(g.pnl_w4/g.sl_pct).mean():+5.2f} "
          f"перевес {r['перевес']:+5.2f} ДИ {r['ДИ']} безтоп10 {r['безтоп10']:+5.2f} монет+ {r['монет+%']:3.0f}% "
          f"стоп {g.sl_pct.median():4.2f}% | " + " ".join(f"{y}:{v:+.2f}" for y, v in yrs.items()))


if __name__ == "__main__":
    for name, tag in (("wave5sm_4h_15m_sw20_z45.pkl", "4h 20/5"), ("wave5sm_4h_15m_sw15_il4_z45.pkl", "4h 15/4")):
        d = pd.read_pickle(SP + name)
        d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
        for c in ("fractal_ok", "line24_break", "w3_ge_w1", "hit_w4"):
            d[c] = d[c].astype(bool)
        d = add_geom(d)
        base = d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1]
        print(f"\n===== {tag}: лонг×gone≤25%×w3≥w1 n={len(base)} · depth5 медиана {base.depth5.median():.2f} · "
              f"w5/w1 медиана {base.w5_w1.median():.2f} · доля depth5<0.5 {(base.depth5 < 0.5).mean()*100:.0f}%")
        print("глубина точки 5 в канале (все лонги базы):")
        for lo, hi in ((-9, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 1.5), (1.5, 99)):
            line(base[(base.depth5 >= lo) & (base.depth5 < hi)], f"  depth5 [{lo:>4},{hi:>4})")
        print("то же с фракталом:")
        fb = base[base.fractal_ok]
        for lo, hi in ((-9, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 1.5), (1.5, 99)):
            line(fb[(fb.depth5 >= lo) & (fb.depth5 < hi)], f"  фрактал+depth5 [{lo:>4},{hi:>4})")
        print("«настоящий пробой» линии 2-4 = пробита И точка 5 была глубоко (depth5≥0.5):")
        line(fb[fb.line24_break & (fb.depth5 >= 0.5)], "  фрактал + пробой глубокой")
        line(fb[fb.line24_break & (fb.depth5 < 0.5)], "  фрактал + «касание» (мелкая)")
        line(fb[~fb.line24_break & (fb.depth5 >= 0.5)], "  фрактал + глубокая, не пробита")
        line(fb[~fb.line24_break & (fb.depth5 < 0.5)], "  фрактал + мелкая, не пробита")
        print("w5/w1 (усечение):")
        for lo, hi in ((0, 0.382), (0.382, 0.618), (0.618, 1.0), (1.0, 1.618), (1.618, 99)):
            line(fb[(fb.w5_w1 >= lo) & (fb.w5_w1 < hi)], f"  фрактал+w5/w1 [{lo:>5},{hi:>5})")
        print("время w5 / время w1:")
        for lo, hi in ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99)):
            line(fb[(fb.t5_t1 >= lo) & (fb.t5_t1 < hi)], f"  фрактал+t5/t1 [{lo:>4},{hi:>4})")
        # корреляция глубины с откатом w4 (крутая линия = мелкая w4?)
        print(f"  corr(depth5, w4_retr) = {base.depth5.corr(base.w4_retr):+.2f} · corr(depth5, line24_break) = "
              f"{base.depth5.corr(base.line24_break.astype(float)):+.2f} · corr(depth5, w5_w1) = {base.depth5.corr(base.w5_w1):+.2f}")
