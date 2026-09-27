"""ЦЕЛИ ОТСКОКА (Егор 16.09: «в падающем рынке отскок даёт… а цели по коррекции 1й волны в ABC ты знаешь!»).
Наша боевая цель — конец волны 4 (`p4_target`). Замер RR показал, что 54% сделок сидят в корзине RR>4
(цель далеко, стоп туго) со средним +0.45%, а лучшая корзина — RR 0.5-1 (близкая цель, широкий стоп): +2.90%.
Значит цель, возможно, стоит брать по коррекционной сетке, а не тянуть до конца четвёртой.

Варианты цели (уже считаются в сетапе): corr_382 · corr_500 · corr_618 · corr_w4 (=p4_target, боевая).
Всё остальное — боевые правила без изменений (вход cross/line24, стоп за экстремумом пятой, кост 0.10%).
Запуск: python target_lab.py run [монет] [процессов] · report
"""
import sys, pickle, time, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/target_lab"); OUT.mkdir(parents=True, exist_ok=True)
TF = "4h"
TARGETS = ("corr_382", "corr_500", "corr_618", "corr_w4", "corr_236", "half_w4", "third_w4")


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
        dh = load_tf(sym, TF); dl = load_tf(sym, T.LTF[TF])
    except Exception as e:
        return sym, f"данные: {e}"
    if len(dh) < T.WARMUP + 100:
        return sym, "мало истории"
    tfm = TF_MIN[TF]; entry_h = T.ENTRY_BARS * tfm / 60; hold_h = T.HOLD_BARS * tfm / 60
    P = WaveParams(); rows = []; seen = set()
    dhr = dh.reset_index(drop=True); idx_h = dh.index
    hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=P.sw, internal_len=P.il)
    sws = _swings(dhr["high"], dhr["low"], P.sw); swi = _swings(dhr["high"], dhr["low"], P.il)
    wt = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    dl_idx = dl.index.values
    for t in range(T.WARMUP, len(dh)):
        now = idx_h[t] + pd.Timedelta(minutes=tfm)
        if now < T.T0:
            continue
        try:
            setups = _setups_at(t, dh, idx_h, hh, lh, st, sws, swi, wt, [], [], np.array([np.nan]), tfm, now, P, TF)
        except Exception:
            continue
        for s in setups:
            if s["key"] in seen:
                continue
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            if t5.tzinfo is not None:
                t5 = t5.tz_convert("UTC").tz_localize(None)
            i0 = int(np.searchsorted(dl_idx, np.datetime64(t5 - pd.Timedelta(minutes=4 * tfm)), "left"))
            i1 = int(np.searchsorted(dl_idx, np.datetime64(t5 + pd.Timedelta(hours=entry_h + hold_h)), "right"))
            w = dl.iloc[i0:i1]
            if len(w) < 100:
                continue
            nw = now.tz_localize(None) if getattr(now, "tzinfo", None) is not None else now
            sg = 1.0 if s["side"] == "LONG" else -1.0
            rng5 = abs(s["p5"] - s["p0"]) if s.get("p0") is not None else abs(s["p4_target"] - s["p5"]) / 0.382
            extra = {"corr_236": s["p5"] + sg * 0.236 * rng5,          # ещё ближе 0.382 — проверка среза RR
                     "half_w4": s["p5"] + 0.5 * (s["p4_target"] - s["p5"]),   # половина пути до конца волны 4
                     "third_w4": s["p5"] + 0.33 * (s["p4_target"] - s["p5"])}
            for tk in TARGETS:
                tgt = extra[tk] if tk in extra else s.get(tk)
                if tgt is None or not np.isfinite(tgt):
                    continue
                ls = ltf_status({**s, "p4_target": float(tgt)}, w, P, after=nw, entry_w_h=entry_h,
                                hold_h=hold_h, cost_pct=T.COST)
                if ls.get("entry_price") is None:
                    continue
                e = ls["entry_price"]; long_ = s["side"] == "LONG"
                if (tgt <= e) if long_ else (tgt >= e):
                    continue                        # цель уже за спиной — такой вход не имеет смысла (случай SYN 16.09)
                rows.append({"sym": sym, "key": s["key"], "side": s["side"], "target_kind": tk,
                             "top_time": t5, "entry": e, "stop": ls["stop"], "target": float(tgt),
                             "entry_t": pd.Timestamp(ls["entry_time"]), "outcome": ls["outcome"], "pnl": ls["pnl_pct"],
                             "risk_pct": abs(e - ls["stop"]) / e * 100, "tgt_pct": abs(tgt - e) / e * 100,
                             "core_full": s["core_full"], "fractal": s["fractal"], "depth5": s["depth5"],
                             "imp_pct": s["imp_pct"]})
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сделок ({len(seen)} сетапов) за {time.time() - t0:.0f}с"


def report():
    rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
    d = pd.DataFrame(rows)
    d["год"] = pd.to_datetime(d.top_time).dt.year
    d["RR"] = d.tgt_pct / d.risk_pct
    print(f"сделок {len(d)} · сетапов {d.key.nunique()} · монет {d.sym.nunique()}\n")
    print("=== ЦЕЛЬ ЦЕЛИКОМ ===")
    g = d.groupby("target_kind").agg(n=("pnl", "size"), ср=("pnl", "mean"), мед=("pnl", "median"),
                                     WR=("pnl", lambda x: (x > 0).mean() * 100), RR=("RR", "median"),
                                     цель_пр=("tgt_pct", "median"), риск_пр=("risk_pct", "median"))
    g["безтоп10"] = [(d[d.target_kind == k].pnl.sum() - d[d.target_kind == k].pnl.nlargest(max(1, (d.target_kind == k).sum() // 10)).sum()) / max(1, (d.target_kind == k).sum()) for k in g.index]
    g["монет+%"] = [(d[d.target_kind == k].groupby("sym").pnl.mean() > 0).mean() * 100 for k in g.index]
    print(g.round(2).to_string())
    for cut, name in ((d.side == "LONG", "LONG"), (d.side == "SHORT", "SHORT"), (d.core_full, "ядро fc")):
        print(f"\n=== {name} ===")
        print(d[cut].groupby("target_kind").agg(n=("pnl", "size"), ср=("pnl", "mean"), WR=("pnl", lambda x: (x > 0).mean() * 100)).round(2).to_string())
    print("\n=== ПО ГОДАМ (среднее %) ===")
    print(d.pivot_table(index="год", columns="target_kind", values="pnl", aggfunc="mean").round(2).to_string())


if __name__ == "__main__":
    if sys.argv[1] == "run":
        syms = sorted(p.stem for p in PARQ.glob("*.parquet"))
        if len(sys.argv) > 2:
            syms = syms[:int(sys.argv[2])]
        with Pool(int(sys.argv[3]) if len(sys.argv) > 3 else 8) as pool:
            for i, (s, m) in enumerate(pool.imap_unordered(run_symbol, syms), 1):
                if i % 50 == 0:
                    print(f"  {i}/{len(syms)} {s}: {m}", flush=True)
        print("ГОТОВО", flush=True)
    else:
        report()
