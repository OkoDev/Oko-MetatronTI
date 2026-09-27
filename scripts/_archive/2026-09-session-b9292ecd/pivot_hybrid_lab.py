"""ГИБРИД ВЫХОДА (Егор 22.09 «замерить гибрид!»): половина на пивоте, раннер дальше. Те же филлы impulse_fib 1h и ядра 4h.
Варианты (цель1 = пивот, цель2 = раннер), раннер после цели1: стоп тот же («same») или в безубыток («BE»):
  E→N   : pvD_Егор + родная        E2→N : pvD_2nd + родная        E→E2 : pvD_Егор + второй дневной (лестница пивотов)
База: родная целиком · pvD_Егор целиком · pvD_2nd целиком. Косты 0.10 на всю позицию. Горизонт 7 дн. python pivot_hybrid_lab.py"""
import sys
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.argv = sys.argv[:1] + ["1h"]
sys.path.insert(0, str(Path(__file__).parent))
from ote_targets_lab import pivots, pick, flat_target
from tfcache import load_tf
HOLD = 7 * 96; COST = 0.10
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 300)


def walk2(hi, lo, cl, j0, j1, long_, e, sl, tp1, tp2, be):
    """50% на tp1, 50% на tp2; после tp1 стоп раннера = e (be) или прежний. Возврат pnl % на всю позицию."""
    sg = 1 if long_ else -1; half1 = None; stop2 = sl
    for k in range(j0, min(j1, len(hi))):
        h, l = hi[k], lo[k]
        if half1 is None:
            if (l <= sl) if long_ else (h >= sl):
                return sg * (sl - e) / e * 100 - COST, "stop"
            if (h >= tp1) if long_ else (l <= tp1):
                half1 = sg * (tp1 - e) / e * 100
                if be:
                    stop2 = e
                if (h >= tp2) if long_ else (l <= tp2):
                    return 0.5 * half1 + 0.5 * sg * (tp2 - e) / e * 100 - COST, "tp1+tp2"
                continue
        else:
            if (l <= stop2) if long_ else (h >= stop2):
                return 0.5 * half1 + 0.5 * sg * (stop2 - e) / e * 100 - COST, "tp1+стоп"
            if (h >= tp2) if long_ else (l <= tp2):
                return 0.5 * half1 + 0.5 * sg * (tp2 - e) / e * 100 - COST, "tp1+tp2"
    k = min(j1, len(hi)) - 1; last = sg * (cl[k] - e) / e * 100
    return (0.5 * half1 + 0.5 * last if half1 is not None else last) - COST, "время"


def one_symbol(args):
    sym, rows = args
    try:
        d15 = load_tf(sym, "15m"); dd = load_tf(sym, "1d")
    except Exception:
        return []
    PD = pivots(dd); i15 = d15.index.values; hi, lo, cl = d15.high.values, d15.low.values, d15.close.values; out = []
    for r in rows:
        et = pd.Timestamp(r["entry_t"]); j = int(np.searchsorted(i15, np.datetime64(et)))
        kd = int(np.searchsorted(PD.index.values, np.datetime64(et.floor("D")), "right")) - 1
        if j >= len(d15) - 10 or kd < 1:
            continue
        long_ = r["side"] == "LONG"; e, sl, nat = float(r["entry"]), float(r["stop"]), float(r["target"])
        if (long_ and not (sl < e < nat)) or (not long_ and not (nat < e < sl)):
            continue
        pdr = PD.iloc[kd]; pE = flat_target(pdr, e, long_); p2 = pick(pdr.values, e, long_, 2)
        def ok(t):
            return t is not None and t == t and ((t > e) if long_ else (t < e))
        V = {"родная": (nat, nat, False)}
        if ok(pE):
            V["Егор целиком"] = (pE, pE, False)
        if ok(p2):
            V["2-й целиком"] = (p2, p2, False)
        for be in (False, True):
            tag = "BE" if be else "same"
            if ok(pE):
                V[f"Егор+родная {tag}"] = (pE, nat if ((nat > pE) if long_ else (nat < pE)) else pE, be)
            if ok(p2):
                V[f"2-й+родная {tag}"] = (p2, nat if ((nat > p2) if long_ else (nat < p2)) else p2, be)
            if ok(pE) and ok(p2) and ((p2 > pE) if long_ else (p2 < pE)):
                V[f"Егор+2-й {tag}"] = (pE, p2, be)
        for name, (t1, t2, be) in V.items():
            pnl, outc = walk2(hi, lo, cl, j, j + HOLD, long_, e, sl, t1, t2, be)
            out.append({"mech": r["mech"], "sym": sym, "side": r["side"], "год": et.year, "entry_t": et, "var": name, "pnl": pnl, "outcome": outc})
    return out


if __name__ == "__main__":
    A = pd.read_pickle("G:/oko_lab/out/own_game_waves/waves_own_game.pkl")
    A = A[A.entered].assign(mech="ядро 4h")[["mech", "sym", "side", "entry", "stop", "target", "entry_t"]]
    M = pd.read_pickle("G:/oko_lab/out/map_replays/trades.pkl"); M = M[(M.mech == "impulse_fib_1h") & M["вошла"]].copy()
    M["target"] = np.where(M.side == "LONG", M.entry_px * (1 + M.tgt_pct / 100), M.entry_px * (1 - M.tgt_pct / 100))
    M = M.rename(columns={"entry_px": "entry", "sl_px": "stop"}).assign(mech="impulse_fib 1h")[["mech", "sym", "side", "entry", "stop", "target", "entry_t"]]
    T = pd.concat([A, M], ignore_index=True); T["entry_t"] = pd.to_datetime(T.entry_t)
    res = []
    with Pool(6) as pool:
        for r in pool.imap_unordered(one_symbol, [(s, g.to_dict("records")) for s, g in T.groupby("sym")]):
            res += r
    R = pd.DataFrame(res); R.to_pickle("G:/oko_lab/out/pivot_logic/hybrid.pkl")
    U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl"); day = R.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    d30, d90 = U.drift30.reindex(day.values).values, U.drift90.reindex(day.values).values
    R["момент"] = np.where(d30 > 25, "безоткатный рост", np.where(d30 < -20, "обвал", np.where(d90 > 15, "альтсезон", "обычный")))
    for (mech, side), Z in R.groupby(["mech", "side"]):
        rows = []
        for v, g in Z.groupby("var"):
            top = g.pnl.nlargest(max(1, int(len(g) * 0.1))).sum(); yrs = g.groupby("год").pnl.mean()
            rows.append({"вариант": v, "n": len(g), "WR": (g.pnl > 0).mean() * 100, "ср": g.pnl.mean(), "мед": g.pnl.median(),
                         "безтоп10": g.pnl.sum() - top, "монет+": (g.groupby("sym").pnl.sum() > 0).mean() * 100, "лет+": f"{(yrs > 0).sum()}/{len(yrs)}",
                         "худший год": yrs.min()})
        print(f"\n################ {mech} {side}"); print(pd.DataFrame(rows).set_index("вариант").sort_values("ср", ascending=False).round(2).to_string())
        print("--- по годам (ср)"); print(Z.groupby(["var", "год"]).pnl.mean().round(2).unstack("год").to_string())
        print("--- по моменту (ср)"); print(Z.groupby(["var", "момент"]).pnl.mean().round(2).unstack("момент").to_string())
