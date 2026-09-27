"""ВХОД «ПОСЛЕ ВОЛНЫ A» — как в разборе аналитика (Егор 22.09, AIOT/NEAR: «отличный сетап в шорт с коротким стопом»).
Реплей логики core.waves.wave_analyst.analyze (LTF-часть) каузально по истории, обе стороны:
  СОСТОЯНИЕ: пятёрка ядра 4h (wave_phase_ctx: бары, где ядро её видит) — активна от первой детекции до последней + 90 баров
             (lookback аналитика 15 сут); пятая «продлевается»: экстремум = бегущий max/min high/low после точки 5.
  3m (OKO-SM swing 50 / internal 5, один прогон по всей истории): после экстремума пятой первый internal-CHoCH против хода
             → волна A; первый встречный internal-CHoCH → A закончена (a_done); вершина A = экстремум между пятой и этим сломом.
  ВХОД: лимит в зоне отката A — варианты 0.5 / 0.618 (касание после a_done); стоп за 0.886 A. Если до входа цена обновила
             экстремум пятой — сетап пересобирается от нового экстремума (как аналитик: зона умирает на стопе 0.886).
  ЦЕЛИ: A (ретест вершины A) · 4h-ход 0.382 / 0.5 / 0.618 от p0 до пятой · 2R · 3R. Выход по касанию, горизонт 7 дн.
Контроль: случайный вход той же геометрии ±30 дн ×4. Косты 0.10. python wave_a_retrace_lab.py run [proc] · report"""
import sys, glob, pickle, random, time
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk, geo
OUT = Path("G:/oko_lab/out/wave_a_retrace"); OUT.mkdir(parents=True, exist_ok=True)
LOOKBACK_4H = 90; HOLD = 7 * 480; T0 = pd.Timestamp("2020-06-01")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)


def run_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    import logging; logging.disable(logging.CRITICAL)
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    from core.smc.oko_sm_engine import run_structure
    t_s = time.time()
    p = Path("G:/oko_lab/out/wave_phase_ctx") / f"{sym}.pkl"
    if not p.exists():
        return sym, "нет сканов ядра"
    S = pickle.load(open(p, "rb"))
    if not len(S):
        pickle.dump([], open(out_p, "wb")); return sym, "пятёрок нет"
    try:
        d3 = load_tf(sym, "3m")
    except Exception as e:
        return sym, f"3m: {e}"
    i3 = d3.index.values; hi, lo, cl = d3.high.values, d3.low.values, d3.close.values
    st = run_structure(d3[["open", "high", "low", "close"]].reset_index(drop=True), swing_len=50, internal_len=5)
    ch_bear = np.array(sorted(e.i for e in st.events if e.internal and e.kind == "CHoCH" and not e.bull))
    ch_bull = np.array(sorted(e.i for e in st.events if e.internal and e.kind == "CHoCH" and e.bull))
    def next_ev(arr, after):
        k = int(np.searchsorted(arr, after, "right"))
        return int(arr[k]) if k < len(arr) else None
    rows = []; busy = -1; rs = random.Random(sum(map(ord, sym)) + 31)
    for key, g in S.groupby("key"):
        g = g.sort_values("tt"); x = g.iloc[0]
        if pd.Timestamp(x.time) < T0:
            continue
        up = x.side == "SHORT"                                   # пятёрка вверх → шорт
        t_start = pd.Timestamp(g.time.iloc[0]) + pd.Timedelta(hours=4)          # бар детекции закрыт
        t_end = pd.Timestamp(g.time.iloc[-1]) + pd.Timedelta(hours=4 * LOOKBACK_4H)
        j_top = int(np.searchsorted(i3, np.datetime64(pd.Timestamp(x.top_time))))    # начало 4h-бара пятой
        j_s, j_e = int(np.searchsorted(i3, np.datetime64(t_start))), min(int(np.searchsorted(i3, np.datetime64(t_end))), len(d3) - 2)
        if j_s >= j_e or j_top >= j_s:
            continue
        p0 = float(x.p0)
        j = j_s
        while j < j_e:
            if j <= busy:
                j = busy + 1; continue
            # экстремум пятой на момент j (бегущий, каузально)
            seg = hi[j_top:j + 1] if up else lo[j_top:j + 1]
            j5 = j_top + int(seg.argmax() if up else seg.argmin()); p5 = float(seg.max() if up else seg.min())
            e = next_ev(ch_bear if up else ch_bull, j5)                  # слом против хода → волна A
            if e is None or e >= j_e:
                break
            if (hi[j5 + 1:e + 1].max() > p5) if up else (lo[j5 + 1:e + 1].min() < p5):
                j = max(j + 1, e); continue                                          # пятая обновилась до слома — пересчёт
            b = next_ev(ch_bull if up else ch_bear, e)                   # встречный слом → A закончена
            if b is None or b >= j_e:
                break
            if (hi[e:b + 1].max() > p5) if up else (lo[e:b + 1].min() < p5):
                j = max(j + 1, b); continue
            ka = j5 + int((lo[j5:b + 1].argmin()) if up else (hi[j5:b + 1].argmax())); a_top = float(lo[ka] if up else hi[ka])
            A = (p5 - a_top) if up else (a_top - p5)
            if A <= 0:
                j = max(j + 1, b + 1); continue
            sg = 1 if up else -1                                         # откат A идёт в сторону +sg
            stop = a_top + sg * 0.886 * A
            filled = {}
            for lvl in (0.5, 0.618):
                z = a_top + sg * lvl * A; jf = None
                for k in range(max(b + 1, j), j_e):              # не раньше текущего момента j: p5 посчитан по данным ≤ j
                    if (hi[k] >= stop) if up else (lo[k] <= stop):
                        break
                    if (hi[k] >= z) if up else (lo[k] <= z):
                        jf = k; break
                if jf is not None:
                    filled[lvl] = (jf, z)
            if not filled:
                # зона умерла (стоп 0.886) или окно кончилось — продолжаем после стопа как с новой пятой
                kstop = next((k for k in range(b + 1, j_e) if ((hi[k] >= stop) if up else (lo[k] <= stop))), None)
                if kstop is None:
                    break
                j = max(j + 1, kstop + 1); continue
            long_ = not up; move = abs(p5 - p0); last_exit = b
            for lvl, (jf, e_) in filled.items():
                rk = abs(stop - e_) / e_
                tg = {"A": a_top, "4h 0.382": p5 - sg * 0.382 * move, "4h 0.5": p5 - sg * 0.5 * move, "4h 0.618": p5 - sg * 0.618 * move,
                      "2R": e_ - sg * 2 * abs(stop - e_), "3R": e_ - sg * 3 * abs(stop - e_)}
                for tn, tp in tg.items():
                    if (tp >= e_) if not long_ else (tp <= e_):
                        continue
                    pnl, outc, k_out = walk(hi, lo, cl, jf + 1, jf + 1 + HOLD, long_, e_, stop, tp)
                    tgp = abs(tp - e_) / e_
                    ctl = [geo(d3, pd.Timestamp(i3[jf]) + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rk, tgp, HOLD) for _ in range(4)]
                    rows.append({"sym": sym, "side": "SHORT" if up else "LONG", "key": key, "entry_t": pd.Timestamp(i3[jf]), "lvl": lvl, "target": tn,
                                 "pnl": round(pnl, 3), "outcome": outc, "risk_pct": rk * 100, "tgt_pct": tgp * 100, "ctl": np.nanmean(ctl) if np.isfinite(ctl).any() else np.nan,
                                 "core_full": bool(x.core_full), "core": bool(x.core), "imp_pct": float(x.imp_pct), "A_pct": A / p5 * 100,
                                 "h_from_5": (pd.Timestamp(i3[jf]) - pd.Timestamp(i3[j5])).total_seconds() / 3600,
                                 "ext_pct": abs(p5 / float(x.p5) - 1) * 100})
                    if lvl == 0.5 and tn == "4h 0.382":
                        last_exit = max(last_exit, k_out)
            busy = last_exit; j = last_exit + 1
            break                                                        # один вход на ключ пятёрки (первый)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"строк {len(rows)} за {time.time() - t_s:.0f}с"


def report():
    d = pd.DataFrame([r for f in glob.glob(str(OUT / "*USDT.pkl")) for r in pickle.load(open(f, "rb"))])
    d["год"] = d.entry_t.dt.year
    U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl"); G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); G["dU30"] = G.usdt_d - G.usdt_d.shift(30)
    day = d.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    d30, d90 = U.drift30.reindex(day.values).values, U.drift90.reindex(day.values).values
    d["момент"] = np.where(d30 > 25, "безоткатный рост", np.where(d30 < -20, "обвал", np.where(d90 > 15, "альтсезон", "обычный")))
    du = G.dU30.reindex(day.values).values; d["USDT.D"] = np.where(du > 0.3, "↑", np.where(du < -0.3, "↓", "="))
    d["продлена"] = np.where(d.ext_pct > 0.5, "пятая продлена", "пятая как при детекции")
    d["свежесть"] = pd.cut(d.h_from_5, [-1, 12, 48, 1e9], labels=["≤12 ч", "12–48 ч", ">48 ч"])
    d.to_pickle(OUT / "trades.pkl")
    def agg(g):
        top = lambda x: x.sum() - x.nlargest(max(1, int(len(x) * 0.1))).sum()
        return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                     риск=("risk_pct", "median"), цель=("tgt_pct", "median"), ctl=("ctl", "mean"), безтоп10=("pnl", top)).assign(Δr=lambda x: x["ср"] - x.ctl).round(2)
    print(f"строк {len(d)} · сетапов {d.drop_duplicates(['sym', 'key', 'lvl']).shape[0]} · монет {d.sym.nunique()} · {d.entry_t.min():%Y-%m} → {d.entry_t.max():%Y-%m}")
    print("\n=== сторона × вход × цель"); print(agg(d.groupby(["side", "lvl", "target"])).to_string())
    b = d[(d.lvl == 0.5)]
    for tn in ("4h 0.382", "2R", "A"):
        z = b[b.target == tn]
        print(f"\n######## вход 0.5 · цель {tn}")
        print("--- год"); print(agg(z.groupby(["side", "год"])).to_string())
        print("--- момент рынка"); print(agg(z.groupby(["side", "момент"])).to_string())
        print("--- USDT.D"); print(agg(z.groupby(["side", "USDT.D"])).to_string())
        print("--- ядро / пятая продлена / свежесть"); print(agg(z.groupby(["side", "core_full"])).to_string()); print(agg(z.groupby(["side", "продлена"])).to_string()); print(agg(z.groupby(["side", "свежесть"], observed=True)).to_string())
        z2 = z.copy(); z2["стоп"] = pd.qcut(z2.risk_pct, 3, labels=["узкий", "средний", "широкий"], duplicates="drop")
        print("--- размер стопа"); print(agg(z2.groupby(["side", "стоп"], observed=True)).to_string())
        for s_, g in z.groupby("side"):
            print(f"  {s_}: монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(g.groupby('год').pnl.mean() > 0).sum()}/{g['год'].nunique()} · исходы {g.outcome.value_counts().to_dict()}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        import pyarrow.parquet as pq
        syms = sorted(p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9)
        with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, [(s, []) for s in syms]), 1):
                print(f"  {i}/{len(syms)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    elif sys.argv[1] == "test":
        p = OUT / f"{sys.argv[2]}.pkl"; p.unlink(missing_ok=True); print(run_symbol((sys.argv[2], [])))
        d = pd.DataFrame(pickle.load(open(p, "rb")))
        if len(d):
            print(d[(d.lvl == 0.5)].groupby(["side", "target"]).pnl.agg(["size", "mean"]).round(2).to_string()); print(d[["side", "entry_t", "risk_pct", "A_pct", "h_from_5", "ext_pct"]].drop_duplicates("entry_t").head(10).to_string())
    else:
        report()
