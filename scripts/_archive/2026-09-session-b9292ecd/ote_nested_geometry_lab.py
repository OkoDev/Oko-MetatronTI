"""КАК УСОВЕРШЕНСТВОВАТЬ ote_nested (Егор 22.09) — те же 10 261 филл реплея «как в бою», но ДРУГАЯ ГЕОМЕТРИЯ:
шкаф ставит стоп по LTF-структуре («компактный, риск ×10», медиана 0.6%) и цель 1R — это и умирает. Варианты:
  A бой        — стоп LTF, цель 1R (pnl из реплея, 72 ч);
  B структура  — стоп за началом ноги HTF (уровень 1.0 зоны = инвалидация, буфер 0.15%), цель 1R от этого стопа;
  C структура+ — стоп за 1.0, цель = экстремум ноги (уровень 0 = конец импульса, «ретест → продолжение»);
  D глубокая   — стоп за 0.886 ноги, цель = экстремум ноги.
Нога восстанавливается тем же калькулятором (`ote_retest_setups` на 200 барах 4h, закрытых к сигналу): зона 0.5–0.79
→ длина ноги L = (hi−lo)/0.29, экстремум и начало. Удержание до 7 дней (не «выход по времени», а предел замера).
Контроли B–D: случайный вход той же геометрии ±30 дн (×6). + разрез по контексту пятёрки ядра 4h (trades_wave_ctx.pkl).
python ote_nested_geometry_lab.py"""
import sys, glob, pickle, random
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf
from triangle_lab import walk, geo
OUT = Path("G:/oko_lab/out/ote_nested_replay"); COST = 0.10; HOLD_BARS = 7 * 96; BUF = 0.0015
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)


def one_symbol(args):
    sym, rows = args
    import logging; logging.disable(logging.CRITICAL)
    from core.smc.smc_engine import ote_retest_setups
    from core.smc.ote_signal_generator import OTESignalGenerator
    gen = OTESignalGenerator(); zd, zv = gen._zz("4h")
    try:
        d4 = load_tf(sym, "4h"); d15 = load_tf(sym, "15m")
    except Exception:
        return []
    i4 = d4.index.values; i15 = d15.index.values; hi, lo, cl = d15.high.values, d15.low.values, d15.close.values
    rs = random.Random(sum(map(ord, sym)) + 3); out = []; cache = {}
    for r in rows:
        t = pd.Timestamp(r["t"]); k4 = int(np.searchsorted(i4, np.datetime64(t), "right"))
        if k4 < 60:
            continue
        if k4 not in cache:
            try:
                cache[k4] = ote_retest_setups(d4.iloc[max(0, k4 - 200):k4], depth=zd, dev_mult=zv, only_choch=False, provisional=True)
            except Exception:
                cache[k4] = []
        st = cache[k4]; long_ = r["side"] == "LONG"; want = "long" if long_ else "short"; e = float(r["entry"])
        inz = [x for x in st if x["direction"] == want and x["ote"][0] <= e <= x["ote"][1]]
        if not inz:
            continue
        lo_z, hi_z = inz[-1]["ote"]; L = (hi_z - lo_z) / 0.29
        if long_:
            extreme, origin = hi_z + 0.5 * L, hi_z + 0.5 * L - L
        else:
            extreme, origin = lo_z - 0.5 * L, lo_z - 0.5 * L + L
        j = int(np.searchsorted(i15, np.datetime64(pd.Timestamp(r["entry_t"]))))
        if j >= len(d15) - 2:
            continue
        rec = {"sym": sym, "side": r["side"], "entry_t": pd.Timestamp(r["entry_t"]), "год": pd.Timestamp(r["entry_t"]).year, "A": r["pnl"], "risk_A": r["risk_pct"], "leg_pct": L / e * 100}
        variants = {}
        sl_B = origin * (1 - BUF) if long_ else origin * (1 + BUF)
        if (long_ and sl_B < e) or (not long_ and sl_B > e):
            rk = abs(e - sl_B)
            variants["B"] = (sl_B, e + rk if long_ else e - rk)
            variants["C"] = (sl_B, extreme)
        lvl886 = extreme - 0.886 * L if long_ else extreme + 0.886 * L
        sl_D = lvl886 * (1 - BUF) if long_ else lvl886 * (1 + BUF)
        if (long_ and sl_D < e) or (not long_ and sl_D > e):
            variants["D"] = (sl_D, extreme)
        for v, (sl, tp) in variants.items():
            if (long_ and not (sl < e < tp)) or (not long_ and not (tp < e < sl)):
                continue
            pnl, outc, _ = walk(hi, lo, cl, j, j + HOLD_BARS, long_, e, sl, tp)
            rsk, tg = abs(e - sl) / e, abs(tp - e) / e
            ctl = [geo(d15, rec["entry_t"] + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, HOLD_BARS) for _ in range(6)]
            rec[v] = pnl; rec[f"risk_{v}"] = rsk * 100; rec[f"ctl_{v}"] = np.nanmean(ctl) if np.isfinite(ctl).any() else np.nan; rec[f"out_{v}"] = outc
        out.append(rec)
    return out


if __name__ == "__main__":
    P = [pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*USDT.pkl"))]
    T = pd.DataFrame([r for p in P for r in p["rows"] if r.get("filled")])
    jobs = [(sym, g.to_dict("records")) for sym, g in T.groupby("sym")]
    res = []
    with Pool(6) as pool:
        for i, r in enumerate(pool.imap_unordered(one_symbol, jobs), 1):
            res += r
            if i % 40 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    R = pd.DataFrame(res); R.to_pickle(OUT / "geometry_lab.pkl")
    W = pd.read_pickle(OUT / "trades_wave_ctx.pkl")[["sym", "entry_t", "rel_4h"]]; W["entry_t"] = pd.to_datetime(W.entry_t)
    R = R.merge(W, on=["sym", "entry_t"], how="left")
    print(f"сделок с восстановленной ногой: {len(R)} из {len(T)}")
    def tab(g):
        rows = {}
        for v in ("A", "B", "C", "D"):
            if v not in g or g[v].notna().sum() == 0:
                continue
            x = g[g[v].notna()]; top = x[v].nlargest(max(1, int(len(x) * 0.1))).sum()
            rows[v] = {"n": len(x), "WR": (x[v] > 0).mean() * 100, "ср": x[v].mean(), "мед": x[v].median(), "риск%": x[f"risk_{v}"].median(),
                       "Δr": (x[v].mean() - x[f"ctl_{v}"].mean()) if f"ctl_{v}" in x else np.nan, "безтоп10": x[v].sum() - top, "сумма": x[v].sum(),
                       "монет+": (x.groupby("sym")[v].sum() > 0).mean() * 100, "лет+": f"{(x.groupby('год')[v].mean() > 0).sum()}/{x['год'].nunique()}"}
        return pd.DataFrame(rows).T.round(2)
    for s_, g in R.groupby("side"):
        print(f"\n=== {s_}: A бой (стоп LTF, 1R) · B стоп за 1.0, 1R · C стоп за 1.0, цель экстремум · D стоп за 0.886, цель экстремум"); print(tab(g).to_string())
        print("--- по годам (ср):"); print(g.groupby("год")[["A", "B", "C", "D"]].mean().round(2).T.to_string())
        print("--- × контекст пятёрки ядра 4h (ср):"); print(g.groupby("rel_4h")[["A", "B", "C", "D"]].agg(["size", "mean"]).round(2).to_string())
        g2 = g.copy(); g2["нога"] = pd.qcut(g2.leg_pct, 3, labels=["короткая", "средняя", "длинная"], duplicates="drop")
        print("--- × длина ноги HTF (ср):"); print(g2.groupby("нога", observed=True)[["A", "B", "C", "D"]].mean().round(2).T.to_string())
