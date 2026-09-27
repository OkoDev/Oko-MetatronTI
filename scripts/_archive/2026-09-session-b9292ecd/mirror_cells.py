# -*- coding: utf-8 -*-
"""КОМБИНАЦИИ ГИПЕРКУБА → МОМЕНТЫ СМЕНЫ ДВИЖЕНИЯ + ЗЕРКАЛЬНОСТЬ (09.09.2026).

Вопрос Егора: какие ЯЧЕЙКИ (комбинации состояний слоёв) стоят в точках смены движения.

🔑 ЗЕРКАЛЬНОСТЬ как встроенный контроль: если ячейка X предшествует развороту ВВЕРХ,
   её зеркало (все знаки инвертированы) обязано предшествовать развороту ВНИЗ с той же
   силой. Несимметричная находка = артефакт режима, а не структура.

Разворот определяется по ЦЕНЕ объективно: локальный экстремум, до которого был ход
≥K·ATR в одну сторону и после — ≥K·ATR в другую. Для диагностики (какие ячейки стоят
в точках разворота) знание будущего допустимо — торговый вывод из этого не делается.
"""
import os, sys, glob
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, SY = z["T"], z["SY"]
W = [int(x) for x in z["windows"]]; L = T.shape[1]
K = 3.0            # ход в K·ATR с каждой стороны от экстремума
LOOK = 160         # окно поиска экстремума, баров 3m (8 часов)

px = []
for f in sorted(glob.glob(r"C:\oko_history\1m\*.parquet")):
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    r = d1.resample("3min", label="left", closed="left")
    c = pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                      "close": r["close"].last()}).dropna()
    px.append(c.values[2200:])
PX = np.vstack(px)
HI, LO, CL = PX[:, 0], PX[:, 1], PX[:, 2]
assert len(PX) == len(T)
atr = pd.Series((HI - LO) / CL).rolling(200, min_periods=60).mean().values

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)


def mirror(c_):
    """Зеркало ячейки: каждый разряд 0↔2 (▼↔▲), 1 (·) остаётся."""
    out, mul = 0, 1
    for _ in range(L):
        d_ = c_ % 3
        out += (2 - d_ if d_ != 1 else 1) * mul
        mul *= 3; c_ //= 3
    return out


# развороты цены
piv_lo, piv_hi = [], []
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    n = len(m)
    c = CL[m]; a = atr[m]
    for i in range(LOOK, n - LOOK):
        if np.isnan(a[i]) or a[i] <= 0:
            continue
        thr = K * a[i]
        left_max = c[i - LOOK:i].max(); left_min = c[i - LOOK:i].min()
        right_max = c[i + 1:i + LOOK].max(); right_min = c[i + 1:i + LOOK].min()
        if (left_max - c[i]) / c[i] >= thr and (right_max - c[i]) / c[i] >= thr \
                and c[i] == c[max(i - 5, 0):i + 6].min():
            piv_lo.append(int(m[i]))
        if (c[i] - left_min) / c[i] >= thr and (c[i] - right_min) / c[i] >= thr \
                and c[i] == c[max(i - 5, 0):i + 6].max():
            piv_hi.append(int(m[i]))
piv_lo = np.array(piv_lo); piv_hi = np.array(piv_hi)
print(f"развороты: низов {len(piv_lo):,} · верхов {len(piv_hi):,} "
      f"(K={K}·ATR, окно {LOOK*3/60:.0f}ч)\n")

base = np.bincount(code, minlength=3**L).astype(float)
base /= base.sum()
cl_ = np.bincount(code[piv_lo], minlength=3**L).astype(float)
ch_ = np.bincount(code[piv_hi], minlength=3**L).astype(float)
nlo, nhi = cl_.sum(), ch_.sum()


def arr(u):
    s = []
    for _ in range(L):
        s.append({0: "▼", 1: "·", 2: "▲"}[int(u % 3)]); u //= 3
    return "".join(s[::-1])


print("=== ЯЧЕЙКИ В ТОЧКАХ РАЗВОРОТА ВНИЗ→ВВЕРХ (низы) + ИХ ЗЕРКАЛА ===")
print(f"{'ячейка':>9} {'n низов':>8} {'lift низ':>9} | {'зеркало':>9} {'n верхов':>9} "
      f"{'lift верх':>10} | {'зеркальность':>13}")
rows = []
for u in np.argsort(-cl_)[:200]:
    if cl_[u] < 40 or base[u] <= 0:
        continue
    lift_lo = (cl_[u] / nlo) / base[u]
    mu = mirror(int(u))
    lift_hi = (ch_[mu] / nhi) / base[mu] if base[mu] > 0 and nhi > 0 else np.nan
    rows.append((int(u), int(cl_[u]), lift_lo, mu, int(ch_[mu]), lift_hi))
rows.sort(key=lambda r: -r[2])
for u, n_, ll, mu, nm_, lh in rows[:14]:
    sym = "✓" if (lh == lh and ll > 1.3 and lh > 1.3) else (
        "✗" if lh == lh and (ll - 1) * (lh - 1) < 0 else "—")
    print(f"{arr(u):>9} {n_:>8,} {ll:9.2f} | {arr(mu):>9} {nm_:>9,} "
          f"{lh:10.2f} | {sym:>13}")

print("\n=== ЗЕРКАЛЬНОСТЬ В ЦЕЛОМ: корреляция lift(низ) и lift(верх зеркала) ===")
A, B = [], []
for u in range(3**L):
    if base[u] <= 0 or cl_[u] < 20:
        continue
    mu = mirror(u)
    if base[mu] <= 0 or ch_[mu] < 20:
        continue
    A.append((cl_[u] / nlo) / base[u]); B.append((ch_[mu] / nhi) / base[mu])
A, B = np.array(A), np.array(B)
if len(A) > 10:
    print(f"  ячеек в сравнении: {len(A)}")
    print(f"  корреляция Пирсона:  {np.corrcoef(A, B)[0,1]:+.3f}")
    print(f"  корреляция Спирмена: "
          f"{pd.Series(A).corr(pd.Series(B), method='spearman'):+.3f}")
    print(f"  медиана lift низов {np.median(A):.2f} · зеркал {np.median(B):.2f}")
    same = ((A > 1) == (B > 1)).mean()
    print(f"  доля ячеек, где знак lift совпал с зеркалом: {same*100:.1f}% "
          f"(случайно ≈50%)")

print("\n=== СКОЛЬКО НЕЗАВИСИМЫХ СЛОЁВ: энтропия распределения по ячейкам ===")
p = base[base > 0]
H = -(p * np.log2(p)).sum()
print(f"  занято ячеек: {(base>0).sum()} из {3**L}")
print(f"  энтропия распределения: {H:.2f} бит (максимум при 7 независимых слоях: "
      f"{L*np.log2(3):.2f})")
print(f"  эффективных независимых слоёв: {H/np.log2(3):.2f} из {L}")
for li in range(L):
    p1 = np.bincount(T[:, li] + 1, minlength=3) / len(T)
    p1 = p1[p1 > 0]
    print(f"    слой {li} (окно {W[li]:>5}): энтропия {-(p1*np.log2(p1)).sum():.3f} бит")
