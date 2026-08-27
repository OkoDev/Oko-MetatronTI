# -*- coding: utf-8 -*-
"""ЗАКОН РАЗМЕРА НА ШОРТ-КЛЕТКЕ OTE (11.08.2026).

Глубочайшая находка проекта — эдж живёт в РАЗМЕРЕ сетапа относительно костов, не в ТФ
([[bigflush_edge_size_not_timeframe]]): косты это ДОЛЯ цели, поэтому мелкий сетап мёртв,
а крупный жив. Порог растёт с падением ТФ: 15m >4%, 5m >5%, 3m >6%.
К шорт-клетке OTE закон НИ РАЗУ не применялся.

Мотив: `SHORT · ≥1BOS` дал n=767, PF 1.29, ПЛЮС ВО ВСЕ 3 ГОДА, 99/146 монет
([[ote_short_impulsive_first_robust_cell]]) — втрое больше выборки, чем у ядра с фазовым
гейтом (n=271), и шире по годам. Провалил ТОЛЬКО хрупкость (безтоп10% −219%), почти дотянув.
Ровно так выглядел 15m до разбиения по дистанции стопа.

Вопрос: спасает ли закон размера шорт-клетку, дав ПРОЧНЫЙ эдж с БОЛЬШЕЙ частотой,
чем узкое фазовое ядро? (Философия Егора: «стабильный + на повторении простого»,
«чем чаще повторение, тем ближе цель».)

Геометрия 1:1 с прошлым тестом: импульс 4h по CHoCH+BOS, вход в OTE на 1h, SL за origin,
TP1R, TTL 72ч, косты 0.35%."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.context.market_regime import ac_label
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 150
MONTHS = 31.0


def load(sym, tf, t0, cols="time,open,high,low,close,volume"):
    c = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT {cols} FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                     "AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def sim(i, side, H, L, C, sl, tp, ttl=72):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if side > 0:
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        else:
            if H[j] >= sl: return (e - sl) / e * 100
            if L[j] <= tp: return (e - tp) / e * 100
    return side * (C[end] - e) / e * 100


def rep(name, rows, cost=0.35, ncoins=None):
    if len(rows) < 30:
        print(f"    {name:36} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    fr = len(r) / (ncoins or len(coins)) / MONTHS
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:36} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:3}/{len(coins):3} "
          f"{fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
# фаза (причинно, как в golden_autocorr_regime)
c = sqlite3.connect(DB)
ac_syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='1h' "
                                   "AND time>=? GROUP BY symbol HAVING n>15000 ORDER BY n DESC LIMIT 60",
                                   (t0,)).fetchall()]
c.close()
px = {}
for s in ac_syms:
    d = load(s, "1h", t0, "time,close")
    if len(d) > 3000:
        px[s] = pd.Series(d.close.values, index=d.time.values)
panel = pd.DataFrame(px).sort_index()
r6 = panel.pct_change(6)
AC = r6.rolling(14 * 24).corr(r6.shift(6)).mean(axis=1).shift(6)
ac_t = AC.index.values.astype("int64"); ac_v = AC.values

c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · ШОРТ-клетка OTE (импульс CHoCH+BOS, n_bos≥1) × ЗАКОН РАЗМЕРА\n")
R = defaultdict(list)
NC = len(syms)
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    seen = None
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        imp = assemble_impulse(st, win["high"], win["low"], internal=True)
        if not imp or imp["n_bos"] < 1 or imp["is_long"]:      # только ШОРТ + собранный
            continue
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if key == seen:
            continue
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], False)
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            if not (z_lo <= p_ <= z_hi):
                continue
            sl = imp["origin"] * 1.003
            if sl <= p_:
                break
            dist = (sl - p_) / p_ * 100
            if not (0.5 < dist < 25):
                break
            y = int(yr1[j])
            pnl = sim(j, -1, H1, L1, C1, sl, p_ - abs(p_ - sl))
            k = int(np.searchsorted(ac_t, t1[j], side="right")) - 1
            lab = ac_label(float(ac_v[k])) if 0 <= k < len(ac_v) and not np.isnan(ac_v[k]) else "?"
            R["ВСЕ (как было: n767 PF1.29)"].append((y, pnl, sym))
            for lo, hi in ((0.5, 2), (2, 4), (4, 6), (6, 9), (9, 25)):
                if lo < dist <= hi:
                    R[f"стоп {lo}-{hi}%"].append((y, pnl, sym))
            for thr in (3, 4, 5, 6):
                if dist > thr:
                    R[f"стоп >{thr}%"].append((y, pnl, sym))
                    if lab == "импульсный":
                        R[f"стоп >{thr}% + импульсный"].append((y, pnl, sym))
            seen = key
            break
    if (si + 1) % 30 == 0:
        print(f"  ... {si+1}/{len(syms)}")
print("\n═══ КОСТЫ 0.35% ═══")
rep("ВСЕ (как было: n767 PF1.29)", R.get("ВСЕ (как было: n767 PF1.29)", []), ncoins=NC)
print("  ── по КОРЗИНАМ дистанции стопа ──")
for lo, hi in ((0.5, 2), (2, 4), (4, 6), (6, 9), (9, 25)):
    rep(f"стоп {lo}-{hi}%", R.get(f"стоп {lo}-{hi}%", []), ncoins=NC)
print("  ── ПОРОГИ (как в BIG-FLUSH) ──")
for thr in (3, 4, 5, 6):
    rep(f"стоп >{thr}%", R.get(f"стоп >{thr}%", []), ncoins=NC)
print("  ── порог + фазовое ядро ──")
for thr in (3, 4, 5, 6):
    rep(f"стоп >{thr}% + импульсный", R.get(f"стоп >{thr}% + импульсный", []), ncoins=NC)
