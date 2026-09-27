"""МЕХАНИКА ПРОДОЛЖЕНИЯ (Егор 17.09: «SYN дал 90% движения, а сколько из него забрали бы мы?»).
На SYN наша цель (конец волны 4) забрала 19.5% из 181% хода — 11% движения. Вопрос: как взять хвост.

Считаются варианты выхода на ОДНИХ И ТЕХ ЖЕ сделках (вход, стоп, окна — боевые, кост 0.10%):
  w4            — как сейчас: всё на конце волны 4
  trail24       — всё на трейле (стоп под минимум 24 ч) после хода 1R — то, что уже есть в ядре
  trail72/168   — то же, но стоп под минимум 72 / 168 ч (свободнее, не душит памп)
  half+trail72  — половина на цели w4, остаток на трейле 72 ч
  half+ext      — половина на цели, остаток до расширения 1.618 от ноги вверх
Плюс печатается ПОТЕНЦИАЛ: максимум после взятия цели (сколько хода осталось на столе).
Запуск: python runner_lab.py run [монет] [процессов] · report
"""
import sys, pickle, time, glob
from pathlib import Path
from multiprocessing import Pool
import numpy as np, pandas as pd
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT))
from tfcache import load_tf, PARQ
import tf_sweep as T

OUT = Path("G:/oko_lab/out/runner_lab"); OUT.mkdir(parents=True, exist_ok=True)
TF, LTF = "4h", "15m"
COST = 0.10


def _trail(x, j, e, sl, trail_h, end_i):
    """Трейл: после хода в 1R стоп = max(стоп, вход, минимум последних trail_h часов). Возврат (цена, исход)."""
    hi, lo, cl = x.high.values, x.low.values, x.close.values
    bars = max(1, int(trail_h * 4))          # 15m баров в часе = 4
    risk = e - sl
    tsl, armed = sl, False
    for k in range(j, end_i + 1):
        if lo[k] <= tsl:
            return tsl, ("trail" if armed else "stop")
        if not armed and hi[k] >= e + risk:
            armed = True
        if armed:
            tsl = max(tsl, e, float(lo[max(j, k - bars):k + 1].min()))
    return float(cl[end_i]), "time"


def _cascade(x, j, e, sl, end_i, deesc_r=2.5, no_degrade_r=8.0):
    """Каскадный TSL как в бою (core/trading/cascade_tsl.py): стоп идёт по структуре, а ТФ структуры
    ЭСКАЛИРУЕТСЯ с ростом R — 15m → 1h → 4h. Смысл: чем дальше ушла сделка, тем шире окно, тем меньше
    шансов, что памп вытряхнет. Плюс anti-degradation: после no_degrade_r стоп только расширяется.
    Окна взяты в барах 15m: 8 ≈ структура 15m, 24 ≈ 1h, 96 ≈ 4h (пороги R — боевые)."""
    hi, lo, cl = x.high.values, x.low.values, x.close.values
    risk = e - sl
    if risk <= 0:
        return float(cl[end_i]), "time"
    tsl, armed, peak_r = sl, False, 0.0
    for k in range(j, end_i + 1):
        if lo[k] <= tsl:
            return tsl, ("trail" if armed else "stop")
        r_now = (hi[k] - e) / risk
        peak_r = max(peak_r, r_now)
        if not armed and r_now >= 1.0:
            armed = True
        if armed:
            win = 8 if peak_r < deesc_r else (24 if peak_r < no_degrade_r else 96)
            cand = float(lo[max(j, k - win):k + 1].min())
            tsl = max(tsl, e, cand)          # только вверх: деградацию стопа не допускаем
    return float(cl[end_i]), "time"


def _wave_trail(x, j, e, sl, end_i, sw=15, il=4):
    """ВОЛНОВОЙ трейл (Егор 17.09: «каскадный TSL можно доработать по волновой теории»).
    Наш вход — коррекция после завершённой пятой ВНИЗ. Значит симметрично: пока вверх строится новый
    импульс, стоп идёт под его подтверждённые свинг-минимумы (точки 2, затем 4), а выход — когда
    структура вверх ломается (первый медвежий CHoCH swing) либо по времени. Это тот же движок
    структуры, что в ядре, — не новая сущность."""
    from core.smc.oko_sm_engine import run_structure, _swings
    sub = x.iloc[j:end_i + 1].reset_index(drop=True)
    if len(sub) < 60:
        return float(x.close.values[end_i]), "time"
    try:
        st = run_structure(sub[["open", "high", "low", "close"]], swing_len=sw, internal_len=il)
        lows = [(c, i, p) for c, i, p, is_top in _swings(sub["high"], sub["low"], sw) if not is_top]
    except Exception:
        return float(x.close.values[end_i]), "time"
    bear = {ev.i for ev in st.events if ev.kind == "CHoCH" and not ev.bull and not ev.internal}
    hi, lo, cl = sub.high.values, sub.low.values, sub.close.values
    tsl = sl; li = 0
    for k in range(len(sub)):
        while li < len(lows) and lows[li][0] <= k:          # свинг подтверждён к бару k
            tsl = max(tsl, float(lows[li][2]))              # стоп под последний подтверждённый минимум
            li += 1
        if lo[k] <= tsl:
            return tsl, "wave_stop"
        if k in bear and k > 0:                             # структура вверх сломалась — выходим
            return float(cl[k]), "wave_choch"
    return float(cl[-1]), "time"


def _atr_trail(x, j, e, sl, end_i, mult=3.0, period=56):
    """ATR-трейл: стоп = достигнутый максимум − mult×ATR. period в барах 15m (56 ≈ 14 часов, т.е. ATR(14) на 1h).
    Затухание учитывается само: с ростом ATR стоп отпускается, при затихании — подтягивается."""
    hi, lo, cl = x.high.values, x.low.values, x.close.values
    tr = np.maximum(hi[1:] - lo[1:], np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    atr = pd.Series(tr).rolling(period).mean().values
    tsl, peak = sl, e
    for k in range(j, end_i + 1):
        if lo[k] <= tsl:
            return tsl, "atr_stop"
        peak = max(peak, float(hi[k]))
        a = atr[k - 1] if 0 < k - 1 < len(atr) and np.isfinite(atr[k - 1]) else None
        if a:
            tsl = max(tsl, peak - mult * float(a))
    return float(cl[end_i]), "time"


def _pivots(d1, when, period="W"):
    """Пивоты ПРЕДЫДУЩЕГО полного периода (недели/месяца) по канону проекта
    (core.indicators.calculate_pivot_points, формулы Pine). Считаются на дневных барах, каузально:
    берётся период, полностью закрытый ДО `when`. Егор 17.09: «по пивотам обычно цели это уровни
    2-3 и выше, для пампов до 5»."""
    from core.indicators.indicators import calculate_pivot_points
    w = when.tz_localize(None) if getattr(when, "tzinfo", None) else when
    idx = d1.index
    cur = pd.Timestamp(w).to_period(period).start_time
    prev = (pd.Timestamp(cur) - pd.Timedelta(days=1)).to_period(period)
    sl = d1[(idx >= prev.start_time) & (idx < prev.end_time)]
    if len(sl) < 2:
        return None
    return calculate_pivot_points(float(sl.high.max()), float(sl.low.min()), float(sl.close.iloc[-1]))


def _exit_at(x, j, e, sl, tp, end_i):
    """Исход при фиксированной цели tp (стоп раньше цели на одном баре)."""
    hi, lo, cl = x.high.values, x.low.values, x.close.values
    for k in range(j, end_i + 1):
        if lo[k] <= sl:
            return sl, "stop"
        if hi[k] >= tp:
            return tp, "target"
    return float(cl[end_i]), "time"


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
        dh = load_tf(sym, TF); dl = load_tf(sym, LTF); d1 = load_tf(sym, "1d")
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
                continue
            seen.add(s["key"])
            t5 = pd.Timestamp(s["top_time"])
            if t5.tzinfo is not None:
                t5 = t5.tz_convert("UTC").tz_localize(None)
            i0 = int(np.searchsorted(dl_idx, np.datetime64(t5 - pd.Timedelta(minutes=4 * tfm)), "left"))
            i1 = int(np.searchsorted(dl_idx, np.datetime64(t5 + pd.Timedelta(hours=entry_h + hold_h)), "right"))
            w = dl.iloc[i0:i1]
            if len(w) < 200:
                continue
            nw = now.tz_localize(None) if getattr(now, "tzinfo", None) is not None else now
            ls = ltf_status(s, w, P, after=nw, entry_w_h=entry_h, hold_h=hold_h, cost_pct=COST)
            if ls.get("entry_price") is None:
                continue
            x = w.reset_index(drop=True); lt = w.index.values
            e = float(ls["entry_price"]); sl = float(ls["stop"]); tp = float(s["p4_target"])
            if tp <= e or sl >= e:
                continue
            j = int(np.searchsorted(lt, np.datetime64(pd.Timestamp(ls["entry_time"]))))
            end_i = min(len(x) - 1, int(np.searchsorted(lt, np.datetime64(pd.Timestamp(ls["entry_time"]) + pd.Timedelta(hours=hold_h)))))
            hi, lo = x.high.values, x.low.values
            rec = {"sym": sym, "key": s["key"], "top_time": t5, "entry": e, "stop": sl, "target": tp,
                   "core_full": s["core_full"], "imp_pct": s["imp_pct"], "depth5": s["depth5"],
                   "risk_pct": (e - sl) / e * 100, "tgt_pct": (tp - e) / e * 100,
                   "pnl_w4": ls["pnl_pct"], "outcome_w4": ls["outcome"]}
            # потенциал: максимум ПОСЛЕ взятия цели
            if ls["outcome"] == "target":
                k_tp = next((k for k in range(j, end_i + 1) if hi[k] >= tp), None)
                if k_tp is not None:
                    peak = float(hi[k_tp:end_i + 1].max())
                    rec["peak_after_tp_pct"] = (peak - e) / e * 100
            for nm, th in (("trail24", 24), ("trail72", 72), ("trail168", 168)):
                px, oc = _trail(x, j, e, sl, th, end_i)
                rec[f"pnl_{nm}"] = round((px - e) / e * 100 - COST, 2); rec[f"out_{nm}"] = oc
            px, oc = _cascade(x, j, e, sl, end_i)
            rec["pnl_cascade"] = round((px - e) / e * 100 - COST, 2); rec["out_cascade"] = oc
            # цели по ПИВОТАМ: недельные и месячные, уровни R2..R5 (ниже R2 цели почти всегда
            # оказываются за спиной — вход и так после импульса)
            for per, tag in (("W", "нед"), ("M", "мес")):
                pv = _pivots(d1, pd.Timestamp(ls["entry_time"]), per)
                if not pv:
                    continue
                for lvl in ("R2", "R3", "R4", "R5"):
                    tpp = float(pv[lvl])
                    if tpp <= e:
                        continue                      # уровень уже пройден — не цель
                    pxp, ocp = _exit_at(x, j, e, sl, tpp, end_i)
                    rec[f"pnl_{tag}{lvl}"] = round((pxp - e) / e * 100 - COST, 2)
                    rec[f"out_{tag}{lvl}"] = ocp
                    rec[f"dist_{tag}{lvl}"] = round((tpp - e) / e * 100, 2)
            # ЧАСТИЧНАЯ ФИКСАЦИЯ НА ПИВОТЕ + БЕЗУБЫТОК (идея Егора 17.09): доходим до ближайшего
            # уровня выше входа, снимаем половину, остаток ведём со стопом в БУ — до цели w4.
            pv_w = _pivots(d1, pd.Timestamp(ls["entry_time"]), "W")
            if pv_w:
                above = sorted([float(v) for k_, v in pv_w.items() if float(v) > e])
                if above:
                    p1 = above[0]
                    rec["dist_пив1"] = round((p1 - e) / e * 100, 2)
                    k_p = next((k for k in range(j, end_i + 1) if hi[k] >= p1), None)
                    k_s = next((k for k in range(j, end_i + 1) if lo[k] <= sl), None)
                    if k_s is not None and (k_p is None or k_s < k_p):
                        rec["pnl_пив_бу"] = round((sl - e) / e * 100 - COST, 2)       # стоп раньше пивота
                    elif k_p is not None:
                        px_r, _ = _exit_at(x, k_p, e, e, tp, end_i)                   # остаток: стоп в БУ, цель w4
                        rec["pnl_пив_бу"] = round(0.5 * ((p1 - e) / e * 100) + 0.5 * ((px_r - e) / e * 100) - COST, 2)
                    else:
                        rec["pnl_пив_бу"] = rec["pnl_w4"]
                    pxn, ocn = _exit_at(x, j, e, sl, p1, end_i)                       # и просто ближайший пивот как цель
                    rec["pnl_пив1"] = round((pxn - e) / e * 100 - COST, 2); rec["out_пив1"] = ocn
            px, oc = _wave_trail(x, j, e, sl, end_i)
            rec["pnl_wave"] = round((px - e) / e * 100 - COST, 2); rec["out_wave"] = oc
            for mlt in (2.0, 3.0, 5.0):
                px, oc = _atr_trail(x, j, e, sl, end_i, mult=mlt)
                rec[f"pnl_atr{mlt:g}"] = round((px - e) / e * 100 - COST, 2); rec[f"out_atr{mlt:g}"] = oc
            # половина на цели, остаток трейлом 72 ч
            k_tp = next((k for k in range(j, end_i + 1) if hi[k] >= tp), None)
            k_sl = next((k for k in range(j, end_i + 1) if lo[k] <= sl), None)
            if k_sl is not None and (k_tp is None or k_sl < k_tp):
                rec["pnl_half72"] = round((sl - e) / e * 100 - COST, 2)
            elif k_tp is not None:
                px2, _ = _trail(x, k_tp, e, max(sl, e), 72, end_i)   # остаток: стоп уже в безубытке
                rec["pnl_half72"] = round(0.5 * ((tp - e) / e * 100) + 0.5 * ((px2 - e) / e * 100) - COST, 2)
                px3, _ = _cascade(x, k_tp, e, max(sl, e), end_i)     # остаток под КАСКАДОМ
                rec["pnl_half_casc"] = round(0.5 * ((tp - e) / e * 100) + 0.5 * ((px3 - e) / e * 100) - COST, 2)
            else:
                rec["pnl_half72"] = rec["pnl_w4"]
            rec.setdefault("pnl_half_casc", rec["pnl_half72"])
            rows.append(rec)
    pickle.dump(rows, open(out_p, "wb"))
    return sym, f"{len(rows)} сделок за {time.time() - t0:.0f}с"


def report():
    rows = [r for f in glob.glob(str(OUT / "*.pkl")) for r in pickle.load(open(f, "rb"))]
    d = pd.DataFrame(rows); d["год"] = pd.to_datetime(d.top_time).dt.year
    print(f"сделок {len(d)} · монет {d.sym.nunique()}\n")
    out = []
    for nm, col in (("цель w4 (как сейчас)", "pnl_w4"), ("трейл 24 ч", "pnl_trail24"),
                    ("трейл 72 ч", "pnl_trail72"), ("трейл 168 ч", "pnl_trail168"),
                    ("КАСКАД (15m→1h→4h по R)", "pnl_cascade"), ("половина на цели + КАСКАД", "pnl_half_casc"),
                    ("ВОЛНОВОЙ (стоп под свинги, выход по CHoCH)", "pnl_wave"),
                    ("ATR×2", "pnl_atr2"), ("ATR×3", "pnl_atr3"), ("ATR×5", "pnl_atr5"),
                    ("ближайший пивот как цель", "pnl_пив1"),
                    ("половина на ближайшем пивоте + БУ → w4", "pnl_пив_бу"),
                    ("пивот нед R2", "pnl_недR2"), ("пивот нед R3", "pnl_недR3"),
                    ("пивот нед R4", "pnl_недR4"), ("пивот нед R5", "pnl_недR5"),
                    ("пивот мес R2", "pnl_месR2"), ("пивот мес R3", "pnl_месR3"),
                    ("пивот мес R4", "pnl_месR4"), ("пивот мес R5", "pnl_месR5"),
                    ("половина на цели + трейл 72 ч", "pnl_half72")):
        v = d[col].dropna()
        frag = (v.sum() - v.nlargest(max(1, len(v) // 10)).sum()) / len(v)
        out.append({"выход": nm, "n": len(v), "ср%": round(v.mean(), 2), "мед%": round(v.median(), 2),
                    "WR%": round((v > 0).mean() * 100), "сумма": round(v.sum()), "безтоп10": round(frag, 2)})
    print(pd.DataFrame(out).to_string(index=False))
    t = d[d.outcome_w4 == "target"].dropna(subset=["peak_after_tp_pct"])
    if len(t):
        print(f"\nПОТЕНЦИАЛ ПОСЛЕ ЦЕЛИ (сделки, взявшие цель: {len(t)}):")
        print(f"  медиана цели {t.tgt_pct.median():.1f}% · медиана максимума после входа {t.peak_after_tp_pct.median():.1f}%")
        print(f"  доля хода, которую забирает цель: медиана {(t.tgt_pct / t.peak_after_tp_pct * 100).median():.0f}%")
        for thr in (30, 50, 100):
            print(f"  сделок, где ход после входа превысил {thr}%: {(t.peak_after_tp_pct > thr).sum()} "
                  f"({(t.peak_after_tp_pct > thr).mean() * 100:.0f}%)")
    print("\nпо годам (среднее %):")
    cols = [c for c in ("pnl_w4", "pnl_cascade", "pnl_trail72", "pnl_atr5", "pnl_пив1", "pnl_недR3") if c in d]
    print(d.groupby("год")[cols].mean().round(2).to_string())
    # 🔴 главный разрез: сезон иксов против рынка без него
    d["режим"] = np.where(d["год"] <= 2021, "2020-21 АЛЬТСЕЗОН", "2022-26 без сезона")
    print("\nСЕЗОН ПРОТИВ НЕ-СЕЗОНА (среднее % · WR · сделок):")
    for nm, col in (("цель w4", "pnl_w4"), ("каскад", "pnl_cascade"), ("трейл 72 ч", "pnl_trail72"),
                    ("ATR×5", "pnl_atr5"), ("ближайший пивот", "pnl_пив1"), ("нед R3", "pnl_недR3"),
                    ("нед R5", "pnl_недR5")):
        if col not in d:
            continue
        line = f"  {nm:18}"
        for rg, g in d.groupby("режим"):
            v = g[col].dropna()
            if len(v):
                line += f" │ {rg}: {v.mean():+5.2f}% WR {(v > 0).mean() * 100:3.0f}% n={len(v):5}"
        print(line)


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
