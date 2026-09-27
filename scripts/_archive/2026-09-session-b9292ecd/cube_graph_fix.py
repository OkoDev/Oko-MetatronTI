# -*- coding: utf-8 -*-
"""ГРАФ ПЕРЕХОДОВ ГИПЕРКУБА (Егор, 09.09.2026): куда рынок уходит из каждого сгустка.

Плотность говорит «где система бывает», граф — «куда пойдёт». Второе и есть предсказание.

Протокол:
  1. Сжать поток моментов в цепочку СОСТОЯНИЙ (run-length): узел + длительность.
     Иначе 99% «переходов» — это «остался на месте», и статистика ни о чём.
  2. Энтропия выхода H(next|cur) против H(next) — сколько бит даёт знание текущей ячейки.
  3. 🔴 Контроль: перемешать последовательность переходов внутри монеты — сохраняет
     маргинальные частоты, разрушает порядок. Информация выше контрольной = реальная.
  4. 🔴 Слепая проверка: переходы отбираются на ПЕРВОЙ половине истории (IS),
     проверяются на ВТОРОЙ (OOS). Открывается один раз.
  5. Форвард считается ПОСЛЕ перехода — то есть решение принимается по уже
     состоявшемуся событию, без заглядывания.
"""
import os, sys, json
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
z = np.load(D + r"\hypercube50_fix.npz", allow_pickle=True)
T, F, SY = z["T"], z["F"], z["SY"]
W = list(z["windows"]); L = T.shape[1]
RNG = np.random.default_rng(20260909)
ARROW = {-1: "▼", 0: "·", 1: "▲"}

code = np.zeros(len(T), np.int32)
for i in range(L):
    code = code * 3 + (T[:, i] + 1)


def dec(u):
    s = []
    for _ in range(L):
        s.append(int(u % 3) - 1); u //= 3
    return s[::-1]


def arr(u):
    return "".join(ARROW[x] for x in dec(u))


# ── 1. цепочка состояний, по монетам ───────────────────────────────────
trans = []          # (from, to, dwell_баров, idx_перехода, sym, half)
for s in np.unique(SY):
    m = np.where(SY == s)[0]
    c = code[m]
    ch = np.where(np.diff(c) != 0)[0] + 1          # индексы смены состояния
    if len(ch) < 10:
        continue
    starts = np.concatenate([[0], ch])
    half_cut = len(c) // 2
    for k in range(1, len(starts)):
        i0, i1 = starts[k - 1], starts[k]
        trans.append((int(c[i0]), int(c[i1]), int(i1 - i0), int(m[i1]),
                      int(s), 0 if i1 < half_cut else 1))

TR = np.array(trans, dtype=np.int64)
print(f"переходов: {len(TR):,} | узлов посещено: {len(np.unique(TR[:, 0])):,}")
print(f"медианная длительность состояния: {np.median(TR[:, 2]):.0f} баров 3m "
      f"({np.median(TR[:, 2])*3/60:.1f} ч)")

# сколько слоёв меняется за один переход
hd = np.array([sum(a != b for a, b in zip(dec(f), dec(t))) for f, t in TR[:2000, :2]])
print(f"слоёв меняется за переход (первые 2000): "
      + " ".join(f"{k}:{(hd == k).mean()*100:.0f}%" for k in range(1, 5)))


# ── 2. энтропия выхода ─────────────────────────────────────────────────
def entropy_stats(fr, to):
    uf, inv = np.unique(fr, return_inverse=True)
    ut, tinv = np.unique(to, return_inverse=True)
    # H(next)
    p = np.bincount(tinv) / len(tinv)
    Hn = -(p[p > 0] * np.log2(p[p > 0])).sum()
    # H(next|cur)
    Hc = 0.0
    for k in range(len(uf)):
        m = inv == k
        if m.sum() < 30:
            continue
        q = np.bincount(tinv[m]) / m.sum()
        q = q[q > 0]
        Hc += m.mean() * (-(q * np.log2(q)).sum())
    return Hn, Hc


Hn, Hc = entropy_stats(TR[:, 0], TR[:, 1])
print(f"\n=== ПРЕДСКАЗУЕМОСТЬ ВЫХОДА ===")
print(f"  H(следующее)          = {Hn:.3f} бит")
print(f"  H(следующее | текущее)= {Hc:.3f} бит")
print(f"  информация            = {Hn - Hc:.3f} бит ({(Hn-Hc)/Hn*100:.1f}% энтропии)")

ctlI = []
for _ in range(20):
    sh = TR[:, 1].copy()
    for s in np.unique(TR[:, 4]):
        m = TR[:, 4] == s
        v = sh[m]; RNG.shuffle(v); sh[m] = v
    a, b = entropy_stats(TR[:, 0], sh)
    ctlI.append(a - b)
print(f"  контроль (перемешан порядок): {np.mean(ctlI):.3f} ± {np.std(ctlI):.3f} бит")
print(f"  🔑 сверх контроля: {(Hn - Hc) - np.mean(ctlI):+.3f} бит")

# ── 3. детерминированные рёбра ─────────────────────────────────────────
print(f"\n=== САМЫЕ ДЕТЕРМИНИРОВАННЫЕ ВЫХОДЫ (n>=300) ===")
uf = np.unique(TR[:, 0])
rows = []
for f in uf:
    m = TR[:, 0] == f
    if m.sum() < 300:
        continue
    tos, cnts = np.unique(TR[m, 1], return_counts=True)
    j = np.argmax(cnts)
    rows.append((f, int(tos[j]), int(cnts[j]), int(m.sum()), cnts[j] / m.sum()))
rows.sort(key=lambda r: -r[4])
print(f"{'из':>9} {'в':>9} {'p(в|из)':>8} {'выходов':>9} {'слоёв сменилось':>16}")
for f, t, c, n, p in rows[:12]:
    hdd = sum(a != b for a, b in zip(dec(f), dec(t)))
    print(f"{arr(f):>9} {arr(t):>9} {p*100:7.1f}% {n:9,} {hdd:>16}")

# ── 4. ТОРГОВОЕ: форвард после перехода, IS → OOS ──────────────────────
print(f"\n=== ФОРВАРД ПОСЛЕ ПЕРЕХОДА · слепой отбор IS(1-я половина) → OOS(2-я) ===")
idx = TR[:, 3]
f4 = F[idx, 1]; f24 = F[idx, 3]
base4 = np.nanmean(f4); base24 = np.nanmean(f24)
print(f"  база по всем переходам: +4ч {base4:+.4f}%  +24ч {base24:+.4f}%  n={len(TR):,}")

key = TR[:, 0] * 3**L + TR[:, 1]
IS = TR[:, 5] == 0
uk = np.unique(key)
cand = []
for k in uk:
    m = key == k
    nis = (m & IS).sum()
    if nis < 150:
        continue
    v = np.nanmean(f4[m & IS])
    cand.append((k, nis, v, int(m.sum() - nis)))
cand.sort(key=lambda r: -abs(r[2] - base4))
print(f"  кандидатов (n_IS>=150): {len(cand)}")
print(f"\n{'переход':>21} {'n_IS':>7} {'IS +4ч':>9} {'n_OOS':>7} {'OOS +4ч':>9} {'перенос':>8}")
kept = 0
for k, nis, vis, noos in cand[:14]:
    f_, t_ = divmod(int(k), 3**L)
    m = (key == k) & (~IS)
    if m.sum() < 60:
        continue
    voos = np.nanmean(f4[m])
    ok = (vis - base4) * (voos - base4) > 0
    kept += ok
    print(f"{arr(f_)}→{arr(t_)} {nis:7,} {vis:+8.4f}% {int(m.sum()):7,} {voos:+8.4f}% "
          f"{'✓' if ok else '✗':>8}")
print(f"\n  знак сохранился на OOS: {kept} из {min(14, len(cand))}")

# ── 5. НАПРАВЛЕНИЕ СМЕНЫ: растёт или падает сумма знаков ───────────────
print(f"\n=== КУДА МЕНЯЕТСЯ СОГЛАСИЕ (сумма знаков) ===")
sf = np.array([sum(dec(int(x))) for x in TR[:, 0]])
st = np.array([sum(dec(int(x))) for x in TR[:, 1]])
d = st - sf
for lo, hi, nm in [(-9, -1, "к медвежьему"), (0, 0, "без смены суммы"), (1, 9, "к бычьему")]:
    m = (d >= lo) & (d <= hi)
    if m.sum() < 500:
        continue
    print(f"  {nm:>16}: n={m.sum():>8,} ({m.mean()*100:5.1f}%) | "
          f"+4ч {np.nanmean(f4[m]):+.4f}% | +24ч {np.nanmean(f24[m]):+.4f}%")

print(f"\n=== ПЕРЕХОД В ПОЛНОЕ СОГЛАСИЕ (момент, когда сошлись ВСЕ 7) ===")
full_up = 3**L - 1
full_dn = 0
for tgt, nm in [(full_up, "▲×7"), (full_dn, "▼×7")]:
    m = (TR[:, 1] == tgt) & (TR[:, 0] != tgt)
    if m.sum() < 100:
        continue
    print(f"  вход в {nm}: n={m.sum():>7,} | +4ч {np.nanmean(f4[m]):+.4f}% "
          f"(мед {np.nanmedian(f4[m]):+.4f}%) | +24ч {np.nanmean(f24[m]):+.4f}% "
          f"(мед {np.nanmedian(f24[m]):+.4f}%)")
    mo = (TR[:, 0] == tgt) & (TR[:, 1] != tgt)
    print(f"  выход из {nm}: n={mo.sum():>7,} | +4ч {np.nanmean(f4[mo]):+.4f}% "
          f"| дожил медиана {np.median(TR[mo, 2])*3/60:.1f} ч")

json.dump(dict(Hn=float(Hn), Hc=float(Hc), ctl=float(np.mean(ctlI)),
               n_trans=int(len(TR)), edges=[[int(a), int(b), int(c), int(n)]
                                            for a, b, c, n, _ in rows[:60]]),
          open(D + r"\cube_graph_fix.json", "w", encoding="utf-8"), ensure_ascii=False)
print("\nсохранено: cube_graph_fix.json")
