# -*- coding: utf-8 -*-
"""OTE × ФАЗА РЫНКА × ОТСКОК-ПРОТИВ-ПРОДОЛЖЕНИЯ (10.08, поправка Егора).

Егор поймал меня на закрытии дуги ПО УСРЕДНЁННОМУ числу — той же ошибке, что «15m тупик»
(оттуда потом вышел BIG-FLUSH). Две его мысли:
  1. НЕ УЧТЕНА ФАЗА РЫНКА. Фейд платит только в импульсном режиме (PF 3.73 против 1.36,
     [[autocorr_regime_key_fade]]) — этой оси в тесте OTE не было вообще.
  2. Похоже, найден эдж КОРРЕКЦИОННОГО ОТСКОКА, а не продолжения тренда. И это по конструкции
     так: вход в зону 0.618-0.786 = вход на глубоком откате, SL за origin, TP=1R, где
     R ≈ 22-38% ноги. Я мерил «отскочит ли на 1R», а не «пойдёт ли к новым хаям».

Здесь разделяем это явно:
  ВЫХОД A (отскок/фейд)      : TP = 1R
  ВЫХОД B (продолжение)      : TP = экстремум импульса (новый хай/лоу)
  ВЫХОД C (продолжение +ext)  : TP = экстремум + 0.272 размаха (расширение)
× ФАЗА: импульсный / середина / возвратный (кросс-секционная автокорреляция 6ч, причинно)
× сборка импульса: 0 BOS против ≥1 BOS ([[ote_impulse_assembly_choch_bos]])

Импульс собирается по CHoCH+BOS, движок причинен (проверено: run_structure(df[:n]).events
== full.events[i<n]). Косты 0.25/0.35."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.context.market_regime import ac_label
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 150


def load(sym, tf, t0, cols="time,open,high,low,close,volume"):
    c = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT {cols} FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                     "AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def assemble(st, win, internal=True):
    """CHoCH в сторону тренда = старт импульса, BOS после него = приваренные ноги."""
    evs = [e for e in st.events if bool(e.internal) == internal]
    if not evs:
        return None
    is_long = (st.itrend if internal else st.trend) > 0
    i_ch = pos = None
    for k in range(len(evs) - 1, -1, -1):
        if evs[k].kind == "CHoCH" and bool(evs[k].bull) == is_long:
            i_ch = int(evs[k].i); pos = k
            break
    if i_ch is None:
        return None
    i_prev = int(evs[pos - 1].i) if pos > 0 else max(0, i_ch - 60)
    a, b = max(0, min(i_prev, i_ch - 1)), i_ch + 1
    if b - a < 2:
        return None
    lo = win["low"].values; hi = win["high"].values
    origin = float(lo[a:b].min()) if is_long else float(hi[a:b].max())
    extreme = float(hi[i_ch:].max()) if is_long else float(lo[i_ch:].min())
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
    if len(rows) < 30:
        print(f"    {name:44} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:44} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:3}/{len(coins):3} | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)

# ── ФАЗА: кросс-секционная автокорреляция 6ч-доходностей (как в golden_autocorr_regime) ──
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
AC = r6.rolling(14 * 24).corr(r6.shift(6)).mean(axis=1).shift(6)      # ПРИЧИННО
ac_t = AC.index.values.astype("int64"); ac_v = AC.values
print(f"фаза: автокорреляция 6ч, медиана {np.nanmedian(ac_v):+.4f} · "
      f"пороги импульсный≥−0.0126 / возвратный≤−0.0672")

c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · импульс CHoCH+BOS на 4h · вход в OTE на 1h\n")
R = defaultdict(list)
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
        a = assemble(st, win, internal=True)
        if not a:
            continue
        origin, extreme, is_long, n_bos = a
        key = (round(origin, 10), round(extreme, 10), is_long)
        if key == seen:
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
            px_ = C1[j]
            if not (z_lo <= px_ <= z_hi):
                continue
            side = 1 if is_long else -1
            sl = (origin * 0.997) if is_long else (origin * 1.003)
            if (is_long and sl >= px_) or ((not is_long) and sl <= px_):
                break
            dist = abs(px_ - sl) / px_ * 100
            if not (0.5 < dist < 25):
                break
            y = int(yr1[j])
            k = int(np.searchsorted(ac_t, t1[j], side="right")) - 1
            lab = ac_label(float(ac_v[k])) if 0 <= k < len(ac_v) and not np.isnan(ac_v[k]) else None
            if lab is None:
                break
            ext = extreme + side * 0.272 * rng
            outs = {
                "A) ОТСКОК TP1R": sim(j, side, H1, L1, C1, sl, px_ + side * abs(px_ - sl), 72),
                "B) ПРОДОЛЖЕНИЕ TP=экстремум": sim(j, side, H1, L1, C1, sl, extreme, 72),
                "C) ПРОДОЛЖЕНИЕ TP=ext+0.272": sim(j, side, H1, L1, C1, sl, ext, 72),
            }
            asm = "≥1BOS" if n_bos >= 1 else "0BOS"
            sd = "LONG" if is_long else "SHORT"
            for nm, p in outs.items():
                R[f"{nm} · ВСЕ фазы"].append((y, p, sym))
                R[f"{nm} · {lab}"].append((y, p, sym))
                R[f"{nm} · {sd}"].append((y, p, sym))          # довод Егора: 2024 = всё в лонг
                if asm == "≥1BOS":
                    R[f"{nm} · {lab} · ≥1BOS"].append((y, p, sym))
                    R[f"{nm} · {sd} · ≥1BOS"].append((y, p, sym))
                    R[f"{nm} · {lab} · {sd} · ≥1BOS"].append((y, p, sym))
            seen = key
            break
    if (si + 1) % 25 == 0:
        print(f"  ... {si+1}/{len(syms)}")
for cost in (0.35,):
    print(f"\n═══ КОСТЫ {cost}% ═══")
    for nm in ("A) ОТСКОК TP1R", "B) ПРОДОЛЖЕНИЕ TP=экстремум", "C) ПРОДОЛЖЕНИЕ TP=ext+0.272"):
        print(f"  ── {nm} ──")
        for lab in ("ВСЕ фазы", "импульсный", "середина", "возвратный"):
            rep(f"{lab}", R.get(f"{nm} · {lab}", []), cost)
        for lab in ("импульсный", "середина", "возвратный"):
            rep(f"{lab} · ≥1BOS (собран)", R.get(f"{nm} · {lab} · ≥1BOS", []), cost)
        # довод Егора 11.08: «2024 год всё в лонг, а мы смотрим на шорты» —
        # если минус 2024 держится шортами против бычьего года, это режим, а не провал сетапа
        for sd in ("LONG", "SHORT"):
            rep(f"{sd} (все фазы)", R.get(f"{nm} · {sd}", []), cost)
            rep(f"{sd} · ≥1BOS", R.get(f"{nm} · {sd} · ≥1BOS", []), cost)
            rep(f"импульсный · {sd} · ≥1BOS", R.get(f"{nm} · импульсный · {sd} · ≥1BOS", []), cost)
