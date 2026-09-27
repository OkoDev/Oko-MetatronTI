"""Срез ядра после ревью: лонг × опоздание ≤25% × w3≥w1 × фрактал × ПРОБОЙ ЛИНИИ 2-4.
Читает готовые pkl 4h 20/5 и 15/4 (после перепрогона 13.09 с line24_break)."""
import sys, pickle, numpy as np, pandas as pd
sys.path.insert(0, ".")
from wave5_sm import block

SP = "C:/Users/yogoru/AppData/Local/Temp/claude/e--MTF-BOT-CURSOR-crypto-volume-bot/b9292ecd-40bf-480f-b583-11c47310bf19/scratchpad/"
pd.set_option("display.width", 220)


def load(name):
    d = pd.read_pickle(SP + name)
    d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "line24_break", "w3_ge_w1", "hit_w4", "med_ok", "reg"):
        d[c] = d[c].astype(bool)
    d["R"] = d.pnl_w4 / d.sl_pct
    return d


def line(g, label):
    if len(g) < 15:
        print(f"{label:<46} n={len(g):4d}  (мало)"); return
    r = block(g, "w4")
    yrs = g.groupby("year").pnl_w4.mean()
    print(f"{label:<46} n={len(g):4d} дошли {r['дошли%']:5.1f}% на сд {r['на сделку%']:+5.2f}% R {g.R.mean():+5.2f} "
          f"перевес {r['перевес']:+5.2f} ДИ {r['ДИ']} безтоп10 {r['безтоп10']:+5.2f} монет+ {r['монет+%']:4.0f}% "
          f"стоп {g.sl_pct.median():4.2f}% | годы " + " ".join(f"{y}:{v:+.2f}" for y, v in yrs.items()))


for name, tag in (("wave5sm_4h_15m_sw20_z45.pkl", "4h 20/5"), ("wave5sm_4h_15m_sw15_il4_z45.pkl", "4h 15/4")):
    d = load(name)
    base = d[(d.dir == "down") & (d.gone <= 0.25) & d.w3_ge_w1]
    print(f"\n===== {tag}: всего {len(d)}, лонг×gone≤25%×w3≥w1 = {len(base)}")
    line(base, "база (лонг, ≤25%, w3≥w1)")
    line(base[base.fractal_ok], "  + фрактал")
    line(base[~base.fractal_ok], "  − фрактал")
    line(base[base.line24_break], "  + линия 2-4 пробита")
    line(base[~base.line24_break], "  − линия не пробита")
    line(base[base.fractal_ok & base.line24_break], "  + фрактал + линия")
    line(base[base.fractal_ok & ~base.line24_break], "  + фрактал − линия")
    line(base[~base.fractal_ok & base.line24_break], "  − фрактал + линия")
    line(base[~base.fractal_ok & ~base.line24_break], "  − фрактал − линия")
    # линия 2-4 как ЗАМЕНА фрактала? и что с опозданием: пробой линии стоит времени → gone растёт?
    print(f"  gone медиана: линия+ {base[base.line24_break].gone.median():.2f} · линия− {base[~base.line24_break].gone.median():.2f} · "
          f"лаг (4h-баров): линия+ {base[base.line24_break].lag_htf_bars.median():.1f} · линия− {base[~base.line24_break].lag_htf_bars.median():.1f}")
    # шорт для честности
    sh = d[(d.dir == "up") & (d.gone <= 0.25) & d.w3_ge_w1]
    line(sh, "ШОРТ база")
    line(sh[sh.fractal_ok & sh.line24_break], "ШОРТ + фрактал + линия")
    # тест случайного отбора для «фрактал+линия»: подвыборки того же размера из базы
    sub = base[base.fractal_ok & base.line24_break]
    if len(sub) >= 15:
        rs = np.random.RandomState(11)
        dif = (base.pnl_w4 - base.ctl_w4).values
        obs = (sub.pnl_w4 - sub.ctl_w4).mean()
        sims = [rs.choice(dif, len(sub), replace=False).mean() for _ in range(3000)]
        print(f"  тест отбора (фрактал+линия, n={len(sub)}): перевес {obs:+.2f}, перцентиль среди случайных подвыборок базы "
              f"{(np.array(sims) < obs).mean()*100:.1f}")
