"""Поглощение подструктуры (merge) — замер 15.09 (Егор: «да» на план LINK).
Сетапы — ПРОДОВЫМ кодом core.waves.wave5_core (_setups_at на каждом закрытом 4h-баре, WaveParams по умолчанию),
в двух вариантах merge=False / merge=True. Сделки — ПРОДОВЫМ ltf_status (правила тени: триггер после закрытия бара
детекции, вход open следующего 15m-бара, стоп фиксирован, цель конец w4, 240 ч, кост 0.10%).
Контроли: (A) случайный вход той же монеты ±30 дней, та же сторона и геометрия (стоп%, цель%, 240 ч), 20 розыгрышей;
(B) по времени — те же моменты входа на других монетах вселенной (рыночный момент), та же геометрия.
Запуск: python merge_lab.py inv | run [N] | report"""
import sys, sqlite3, pickle, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
OUT = Path(__file__).with_name("merge_lab.pkl")
DB = ROOT / "ohlcv_cache.db"


def inventory():
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        r = pd.read_sql("SELECT symbol, timeframe, COUNT(*) n, MIN(time) t0, MAX(time) t1 FROM ohlcv_cache "
                        "WHERE timeframe IN ('4h','15m') GROUP BY symbol, timeframe", c)
    r["t0"] = pd.to_datetime(r.t0, unit="ms"); r["t1"] = pd.to_datetime(r.t1, unit="ms")
    p = r.pivot(index="symbol", columns="timeframe", values=["n", "t0", "t1"])
    both = p.dropna()
    both = both[(both[("n", "4h")] >= 3000) & (both[("n", "15m")] >= 40000)]
    print("монет с 4h≥3000 и 15m≥40000:", len(both))
    for y in range(2022, 2027):
        live = ((both[("t0", "15m")] <= f"{y}-03-01") & (both[("t1", "15m")] >= f"{y}-10-01")).sum()
        print(f"  {y}: монет с 15m почти весь год {live}")
    return list(both.index)


def load(sym, tf):
    from research_harness import load as L
    return L(sym, tf)


def run_symbol(sym):
    from core.waves.wave5_core import WaveParams, _setups_at, ltf_status, TF_MIN
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    try:
        dh = load(sym, "4h"); dl = load(sym, "15m")
        if len(dh) < 1000 or len(dl) < 20000:
            return []
        dhr = dh.reset_index(drop=True); idx_h = dh.index
        hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
        rows = []
        for merge in (False, True):
            p = WaveParams(merge=merge)
            st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=p.sw, internal_len=p.il)
            swings = _swings(dhr["high"], dhr["low"], p.sw); swings_i = _swings(dhr["high"], dhr["low"], p.il)
            wt1 = calculate_wt(dhr.copy())["wt1"].values.astype(float)
            seen = {}
            for t in range(6 * p.sw + 50, len(dhr)):
                now = idx_h[t] + pd.Timedelta(hours=4)
                for s in _setups_at(t, dh, idx_h, hh, lh, st, swings, swings_i, wt1, [], [], np.array([np.nan]), TF_MIN["4h"], now, p, "4h"):
                    if s["key"] in seen:
                        continue
                    seen[s["key"]] = s
                    t5 = pd.Timestamp(s["top_time"])
                    w = dl[(dl.index >= t5 - pd.Timedelta(days=4)) & (dl.index <= t5 + pd.Timedelta(hours=96 + 250))]
                    if len(w) < 400:
                        continue
                    ls = ltf_status(s, w, p, after=now, entry_w_h=96.0, hold_h=240.0)
                    rows.append({"sym": sym, "merge": merge, "key": s["key"], "side": s["side"], "absorbed": s["absorbed"],
                                 "detect": now, "top_time": t5, "imp_pct": s["imp_pct"], "fractal": s["fractal"], "depth5": s["depth5"],
                                 "core": s["core"], "core_full": s["core_full"], "count_ok": s["count_ok"], "altern": s["altern"],
                                 "p4": s["p4_target"], "wave_times": s["wave_times"], "wave_px": s["wave_px"],
                                 "trigger": ls["trigger"], "entry_time": ls["entry_time"], "entry": ls["entry_price"], "stop": ls["stop"],
                                 "outcome": ls["outcome"], "pnl": ls["pnl_pct"], "pnl_trail": ls.get("pnl_trail"), "exit_time": ls["exit_time"]})
        return rows
    except Exception as e:
        print(f"[{sym}] {type(e).__name__} {e}", flush=True)
        return []


def walk(dl, t0, long_, e, sl, tp, hold_h=240.0, cost=0.10):
    """Исход той же геометрии со входа по open бара t0 (стоп раньше цели на баре), как в ltf_status."""
    w = dl[(dl.index >= t0) & (dl.index <= t0 + pd.Timedelta(hours=hold_h + 1))]
    if len(w) < 10:
        return np.nan
    e = float(w.open.iloc[0]); s_ = e * (1 + sl) if not long_ else e * (1 - sl); t_ = e * (1 + tp) if long_ else e * (1 - tp)
    lo, hi, cl = w.low.values, w.high.values, w.close.values
    for k in range(len(w)):
        if (lo[k] <= s_) if long_ else (hi[k] >= s_):
            x = s_; break
        if (hi[k] >= t_) if long_ else (lo[k] <= t_):
            x = t_; break
    else:
        x = cl[-1]
    return ((x - e) / e * 100) * (1 if long_ else -1) - cost


def controls(args):
    sym, trades, all_syms = args
    rs = random.Random(hash(sym) & 0xffff)
    dl = load(sym, "15m"); out = []
    cache = {}
    for tr in trades:
        long_ = tr["side"] == "LONG"; e = tr["entry"]
        sl = abs(e - tr["stop"]) / e; tp = abs(tr["p4"] - e) / e
        et = pd.Timestamp(tr["entry_time"]).tz_localize("UTC") if pd.Timestamp(tr["entry_time"]).tzinfo is None else pd.Timestamp(tr["entry_time"])
        a = []
        for _ in range(20):
            t0 = et + pd.Timedelta(minutes=15 * rs.randint(-30 * 96, 30 * 96))
            v = walk(dl, t0, long_, e, sl, tp)
            if np.isfinite(v):
                a.append(v)
        b = []
        for o in rs.sample([s for s in all_syms if s != sym], min(8, len(all_syms) - 1)):
            if o not in cache:
                cache[o] = load(o, "15m")
            v = walk(cache[o], et, long_, e, sl, tp)
            if np.isfinite(v):
                b.append(v)
        out.append({"key": tr["key"], "sym": sym, "merge": tr["merge"], "ctl_rand": np.mean(a) if a else np.nan, "ctl_time": np.mean(b) if b else np.nan})
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "inv"
    if mode == "inv":
        inventory()
    elif mode == "run":
        syms = inventory()
        n = int(sys.argv[2]) if len(sys.argv) > 2 else len(syms)
        random.Random(19).shuffle(syms); syms = sorted(syms[:n])
        with Pool(8) as pool:
            res = pool.map(run_symbol, syms, chunksize=1)
        df = pd.DataFrame([r for rr in res for r in rr])
        print("сетапов:", len(df), df.groupby("merge").size().to_dict())
        tr = df[df.pnl.notna()]
        jobs = [(s, g.to_dict("records"), syms) for s, g in tr.groupby("sym")]
        with Pool(8) as pool:
            ctl = pd.DataFrame([r for rr in pool.map(controls, jobs, chunksize=1) for r in rr])
        pickle.dump({"setups": df, "ctl": ctl, "syms": syms}, open(OUT, "wb"))
        print("ok", OUT)
