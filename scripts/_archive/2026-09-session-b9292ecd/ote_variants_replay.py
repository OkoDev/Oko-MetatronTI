"""ote_nested НА ДРУГИХ ТФ (Егор 20.09: «ote_nested может на 1h перевести?!») — тот же реплей генератора «как в бою»
(см. ote_nested_replay.py), но с ДРУГИМ сетапом шкафа: SETUP=1h_15m_pull (зона 1h, вход 15m) · 1h_5m_pull · 1d_1h_pull (зона 1d,
вход 1h; в бою 1d = ресемпл 300 баров 1h = 12 дней → зона 1d невозможна, здесь подаём настоящие 1d бары) · 4h_1h_pull (контроль
= боевой). Остальное как в бою: FIRE → premium (fvg_held), 1d cascade-gate, лимит по sig.entry TTL 4 ч, филл касанием 15m,
SL/TP из сигнала (TP = tp1 = 1R), удержание 72 ч, одна позиция на монету, кост 0.10, оба контроля.
Запуск: SETUP=1h_15m_pull python ote_variants_replay.py run [монет] [процессов] · SETUP=... report
"""
import sys, glob, pickle, time, random, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ

SETUP = os.environ.get("SETUP", "1h_15m_pull")
HTF, LTF, STYPE = SETUP.split("_")[0], SETUP.split("_")[1], SETUP.split("_")[2]
TIER = {"1h_15m_pull": 2, "1h_5m_pull": 1, "1d_1h_pull": 1, "4h_1h_pull": 2, "1d_15m_pull": 1, "4h_15m_pull": 2}.get(SETUP, 2)
OUT = Path(f"G:/oko_lab/out/ote_variants/{SETUP}"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp(os.environ.get("T0", "2020-06-01"))
COST = 0.10
TAILS = {"3m": 600, "5m": 500, "15m": 400, "1h": 300, "4h": 200, "1d": 200}
TTL_H, HOLD_H = 4, 72
MIN_STRENGTH = 70


def _strength(sig):
    s = max(60, min(95, 55 + int(sig.weight * 30)))
    premium = getattr(sig, "setup_id", "") == SETUP and "fvg_held" in (sig.confirmations or [])
    return s if premium else min(s, 65)


def replay_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.ote_signal_generator import OTESignalGenerator
    from core.smc.smc_engine import ote_retest_setups
    from core.indicators.indicators import calculate_trend
    t_start = time.time()
    try:
        D = {tf: load_tf(sym, tf) for tf in ("3m", "5m", "15m", "1h", "4h", "1d")}
    except Exception as e:
        return sym, f"данные: {e}"
    h1 = D["1h"]
    if len(h1) < 1000:
        return sym, "мало истории"
    gen = OTESignalGenerator()
    gen.setups = [{"id": SETUP, "htf": HTF, "ltf": LTF, "type": STYPE, "direction": "both", "enabled": True, "tier": TIER}]
    idx = {tf: D[tf].index.values for tf in D}
    d15 = D["15m"]; i15 = d15.index.values; hi15, lo15, cl15 = d15.high.values, d15.low.values, d15.close.values
    rows = []; busy_until = pd.Timestamp.min; n_fire = n_prem = n_gate = n_nofill = n_gen = 0
    start = max(int(np.searchsorted(h1.index.values, np.datetime64(T0))), 300)
    trend_cache = {}
    zz_depth, zz_dev = gen._zz(HTF); zones = []; zones_k = -1
    for t_i in range(start, len(h1) - 1):
        t = h1.index[t_i]
        if t < busy_until:
            continue
        kh = int(np.searchsorted(idx[HTF], np.datetime64(t), "right"))
        if kh < 50:
            continue
        if kh != zones_k:                                      # зоны HTF — раз на новый бар HTF, тем же калькулятором
            zones_k = kh
            try:
                sth = ote_retest_setups(D[HTF].iloc[max(0, kh - TAILS[HTF]):kh], depth=zz_depth, dev_mult=zz_dev,
                                        only_choch=False, provisional=True)
                zones = [x["ote"] for x in sth]
            except Exception:
                zones = []
        px = float(h1.close.values[t_i])
        if not any(lo_ <= px <= hi_ for lo_, hi_ in zones):
            continue
        dfs = {}
        for tf, n in TAILS.items():
            k = int(np.searchsorted(idx[tf], np.datetime64(t), "right"))
            if k < 50:
                dfs = None; break
            dfs[tf] = D[tf].iloc[max(0, k - n):k]
        if not dfs:
            continue
        if HTF != "1d":                                         # как в бою: 1d = ресемпл хвоста 1h
            h = dfs["1h"]
            dfs["1d"] = pd.DataFrame({"open": h.open.resample("1D").first(), "high": h.high.resample("1D").max(),
                                      "low": h.low.resample("1D").min(), "close": h.close.resample("1D").last()}).dropna()
        n_gen += 1
        try:
            sigs = gen.generate(sym, dfs)
        except Exception:
            continue
        fires = [s for s in sigs if s.status == "FIRE"]
        if not fires:
            continue
        n_fire += len(fires)
        sig = max(fires, key=lambda s: (_strength(s), s.conf_score))
        if _strength(sig) < MIN_STRENGTH:
            continue
        n_prem += 1
        long_ = str(sig.direction).lower() == "long"
        day = t.floor("D")
        if day not in trend_cache:
            k1 = int(np.searchsorted(idx["1d"], np.datetime64(day)))
            dd = D["1d"].iloc[max(0, k1 - 60):k1]
            try:
                tr = calculate_trend(dd.copy())["trend"].iloc[-1] if len(dd) >= 43 else np.nan
            except Exception:
                tr = np.nan
            trend_cache[day] = tr
        tr = trend_cache[day]
        if tr == tr and ((tr < 0) if long_ else (tr > 0)):
            n_gate += 1
            continue
        e, sl, tp = float(sig.entry), float(sig.sl), float(sig.tp1)
        if not (e > 0 and sl > 0 and tp > 0) or (long_ and not (sl < e < tp)) or (not long_ and not (tp < e < sl)):
            continue
        j0 = int(np.searchsorted(i15, np.datetime64(t + pd.Timedelta(hours=1))))
        j_ttl = int(np.searchsorted(i15, np.datetime64(t + pd.Timedelta(hours=1 + TTL_H))))
        fill = None
        for j in range(j0, min(j_ttl, len(d15))):
            if (lo15[j] <= e) if long_ else (hi15[j] >= e):
                fill = j; break
        if fill is None:
            n_nofill += 1; busy_until = t + pd.Timedelta(hours=TTL_H)
            rows.append({"sym": sym, "t": t, "side": "LONG" if long_ else "SHORT", "filled": False, "risk_pct": abs(e - sl) / e * 100, "pnl": np.nan, "outcome": "no_fill"})
            continue
        end = int(np.searchsorted(i15, np.datetime64(pd.Timestamp(i15[fill]) + pd.Timedelta(hours=HOLD_H))))
        pnl, outc, k_out = None, "time", min(end, len(d15)) - 1
        for k in range(fill, min(end, len(d15))):
            if (lo15[k] <= sl) if long_ else (hi15[k] >= sl):
                pnl, outc, k_out = ((sl - e) / e * 100) * (1 if long_ else -1), "stop", k; break
            if (hi15[k] >= tp) if long_ else (lo15[k] <= tp):
                pnl, outc, k_out = ((tp - e) / e * 100) * (1 if long_ else -1), "target", k; break
        if pnl is None:
            pnl = ((float(cl15[k_out]) - e) / e * 100) * (1 if long_ else -1)
        rows.append({"sym": sym, "t": t, "side": "LONG" if long_ else "SHORT", "filled": True, "entry": e, "stop": sl, "target": tp,
                     "conf": "+".join(sig.confirmations or []), "risk_pct": abs(e - sl) / e * 100, "tgt_pct": abs(tp - e) / e * 100,
                     "pnl": round(pnl - COST, 3), "outcome": outc, "entry_t": pd.Timestamp(i15[fill]), "hold": HOLD_H, "trend1d": tr})
        busy_until = pd.Timestamp(i15[k_out]) + pd.Timedelta(minutes=15)
    filled = [r for r in rows if r["filled"]]
    if filled:
        from triangle_lab import geo
        rs = random.Random(sum(map(ord, sym)) + 9); oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "15m"))
            except Exception:
                pass
        hold_bars = HOLD_H * 4
        for r in filled:
            long_ = r["side"] == "LONG"; rsk, tg = r["risk_pct"] / 100, r["tgt_pct"] / 100; et = r["entry_t"]
            a = [geo(d15, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, hold_bars) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, hold_bars) for o in oth]
            r["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            r["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump({"rows": rows, "n_fire": n_fire, "n_prem": n_prem, "n_gate": n_gate, "n_nofill": n_nofill, "n_gen": n_gen}, open(out_p, "wb"))
    return sym, f"generate {n_gen} · FIRE {n_fire} · premium {n_prem} · гейт 1d {n_gate} · без филла {n_nofill} · сделок {len(filled)} за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median")).assign(
        Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    P = [pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*.pkl"))]
    d = pd.DataFrame([r for p in P for r in p["rows"]]); f = d[d.filled].copy(); f["год"] = pd.to_datetime(f.entry_t).dt.year
    tot = {k: sum(p[k] for p in P) for k in ("n_gen", "n_fire", "n_prem", "n_gate", "n_nofill")}
    pd.set_option("display.width", 250)
    print(f"{SETUP}: монет {len(P)} · generate {tot['n_gen']} · FIRE {tot['n_fire']} · premium {tot['n_prem']} · гейт 1d {tot['n_gate']} · без филла {tot['n_nofill']} · сделок {len(f)} · "
          f"{pd.to_datetime(f.entry_t).min():%Y-%m} → {pd.to_datetime(f.entry_t).max():%Y-%m}")
    print(agg(f.groupby("side")).to_string())
    print("\n=== сторона × год"); print(agg(f.groupby(["side", "год"])).to_string())
    f["стоп"] = pd.qcut(f.risk_pct, 3, labels=["узкий", "средний", "широкий"], duplicates="drop")
    print("\n=== сторона × корзина стопа"); print(agg(f.groupby(["side", "стоп"], observed=True)).to_string())
    G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl")
    G["dU30"] = G.usdt_d - G.usdt_d.shift(30); day = pd.to_datetime(f.entry_t).dt.floor("D") - pd.Timedelta(days=1)
    f["dU30"] = G.dU30.reindex(day.values).values; f["drift90"] = U.drift90.reindex(day.values).values
    f["USDT.D"] = np.where(f.dU30 > 0.3, "↑", np.where(f.dU30 < -0.3, "↓", "=")); f["дрейф"] = pd.cut(f.drift90, [-999, -15, 15, 999], labels=["дрейф↓", "нейтр", "бык"])
    print("\n=== сторона × USDT.D"); print(agg(f.groupby(["side", "USDT.D"])).to_string())
    print("\n=== сторона × дрейф"); print(agg(f.groupby(["side", "дрейф"], observed=True)).to_string())
    for s_, z in f.groupby("side"):
        top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum(); yrs = z.groupby("год").pnl.mean()
        print(f"  хрупкость {s_}: n {len(z)} · сумма {z.pnl.sum():.0f} · без топ-10% {z.pnl.sum() - top:.0f} · монет+ {(z.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(yrs > 0).sum()}/{len(yrs)} · исходы {z.outcome.value_counts().to_dict()} · R ср {(z.pnl / z.risk_pct).mean():.2f}")
    f.to_pickle(OUT / "trades.pkl")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        import pyarrow.parquet as pq
        syms = sorted(p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9)
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            rs = random.Random(1); syms = sorted(rs.sample(syms, int(sys.argv[2])))
        print(f"{SETUP}: вселенная {len(syms)} монет", flush=True)
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(replay_symbol, jobs), 1):
                print(f"  {i}/{len(jobs)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
