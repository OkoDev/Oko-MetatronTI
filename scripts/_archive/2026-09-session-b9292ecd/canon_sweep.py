# -*- coding: utf-8 -*-
"""ПЕРЕБОР КАНОНА ЭЛЛИОТТА КАК ФЛАГОВ (13.09, Егор: «перебирай все варианты по теории»).

На 888 входах двухслойного детектора (wave5sm_4h_15m_sw20_z45.pkl) считаем КАНОНИЧЕСКИЕ признаки
из obsidian/Concepts/Elliott-Wave-Labeling.md (§3-§8) и проверяем каждый:
  · один, поверх базы (опоздание ≤25% + фрактал), тест случайного отбора внутри базы;
  · комбинации канонических правил (не по результату, а по теории).
Все пропорции считаются из wave_px (6 точек), время — из wave_idx (в HTF-барах).
"""
import sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = Path(__file__).parent
d = pd.read_pickle(D / "wave5sm_4h_15m_sw20_z45.pkl")
PN, CT, HT = "pnl_w4", "ctl_w4", "hit_w4"
d = d[d[PN].notna() & d[CT].notna()].copy()
d["fr"] = d.fractal_ok.astype(bool); d["hit"] = d[HT].astype(bool)

# ── пропорции из точек
px = np.array(d.wave_px.tolist(), dtype=float); ix = np.array(d.wave_idx.tolist(), dtype=float)
L = np.abs(np.diff(px, axis=1))                 # длины волн 1..5 (в цене)
T = np.diff(ix, axis=1)                         # длительности волн 1..5 (в HTF-барах)
w1, w2, w3, w4, w5 = L.T
t1, t2, t3, t4, t5 = T.T
d["w3_ge_w1"] = w3 >= w1
d["w3_ext_1618"] = w3 >= 1.618 * w1
d["w2_zigzag"] = (d.w2_retr >= 0.5) & (d.w2_retr <= 0.886)          # резкая глубокая вторая
d["w4_shallow"] = (d.w4_retr >= 0.236) & (d.w4_retr <= 0.5)         # мелкая четвёртая
d["alternation"] = d.w2_retr > d.w4_retr                            # чередование: 2 глубже 4
d["w5_eq_w1"] = np.abs(w5 / np.where(w1 > 0, w1, np.nan) - 1) <= 0.25   # w5 ≈ w1 (±25%)
d["w5_618_13"] = np.abs(w5 / np.where(w1 + w3 > 0, 0.618 * (w1 + w3), np.nan) - 1) <= 0.25
d["w5_truncated"] = w5 < 0.382 * w3                                 # усечённая пятая
d["w5_shorter_w3"] = w5 < w3
d["w3_longest"] = (w3 > w1) & (w3 > w5)
d["w3_ext_only"] = d.w3_ext_1618 & d.w5_eq_w1                      # расширенная 3 → 1≈5
d["t2_gt_t4"] = t2 > t4                                             # чередование по времени
d["t3_longest"] = (t3 >= t1) & (t3 >= t5)
d["t5_short"] = t5 < t3                                             # пятая быстрее третьей
d["fib_time_35"] = np.abs(t5 / np.where(t3 > 0, t3, np.nan) - 0.618) <= 0.2   # время 5 ≈ 0.618 времени 3
d["reg_b"] = d.reg.astype(bool); d["vol_b"] = d.vol_w5_weak.astype(bool); d["med_b"] = d.med_ok.astype(bool)
d["long"] = d.dir == "down"

base = d[(d.gone <= 0.25) & d.fr].copy()
rs = np.random.RandomState(20260912)
print(f"БАЗА: опоздание ≤25% + фрактал → n={len(base)} · {base[PN].mean():+.2f}%/сд · дошли {base.hit.mean()*100:.0f}%\n")

FLAGS = ["w3_ge_w1", "w3_ext_1618", "w3_longest", "w2_zigzag", "w4_shallow", "alternation",
         "w5_eq_w1", "w5_618_13", "w5_truncated", "w5_shorter_w3", "w3_ext_only",
         "t2_gt_t4", "t3_longest", "t5_short", "fib_time_35", "reg_b", "vol_b", "med_b", "long"]


def stat(g, pool):
    if len(g) < 25:
        return None
    keep = g[PN].sort_values(ascending=False).iloc[int(len(g) * 0.1):]
    ep = g.assign(_e=g.sym + "_" + g.ts.dt.strftime("%Y%m")).groupby("_e")[PN].mean()
    bs = [ep.sample(len(ep), replace=True, random_state=rs.randint(1e6)).mean() for _ in range(1500)]
    rnd = [pool[PN].sample(len(g), replace=False, random_state=rs.randint(1e6)).mean() for _ in range(2000)]
    yr = g.groupby(g.ts.dt.year)[PN].mean()
    return dict(n=len(g), доля=len(g) / len(pool) * 100, сд=g[PN].mean(), дошли=g.hit.mean() * 100,
                мед=g[PN].median(), ДИ_низ=np.percentile(bs, 2.5), отбор=(np.array(rnd) < g[PN].mean()).mean() * 100,
                безтоп10=keep.mean(), монет=(g.groupby("sym")[PN].sum() > 0).mean() * 100,
                годы=f"{(yr > 0).sum()}/{len(yr)}")


rows = []
for f in FLAGS:
    r = stat(base[base[f]], base)
    if r:
        r_no = base[~base[f]][PN].mean() if (~base[f]).sum() > 10 else np.nan
        rows.append({"флаг": f, **r, "без_флага": r_no})
t = pd.DataFrame(rows).sort_values("отбор", ascending=False)
print("=== КАЖДЫЙ ФЛАГ ПОВЕРХ БАЗЫ (тест отбора внутри базы; порог Бонферрони для 19 флагов 99.7%)")
print(t.to_string(index=False, float_format=lambda x: f"{x:7.2f}"))

print("\n=== КАНОНИЧЕСКИЕ СВЯЗКИ (по теории, не по результату)")
COMBOS = {
    "w3≥w1 + чередование": base.w3_ge_w1 & base.alternation,
    "w3≥w1 + w2 zigzag + w4 мелкая": base.w3_ge_w1 & base.w2_zigzag & base.w4_shallow,
    "расширенная 3 (≥1.618) + 5≈1": base.w3_ext_only,
    "w3≥w1 + усечённая 5": base.w3_ge_w1 & base.w5_truncated,
    "w3≥w1 + дивергенция": base.w3_ge_w1 & base.reg_b,
    "w3≥w1 + объём 5<3": base.w3_ge_w1 & base.vol_b,
    "w3≥w1 + время 5<3": base.w3_ge_w1 & base.t5_short,
    "w3≥w1 + медиана": base.w3_ge_w1 & base.med_b,
    "w3≥w1 + лонг": base.w3_ge_w1 & base.long,
    "w3≥w1 + лонг + чередование": base.w3_ge_w1 & base.long & base.alternation,
    "w3≥w1 + лонг + дивергенция": base.w3_ge_w1 & base.long & base.reg_b,
    "полный канон: w3≥w1+черед+5<3+объём": base.w3_ge_w1 & base.alternation & base.w5_shorter_w3 & base.vol_b,
}
rows = []
for name, m in COMBOS.items():
    r = stat(base[m], base)
    if r:
        rows.append({"связка": name, **r})
    else:
        rows.append({"связка": name, "n": int(m.sum())})
print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:7.2f}"))
