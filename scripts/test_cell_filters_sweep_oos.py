# -*- coding: utf-8 -*-
"""РАЗВЁРТКА ТРЁХ ОСТАВШИХСЯ ОСЕЙ: зона × стоп × кластер (11.08.2026).

Развёртка детектора режима дала ЧАСТИЧНОЕ плато (12/42 комбинаций), причём лучшим оказалось
окно дрейфа, выбранное мной первым — след неосознанной подгонки
([[regime_switch_causal_survives]]).

Остались ТРИ степени свободы, которые я тоже подбирал руками и ни разу не разворачивал:
  · границы зоны OTE  0.618–0.786  (взяты из методики, но методику мы уже проверяли)
  · порог стопа       >6%          (найден перебором по корзинам = уже半 подгонка)
  · порог кластера    ≥2           (перенесён с bigflush, где ≥2 лучше ≥3)
Если и здесь окажется одна рабочая точка из трёх — суммарно это подгонка по четырём осям,
и направление придётся закрыть.

ТОНКОСТЬ: границы зоны определяют, СУЩЕСТВУЕТ ли сигнал, поэтому постфактум к готовому набору
их применить нельзя. Собираем входы по ШИРОКОЙ зоне 0.45-0.95, записывая фактический уровень
отката и PnL для КАЖДОГО бара в зоне (до 8 на импульс). Тогда любая узкая зона = подмножество
с ПРАВИЛЬНЫМ «первым касанием», а не с подменённым.

Режим фиксируем на конфигурации, выжившей в прошлой развёртке (180/48/12)."""
import sqlite3, sys, warnings, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from core.smc.oko_sm_engine import run_structure
from core.smc.impulse_assembly import assemble_impulse
from core.context.market_drift import regime_series, BULL, BEAR
DB = "ohlcv_cache.db"
NCOIN = int(sys.argv[1]) if len(sys.argv) > 1 else 120
COST = 0.35
WIDE_LO, WIDE_HI = 0.45, 0.95      # широкая зона сбора
MAX_PER_IMP = 8


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


def stats(vals):
    if len(vals) < 25:
        return len(vals), None, None
    r = np.array(vals) - COST
    srt = np.sort(r); cut = max(1, len(r) // 10)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    return len(r), pf, srt[:-cut].sum()


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>6000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · сбор по ШИРОКОЙ зоне {WIDE_LO}-{WIDE_HI}, до {MAX_PER_IMP} входов/импульс\n")

px = {}
IMP = []                      # список импульсов, у каждого — кандидаты входа
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
        o, e_ = imp["origin"], imp["extreme"]
        rng = abs(e_ - o)
        if rng <= 0:
            continue
        side = 1 if is_long else -1
        sl = o * (0.997 if is_long else 1.003)
        j0 = int(np.searchsorted(t1, t4[b])); j1 = min(j0 + 24, len(d1) - 2)
        cands = []
        for j in range(max(j0, 1), j1):
            p_ = C1[j]
            retr = (e_ - p_) / rng if is_long else (p_ - e_) / rng   # доля отката
            if not (WIDE_LO <= retr <= WIDE_HI):
                continue
            if (is_long and sl >= p_) or ((not is_long) and sl <= p_):
                continue
            dist = abs(p_ - sl) / p_ * 100
            if not (0.5 < dist < 25):
                continue
            cands.append({"t": int(t1[j]), "y": int(yr1[j]), "retr": float(retr),
                          "stop": float(dist),
                          "pnl": sim(j, side, H1, L1, C1, sl, p_ + side * abs(p_ - sl))})
            if len(cands) >= MAX_PER_IMP:
                break
        if cands:
            IMP.append({"sym": sym, "side": sd, "cands": cands})
    if (si + 1) % 30 == 0:
        print(f"  ... {si+1}/{len(syms)} импульсов={len(IMP)}")

panel = pd.DataFrame(px).sort_index()
REG = regime_series(panel, drift_bars=180, ma_bars=48, min_periods=500, min_hold=12)
rt = REG.index.values.astype("int64"); rl = REG["label"].values
print(f"\nимпульсов с кандидатами: {len(IMP)}")


def run(zlo, zhi, stop_thr, clu_thr, ymin=None, ymax=None):
    """Собрать сделки для конкретной комбинации фильтров и вернуть PnL переключателя.
    ymin/ymax — год-фильтр (OOS-разбиение по режимам)."""
    picked = []
    for im in IMP:
        for c_ in im["cands"]:                       # ПЕРВОЕ касание НУЖНОЙ зоны
            if ymin is not None and c_["y"] < ymin:
                continue
            if ymax is not None and c_["y"] > ymax:
                continue
            if zlo <= c_["retr"] <= zhi:
                if c_["stop"] > stop_thr:
                    picked.append({"sym": im["sym"], "side": im["side"], **c_})
                break
    if not picked:
        return []
    BUCKET = 4 * 3600 * 1000
    cl = defaultdict(int)
    for s in picked:
        cl[(s["t"] // BUCKET, s["side"])] += 1
    out = []
    for s in picked:
        if cl[(s["t"] // BUCKET, s["side"])] < clu_thr:
            continue
        k = int(np.searchsorted(rt, s["t"], side="right")) - 1
        lab = rl[k] if 0 <= k < len(rl) else None
        if lab is None or (isinstance(lab, float) and np.isnan(lab)):
            continue
        if (lab == BULL and s["side"] == "LONG") or (lab == BEAR and s["side"] == "SHORT"):
            out.append(s["pnl"])
    return out


ZONES = [(0.5, 0.7), (0.618, 0.786), (0.55, 0.85), (0.45, 0.95), (0.7, 0.9)]
STOPS = [3.0, 4.5, 6.0, 8.0]
CLUS = [1, 2, 3]
print("\n═══ РАЗВЁРТКА ФИЛЬТРОВ · PF (n) [безтоп10%] · косты 0.35% ═══\n")
res = {}
for clu in CLUS:
    print(f"  ── кластер ≥{clu} ──")
    hdr = f"{'зона':>14} |" + "".join(f"{'стоп>'+str(s):>20}" for s in STOPS)
    print(hdr)
    for z in ZONES:
        line = f"{f'{z[0]}-{z[1]}':>14} |"
        for stp in STOPS:
            v = run(z[0], z[1], stp, clu)
            n, pf, frag = stats(v)
            res[(z, stp, clu)] = (n, pf, frag)
            line += f"{(f'{pf:.2f} ({n}) [{frag:+.0f}]' if pf else f'n={n}'):>20}"
        print(line)
    print()

ok = [(k, v) for k, v in res.items() if v[1] is not None]
pfs = [v[1] for _, v in ok]
good = [k for k, v in ok if v[1] > 1.3 and v[2] > 0]
print(f"комбинаций с оценкой: {len(ok)} · PF медиана {np.median(pfs):.2f} · "
      f"диапазон {min(pfs):.2f}–{max(pfs):.2f}")
print(f"PF>1.3 И хрупкость пройдена: {len(good)} из {len(ok)} ({100*len(good)/max(1,len(ok)):.0f}%)")
print(f"доля PF>1.0: {100*np.mean([p > 1.0 for p in pfs]):.0f}%")
print("\nВЕРДИКТ: " + ("ПЛАТО по фильтрам" if len(good) >= 0.5 * len(ok) else
                       ("частичное плато" if len(good) >= 0.25 * len(ok) else
                        "ПОДГОНКА по фильтрам")))
if good:
    print("\nустойчивые комбинации:")
    for k in sorted(good, key=lambda x: -res[x][1])[:8]:
        n, pf, fr = res[k]
        print(f"   зона {k[0][0]}-{k[0][1]} · стоп>{k[1]} · кластер≥{k[2]}  →  PF {pf:.2f} (n={n}) [{fr:+.0f}]")

print("\n═══ OOS-РАЗБИЕНИЕ ПО РЕЖИМАМ: лучшие комбинации ═══")
print("TRAIN 2022-2024 (бык+нейтр) → TEST 2025-2026 (медведь), пороги фиксированы")
BEST = [(0.55, 0.85, 6.0, 3), (0.55, 0.85, 8.0, 3), (0.45, 0.95, 8.0, 3),
        (0.55, 0.85, 6.0, 2), (0.55, 0.85, 8.0, 2), (0.5, 0.7, 8.0, 3)]
for (z0, z1, stp, clu) in BEST:
    tr = run(z0, z1, stp, clu, ymin=2022, ymax=2024)
    te = run(z0, z1, stp, clu, ymin=2025, ymax=2026)
    n_tr, pf_tr, fr_tr = stats(tr)
    n_te, pf_te, fr_te = stats(te)
    print(f"  зона {z0}-{z1} · стоп>{stp} · кластер≥{clu}: "
          f"TRAIN n={n_tr} PF={pf_tr:.2f} [{fr_tr:+.0f}] | "
          f"TEST n={n_te} PF={pf_te:.2f} [{fr_te:+.0f}]")
