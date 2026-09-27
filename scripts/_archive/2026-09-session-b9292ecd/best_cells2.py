# -*- coding: utf-8 -*-
"""ОТБОР ЯЧЕЕК НА 24ч: зеркальность, стороны, устойчивость порога (09.09.2026).

Порог 70% дал на OOS +0.579% и WR 58.3%. Проверяем главное подозрение: не медвежий
ли это режим. Если отбор почти весь ушёл в short — это период, а не структура.
"""
import os, sys
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
L = T.shape[1]
HJ = 3          # 24 часа
COSTS = [0.35, 0.15, 0.06]

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
uniq, cinv = np.unique(code, return_inverse=True)
half = np.zeros(len(T), np.int8)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    half[m[len(m) // 2:]] = 1
y = F[:, HJ]; ok = ~np.isnan(y)


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


def mirror_code(u):
    out, mul = 0, 1
    for _ in range(L):
        d_ = u % 3
        out += (2 - d_ if d_ != 1 else 1) * mul
        mul *= 3; u //= 3
    return out


stats = {}
for ci in range(len(uniq)):
    m_is = (cinv == ci) & ok & (half == 0)
    if m_is.sum() >= 400:
        stats[ci] = float(np.nanmean(y[m_is]))
keys = np.array(list(stats)); vals = np.array([stats[k] for k in keys])
print(f"ячеек с n_IS≥400: {len(keys)}\n")

print("=== БАЗОВЫЙ ДРЕЙФ ОКНА (весь рынок, без отбора) ===")
print(f"  средний ход за 24ч по ВСЕМ барам: IS {np.nanmean(y[ok & (half==0)]):+.4f}% · "
      f"OOS {np.nanmean(y[ok & (half==1)]):+.4f}%")
print(f"  доля баров с положительным ходом: IS "
      f"{(y[ok & (half==0)]>0).mean()*100:.1f}% · OOS {(y[ok & (half==1)]>0).mean()*100:.1f}%")

for q in [70, 80, 90]:
    thr = np.percentile(np.abs(vals), q)
    sel_hi = keys[vals >= thr]; sel_lo = keys[vals <= -thr]
    print(f"\n=== ПОРОГ {q}% (|сдвиг| ≥ {thr:.3f}%) · ячеек long {len(sel_hi)} · "
          f"short {len(sel_lo)} ===")
    for nm, sel, sgn in [("LONG", sel_hi, 1), ("SHORT", sel_lo, -1)]:
        if len(sel) == 0:
            print(f"  {nm}: ячеек нет"); continue
        mask = np.isin(cinv, sel)
        m_o = mask & ok & (half == 1)
        m_i = mask & ok & (half == 0)
        if m_o.sum() < 500:
            print(f"  {nm}: OOS сделок {m_o.sum()} — мало"); continue
        vo = y[m_o] * sgn; vi = y[m_i] * sgn
        per = []
        for s in np.unique(SY[m_o]):
            mm = m_o & (SY == s)
            if mm.sum() > 30:
                per.append(np.nanmean(y[mm] * sgn))
        nets = " ".join(f"{vo.mean()-c:+8.4f}" for c in COSTS)
        print(f"  {nm:>5}: ячеек {len(sel):>3} · IS {vi.mean():+7.4f}% ({m_i.sum():>7,}) · "
              f"OOS {vo.mean():+7.4f}% ({m_o.sum():>7,}) · WR {(vo>0).mean()*100:5.1f}% · "
              f"нетто {nets} · монет {sum(1 for x in per if x>0)}/{len(per)}")
    # зеркальность отобранных
    mirr = 0
    for ci in sel_hi:
        mc = mirror_code(int(uniq[ci]))
        w = np.where(uniq == mc)[0]
        if len(w) and w[0] in set(sel_lo.tolist()):
            mirr += 1
    print(f"  зеркальных пар среди отобранных: {mirr} из {min(len(sel_hi), len(sel_lo))}")
