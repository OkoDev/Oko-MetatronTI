"""РЕПЛЕИ ДЛЯ КАРТЫ РЕЖИМОВ (Егор 20.09: «проверить choch_wavec, rangefade, impulse_fib») — ОДИН калькулятор каждой механики,
исходы считаются так же, как журналы лупов (_resolve): окно фила WAIT баров ПОСЛЕ бара сигнала, стоп до фила = INVALID,
позиция живёт HOLD баров, начиная со СЛЕДУЮЩЕГО за филом бара, стоп в приоритете над целью в одном баре, выход по времени — close.

  impulse_fib (1h)  — core.smc.impulse_fib.find_impulses по определению (ход ≥3 ATR, откат ≤0.32, ≤60 баров), лимит на 0.382,
                      стоп 2.5·ATR(b), цель −1.618, три гейта (объём 1.0–1.5× · по EMA200 · ATR/SMA100 ≥1.1), стоп 1.5–3.234%,
                      обе стороны, ≤2 позиций на монету/сторону (config max_per_symbol 2), дрейф-гейт SHADOW (не блокирует).
                      Один проход по истории с дедупом по началу импульса = журнал UNIQUE(symbol, origin_ts).
  choch_wavec (1h)  — core.smc.choch_wavec: swing-CHoCH вниз (OKO-SM swing 50 / internal 5, record_legs) → нога из leg_history[i]
                      → лимит extreme+0.236·нога, стоп origin×1.001, цель −1.0 ноги; SHORT; стоп 8–15%; медиана ATR% по 1000 барам
                      ≥1.59; ожидание 12, удержание 96. Структура считается ОДИН раз (машина каузальна; отличие от окна 1000 баров
                      бота — только метка ПЕРВОГО слома в окне, см. check_window).
  rangefade         — bot/loops/rangefade_loop: LONG; на ЗАКРЫТОМ баре ATRTrend>0 и −150 ≤ WT1 < порог (1h −70 · 4h −60 · 15m −60
                      = bigflush15); вход по open следующего бара (бой: по тику, как только состояние истинно — падающий нож);
                      SL = min(low 3 баров)×0.997, TP 1R, стоп ≤12% (bigflush 1–4%), оборот 24ч ≥ $2M, 4h: close_pos ≤ 0.7,
                      bigflush15: часы 8–20 UTC исключены + ≥1 медвежий internal-BOS за 21 бар (структура на 200 барах);
                      кластер-гейт (≥2 монеты РАЗНЫХ семейств в одном баре) и кулдаун 6 ч на монету — вторым проходом в report().
                      Удержание 72 ч (в бою — до TP/SL, лимита нет; раннер bigflush15 под TSL здесь НЕ моделируется).
Косты 0.10% на сделку (конвенция лаборатории; лимит ≈ 0.05+0.05). Контроли той же геометрии: ±30 дн той же монеты ×8 и
5 других монет в тот же момент. Вселенная: монеты с историей ≥2 лет (паркеты 1m). Окно 2020-06 → 2026-09.
Запуск: python map_replays.py run [процессов] · test SYM · check_window SYM · report · parity
"""
import sys, glob, pickle, time, random, os
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
from tfcache import load_tf, PARQ
from triangle_lab import walk, geo

OUT = Path("G:/oko_lab/out/map_replays"); OUT.mkdir(parents=True, exist_ok=True)
T0 = pd.Timestamp("2020-06-01"); COST = 0.10
MIN_TURN = 2_000_000


def _fill(hi, lo, start, wait, long_, e, sl):
    """Окно фила как в _resolve: бары start..start+wait-1; стоп раньше входа → None (INVALID)."""
    for j in range(start, min(start + wait, len(hi))):
        stop_hit = (lo[j] <= sl) if long_ else (hi[j] >= sl)
        ent_hit = (lo[j] <= e) if long_ else (hi[j] >= e)
        if stop_hit:
            return None
        if ent_hit:
            return j
    return None


def _turn(m, bars):
    return (m.close * m.volume).rolling(bars).sum().values


def impulse_fib_1h(sym, m):
    from core.smc.impulse_fib import find_impulses, _atr, WAIT_BARS, HOLD_BARS, ENTRY_FIB, TARGET_FIB, STOP_ATR_K, VOL_LO, VOL_HI, REGIME_MIN
    d = m.reset_index(drop=True); n = len(d)
    H, L, C, V = d.high.values, d.low.values, d.close.values, d.volume.values
    aa = _atr(d); atr = aa.values
    regime = (aa / aa.rolling(100).mean()).values
    ema200 = d.close.ewm(span=200, adjust=False).mean().values
    volma = pd.Series(V).rolling(120).mean().values
    turn = _turn(m, 24); mi = m.index.values
    i0 = int(np.searchsorted(mi, np.datetime64(T0)))
    imps = find_impulses(H, L, C, atr, n, start=max(60, i0 - 100))
    rows = []; open_until = {"long": [], "short": []}; fun = {"импульсов": 0, "стоп вне": 0, "гейты": 0, "лимит на монету": 0, "без фила": 0, "сделок": 0}
    for a, b, up in imps:
        if b < i0 or b + 2 >= n:
            continue
        fun["импульсов"] += 1
        side = "long" if up else "short"; origin, extreme = float(C[a]), float(C[b]); amp = abs(extreme - origin)
        if amp <= 0:
            continue
        sign = -1.0 if up else 1.0
        e = extreme + sign * ENTRY_FIB * amp
        sl = e - STOP_ATR_K * atr[b] if up else e + STOP_ATR_K * atr[b]
        tp = extreme + sign * TARGET_FIB * amp
        if (up and sl >= e) or (not up and sl <= e):
            continue
        stop_pct = abs(e - sl) / e * 100
        if not (1.5 <= stop_pct <= 3.234):
            fun["стоп вне"] += 1; continue
        vratio = float(V[a:b + 1].sum() / (b - a + 1) / volma[b]) if volma[b] > 0 else 0.0
        reg = float(regime[b]) if not np.isnan(regime[b]) else 1.0
        with_trend = bool((C[b] > ema200[b]) == up)
        if not (VOL_LO <= vratio < VOL_HI and with_trend and reg >= REGIME_MIN):
            fun["гейты"] += 1; continue
        open_until[side] = [k for k in open_until[side] if k > b]
        if len(open_until[side]) >= 2:
            fun["лимит на монету"] += 1; continue
        fill = _fill(H, L, b + 1, WAIT_BARS, up, e, sl)
        if fill is None:
            fun["без фила"] += 1; continue
        pnl, outc, k_out = walk(H, L, C, fill + 1, fill + 1 + HOLD_BARS, up, e, sl, tp)
        open_until[side].append(k_out); fun["сделок"] += 1
        rows.append({"sym": sym, "mech": "impulse_fib_1h", "side": side.upper(), "signal_t": pd.Timestamp(mi[b]), "entry_t": pd.Timestamp(mi[fill]),
                     "pnl": round(pnl, 3), "risk_pct": stop_pct, "tgt_pct": abs(tp - e) / e * 100, "hold": HOLD_BARS, "outcome": outc,
                     "turn24": float(turn[b]) if turn[b] == turn[b] else np.nan, "vratio": vratio, "regime": reg, "amp_atr": amp / atr[b],
                     "entry_px": e, "sl_px": sl})
    return rows, fun


def choch_wavec_1h(sym, m):
    from core.smc.oko_sm_engine import run_structure
    from core.smc.choch_wavec import PULLBACK, TARGET_K, WAIT_BARS, SWING_LEN
    HOLD = 96
    dd = m.reset_index(drop=True)
    st = run_structure(dd, swing_len=SWING_LEN, internal_len=5, record_legs=True)
    legs = st.leg_history
    mi = m.index.values; hi, lo, cl = m.high.values, m.low.values, m.close.values
    tr = pd.concat([m.high - m.low, (m.high - m.close.shift()).abs(), (m.low - m.close.shift()).abs()], axis=1).max(axis=1)
    atr_pct = (tr.ewm(alpha=1 / 43, adjust=False).mean() / m.close * 100).rolling(1000, min_periods=300).median().values
    turn = _turn(m, 24)
    rows = []; fun = {"CHoCH вниз": 0, "нога": 0, "стоп вне": 0, "ATR<1.59": 0, "без фила": 0, "сделок": 0}
    for ev in st.events:
        if not (ev.kind == "CHoCH" and not ev.internal and not ev.bull):
            continue
        i = int(ev.i)
        if mi[i] < np.datetime64(T0) or i + 2 >= len(m):
            continue
        fun["CHoCH вниз"] += 1
        leg = legs[i] if i < len(legs) else None
        if not leg or leg.get("trend") == "long":
            fun["нога"] += 1; continue
        origin, extreme = float(leg["origin"]), float(leg["extreme"]); leg_len = abs(extreme - origin)
        if leg_len <= 0:
            continue
        e = extreme + leg_len * PULLBACK; sl = origin * 1.001; tp = e - leg_len * TARGET_K
        if sl <= e or tp <= 0:
            continue
        stop_pct = (sl - e) / e * 100
        if not (8.0 <= stop_pct <= 15.0):
            fun["стоп вне"] += 1; continue
        if not (atr_pct[i] == atr_pct[i]) or atr_pct[i] < 1.59:
            fun["ATR<1.59"] += 1; continue
        fill = _fill(hi, lo, i + 1, WAIT_BARS, False, e, sl)
        if fill is None:
            fun["без фила"] += 1; continue
        pnl, outc, k_out = walk(hi, lo, cl, fill + 1, fill + 1 + HOLD, False, e, sl, tp)
        fun["сделок"] += 1
        rows.append({"sym": sym, "mech": "choch_wavec", "side": "SHORT", "signal_t": pd.Timestamp(mi[i]), "entry_t": pd.Timestamp(mi[fill]),
                     "pnl": round(pnl, 3), "risk_pct": stop_pct, "tgt_pct": abs(tp - e) / e * 100, "hold": HOLD, "outcome": outc,
                     "turn24": float(turn[i]) if turn[i] == turn[i] else np.nan, "atr_pct": float(atr_pct[i]), "leg_pct": leg_len / e * 100,
                     "entry_px": e, "sl_px": sl})
    return rows, fun


RF = (("1h", -70.0, "rangefade", 0.0, 12.0, 24, 72), ("4h", -60.0, "rangefade4h", 0.0, 12.0, 6, 18), ("15m", -60.0, "bigflush15", 1.0, 4.0, 96, 288))


def rangefade_variants(sym, D):
    from core.indicators.indicators import calculate_wt, calculate_trend
    from core.smc.oko_sm_engine import run_structure
    rows = []; fun = {}
    for tf, thr, src, min_stop, max_stop, tb, hold in RF:
        m = D[tf]
        if len(m) < 1500:
            continue
        w1 = calculate_wt(m[["open", "high", "low", "close"]].copy()).wt1.values
        trend = np.asarray(calculate_trend(m[["open", "high", "low", "close"]].copy())["trend"].values, dtype=float)
        mi = m.index.values; hi, lo, cl, op = m.high.values, m.low.values, m.close.values, m.open.values
        turn = _turn(m, tb); hours = pd.DatetimeIndex(m.index).hour.values
        start = max(300, int(np.searchsorted(mi, np.datetime64(T0))))
        mask = (trend > 0) & (w1 < thr) & (w1 >= -150); mask[:start] = False; mask[-2:] = False
        f = {"состояние": int(mask.sum()), "стоп вне": 0, "оборот": 0, "форма 4h": 0, "часы": 0, "BOS": 0, "кандидатов": 0}
        for t in np.flatnonzero(mask):
            px = float(cl[t]); sl = float(lo[t - 2:t + 1].min()) * 0.997
            if sl >= px:
                continue
            stop_pct = (px - sl) / px * 100
            if stop_pct < min_stop or stop_pct > max_stop:
                f["стоп вне"] += 1; continue
            if turn[t] == turn[t] and turn[t] < MIN_TURN:
                f["оборот"] += 1; continue
            if src == "rangefade4h":
                rng = hi[t] - lo[t]
                if rng > 0 and (cl[t] - lo[t]) / rng > 0.7:
                    f["форма 4h"] += 1; continue
            n_bos = np.nan
            if src == "bigflush15":
                if 8 <= hours[t + 1] < 21:
                    f["часы"] += 1; continue
                k0 = max(0, t - 199)
                st = run_structure(m.iloc[k0:t + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=50, internal_len=5)
                n_bos = sum(1 for e_ in st.events if e_.internal and e_.kind == "BOS" and not e_.bull and int(e_.i) >= (t - k0) - 20)
                if n_bos < 1:
                    f["BOS"] += 1; continue
            e = float(op[t + 1]); tp = e + (e - sl)
            if sl >= e:
                continue
            pnl, outc, k_out = walk(hi, lo, cl, t + 1, t + 1 + hold, True, e, sl, tp)
            f["кандидатов"] += 1
            rows.append({"sym": sym, "mech": src, "side": "LONG", "signal_t": pd.Timestamp(mi[t]), "entry_t": pd.Timestamp(mi[t + 1]), "pnl": round(pnl, 3),
                         "risk_pct": abs(e - sl) / e * 100, "tgt_pct": abs(tp - e) / e * 100, "hold": hold, "outcome": outc, "wt1": float(w1[t]),
                         "wt_rise": bool(w1[t] > w1[t - 1]), "n_bos": n_bos, "turn24": float(turn[t]) if turn[t] == turn[t] else np.nan})
        fun[src] = f
    return rows, fun


def run_symbol(args):
    sym, others = args
    out_p = OUT / f"{sym}.pkl"
    if out_p.exists():
        return sym, "есть"
    try:
        import psutil; psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass
    import logging; logging.disable(logging.CRITICAL)
    t0 = time.time()
    try:
        D = {tf: load_tf(sym, tf) for tf in ("15m", "1h", "4h")}
    except Exception as e:
        return sym, f"данные: {e}"
    rows = []; msg = []; funnel = {}
    for nm, fn in (("impulse_fib_1h", lambda: impulse_fib_1h(sym, D["1h"])), ("choch_wavec", lambda: choch_wavec_1h(sym, D["1h"])), ("rangefade", lambda: rangefade_variants(sym, D))):
        try:
            r, f = fn(); rows += r; funnel[nm] = f; msg.append(f"{nm} {len(r)}")
        except Exception as e:
            msg.append(f"{nm} ОШИБКА {type(e).__name__}: {str(e)[:80]}")
    if rows:
        rs = random.Random(sum(map(ord, sym)) + 17); oth = {}
        for o in rs.sample(others, min(5, len(others))):
            for tf in ("15m", "1h", "4h"):
                try:
                    oth.setdefault(tf, []).append(load_tf(o, tf))
                except Exception:
                    pass
        for r in rows:
            tf = {"bigflush15": "15m", "rangefade4h": "4h"}.get(r["mech"], "1h"); m = D[tf]
            long_ = r["side"] == "LONG"; rsk, tg = r["risk_pct"] / 100, r["tgt_pct"] / 100; et = r["entry_t"]
            a = [geo(m, et + pd.Timedelta(minutes=rs.randint(-43200, 43200)), long_, rsk, tg, r["hold"]) for _ in range(8)]
            b = [geo(o, et, long_, rsk, tg, r["hold"]) for o in oth.get(tf, [])]
            r["ctl_rand"] = np.nanmean(a) if np.isfinite(a).any() else np.nan
            r["ctl_time"] = np.nanmean(b) if b and np.isfinite(b).any() else np.nan
    pickle.dump({"rows": rows, "funnel": funnel}, open(out_p, "wb"))
    return sym, " · ".join(msg) + f" · {time.time() - t0:.0f}с"


def agg(g):
    return g.agg(n=("pnl", "size"), монет=("sym", "nunique"), WR=("pnl", lambda x: (x > 0).mean() * 100), ср=("pnl", "mean"),
                 мед=("pnl", "median"), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean"), риск=("risk_pct", "median")).assign(
        Δr=lambda x: (x["ср"] - x.ctl_r).round(2), Δt=lambda x: (x["ср"] - x.ctl_t).round(2)).round(2)


def _family(sym):
    b = "".join(ch for ch in sym.replace("USDT", "").upper() if ch.isalpha())
    return b[:4] if len(b) >= 4 else b


def load_all():
    P = [pickle.load(open(f, "rb")) for f in glob.glob(str(OUT / "*USDT.pkl"))]
    d = pd.DataFrame([r for p in P for r in p["rows"]])
    d["entry_t"] = pd.to_datetime(d.entry_t); d["signal_t"] = pd.to_datetime(d.signal_t); d["год"] = d.entry_t.dt.year
    fun = {}
    for p in P:
        for mech, f in p["funnel"].items():
            if mech == "rangefade":
                for src, ff in f.items():
                    for k, v in ff.items():
                        fun.setdefault(src, {}); fun[src][k] = fun[src].get(k, 0) + v
            else:
                for k, v in f.items():
                    fun.setdefault(mech, {}); fun[mech][k] = fun[mech].get(k, 0) + v
    # rangefade, проход 2: кластер по бару (≥2 монеты разных семейств) → кулдаун 6 ч на монету поперёк вариантов
    rf = d.mech.isin(["rangefade", "rangefade4h", "bigflush15"])
    key = d.mech.astype(str) + "|" + d.signal_t.astype(str)
    nfam = pd.DataFrame({"k": key, "f": d.sym.map(_family)})[rf].groupby("k").f.nunique()
    d["кластер"] = np.where(rf, key.map(nfam).fillna(1).astype(int), 0)
    d["вошла"] = ~rf
    z = d[rf & (d["кластер"] >= 2)].sort_values(["sym", "entry_t"])
    last = {}; ok = []
    for r in z.itertuples():
        lt = last.get(r.sym)
        if lt is not None and (r.entry_t - lt) < pd.Timedelta(hours=6):
            ok.append(False); continue
        last[r.sym] = r.entry_t; ok.append(True)
    d.loc[z.index, "вошла"] = ok
    G = pd.read_pickle("G:/oko_lab/out/usdtd_daily.pkl"); U = pd.read_pickle("G:/oko_lab/out/universe_drift_daily.pkl")
    G["dU30"] = G.usdt_d - G.usdt_d.shift(30); G["dB30"] = G.btc_d - G.btc_d.shift(30)
    day = d.entry_t.dt.floor("D") - pd.Timedelta(days=1)
    d["dU30"] = G.dU30.reindex(day.values).values; d["dB30"] = G.dB30.reindex(day.values).values
    d["drift90"] = U.drift90.reindex(day.values).values; d["drift30"] = U.drift30.reindex(day.values).values
    d["USDT.D"] = np.where(d.dU30 > 0.3, "↑", np.where(d.dU30 < -0.3, "↓", "="))
    d["BTC.D"] = np.where(d.dB30 > 1.0, "↑", np.where(d.dB30 < -1.0, "↓", "="))
    d["дрейф"] = pd.cut(d.drift90, [-999, -15, 15, 999], labels=["дрейф↓", "нейтр", "бык"])
    d["ликв"] = np.where(d.turn24 >= d.groupby("mech").turn24.transform("median"), "ликв+", "ликв−")
    return d, fun


def report():
    d, fun = load_all()
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    print(f"строк {len(d)} · монет {d.sym.nunique()} · {d.entry_t.min():%Y-%m} → {d.entry_t.max():%Y-%m}")
    print("воронки:", {k: v for k, v in fun.items()})
    rf = d.mech.isin(["rangefade", "rangefade4h", "bigflush15"])
    print("\n=== rangefade: кандидаты (без кластера) · кластер≥2 · кластер≥2+кулдаун (= бой)")
    for nm, msk in (("кандидаты", rf), ("кластер≥2", rf & (d["кластер"] >= 2)), ("бой", rf & d["вошла"])):
        print(f"--- {nm}"); print(agg(d[msk].groupby("mech")).to_string())
    print("\n--- rangefade: кластер (1 / 2 / 3+ семейств) — все кандидаты")
    print(agg(d[rf].assign(k=np.clip(d["кластер"], 1, 3)).groupby(["mech", "k"])).to_string())
    print("\n--- rangefade (бой): WT растёт на закрытом баре (условие бэктеста) vs падает (живой вход)")
    print(agg(d[rf & d["вошла"]].groupby(["mech", "wt_rise"])).to_string())
    dd = d[d["вошла"]].copy()                                   # боевая конфигурация
    print("\n=== БОЕВАЯ КОНФИГУРАЦИЯ: механика × сторона"); print(agg(dd.groupby(["mech", "side"])).to_string())
    print("\n=== механика × сторона × год (ср %)"); print(dd.groupby(["mech", "side", "год"]).pnl.mean().round(2).unstack("год").to_string())
    print("    n:"); print(dd.groupby(["mech", "side", "год"]).pnl.size().unstack("год").to_string())
    print("\n=== механика × сторона × корзина стопа"); dd["стоп"] = dd.groupby("mech").risk_pct.transform(lambda x: pd.qcut(x, 3, labels=["узкий", "средний", "широкий"], duplicates="drop"))
    print(agg(dd.groupby(["mech", "side", "стоп"], observed=True)).to_string())
    print("\n=== механика × сторона × ликвидность (оборот 24ч выше/ниже медианы механики)"); print(agg(dd.groupby(["mech", "side", "ликв"])).to_string())
    print("\n=== КАРТА: механика × сторона × USDT.D-30"); g = agg(dd.groupby(["mech", "side", "USDT.D"])); print(g[["n", "WR", "ср", "Δr", "Δt"]].to_string())
    print("\n=== КАРТА: механика × сторона × дрейф 90"); g = agg(dd.groupby(["mech", "side", "дрейф"], observed=True)); print(g[["n", "WR", "ср", "Δr", "Δt"]].to_string())
    print("\n=== КАРТА: механика × сторона × BTC.D-30"); g = agg(dd.groupby(["mech", "side", "BTC.D"])); print(g[["n", "WR", "ср", "Δr", "Δt"]].to_string())
    print("\n=== 2D: механика × сторона × USDT.D × дрейф"); g = agg(dd.groupby(["mech", "side", "USDT.D", "дрейф"], observed=True)); print(g[["n", "WR", "ср", "Δr", "Δt"]].to_string())
    print("\n=== impulse_fib_1h: сторона × размер импульса (ATR)")
    z = dd[dd.mech == "impulse_fib_1h"].copy(); z["имп"] = pd.qcut(z.amp_atr, 3, labels=["3-4", "средн", "крупн"], duplicates="drop")
    print(agg(z.groupby(["side", "имп"], observed=True)).to_string())
    print("\n=== choch_wavec: ATR% корзины · нога")
    z = dd[dd.mech == "choch_wavec"].copy(); z["ATR"] = pd.qcut(z.atr_pct, 3, labels=["1.6-", "средн", "выс"], duplicates="drop"); z["нога"] = pd.qcut(z.leg_pct, 3, labels=["кор", "средн", "длин"], duplicates="drop")
    print(agg(z.groupby(["ATR"], observed=True)).to_string()); print(agg(z.groupby(["нога"], observed=True)).to_string())
    print("\n=== хрупкость / охват")
    for (m_, s_), z in dd.groupby(["mech", "side"]):
        top = z.pnl.nlargest(max(1, int(len(z) * 0.1))).sum(); yrs = z.groupby("год").pnl.mean()
        print(f"  {m_} {s_}: n {len(z)} · сумма {z.pnl.sum():.0f} · без верхних 10% {z.pnl.sum() - top:.0f} · монет+ {(z.groupby('sym').pnl.sum() > 0).mean() * 100:.0f}% "
              f"· лет+ {(yrs > 0).sum()}/{len(yrs)} · исходы {z.outcome.value_counts().to_dict()} · сделок/год {len(z) / max(1, z['год'].nunique()):.0f}")
    d.to_pickle(OUT / "trades.pkl")


def parity():
    """Сверка с журналами боя: choch_shadow (с 19.08) и impulse_shadow (1h, с 20.08)."""
    import sqlite3
    d, _ = load_all(); c = sqlite3.connect(ROOT / "subscriptions.db")
    for tbl, mech, ts in (("choch_shadow", "choch_wavec", "choch_ts"), ("impulse_shadow", "impulse_fib_1h", "impulse_ts")):
        cols = "symbol,%s,entry,stop_loss,status,result_pct" % ts + (",side" if mech != "choch_wavec" else "")
        J = pd.read_sql(f"SELECT {cols} FROM {tbl}", c); J["sym"] = J.symbol.str.split("/").str[0] + "USDT"; J["t"] = pd.to_datetime(J[ts])
        J = J.drop_duplicates(["sym", "t"])
        R = d[(d.mech == mech) & (d.signal_t >= J.t.min() - pd.Timedelta(days=1))]
        print(f"\n=== {tbl}: журнал {len(J)} сетапов ({J.t.min():%d.%m} → {J.t.max():%d.%m}), монет {J.sym.nunique()} · реплей за то же время: {len(R)} СДЕЛОК (журнал считает и нефилленные)")
        inu = J.sym.isin(set(p.stem for p in PARQ.glob("*.parquet"))); print(f"  журнал: монет в моей вселенной {J[inu].sym.nunique()}/{J.sym.nunique()} (остальные — молодые монеты без 2 лет истории или не в паркетах)")
        hits = 0
        for r in J[inu].itertuples():
            q = R[(R.sym == r.sym) & ((R.signal_t - r.t).abs() <= pd.Timedelta(hours=2))]
            if len(q):
                hits += 1; print(f"  ✓ {r.sym} {r.t:%d.%m %H:%M} журнал entry {r.entry:.6g} стоп {r.stop_loss:.6g} {r.status} {r.result_pct} ↔ реплей {q.iloc[0].get('entry_px', np.nan):.6g} pnl {q.iloc[0].pnl}")
            else:
                print(f"  ✗ {r.sym} {r.t:%d.%m %H:%M} {r.status} — в реплее нет (гейт/фил/окно)")
        print(f"  совпало {hits}/{int(inu.sum())}")


def check_window(sym):
    """Отличие полной истории от окна 1000 баров бота: сетапы choch по окну (шаг 6) vs по полному прогону, 2025-26."""
    from core.smc.choch_wavec import find_setup
    m = load_tf(sym, "1h"); full, _ = choch_wavec_1h(sym, m); F = {r["signal_t"] for r in full}
    W = set(); t0 = int(np.searchsorted(m.index.values, np.datetime64("2025-01-01")))
    for t in range(t0, len(m), 6):
        s = find_setup(m.iloc[t - 999:t + 1], symbol=sym, drop_last=False)
        if s and "reason" not in s and s["age"] <= 5 and 8 <= s["stop_pct"] <= 15 and s["atr_pct"] >= 1.59:
            W.add(pd.Timestamp(m.index[s["i"] + (t - 999)]))
    F25 = {t for t in F if t >= pd.Timestamp("2025-01-01")}
    print(f"{sym}: полный прогон {len(F25)} сетапов с 2025 (с филом) · окно 1000 {len(W)} сетапов (до фила) · общих {len(F25 & W)} · только полный {sorted(F25 - W)[:5]} · только окно {sorted(W - F25)[:5]}")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        import pyarrow.parquet as pq
        syms = sorted(p.stem for p in PARQ.glob("*.parquet") if pq.read_metadata(p).num_rows >= 2 * 365 * 1440 * 0.9)
        print(f"вселенная: {len(syms)} монет ≥2 лет", flush=True)
        jobs = [(s, [o for o in syms if o != s]) for s in syms]
        with Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 6) as pool:
            for i, (s, msg) in enumerate(pool.imap_unordered(run_symbol, jobs), 1):
                print(f"  {i}/{len(jobs)} {s}: {msg}", flush=True)
        print("ГОТОВО", flush=True)
    elif sys.argv[1] == "test":
        sym = sys.argv[2]; p = OUT / f"{sym}.pkl"
        if p.exists():
            p.unlink()
        print(run_symbol((sym, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LINKUSDT", "ADAUSDT"])))
        P = pickle.load(open(p, "rb")); print(P["funnel"]); d = pd.DataFrame(P["rows"])
        if len(d):
            print(d.groupby("mech").agg(n=("pnl", "size"), ср=("pnl", "mean"), WR=("pnl", lambda x: (x > 0).mean()), ctl_r=("ctl_rand", "mean"), ctl_t=("ctl_time", "mean")).round(2))
    elif sys.argv[1] == "check_window":
        check_window(sys.argv[2])
    elif sys.argv[1] == "parity":
        parity()
    else:
        report()
