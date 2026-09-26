# -*- coding: utf-8 -*-
"""OTE ОТ ИМПУЛЬСА, СОБРАННОГО ПО CHoCH+BOS (10.08, мысль Егора).

Прошлые две проверки брали ОДНУ ногу (`current_leg`) — обе дали PF<1.
Егор: «по волновой теории импульс надо СКЛАДЫВАТЬ из ног, и чтобы складывался — у нас есть
CHoCH и BOS». Методика ICT это подтверждает: свинг годен под OTE только ПОСЛЕ того как дал
BOS/CHoCH, и фибо тянут от лоу, С КОТОРОГО начался ход, до хая, КОТОРЫМ он закончился.

Сборка здесь:
  CHoCH в сторону тренда  = СТАРТ импульса (origin = экстремум перед сломом характера)
  каждый последующий BOS  = приваренная нога (счётчик n_bos = «сколько ног сложилось»)
  текущий экстремум       = КОНЕЦ импульса
Гипотеза: OTE от СОБРАННОГО импульса (n_bos≥1) лучше, чем от последней ноги (n_bos=0).
Отдельно две шкалы: swing (len50, internal=False) и internal (len5, internal=True).

Вход/выход как в предыдущем тесте, чтобы сравнение было честным: нога с 4h (пересчёт раз в
сутки, причинно), вход при заходе в OTE 0.618-0.786 на 1h, SL за origin, TP 1R, TTL 72ч."""
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


def assemble(st, win, internal):
    """Импульс = от CHoCH в сторону тренда до текущего экстремума; BOS-ы после CHoCH = ноги.
    Возвращает (origin, extreme, is_long, n_bos) или None."""
    evs = [e for e in st.events if bool(e.internal) == internal]
    if not evs:
        return None
    is_long = (st.minor_trend if internal else st.trend) > 0
    # последний CHoCH В СТОРОНУ тренда = момент, когда характер сменился на текущий
    i_ch = None; pos = None
    for k in range(len(evs) - 1, -1, -1):
        if evs[k].kind == "CHoCH" and bool(evs[k].bull) == is_long:
            i_ch = int(evs[k].i); pos = k
            break
    if i_ch is None:
        return None
    # origin = экстремум ДО слома характера (структурное начало хода)
    i_prev = int(evs[pos - 1].i) if pos > 0 else max(0, i_ch - 60)
    a, b = max(0, min(i_prev, i_ch - 1)), i_ch + 1
    if b - a < 2:
        return None
    lo = win["low"].values; hi = win["high"].values
    origin = float(lo[a:b].min()) if is_long else float(hi[a:b].max())
    extreme = float(hi[i_ch:].max()) if is_long else float(lo[i_ch:].min())
    # сколько ног приварилось: BOS в сторону тренда после CHoCH
    n_bos = sum(1 for e in evs[pos + 1:] if e.kind == "BOS" and bool(e.bull) == is_long)
    if (is_long and extreme <= origin) or ((not is_long) and extreme >= origin):
        return None
    return origin, extreme, is_long, n_bos


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
    if len(rows) < 25:
        print(f"    {name:38} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:38} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:2}/{len(coins):2} | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, int(sys.argv[1]) if len(sys.argv) > 1 else 10)).fetchall()]
c.close()
print(f"монет {len(syms)} · импульс = CHoCH→BOS…→экстремум · вход в OTE на 1h\n")
R = defaultdict(list)
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    seen = {}
    stat = defaultdict(int)
    for b in range(1050, len(d4) - 1, 6):
        win = d4.iloc[max(0, b - 1000):b + 1].reset_index(drop=True)
        try:
            st = run_structure(win, swing_len=50, internal_len=5)
        except Exception:
            continue
        arms = []
        for internal, tag in ((False, "swing50"), (True, "internal5")):
            a = assemble(st, win, internal)
            if a:
                arms.append((tag, a))
        leg = current_leg(st)
        if leg:
            arms.append(("baseline_current_leg",
                         (float(leg["origin"]), float(leg["extreme"]), leg["trend"] == "long", -1)))
        for tag, (origin, extreme, is_long, n_bos) in arms:
            key = (tag, round(origin, 10), round(extreme, 10), is_long)
            if seen.get(tag) == key:
                continue
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
                y = int(yr1[j]); p = sim(j, side, H1, L1, C1, sl, px + side * abs(px - sl), 72)
                if tag == "baseline_current_leg":
                    R["БАЗА: current_leg (как раньше)"].append((y, p, sym))
                else:
                    R[f"{tag}: импульс ВСЕ"].append((y, p, sym))
                    nb = "0 BOS (только CHoCH)" if n_bos == 0 else (
                         "1 BOS (2 ноги)" if n_bos == 1 else (
                         "2 BOS (3 ноги)" if n_bos == 2 else "3+ BOS (4+ ног)"))
                    R[f"{tag}: {nb}"].append((y, p, sym))
                    if n_bos >= 1:
                        R[f"{tag}: ≥1 BOS (собран)"].append((y, p, sym))
                    if n_bos >= 2:
                        R[f"{tag}: ≥2 BOS (длинный импульс)"].append((y, p, sym))
                    stat[f"{tag}|{nb}"] += 1
                seen[tag] = key
                break
    print(f"  [{si+1}/{len(syms)}] {sym.split('/')[0]:12} " +
          " ".join(f"{k.split('|')[0][:4]}·{k.split('|')[1][:5]}={v}" for k, v in sorted(stat.items())))
for cost in (0.25, 0.35):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    rep("БАЗА: current_leg (как раньше)", R.get("БАЗА: current_leg (как раньше)", []), cost)
    for tag in ("swing50", "internal5"):
        print(f"  ── {tag} ──")
        for nb in ("импульс ВСЕ", "0 BOS (только CHoCH)", "1 BOS (2 ноги)",
                   "2 BOS (3 ноги)", "3+ BOS (4+ ног)",
                   "≥1 BOS (собран)", "≥2 BOS (длинный импульс)"):
            rep(f"{tag}: {nb}", R.get(f"{tag}: {nb}", []), cost)
