"""КАРТА «РЕЖИМ × МЕХАНИКА × СТОРОНА» (план 19.09, «инвертированный поиск»: режим → сторона → механика).
Оси режима — каузально, по закрытому дню до входа: ΔUSDT.D за 30 дн (главная: corr с дрейфом альтов −0.73),
дрейф вселенной 90 дн (медиана доходности монет), ΔBTC.D за 30 дн. Серии: usdtd_daily.pkl, universe_drift_daily.pkl.
Механики (сделки с pnl% после костов, risk% для R, контроли той же геометрии):
  core_long / core_short          — ядро волн 4h (tf_sweep, боевые правила; кросс и line24)      [есть]
  core_short_1d                    — шорт ядра как коррекция ДНЕВНОГО даун-тренда (медвежий тренд 1d, line24 или фрактал)
  wt_deep_long_70 / _75            — лонг от глубокой перепроданности WT 1h → первый кросс 15m, выход касание +60/+70,
                                     без стопа, 400 баров 15m, одна позиция на монету (SPOT_DUMP_GRID-кандидат, память
                                     wt_deep_oversold_long_candidate); контроль — случайный вход той же длительности
Запуск: python regime_map_lab.py build [монет] [процессов]  ·  python regime_map_lab.py report
"""
import sys, glob, pickle, time, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/regime_map"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01"); COST = 0.10


# ── механика: лонг от глубокой перепроданности WT (правило из памяти, одна позиция на монету) ──────────────
def wt_deep_long(sym, iz=70, ez=60, life=12, timeout=400):
    from core.indicators.indicators import calculate_wt
    h = load_tf(sym, "1h"); m = load_tf(sym, "15m")
    if len(h) < 500 or len(m) < 2000:
        return []
    wh = calculate_wt(h.copy()); wm = calculate_wt(m.copy())
    w1h, w2h = wh.wt1.values, wh.wt2.values; w1m, w2m = wm.wt1.values, wm.wt2.values
    hi = h.index.values; mi = m.index.values; op = m.open.values; cl = m.close.values; lo = m.low.values
    rows = []; busy = -1
    for i in range(1, len(h)):
        if hi[i] < np.datetime64(T0):
            continue
        if not (w1h[i - 1] <= w2h[i - 1] and w1h[i] > w2h[i] and w1h[i] < -iz):
            continue                                                    # разрешение: кросс вверх из глубокой зоны на 1h
        j0 = int(np.searchsorted(mi, hi[i] + np.timedelta64(1, "h")))  # после закрытия часа
        j1 = int(np.searchsorted(mi, hi[i] + np.timedelta64(1 + life, "h")))
        if j0 <= busy:
            continue
        ent = None
        for j in range(max(j0, 1), min(j1, len(m) - 2)):
            if w1m[j - 1] <= w2m[j - 1] and w1m[j] > w2m[j]:
                ent = j + 1; break                                      # первый кросс 15m → open следующего бара
        if ent is None or ent <= busy:
            continue
        e = float(op[ent]); k_out = min(ent + timeout, len(m) - 1); outc = "time"
        for k in range(ent, min(ent + timeout, len(m))):
            if w1m[k] >= ez:
                k_out = k; outc = "target"; break
        pnl = (float(cl[k_out]) / e - 1) * 100 - COST
        mae = (lo[ent:k_out + 1].min() / e - 1) * 100
        rows.append({"sym": sym, "mech": f"wt_deep_long_{iz}", "side": "LONG", "entry_t": pd.Timestamp(mi[ent]), "pnl": round(pnl, 3),
                     "risk_pct": max(0.5, -mae), "hold_bars": k_out - ent, "outcome": outc, "mae": round(mae, 2)})
        busy = k_out
    return rows


def _ctl_duration(m, rows, rs, oth):
    """Контроли для сделок без стопа/цели: случайный вход той же ДЛИТЕЛЬНОСТИ (±30 дн той же монеты ×8, чужие монеты в тот же момент)."""
    mi = m.index.values; cl = m.close.values
    def ret(dd, t, bars):
        ii = dd.index.values; c = dd.close.values
        j = int(np.searchsorted(ii, np.datetime64(t)))
        if j + bars >= len(c) or j < 0:
            return np.nan
        return (c[j + bars] / c[j] - 1) * 100 - COST
    for r in rows:
        a = [ret(m, r["entry_t"] + pd.Timedelta(minutes=rs.randint(-43200, 43200)), r["hold_bars"]) for _ in range(8)]
        b = [ret(o, r["entry_t"], r["hold_bars"]) for o in oth]
        r["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
        r["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan


def build_symbol(args):
    sym, others = args
    out_p = OUT / f"wt_{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    t0 = time.time(); rows = []
    try:
        for iz, ez in ((70, 60), (75, 70)):
            rows += wt_deep_long(sym, iz, ez)
    except Exception as e:
        return sym, f"ошибка {type(e).__name__}: {e}"
    if rows:
        m = load_tf(sym, "15m"); rs = random.Random(sum(map(ord, sym)) + 21); oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "15m"))
            except Exception:
                pass
        _ctl_duration(m, rows, rs, oth)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сделок за {time.time() - t0:.0f}с"


def core_rows():
    """Ядро волн 4h: обе стороны + шорт как коррекция дневного даун-тренда (тренд 1d медвежий на закрытом дне до вершины)."""
    from core.indicators.indicators import calculate_trend
    rows = [r for r in T.rows_of("4h") if r.get("entered")]
    d = pd.DataFrame(rows); c = pickle.load(open(T.OUT / "ctl_4h.pkl", "rb"))
    d = d.merge(c[["sym", "key", "ctl_rand", "ctl_time"]], on=["sym", "key"], how="left")
    d["entry_t"] = pd.to_datetime(d.entry_t); d["mech"] = np.where(d.side == "LONG", "core_long", "core_short")
    # дневной тренд каузально
    tr_cache = {}; tr = []
    for r in d.itertuples():
        if r.sym not in tr_cache:
            try:
                dd = load_tf(r.sym, "1d"); t1 = pd.Series(calculate_trend(dd.copy())["trend"].values, index=dd.index); tr_cache[r.sym] = t1
            except Exception:
                tr_cache[r.sym] = None
        t1 = tr_cache[r.sym]
        if t1 is None:
            tr.append(np.nan); continue
        day = pd.Timestamp(r.top_time).tz_localize(None).floor("D") if pd.Timestamp(r.top_time).tzinfo else pd.Timestamp(r.top_time).floor("D"); i = t1.index.searchsorted(day) - 1
        tr.append(float(t1.iloc[i]) if i >= 0 else np.nan)
    d["trend1d"] = tr
    ex = d[(d.side == "SHORT") & (d.trend1d < 0) & ((d.trigger == "line24") | (d.fractal == True))].copy(); ex["mech"] = "core_short_1d"
    return pd.concat([d, ex], ignore_index=True)


def report():
    wt = pd.DataFrame([r for f in glob.glob(str(OUT / "wt_*.pkl")) for r in pickle.load(open(f, "rb"))])
    core = core_rows()
    A = pd.concat([core[["sym", "mech", "side", "entry_t", "pnl", "risk_pct", "ctl_rand", "ctl_time"]], wt[["sym", "mech", "side", "entry_t", "pnl", "risk_pct", "ctl_rand", "ctl_time"]]], ignore_index=True)
    A["entry_t"] = pd.to_datetime(A.entry_t); A["R"] = A.pnl / A.risk_pct; A["год"] = A.entry_t.dt.year
    G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl")
    G["dU30"] = G.usdt_d - G.usdt_d.shift(30); G["dB30"] = G.btc_d - G.btc_d.shift(30)
    day = A.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    A["dU30"] = G.dU30.reindex(day.values).values; A["dB30"] = G.dB30.reindex(day.values).values; A["drift90"] = U.drift90.reindex(day.values).values
    A = A.dropna(subset=["dU30", "drift90"])
    A["USDT.D"] = np.where(A.dU30 > 0.3, "↑", np.where(A.dU30 < -0.3, "↓", "="))
    A["дрейф"] = pd.cut(A.drift90, [-999, -15, 15, 999], labels=["дрейф↓", "нейтр", "бык"])
    A["BTC.D"] = np.where(A.dB30 > 1, "↑", np.where(A.dB30 < -1, "↓", "="))
    A.to_pickle(OUT / "map_trades.pkl")
    pd.set_option("display.width", 250)

    def agg(g):
        return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                     срR=("R", "mean"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).assign(
            Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)
    print(f"сделок {len(A)} · механик {A.mech.nunique()} · {A.entry_t.min():%Y-%m} → {A.entry_t.max():%Y-%m}\n")
    print("=== механика: всё"); print(agg(A.groupby("mech")).to_string())
    print("\n=== механика × год (ср %)"); print(A.groupby(["mech", "год"]).pnl.mean().round(2).unstack("год").to_string())
    print("\n=== КАРТА: механика × USDT.D-30 (ср % · Δt · n)")
    for col, nm in (("ср", "ср %"), ("Δt", "Δ к контролю по времени"), ("Δr", "Δ к случайному"), ("n", "n")):
        t = agg(A.groupby(["mech", "USDT.D"]))[col].unstack("USDT.D"); print(f"--- {nm}"); print(t.to_string())
    print("\n=== КАРТА: механика × дрейф 90 (ср % / Δt / n)")
    g = agg(A.groupby(["mech", "дрейф"], observed=True)); print(g[["n", "ср", "Δt", "Δr"]].unstack("дрейф").to_string())
    print("\n=== КАРТА 2D: механика × USDT.D × дрейф (ср %, n)")
    g = agg(A.groupby(["mech", "USDT.D", "дрейф"], observed=True)); print(g[["n", "WR", "ср", "Δt"]].to_string())
    for m_ in sorted(A.mech.unique()):
        z = A[A.mech == m_]; top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
        print(f"  хрупкость {m_}: n {len(z)} · сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · монет+ {(z.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {sum(z[z['год'] == y].pnl.mean() > 0 for y in z['год'].unique())}/{z['год'].nunique()}")


if __name__ == "__main__":
    if sys.argv[1] == "build":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(build_symbol, jobs), 1):
                if i % 50 == 0 or i <= 3:
                    print(f"  {i}/{len(jobs)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
