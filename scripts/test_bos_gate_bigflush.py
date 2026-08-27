# -*- coding: utf-8 -*-
"""ГЕЙТ «ТОЛЬКО ПОСЛЕ BOS» НА ЖИВОМ ЯДРЕ bigflush15 (10.08).

Из проверки OTE ([[ote_impulse_assembly_choch_bos]]) вынесено правило, которое НЕ про фибо:
отделение свингов, давших BOS, от не давших подняло PF 0.76→1.00 на 10k сделок.
Правило структурное — значит применимо к любому входу. В бою два источника ничего не знают
про BOS. Здесь проверяем на ЯДРЕ (bigflush15).

Логика гипотезы: bigflush — это ФЕЙД дислокации. Осмысленно фейдить дислокацию, которая
СЛОМАЛА структуру (медвежий BOS = displacement вниз), а не рыночный шум. Это же согласуется
с находкой по автокорреляции: фейд платит в ИМПУЛЬСНОМ режиме ([[autocorr_regime_key_fade]]).

Контр-гипотеза (ожидаю провал): бычий CHoCH перед входом = «разворот подтверждён».
Семь раз подряд подтверждение оказывалось опозданием.

Сетап 1:1 как в бою: ATRTrend(43,1.25)↑ + WT(10,21)<−60 растущий + SL=min(low[-3:])*0.997,
дистанция стопа 4-12%, ликвидная половина, TP1R, TTL 24 бара.
Причинность структуры проверена: run_structure(df[:n]).events == full.events[i<n]."""
import sqlite3, sys, time, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def load(sym, tf, t0):
    c = sqlite3.connect(DB)
    df = pd.read_sql("SELECT time,open,high,low,close,volume FROM ohlcv_cache WHERE symbol=? "
                     "AND timeframe=? AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def wt(df, n1=10, n2=21):
    hlc = (df.high + df.low + df.close) / 3
    esa = hlc.ewm(span=n1).mean(); d = (hlc - esa).abs().ewm(span=n1).mean()
    return ((hlc - esa) / (0.015 * d.replace(0, np.nan))).ewm(span=n2).mean().fillna(0).values


def atrt(df, period=43, factor=1.25):
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    tu = up.copy(); td = dn.copy(); tr_ = np.ones(len(hl2))
    for i in range(1, len(hl2)):
        tu[i] = max(up[i], tu[i - 1]) if hl2[i - 1] > tu[i - 1] else up[i]
        td[i] = min(dn[i], td[i - 1]) if hl2[i - 1] < td[i - 1] else dn[i]
        tr_[i] = 1 if hl2[i] > td[i - 1] else (-1 if hl2[i] < tu[i - 1] else tr_[i - 1])
    return tr_


def ex_tp1r(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e + (e - sl); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if L[j] <= sl: return (sl - e) / e * 100
        if H[j] >= tp: return (tp - e) / e * 100
    return (C[end] - e) / e * 100


def rep(name, rows, cost):
    if len(rows) < 30:
        print(f"    {name:40} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:40} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:3}/{len(coins):3} | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='15m' "
                                "AND time>=? GROUP BY symbol HAVING n>40000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
DATA = {}; turn = {}
for s in syms:
    d = load(s, "15m", t0)
    if len(d) >= 20000:
        DATA[s] = d; turn[s] = float(np.nanmedian((d.close * d.volume).values))
mt = np.nanmedian(list(turn.values()))
liq = [s for s in DATA if turn[s] >= mt]
print(f"монет {len(DATA)}, ликвидных {len(liq)} · сетап bigflush15 1:1 как в бою\n")

R = defaultdict(list)
WIN = 20            # окно «недавнего» события: 20 баров 15m = 5 часов
for si, s in enumerate(liq):
    d = DATA[s]
    t_ = time.time()
    st = run_structure(d, swing_len=50, internal_len=5)      # причинно (проверено)
    # раскладываем события по бару: последний BOS/CHoCH каждой полярности и шкалы
    ev_by_bar = defaultdict(list)
    for e in st.events:
        ev_by_bar[int(e.i)].append(e)
    w = wt(d); tr_ = atrt(d)
    H = d.high.values; L = d.low.values; C = d.close.values
    yr = pd.to_datetime(d.time, unit="ms").dt.year.values
    n = 0
    # скользящие счётчики: сколько событий каждого типа в последних WIN барах
    from collections import deque
    recent = deque()
    cnt = defaultdict(int)
    for i in range(120, len(d) - 1):
        for e in ev_by_bar.get(i, []):
            k = (e.kind, bool(e.bull), bool(e.internal))
            recent.append((i, k)); cnt[k] += 1
        while recent and recent[0][0] < i - WIN:
            _, k = recent.popleft(); cnt[k] -= 1
        if not (tr_[i] > 0 and w[i] < -60 and w[i] > w[i - 1]):
            continue
        e_ = C[i]; sl = L[max(0, i - 3):i + 1].min() * 0.997
        if sl >= e_:
            continue
        dist = (e_ - sl) / e_ * 100
        if not (4.0 < dist <= 12.0):
            continue
        y = int(yr[i]); p = ex_tp1r(i, H, L, C, sl)
        n += 1
        R["A) БАЗА (как в бою)"].append((y, p, s))
        bos_dn_i = cnt[("BOS", False, True)]; bos_dn_s = cnt[("BOS", False, False)]
        ch_up_i = cnt[("CHoCH", True, True)]
        ch_dn_i = cnt[("CHoCH", False, True)]
        if bos_dn_i >= 1:
            R["B) был медв. BOS internal5 (≤5ч)"].append((y, p, s))
        else:
            R["B') БЕЗ медв. BOS internal5"].append((y, p, s))
        if bos_dn_i >= 2:
            R["C) ≥2 медв. BOS internal5"].append((y, p, s))
        if bos_dn_s >= 1:
            R["D) был медв. BOS swing50 (≤5ч)"].append((y, p, s))
        if ch_up_i >= 1:
            R["E) был бычий CHoCH (подтверждение)"].append((y, p, s))
        if ch_dn_i >= 1:
            R["F) был медв. CHoCH (слом вниз)"].append((y, p, s))
        if bos_dn_i >= 1 and ch_up_i == 0:
            R["G) медв. BOS И БЕЗ бычьего CHoCH"].append((y, p, s))
    print(f"  [{si+1}/{len(liq)}] {s.split('/')[0]:12} сигналов={n:5} структура {time.time()-t_:.0f}с")
for cost in (0.25, 0.35):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    for k in ("A) БАЗА (как в бою)", "B) был медв. BOS internal5 (≤5ч)",
              "B') БЕЗ медв. BOS internal5", "C) ≥2 медв. BOS internal5",
              "D) был медв. BOS swing50 (≤5ч)", "E) был бычий CHoCH (подтверждение)",
              "F) был медв. CHoCH (слом вниз)", "G) медв. BOS И БЕЗ бычьего CHoCH"):
        rep(k, R.get(k, []), cost)
