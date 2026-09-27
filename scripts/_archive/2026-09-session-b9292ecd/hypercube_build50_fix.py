# -*- coding: utf-8 -*-
"""ПОСТРОЕНИЕ ГИПЕРКУБА (постановка Егора 09.09.2026): построить из данных, потом
исследовать БЕЗ признаков, ища сгустки согласия как уплотнение данных.

Слои — по ОКНАМ детектора (ТФ значения не имеет, доказано сеткой 12×12):
   окно = len × ТФ, len=10 фиксирован, ТФ подобран → 10 · 20 · 50 · 180 · 600 · 2000 · 6600 мин
Состояние слоя — СЫРОЕ, не признак-гипотеза:
   trend (знак структуры) · pos (место цены между Weak Low и Strong High) · slope (σ ATR)

Первый заход обозрим: конфигурация = знаки тренда 7 слоёв → 3^7 = 2187 ячеек.
🔴 КОНТРОЛЬ — циклический сдвиг КАЖДОГО слоя на свою случайную величину: сохраняет
   автокорреляцию внутри слоя, разрывает связь МЕЖДУ слоями. Это и есть «что было бы,
   если бы масштабы не были связаны». Сгусток = частота выше контрольной.
"""
import os, sys, glob, json
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure

SRC = r"C:\oko_history\1m"
OUTDIR = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
          r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19"
          r"\scratchpad")
LEN = 10
# (ТФ в минутах) → окно = ТФ × LEN
TF_LAYERS = [1, 2, 5, 18, 60, 200, 660]
WINDOWS = [t * LEN for t in TF_LAYERS]
BASE_TF = 3                      # на какой сетке собираем моменты
FWD_BARS = {"1h": 20, "4h": 80, "12h": 240, "24h": 480}   # в барах 3m
RNG = np.random.default_rng(20260909)


def resample(d1, tf):
    if tf == 1:
        return d1
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def layer_series(d):
    """Каузальное состояние слоя по его барам: trend ∈ {−1,0,1}, pos ∈ [0,1], slope (σ)."""
    dd = d.reset_index(drop=True)
    st = run_structure(dd, swing_len=LEN, internal_len=max(3, LEN // 3))
    n = len(dd)
    trend = np.zeros(n, np.int8)
    t = 0
    ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
    p = 0
    for b in range(n):
        while p < len(ev) and ev[p].i <= b:
            t = 1 if ev[p].bull else -1
            p += 1
        trend[b] = t
    c = dd["close"].values
    hi = pd.Series(dd["high"]).rolling(LEN * 5, min_periods=LEN).max().values
    lo = pd.Series(dd["low"]).rolling(LEN * 5, min_periods=LEN).min().values
    rng_ = np.where((hi - lo) > 0, hi - lo, np.nan)
    pos = np.clip((c - lo) / rng_, 0, 1)
    tr = pd.Series(dd["high"] - dd["low"]).rolling(LEN * 5, min_periods=LEN).mean().values
    slope = np.where(tr > 0, (c - pd.Series(c).shift(LEN).values) / tr, np.nan)
    return trend, pos, slope


files = sorted(glob.glob(SRC + r"\*.parquet"))
print(f"монет: {len(files)} | слои (окна, мин): {WINDOWS}", flush=True)

T_all, P_all, S_all, F_all, SYM_all = [], [], [], [], []
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        print(f"  {sym}: мало ({len(d1)}), пропуск", flush=True); continue
    base = resample(d1, BASE_TF)
    bidx = base.index.values
    nb = len(base)
    T = np.zeros((nb, len(TF_LAYERS)), np.int8)
    P = np.full((nb, len(TF_LAYERS)), np.nan, np.float32)
    S = np.full((nb, len(TF_LAYERS)), np.nan, np.float32)
    for li, tf in enumerate(TF_LAYERS):
        d = resample(d1, tf)
        tr, po, sl = layer_series(d)
        # 🔴 ИСПРАВЛЕНО 09.09: index — время ОТКРЫТИЯ бара слоя. Бар закрывается через tf.
        # Прежняя строка брала бар, который ещё НЕ ЗАКРЫЛСЯ → заглядывание до tf минут
        # вперёд (на слое 200m это 200 мин при горизонте 240). Берём по времени ЗАКРЫТИЯ.
        close_time = d.index.values + np.timedelta64(tf, "m")
        j = np.searchsorted(close_time, bidx, "right") - 1
        ok = j >= 0
        j2 = np.clip(j, 0, len(d) - 1)
        T[:, li] = np.where(ok, tr[j2], 0)
        P[:, li] = np.where(ok, po[j2], np.nan)
        S[:, li] = np.where(ok, sl[j2], np.nan)
    c = base["close"].values
    F = np.full((nb, len(FWD_BARS)), np.nan, np.float32)
    for k, (nm, sh) in enumerate(FWD_BARS.items()):
        F[:-sh, k] = (c[sh:] - c[:-sh]) / c[:-sh] * 100
    warm = 6600 // BASE_TF                    # прогрев самого длинного окна
    sl_ = slice(warm, nb)
    T_all.append(T[sl_])
    F_all.append(F[sl_]); SYM_all.append(np.full(nb - warm, fi, np.int16))
    print(f"[{fi}/{len(files)}] {sym}: моментов {nb - warm:,}", flush=True)

T = np.vstack(T_all)
F = np.vstack(F_all); SY = np.concatenate(SYM_all)
print(f"\nтензор: {T.shape[0]:,} моментов × {T.shape[1]} слоёв", flush=True)
np.savez_compressed(OUTDIR + r"\hypercube50_fix.npz", T=T, F=F, SY=SY,
                    windows=np.array(WINDOWS), fwd=np.array(list(FWD_BARS)))

# ── КОНФИГУРАЦИИ И СГУСТКИ ──────────────────────────────────────────────
code = np.zeros(len(T), np.int32)
for li in range(T.shape[1]):
    code = code * 3 + (T[:, li] + 1)
uniq, cnt = np.unique(code, return_counts=True)
print(f"занятых ячеек: {len(uniq):,} из {3**len(TF_LAYERS):,}", flush=True)

# контроль: каждый слой циклически сдвинут на свою случайную величину
NCTL = 30
exp = np.zeros(3 ** len(TF_LAYERS), np.float64)
for _ in range(NCTL):
    cc = np.zeros(len(T), np.int32)
    for li in range(T.shape[1]):
        sh = int(RNG.integers(len(T) // 20, len(T) - len(T) // 20))
        cc = cc * 3 + (np.roll(T[:, li], sh) + 1)
    u2, c2 = np.unique(cc, return_counts=True)
    exp[u2] += c2
exp /= NCTL

real = np.zeros(3 ** len(TF_LAYERS), np.float64)
real[uniq] = cnt
mask = (real >= 500) | (exp >= 500)
lift = np.where(exp > 0, real / np.maximum(exp, 1e-9), np.nan)

# форвард по ячейкам
fwd4 = np.full(3 ** len(TF_LAYERS), np.nan)
fwd24 = np.full(3 ** len(TF_LAYERS), np.nan)
order = np.argsort(code)
cs, ce = np.searchsorted(code[order], uniq, "left"), np.searchsorted(code[order], uniq, "right")
for u, a, b in zip(uniq, cs, ce):
    if b - a >= 500:
        fwd4[u] = np.nanmean(F[order[a:b], 1])
        fwd24[u] = np.nanmean(F[order[a:b], 3])


def decode(u):
    s = []
    for _ in range(len(TF_LAYERS)):
        s.append(int(u % 3) - 1); u //= 3
    return s[::-1]


rows = []
for u in np.where(mask)[0]:
    rows.append(dict(code=int(u), trends=decode(int(u)), real=int(real[u]),
                     exp=float(exp[u]), lift=float(lift[u]),
                     share=float(real[u] / len(T) * 100),
                     agree=int(abs(sum(decode(int(u))))),
                     fwd4=float(fwd4[u]) if fwd4[u] == fwd4[u] else None,
                     fwd24=float(fwd24[u]) if fwd24[u] == fwd24[u] else None))
rows.sort(key=lambda r: -r["lift"])
json.dump(dict(n_moments=int(len(T)), windows=WINDOWS, cells=rows),
          open(OUTDIR + r"\hypercube50_fix_cells.json", "w", encoding="utf-8"),
          ensure_ascii=False)

print("\n=== СГУСТКИ: частота выше независимости (lift), n>=500 ===")
print(f"{'конфигурация слоёв':>30} {'реально':>9} {'ожид.':>9} {'lift':>7} "
      f"{'доля':>7} {'+4ч':>8} {'+24ч':>8}")
for r in rows[:18]:
    t = "".join({-1: "▼", 0: "·", 1: "▲"}[x] for x in r["trends"])
    print(f"{t:>30} {r['real']:9,} {r['exp']:9,.0f} {r['lift']:7.2f} "
          f"{r['share']:6.2f}% "
          f"{(f'{r['fwd4']:+.3f}%' if r['fwd4'] is not None else '—'):>8} "
          f"{(f'{r['fwd24']:+.3f}%' if r['fwd24'] is not None else '—'):>8}")

print("\n=== ПРОВАЛЫ: частота НИЖЕ независимости (рынок так почти не бывает) ===")
for r in sorted([x for x in rows if x["exp"] >= 2000], key=lambda r: r["lift"])[:8]:
    t = "".join({-1: "▼", 0: "·", 1: "▲"}[x] for x in r["trends"])
    print(f"{t:>30} {r['real']:9,} {r['exp']:9,.0f} {r['lift']:7.2f}")

print("\n=== СОГЛАСИЕ ПО ГЛУБИНЕ: |сумма знаков| = сколько слоёв в одну сторону ===")
ag = np.abs(T.sum(1))
for k in range(8):
    m = ag == k
    if m.sum() >= 200:
        print(f"  глубина {k}: n={m.sum():>9,} ({m.mean()*100:5.2f}%) | "
              f"+4ч {np.nanmean(F[m, 1]):+.3f}% | +24ч {np.nanmean(F[m, 3]):+.3f}%")
print("\nсохранено: hypercube50_fix.npz + hypercube50_fix_cells.json", flush=True)
