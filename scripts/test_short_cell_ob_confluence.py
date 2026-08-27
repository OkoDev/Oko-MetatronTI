# -*- coding: utf-8 -*-
"""КОНФЛЮЭНЦИЯ OTE-ЗОНЫ С ОРДЕР-БЛОКОМ на шорт-клетке (11.08.2026, идея Егора).

Егор: «зоны POB/Demand ордер блоки» + видение матрицы схождений
([[mtf_confluence_matrix_vision]]).

ПОЧЕМУ ЭТО НЕ «ПОДТВЕРЖДЕНИЕ»: закон «подтверждение = опоздание» подтверждён 8 раз, но он
про ОЖИДАНИЕ ТРИГГЕРА (дождись кросса / свечи / CHoCH — и опоздай). Здесь ждать нечего:
пересекается ли зона входа с ордер-блоком — СТАТИЧЕСКОЕ свойство, известное В МОМЕНТ
сигнала. Это фильтр качества зоны, а не задержка входа. Класс другой — проверять честно.

Гипотеза: шорт в OTE, которая ЛЕЖИТ В ЗОНЕ ПРЕДЛОЖЕНИЯ (медвежий OB) — сильнее, чем
шорт в «пустой» OTE: там реально стоит непогашенный ордер-поток.

База — валидированный кандидат ([[ote_short_cluster_full_candidate]]):
импульс CHoCH+BOS (n_bos≥1) · SHORT · стоп>6% · вход в OTE 0.618-0.786 на 1h · SL за origin · TP1R.
Причинно: OB считается на окне ДО текущего бара."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 100
MIN_STOP = 6.0
MONTHS = 31.0


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def sim_short(i, H, L, C, sl, tp, ttl=72):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def rep(name, rows, cost=0.35, ncoins=100):
    if len(rows) < 25:
        print(f"    {name:36} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 12 else "  ?  "
    fr = len(r) / ncoins / MONTHS
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:36} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} "
          f"{fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · шорт-клетка × пересечение OTE-зоны с медвежьим OB\n")
R = defaultdict(list)
SIG = []
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
        if not imp or imp["n_bos"] < 1 or imp["is_long"]:
            continue
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if key == seen:
            continue
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], False)
        # пересекается ли зона входа с активным медвежьим OB (СТАТИЧЕСКОЕ свойство зоны)
        ov = 0.0
        try:
            sa = detect_structure(win)
            oba = detect_order_blocks(win, sa)
            for o in oba.active_bear:
                lo_, hi_ = min(o.bottom, o.top), max(o.bottom, o.top)
                inter = max(0.0, min(z_hi, hi_) - max(z_lo, lo_))
                if inter > 0:
                    ov = max(ov, inter / max(1e-12, (z_hi - z_lo)))
        except Exception:
            pass
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            px = C1[j]
            if not (z_lo <= px <= z_hi):
                continue
            sl = imp["origin"] * 1.003
            if sl <= px:
                break
            dist = (sl - px) / px * 100
            if not (MIN_STOP < dist < 25):
                break
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "ov": ov,
                        "pnl": sim_short(j, H1, L1, C1, sl, px - (sl - px))})
            seen = key
            break
    if (si + 1) % 25 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")
# кластер по 4h-корзине (лучший фильтр кандидата)
BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[s["t"] // BUCKET] += 1
for s in SIG:
    row = (s["y"], s["pnl"], s["sym"])
    n_cl = cl[s["t"] // BUCKET]
    R["БАЗА (все)"].append(row)
    R["OB: нет пересечения" if s["ov"] <= 0 else "OB: ЕСТЬ пересечение"].append(row)
    for thr, nm in ((0.25, "OB перекрытие >25%"), (0.5, "OB перекрытие >50%")):
        if s["ov"] > thr:
            R[nm].append(row)
    if n_cl >= 2:
        R["кластер≥2 (кандидат)"].append(row)
        R["кластер≥2 + OB нет" if s["ov"] <= 0 else "кластер≥2 + OB ЕСТЬ"].append(row)
print(f"\nсигналов {len(SIG)} · с пересечением OB {sum(1 for s in SIG if s['ov']>0)} "
      f"({100*sum(1 for s in SIG if s['ov']>0)/max(1,len(SIG)):.0f}%)")
print("\n═══ КОСТЫ 0.35% ═══")
for k in ("БАЗА (все)", "OB: нет пересечения", "OB: ЕСТЬ пересечение",
          "OB перекрытие >25%", "OB перекрытие >50%",
          "кластер≥2 (кандидат)", "кластер≥2 + OB нет", "кластер≥2 + OB ЕСТЬ"):
    rep(k, R.get(k, []), ncoins=len(syms))
