"""РАДАР С ЕГО НАСТОЯЩИМ ВЫХОДОМ: три цели 40/30/30 + безубыток после первой.

Первый прогон (radar_wave_hist) считал «вход → tp1 или стоп» и дал Δr −0.26 на боевой выборке
A/B. Но в бою радар выходит иначе (config radar_armed: tp_shares [40,30,30], be_after_tp1: true,
runner_*), поэтому вывод «убыточен» мог оказаться артефактом упрощённой модели.

Здесь считаем ровно боевой план: фил лимитом ≤45 мин → 40% на tp1 (и стоп в безубыток) →
30% на tp2 → 30% на tp3; остаток по стопу/по времени (48 ч). Раннер-трейл НЕ моделируем —
он может только добавить, поэтому оценка консервативная. Данные — наши 1m-паркеты (5m).
Контроль тот же: случайный момент ±10 дн, та же геометрия и тот же план выхода.

python radar_multi_tp.py
"""
import sys, glob, pickle, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from radar_wave_hist import klines5, COST, TTL_MIN, HOLD_H, FEED        # noqa: E402


def load_sigs():
    """Здесь нужны ВСЕ три цели (в radar_wave_hist бралась только tp1)."""
    import sqlite3
    c = sqlite3.connect(FEED)
    d = pd.read_sql("select ts, symbol, side, entry, sl, tp1, tp2, tp3, grade, wave_leg "
                    "from radar_orders where sig_type='pump' and entry>0 and sl>0 and tp1>0", c)
    d["t"] = pd.to_datetime(d.ts, unit="s")
    s = d.symbol.str.replace("/", "", regex=False).str.upper()
    d["sym"] = s.where(s.str.endswith("USDT"), s + "USDT")
    return d

OUT = Path("G:/oko_lab/out/radar_multi_tp"); OUT.mkdir(parents=True, exist_ok=True)
SHARES = (0.40, 0.30, 0.30)
N_CTL = 3


def run_plan(w, long_, e, sl, tps):
    """Боевой план выхода. Возвращает pnl% на полную позицию (сумма долей) или None."""
    hi, lo, cl = w.high.values, w.low.values, w.close.values
    n = min(HOLD_H * 12, len(w) - 1)
    if n <= 0:
        return None
    sgn = 1 if long_ else -1
    left, pnl, stop = 1.0, 0.0, sl
    hit = [False, False, False]
    for j in range(1, n + 1):
        # стоп проверяем первым: в одном баре он приоритетнее (консервативно)
        if (lo[j] <= stop) if long_ else (hi[j] >= stop):
            return pnl + left * (((stop - e) / e * 100) * sgn) - COST
        for i, tp in enumerate(tps):
            if hit[i] or tp is None or not np.isfinite(tp):
                continue
            reached = (hi[j] >= tp) if long_ else (lo[j] <= tp)
            if reached:
                hit[i] = True
                pnl += SHARES[i] * (((tp - e) / e * 100) * sgn)
                left -= SHARES[i]
                if i == 0:
                    stop = e                       # be_after_tp1
        if left <= 1e-9:
            return pnl - COST
    return pnl + left * (((cl[n] - e) / e * 100) * sgn) - COST


def one(args):
    sym, sigs = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, 0
    d = pd.DataFrame(sigs).sort_values("t")
    k5 = klines5(sym, d.t.min() - pd.Timedelta(days=12), d.t.max() + pd.Timedelta(hours=HOLD_H + 4))
    if k5 is None or len(k5) < 100:
        pickle.dump([], open(out_p, "wb")); return sym, 0
    rs = random.Random(sum(map(ord, sym)) + 5)
    rows = []
    for r in d.itertuples():
        long_ = str(r.side).upper() == "LONG"
        e, sl = float(r.entry), float(r.sl)
        tps = [float(x) if x and float(x) > 0 else None for x in (r.tp1, r.tp2, r.tp3)]
        if e <= 0 or sl <= 0 or tps[0] is None:
            continue
        w = k5[k5.index >= r.t]
        if w.empty or w.index[0] > r.t + pd.Timedelta(minutes=10):
            continue
        hi, lo = w.high.values, w.low.values
        fill = None
        for j in range(min(max(1, TTL_MIN // 5), len(w))):
            if (lo[j] <= sl) if long_ else (hi[j] >= sl):
                fill = "стоп до фила"; break
            if (lo[j] <= e) if long_ else (hi[j] >= e):
                fill = j; break
        if fill is None or isinstance(fill, str):
            rows.append({"sym": sym, "t": r.t, "side": "LONG" if long_ else "SHORT", "grade": r.grade,
                         "wave_leg": r.wave_leg, "исход": fill or "нет фила", "pnl": np.nan, "ctl": np.nan})
            continue
        pnl = run_plan(w.iloc[fill:], long_, e, sl, tps)
        rsk = abs(e - sl) / e
        tg = [abs(t - e) / e if t else None for t in tps]
        ctl = []
        for _ in range(N_CTL):
            tc = r.t + pd.Timedelta(days=rs.uniform(-10, 10))
            wc = k5[k5.index >= tc]
            if len(wc) < 20:
                continue
            ec = float(wc.open.values[0])
            slc = ec * (1 - rsk) if long_ else ec * (1 + rsk)
            tpc = [ec * (1 + g) if long_ else ec * (1 - g) for g in tg if g]
            v = run_plan(wc, long_, ec, slc, tpc + [None] * (3 - len(tpc)))
            if v is not None:
                ctl.append(v)
        rows.append({"sym": sym, "t": r.t, "side": "LONG" if long_ else "SHORT", "grade": r.grade,
                     "wave_leg": r.wave_leg, "исход": "исполнена", "pnl": pnl,
                     "ctl": float(np.mean(ctl)) if ctl else np.nan})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, len(rows)


if __name__ == "__main__":
    d = load_sigs()
    groups = [(s, g.to_dict("records")) for s, g in d.groupby("sym")]
    print(f"монет {len(groups)} · сигналов {len(d)}", flush=True)
    with Pool(5) as pool:
        done = 0
        for sym, k in pool.imap_unordered(one, groups):
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(groups)}", flush=True)
    R = []
    for f in glob.glob(str(OUT / "*.pkl")):
        R += pickle.load(open(f, "rb"))
    x = pd.DataFrame(R)
    pd.set_option("display.width", 260)
    print(f"\nсигналов: {len(x)}")
    print(x["исход"].value_counts().to_string())
    f = x[(x["исход"] == "исполнена") & x.pnl.notna()].copy()
    f["Δ"] = f.pnl - f.ctl
    ab = f[f.grade.isin(["A", "B"])]
    print(f"\n=== ВЕСЬ журнал: n={len(f)} · средн {f.pnl.mean():+.2f} · медиана {f.pnl.median():+.2f} · "
          f"сумма {f.pnl.sum():+.0f} · контроль {f.ctl.mean():+.2f} · Δr {f['Δ'].mean():+.2f}")
    print(f"=== БОЕВАЯ выборка A/B: n={len(ab)} · средн {ab.pnl.mean():+.2f} · медиана {ab.pnl.median():+.2f} · "
          f"сумма {ab.pnl.sum():+.0f} · контроль {ab.ctl.mean():+.2f} · Δr {ab['Δ'].mean():+.2f} · WR {100*(ab.pnl>0).mean():.0f}%")
    print(f"   хрупкость A/B: без верхних 10% {ab.pnl.sum()-ab.pnl.nlargest(max(1,len(ab)//10)).sum():+.0f}")
    print(f"   охват A/B: монет в плюсе {(ab.groupby('sym').pnl.sum()>0).sum()} из {ab.sym.nunique()}")
    print("\n=== по grade")
    print(f.groupby("grade", dropna=False).agg(n=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"),
          медиана=("pnl", "median"), Δr=("Δ", "mean")).round(2).to_string())
    print("\n=== A/B × свой счёт ног (гейт радара leg>=3)")
    a = ab.copy(); a["leg"] = np.where(a.wave_leg.isna(), "нет", np.where(a.wave_leg < 3, "leg<3", "leg>=3"))
    print(a.groupby("leg").agg(n=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"), Δr=("Δ", "mean")).round(2).to_string())
    print("\n=== A/B × сторона")
    print(ab.groupby("side").agg(n=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"), Δr=("Δ", "mean")).round(2).to_string())
    print("\n=== A/B × месяц")
    m = ab.assign(мес=ab.t.dt.to_period("M").astype(str))
    print(m.groupby("мес").agg(n=("pnl", "size"), средн=("pnl", "mean"), сумма=("pnl", "sum"), Δr=("Δ", "mean")).round(2).to_string())
