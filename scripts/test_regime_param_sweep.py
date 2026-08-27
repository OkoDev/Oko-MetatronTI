# -*- coding: utf-8 -*-
"""РАЗВЁРТКА ПАРАМЕТРОВ РЕЖИМА — подгонка или плато? (11.08.2026, требование Егора).

Я выбрал drift_bars=180 (30д), ma_bars=48 (8д) и min_hold=12 (2 суток) ПО СМЫСЛУ, не по данным.
Егор: «подгонка — нехорошо, нужно перепроверить». Он прав: сегодня мы уже дважды ловили
находку, живущую в единственной точке (фазовый гейт = подгонка под 2025; клетка PF 2.10,
рассыпавшаяся при смене окна).

КРИТЕРИЙ ЧЕСТНОСТИ: эдж должен держаться на ПЛАТО значений, а не в одной точке.
Если PF>1.3 только при min_hold=12 и рушится при 6 и 24 — это подгонка, направление закрыто.

Приём: СИГНАЛЫ НЕ ЗАВИСЯТ ОТ МЕТКИ РЕЖИМА. Считаем их ОДИН раз (дорого), затем гоняем
по ним десятки разметок (дёшево). Иначе прогон занял бы сутки.

Сетка: drift_bars ∈ {90,180,360} (15/30/60д) × ma_bars ∈ {24,48,96} × min_hold ∈ {1,6,12,24,42}
= 45 комбинаций на одних и тех же сделках."""
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
MIN_STOP, COST = 6.0, 0.35


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
    """→ (n, WR, медиана, PF, безтоп10%) с уже вычтенными костами."""
    if len(vals) < 25:
        return len(vals), None, None, None, None
    r = np.array(vals) - COST
    srt = np.sort(r); cut = max(1, len(r) // 10)
    pf = (r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else 9.9
    return len(r), 100 * (r > 0).mean(), np.median(r), pf, srt[:-cut].sum()


t0 = int(dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
c = sqlite3.connect(DB)
syms = [r[0] for r in c.execute("SELECT symbol,COUNT(*) n FROM ohlcv_cache WHERE timeframe='4h' "
                                "AND time>=? GROUP BY symbol HAVING n>6000 ORDER BY n DESC LIMIT ?",
                                (t0, NCOIN)).fetchall()]
c.close()
print(f"монет {len(syms)} · окно 2022-2026 · сигналы считаются ОДИН раз\n")

px = {}
SIG = []
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
            SIG.append({"sym": sym, "t": int(t1[j]), "y": int(yr1[j]), "side": sd,
                        "pnl": sim(j, side, H1, L1, C1, sl, p_ + side * abs(p_ - sl))})
            seen[sd] = key
            break
    if (si + 1) % 30 == 0:
        print(f"  ... {si+1}/{len(syms)} сигналов={len(SIG)}")

# кластер-гейт один раз
BUCKET = 4 * 3600 * 1000
cl = defaultdict(int)
for s in SIG:
    cl[(s["t"] // BUCKET, s["side"])] += 1
SIG = [s for s in SIG if cl[(s["t"] // BUCKET, s["side"])] >= 2]
panel = pd.DataFrame(px).sort_index()
print(f"\nсигналов после кластер-гейта: {len(SIG)} "
      f"(LONG {sum(1 for s in SIG if s['side']=='LONG')} · SHORT {sum(1 for s in SIG if s['side']=='SHORT')})")

print("\n═══ РАЗВЁРТКА: ПЕРЕКЛЮЧАТЕЛЬ (бык→лонг, медведь→шорт), косты 0.35% ═══")
print("плато = эдж; одиночная точка = подгонка. Формат: PF (n) [безтоп10%]\n")
hdr = f"{'дрейф':>6} {'MA':>4} |" + "".join(f"{'hold='+str(h):>20}" for h in (1, 6, 12, 24, 42))
print(hdr); print("-" * len(hdr))
grid = {}
for db_ in (90, 180, 360):
    for mb in (24, 48, 96):
        line = f"{db_:>6} {mb:>4} |"
        for mh in (1, 6, 12, 24, 42):
            R = regime_series(panel, drift_bars=db_, ma_bars=mb, min_periods=500, min_hold=mh)
            rt = R.index.values.astype("int64"); rl = R["label"].values
            sw = []
            for s in SIG:
                k = int(np.searchsorted(rt, s["t"], side="right")) - 1
                lab = rl[k] if 0 <= k < len(rl) else None
                if lab is None or (isinstance(lab, float) and np.isnan(lab)):
                    continue
                if (lab == BULL and s["side"] == "LONG") or (lab == BEAR and s["side"] == "SHORT"):
                    sw.append(s["pnl"])
            n, wr, med, pf, frag = stats(sw)
            grid[(db_, mb, mh)] = (n, pf, frag)
            line += f"{(f'{pf:.2f} ({n}) [{frag:+.0f}]' if pf else f'n={n}'):>20}"
        print(line)

vals = [(k, v) for k, v in grid.items() if v[1] is not None]
if vals:
    pfs = [v[1] for _, v in vals]
    good = [k for k, v in vals if v[1] > 1.3 and v[2] > 0]
    print(f"\nкомбинаций с оценкой: {len(vals)} · PF медиана {np.median(pfs):.2f} · "
          f"диапазон {min(pfs):.2f}–{max(pfs):.2f}")
    print(f"комбинаций, где PF>1.3 И хрупкость пройдена: {len(good)} из {len(vals)} "
          f"({100*len(good)/len(vals):.0f}%)")
    print(f"доля комбинаций с PF>1.0: {100*np.mean([p>1.0 for p in pfs]):.0f}%")
    print("\nВЕРДИКТ: " + ("ПЛАТО — эдж не зависит от выбора параметров"
                           if len(good) >= 0.5 * len(vals) else
                           ("частичное плато — держится не везде" if len(good) >= 0.25 * len(vals)
                            else "ПОДГОНКА — эдж живёт в отдельных точках")))
