"""ШОРТ ПОСЛЕ ЛОНГА (Егор 16.09: «а шорт после лонга?»).
Логика: наш LONG — это отскок после нисходящего импульса, цель = конец волны 4. Когда коррекция отработала,
падение по идее продолжается — значит после закрытия лонга есть разворотный шорт (в разборе это сценарий
«лонг только до коррекции, затем против»).

Считается на тех же сетапах 4h: берём лонги, дошедшие до цели (или вышедшие по времени/стопу — отдельными срезами),
и от момента выхода открываем шорт на 15m:
  вход  — по слому SWING-структуры вниз (тот же триггер, что выиграл у кросса) либо сразу по цене выхода;
  стоп  — за максимумом, достигнутым после вершины пятой (буфер как в ядре);
  цели  — p5 (низ пятой) и расширение 1.272 от коррекции.
Контроль — случайный вход той же геометрии (tf_sweep.controls). Кост 0.10%.
Запуск: python short_after_long.py run [монет] [процессов] · report
"""
import os, sys, pickle, time, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/short_after_long" + (os.environ.get("HOLD_SUF",""))); OUT.mkdir(parents=True, exist_ok=True)
TF, LTF = "4h", "15m"
# 17.09: цели measured move (50-85% хода) за 60 баров 15m = 15 ч не проходят физически — в первом прогоне
# у ветки «цель взята» было 0 достигнутых целей и 345 выходов по времени. Горизонт задаётся переменной.
HOLD_BARS, COST = int(os.environ.get("HOLD_BARS", "60")), 0.10


def run_symbol(sym):
    out_p = OUT / f"{sym}.pkl"
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
        dh = load_tf(sym, TF); dl = load_tf(sym, LTF)
    except Exception as e:
        return sym, f"данные: {e}"
    if len(dh) < T.WARMUP + 100:
        return sym, "мало истории"
    tfm = TF_MIN[TF]; entry_h = T.ENTRY_BARS * tfm / 60; hold_h = T.HOLD_BARS * tfm / 60
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
            setups = _setups_at(t, dh, idx_h, hh, lh, st4, sws, swi, wt, [], [], np.array([np.nan]), tfm, now, P, TF)
        except Exception:
            continue
        for s in setups:
            if s["key"] in seen or s["side"] != "LONG":
                continue                                   # шорт-разворот считаем только после ЛОНГА (отскока)
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            if t5.tzinfo is not None:
                t5 = t5.tz_convert("UTC").tz_localize(None)
            i0 = int(np.searchsorted(dl_idx, np.datetime64(t5 - pd.Timedelta(minutes=4 * tfm)), "left"))
            i1 = int(np.searchsorted(dl_idx, np.datetime64(t5 + pd.Timedelta(hours=entry_h + hold_h * 2)), "right"))
            w = dl.iloc[i0:i1]
            if len(w) < 200:
                continue
            nw = now.tz_localize(None) if getattr(now, "tzinfo", None) is not None else now
            ls = ltf_status(s, w, P, after=nw, entry_w_h=entry_h, hold_h=hold_h, cost_pct=COST)
            if ls.get("entry_price") is None or ls.get("exit_time") is None:
                continue
            p5 = float(s["p5"]); p4 = float(s["p4_target"])
            x = w.reset_index(drop=True); lt = w.index.values
            j_out = int(np.searchsorted(lt, np.datetime64(pd.Timestamp(ls["exit_time"]))))
            if j_out + 5 >= len(x):
                continue
            hi_, lo_, op_, cl_ = x.high.values, x.low.values, x.open.values, x.close.values
            j5 = int(np.searchsorted(lt, np.datetime64(t5)))
            base = {"sym": sym, "key": s["key"], "long_outcome": ls["outcome"], "long_pnl": ls["pnl_pct"],
                    "top_time": t5, "core_full": s["core_full"], "imp_pct": s["imp_pct"], "depth5": s["depth5"]}
            # два варианта входа в шорт
            try:
                stl = run_structure(x[["open", "high", "low", "close"]], swing_len=15, internal_len=4)
            except Exception:
                continue
            ev = [e for e in stl.events if e.kind == "CHoCH" and not e.internal and not e.bull and e.i > j_out]
            for nm, j in (("сразу по выходу", j_out + 1), ("по слому 15m вниз", (ev[0].i + 1) if ev else None)):
                if j is None or j >= len(x):
                    continue
                e_px = float(op_[j])
                top = float(hi_[j5:j].max())                       # максимум коррекции к моменту входа
                sl = top * (1 + P.buf)
                rng = top - p5
                p0 = float(s["p0"]); leg = p0 - p5                 # вся нисходящая нога (0→5)
                # цели ДВУХ сеток (Егор: «по волновому принципу мы знаем и цели на коррекцию,
                # и цели на случай продолжения»): продолжение = measured move от ноги (лестница build_ote),
                # коррекционные — от размаха отскока
                for tgt_nm, tp in (("цель p5", p5), ("цель 1.272", top - 1.272 * rng),
                                   ("расш 0.618 ноги", p5 - 0.618 * leg), ("расш 1.0 ноги", p5 - 1.0 * leg),
                                   ("расш 1.618 ноги", p5 - 1.618 * leg)):
                    if tp >= e_px or sl <= e_px:
                        continue
                    end = lt[j] + np.timedelta64(int(HOLD_BARS * 15), "m")
                    out_px, outc = None, None
                    for k in range(j, len(x)):
                        if hi_[k] >= sl:
                            out_px, outc = sl, "stop"; break
                        if lo_[k] <= tp:
                            out_px, outc = tp, "target"; break
                        if lt[k] >= end:
                            out_px, outc = float(cl_[k]), "time"; break
                    if out_px is None:
                        out_px, outc = float(cl_[-1]), "time"
                    pnl = ((out_px - e_px) / e_px * 100) * (-1) - COST
                    rows.append({**base, "вход": nm, "цель": tgt_nm, "entry": e_px, "stop": sl, "target": tp,
                                 "entry_t": pd.Timestamp(lt[j]), "outcome": outc, "pnl": round(pnl, 2),
                                 "risk_pct": abs(e_px - sl) / e_px * 100, "tgt_pct": abs(tp - e_px) / e_px * 100})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} шортов за {time.time() - t0:.0f}с"


def report():
    rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
    if not rows:
        print("пусто"); return
    d = pd.DataFrame(rows); d["год"] = pd.to_datetime(d.top_time).dt.year
    мес = (pd.to_datetime(d.entry_t).max() - pd.to_datetime(d.entry_t).min()).days / 30.44
    print(f"шортов {len(d)} · сетапов {d.key.nunique()} · монет {d.sym.nunique()}\n")
    g = d.groupby(["вход", "цель"]).agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                        ср=("pnl", "mean"), мед=("pnl", "median"), сумма=("pnl", "sum"),
                                        риск=("risk_pct", "median"), цель_пр=("tgt_pct", "median"))
    print(g.round(2).to_string())
    print("\n--- в зависимости от того, чем кончился ЛОНГ:")
    print(d.groupby(["long_outcome", "вход", "цель"]).agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                                         ср=("pnl", "mean")).round(2).to_string())
    best = d[(d["вход"] == "по слому 15m вниз") & (d["цель"] == "цель p5")]
    if len(best):
        print("\n--- «по слому вниз → цель p5» по годам:")
        print(best.groupby("год").agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100),
                                      ср=("pnl", "mean"), сумма=("pnl", "sum")).round(2).to_string())


if __name__ == "__main__":
    if sys.argv[1] == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 8) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, syms), 1):
                if i % 100 == 0:
                    print(f"  {i}/{len(syms)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
