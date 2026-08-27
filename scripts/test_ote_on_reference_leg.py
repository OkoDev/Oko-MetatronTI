# -*- coding: utf-8 -*-
"""OTE НА ЭТАЛОННОЙ НОГЕ (10.08) — первая честная проверка метода Егора.

07.08 измерено: детектор ote берёт НЕ ТУ НОГУ (направление совпадает в 62%, зоны не
пересекаются в 66%). Значит весь прошлый вердикт по OTE относился к СЛОМАННОЙ разметке.
Здесь строим зону от `current_leg` эталона (run_structure swing_len=50, порт индикатора
Егора 1:1, верифицирован метками графика) и спрашиваем: есть ли эдж в ЭТОЙ зоне.

Правила: нога с 4h (контекст) · вход при заходе цены в OTE 0.618-0.786 на 1h ·
LONG на откате в зону восходящей ноги, SHORT — нисходящей · SL за origin ноги (структура) ·
TP: (A) 1R (B) экстремум ноги. Причинно: run_structure только по закрытым барам,
пересчёт раз в сутки (6 баров 4h). Косты 0.25/0.35."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure, current_leg
DB = "ohlcv_cache.db"


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def rep(name, rows, cost, months=29.0):
    if len(rows) < 25:
        print(f"    {name:30} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    fr = len(r) / len(coins) / months
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:30} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} {fr:5.2f}сд/мес | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


def sim(i, side, H, L, C, sl, tp, ttl):
    e = C[i]; end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if side > 0:
            if L[j] <= sl: return (sl - e) / e * 100
            if H[j] >= tp: return (tp - e) / e * 100
        else:
            if H[j] >= sl: return (e - sl) / e * 100
            if L[j] <= tp: return (e - tp) / e * 100
    return side * (C[end] - e) / e * 100


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 10",
                                (t0,)).fetchall()]
c.close()
print(f"монет {len(syms)} · нога 4h (пересчёт раз в сутки) · вход в зону на 1h\n")
R = defaultdict(list)
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    n_leg = n_tr = 0
    last_key = None
    for b in range(1050, len(d4) - 1, 6):          # раз в сутки, причинно
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            leg = current_leg(run_structure(win, swing_len=50, internal_len=5))
        except Exception:
            leg = None
        if not leg:
            continue
        n_leg += 1
        o, e_ = float(leg["origin"]), float(leg["extreme"])
        is_long = leg["trend"] == "long"
        rng = abs(e_ - o)
        if rng <= 0:
            continue
        key = (round(o, 10), round(e_, 10), is_long)
        if key == last_key:                        # ту же ногу второй раз не торгуем
            continue
        # OTE 0.618-0.786 отката
        if is_long:
            z_lo, z_hi = e_ - 0.786 * rng, e_ - 0.618 * rng
        else:
            z_lo, z_hi = e_ + 0.618 * rng, e_ + 0.786 * rng
        # ищем ПЕРВЫЙ заход в зону на 1h в ближайшие сутки после закрытия 4h-бара
        j0 = int(np.searchsorted(t1, t4[b]))
        j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            px = C1[j]
            if not (z_lo <= px <= z_hi):
                continue
            side = 1 if is_long else -1
            sl = (o * 0.997) if is_long else (o * 1.003)   # за origin ноги = за структуру
            if (is_long and sl >= px) or ((not is_long) and sl <= px):
                break
            dist = abs(px - sl) / px * 100
            if not (0.5 < dist < 25):
                break
            y = int(yr1[j])
            R["A) TP1R"].append((y, sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl), 72), sym))
            R["B) TP = экстремум ноги"].append((y, sim(j, side, H1, L1, C1, sl, e_, 72), sym))
            R[f"A) TP1R · {'LONG' if is_long else 'SHORT'}"].append(
                (y, sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl), 72), sym))
            # C) МЕТОД ЕГОРА: зона + ТРИГГЕР len5-CHoCH на 1h в сторону ноги
            try:
                w1 = d1.iloc[max(0, j - 200):j + 1].reset_index(drop=True)
                st1 = run_structure(w1, swing_len=50, internal_len=5)
                _tr = getattr(st1, "itrend", None)
                if _tr is None:
                    _tr = getattr(st1, "internal_trend", None)
                if _tr is None:
                    _tr = getattr(st1, "trend", None)
                if _tr is not None and ((is_long and _tr == 1) or ((not is_long) and _tr == -1)):
                    R["C) зона + триггер len5-CHoCH"].append(
                        (y, sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl), 72), sym))
            except Exception:
                pass
            n_tr += 1
            last_key = key
            break
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:12} ног={n_leg:4} входов={n_tr:3}")
for cost in (0.25, 0.35):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    for k in ("A) TP1R", "B) TP = экстремум ноги", "C) зона + триггер len5-CHoCH",
              "A) TP1R · LONG", "A) TP1R · SHORT"):
        rep(k, R.get(k, []), cost)
