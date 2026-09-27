"""РЕПЛЕЙ impulse_fib_15m «КАК В БОЮ» — единственный шорт-источник с положительным замером (дверь EQH), для карты
«режим × механика × сторона». ОДИН калькулятор: core.smc.impulse_fib.find_setup + gates; дверь EQH — та же логика, что
bot/loops/impulse_fib_runner._eqh_alt_entry (detect_equal_levels, лаг 3 бара, порог 1.0 ATR, сравнение на ЗАКРЫТОМ баре).
Конфиг боя (config trading.impulse_fib_15m): sides [short] (здесь считаем ОБЕ стороны — карта требует), require_gates,
стоп 1.5–3.234%, лимит на 0.382 отката, ожидание 12 баров, стоп 2.5·ATR, цель −1.618, удержание 96 баров, дрейф-гейт
в SHADOW (не блокирует). Шаг сканирования — 2 бара 15m (луп сканирует не каждый бар), одна позиция на монету.
Контроли: та же геометрия — случайный сдвиг ±30 дн той же монеты (×8) и 5 других монет в тот же момент.
Запуск: python impulse_fib_15m_replay.py run [процессов] (вселенная — монеты с историей ≥2 лет) · report
"""
import sys, glob, pickle, time, random, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk, geo

OUT = Path("G:/oko_lab/out/impulse_fib_15m_replay"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01"); COST = 0.10
STEP, TAIL = 2, 420
MIN_STOP, MAX_STOP = 1.5, 3.234
EQH_TOL, EQH_LAG = 1.0, 3


def eqh_door(d0, side, atr):
    """Цена (закрытый бар) в пределах EQH_TOL·ATR от подтверждённого EQH (short) / EQL (long)."""
    from core.smc.smc_engine import detect_equal_levels
    price = float(d0["close"].iloc[-1]); tag = "EQH" if side == "short" else "EQL"
    cutoff = d0.index[-EQH_LAG] if len(d0) > EQH_LAG else d0.index[-1]
    best = None
    try:
        for e in detect_equal_levels(d0):
            if len(e) < 5 or str(e[4]).upper() != tag or pd.Timestamp(e[2]) > cutoff:
                continue
            lvl = (float(e[1]) + float(e[3])) / 2.0; dist = abs(price - lvl) / atr
            if best is None or dist < best:
                best = dist
    except Exception:
        return False, np.nan
    return (best is not None and best <= EQH_TOL), (best if best is not None else np.nan)


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
    from core.smc.impulse_fib import find_setup, gates, _atr, WAIT_BARS, HOLD_BARS
    t_start = time.time()
    try:
        m = load_tf(sym, "15m")
    except Exception as e:
        return sym, f"данные: {e}"
    if len(m) < 5000:
        return sym, "мало истории"
    mi = m.index.values; hi, lo, cl, op = m.high.values, m.low.values, m.close.values, m.open.values
    start = max(TAIL, int(np.searchsorted(mi, np.datetime64(T0))))
    rows = []; seen = set(); busy_until = -1; n_setups = n_gates = n_stop = 0
    for t in range(start, len(m) - 2, STEP):
        if t <= busy_until:
            continue
        df = m.iloc[t - TAIL + 1:t + 1]                         # закрытые бары ≤ t
        s = find_setup(df, symbol=sym, drop_last=False)
        if "reason" in s or not s["live"]:
            continue
        key = (s["origin_ts"], s["side"])
        if key in seen:
            continue
        seen.add(key); n_setups += 1
        if not (MIN_STOP <= s["stop_pct"] <= MAX_STOP):
            n_stop += 1; continue
        g = gates(s)
        if not g["passed"]:
            n_gates += 1; continue
        long_ = s["side"] == "long"
        atr_now = float(_atr(df).iloc[-1])
        eqh, eqh_dist = eqh_door(df, s["side"], atr_now) if atr_now > 0 else (False, np.nan)
        e, sl, tp = float(s["entry"]), float(s["sl"]), float(s["tp"])
        # лимит: ожидание WAIT_BARS баров от конца импульса (b) — сколько уже прошло (age), столько меньше осталось
        remain = max(1, WAIT_BARS - int(s["age"]))
        fill = None
        for j in range(t + 1, min(t + 1 + remain, len(m))):
            if (lo[j] <= e) if long_ else (hi[j] >= e):
                fill = j; break
        if fill is None:
            rows.append({"sym": sym, "side": s["side"].upper(), "filled": False, "entry_t": pd.Timestamp(mi[t]), "eqh": eqh, "eqh_dist": eqh_dist,
                         "stop_pct": s["stop_pct"], "pnl": np.nan, "outcome": "no_fill", "with_trend": s["with_trend"], "vratio": s["vratio"], "regime": s["regime"]})
            continue
        pnl, outc, k_out = walk(hi, lo, cl, fill, fill + HOLD_BARS, long_, e, sl, tp)
        seg_h, seg_l = hi[fill:k_out + 1], lo[fill:k_out + 1]
        mfe = (seg_h.max() / e - 1) * 100 if long_ else (1 - seg_l.min() / e) * 100
        rows.append({"sym": sym, "side": s["side"].upper(), "filled": True, "entry_t": pd.Timestamp(mi[fill]), "signal_t": pd.Timestamp(mi[t]),
                     "eqh": eqh, "eqh_dist": eqh_dist, "entry": e, "stop": sl, "target": tp, "risk_pct": abs(e - sl) / e * 100,
                     "tgt_pct": abs(tp - e) / e * 100, "stop_pct": s["stop_pct"], "pnl": round(pnl, 3), "outcome": outc, "mfe": round(mfe, 2),
                     "with_trend": s["with_trend"], "vratio": s["vratio"], "regime": s["regime"], "hold": HOLD_BARS})
        busy_until = k_out
    filled = [r for r in rows if r["filled"]]
    if filled:
        rs = random.Random(sum(map(ord, sym)) + 13); oth = []
        for o in rs.sample(others, min(5, len(others))):
            try:
                oth.append(load_tf(o, "15m"))
            except Exception:
                pass
        for r in filled:
            long_ = r["side"] == "LONG"; rsk, tg = r["risk_pct"] / 100, r["tgt_pct"] / 100; et = r["entry_t"]
            a = [geo(m, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, HOLD_BARS) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, HOLD_BARS) for o in oth]
            r["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            r["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump({"rows": rows, "n_setups": n_setups, "n_gates": n_gates, "n_stop": n_stop}, open(out_p, "wb"))
    return sym, f"сетапов {n_setups} · стоп вне {n_stop} · гейты {n_gates} · сделок {len(filled)} за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median"),
                 MFE=("mfe", "median")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def report():
    P = [pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*.pkl"))]
    d = pd.DataFrame([r for p in P for r in p["rows"]]); f = d[d.filled].copy(); f["год"] = pd.to_datetime(f.entry_t).dt.year
    tot = {k: sum(p[k] for p in P) for k in ("n_setups", "n_gates", "n_stop")}
    print(f"монет {len(P)} · сетапов {tot['n_setups']} · стоп вне зоны {tot['n_stop']} · не прошли гейты {tot['n_gates']} · без филла {int((~d.filled).sum())} · сделок {len(f)} · "
          f"{pd.to_datetime(f.entry_t).min():%Y-%m} → {pd.to_datetime(f.entry_t).max():%Y-%m}\n")
    pd.set_option("display.width", 250)
    f["дверь"] = np.where(f.eqh, "EQH/EQL", "без")
    print("=== сторона × дверь EQH"); print(agg(f.groupby(["side", "дверь"])).to_string())
    print("\n=== сторона × год"); print(agg(f.groupby(["side", "год"])).to_string())
    print("\n=== SHORT × дверь × год"); print(agg(f[f.side == "SHORT"].groupby(["дверь", "год"])).to_string())
    G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl")
    G["dU30"] = G.usdt_d - G.usdt_d.shift(30)
    day = pd.to_datetime(f.entry_t).dt.floor("D") - pd.Timedelta(days=1)
    f["dU30"] = G.dU30.reindex(day.values).values; f["drift90"] = U.drift90.reindex(day.values).values
    f["USDT.D"] = np.where(f.dU30 > 0.3, "↑", np.where(f.dU30 < -0.3, "↓", "=")); f["дрейф"] = pd.cut(f.drift90, [-999, -15, 15, 999], labels=["дрейф↓", "нейтр", "бык"])
    print("\n=== сторона × дверь × USDT.D-30"); print(agg(f.groupby(["side", "дверь", "USDT.D"])).to_string())
    print("\n=== сторона × дверь × дрейф"); print(agg(f.groupby(["side", "дверь", "дрейф"], observed=True)).to_string())
    for (side, door), z in f.groupby(["side", "дверь"]):
        top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum()
        print(f"  хрупкость {side} {door}: n {len(z)} · сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · монет+ {(z.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · исходы {z.outcome.value_counts().to_dict()}")
    f.to_pickle(OUT / "trades.pkl")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        import pyarrow.parquet as pq
        syms = [p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9]
        syms = sorted(syms); print(f"вселенная: {len(syms)} монет с историей ≥2 лет", flush=True)
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(replay_symbol, jobs), 1):
                print(f"  {i}/{len(jobs)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
