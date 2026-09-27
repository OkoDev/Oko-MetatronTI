"""ПИВОТНАЯ ЛОГИКА ЕГОРА на механиках с эджем (22.09: «r1-pp-s1 — боковик, r2/s2 — цели и поддержка/сопротивление,
r3..r5 — рост/падение/пампы»). Входы не трогаем — филлы реплеев: ядро волн 4h LONG/SHORT (own_game_waves, стоп за пятой,
цель конец 4-й) и impulse_fib 1h (map_replays, стоп 2.5 ATR, цель −1.618). Проверяем три вещи:
  1) ЦЕЛИ: родная · дневной/недельный пивот ближний · «логика Егора» (внутри S1–R1 → R1/S1, за → R2/S2, дальше R3..R5) ·
     второй уровень · недельные фибо-пивоты; выход по касанию, горизонт 7 дн.
  2) РЕЖИМ ДНЯ по пивотам: вход внутри S1–R1 (боковик) / между R1–R2 (S1–S2) / за R2 (S2) — выход на рост/падение.
  3) ОПОРА: вход у поддержки для лонга (до ближайшего S-уровня/PP снизу ≤ 0.5%) / у сопротивления для шорта.
Контроль — случайный вход той же геометрии ±30 дн ×4. python pivot_logic_lab.py"""
import sys, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
sys.argv = sys.argv[:1] + ["1h"]                       # ote_targets_lab читает argv при импорте
sys.path.insert(0, str(Path(__file__).parent))
from ote_targets_lab import pivots, fib_week, pick, flat_target, PIV_ORDER
from tfcache import load_tf
from triangle_lab import walk, geo
OUT = Path("G:/oko_lab/out/pivot_logic"); OUT.mkdir(parents=True, exist_ok=True)
HOLD = 7 * 96
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 400)


def day_zone(row, e):
    if row["S1"] <= e <= row["R1"]:
        return "боковик S1–R1"
    if row["R1"] < e <= row["R2"]:
        return "R1–R2"
    if row["S2"] <= e < row["S1"]:
        return "S2–S1"
    return "за R2" if e > row["R2"] else "за S2"


def one_symbol(args):
    sym, rows = args
    try:
        d15 = load_tf(sym, "15m"); dd = load_tf(sym, "1d")
    except Exception:
        return []
    dw = dd.resample("W-MON", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    PD, PW, FW = pivots(dd), pivots(dw), fib_week(dw)
    i15 = d15.index.values; hi, lo, cl = d15.high.values, d15.low.values, d15.close.values
    rs = random.Random(sum(map(ord, sym)) + 21); out = []
    for r in rows:
        et = pd.Timestamp(r["entry_t"]); j = int(np.searchsorted(i15, np.datetime64(et)))
        kd = int(np.searchsorted(PD.index.values, np.datetime64(et.floor("D")), "right")) - 1
        kw = int(np.searchsorted(PW.index.values, np.datetime64(et), "right")) - 1
        if j >= len(d15) - 10 or kd < 1 or kw < 1:
            continue
        long_ = r["side"] == "LONG"; e, sl = float(r["entry"]), float(r["stop"])
        if (long_ and sl >= e) or (not long_ and sl <= e):
            continue
        pdr, pwr, fwr = PD.iloc[kd], PW.iloc[kw], FW.iloc[kw]
        lv = [x for x in pdr.values if x == x]
        near = min((abs(e - x) / e for x in lv if ((x <= e) if long_ else (x >= e))), default=np.nan)   # до опоры за спиной
        zone = day_zone(pdr, e) if pdr["S1"] == pdr["S1"] else "—"
        tg = {"родная": float(r["target"]), "pvD_near": pick(pdr.values, e, long_), "pvD_Егор": flat_target(pdr, e, long_),
              "pvD_2nd": pick(pdr.values, e, long_, 2), "pvW_near": pick(pwr.values, e, long_), "pvW_Егор": flat_target(pwr, e, long_),
              "fibW": pick(fwr.values, e, long_)}
        for tn, tp in tg.items():
            if tp is None or not (tp == tp) or ((tp <= e) if long_ else (tp >= e)):
                continue
            pnl, outc, k = walk(hi, lo, cl, j, j + HOLD, long_, e, sl, tp)
            rk, tgp = abs(e - sl) / e, abs(tp - e) / e
            ctl = [geo(d15, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rk, tgp, HOLD) for _ in range(4)]
            out.append({"mech": r["mech"], "sym": sym, "side": r["side"], "entry_t": et, "год": et.year, "target": tn, "pnl": pnl, "outcome": outc,
                        "risk_pct": rk * 100, "tgt_pct": tgp * 100, "ctl": np.nanmean(ctl) if np.isfinite(ctl).any() else np.nan,
                        "zone": zone, "support_pct": near * 100})
    return out


if __name__ == "__main__":
    A = pd.read_pickle("G:/oko_lab/out/own_game_waves/waves_own_game.pkl")
    A = A[A.entered].assign(mech="ядро 4h")[["mech", "sym", "side", "entry", "stop", "target", "entry_t"]]
    M = pd.read_pickle("G:/oko_lab/out/map_replays/trades.pkl"); M = M[(M.mech == "impulse_fib_1h") & M["вошла"]].copy()
    M["target"] = np.where(M.side == "LONG", M.entry_px * (1 + M.tgt_pct / 100), M.entry_px * (1 - M.tgt_pct / 100))
    M = M.rename(columns={"entry_px": "entry", "sl_px": "stop"}).assign(mech="impulse_fib 1h")[["mech", "sym", "side", "entry", "stop", "target", "entry_t"]]
    T = pd.concat([A, M], ignore_index=True); T["entry_t"] = pd.to_datetime(T.entry_t)
    print("входов:", T.groupby(["mech", "side"]).size().to_dict())
    res = []
    with Pool(6) as pool:
        for r in pool.imap_unordered(one_symbol, [(s, g.to_dict("records")) for s, g in T.groupby("sym")]):
            res += r
    R = pd.DataFrame(res)
    U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl"); day = R.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    R["drift30"] = U.drift30.reindex(day.values).values; R["drift90"] = U.drift90.reindex(day.values).values
    R["момент"] = np.where(R.drift30 > 25, "безоткатный рост", np.where(R.drift30 < -20, "обвал", np.where(R.drift90 > 15, "альтсезон", "обычный")))
    R["опора"] = pd.cut(R.support_pct, [-0.01, 0.5, 1.5, 999], labels=["у опоры ≤0.5%", "0.5–1.5%", "далеко >1.5%"])
    R.to_pickle(OUT / "trades.pkl")
    def agg(g):
        return g.agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"), риск=("risk_pct", "median"),
                     цель=("tgt_pct", "median"), ctl=("ctl", "mean")).assign(Δr=lambda x: x["ср"] - x.ctl).round(2)
    for mech, Z in R.groupby("mech"):
        print(f"\n################ {mech}")
        print("=== 1) ЦЕЛИ: сторона × цель"); print(agg(Z.groupby(["side", "target"])).to_string())
        print("--- цели × год (ср)"); print(Z.groupby(["side", "target", "год"]).pnl.mean().round(2).unstack("год").to_string())
        print("--- цели × момент рынка (ср)"); print(Z.groupby(["side", "target", "момент"]).pnl.mean().round(2).unstack("момент").to_string())
        B = Z[Z.target == "родная"]
        print("=== 2) РЕЖИМ ДНЯ по пивотам (родная цель)"); print(agg(B.groupby(["side", "zone"])).to_string())
        print("--- режим дня × цель (ср)"); print(Z.groupby(["side", "zone", "target"]).pnl.mean().round(2).unstack("target").to_string())
        print("=== 3) ОПОРА за спиной (родная цель)"); print(agg(B.groupby(["side", "опора"], observed=True)).to_string())
        for (s_, t_), g in Z.groupby(["side", "target"]):
            top = g.pnl.nlargest(max(1, int(len(g) * 0.1))).sum(); yrs = g.groupby("год").pnl.mean()
            print(f"  хрупкость {s_}/{t_}: n {len(g)} · ср {g.pnl.mean():+.2f} · без топ-10% {g.pnl.sum() - top:+.0f} · монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(yrs > 0).sum()}/{len(yrs)}")
