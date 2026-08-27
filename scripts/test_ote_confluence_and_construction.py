# -*- coding: utf-8 -*-
"""КОНФЛЮЭНЦИИ В OTE + ВЕРНОСТЬ ПОСТРОЕНИЯ ЗОНЫ (11.08.2026, два вопроса Егора).

ВОПРОС 1: «включали ли прошлые вердикты OTE конфлюэнции — FVG при старте импульса и FVG
внутри зоны?» Ответ по грепу: НЕТ, ни в одном тесте. FVG=0, ордер-блоки=0, пивоты=0,
дивергенция=0 во всех пяти скриптах. Все вердикты («зона не даёт эджа», «канон худший»)
измеряли ГОЛУЮ зону. Дыра признана — здесь закрывается.

ВОПРОС 2: «сомневаюсь в верности построения зоны OTE, а это критично». Обоснованно:
если origin/extreme определены неверно, то и глубина отката меряется неверно, и все выводы
о зоне — об артефакте построения, а не о рынке. Проверяем ТРИ определения origin:
  A) моё текущее — структурный экстремум между предыдущим событием и CHoCH
  B) фактический свинг-пивот из `_swings` (точка, а не экстремум диапазона)
  C) origin из `current_leg` — нога ЭТАЛОННОГО движка, сверенного с графиком Егора
Если результат сильно зависит от определения — построение критично и его надо чинить.
Если нет — глубина отката устойчива, и спор о точке origin не влияет на эдж.

База: конфигурация, выжившая развёртки — зона 0.55-0.85, стоп>6%, кластер≥2,
переключатель по причинному режиму (180/48/12). Косты 0.35%."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure, current_leg, _swings
from core.smc.impulse_assembly import assemble_impulse, ote_zone
from core.smc.structure import detect_structure
from core.smc.order_blocks import detect_order_blocks
from core.smc.fvg import detect_fvg
from core.context.market_drift import regime_series, BULL, BEAR
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 50
COST, MIN_STOP = 0.35, 6.0
ZLO, ZHI = 0.55, 0.85


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


def overlap(a_lo, a_hi, b_lo, b_hi):
    inter = max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))
    return inter / max(1e-12, a_hi - a_lo)


def rep(name, rows):
    if len(rows) < 25:
        print(f"    {name:36} n={len(rows)}"); return
    r = np.array([x[1] for x in rows]) - COST
    srt = np.sort(r); cut = max(1, len(r) // 10); med = np.median(r)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    coins = sorted(set(x[2] for x in rows))
    pos = sum(1 for cn in coins if np.median([x[1] - COST for x in rows if x[2] == cn]) > 0)
    ok = med > 0.02 and srt[:-cut].sum() > 0 and pf > 1.05
    print(f"    {name:36} n={len(r):4} WR{100*(r>0).mean():3.0f}% МЕД{med:+7.3f}% PF{pf:5.2f} "
          f"безтоп10%{srt[:-cut].sum():+7.0f}% монет+{pos:3}/{len(coins):3} "
          f"{'🟢🟢' if ok else ('🟡' if r.mean() > 0 else '🔴')}")


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>6000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · зона {ZLO}-{ZHI} · стоп>{MIN_STOP}% · кластер≥2 · переключатель\n")

px = {}
SIG = []
DIFF = []                      # расхождение определений origin
for si, sym in enumerate(syms):
    d4 = load(sym, "4h", t0); d1 = load(sym, "1h", t0)
    if len(d4) < 1200 or len(d1) < 5000:
        continue
    px[sym] = pd.Series(d4.close.values, index=d4.time.values)
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
        seen[sd] = key
        # ── ТРИ ОПРЕДЕЛЕНИЯ ORIGIN ──
        origins = {"A) мой (экстремум диапазона)": imp["origin"]}
        try:
            sw = [(p, is_top) for (_ci, _si, p, is_top) in _swings(win["high"], win["low"], 5)]
            cand = [p for p, tp_ in sw if (tp_ is False) == is_long]      # лоу для лонга, хай для шорта
            if cand:
                origins["B) свинг-пивот len5"] = (min(cand) if is_long else max(cand))
        except Exception:
            pass
        try:
            lg = current_leg(st)
            if lg and (lg["trend"] == "long") == is_long:
                origins["C) current_leg (эталон)"] = float(lg["origin"])
        except Exception:
            pass
        base_o = imp["origin"]
        for nm, o in origins.items():
            if nm.startswith("A"):
                continue
            DIFF.append(abs(o - base_o) / max(1e-12, abs(imp["extreme"] - base_o)))
        # ── конфлюэнции (СТАТИЧЕСКОЕ свойство зоны, считаем один раз на импульс) ──
        z_lo, z_hi = ote_zone(base_o, imp["extreme"], is_long, ZLO, ZHI)
        ov_ob = ov_fvg = 0.0
        try:
            sa = detect_structure(win)
            oba = detect_order_blocks(win, sa)
            pool = oba.active_bull if is_long else oba.active_bear
            for o_ in pool:
                ov_ob = max(ov_ob, overlap(z_lo, z_hi, min(o_.bottom, o_.top), max(o_.bottom, o_.top)))
        except Exception:
            pass
        try:
            fa = detect_fvg(win)
            poolf = fa.active_bull if is_long else fa.active_bear
            for f_ in poolf:
                ov_fvg = max(ov_fvg, overlap(z_lo, z_hi, min(f_.bottom, f_.top), max(f_.bottom, f_.top)))
        except Exception:
            pass
        side = 1 if is_long else -1
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            if not (z_lo <= p_ <= z_hi):
                continue
            rec = {"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "side": sd,
                   "ov_ob": ov_ob, "ov_fvg": ov_fvg, "pnl": {}}
            for nm, o in origins.items():
                sl = o * (0.997 if is_long else 1.003)
                if (is_long and sl >= p_) or ((not is_long) and sl <= p_):
                    continue
                dist = abs(p_ - sl) / p_ * 100
                if not (MIN_STOP < dist < 25):
                    continue
                rec["pnl"][nm] = sim(j, side, H1, L1, C1, sl, p_ + side * abs(p_ - sl))
            if rec["pnl"]:
                SIG.append(rec)
            break
    if (si + 1) % 15 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")

panel = pd.DataFrame(px).sort_index()
REG = regime_series(panel, drift_bars=180, ma_bars=48, min_periods=500, min_hold=12)
rt = REG.index.values.astype("int64"); rl = REG["label"].values
BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[(s["t"] // BUCKET, s["side"])] += 1

R = defaultdict(list)
for s in SIG:
    if cl[(s["t"] // BUCKET, s["side"])] < 2:
        continue
    k = int(np.searchsorted(rt, s["t"], side="right")) - 1
    lab = rl[k] if 0 <= k < len(rl) else None
    if lab is None or (isinstance(lab, float) and np.isnan(lab)):
        continue
    if not ((lab == BULL and s["side"] == "LONG") or (lab == BEAR and s["side"] == "SHORT")):
        continue
    for nm, v in s["pnl"].items():
        R[f"ORIGIN {nm}"].append((s["y"], v, s["sym"]))
    base = s["pnl"].get("A) мой (экстремум диапазона)")
    if base is None:
        continue
    row = (s["y"], base, s["sym"])
    R["БАЗА (без конфлюэнций)"].append(row)
    R["OB: есть" if s["ov_ob"] > 0 else "OB: нет"].append(row)
    R["FVG: есть" if s["ov_fvg"] > 0 else "FVG: нет"].append(row)
    if s["ov_fvg"] > 0.25:
        R["FVG перекрытие >25%"].append(row)
    if s["ov_ob"] > 0 and s["ov_fvg"] > 0:
        R["ОБА (OB и FVG)"].append(row)
    if s["ov_ob"] == 0 and s["ov_fvg"] == 0:
        R["НИ ОДНОЙ конфлюэнции"].append(row)

print(f"\nсигналов после гейтов: {len(R.get('БАЗА (без конфлюэнций)', []))}")
if DIFF:
    d = np.array(DIFF)
    print(f"\n═══ ВОПРОС 2: расхождение определений ORIGIN ═══")
    print(f"  |origin_alt − origin_мой| / длина импульса: медиана {np.median(d)*100:.1f}% · "
          f"доля расхождений >10%: {100*np.mean(d > 0.10):.0f}% · >25%: {100*np.mean(d > 0.25):.0f}%")
print("\n  результат по КАЖДОМУ определению origin (если близки — построение не критично):")
for nm in ("A) мой (экстремум диапазона)", "B) свинг-пивот len5", "C) current_leg (эталон)"):
    rep(f"ORIGIN {nm}", R.get(f"ORIGIN {nm}", []))
print("\n═══ ВОПРОС 1: КОНФЛЮЭНЦИИ (впервые измеряются) ═══")
for k in ("БАЗА (без конфлюэнций)", "FVG: есть", "FVG: нет", "FVG перекрытие >25%",
          "OB: есть", "OB: нет", "ОБА (OB и FVG)", "НИ ОДНОЙ конфлюэнции"):
    rep(k, R.get(k, []))
