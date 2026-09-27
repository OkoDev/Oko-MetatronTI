"""«ВСЁ ЗАВИСИТ ОТ ВОЛН» (Егор 21.09) — проверка: контекст по ЯДРУ ВОЛН, а не по сырой ноге OKO-SM.
Для каждого 4h-бара каузально (как в тени, `wave5_core._setups_at`, WaveParams ядра) — какой 5-волновой импульс 4h ядро
ВИДИТ на этом баре (пятая provisional): направление, p0/p5, цель w4, флаги core/core_full (фрактал × канал × чередование ×
счёт). Затем каждая сделка всех механик (65k, ote_context/trades_ote_context.pkl) получает: последний импульс ядра,
видимый на закрытом 4h-баре до входа (не старше 60 баров = 10 дней) → отношение (сторона сделки = разворот после пятой /
по импульсу), качество импульса (core_full / core / просто пятёрка), откат цены входа от пятой к началу импульса
(за пятой <0 · у пятой <0.382 · цель коррекции 0.382–0.618 · 0.618–0.79 · 0.79–1 · за началом >1), свежесть.
Сравнение с контекстом сырой ноги: если деньги концентрируются там, где ядро видит завершённую пятёрку — прав Егор.
Запуск: python wave_phase_context.py scan [proc] · report"""
import sys, glob, pickle, time
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
import os
TF = os.environ.get("TF", "4h"); TF_H = {"1h": 1, "4h": 4, "1d": 24}[TF]
OUT = Path("G:/oko_lab/out/wave_phase_ctx") / ("" if TF == "4h" else TF); OUT.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)


def scan_symbol(sym):
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    import logging; logging.disable(logging.CRITICAL)
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from core.waves.wave5_core import WaveParams, _setups_at
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    t0 = time.time(); p = WaveParams()
    try:
        dh = load_tf(sym, TF)
    except Exception as e:
        return sym, f"данные {e}"
    if len(dh) < 6 * p.sw + 60:
        pickle.dump(pd.DataFrame(), open(out_p, "wb")); return sym, "мало истории"
    idx_h = dh.index; hh, lh = dh.high.values.astype(float), dh.low.values.astype(float)
    dhr = dh.reset_index(drop=True)
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=p.sw, internal_len=p.il)
    swings = _swings(dhr["high"], dhr["low"], p.sw); swings_i = _swings(dhr["high"], dhr["low"], p.il)
    wt1_h = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    rows = []
    for tt in range(6 * p.sw + 50, len(dhr)):
        try:
            out = _setups_at(tt, dh, idx_h, hh, lh, st, swings, swings_i, wt1_h, [], [], np.array([np.nan]), TF_H * 60, idx_h[tt] + pd.Timedelta(hours=TF_H), p, TF)
        except Exception:
            continue
        for s in out:
            rows.append({"tt": tt, "time": idx_h[tt], "key": s["key"], "side": s["side"], "p0": s["p0"], "p5": s["p5"], "p4": s["p4_target"],
                         "top_time": s["top_time"], "core": s["core"], "core_full": s["core_full"], "depth5": s["depth5"], "imp_pct": s["imp_pct"],
                         "fractal": s["fractal"], "altern": s["altern"], "count_ok": s["count_ok"]})
    pickle.dump(pd.DataFrame(rows), open(out_p, "wb"))
    return sym, f"баров {len(dhr)} · сетапов на барах {len(rows)} · импульсов {len({r['key'] for r in rows})} за {time.time() - t0:.0f}с"


def band(r):
    if r < 0: return "за пятой (импульс продолжился)"
    if r < 0.382: return "у пятой <0.382"
    if r <= 0.618: return "цель коррекции 0.382–0.618"
    if r <= 0.79: return "0.618–0.79"
    if r <= 1.0: return "0.79–1.0"
    return "за началом импульса >1"


def report():
    T = pd.read_pickle("G:/oko_lab/out/ote_context/trades_ote_context.pkl")
    S = {Path(f).stem: pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*USDT.pkl"))}
    rows = []
    for sym, g in T.groupby("sym"):
        s = S.get(sym)
        m1 = load_tf(sym, "1h").close
        if s is None or len(s) == 0:
            for r in g.itertuples():
                rows.append({"idx": r.Index, "wave": "нет импульса", "rel": "—", "q": "—", "band": "—", "fresh": "—"})
            continue
        s = s.sort_values("tt"); stimes = s.time.values
        for r in g.itertuples():
            t_close = np.datetime64(r.entry_t) - np.timedelta64(4, "h")            # бар 4h, закрытый к входу: time ≤ entry−4h
            k = int(np.searchsorted(stimes, t_close, "right")) - 1
            if k < 0 or (np.datetime64(r.entry_t) - stimes[k]) > np.timedelta64(60 * 4, "h"):
                rows.append({"idx": r.Index, "wave": "нет импульса", "rel": "—", "q": "—", "band": "—", "fresh": "—"}); continue
            x = s.iloc[k]; px = r.entry_px
            if not (px == px):
                j = int(np.searchsorted(m1.index.values, np.datetime64(r.entry_t), "right")) - 1; px = float(m1.values[j]) if j >= 0 else np.nan
            rng = x.p0 - x.p5
            rr = (px - x.p5) / rng if rng != 0 and px == px else np.nan
            rel = "разворот после пятой" if r.side == x.side else "по импульсу (после пятой)"
            q = "core_full" if x.core_full else ("core" if x.core else "пятёрка без ядра")
            age_h = (pd.Timestamp(r.entry_t) - pd.Timestamp(x.top_time)).total_seconds() / 3600
            rows.append({"idx": r.Index, "wave": "импульс " + ("вниз" if x.side == "LONG" else "вверх"), "rel": rel, "q": q,
                         "band": band(rr) if rr == rr else "—", "fresh": "<2 дн" if age_h < 48 else ("2–7 дн" if age_h < 168 else ">7 дн")})
    W = pd.DataFrame(rows).set_index("idx"); T = T.join(W); T.to_pickle(OUT / "trades_wave_ctx.pkl")
    def agg(g):
        return g.agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                     ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).assign(Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)
    print(f"сделок {len(T)} · с импульсом ядра в 10 дн до входа: {(T.wave != 'нет импульса').mean() * 100:.0f}%")
    print("\n=== механика × сторона × (нет импульса / разворот после пятой / по импульсу)"); print(agg(T.groupby(["mech", "side", "rel"])).to_string())
    print("\n=== механика × сторона × отношение × КАЧЕСТВО импульса (core_full / core / пятёрка)")
    g = agg(T[T.wave != "нет импульса"].groupby(["mech", "side", "rel", "q"])); print(g[g.n >= 30].to_string())
    print("\n=== механика × сторона × отношение × откат от пятой")
    g = agg(T[T.wave != "нет импульса"].groupby(["mech", "side", "rel", "band"])); print(g[g.n >= 30].to_string())
    print("\n=== свежесть импульса (разворот после пятой)")
    g = agg(T[T.rel == "разворот после пятой"].groupby(["mech", "side", "fresh"])); print(g[g.n >= 30].to_string())
    print("\n=== СРАВНЕНИЕ с контекстом сырой ноги 4h: клетки «против ноги у экстремума» × есть ли пятёрка ядра")
    for mech, side, band4, name in (("impulse_fib_1h", "LONG", "мелкая (<0.5)", "impulse_fib 1h LONG от низа 4h-даунлега"), ("choch_wavec", "SHORT", "OTE 0.62–0.79", "choch SHORT в 62–79% аплега"),
                                    ("rangefade", "LONG", "мелкая (<0.5)", "rangefade LONG у низа 4h-даунлега"), ("core_long", "LONG", "мелкая (<0.5)", "core_long у низа 4h-даунлега")):
        z = T[(T.mech == mech) & (T.side == side) & (T.rel_4h == "против ноги") & (T.band_4h == band4)]
        print(f"--- {name}: n {len(z)} ср {z.pnl.mean():+.2f}"); print(agg(z.groupby(["rel", "q"], dropna=False)).to_string())


if __name__ == "__main__":
    if sys.argv[1] == "scan":
        import pyarrow.parquet as pq
        syms = sorted(p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9)
        with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(scan_symbol, syms), 1):
                print(f"  {i}/{len(syms)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
