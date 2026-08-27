# -*- coding: utf-8 -*-
"""ШОРТ-КЛЕТКА OTE × ГИБРИД-ВЫХОД × КЛАСТЕР-ГЕЙТ (11.08.2026).

Кандидат ([[ote_short_size_law_beats_phase]]): импульс CHoCH+BOS (n_bos≥1) + SHORT +
стоп >6% → PF 1.41, медиана +3.06%, все 3 года, 95/142 монет. Слабости: хрупкость проходит
ВПРИТЫК (безтоп10% +19%) и низкая частота (0.11 сд/монету/мес).

К нему НЕ применялись два приёма, давшие больше всего на живом ядре bigflush:
  1. ГИБРИД-ВЫХОД — половина фиксируется на 1R, половина идёт раннером под трейлом.
     На bigflush утроил медиану (+0.910% → +2.839%), безтоп10% +53 → +216.
     Трейл берём ТОТ, что реально умеет бот: линия ATRTrend(43,1.25). Урок «торговали не то,
     что тестировали» — свой трейл писать не нужно, штатный проверен не хуже peak−k×ATR.
  2. КЛАСТЕР-ГЕЙТ — торгуем только рыночное движение, не одиночку.
     На bigflush: одиночка PF 0.67, кластер ≥2 PF 2.24 ([[cluster_gate_market_wide_flush]]).
     Здесь кластер считаем по 4h-бару: сколько монет одновременно дают сетап.

Оба приёма измерены на ФЕЙДЕ ВНИЗ. Здесь механика другая (трендовый шорт) — переносить
вслепую нельзя, ровно как гейт BOS не перенёсся на зеркало
([[regime_map_four_setups_downdrift]]). Поэтому меряем, а не предполагаем."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 150
MIN_STOP = 6.0          # порог закона размера, найденный для этой клетки
MONTHS = 31.0


def load(sym, tf, t0, cols="time,open,high,low,close,volume"):
    c = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT {cols} FROM ohlcv_cache WHERE symbol=? AND timeframe=? "
                     "AND time>=? ORDER BY time", c, params=(sym, tf, t0))
    c.close()
    return df.reset_index(drop=True)


def atrt_line(df, period=43, factor=1.25):
    """Тренд ±1 И ЛИНИЯ трейла — то, за чем следит штатный tsl_engine бота."""
    h, l, c = df.high, df.low, df.close
    hl2 = ((h + l) / 2).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().values
    up = hl2 - factor * atr; dn = hl2 + factor * atr
    tu = up.copy(); td = dn.copy(); tr_ = np.ones(len(hl2)); line = up.copy()
    for i in range(1, len(hl2)):
        tu[i] = max(up[i], tu[i - 1]) if hl2[i - 1] > tu[i - 1] else up[i]
        td[i] = min(dn[i], td[i - 1]) if hl2[i - 1] < td[i - 1] else dn[i]
        tr_[i] = 1 if hl2[i] > td[i - 1] else (-1 if hl2[i] < tu[i - 1] else tr_[i - 1])
        line[i] = tu[i] if tr_[i] > 0 else td[i]
    return line


def ex_tp1r_short(i, H, L, C, sl, ttl=72):
    e = C[i]; tp = e - (sl - e); end = min(i + ttl, len(C) - 1)
    for j in range(i + 1, end + 1):
        if H[j] >= sl: return (e - sl) / e * 100
        if L[j] <= tp: return (e - tp) / e * 100
    return (e - C[end]) / e * 100


def ex_hybrid_short(i, H, L, C, sl, line, ttl=72):
    """½ фиксируется на 1R, ½ идёт раннером под линией ATRTrend (зеркало лонговой версии)."""
    e = C[i]; R = sl - e; tp = e - R; end = min(i + ttl, len(C) - 1)
    half1 = None; trough = e; trail = sl
    for j in range(i + 1, end + 1):
        if half1 is None and H[j] >= sl:
            return (e - sl) / e * 100
        if half1 is None and L[j] <= tp:
            half1 = (e - tp) / e * 100
            trough = min(trough, L[j]); trail = min(trail, e)
            continue
        if half1 is not None:
            trough = min(trough, L[j])
            if not np.isnan(line[j]) and line[j] > C[j]:
                trail = min(trail, line[j])
            if H[j] >= trail:
                return (half1 + (e - trail) / e * 100) / 2
    if half1 is None:
        return (e - C[end]) / e * 100
    return (half1 + (e - C[end]) / e * 100) / 2


def rep(name, rows, cost=0.35, ncoins=146):
    if len(rows) < 30:
        print(f"    {name:34} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+.2f}" if len(a) > 15 else "  ?  "
    fr = len(r) / ncoins / MONTHS
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:34} n={len(r):5} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+8.0f}% монет+{pos:3}/{len(coins):3} "
          f"{fr:5.2f}сд/мес → **{fr*med:+.2f}%/мес** | "
          f"24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>3000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · ШОРТ-клетка (n_bos≥1, стоп>{MIN_STOP}%) × гибрид × кластер\n")

# ── ПРОХОД 1: собираем все сигналы с временем ──
SIG = []
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    t4 = d4.time.values; t1 = d1.time.values
    H1 = d1.high.values; L1 = d1.low.values; C1 = d1.close.values
    yr1 = pd.to_datetime(d1.time, unit="ms").dt.year.values
    line1 = atrt_line(d1)
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
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            if not (z_lo <= p_ <= z_hi):
                continue
            sl = imp["origin"] * 1.003
            if sl <= p_:
                break
            dist = (sl - p_) / p_ * 100
            if not (MIN_STOP < dist < 25):
                break
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]),
                        "tp1r": ex_tp1r_short(j, H1, L1, C1, sl),
                        "hyb": ex_hybrid_short(j, H1, L1, C1, sl, line1),
                        "nbos": imp["n_bos"]})
            seen = key
            break
    if (si + 1) % 30 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")

# ── ПРОХОД 2: кластер по 4h-корзине времени ──
BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[s["t"] // BUCKET] += 1
R = defaultdict(list)
for s in SIG:
    n_cl = cl[s["t"] // BUCKET]
    for tag, v in (("A) TP1R (кандидат)", s["tp1r"]), ("B) ГИБРИД ½1R+½раннер", s["hyb"])):
        R[tag].append((s["y"], v, s["sym"]))
        if n_cl == 1:
            R[f"{tag} · одиночка"].append((s["y"], v, s["sym"]))
        if n_cl >= 2:
            R[f"{tag} · кластер ≥2"].append((s["y"], v, s["sym"]))
        if n_cl >= 3:
            R[f"{tag} · кластер ≥3"].append((s["y"], v, s["sym"]))
        if s["nbos"] >= 2:
            R[f"{tag} · ≥2 BOS"].append((s["y"], v, s["sym"]))
print(f"\nвсего сигналов {len(SIG)} · кластеров-корзин {len(cl)} · "
      f"одиночек {sum(1 for s in SIG if cl[s['t']//BUCKET]==1)}")
print("\n═══ КОСТЫ 0.35% ═══")
for tag in ("A) TP1R (кандидат)", "B) ГИБРИД ½1R+½раннер"):
    print(f"  ── {tag} ──")
    for suf in ("", " · одиночка", " · кластер ≥2", " · кластер ≥3", " · ≥2 BOS"):
        rep((suf[3:] if suf else "база"), R.get(tag + suf, []))
