# -*- coding: utf-8 -*-
"""ОБЕ СТОРОНЫ, ПОЛНОЕ ОКНО 2022-2026 (11.08.2026 — вопрос Егора про окно).

🔴 МОЙ ПРОМАХ, который поймал Егор: во ВСЕХ скриптах стояло t0=2024-01-01 «по привычке».
Замеренный дрейф рынка (медиана годовой доходности монеты, 92 монеты со сплошной историей):
  2022: −84.1% (растущих 0%)   ← глубокий медведь
  2023: **+82.1% (растущих 90%)** ← БЫК, в кэше есть, НИ РАЗУ не использован
  2024:  −4.6% (растущих 47%)  ← нейтраль
  2025: −72.0% (растущих 7%)
  2026: −27.2% (растущих 13%)
Моё окно = нейтраль + два медведя. Вывод «лонг мёртв» получен там, где лонгу негде работать
ПО ПОСТРОЕНИЮ — это тавтология, а не находка. И PF 1.83 шорт-клетки
([[ote_short_cluster_full_candidate]]) намерен почти целиком на падении → устойчивость
преувеличена.

Здесь: ОБЕ стороны × ВСЯ стопка (собранный импульс CHoCH+BOS + стоп>6% + кластер≥2)
× полное окно 2022-2026 × разбивка ПО ГОДАМ и по режиму года (бык/нейтраль/медведь).
Вопрос: клетка — эдж или функция падающего рынка? И оживает ли лонг в 2023?"""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 120
MIN_STOP = 6.0
# режим года из замера дрейфа (медиана годовой доходности монеты)
YEAR_REGIME = {2022: "медведь", 2023: "БЫК", 2024: "нейтраль", 2025: "медведь", 2026: "медведь"}


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
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


def rep(name, rows, cost=0.35):
    if len(rows) < 25:
        print(f"    {name:34} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+6.2f}" if len(a) > 12 else "   ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:34} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} | "
          f"22:{fmt(y(2022))} 23:{fmt(y(2023))} 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
# монеты с ДЛИННОЙ историей — иначе 2022-23 представлены единицами
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>6000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} (история >6000 баров 4h) · окно 2022-2026 · ОБЕ стороны, вся стопка\n")
SIG = []
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    seen = {}
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        imp = assemble_impulse(st, win["high"], win["low"], internal=True)
        if not imp or imp["n_bos"] < 1:
            continue
        is_long = imp["is_long"]
        sd = "LONG" if is_long else "SHORT"
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if seen.get(sd) == key:
            continue
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], is_long)
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            px = C1[j]
            if not (z_lo <= px <= z_hi):
                continue
            side = 1 if is_long else -1
            sl = imp["origin"] * (0.997 if is_long else 1.003)
            if (is_long and sl >= px) or ((not is_long) and sl <= px):
                break
            dist = abs(px - sl) / px * 100
            if not (MIN_STOP < dist < 25):
                break
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "side": sd,
                        "pnl": sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl))})
            seen[sd] = key
            break
    if (si + 1) % 25 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")

BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[(s["t"] // BUCKET, s["side"])] += 1      # кластер СЧИТАЕМ ПО СТОРОНЕ
R = defaultdict(list)
for s in SIG:
    row = (s["y"], s["pnl"], s["sym"])
    n_cl = cl[(s["t"] // BUCKET, s["side"])]
    R[f"{s['side']} · стоп>6%"].append(row)
    if n_cl >= 2:
        R[f"{s['side']} · стоп>6% + кластер≥2"].append(row)
        R[f"{s['side']} · ПОЛНАЯ СТОПКА · {YEAR_REGIME.get(s['y'],'?')}"].append(row)
print(f"\nсигналов {len(SIG)}: LONG {sum(1 for s in SIG if s['side']=='LONG')} · "
      f"SHORT {sum(1 for s in SIG if s['side']=='SHORT')}")
print("\n═══ КОСТЫ 0.35% · 22=медведь 23=БЫК 24=нейтраль 25/26=медведь ═══")
for sd in ("SHORT", "LONG"):
    print(f"  ── {sd} ──")
    rep(f"{sd} стоп>6%", R.get(f"{sd} · стоп>6%", []))
    rep(f"{sd} + кластер≥2 (КАНДИДАТ)", R.get(f"{sd} · стоп>6% + кластер≥2", []))
    for reg in ("БЫК", "нейтраль", "медведь"):
        rep(f"{sd} полная стопка · {reg}", R.get(f"{sd} · ПОЛНАЯ СТОПКА · {reg}", []))
