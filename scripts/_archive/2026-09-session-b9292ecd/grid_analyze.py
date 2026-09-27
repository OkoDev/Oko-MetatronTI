# -*- coding: utf-8 -*-
"""Разбор сетки вложенности. Задача — РАЗДЕЛИТЬ гипотезы, а не подтвердить одну.

H1 (окно):  совпадение = f(R), R = окно_hi/окно_lo. От отношения ТФ не зависит.
H0 (ТФ):    совпадение = f(ТФ_hi/ТФ_lo). Окна ни при чём.
Решающий срез: пары с R≈1 при РАЗНОМ отношении ТФ. Если H1 верна — совпадение там
одинаковое; если H0 — оно поедет вслед за отношением ТФ.

Везде считаем lift = real − ctl (контроль = те же свинги, сдвинутые на 37 баров).
Без вычета контроля цифры бессмысленны: свинги младшего ТФ плотные.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

P = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19"
     r"\scratchpad\grid_nest.pkl")
df = pd.read_pickle(P)
df = df.dropna(subset=["real", "ctl"])
df["lift"] = df["real"] - df["ctl"]
print(f"пар: {len(df):,} | монет: {df.sym.nunique()} | "
      f"ТФ: {sorted(df.tfh.unique())}\n")

# --- 1. Зависимость от R (отношение ОКОН) ---
bins = [0.25, 0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1, 2.6, 3.2, 4.0]
df["Rb"] = pd.cut(df.R, bins)
g = df.groupby("Rb", observed=True).agg(real=("real", "mean"), ctl=("ctl", "mean"),
                                        lift=("lift", "mean"), n=("real", "size"))
print("=== 1. СОВПАДЕНИЕ ПО ОТНОШЕНИЮ ОКОН R = окно_hi/окно_lo ===")
print(f"{'R':>14} {'real':>7} {'контроль':>9} {'lift':>7} {'пар':>7}")
for k, r in g.iterrows():
    print(f"{str(k):>14} {r.real*100:6.1f}% {r.ctl*100:8.1f}% {r.lift*100:6.1f}% {int(r.n):7,}")

# --- 2. Зависимость от отношения ТФ ---
df["tfrb"] = pd.cut(df.tfr, [1, 1.6, 2.5, 3.5, 5, 7, 10, 14, 20, 30, 200])
g2 = df.groupby("tfrb", observed=True).agg(real=("real", "mean"), ctl=("ctl", "mean"),
                                           lift=("lift", "mean"), n=("real", "size"))
print("\n=== 2. СОВПАДЕНИЕ ПО ОТНОШЕНИЮ ТФ ===")
print(f"{'ТФ_hi/ТФ_lo':>14} {'real':>7} {'контроль':>9} {'lift':>7} {'пар':>7}")
for k, r in g2.iterrows():
    print(f"{str(k):>14} {r.real*100:6.1f}% {r.ctl*100:8.1f}% {r.lift*100:6.1f}% {int(r.n):7,}")

# --- 3. РЕШАЮЩИЙ ТЕСТ: при R≈1 меняем отношение ТФ ---
near = df[(df.R >= 0.85) & (df.R <= 1.2)]
print(f"\n=== 3. РЕШАЮЩИЙ: R≈1 (0.85-1.2), n={len(near):,} — едет ли за отношением ТФ? ===")
g3 = near.groupby("tfrb", observed=True).agg(real=("real", "mean"), lift=("lift", "mean"),
                                             n=("real", "size"))
print(f"{'ТФ_hi/ТФ_lo':>14} {'real':>7} {'lift':>7} {'пар':>7}")
for k, r in g3.iterrows():
    if r.n >= 30:
        print(f"{str(k):>14} {r.real*100:6.1f}% {r.lift*100:6.1f}% {int(r.n):7,}")
if len(g3[g3.n >= 30]) >= 2:
    v = g3[g3.n >= 30]["real"]
    print(f"  разброс real при R≈1: {v.min()*100:.1f}%…{v.max()*100:.1f}% "
          f"(размах {(v.max()-v.min())*100:.1f} п.п.)")

# --- 4. Зеркальный: при фикс. отношении ТФ меняем R ---
print("\n=== 4. ЗЕРКАЛЬНЫЙ: отношение ТФ 3-5×, меняем R ===")
fix = df[(df.tfr >= 3) & (df.tfr <= 5)]
g4 = fix.groupby("Rb", observed=True).agg(real=("real", "mean"), lift=("lift", "mean"),
                                          n=("real", "size"))
for k, r in g4.iterrows():
    if r.n >= 30:
        print(f"{str(k):>14} {r.real*100:6.1f}% {r.lift*100:6.1f}% {int(r.n):7,}")

# --- 5. Лучшие конкретные пары слоёв (усреднение по монетам) ---
print("\n=== 5. ЛУЧШИЕ ПАРЫ СЛОЁВ (lift, ≥8 монет) ===")
k = (df.groupby(["tfh", "Lh", "tfl", "Ll"])
       .agg(real=("real", "mean"), ctl=("ctl", "mean"), lift=("lift", "mean"),
            R=("R", "first"), tfr=("tfr", "first"), m=("sym", "nunique"))
       .reset_index())
k = k[k.m >= 8].sort_values("lift", ascending=False)
print(f"{'старший':>12} {'младший':>12} {'окна':>13} {'R':>5} {'ТФ×':>5} "
      f"{'real':>7} {'ctl':>6} {'lift':>7}")
for _, r in k.head(25).iterrows():
    print(f"{int(r.tfh):>6}m×{int(r.Lh):<5} {int(r.tfl):>6}m×{int(r.Ll):<5} "
          f"{int(r.tfh*r.Lh):>6}/{int(r.tfl*r.Ll):<6} {r.R:5.2f} {r.tfr:5.1f} "
          f"{r.real*100:6.1f}% {r.ctl*100:5.1f}% {r.lift*100:6.1f}%")

# --- 6. Нестандартные ТФ: есть ли они среди лучших ---
STD = {5, 15, 60, 240}
k["nonstd"] = (~k.tfh.isin(STD)) | (~k.tfl.isin(STD))
print("\n=== 6. НЕСТАНДАРТНЫЕ ТФ среди лучших ===")
top = k.head(50)
print(f"  в топ-50 пар с нестандартным ТФ: {int(top.nonstd.sum())} из 50")
best_ns = k[k.nonstd].head(10)
for _, r in best_ns.iterrows():
    print(f"  {int(r.tfh):>4}m×{int(r.Lh):<3} → {int(r.tfl):>4}m×{int(r.Ll):<3} "
          f"| окна {int(r.tfh*r.Lh)}/{int(r.tfl*r.Ll)} | R={r.R:.2f} "
          f"| lift {r.lift*100:.1f}%")

# --- 7. Корреляции: что объясняет lift лучше ---
print("\n=== 7. ЧТО ОБЪЯСНЯЕТ LIFT ===")
d = df.copy()
d["lnR"] = np.log(d.R).abs()          # близость к R=1
d["lntfr"] = np.log(d.tfr)
for c, name in [("lnR", "|ln R| (близость окон)"), ("lntfr", "ln(ТФ_hi/ТФ_lo)")]:
    print(f"  corr(lift, {name:<26}) = {d['lift'].corr(d[c]):+.3f}")
