"""ВХОД ПО СЛОМУ СТРУКТУРЫ НА LTF (Егор 16.09: «перепроверь на отскоках по кроссам на LTF или по сломам»).
В ядре триггера «слом» нет — есть кросс WT и пробой линии 2-4. Здесь добавлен третий: первый CHoCH на младшем ТФ
в сторону отскока (internal и swing по отдельности). Всё остальное боевое: стоп за экстремумом пятой, цель — конец
волны 4, окно входа 24 бара HTF, удержание 60 баров, кост 0.10%.
Запуск: python choch_entry.py run <тф> [монет] [процессов] · report <тф>
"""
import sys, pickle, time, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/choch_entry"); OUT.mkdir(parents=True, exist_ok=True)
LTF_SW, LTF_IL = 15, 4          # те же окна структуры, что в ядре
# LTF входа можно переопределить (Егор 16.09: «на LTF 3м сломы и 5м кроссы посмотри! почему ты не спускаешься ниже 15м?»)
_OVR = __import__("os").environ.get("LTF_OVERRIDE")
if _OVR:
    T.LTF = dict(T.LTF); T.LTF["4h"] = _OVR; T.LTF["1h"] = _OVR


def run_symbol(args):
    sym, tf = args
    out_p = OUT / (f"{tf}_{sym}.pkl" if not _OVR else f"{tf}@{_OVR}_{sym}.pkl")
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import fast_core; fast_core.patch()
    from core.waves.wave5_core import _setups_at, ltf_status, WaveParams, TF_MIN
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    t0 = time.time()
    try:
        dh = load_tf(sym, tf)
        dl = T.load_1m(sym) if T.LTF[tf] == "1m" else load_tf(sym, T.LTF[tf])
    except Exception as e:
        return sym, f"данные: {e}"
    if len(dh) < T.WARMUP + 100:
        return sym, "мало истории"
    tfm = TF_MIN[tf]; entry_h = T.ENTRY_BARS * tfm / 60; hold_h = T.HOLD_BARS * tfm / 60
    P = WaveParams(); rows = []; seen = set()
    dhr = dh.reset_index(drop=True); idx_h = dh.index
    hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
    st4 = run_structure(dhr[["open", "high", "low", "close"]], swing_len=P.sw, internal_len=P.il)
    sws = _swings(dhr["high"], dhr["low"], P.sw); swi = _swings(dhr["high"], dhr["low"], P.il)
    wt = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    dl_idx = dl.index.values
    for t in range(T.WARMUP, len(dh)):
        now = idx_h[t] + pd.Timedelta(minutes=tfm)
        if now < T.T0:
            continue
        try:
            setups = _setups_at(t, dh, idx_h, hh, lh, st4, sws, swi, wt, [], [], np.array([np.nan]), tfm, now, P, tf)
        except Exception:
            continue
        for s in setups:
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            if t5.tzinfo is not None:
                t5 = t5.tz_convert("UTC").tz_localize(None)
            i0 = int(np.searchsorted(dl_idx, np.datetime64(t5 - pd.Timedelta(minutes=8 * tfm)), "left"))
            i1 = int(np.searchsorted(dl_idx, np.datetime64(t5 + pd.Timedelta(hours=entry_h + hold_h)), "right"))
            w = dl.iloc[i0:i1]
            if len(w) < 200:
                continue
            nw = now.tz_localize(None) if getattr(now, "tzinfo", None) is not None else now
            base = ltf_status(s, w, P, after=nw, entry_w_h=entry_h, hold_h=hold_h, cost_pct=T.COST)
            long_ = s["side"] == "LONG"
            x = w.reset_index(drop=True)
            try:
                stl = run_structure(x[["open", "high", "low", "close"]], swing_len=LTF_SW, internal_len=LTF_IL)
            except Exception:
                continue
            lt = w.index.values
            j_after = int(np.searchsorted(lt, np.datetime64(nw)))            # не раньше детекции (каузально)
            j_win = int(np.searchsorted(lt, np.datetime64(t5 + pd.Timedelta(hours=entry_h))))
            op = x.open.values.astype(float); hi = x.high.values.astype(float); lo = x.low.values.astype(float)
            j5 = int(np.searchsorted(lt, np.datetime64(t5)))
            tp = float(s["p4_target"])
            for kind, want_int in (("CHoCH_internal", True), ("CHoCH_swing", False)):
                ev = [e for e in stl.events
                      if e.kind == "CHoCH" and e.internal == want_int and e.bull == long_ and j_after <= e.i < j_win]
                if not ev or ev[0].i + 1 >= len(x):
                    continue
                j = ev[0].i + 1
                e_px = float(op[j])
                ext = float(lo[j5:j].min()) if long_ else float(hi[j5:j].max())
                p5_at = min(float(s["p5"]), ext) if long_ else max(float(s["p5"]), ext)
                sl = p5_at * (1 - P.buf) if long_ else p5_at * (1 + P.buf)
                if ((tp <= e_px) or (sl >= e_px)) if long_ else ((tp >= e_px) or (sl <= e_px)):
                    continue                                                # цель/стоп не с той стороны
                end = lt[j] + np.timedelta64(int(hold_h * 60), "m")
                out_px, outc = None, None
                for k in range(j, len(x)):
                    if (lo[k] <= sl) if long_ else (hi[k] >= sl):
                        out_px, outc = sl, "stop"; break
                    if (hi[k] >= tp) if long_ else (lo[k] <= tp):
                        out_px, outc = tp, "target"; break
                    if lt[k] >= end:
                        out_px, outc = float(x.close.values[k]), "time"; break
                if out_px is None:
                    out_px, outc = float(x.close.values[-1]), "time"
                pnl = ((out_px - e_px) / e_px * 100) * (1 if long_ else -1) - T.COST
                rows.append({"sym": sym, "tf": tf, "key": s["key"], "side": s["side"], "trigger": kind,
                             "top_time": t5, "entry": e_px, "stop": sl, "target": tp,
                             "entry_t": pd.Timestamp(lt[j]), "outcome": outc, "pnl": round(pnl, 2),
                             "risk_pct": abs(e_px - sl) / e_px * 100, "tgt_pct": abs(tp - e_px) / e_px * 100,
                             "core_full": s["core_full"], "fractal": s["fractal"],
                             "base_pnl": base.get("pnl_pct"), "base_trigger": base.get("trigger")})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} входов за {time.time() - t0:.0f}с"


def report(tf):
    pat = f"{tf}_*.pkl" if not _OVR else f"{tf}@{_OVR}_*.pkl"
    rows = [r for f in glob.glob(str(OUT / pat)) for r in pickle.load(open(f, "rb"))]
    if not rows:
        print(f"{tf}: пусто"); return
    d = pd.DataFrame(rows)
    d["год"] = pd.to_datetime(d.top_time).dt.year
    print(f"\n=== {tf}: вход по слому структуры на {T.LTF[tf]} ===")
    g = d.groupby(["trigger", "side"]).agg(n=("pnl", "size"), ср=("pnl", "mean"), мед=("pnl", "median"),
                                           WR=("pnl", lambda x: (x > 0).mean() * 100), риск=("risk_pct", "median"),
                                           базовый=("base_pnl", "mean"))
    g["против базы"] = (g["ср"] - g["базовый"]).round(2)
    print(g.round(2).to_string())
    print("\nпо годам (среднее %):")
    print(d.pivot_table(index="год", columns="trigger", values="pnl", aggfunc="mean").round(2).to_string())
    print("\nотбор ядро fc:")
    print(d[d.core_full].groupby("trigger").agg(n=("pnl", "size"), ср=("pnl", "mean"),
                                                WR=("pnl", lambda x: (x > 0).mean() * 100)).round(2).to_string())


if __name__ == "__main__":
    cmd, tf = sys.argv[1], sys.argv[2]
    if cmd == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        import random; random.Random(5).shuffle(syms)
        if len(sys.argv) > 3:
            syms = syms[:int(sys.argv[3])]
        with Pool(int(sys.argv[4]) if len(sys.argv) > 4 else 8) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, [(s, tf) for s in syms]), 1):
                if i % 50 == 0:
                    print(f"  {i}/{len(syms)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report(tf)
