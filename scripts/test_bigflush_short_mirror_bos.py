# -*- coding: utf-8 -*-
"""ШОРТ-ЗЕРКАЛО BIG-FLUSH С ГЕЙТОМ BOS (11.08.2026).

Зеркало было отвергнуто раньше: PF 0.72 ([[autocorr_regime_key_fade]] — «шорт-зеркало сломано»).
НО мерилось ДО структурного гейта, который на лонговой стороне перевёл сетап из хрупкого
в прочный: PF 1.05 → 1.79, безтоп10% −884% → +634% ([[bos_gate_bigflush_structural]]).
И в тот же день ДВА независимых источника показали, что в текущем режиме платит ШОРТ:
  · бэктест OTE 150 монет: LONG PF 0.70, SHORT+BOS+импульсный PF 2.10
  · форвард метода Егора 135 сигналов: LONG PF 0.83, SHORT PF 1.47
Значит перепроверка зеркала с гейтом — не рыбалка, а следствие.

Зеркало 1:1: ATRTrend ВНИЗ + WT(10,21) > +порог (перегрев) + WT падает + стоп = 3-барный
хай ×1.003, дистанция 4-12% (закон размера) → SHORT, TP 1R, TTL 24 бара, ликвидная половина.
ГЕЙТ: бычий BOS внутренней структуры (len5) за последние 20 баров = памп СЛОМАЛ структуру
вверх (зеркало медвежьего BOS у лонга).
Причинность движка проверена: run_structure(df[:n]).events == full.events[i<n]."""
import sqlite3, sys, time, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict, deque
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 200


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


def ex_short(i, H, L, C, sl, ttl=24):
    e = C[i]; tp = e - (sl - e); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def rep(name, rows, cost):
    if len(rows) < 30:
        print(f"    {name:38} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:38} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
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
print(f"монет {len(DATA)}, ликвидных {len(liq)} · ШОРТ-зеркало bigflush + гейт бычьего BOS\n")
R = defaultdict(list)
WIN = 20
for si, s in enumerate(liq):
    d = DATA[s]
    st = run_structure(d, swing_len=50, internal_len=5)
    ev_by_bar = defaultdict(list)
    for e in st.events:
        ev_by_bar[int(e.i)].append(e)
    w = wt(d); tr_ = atrt(d)
    H = d.high.values; L = d.low.values; C = d.close.values
    yr = pd.to_datetime(d.time, unit="ms").dt.year.values
    recent = deque(); cnt = defaultdict(int); n = 0
    for i in range(120, len(d) - 1):
        for e in ev_by_bar.get(i, []):
            k = (e.kind, bool(e.bull), bool(e.internal))
            recent.append((i, k)); cnt[k] += 1
        while recent and recent[0][0] < i - WIN:
            _, k = recent.popleft(); cnt[k] -= 1
        if not (tr_[i] < 0 and w[i] > 60 and w[i] < w[i - 1]):      # ЗЕРКАЛО лонговых условий
            continue
        e_ = C[i]; sl = H[max(0, i - 3):i + 1].max() * 1.003
        if sl <= e_:
            continue
        dist = (sl - e_) / e_ * 100
        if not (4.0 < dist <= 12.0):
            continue
        y = int(yr[i]); p = ex_short(i, H, L, C, sl); n += 1
        R["A) ЗЕРКАЛО без гейта"].append((y, p, s))
        bos_up_i = cnt[("BOS", True, True)]
        ch_dn_i = cnt[("CHoCH", False, True)]
        if bos_up_i >= 1:
            R["B) + бычий BOS len5 (≤5ч)"].append((y, p, s))
        else:
            R["B') БЕЗ бычьего BOS"].append((y, p, s))
        if bos_up_i >= 2:
            R["C) ≥2 бычьих BOS"].append((y, p, s))
        if ch_dn_i >= 1:
            R["D) медв. CHoCH (подтверждение)"].append((y, p, s))
    if (si + 1) % 25 == 0:
        print(f"  ... {si+1}/{len(liq)}")
for cost in (0.25, 0.35):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    for k in ("A) ЗЕРКАЛО без гейта", "B) + бычий BOS len5 (≤5ч)", "B') БЕЗ бычьего BOS",
              "C) ≥2 бычьих BOS", "D) медв. CHoCH (подтверждение)"):
        rep(k, R.get(k, []), cost)
