"""СБОРКА «СОСТОЯНИЕ → ТРИГГЕР → ГЕОМЕТРИЯ» ЦЕЛИКОМ (Егор 22.09: «замерить эту сборку целиком! на разных ТФ с разными
признаками и наборами для входа + цели с учётом альтсезонов + моментов, когда всё безоткатно растёт»).
Каузально, 222 монеты, 2020-06→2026-09, один прогон на монету.

СОСТОЯНИЯ (старший ТФ H ∈ {4h, 1d}), сторона сделки = разворот:
  fifth  — завершённая пятёрка ядра (wave_phase_ctx: импульс виден на баре; окно 60 баров H от первого появления ключа)
  leg    — экстремум противоположной ноги OKO-SM (swing 50/internal 5 на H) снят: low бара ≤ экстремум даунлега (для LONG),
           окно 10 баров H
  wt     — WT1 на H ниже −60 (для LONG) / выше +60 (SHORT), окно 10 баров H
ТРИГГЕРЫ (младший ТФ, первый после начала состояния, в сторону разворота):
  none      — вход по open первого LTF-бара после начала состояния (база: «состояние само по себе»)
  wt_cross  — кросс WT1×WT2 на 1h в сторону (wt1 < −45 / > +45 в момент кросса)
  impulse   — импульс 1h по определению impulse_fib (≥3 ATR, откат ≤0.32, ≤60 баров) в сторону, вход по close бара конца
  imp_limit — тот же импульс, лимит на 0.382 (как бой impulse_fib), окно 12 баров
  choch15   — swing-CHoCH на 15m (swing 50) в сторону, вход по close бара слома
  choch1h   — internal-CHoCH (len 5) на 1h в сторону
ГЕОМЕТРИЯ: стоп за экстремумом состояния (буфер 0.3%; для impulse/imp_limit дополнительно родной 2.5·ATR);
  выходы БЕЗ времени: p4 (конец 4-й — только fifth) · swing (ближайший internal-свинг H против входа) · trail1h (после +1R —
  первый internal-CHoCH 1h против позиции; горизонт 30 дн) · trail4h (то же на 4h — для безоткатного роста).
Контроли (для фиксированных целей): случайный вход той же геометрии ±30 дн той же монеты ×6.
Режимы: дрейф90 (альтсезон >15) · USDT.D-30 · «безоткатный рост» = дрейф30 вселенной > +25%. Кластер — монет в том же
состоянии в тот же день (post-hoc). Запуск: python assembly_lab.py run [proc] · report"""
import sys, glob, pickle, random, time, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot"); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
OUT = Path(os.environ.get("ASM_OUT", "G:/oko_lab/out/assembly")); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01"); COST = 0.10; BUF = 0.003
WIN_STATE = {"fifth": 60, "leg": 10, "wt": 10}; HORIZON_D = 30
HTF_H = {"4h": 4, "1d": 24}


def _walk(hi, lo, cl, j0, j1, long_, e, sl, tp=None, exit_bars=None):
    """Стоп / цель (если есть) / структурный выход (exit_bars — множество индексов 15m-баров, на закрытии которых выходим,
    только после того как сделка была ≥ +1R) / горизонт по close."""
    rk = abs(e - sl); armed = False
    for k in range(j0, min(j1, len(hi))):
        if (lo[k] <= sl) if long_ else (hi[k] >= sl):
            return ((sl - e) / e * 100) * (1 if long_ else -1) - COST, "stop", k
        if tp is not None and ((hi[k] >= tp) if long_ else (lo[k] <= tp)):
            return ((tp - e) / e * 100) * (1 if long_ else -1) - COST, "target", k
        if exit_bars is not None:
            if not armed and ((hi[k] - e >= rk) if long_ else (e - lo[k] >= rk)):
                armed = True
            if armed and k in exit_bars:
                return ((cl[k] - e) / e * 100) * (1 if long_ else -1) - COST, "trail", k
    k = min(j1, len(hi)) - 1
    return ((cl[k] - e) / e * 100) * (1 if long_ else -1) - COST, "horizon", k


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
    from core.smc.oko_sm_engine import run_structure, _swings
    from core.indicators.indicators import calculate_wt
    from core.smc.impulse_fib import find_impulses, _atr, ENTRY_FIB, STOP_ATR_K
    from triangle_lab import geo
    t_start = time.time()
    try:
        D = {tf: load_tf(sym, tf) for tf in ("15m", "1h", "4h", "1d")}
    except Exception as e:
        return sym, f"данные {e}"
    d15 = D["15m"]; i15 = d15.index.values; hi, lo, cl, op = d15.high.values, d15.low.values, d15.close.values, d15.open.values
    if len(d15) < 20000:
        pickle.dump([], open(out_p, "wb")); return sym, "мало истории"
    # ---- LTF-инструменты (1h): WT, импульсы, internal-CHoCH; 15m: swing-CHoCH
    h1 = D["1h"]; i1 = h1.index.values
    w = calculate_wt(h1[["open", "high", "low", "close"]].copy()); wt1, wt2 = w.wt1.values, w.wt2.values
    H, L, C = h1.high.values, h1.low.values, h1.close.values; atr1 = _atr(h1.reset_index(drop=True)).values
    imps = find_impulses(H, L, C, atr1, len(h1), start=60)
    imp_by_dir = {"LONG": [(a, b) for a, b, up in imps if up], "SHORT": [(a, b) for a, b, up in imps if not up]}
    st1 = run_structure(h1.reset_index(drop=True)[["open", "high", "low", "close"]], swing_len=50, internal_len=5, record_legs=False)
    ch1 = {"LONG": sorted(e.i for e in st1.events if e.internal and e.kind == "CHoCH" and e.bull), "SHORT": sorted(e.i for e in st1.events if e.internal and e.kind == "CHoCH" and not e.bull)}
    st15 = run_structure(d15.reset_index(drop=True)[["open", "high", "low", "close"]], swing_len=50, internal_len=5, record_legs=False)
    ch15 = {"LONG": sorted(e.i for e in st15.events if not e.internal and e.kind == "CHoCH" and e.bull), "SHORT": sorted(e.i for e in st15.events if not e.internal and e.kind == "CHoCH" and not e.bull)}
    exit1h = {"LONG": set(), "SHORT": set()}                     # выход из LONG — медвежий internal-CHoCH 1h (в индексах 15m)
    for e in st1.events:
        if e.internal and e.kind == "CHoCH":
            k15 = int(np.searchsorted(i15, i1[e.i] + np.timedelta64(60, "m"))) - 1     # закрытие того 1h бара
            (exit1h["LONG"] if not e.bull else exit1h["SHORT"]).add(k15)
    h4 = D["4h"]; i4 = h4.index.values
    st4 = run_structure(h4.reset_index(drop=True)[["open", "high", "low", "close"]], swing_len=50, internal_len=5, record_legs=True)
    exit4h = {"LONG": set(), "SHORT": set()}; exit4hS = {"LONG": set(), "SHORT": set()}
    for e in st4.events:
        if e.kind == "CHoCH":
            k15 = int(np.searchsorted(i15, i4[e.i] + np.timedelta64(240, "m"))) - 1
            tgt = exit4h if e.internal else exit4hS
            (tgt["LONG"] if not e.bull else tgt["SHORT"]).add(k15)
    d1 = D["1d"]; i1d = d1.index.values
    st1d = run_structure(d1.reset_index(drop=True)[["open", "high", "low", "close"]], swing_len=50, internal_len=5, record_legs=True)
    exit1d = {"LONG": set(), "SHORT": set()}
    for e in st1d.events:
        if e.internal and e.kind == "CHoCH":
            k15 = int(np.searchsorted(i15, i1d[e.i] + np.timedelta64(1440, "m"))) - 1
            (exit1d["LONG"] if not e.bull else exit1d["SHORT"]).add(k15)
    # ---- СОСТОЯНИЯ на H
    states = []
    for Hf in ("4h", "1d"):
        dh = D[Hf]; ih = dh.index.values; hh, lh = dh.high.values, dh.low.values
        bar_h = HTF_H[Hf]
        # fifth — из сканов ядра
        p = Path("G:/oko_lab/out/wave_phase_ctx") / ("" if Hf == "4h" else Hf) / f"{sym}.pkl"
        if p.exists():
            S = pickle.load(open(p, "rb"))
            if len(S):
                first = S.sort_values("tt").groupby("key").first()
                for key, x in first.iterrows():
                    states.append({"H": Hf, "state": "fifth", "side": x.side, "t0": pd.Timestamp(x.time) + pd.Timedelta(hours=bar_h),
                                   "t1": pd.Timestamp(x.time) + pd.Timedelta(hours=bar_h * WIN_STATE["fifth"]), "ext": float(x.p5), "p4": float(x.p4), "p0": float(x.p0), "q": "core_full" if x.core_full else ("core" if x.core else "пятёрка")})
        # leg — экстремум противоположной ноги снят (нога по закрытому предыдущему бару)
        sth = st4 if Hf == "4h" else run_structure(dh.reset_index(drop=True)[["open", "high", "low", "close"]], swing_len=50, internal_len=5, record_legs=True)
        legs = sth.leg_history; last_fire = {"LONG": -999, "SHORT": -999}
        for k in range(1, len(dh) - 1):
            leg = legs[k - 1] if k - 1 < len(legs) else None
            if not leg or ih[k] < np.datetime64(T0):
                continue
            if leg["trend"] == "short" and lh[k] <= float(leg["extreme"]) and k - last_fire["LONG"] > WIN_STATE["leg"]:
                states.append({"H": Hf, "state": "leg", "side": "LONG", "t0": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h), "t1": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h * (WIN_STATE["leg"] + 1)), "ext": float(min(lh[k], leg["extreme"])), "p4": np.nan, "p0": float(leg["origin"]), "q": "—"}); last_fire["LONG"] = k
            if leg["trend"] == "long" and hh[k] >= float(leg["extreme"]) and k - last_fire["SHORT"] > WIN_STATE["leg"]:
                states.append({"H": Hf, "state": "leg", "side": "SHORT", "t0": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h), "t1": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h * (WIN_STATE["leg"] + 1)), "ext": float(max(hh[k], leg["extreme"])), "p4": np.nan, "p0": float(leg["origin"]), "q": "—"}); last_fire["SHORT"] = k
        # wt — глубокая зона WT на H
        wh = calculate_wt(dh[["open", "high", "low", "close"]].copy()).wt1.values; last_fire = {"LONG": -999, "SHORT": -999}
        for k in range(1, len(dh) - 1):
            if ih[k] < np.datetime64(T0):
                continue
            if wh[k] < -60 and k - last_fire["LONG"] > WIN_STATE["wt"]:
                states.append({"H": Hf, "state": "wt", "side": "LONG", "t0": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h), "t1": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h * (WIN_STATE["wt"] + 1)), "ext": float(lh[max(0, k - 5):k + 1].min()), "p4": np.nan, "p0": np.nan, "q": "—"}); last_fire["LONG"] = k
            if wh[k] > 60 and k - last_fire["SHORT"] > WIN_STATE["wt"]:
                states.append({"H": Hf, "state": "wt", "side": "SHORT", "t0": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h), "t1": pd.Timestamp(ih[k]) + pd.Timedelta(hours=bar_h * (WIN_STATE["wt"] + 1)), "ext": float(hh[max(0, k - 5):k + 1].max()), "p4": np.nan, "p0": np.nan, "q": "—"}); last_fire["SHORT"] = k
    # ---- ближайший internal-свинг 4h как цель
    sw4 = _swings(h4.reset_index(drop=True)["high"], h4.reset_index(drop=True)["low"], 5)     # (conf_i, sw_i, price, is_top)
    sw_tops = [(int(c), float(px)) for c, s_, px, top in sw4 if top]; sw_bots = [(int(c), float(px)) for c, s_, px, top in sw4 if not top]
    # ---- ТРИГГЕРЫ и сделки
    rows = []; rs = random.Random(sum(map(ord, sym)) + 5)
    def entries(st):
        long_ = st["side"] == "LONG"; t0, t1 = np.datetime64(st["t0"]), np.datetime64(st["t1"]); out = {}
        j0 = int(np.searchsorted(i15, t0)); out["none"] = (j0, float(op[j0]) if j0 < len(op) else np.nan)
        k0, k1 = int(np.searchsorted(i1, t0)), int(np.searchsorted(i1, t1))
        for k in range(max(k0, 1), min(k1, len(h1) - 1)):
            if long_ and wt1[k - 1] <= wt2[k - 1] and wt1[k] > wt2[k] and wt1[k] < -45:
                j = int(np.searchsorted(i15, i1[k] + np.timedelta64(60, "m"))); out["wt_cross"] = (j, float(op[j]) if j < len(op) else np.nan); break
            if not long_ and wt1[k - 1] >= wt2[k - 1] and wt1[k] < wt2[k] and wt1[k] > 45:
                j = int(np.searchsorted(i15, i1[k] + np.timedelta64(60, "m"))); out["wt_cross"] = (j, float(op[j]) if j < len(op) else np.nan); break
        for a, b in imp_by_dir[st["side"]]:
            if k0 <= b < k1:
                j = int(np.searchsorted(i15, i1[b] + np.timedelta64(60, "m"))); out["impulse"] = (j, float(op[j]) if j < len(op) else np.nan, a, b)
                amp = abs(C[b] - C[a]); e_lim = C[b] - ENTRY_FIB * amp if long_ else C[b] + ENTRY_FIB * amp
                jf = None
                for jj in range(j, min(j + 12 * 4, len(d15))):
                    if (lo[jj] <= e_lim) if long_ else (hi[jj] >= e_lim):
                        jf = jj; break
                if jf is not None:
                    out["imp_limit"] = (jf, e_lim, a, b)
                break
        for kk in ch15[st["side"]]:
            if np.searchsorted(i15, t0) <= kk < np.searchsorted(i15, t1):
                out["choch15"] = (kk + 1, float(op[kk + 1]) if kk + 1 < len(op) else np.nan); break
        for kk in ch1[st["side"]]:
            if k0 <= kk < k1:
                j = int(np.searchsorted(i15, i1[kk] + np.timedelta64(60, "m"))); out["choch1h"] = (j, float(op[j]) if j < len(op) else np.nan); break
        return out
    for st in states:
        long_ = st["side"] == "LONG"
        for trg, val in entries(st).items():
            j, e = val[0], val[1]
            if not (e == e) or j >= len(d15) - 10:
                continue
            sl = st["ext"] * (1 - BUF) if long_ else st["ext"] * (1 + BUF)
            if (long_ and sl >= e) or (not long_ and sl <= e):
                continue
            geoms = {"state": sl}
            if trg in ("impulse", "imp_limit"):
                b = val[3]; sl_i = e - STOP_ATR_K * atr1[b] if long_ else e + STOP_ATR_K * atr1[b]
                if (long_ and sl_i < e) or (not long_ and sl_i > e):
                    geoms["atr2.5"] = sl_i
            # цели
            k4 = int(np.searchsorted(i4, i15[j], "right")) - 1
            tops = [px for c, px in sw_tops if c <= k4 and px > e]; bots = [px for c, px in sw_bots if c <= k4 and px < e]
            tp_sw = (min(tops) if tops else None) if long_ else (max(bots) if bots else None)
            tp_sw = tp_sw if (tp_sw is not None and abs(tp_sw - e) / e > 0.005) else None
            j1 = int(np.searchsorted(i15, i15[j] + np.timedelta64(HORIZON_D, "D")))
            for gname, sl_ in geoms.items():
                rk = abs(e - sl_) / e
                exits = {"trail1h": (None, exit1h[st["side"]]), "trail4h": (None, exit4h[st["side"]]),
                         "trail4hS": (None, exit4hS[st["side"]]), "trail1d": (None, exit1d[st["side"]])}
                if st.get("p0") == st.get("p0") and ((st["p0"] > e) if long_ else (st["p0"] < e)):
                    exits["p0"] = (float(st["p0"]), None)
                if tp_sw is not None:
                    exits["swing"] = (tp_sw, None)
                if st["state"] == "fifth" and st["p4"] == st["p4"] and ((st["p4"] > e) if long_ else (st["p4"] < e)):
                    exits["p4"] = (float(st["p4"]), None)
                for xname, (tp, xb) in exits.items():
                    pnl, outc, k_out = _walk(hi, lo, cl, j, j1, long_, e, sl_, tp, xb)
                    rec = {"sym": sym, "H": st["H"], "state": st["state"], "q": st["q"], "side": st["side"], "trigger": trg, "geom": gname, "exit": xname,
                           "state_t": st["t0"], "entry_t": pd.Timestamp(i15[j]), "risk_pct": rk * 100, "pnl": round(pnl, 3), "outcome": outc,
                           "bars": k_out - j, "wait_h": (pd.Timestamp(i15[j]) - st["t0"]).total_seconds() / 3600}
                    if tp is not None:
                        tg = abs(tp - e) / e
                        a = [geo(d15, rec["entry_t"] + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rk, tg, j1 - j) for _ in range(6)]
                        rec["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan; rec["tgt_pct"] = tg * 100
                    rows.append(rec)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"состояний {len(states)} · строк {len(rows)} за {time.time() - t_start:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"), мед=("pnl", "median"),
                 риск=("risk_pct", "median"), ctl=("ctl_rand", "mean")).assign(Δr=lambda x: (x["ср"] - x.ctl).round(2)).round(2)


def report():
    d = pd.DataFrame([r for f in glob.glob(str(OUT / "*USDT.pkl")) for r in pickle.load(open(f, "rb"))])
    d["год"] = d.entry_t.dt.year
    G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl"); G["dU30"] = G.usdt_d - G.usdt_d.shift(30)
    day = d.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    d["dU30"] = G.dU30.reindex(day.values).values; d["drift90"] = U.drift90.reindex(day.values).values; d["drift30"] = U.drift30.reindex(day.values).values
    d["USDT.D"] = np.where(d.dU30 > 0.3, "↑", np.where(d.dU30 < -0.3, "↓", "=")); d["дрейф"] = pd.cut(d.drift90, [-999, -15, 15, 999], labels=["дрейф↓", "нейтр", "альтсезон"])
    d["момент"] = np.where(d.drift30 > 25, "безоткатный рост", np.where(d.drift30 < -20, "обвал", "обычный"))
    key = d.H + "|" + d.state + "|" + d.side + "|" + d.state_t.dt.floor("D").astype(str)
    d["кластер"] = key.map(d.drop_duplicates(["sym", "H", "state", "side", "state_t"]).assign(k=key).groupby("k").sym.nunique())
    d.to_pickle(OUT / "trades.pkl")
    pd.set_option("display.width", 260); pd.set_option("display.max_rows", 1000)
    print(f"строк {len(d)} · монет {d.sym.nunique()} · {d.entry_t.min():%Y-%m} → {d.entry_t.max():%Y-%m}")
    EX = ["swing", "p4", "p0", "trail1h", "trail4h", "trail4hS", "trail1d"]
    print("\n################ ДАЛЬНЯЯ ЦЕЛЬ И ВЫХОД СО СТАРШЕГО ТФ — H=4h, стоп за состоянием: состояние × сторона × выход (все триггеры)")
    z = d[(d.H == "4h") & (d.geom == "state")]
    g = agg(z.groupby(["state", "side", "exit"])); print(g.to_string())
    print("\n=== fifth × сторона × триггер × выход (H=4h, стоп за пятой), n≥20")
    g = agg(z[z.state == "fifth"].groupby(["side", "trigger", "exit"])); print(g[g.n >= 20].to_string())
    print("\n=== impulse_fib перемер (H=4h): fifth × сторона × стоп × выход, триггер impulse/imp_limit")
    g = agg(d[(d.H == "4h") & (d.state == "fifth") & d.trigger.isin(["impulse", "imp_limit"])].groupby(["side", "trigger", "geom", "exit"])); print(g[g.n >= 20].to_string())
    print("\n=== выход × дрейф90 / момент (H=4h, все состояния, стоп за состоянием) — ср")
    print(z.groupby(["side", "exit", "дрейф"], observed=True).pnl.agg(["size", "mean"]).round(2).unstack("дрейф").to_string())
    print(z.groupby(["side", "exit", "момент"]).pnl.agg(["size", "mean"]).round(2).unstack("момент").to_string())
    print("\n=== fifth LONG: выход × год (ср)"); print(z[(z.state == "fifth") & (z.side == "LONG")].groupby(["exit", "год"]).pnl.mean().round(2).unstack("год").to_string())
    print("\n=== H=1d: fifth × сторона × выход"); print(agg(d[(d.H == "1d") & (d.geom == "state") & (d.state == "fifth")].groupby(["side", "exit"])).to_string())
    print("\n=== хрупкость (H=4h, стоп за состоянием, n≥100, ср>0.8)")
    for (st_, sd, tr, ex), g in z.groupby(["state", "side", "trigger", "exit"]):
        if len(g) < 100 or g.pnl.mean() <= 0.8:
            continue
        top = g.pnl.nlargest(int(len(g) * 0.1)).sum(); yrs = g.groupby("год").pnl.mean()
        print(f"  {st_}/{sd}/{tr}/{ex}: n {len(g)} · ср {g.pnl.mean():+.2f} · WR {(g.pnl > 0).mean() * 100:.0f}% · мед {g.pnl.median():+.2f} · без топ-10% {g.pnl.sum() - top:+.0f} · монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(yrs > 0).sum()}/{len(yrs)} · исходы {g.outcome.value_counts().to_dict()} · баров {g.bars.median():.0f}")
    return
    for Hf in ("4h", "1d"):
        z = d[d.H == Hf]
        print(f"\n################ H = {Hf}: состояние × сторона × триггер — выход swing (фикс. цель, есть контроль)")
        g = agg(z[(z.exit == "swing") & (z.geom == "state")].groupby(["state", "side", "trigger"])); print(g[g.n >= 30].to_string())
        print(f"\n=== {Hf}: состояние × сторона × ВЫХОД (триггер none, стоп за состоянием)")
        g = agg(z[(z.trigger == "none") & (z.geom == "state")].groupby(["state", "side", "exit"])); print(g[g.n >= 30].to_string())
        print(f"\n=== {Hf}: fifth × триггер × выход (стоп за пятой)")
        g = agg(z[(z.state == "fifth") & (z.geom == "state")].groupby(["side", "trigger", "exit"])); print(g[g.n >= 20].to_string())
        print(f"\n=== {Hf}: impulse_fib перемер — состояние × стоп (за состоянием / 2.5 ATR) × выход, триггер impulse и imp_limit")
        g = agg(z[z.trigger.isin(["impulse", "imp_limit"])].groupby(["state", "side", "trigger", "geom", "exit"])); print(g[g.n >= 20].to_string())
    print("\n################ РЕЖИМЫ (H=4h, все состояния, стоп за состоянием): выход × дрейф90 (альтсезон) — ср")
    z = d[(d.H == "4h") & (d.geom == "state")]
    print(z.groupby(["side", "exit", "дрейф"], observed=True).pnl.agg(["size", "mean"]).round(2).unstack("дрейф").to_string())
    print("\n=== выход × момент (безоткатный рост / обвал / обычный) — ср"); print(z.groupby(["side", "exit", "момент"]).pnl.agg(["size", "mean"]).round(2).unstack("момент").to_string())
    print("\n=== состояние × сторона × USDT.D (выход swing)"); print(agg(z[z.exit == "swing"].groupby(["state", "side", "USDT.D"])).to_string())
    print("\n=== кластер (монет в том же состоянии в тот же день): 1 / 2-3 / 4+ (H=4h, none, swing)")
    z2 = z[(z.trigger == "none") & (z.exit == "swing")].copy(); z2["k"] = pd.cut(z2["кластер"], [0, 1, 3, 999], labels=["1", "2-3", "4+"])
    print(agg(z2.groupby(["state", "side", "k"], observed=True)).to_string())
    print("\n=== по годам: H=4h, fifth, триггер × выход (LONG, ср)")
    z3 = d[(d.H == "4h") & (d.state == "fifth") & (d.side == "LONG") & (d.geom == "state")]
    print(z3.groupby(["trigger", "exit", "год"]).pnl.mean().round(2).unstack("год").to_string())
    print("\n=== хрупкость лучших клеток (H=4h, стоп за состоянием)")
    for (st_, sd, tr, ex), g in z.groupby(["state", "side", "trigger", "exit"]):
        if len(g) < 100:
            continue
        top = g.pnl.nlargest(int(len(g) * 0.1)).sum(); yrs = g.groupby("год").pnl.mean()
        if g.pnl.mean() > 1.0:
            print(f"  {st_}/{sd}/{tr}/{ex}: n {len(g)} · ср {g.pnl.mean():+.2f} · WR {(g.pnl > 0).mean() * 100:.0f}% · мед {g.pnl.median():+.2f} · без топ-10% {g.pnl.sum() - top:+.0f} · монет+ {(g.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% · лет+ {(yrs > 0).sum()}/{len(yrs)} · исходы {g.outcome.value_counts().to_dict()}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        import pyarrow.parquet as pq
        syms = sorted(p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9)
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, jobs), 1):
                print(f"  {i}/{len(jobs)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    elif sys.argv[1] == "test":
        p = OUT / f"{sys.argv[2]}.pkl"; p.unlink(missing_ok=True); print(run_symbol((sys.argv[2], [])))
        d = pd.DataFrame(pickle.load(open(p, "rb"))); print(d.groupby(["H", "state", "trigger", "exit"]).pnl.agg(["size", "mean"]).round(2).to_string())
    else:
        report()
