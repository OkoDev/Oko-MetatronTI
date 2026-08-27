# -*- coding: utf-8 -*-
"""OTE ОТ СОБРАННОГО ИМПУЛЬСА (10.08, мысль Егора про волновую теорию).

Обе прошлые проверки брали ОДНУ ногу (детектор — свою, эталон — current_leg) и обе дали PF<1.
Гипотеза Егора: импульсная волна СКЛАДЫВАЕТСЯ из нескольких ног (1-2-3-4-5), и значимый OTE
меряется от НАЧАЛА всего импульса до его КОНЦА, а не от последнего подсегмента.

Здесь: берём свинги эталона (run_structure), идём назад от последнего экстремума и НАКАПЛИВАЕМ
последовательные ноги, пока структура продолжается в ту же сторону (для импульса вверх —
каждый следующий лоу выше предыдущего). Полученный размах = импульсная волна.
Сравниваем OTE от 1 ноги / 2 ног / 3+ ног (собранный импульс)."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure, current_leg, _swings
DB = "ohlcv_cache.db"


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def assemble_impulse(win, is_long, swing_len=50):
    """Складываем ноги в импульс: идём назад по свингам, пока структура не сломалась.
    Для импульса ВВЕРХ: каждый предыдущий лоу должен быть НИЖЕ следующего (HL-цепочка).
    Возвращает список размахов: [1 нога, 2 ноги, 3+ ног]."""
    try:
        hi, lo = _swings(win["high"], win["low"], swing_len)
    except Exception:
        return []
    # свинги: списки (index, price); собираем чередующуюся последовательность
    pts = sorted([(i, p, "H") for i, p in (hi or [])] + [(i, p, "L") for i, p in (lo or [])])
    if len(pts) < 3:
        return []
    out = []
    if is_long:
        # последний максимум = конец импульса
        highs = [p for p in pts if p[2] == "H"]
        lows = [p for p in pts if p[2] == "L"]
        if not highs or not lows:
            return []
        top = highs[-1]
        prior_lows = [p for p in lows if p[0] < top[0]]
        prior_lows.reverse()                       # от ближнего к дальнему
        chain = []
        prev = None
        for lw in prior_lows:
            if prev is not None and lw[1] >= prev[1]:
                break                              # цепочка HL сломалась
            chain.append(lw); prev = lw
            out.append((lw[1], top[1], len(chain)))
            if len(chain) >= 4:
                break
    else:
        lows = [p for p in pts if p[2] == "L"]
        highs = [p for p in pts if p[2] == "H"]
        if not highs or not lows:
            return []
        bot = lows[-1]
        prior_highs = [p for p in highs if p[0] < bot[0]]
        prior_highs.reverse()
        chain = []
        prev = None
        for hg in prior_highs:
            if prev is not None and hg[1] <= prev[1]:
                break
            chain.append(hg); prev = hg
            out.append((hg[1], bot[1], len(chain)))
            if len(chain) >= 4:
                break
    return out


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


def rep(name, rows, cost):
    if len(rows) < 20:
        print(f"    {name:34} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 12 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:34} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT 10",
                                (t0,)).fetchall()]
c.close()
print(f"монет {len(syms)} · импульс складывается из ног (эталонные свинги len50)\n")
R = defaultdict(list)
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    n_imp = 0
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            leg = current_leg(run_structure(win, swing_len=50, internal_len=5))
        except Exception:
            leg = None
        if not leg:
            continue
        is_long = leg["trend"] == "long"
        spans = assemble_impulse(win, is_long)
        if not spans:
            continue
        n_imp += 1
        for origin, extreme, n_legs in spans:
            rng = abs(extreme - origin)
            if rng <= 0:
                continue
            if is_long:
                z_lo, z_hi = extreme - 0.786 * rng, extreme - 0.618 * rng
            else:
                z_lo, z_hi = extreme + 0.618 * rng, extreme + 0.786 * rng
            j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
            for j in range(max(j0, 1), j1):
                px = C1[j]
                if not (z_lo <= px <= z_hi):
                    continue
                side = 1 if is_long else -1
                sl = (origin * 0.997) if is_long else (origin * 1.003)
                if (is_long and sl >= px) or ((not is_long) and sl <= px):
                    break
                dist = abs(px - sl) / px * 100
                if not (0.5 < dist < 25):
                    break
                y = int(yr1[j])
                p = sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl), 72)
                key = "1 нога (как раньше)" if n_legs == 1 else (
                      "2 ноги" if n_legs == 2 else "3+ ног (собранный импульс)")
                R[key].append((y, p, sym))
                R["ВСЕ размахи"].append((y, p, sym))
                break
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:12} импульсов={n_imp}")
for cost in (0.25, 0.35):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    for k in ("ВСЕ размахи", "1 нога (как раньше)", "2 ноги", "3+ ног (собранный импульс)"):
        rep(k, R.get(k, []), cost)
