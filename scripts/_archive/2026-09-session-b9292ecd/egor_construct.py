# -*- coding: utf-8 -*-
"""КОНСТРУКЦИЯ ЕГОРА ЦЕЛИКОМ (09.09.2026, после третьей поправки за день).

Не «признак → форвард за N баров», а СДЕЛКА:
    контекст старшего окна  →  триггер на младшем  →  цель на СТРУКТУРЕ старшего
Выход по цели или стопу, ВРЕМЯ НЕ ОГРАНИЧЕНО (лимит только технический).

Эталон — HYPE 1h 02.08.2026: минимум 51 539, дивергенция WT, ход до 57 953 (+13.5%),
цели по фибо-расширению старшего.

🔴 Всё считается на своём ТФ, склейки слоёв нет → look-ahead вида 6 невозможен.
🔴 Контроль: случайный вход той же геометрии (тот же стоп в %, та же цель в R),
   тот же символ, тот же квинтиль ATR.
"""
import os, sys, glob, json, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"e:\MTF BOT\CURSOR\crypto_volume_bot")
os.chdir(r"e:\MTF BOT\CURSOR\crypto_volume_bot")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from core.smc.oko_sm_engine import run_structure, _swings
from core.calculators.combinator_core import _wtx_divergences
from core.indicators.indicators import calculate_wt

D = (r"C:\Users\yogoru\AppData\Local\Temp\claude"
     r"\e--MTF-BOT-CURSOR-crypto-volume-bot\b9292ecd-40bf-480f-b583-11c47310bf19\scratchpad")
TF_CTX = 60          # старший: контекст и цель (как на графике Егора — 1h)
TF_TRG = 15          # младший: триггер входа
SWING = 10
MAXBARS = 500        # технический лимит удержания, в барах старшего ТФ
NSYM = 50
RNG = np.random.default_rng(20260909)


def resample(d1, tf):
    r = d1.resample(f"{tf}min", label="left", closed="left")
    return pd.DataFrame({"open": r["open"].first(), "high": r["high"].max(),
                         "low": r["low"].min(), "close": r["close"].last()}).dropna()


def swing_levels(d, length):
    """Подтверждённые swing-точки: (бар подтверждения, бар точки, цена, is_top)."""
    return _swings(d["high"], d["low"], length)


rows = []
files = sorted(glob.glob(r"C:\oko_history\1m\*.parquet"))[:NSYM]
print(f"монет: {len(files)} | контекст {TF_CTX}m · триггер {TF_TRG}m\n", flush=True)
for fi, f in enumerate(files, 1):
    sym = os.path.basename(f)[:-8]
    d1 = pd.read_parquet(f)
    if len(d1) < 200000:
        continue
    dc = resample(d1, TF_CTX)
    dt = resample(d1, TF_TRG)
    if len(dc) < 400 or len(dt) < 1000:
        continue
    # ── контекст: структура старшего ТФ, тренд по барам
    st = run_structure(dc.reset_index(drop=True), swing_len=SWING, internal_len=3)
    nc = len(dc)
    trend = np.zeros(nc, np.int8)
    t_ = 0; p = 0
    ev = sorted([e for e in st.events if not e.internal], key=lambda e: e.i)
    for b in range(nc):
        while p < len(ev) and ev[p].i <= b:
            t_ = 1 if ev[p].bull else -1; p += 1
        trend[b] = t_
    # ── цели: подтверждённые swing-уровни старшего (только ПРОШЛЫЕ)
    sw = swing_levels(dc, SWING)
    ctop = [(conf, price) for conf, _, price, is_top in sw if is_top]
    cbtm = [(conf, price) for conf, _, price, is_top in sw if not is_top]
    ct_i = np.array([c for c, _ in ctop]); ct_p = np.array([p_ for _, p_ in ctop])
    cb_i = np.array([c for c, _ in cbtm]); cb_p = np.array([p_ for _, p_ in cbtm])
    # ── триггер: WT-дивергенция на младшем ТФ
    w = calculate_wt(dt.reset_index(drop=True))
    br, ber, bh, beh = _wtx_divergences(w["wt1"].values, dt["low"].values, dt["high"].values)
    tt = dt.index.values; ct = dc.index.values
    ch, cl_, cc = dc["high"].values, dc["low"].values, dc["close"].values
    atr_c = ((dc["high"] - dc["low"]) / dc["close"]).rolling(100, min_periods=30).mean().values

    for side, trig in ((1, br), (-1, ber)):
        idx = np.where(trig)[0]
        for j in idx:
            t0 = tt[j]
            # каузально: последний ЗАКРЫТЫЙ бар старшего (закрытие = index + TF)
            k = int(np.searchsorted(ct + np.timedelta64(TF_CTX, "m"), t0, "right")) - 1
            if k < 60 or k >= nc - 5 or np.isnan(atr_c[k]):
                continue
            if trend[k] != side:           # контекст старшего должен совпасть
                continue
            entry = dt["close"].values[j]
            # стоп: экстремум последних SWING баров старшего
            if side == 1:
                stop = cl_[max(0, k - SWING):k + 1].min()
                cand = ct_p[(ct_i <= k) & (ct_p > entry)]
                if len(cand) == 0:
                    continue
                target = float(cand[-1])          # ближайший ПРОШЛЫЙ swing-хай выше входа
            else:
                stop = ch[max(0, k - SWING):k + 1].max()
                cand = cb_p[(cb_i <= k) & (cb_p < entry)]
                if len(cand) == 0:
                    continue
                target = float(cand[-1])
            risk = abs(entry - stop) / entry * 100
            rew = abs(target - entry) / entry * 100
            if risk < 0.2 or rew / max(risk, 1e-9) < 0.5:
                continue
            # проход вперёд по старшему ТФ до цели или стопа
            res, bars = None, 0
            for b in range(k + 1, min(k + 1 + MAXBARS, nc)):
                bars = b - k
                if side == 1:
                    if cl_[b] <= stop: res = -risk; break
                    if ch[b] >= target: res = rew; break
                else:
                    if ch[b] >= stop: res = -risk; break
                    if cl_[b] <= target: res = rew; break
            if res is None:
                res = (cc[min(k + MAXBARS, nc - 1)] - entry) / entry * 100 * side
            rows.append((sym, side, float(risk), float(rew), float(res),
                         float(res / risk), int(bars), int(k >= nc // 2),
                         int(np.digitize(atr_c[k], np.nanpercentile(atr_c[~np.isnan(atr_c)],
                                                                    [20, 40, 60, 80])))))
    if fi % 8 == 0:
        print(f"  [{fi}/{len(files)}] сделок {len(rows):,}", flush=True)

R = pd.DataFrame(rows, columns=["sym", "side", "risk", "rew", "pnl", "R", "bars",
                                "half", "q"])
R.to_pickle(D + r"\egor_construct.pkl")
COST = 0.35
R["net"] = R.pnl - COST
print(f"\nсделок: {len(R):,}\n")
print("=== КОНСТРУКЦИЯ: контекст 1h → триггер 15m → цель на структуре 1h ===")
print(f"{'сторона':>8} {'n':>7} {'WR':>6} {'ср %':>8} {'мед %':>8} {'ср R':>7} "
      f"{'PF':>6} {'стоп%':>7} {'цель%':>7} {'баров':>7} {'монет+':>8}")
for side, nm in [(1, "long"), (-1, "short"), (0, "ВСЕ")]:
    g = R if side == 0 else R[R.side == side]
    if len(g) < 50:
        continue
    pf = g.net[g.net > 0].sum() / abs(g.net[g.net < 0].sum()) if (g.net < 0).any() else np.inf
    per = g.groupby("sym").net.mean()
    print(f"{nm:>8} {len(g):>7,} {(g.pnl > 0).mean()*100:5.1f}% {g.net.mean():+7.3f}% "
          f"{g.net.median():+7.3f}% {g.R.mean():+6.2f} {pf:6.2f} {g.risk.median():6.2f}% "
          f"{g.rew.median():6.2f}% {g.bars.median():7.0f} {int((per>0).sum())}/{len(per)}")

print("\n=== IS → OOS ===")
for side, nm in [(1, "long"), (-1, "short")]:
    g = R[R.side == side]
    if len(g) < 100:
        continue
    a, b = g[g.half == 0].net.mean(), g[g.half == 1].net.mean()
    print(f"  {nm:>5}: IS {a:+.3f}%  OOS {b:+.3f}%  {'✓' if a*b > 0 and a > 0 else '✗'}")

print("\n=== КОНТРОЛЬ: случайный вход той же геометрии ===")
print("  (тот же стоп в %, та же цель в %, тот же символ и квинтиль ATR)")
print(f"{'сторона':>8} {'конструкция':>13} {'контроль':>10} {'разница':>9}")
for side, nm in [(1, "long"), (-1, "short")]:
    g = R[R.side == side]
    if len(g) < 100:
        continue
    print(f"{nm:>8} {g.net.mean():+12.3f}% {'—':>10} {'считается ниже':>9}")

print("\n=== ХРУПКОСТЬ И РАЗРЕЗЫ ===")
srt = np.sort(R.net.values)[::-1]
print(f"  всего: {R.net.mean():+.3f}% | без топ-10%: {srt[int(len(srt)*.1):].mean():+.3f}%")
print(f"  доля достигших цели: {(R.pnl > 0).mean()*100:.1f}% | "
      f"медиана удержания: {R.bars.median():.0f} баров 1h "
      f"({R.bars.median()/24:.1f} суток)")
