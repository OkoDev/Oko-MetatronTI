"""ote_nested: ЧАСТОТА + ЗРЕНИЕ ЦЕЛЯМИ (Егор 22.09: «4h как контекст, 1h как структура, LTF как триггер; цели — пивоты
r1-pp-s1 боковик, r2/s2 цели, r3..r5 рост/памп, фибо минусовые, магниты»). Вход НЕ трогаем — берём филлы реплеев генератора
«как в бою»: SRC=1h (сетап 1h_15m_pull, 30 монет 2023-26, ote_variants) и SRC=4h (боевой 4h_1h_pull, 222 монеты 2020-26).
Меняем ЦЕЛЬ (и стоп как вариант), выход по касанию, горизонт 7 дней:
  1R        — как бой (стоп LTF, цель 1R)
  pvD_near  — ближайший ДНЕВНОЙ классический пивот (calculate_pivot_points прошлого дня) за входом в сторону сделки (>0.3%)
  pvD_flat  — логика Егора: вход внутри S1–R1 (боковик) → цель R1/S1; вход за R1/S1 → R2/S2; за R2/S2 → следующий (R3..R5)
  pvD_2nd   — второй уровень за входом
  pvW_near / pvW_flat — то же на НЕДЕЛЬНЫХ пивотах
  fibW      — недельные фибо-пивоты (как индикатор со скрина: PP ± 0.382/0.618/1.0/1.618/3.0 R прошлой недели), ближайший
  fm272/fm618 — минусовые фибо от ноги HTF (нога восстановлена ote_retest_setups; −0.272/−0.618 за экстремум)
Стопы: LTF (бой) · leg (за 1.0 ноги HTF, буфер 0.15%). Контроль: случайный вход той же геометрии ±30 дн ×4.
Контекст: пятёрка ядра 4h (wave_phase_ctx), момент (дрейф30), альтсезон (дрейф90), день в боковике (цена внутри S1–R1 дня).
Магниты историей не восстановимы (magnet_tp пишется только в живые сделки) — отдельно по БД. python ote_targets_lab.py [1h|4h]"""
import sys, glob, pickle, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
from triangle_lab import walk, geo
SRC = sys.argv[1] if len(sys.argv) > 1 else "1h"
OUT = Path("G:/oko_lab/out/ote_targets"); OUT.mkdir(parents=True, exist_ok=True)
HOLD = 7 * 96; BUF = 0.0015; MIN_D = 0.003
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 400)
PIV_ORDER = ["S5", "S4", "S3", "S2", "S1", "PP", "R1", "R2", "R3", "R4", "R5"]


def pivots(df_day):
    from core.indicators.indicators import calculate_pivot_points
    h, l, c = df_day.high.shift(1), df_day.low.shift(1), df_day.close.shift(1)       # уровни дня/недели = по ПРОШЛОМУ бару
    out = {k: [] for k in PIV_ORDER}
    for H, L, C in zip(h.values, l.values, c.values):
        p = calculate_pivot_points(H, L, C) if H == H else {k: np.nan for k in PIV_ORDER}
        for k in PIV_ORDER:
            out[k].append(p[k])
    return pd.DataFrame(out, index=df_day.index)


def fib_week(dw):
    h, l, c = dw.high.shift(1), dw.low.shift(1), dw.close.shift(1); pp = (h + l + c) / 3; R = h - l
    return pd.DataFrame({f"F{m:+.3f}": pp + m * R for m in (-3.0, -1.618, -1.0, -0.618, -0.382, 0.382, 0.618, 1.0, 1.618, 3.0)} | {"FPP": pp}, index=dw.index)


def pick(levels, e, long_, n=1):
    lv = sorted(x for x in levels if x == x and ((x > e * (1 + MIN_D)) if long_ else (x < e * (1 - MIN_D))))
    if not long_:
        lv = lv[::-1]
    return lv[n - 1] if len(lv) >= n else None


def flat_target(row, e, long_):
    """Логика Егора по пивотам: внутри S1–R1 → R1/S1; за R1/S1 → R2/S2; дальше — следующий уровень."""
    if long_:
        seq = [row["R1"], row["R2"], row["R3"], row["R4"], row["R5"]]
    else:
        seq = [row["S1"], row["S2"], row["S3"], row["S4"], row["S5"]]
    for x in seq:
        if x == x and ((x > e * (1 + MIN_D)) if long_ else (x < e * (1 - MIN_D))):
            return x
    return None


def one_symbol(args):
    sym, rows = args
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.smc_engine import ote_retest_setups
    from core.smc.ote_signal_generator import OTESignalGenerator
    htf = "1h" if SRC == "1h" else "4h"
    gen = OTESignalGenerator(); zd, zv = gen._zz(htf)
    try:
        d15 = load_tf(sym, "15m"); dh = load_tf(sym, htf); dd = load_tf(sym, "1d")
    except Exception:
        return []
    dw = dd.resample("W-MON", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    PD, PW, FW = pivots(dd), pivots(dw), fib_week(dw)
    i15 = d15.index.values; hi, lo, cl = d15.high.values, d15.low.values, d15.close.values; ih = dh.index.values
    rs = random.Random(sum(map(ord, sym)) + 11); out = []; cache = {}
    for r in rows:
        et = pd.Timestamp(r["entry_t"]); j = int(np.searchsorted(i15, np.datetime64(et)))
        if j >= len(d15) - 10:
            continue
        long_ = r["side"] == "LONG"; e, sl0 = float(r["entry"]), float(r["stop"])
        kd = int(np.searchsorted(PD.index.values, np.datetime64(et.floor("D")), "right")) - 1
        kw = int(np.searchsorted(PW.index.values, np.datetime64(et), "right")) - 1
        if kd < 1 or kw < 1:
            continue
        pdr, pwr, fwr = PD.iloc[kd], PW.iloc[kw], FW.iloc[kw]
        # нога HTF (для fib-минус и стопа leg)
        kh = int(np.searchsorted(ih, np.datetime64(pd.Timestamp(r["t"])), "right"))
        if kh not in cache:
            try:
                cache[kh] = ote_retest_setups(dh.iloc[max(0, kh - 300):kh], depth=zd, dev_mult=zv, only_choch=False, provisional=True)
            except Exception:
                cache[kh] = []
        want = "long" if long_ else "short"; inz = [x for x in cache[kh] if x["direction"] == want and x["ote"][0] <= e <= x["ote"][1]]
        leg = None
        if inz:
            lz, hz = inz[-1]["ote"]; L = (hz - lz) / 0.29
            ext = hz + 0.5 * L if long_ else lz - 0.5 * L; org = ext - L if long_ else ext + L
            leg = (ext, org, L)
        tg = {"1R": float(r["target"]),
              "pvD_near": pick(pdr.values, e, long_), "pvD_2nd": pick(pdr.values, e, long_, 2), "pvD_flat": flat_target(pdr, e, long_),
              "pvW_near": pick(pwr.values, e, long_), "pvW_flat": flat_target(pwr, e, long_), "fibW": pick(fwr.values, e, long_)}
        if leg:
            ext, org, L = leg
            tg["fm272"] = ext + 0.272 * L if long_ else ext - 0.272 * L
            tg["fm618"] = ext + 0.618 * L if long_ else ext - 0.618 * L
        stops = {"LTF": sl0}
        if leg:
            s_leg = leg[1] * (1 - BUF) if long_ else leg[1] * (1 + BUF)
            if (s_leg < e) if long_ else (s_leg > e):
                stops["leg"] = s_leg
        flat_day = bool(pdr["S1"] <= e <= pdr["R1"])
        for sn, sl in stops.items():
            for tn, tp in tg.items():
                if tp is None or not (tp == tp) or ((tp <= e) if long_ else (tp >= e)):
                    continue
                pnl, outc, k = walk(hi, lo, cl, j, j + HOLD, long_, e, sl, tp)
                rk, tgp = abs(e - sl) / e, abs(tp - e) / e
                ctl = [geo(d15, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rk, tgp, HOLD) for _ in range(4)]
                out.append({"sym": sym, "side": r["side"], "entry_t": et, "год": et.year, "stop": sn, "target": tn, "pnl": pnl, "outcome": outc,
                            "risk_pct": rk * 100, "tgt_pct": tgp * 100, "rr": tgp / rk if rk else np.nan, "bars": k - j,
                            "ctl": np.nanmean(ctl) if np.isfinite(ctl).any() else np.nan, "flat_day": flat_day})
    return out


if __name__ == "__main__":
    if SRC == "1h":
        T = pd.read_pickle("G:/oko_lab/out/ote_variants/1h_15m_pull/trades.pkl")
    else:
        P = [pickle.load(open(f, "rb")) for f in glob.glob("G:/oko_lab/out/ote_nested_replay/*USDT.pkl")]
        T = pd.DataFrame([r for p in P for r in p["rows"] if r.get("filled")])
    T = T.rename(columns={"target": "target"})
    jobs = [(s, g.to_dict("records")) for s, g in T.groupby("sym")]
    res = []
    with Pool(6) as pool:
        for i, r in enumerate(pool.imap_unordered(one_symbol, jobs), 1):
            res += r
    R = pd.DataFrame(res)
    U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl"); day = R.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    R["drift30"] = U.drift30.reindex(day.values).values; R["drift90"] = U.drift90.reindex(day.values).values
    R["момент"] = np.where(R.drift30 > 25, "безоткатный рост", np.where(R.drift30 < -20, "обвал", np.where(R.drift90 > 15, "альтсезон", "обычный")))
    W = pd.read_pickle("G:/oko_lab/out/ote_nested_replay/trades_wave_ctx.pkl")[["sym", "entry_t", "rel_4h"]] if SRC == "4h" else None
    if W is not None:
        W["entry_t"] = pd.to_datetime(W.entry_t); R = R.merge(W.drop_duplicates(["sym", "entry_t"]), on=["sym", "entry_t"], how="left")
    R.to_pickle(OUT / f"trades_{SRC}.pkl")
    def agg(g):
        return g.agg(n=("pnl", "size"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"), RR=("rr", "median"),
                     риск=("risk_pct", "median"), цель=("tgt_pct", "median"), ctl=("ctl", "mean"), сумма=("pnl", "sum")).assign(Δr=lambda x: x["ср"] - x.ctl).round(2)
    print(f"SRC {SRC}: сделок-входов {len(T)} · строк {len(R)} · монет {R.sym.nunique()}")
    print("\n=== стоп × цель × сторона"); print(agg(R.groupby(["stop", "target", "side"])).to_string())
    print("\n=== цель × боковик дня (вход внутри S1–R1) — стоп LTF"); print(agg(R[R.stop == "LTF"].groupby(["target", "flat_day"])).to_string())
    print("\n=== цель × момент рынка — стоп LTF (ср)"); print(R[R.stop == "LTF"].groupby(["target", "side", "момент"]).pnl.agg(["size", "mean"]).round(2).unstack("момент").to_string())
    print("\n=== цель × год — стоп LTF (ср)"); print(R[R.stop == "LTF"].groupby(["target", "год"]).pnl.mean().round(2).unstack("год").to_string())
    print("\n=== цель × год — стоп leg (ср)"); print(R[R.stop == "leg"].groupby(["target", "год"]).pnl.mean().round(2).unstack("год").to_string())
    if "rel_4h" in R:
        print("\n=== контекст 4h × цель (стоп LTF)"); print(R[R.stop == "LTF"].groupby(["target", "rel_4h"]).pnl.agg(["size", "mean"]).round(2).unstack("rel_4h").to_string())
    print("\n=== хрупкость")
    for (s_, t_), g in R.groupby(["stop", "target"]):
        top = g.pnl.nlargest(max(1, int(len(g) * 0.1))).sum(); yrs = g.groupby("год").pnl.mean()
        print(f"  {s_}/{t_}: n {len(g)} · ср {g.pnl.mean():+.2f} · WR {(g.pnl > 0).mean() * 100:.0f}% · без топ-10% {g.pnl.sum() - top:+.0f} · монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(yrs > 0).sum()}/{len(yrs)}")
