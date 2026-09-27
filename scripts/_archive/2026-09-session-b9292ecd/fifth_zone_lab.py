"""Сетап №1 (Егор 15.09 «начинай»): ПЯТАЯ В ПРОЦЕССЕ → ВХОД В ЗОНЕ ЗАВЕРШЕНИЯ ПО СЛОМУ 3m.
Зона и счёт — ПРОДОВЫЙ core.waves.wave_progress.analyze_progress (1h свинг 60, уровни пятой/C=A/нога 1D/пивоты → cluster_zone),
считается каждые 4 часа строго по ЗАКРЫТЫМ барам. Взводится при счёте 0–4 (не вложенном) с зоной.
Вход «choch»: касание зоны → первый internal CHoCH 3m против хода (OKO-SM swing 50 / internal 5), пока экстремум после касания
не ушёл за дальний край зоны больше чем на её ширину; вход open следующего 3m-бара; стоп за экстремумом после касания (буфер 0.15%);
цель — точка 4 (первая цель сценария A); удержание ≤240 ч; кост 0.10%. Отмена: закрытие 1h за точкой 4 / 48 ч без слома.
Вход «touch» (сравнение): open следующего бара после касания, стоп за дальним краем зоны + ширина зоны, та же цель.
Данные: 1m-паркеты Binance C:/oko_history/1m. Запуск: python fifth_zone_lab.py run [N] | ctl | report"""
import sys, pickle, time, random, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
OUT = Path("G:/oko_lab/out/fifth_zone"); OUT.mkdir(parents=True, exist_ok=True)
HOLD_H, WAIT_H, BUF, COST = 240, 48, 0.0015, 0.10


def load(sym):
    # предрасчитанный кэш G:\oko_lab\tf; здесь индексы tz-aware UTC, как было в прежнем load()
    return {tf: load_tf(sym, tf, tz="UTC") for tf in ("3m", "5m", "1h", "1d")}


def walk(d5, t0, long_, e, sl, tp, hold_h=HOLD_H):
    """Исход со входа в t0 по цене e на 5m-барах, открытых не раньше t0; стоп раньше цели на одном баре."""
    w = d5[(d5.index >= t0) & (d5.index < t0 + pd.Timedelta(hours=hold_h))]
    if len(w) < 12:
        return np.nan, None, None
    lo, hi = w.low.values, w.high.values
    for k in range(len(w)):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - COST, "stop", w.index[k]
        if (hi[k] >= tp) if long_ else (lo[k] <= tp):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - COST, "target", w.index[k]
    x = float(w.close.values[-1])
    return ((x - e) / e * 100) * (1 if long_ else -1) - COST, "time", w.index[-1]


def run_symbol(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from core.waves.wave_progress import analyze_progress
    from core.waves.wave_analyst import daily_leg
    from core.smc.oko_sm_engine import run_structure
    t_start = time.time()
    try:
        F = load(sym)
    except Exception as e:
        return sym, f"данные: {e}"
    d3, d5, d1, dd = F["3m"], F["5m"], F["1h"], F["1d"]
    c1 = d1.index + pd.Timedelta(hours=1); cd = dd.index + pd.Timedelta(days=1)
    st = run_structure(d3[["open", "high", "low", "close"]].reset_index(drop=True), swing_len=50, internal_len=5)
    ev = [(e.i, bool(e.bull)) for e in st.events if e.internal and e.kind == "CHoCH"]
    ev_i = np.array([i for i, _ in ev], dtype=np.int64); ev_b = np.array([b for _, b in ev], dtype=bool)
    t3 = d3.index; c3 = (t3 + pd.Timedelta(minutes=3)).values
    lo3, hi3, cl3, op3 = d3.low.values, d3.high.values, d3.close.values, d3.open.values
    grid = pd.date_range(max(d1.index[0] + pd.Timedelta(days=75), pd.Timestamp("2023-02-01", tz="UTC")).ceil("4h"),
                         d1.index[-1] - pd.Timedelta(hours=HOLD_H), freq="4h")
    rows, done = [], set()
    for T in grid:
        j1 = int(np.searchsorted(c1.values, T.to_datetime64(), side="right")); jd = int(np.searchsorted(cd.values, T.to_datetime64(), side="right"))
        if j1 < 1000 or jd < 60:
            continue
        h1 = d1.iloc[max(0, j1 - 1500):j1]; day = dd.iloc[max(0, jd - 250):jd]
        leg_fn = lambda t0_, want_top_, p_ext, t_ext, _day=day, _T=T: daily_leg(None, t0_, want_top_, p_ext, t_ext, _T, 10, dd=_day)
        rep = {"sym": sym, "now": str(T), "ltf": "3m", "structure": None, "leg": None, "ltf_state": None, "scenarios": [], "text": []}
        try:
            rep = analyze_progress(sym, None, h1, None, T, leg_fn, rep, dl3=None)
        except Exception:
            continue
        cnt, z = rep.get("progress"), rep.get("zone")
        if not cnt or cnt["k"] != 4 or cnt.get("nested") or not z:
            continue
        key = tuple(round(p, 10) for p in cnt["px"])
        if key in done:
            continue
        down = cnt["down"]; long_ = down; p4 = cnt["px"][4]; width = max(z["hi"] - z["lo"], 0.005 * z["mid"])
        price = float(h1.close.iloc[-1])
        if (price <= z["hi"]) if down else (price >= z["lo"]):
            done.add(key); continue                                   # уже в зоне/за ней на момент взвода — не свежий сетап
        a = int(np.searchsorted(c3, T.to_datetime64(), side="left")); b_ = int(np.searchsorted(c3, (T + pd.Timedelta(hours=4)).to_datetime64(), side="left"))
        touched = None
        for m in range(a, min(b_, len(t3))):
            if ((cl3[m] > p4) if down else (cl3[m] < p4)) and (pd.Timestamp(c3[m]).minute == 0):
                done.add(key); break                                  # закрытие 1h за точкой 4 — сценарий A отменён
            if (lo3[m] <= z["hi"]) if down else (hi3[m] >= z["lo"]):
                touched = m; break
        if touched is None:
            continue
        done.add(key)
        leg = rep.get("leg") or {}
        base = {"sym": sym, "armed": T, "side": "LONG" if long_ else "SHORT", "zone_lo": z["lo"], "zone_hi": z["hi"], "zone_score": z["score"],
                "zone_w_pct": (z["hi"] - z["lo"]) / z["mid"] * 100, "p4": p4, "p0": cnt["px"][0], "leg_zone": leg.get("zone"), "leg_depth": leg.get("depth"),
                "prov": bool(cnt.get("prov")), "absorbed": cnt.get("absorbed", 0), "touch_t": pd.Timestamp(t3[touched])}
        # --- вход «touch»
        if touched + 1 < len(t3):
            e = float(op3[touched + 1]); sl = (z["lo"] - width) * (1 - BUF) if long_ else (z["hi"] + width) * (1 + BUF)
            if (long_ and sl < e < p4) or ((not long_) and p4 < e < sl):
                pnl, how, tx = walk(d5, t3[touched + 1], long_, e, sl, p4)
                rows.append({**base, "entry_kind": "touch", "entry_t": t3[touched + 1], "entry": e, "stop": sl, "pnl": pnl, "outcome": how,
                             "risk_pct": abs(e - sl) / e * 100, "tgt_pct": abs(p4 - e) / e * 100})
        # --- вход «choch»
        ext = lo3[touched] if long_ else hi3[touched]; t_lim = t3[touched] + pd.Timedelta(hours=WAIT_H)
        k0 = int(np.searchsorted(ev_i, touched, side="left"))
        m = touched
        for q in range(k0, len(ev_i)):
            i_ev = int(ev_i[q])
            if t3[i_ev] > t_lim:
                break
            seg = lo3[m:i_ev + 1] if long_ else hi3[m:i_ev + 1]
            if len(seg):
                ext = min(ext, float(seg.min())) if long_ else max(ext, float(seg.max()))
            m = i_ev + 1
            if (ext < z["lo"] - width) if long_ else (ext > z["hi"] + width):
                break                                                 # зона пробита — сетап отменён
            if ev_b[q] != long_ or i_ev + 1 >= len(t3):
                continue
            e = float(op3[i_ev + 1]); sl = ext * (1 - BUF) if long_ else ext * (1 + BUF)
            if not ((long_ and sl < e < p4) or ((not long_) and p4 < e < sl)):
                break
            pnl, how, tx = walk(d5, t3[i_ev + 1], long_, e, sl, p4)
            rows.append({**base, "entry_kind": "choch", "entry_t": t3[i_ev + 1], "entry": e, "stop": sl, "pnl": pnl, "outcome": how,
                         "risk_pct": abs(e - sl) / e * 100, "tgt_pct": abs(p4 - e) / e * 100,
                         "wait_h": (t3[i_ev + 1] - t3[touched]).total_seconds() / 3600})
            break
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} входов за {time.time() - t_start:.0f}с"


def controls(args):
    sym, trades, others = args
    rs = random.Random(sum(map(ord, sym)))
    F = load(sym); d5 = F["5m"]; cache = {}
    out = []
    for tr in trades:
        long_ = tr["side"] == "LONG"; et = pd.Timestamp(tr["entry_t"]); rsk = tr["risk_pct"] / 100; tg = tr["tgt_pct"] / 100
        def geo(dd5, t0):
            w = dd5[dd5.index >= t0]
            if len(w) < 12:
                return np.nan
            e = float(w.open.iloc[0])
            return walk(dd5, w.index[0], long_, e, e * (1 - rsk) if long_ else e * (1 + rsk), e * (1 + tg) if long_ else e * (1 - tg))[0]
        a = [geo(d5, et + pd.Timedelta(minutes=5 * rs.randint(-30 * 288, 30 * 288))) for _ in range(10)]
        b = []
        for o in rs.sample(others, min(6, len(others))):
            if o not in cache:
                try:
                    cache[o] = load(o)["5m"]
                except Exception:
                    cache[o] = None
            if cache[o] is not None:
                b.append(geo(cache[o], et))
        out.append({"sym": sym, "entry_t": tr["entry_t"], "entry_kind": tr["entry_kind"], "ctl_rand": np.nanmean(a) if a else np.nan,
                    "ctl_time": np.nanmean(b) if b else np.nan})
    return out


if __name__ == "__main__":
    syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
    if sys.argv[1] == "run":
        random.Random(11).shuffle(syms)
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        print("монет:", len(syms), flush=True)
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, syms), 1):
                print(f"{i}/{len(syms)} {s}: {msg}", flush=True)
    elif sys.argv[1] == "ctl":
        rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
        d = pd.DataFrame(rows); d = d[d.pnl.notna()]
        have = sorted(d.sym.unique())
        jobs = [(s, g.to_dict("records"), [o for o in syms if o != s]) for s, g in d.groupby("sym")]
        with Pool(6) as pool:
            ctl = pd.DataFrame([r for rr in pool.imap_unordered(controls, jobs) for r in rr])
        pickle.dump(ctl, open(Path(__file__).with_name("fifth_zone_ctl.pkl"), "wb")); print("ok", len(ctl))
