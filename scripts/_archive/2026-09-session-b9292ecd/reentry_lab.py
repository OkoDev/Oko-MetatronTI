"""ПОВТОРНЫЙ ВХОД ПОСЛЕ СТОПА (Егор 16.09: «иначе теряем монету вместе с пробитым стопом»).
Сетапы — продовый core.waves.wave5_core.mark_impulse на каждом закрытом 4h-баре; первичный вход — ltf_status (правила тени:
триггер после детекции, 15m, стоп за экстремумом пятой, цель конец w4, 240 ч). Если первичный вышел ПО СТОПУ — считаем
повторный вход тем же кодом, что пойдёт в тень: core.waves.wave5_core.reentry_status (новый экстремум за старой пятой + первый
internal CHoCH 3m против хода, стоп за новым экстремумом ×stop_mult, цель — конец w4, окно 96 ч от вершины).
Варианты стопа 1×/2×/3× буфера — проверка закона размера стопа. Данные: 1m-паркеты (163 монеты).
Запуск: python reentry_lab.py run [N] [proc] | ctl | report"""
import sys, pickle, time, random, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
OUT = Path("G:/oko_lab/out/reentry2"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2023-02-01")
# варианты входа: рыночный по слому со стопом 1×/2×/3× расстояния до экстремума и ЛИМИТ на откате 0.5 со стопом 0.886
# (Егор 16.09: «стоп 14.9% слишком большой — нужно ждать откат»); лимит включается, когда рыночный риск > cap
VARIANTS = [("market1", dict(stop_mult=1.0, max_risk_pct=1e9)), ("market2", dict(stop_mult=2.0, max_risk_pct=1e9)),
            ("market3", dict(stop_mult=3.0, max_risk_pct=1e9)), ("limit5", dict(stop_mult=1.0, max_risk_pct=5.0)),
            ("limit3", dict(stop_mult=1.0, max_risk_pct=3.0))]


def load(sym):
    # ТФ берутся из предрасчитанного кэша G:\oko_lab\tf (tfcache), а не пересобираются из 1m на каждом запуске
    return {tf: load_tf(sym, tf) for tf in ("3m", "5m", "15m", "4h")}


def load5(sym):
    """Только 5m (контроли): load() строил 3m/5m/15m/4h для КАЖДОЙ контрольной монеты — 1.5 ГБ на процесс и 88% ЦП (Егор 16.09)."""
    return load_tf(sym, "5m", cols=["open", "high", "low", "close"])


def walk5(d5, t0, long_, e, sl, tp, hold_h=240, cost=0.10):
    w = d5[(d5.index >= t0) & (d5.index < t0 + pd.Timedelta(hours=hold_h))]
    if len(w) < 12:
        return np.nan
    lo, hi = w.low.values, w.high.values
    for k in range(len(w)):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - cost
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - cost
    return ((float(w.close.values[-1]) - e) / e * 100) * (1 if long_ else -1) - cost


def run_symbol(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from core.waves.wave5_core import _setups_at, ltf_status, reentry_status, WaveParams, TF_MIN
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    t_start = time.time()
    try:
        F = load(sym)
    except Exception as e:
        return sym, f"данные: {e}"
    d4, d15, d3 = F["4h"], F["15m"], F["3m"]
    if len(d4) < 500 or len(d3) < 20000:
        return sym, "мало истории"
    P = WaveParams(); rows = []; seen = set()
    # структура/свинги/WT считаются ОДИН раз на монету (как в merge_lab), дальше _setups_at по каждому бару — иначе mark_impulse
    # пересчитывает всё на каждом баре: 157с на год против ~30с
    dhr = d4.reset_index(drop=True); idx_h = d4.index
    hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
    st4 = run_structure(dhr[["open", "high", "low", "close"]], swing_len=P.sw, internal_len=P.il)
    sw4 = _swings(dhr["high"], dhr["low"], P.sw); swi4 = _swings(dhr["high"], dhr["low"], P.il)
    wt4 = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    for t in range(400, len(d4)):
        now = d4.index[t] + pd.Timedelta(hours=4)
        if now < T0:
            continue
        try:
            setups = _setups_at(t, d4, idx_h, hh, lh, st4, sw4, swi4, wt4, [], [], np.array([np.nan]), TF_MIN["4h"], now, P, "4h")
        except Exception:
            continue
        for s in setups:
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            w15 = d15[(d15.index >= t5 - pd.Timedelta(days=4)) & (d15.index <= t5 + pd.Timedelta(hours=96 + 250))]
            if len(w15) < 300:
                continue
            ls = ltf_status(s, w15, P, after=now, entry_w_h=96.0, hold_h=240.0)
            if ls.get("outcome") != "stop":
                continue                                     # повторный вход считаем только после выбитого стопа
            base = {"sym": sym, "key": s["key"], "side": s["side"], "core": s["core"], "core_full": s["core_full"],
                    "fractal": s["fractal"], "depth5": s["depth5"], "imp_pct": s["imp_pct"], "top_time": t5,
                    "p5": s["p5"], "p4": s["p4_target"], "first_entry": ls["entry_price"], "first_stop": ls["stop"],
                    "first_risk_pct": abs(ls["entry_price"] - ls["stop"]) / ls["entry_price"] * 100,
                    "first_pnl": ls["pnl_pct"], "stop_time": pd.Timestamp(ls["exit_time"])}
            w3 = d3[(d3.index >= t5 - pd.Timedelta(hours=6)) & (d3.index <= t5 + pd.Timedelta(hours=96 + 250))]
            for nm, kw in VARIANTS:
                r = reentry_status(s, w3, ls["exit_time"], P, entry_w_h=96.0, hold_h=240.0, **kw)
                if r["entry_price"] is None:
                    rows.append({**base, "mult": nm, "mode": r.get("mode"), "re_entry": None}); continue
                rows.append({**base, "mult": nm, "mode": r.get("mode"), "re_entry": r["entry_price"], "re_stop": r["stop"], "re_ext": r["ext"],
                             "re_entry_t": r["entry_time"], "re_outcome": r["outcome"], "re_pnl": r["pnl_pct"],
                             "re_risk_pct": abs(r["entry_price"] - r["stop"]) / r["entry_price"] * 100,
                             "re_tgt_pct": abs(s["p4_target"] - r["entry_price"]) / r["entry_price"] * 100,
                             "wait_h": (pd.Timestamp(r["entry_time"]) - pd.Timestamp(ls["exit_time"])).total_seconds() / 3600})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len([r for r in rows if r.get('re_entry')])} повторных из {len(set(r['key'] for r in rows))} стопов за {time.time() - t_start:.0f}с"


def controls(args):
    sym, trades, others = args
    rs = random.Random(sum(map(ord, sym)) + 7)
    try:
        import psutil; psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS)
    except Exception:
        pass
    d5 = load5(sym); cache = {}; out = []
    for tr in trades:
        long_ = tr["side"] == "LONG"; et = pd.Timestamp(tr["re_entry_t"]); rsk = tr["re_risk_pct"] / 100; tg = tr["re_tgt_pct"] / 100
        def geo(dd5, t0):
            w = dd5[dd5.index >= t0]
            if len(w) < 12:
                return np.nan
            e = float(w.open.iloc[0])
            return walk5(dd5, w.index[0], long_, e, e * (1 - rsk) if long_ else e * (1 + rsk), e * (1 + tg) if long_ else e * (1 - tg))
        a = [geo(d5, et + pd.Timedelta(minutes=5 * rs.randint(-30 * 288, 30 * 288))) for _ in range(10)]
        b = []
        for o in rs.sample(others, min(6, len(others))):
            if o not in cache:
                if len(cache) > 2:
                    cache.clear()                            # держим максимум 3 чужих 5m — иначе память растёт до гигабайтов
                try:
                    cache[o] = load5(o)
                except Exception:
                    cache[o] = None
            if cache[o] is not None:
                b.append(geo(cache[o], et))
        out.append({"sym": sym, "key": tr["key"], "mult": tr["mult"], "ctl_rand": np.nanmean(a) if a else np.nan,
                    "ctl_time": np.nanmean(b) if b else np.nan})
    return out


if __name__ == "__main__":
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    if sys.argv[1] == "run":
        random.Random(5).shuffle(syms)
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 8) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, syms), 1):
                print(f"{i}/{len(syms)} {s}: {msg}", flush=True)
    elif sys.argv[1] == "ctl":
        rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
        d = pd.DataFrame(rows); d = d[d.re_pnl.notna()]
        jobs = [(s, g.to_dict("records"), [o for o in syms if o != s]) for s, g in d.groupby("sym")]
        with Pool(2) as pool:                                # 2 процесса: машина должна оставаться рабочей
            ctl = pd.DataFrame([r for rr in pool.imap_unordered(controls, jobs) for r in rr])
        pickle.dump(ctl, open(OUT.parent / "reentry_ctl.pkl", "wb")); print("ok", len(ctl))
