"""Сводная лестница ядра: каждая проверенная находка добавляется по очереди. Частота / WR / точность."""
import sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
from channel_depth import add_geom, SP
from wave5_sm import block
pd.set_option("display.width", 250)


def load(name):
    d = pd.read_pickle(SP + name); d = d[d.pnl_w4.notna() & d.ctl_w4.notna()].copy()
    for c in ("fractal_ok", "w3_ge_w1", "hit_w4"):
        d[c] = d[c].astype(bool)
    d = add_geom(d); d["R"] = d.pnl_w4 / d.sl_pct
    xi = np.array([[float(v) for v in w] for w in d.wave_idx])
    d["t2"], d["t4"] = xi[:, 2] - xi[:, 1], xi[:, 4] - xi[:, 3]
    d["alt_type"] = ((d.w2_retr > d.w4_retr) & (d.t2 < d.t4)) | ((d.w2_retr < d.w4_retr) & (d.t2 > d.t4))
    d["alt_form"] = ((d.ns2 - d.ns4).abs() >= 2) if "ns2" in d else False
    d["altern"] = d.alt_type | d.alt_form
    if "alt_exists" in d:
        d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
    else:
        d["count_ok"] = True
    return d


def row(g, lbl, yrs):
    if len(g) < 8:
        return {"ступень": lbl, "n": len(g)}
    ep = g.groupby(g.ts.dt.strftime("%Y-%m-%d")).pnl_w4.mean()
    r = block(g, "w4") if len(g) >= 20 else None
    out = {"ступень": lbl, "n": len(g), "сд/год": len(g) / yrs, "дн/год": len(ep) / yrs, "на сд%": g.pnl_w4.mean(), "R": g.R.mean(), "медR": g.R.median(),
           "цель%": g.hit_w4.mean() * 100, "WR%": (g.pnl_w4 > 0).mean() * 100, "безтоп10": g.pnl_w4.sort_values(ascending=False).iloc[int(len(g) * 0.1):].mean(),
           "монет+%": (g.groupby("sym").pnl_w4.sum() > 0).mean() * 100, "дней+%": (ep > 0).mean() * 100, "мед.дня": ep.median(),
           "годы": " ".join(f"{str(y)[2:]}:{x.pnl_w4.mean():+.1f}" for y, x in g.groupby("year")), "стоп%": g.sl_pct.median(),
           "перевес": (r["перевес"] if r else np.nan), "ДИ": (r["ДИ"] if r else "")}
    return out


def ladder(d, side, tag, extra=None):
    b = d[(d.dir == side) & (d.gone <= 0.25) & d.w3_ge_w1]
    yrs = (b.ts.max() - b.ts.min()).days / 365.25
    steps = [("база: 5 волн + WT-зона + w3≥w1 + опоздание ≤25%", b)]
    g = b[b.fractal_ok]; steps.append(("+ фрактал (импульс настоящий)", g))
    g = g[g.depth5 >= 0.5]; steps.append(("+ канал ≥0.5 (импульс завершён)", g))
    g = g[g.altern]; steps.append(("+ чередование (тип или форма)", g))
    g = g[g.count_ok]; steps.append(("+ канонический счёт (не подволны)", g))
    if "d_wt" in d:
        thr = -45 if side == "down" else 45
        gg = g[(g.d_wt < thr) if side == "down" else (g.d_wt > thr)]; steps.append(("+ дневной WT в зоне (фильтр качества)", gg))
    if extra is not None:
        for lbl, m in extra(g): steps.append((lbl, g[m]))
    rows = [row(x, l, yrs) for l, x in steps]
    print(f"\n===== {tag} · {'ЛОНГ' if side == 'down' else 'ШОРТ'} · окно {b.ts.min():%Y-%m} → {b.ts.max():%Y-%m} ({yrs:.1f} г)")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:6.2f}"))
    return steps


for name, tag in (("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", "4h 15/4 → вход 15m по КРОССУ · cap 240 ч"),
                  ("wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl", "4h 15/4 → вход 15m по ЛИНИИ 2-4 · cap 240 ч")):
    d = load(name)
    ladder(d, "down", tag)
# шорт: line24 + дневной контекст (медвежья 1D, дневной high не пробит)
d = load("wave5sm_4h_15m_sw15_il4_hold240_line24_ctx10_z45.pkl")
b = d[(d.dir == "up") & (d.gone <= 0.25) & d.w3_ge_w1 & d.d_bull.notna()]
yrs = (b.ts.max() - b.ts.min()).days / 365.25
steps = [("база шорт", b)]
g = b[b.fractal_ok]; steps.append(("+ фрактал", g))
g = g[(~g.d_bull.astype(bool)) & (~g.d_broke.astype(bool))]; steps.append(("+ дневной слой: медвежья 1D, дневной high не пробит", g))
steps.append(("+ канал ≥0.5", g[g.depth5 >= 0.5])); steps.append(("+ чередование", g[g.altern]))
print(f"\n===== ШОРТ · 4h 15/4 → линия 2-4 · окно {b.ts.min():%Y-%m} → {b.ts.max():%Y-%m}")
print(pd.DataFrame([row(x, l, yrs) for l, x in steps]).to_string(index=False, float_format=lambda x: f"{x:6.2f}"))
# 5m-вход (2025-26): частичная связка (в pkl нет ns/alt)
d5 = load("wave5sm_4h_5m_sw20_hold240_z45.pkl")
b = d5[(d5.dir == "down") & (d5.gone <= 0.25) & d5.w3_ge_w1]; yrs = (b.ts.max() - b.ts.min()).days / 365.25
steps = [("база", b), ("+ фрактал", b[b.fractal_ok]), ("+ канал ≥0.5", b[b.fractal_ok & (b.depth5 >= 0.5)]), ("+ чередование по типу", b[b.fractal_ok & (b.depth5 >= 0.5) & b.alt_type])]
print(f"\n===== 4h 20/5 → вход 5m по кроссу · cap 240 ч · окно {b.ts.min():%Y-%m} → {b.ts.max():%Y-%m} (только тип чередования — в этом файле нет подсвингов)")
print(pd.DataFrame([row(x, l, yrs) for l, x in steps]).to_string(index=False, float_format=lambda x: f"{x:6.2f}"))
