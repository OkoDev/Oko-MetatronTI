# -*- coding: utf-8 -*-
"""КАСКАД: закрываем НЕ проверенное — распределение MAE, симуляция стоп/цель, кластерность.

1. Квантили MAE: какой стоп реально выживает (медиана лжёт, половина случаев хуже).
2. Симуляция сделки: стоп × цель на сетке, косты 0.35%, порядок внутри бара
   консервативный (сначала стоп, потом цель).
3. 🔴 КОНТРОЛЬ: случайный вход той же геометрии, матч по монете и часу суток.
4. 🔴 КЛАСТЕРНОСТЬ: не сидят ли события в нескольких эпизодах на многих монетах разом.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
L = T.shape[1]
COST = 0.35
RNG = np.random.default_rng(20260909)

SRC = r"C:\oko_history\1m"
warm = 6600 // 3
px, tss = [], []
for f in sorted(glob.glob(SRC + r"\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[warm:]); tss.append(c.index.values[warm:])
PX = np.vstack(px); TS = np.concatenate(tss)
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)
ev = []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    for k in np.where(np.diff(code[m]) != 0)[0] + 1:
        ev.append(int(m[k]))
EV = np.array(ev)
Tf, Tt = T[EV - 1], T[EV]


def cascade(k, side):
    m = (Tf[:, k] != Tt[:, k]) & (Tt[:, k] == side) & np.all(Tt[:, :k] == side, axis=1)
    ii = EV[m]
    return ii[(ii > 100) & (ii < len(CL) - 481)]


def mae_mfe(ii, side, hold):
    out = []
    for i in ii:
        e = CL[i]
        h = HI[i + 1:i + 1 + hold]; l = LO[i + 1:i + 1 + hold]
        if side == 1:
            out.append(((l.min() - e) / e * 100, (h.max() - e) / e * 100))
        else:
            out.append(((e - h.max()) / e * 100, (e - l.min()) / e * 100))
    return np.array(out)


print("=== 1. РАСПРЕДЕЛЕНИЕ ПРОСАДКИ (MAE) ЗА 4 ЧАСА ===")
print(f"{'слой':>5} {'сторона':>7} {'n':>6}  " +
      "  ".join(f"{q:>6}" for q in ["p25", "p50", "p75", "p90", "p95"]))
for k in (3, 4):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        ii = cascade(k, side)
        if len(ii) < 100:
            continue
        mm = mae_mfe(ii, side, 80)
        q = np.percentile(-mm[:, 0], [25, 50, 75, 90, 95])
        print(f"{k:>5} {nm:>7} {len(ii):>6,}  " + "  ".join(f"{v:5.2f}%" for v in q))
print("  → стоп должен быть шире p50, иначе выбивает половину; p75/p90 = цена вопроса")


def sim(ii, side, stop, tgt, hold):
    """Консервативно: если бар задел и стоп, и цель — считаем стоп."""
    r = []
    for i in ii:
        e = CL[i]
        sl = e * (1 - side * stop / 100)
        tp = e * (1 + side * tgt / 100)
        hit = None
        for j in range(i + 1, min(i + 1 + hold, len(CL))):
            lo, hi = LO[j], HI[j]
            if side == 1:
                if lo <= sl: hit = -stop; break
                if hi >= tp: hit = tgt; break
            else:
                if hi >= sl: hit = -stop; break
                if lo <= tp: hit = tgt; break
        if hit is None:
            j = min(i + hold, len(CL) - 1)
            hit = (CL[j] - e) / e * 100 * side
        r.append(hit - COST)
    return np.array(r)


print("\n=== 2. СИМУЛЯЦИЯ СДЕЛКИ · косты 0.35% · удержание 4ч ===")
print(f"{'слой':>4} {'стор':>5} {'стоп':>5} {'цель':>5} {'n':>6} {'ср%':>8} {'мед%':>8} "
      f"{'WR':>6} {'PF':>6} {'без топ10%':>11}")
best = {}
for k in (3, 4):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        ii = cascade(k, side)
        if len(ii) < 100:
            continue
        for stop in (0.6, 1.0, 1.5):
            for tgt in (1.0, 1.5, 2.5):
                r = sim(ii, side, stop, tgt, 80)
                pf = r[r > 0].sum() / abs(r[r < 0].sum()) if (r < 0).any() else np.inf
                srt = np.sort(r)[::-1]; cut = int(len(srt) * .1)
                frag = srt[cut:].mean()
                print(f"{k:>4} {nm:>5} {stop:5.1f} {tgt:5.1f} {len(r):>6,} {r.mean():+7.3f}% "
                      f"{np.median(r):+7.3f}% {(r > 0).mean()*100:5.1f}% {pf:6.2f} "
                      f"{frag:+10.3f}%")
                if (k, side) not in best or r.mean() > best[(k, side)][0]:
                    best[(k, side)] = (r.mean(), stop, tgt, ii)

print("\n=== 3. КОНТРОЛЬ: случайный вход той же геометрии (тот же символ, тот же час) ===")
print(f"{'слой':>4} {'стор':>5} {'стоп':>5} {'цель':>5} {'каскад':>9} {'контроль':>10} "
      f"{'разница':>9}")
for (k, side), (mn, stop, tgt, ii) in sorted(best.items()):
    nm = "лонг" if side == 1 else "шорт"
    hrs = pd.to_datetime(TS[ii]).hour.values
    ctl_means = []
    for _ in range(5):
        pick = []
        for i, h in zip(ii, hrs):
            s = SY[i]
            cand = np.where((SY == s) & (pd.to_datetime(TS).hour.values == h))[0]
            cand = cand[(cand > 100) & (cand < len(CL) - 481)]
            if len(cand):
                pick.append(int(RNG.choice(cand)))
        ctl_means.append(sim(np.array(pick), side, stop, tgt, 80).mean())
    c = float(np.mean(ctl_means))
    print(f"{k:>4} {nm:>5} {stop:5.1f} {tgt:5.1f} {mn:+8.3f}% {c:+9.3f}% {mn - c:+8.3f}%")

print("\n=== 4. КЛАСТЕРНОСТЬ: сидят ли события в нескольких эпизодах ===")
for k in (3, 4):
    for side, nm in [(1, "лонг"), (-1, "шорт")]:
        ii = cascade(k, side)
        if len(ii) < 100:
            continue
        days = pd.to_datetime(TS[ii]).normalize()
        vc = pd.Series(days).value_counts()
        top10 = vc.head(max(1, len(vc) // 10)).sum() / len(ii) * 100
        syms = SY[ii]
        sv = pd.Series(syms).value_counts()
        print(f"  слой {k} {nm:>5}: n={len(ii):>5,} | дней {len(vc):>4} | "
              f"верхние 10% дней держат {top10:5.1f}% событий | "
              f"монет {len(sv)} | максимум на монету {sv.iloc[0]/len(ii)*100:.0f}%")
