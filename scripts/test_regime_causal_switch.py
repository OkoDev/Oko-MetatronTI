# -*- coding: utf-8 -*-
"""ПЕРЕЖИВАЕТ ЛИ ЗЕРКАЛО ПРИЧИННУЮ МЕТКУ РЕЖИМА (11.08.2026).

Замер 11.08: клетка OTE — зеркало режима (в быка лонг PF 2.41, в медведя шорт 1.71).
НО метка бралась по доходности за ВЕСЬ ГОД = заглядывание в будущее. Торговать так нельзя.

Здесь метка строится причинно (`core/context/market_drift`): дрейф вселенной + ширина рынка,
пороги — РАСШИРЯЮЩИЙСЯ перцентиль по прошлым значениям, плюс shift(1).

ВОПРОС: сохраняется ли переключение сторон, когда «читерскую» метку заменили честной?
Если да — у нас гейт для бота и ядро продукта («какая сторона платит сейчас»).
Если нет — зеркало было артефактом разметки, и это надо знать до того, как строить продукт.

Контроль: тот же прогон с ГОДОВОЙ меткой (нечестной) — чтобы видеть цену честности."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.context.market_drift import regime_series, BULL, BEAR, FLAT
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 120
MIN_STOP = 6.0
YEAR_REGIME = {2022: BEAR, 2023: BULL, 2024: FLAT, 2025: BEAR, 2026: BEAR}   # НЕчестная, для контроля


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


def rep(name, rows, cost=0.35):
    if len(rows) < 25:
        print(f"    {name:38} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - cost
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - cost for x in rows if x[2] == cn]) > 0)
    y = lambda yy: [x[1] - cost for x in rows if x[0] == yy]
    fmt = lambda a: f"{np.median(a):+6.2f}" if len(a) > 12 else "   ?  "
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:38} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} | "
          f"22:{fmt(y(2022))} 23:{fmt(y(2023))} 24:{fmt(y(2024))} 25:{fmt(y(2025))} 26:{fmt(y(2026))} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>6000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · окно 2022-2026 · ПРИЧИННАЯ метка режима\n")

# ── причинный режим по вселенной (панель 4h close) ──
px = {}
for s in syms:
    d = load(s, "4h", t0, "time,close")
    if len(d) > 2000:
        px[s] = pd.Series(d.close.values, index=d.time.values)
panel = pd.DataFrame(px).sort_index()
REG = regime_series(panel, drift_bars=180, ma_bars=48, min_periods=500)
rt = REG.index.values.astype("int64")
rlab = REG["label"].values
ok = pd.notna(REG["label"])
print("режим (причинно), распределение баров:")
vc = REG.loc[ok, "label"].value_counts()
for k, v in vc.items():
    print(f"   {k:10} {v:6} баров ({100*v/ok.sum():4.1f}%)")
idx = pd.to_datetime(REG.index, unit="ms")
for yy in (2022, 2023, 2024, 2025, 2026):
    m = ok & (idx.year == yy)
    if m.sum():
        top = REG.loc[m, "label"].value_counts()
        share = {k: f"{100*v/m.sum():.0f}%" for k, v in top.items()}
        print(f"   {yy}: {share}")

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
        is_long = imp["is_long"]; sd = "LONG" if is_long else "SHORT"
        key = (round(imp["origin"], 10), round(imp["extreme"], 10))
        if seen.get(sd) == key:
            continue
        z_lo, z_hi = ote_zone(imp["origin"], imp["extreme"], is_long)
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            if not (z_lo <= p_ <= z_hi):
                continue
            side = 1 if is_long else -1
            sl = imp["origin"] * (0.997 if is_long else 1.003)
            if (is_long and sl >= p_) or ((not is_long) and sl <= p_):
                break
            dist = abs(p_ - sl) / p_ * 100
            if not (MIN_STOP < dist < 25):
                break
            k = int(np.searchsorted(rt, t1[j], side="right")) - 1
            lab = rlab[k] if 0 <= k < len(rlab) else None
            if lab is None or (isinstance(lab, float) and np.isnan(lab)):
                break
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "side": sd,
                        "reg": str(lab), "pnl": sim(j, side, H1, L1, C1, sl,
                                                    p_ + side * abs(p_ - sl))})
            seen[sd] = key
            break
    if (si + 1) % 25 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")

BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[(s["t"] // BUCKET, s["side"])] += 1
R = defaultdict(list)
for s in SIG:
    if cl[(s["t"] // BUCKET, s["side"])] < 2:      # кластер-гейт как в кандидате
        continue
    row = (s["y"], s["pnl"], s["sym"])
    R[f"{s['side']} · ПРИЧИННО · {s['reg']}"].append(row)
    R[f"{s['side']} · ГОД (нечестно) · {YEAR_REGIME.get(s['y'])}"].append(row)
    R[f"{s['side']} · всё"].append(row)
    # ПЕРЕКЛЮЧАТЕЛЬ: торгуем сторону, которую предписывает режим
    if (s["reg"] == BULL and s["side"] == "LONG") or (s["reg"] == BEAR and s["side"] == "SHORT"):
        R["ПЕРЕКЛЮЧАТЕЛЬ (причинно)"].append(row)
    if (s["reg"] == BULL and s["side"] == "SHORT") or (s["reg"] == BEAR and s["side"] == "LONG"):
        R["ПРОТИВ режима (контроль)"].append(row)

print(f"\nсигналов в кластере: {sum(len(v) for k,v in R.items() if k.endswith('· всё'))}")
print("\n═══ КОСТЫ 0.35% · метка ПРИЧИННАЯ ═══")
for sd in ("LONG", "SHORT"):
    print(f"  ── {sd} ──")
    rep(f"{sd} всё", R.get(f"{sd} · всё", []))
    for reg in (BULL, FLAT, BEAR):
        rep(f"{sd} · причинно · {reg}", R.get(f"{sd} · ПРИЧИННО · {reg}", []))
print("\n  ── ИТОГ: переключатель против контроля ──")
rep("ПЕРЕКЛЮЧАТЕЛЬ (причинно)", R.get("ПЕРЕКЛЮЧАТЕЛЬ (причинно)", []))
rep("ПРОТИВ режима (контроль)", R.get("ПРОТИВ режима (контроль)", []))
print("\n  ── контроль: та же нарезка НЕЧЕСТНОЙ годовой меткой ──")
for sd in ("LONG", "SHORT"):
    for reg in (BULL, BEAR):
        rep(f"{sd} · год · {reg}", R.get(f"{sd} · ГОД (нечестно) · {reg}", []))
