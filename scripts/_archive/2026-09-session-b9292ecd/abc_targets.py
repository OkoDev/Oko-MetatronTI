"""ЦЕЛИ ОТСКОКА ПО ABC (Егор 16.09: «цели по коррекции 1й волны в ABC ты знаешь!»).
Прошлый замер (target_lab) мерил откаты от ВСЕГО импульса — это не то, что имел в виду Егор.
Здесь цели считаются от длины ПЕРВОЙ ВОЛНЫ ОТСКОКА (A), как в коррекции A-B-C:
  A = первый подтверждённый свинг-максимум на LTF после пятой (для LONG; для SHORT зеркально)
  B = следующий свинг против A (откат)
  цели: C = A (равенство, C от конца B) · C = 0.618·A · C = 1.618·A · повтор максимума A
Сравнение с боевой целью (конец волны 4). Вход, стоп, кост, окна — боевые, без изменений.
Запуск: python abc_targets.py run [монет] [процессов] · report
"""
import sys, pickle, time, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/abc_targets"); OUT.mkdir(parents=True, exist_ok=True)
TF, LTF_SW = "4h", 6            # окно свингов на 15m для разметки A и B


def ab_points(w, t5, long_, sw=LTF_SW):
    """A (конец первой волны отскока) и B (откат после неё) на LTF — по подтверждённым свингам."""
    from core.smc.oko_sm_engine import _swings
    x = w.reset_index(drop=True)
    sws = _swings(x["high"], x["low"], sw)
    j5 = int(np.searchsorted(w.index.values, np.datetime64(t5)))
    a = b = None
    for conf_i, sw_i, price, is_top in sws:
        if sw_i <= j5:
            continue
        if a is None and (is_top if long_ else not is_top):
            a = (int(conf_i), int(sw_i), float(price))          # конец волны A (подтверждён на баре conf_i)
        elif a is not None and (not is_top if long_ else is_top) and sw_i > a[1]:
            b = (int(conf_i), int(sw_i), float(price))          # конец волны B
            break
    return a, b


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
            base = ltf_status(s, w, P, after=nw, entry_w_h=entry_h, hold_h=hold_h, cost_pct=T.COST)
            if base.get("entry_price") is None:
                continue
            long_ = s["side"] == "LONG"; e = base["entry_price"]; sl = base["stop"]; p5 = float(s["p5"])
            a, b = ab_points(w, np.datetime64(t5), long_)
            rec = {"sym": sym, "key": s["key"], "side": s["side"], "top_time": t5, "entry": e, "stop": sl,
                   "risk_pct": abs(e - sl) / e * 100, "core_full": s["core_full"], "fractal": s["fractal"],
                   "w4": {"tgt": float(s["p4_target"]), "pnl": base["pnl_pct"], "outcome": base["outcome"]}}
            if a is not None:
                lenA = abs(a[2] - p5)
                cands = {"A_повтор": a[2],
                         "C=A": (b[2] + lenA) if b is not None else np.nan,
                         "C=0.618A": (b[2] + 0.618 * lenA) if b is not None else np.nan,
                         "C=1.618A": (b[2] + 1.618 * lenA) if b is not None else np.nan}
                if not long_:
                    cands = {"A_повтор": a[2],
                             "C=A": (b[2] - lenA) if b is not None else np.nan,
                             "C=0.618A": (b[2] - 0.618 * lenA) if b is not None else np.nan,
                             "C=1.618A": (b[2] - 1.618 * lenA) if b is not None else np.nan}
                rec["lenA_pct"] = lenA / p5 * 100
                rec["has_B"] = b is not None
                for nm, tgt in cands.items():
                    if tgt is None or not np.isfinite(tgt) or ((tgt <= e) if long_ else (tgt >= e)):
                        continue                                # цель за спиной — вход не имеет смысла
                    r = ltf_status({**s, "p4_target": float(tgt)}, w, P, after=nw, entry_w_h=entry_h,
                                   hold_h=hold_h, cost_pct=T.COST)
                    rec[nm] = {"tgt": float(tgt), "pnl": r["pnl_pct"], "outcome": r["outcome"],
                               "tgt_pct": abs(tgt - e) / e * 100}
            rows.append(rec)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сетапов за {time.time() - t0:.0f}с"


def report():
    rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
    print(f"сетапов с входом: {len(rows)} · монет {len({r['sym'] for r in rows})}")
    print(f"волна A размечена: {sum(1 for r in rows if 'lenA_pct' in r)} · с волной B: {sum(1 for r in rows if r.get('has_B'))}")
    out = []
    for nm in ("w4", "A_повтор", "C=A", "C=0.618A", "C=1.618A"):
        v = [r[nm] for r in rows if nm in r and r[nm].get("pnl") is not None]
        if not v:
            continue
        p = np.array([x["pnl"] for x in v], float)
        tp = np.array([x.get("tgt_pct", np.nan) for x in v], float)
        out.append({"цель": nm, "n": len(p), "ср%": round(p.mean(), 2), "мед%": round(float(np.median(p)), 2),
                    "WR%": round((p > 0).mean() * 100), "дист_цели%": round(float(np.nanmedian(tp)), 1) if np.isfinite(tp).any() else np.nan,
                    "доля target": round(sum(1 for x in v if x["outcome"] == "target") / len(v) * 100),
                    "безтоп10": round((p.sum() - np.sort(p)[-max(1, len(p) // 10):].sum()) / len(p), 2)})
    print("\n=== ЦЕЛИ ОТСКОКА ===")
    print(pd.DataFrame(out).to_string(index=False))
    # честное сравнение на ОДНИХ И ТЕХ ЖЕ сетапах, где размечены A и B
    both = [r for r in rows if "C=A" in r and r["w4"].get("pnl") is not None and r["C=A"].get("pnl") is not None]
    if both:
        w4 = np.array([r["w4"]["pnl"] for r in both]); ca = np.array([r["C=A"]["pnl"] for r in both])
        print(f"\nна одних и тех же {len(both)} сетапах: конец w4 {w4.mean():+.2f}% · C=A {ca.mean():+.2f}% · "
              f"разница {ca.mean() - w4.mean():+.2f} п.п.")
        for nm in ("C=0.618A", "C=1.618A", "A_повтор"):
            sub = [r for r in both if nm in r and r[nm].get("pnl") is not None]
            if sub:
                a1 = np.array([r["w4"]["pnl"] for r in sub]); a2 = np.array([r[nm]["pnl"] for r in sub])
                print(f"  {nm}: {a2.mean():+.2f}% против w4 {a1.mean():+.2f}% на тех же {len(sub)} → {a2.mean()-a1.mean():+.2f} п.п.")


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
