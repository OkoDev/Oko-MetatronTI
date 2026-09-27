"""3m-механика Егора, v2 — перемер после ревью look-ahead (bot-arch, 14.09). Исправлено:
 (1) филл лимитки проверяется РАНЬШЕ отмены; бар, прошедший сквозь уровень и ниже пятой, = сделка со стопом
 (2) контроль по ВСЕМ сетапам через тот же автомат (вход только пока пятая не пробита) + второй контроль с
     совпадением по времени на других монетах (15m) — закон «считать оба»
 (3) пятая = провизорная на баре детекции (low 4h-бара b), а не p5e из pkl (у 27% сетапов — будущий минимум);
     цели, глубина канала, отбор ядра (fc) пересчитаны от неё
 (4) филл только при проходе сквозь уровень (≥1 bp) или гэпом по open; тип филла пишется
 (5) глубина в дневной ноге — оба масштаба свинга (10 и 5 дней) РАЗДЕЛЬНО, без выбора «попавшего»
 (6) дневные бары — только закрытые к моменту детекции; максимум ноги — по 4h до бара детекции
 (7) окна в часах; стоп < 0.35% (A ≈ косты) отбрасывается и считается отдельно; CI — бутстрап по дням
SIDE=down (пятёрка вниз → лонг) / up (зеркало знаком → шорт). SYMS=… для отладки, OUT=… pickle."""
import contextlib, io, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
with contextlib.redirect_stdout(io.StringIO()):
    from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure, _swings

SIDE = os.environ.get("SIDE", "down")
COST, BUF, WIN_H, HOLD_H, NCTL, PASS, MIN_RISK = 0.10, 0.0015, 72, 240, 30, 1e-4, 0.35
rng = np.random.default_rng(29)
EXITS = {"X3": [(.5, "Atop"), (.5, "T1")], "Y1": [(1.0, "C382")], "Y0": [(1.0, "W4")], "Z1": [(.5, "C382"), (.5, "W4")]}


def neg(df):
    o = pd.DataFrame(index=df.index)
    o["open"], o["close"], o["high"], o["low"] = -df.open, -df.close, -df.low, -df.high
    return o


def first(mask):
    if mask.size == 0:
        return 10 ** 9
    i = int(np.argmax(mask))
    return i if mask[i] else 10 ** 9


def run_exit(h, l, c, k0, e, sl, tg, legs, end):
    """Векторно. Цели по возрастанию цены; стоп раньше цели на одном баре; после взятой цели стоп → вход (→ предыдущая цель)
    со СЛЕДУЮЩЕГО бара. Возврат: % с костами или None, если цель не выше входа."""
    lv = sorted([(fr, tg[n]) for fr, n in legs], key=lambda x: x[1])
    if any(p <= e for _, p in lv) or k0 > end:
        return None
    ae = abs(e); pnl = 0.0; rem = 1.0; ps = pt = k0; stop = sl
    for i, (fr, tp) in enumerate(lv):
        js = first(l[ps:end + 1] <= stop); js = ps + js if js < 10 ** 9 else 10 ** 9
        jt = first(h[pt:end + 1] >= tp); jt = pt + jt if jt < 10 ** 9 else 10 ** 9
        if js <= jt and js < 10 ** 9:
            return pnl + rem * (stop - e) / ae * 100 - COST
        if jt >= 10 ** 9:
            return pnl + rem * (c[end] - e) / ae * 100 - COST
        pnl += fr * (tp - e) / ae * 100; rem -= fr
        stop = e if i == 0 else lv[i - 1][1]; pt = jt; ps = jt + 1
    return pnl - COST


with contextlib.redirect_stdout(io.StringIO()):
    d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", side=SIDE)
htf = d.htf.iloc[0]
ONLY = [x for x in os.environ.get("SYMS", "").split(",") if x]
syms_all = sorted(d.sym.unique())
POOL = [x for x in pd.Series(syms_all).sample(20, random_state=5)]      # пул для контроля по времени (грузится один раз)
C15 = {}                                                        # кэш 15m для контроля по времени


def ctl15(sym):
    if sym not in C15:
        x = load(sym, "15m")
        if SIDE == "up":
            x = neg(x)
        C15[sym] = (x.index.values.astype("datetime64[ns]"), x.high.values.astype(float), x.low.values.astype(float),
                    x.close.values.astype(float), x.open.values.astype(float)) if len(x) else None
    return C15[sym]


rows = []; skipped = {"мало 3m": 0, "нет A/отмена": 0, "стоп<0.35%": 0}
for sym, g in d.groupby("sym"):
    if ONLY and sym not in ONLY:
        continue
    d3 = load(sym, "3m")
    if d3.empty:
        continue
    dh = load(sym, htf)
    if SIDE == "up":
        d3, dh = neg(d3), neg(dh)
    h, l, c, o = (d3[k].values.astype(float) for k in ("high", "low", "close", "open")); t3 = d3.index.values.astype("datetime64[ns]")
    hh4, lh4 = dh.high.values.astype(float), dh.low.values.astype(float); i4 = dh.index
    dd_all = dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    for _, r in g.iterrows():
        wi = [int(x) for x in r.wave_idx]; b, t = int(r.b), int(r.t)
        px = [float(x) for x in r.wave_px[:5]]
        if SIDE == "up":
            px = [-x for x in px]
        p5t = float(lh4[b])                                     # провизорная пятая на баре детекции
        tdet = i4[t] + pd.Timedelta(hours=4)
        a5 = int(np.searchsorted(t3, i4[b].to_datetime64())); b5 = int(np.searchsorted(t3, (i4[b] + pd.Timedelta(hours=4)).to_datetime64()))
        j0 = int(np.searchsorted(t3, tdet.to_datetime64())); jw = int(np.searchsorted(t3, (tdet + pd.Timedelta(hours=WIN_H)).to_datetime64()))
        if b5 <= a5 or a5 < 2000 or jw >= len(t3) - 10:
            skipped["мало 3m"] += 1; continue
        i5 = a5 + int(l[a5:b5].argmin()); p5 = float(l[i5])
        # канал и отбор ядра от провизорной пятой
        xi = wi[:5] + [b]; pp = px + [p5t]
        slope = (pp[4] - pp[2]) / (xi[4] - xi[2]) if xi[4] > xi[2] else 0.0
        width = -(pp[3] - (pp[2] + slope * (xi[3] - xi[2]))); depth5 = -(pp[5] - (pp[4] + slope * (xi[5] - xi[4])))
        depth5 = depth5 / width if width > 0 else np.nan
        fc = bool(r.fractal_ok) and np.isfinite(depth5) and depth5 >= 0.5
        # точка 0 → экстремум ноги (только бары до точки 1)
        bz = np.where(lh4[:wi[0]] < px[1])[0]; kb = int(bz[-1]) + 1 if len(bz) else max(0, wi[0] - 60)
        P0 = max(px[0], float(hh4[kb:wi[1]].max())); R5 = P0 - p5t
        # глубина в дневной ноге: только дни, закрытые к детекции; оба масштаба раздельно
        dd = dd_all[dd_all.index + pd.Timedelta(days=1) <= tdet]
        dep = {}
        for L_ in (10, 5):
            sws = [x for x in _swings(dd["high"], dd["low"], L_) if (not x[3]) and dd.index[int(x[1])] < i4[wi[0]] and float(x[2]) < p5t]
            if not sws:
                dep[L_] = np.nan; continue
            ko = int(np.searchsorted(i4.values, dd.index[int(sws[-1][1])].to_datetime64()))
            H = float(hh4[ko:t + 1].max()); L = float(sws[-1][2])
            dep[L_] = (H - p5t) / (H - L) if H > L else np.nan
        tg0 = {"W4": px[4], "C382": p5t + .382 * R5, "C500": p5t + .5 * R5, "C618": p5t + .618 * R5}
        st = run_structure(d3.iloc[i5 - 1500:jw + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=50, internal_len=5)
        ich = [x.i + i5 - 1500 for x in st.events if x.internal and x.bull and x.kind == "CHoCH" and x.i + i5 - 1500 > i5]
        kc = ich[0] if ich else None
        base = dict(sym=sym, ts=str(r.ts), year=int(r.year), day=str(tdet.date()), fc=fc, depth5=depth5, dep10=dep[10], dep5=dep[5],
                    d_bull=r.d_bull, p5_leak=bool(abs(float(r.p5) - (-p5t if SIDE == "up" else p5t)) > 1e-12))
        # контроль по всем сетапам: случайный момент в окне, пока пятая не пробита (тот же автомат отмен)
        kr_all = rng.integers(j0, jw, NCTL)
        minlow = np.minimum.accumulate(l[i5:jw + 1])

        def ctl_eval(risk, tg_rel, legs):
            out = []
            for kr in kr_all:
                if kr - i5 - 1 >= 0 and minlow[kr - i5 - 1] < p5:     # сценарий отменён до входа (бар входа сам не в счёт)
                    continue
                er = float(o[kr]); slr = er - abs(er) * risk / 100
                end_r = int(np.searchsorted(t3, t3[kr] + np.timedelta64(HOLD_H, "h")))
                if l[kr] <= slr:
                    out.append(-risk - COST); continue
                v = run_exit(h, l, c, kr + 1, er, slr, {n: er + abs(er) * dd_ for n, dd_ in tg_rel.items()}, legs, min(len(t3) - 1, end_r))
                if v is not None:
                    out.append(v)
            return np.mean(out) if out else np.nan

        def ctl_time(sym_self, t_entry, risk, tg_rel, legs, n=10):
            out = []
            for s2 in rng.choice([s for s in POOL if s != sym_self], n, replace=False):
                x = ctl15(s2)
                if x is None:
                    continue
                tt, hh, ll, cc, oo = x; k = int(np.searchsorted(tt, t_entry))
                if k >= len(tt) - 5 or tt[k] - t_entry > np.timedelta64(1, "h"):
                    continue
                er = float(oo[k]); slr = er - abs(er) * risk / 100
                if ll[k] <= slr:
                    out.append(-risk - COST); continue
                v = run_exit(hh, ll, cc, k + 1, er, slr, {nn: er + abs(er) * dd_ for nn, dd_ in tg_rel.items()}, legs,
                             min(len(tt) - 1, int(np.searchsorted(tt, t_entry + np.timedelta64(HOLD_H, "h")))))
                if v is not None:
                    out.append(v)
            return np.mean(out) if out else np.nan

        # контроль ПО ВСЕМ сетапам (не зная, будет ли филл): случайный вход в окне, пока пятая не пробита,
        # стоп на сетке 1/2/3%, цели — АБСОЛЮТНЫЕ уровни, известные на детекции (W4, C382)
        srow = {**base, "v": "__setup__"}
        for rk in (1.0, 2.0, 3.0):
            for xn in ("Y1", "Y0", "Z1"):
                out = []
                for kr in kr_all:
                    if kr - i5 - 1 >= 0 and minlow[kr - i5 - 1] < p5:
                        continue
                    er = float(o[kr]); slr = er - abs(er) * rk / 100
                    if l[kr] <= slr:
                        out.append(-rk - COST); continue
                    v_ = run_exit(h, l, c, kr + 1, er, slr, tg0, EXITS[xn], min(len(t3) - 1, int(np.searchsorted(t3, t3[kr] + np.timedelta64(HOLD_H, "h")))))
                    if v_ is not None:
                        out.append(v_)
                srow[f"ca{int(rk)}_{xn}"] = np.mean(out) if out else np.nan
        rows.append(srow)
        variants = [("PEAK", None, None, None)] + [(("CH" if nc else "noCH"), nc, f, sn) for nc in (True, False) for f in (0.5, 0.618) for sn in ("0.886", "p5")]
        for tag, need_choch, f, sname in variants:
            name = "PEAK · вход на CHoCH 3m · стоп под пятую" if tag == "PEAK" else f"{tag} · откат {f} · стоп {sname}"
            fill = None
            if tag == "PEAK":
                if kc is not None and j0 <= kc < jw - 1:
                    fill = (kc + 1, float(o[kc + 1]), None, None, "open")
            else:
                if need_choch and kc is None:
                    skipped["нет A/отмена"] += 1; continue
                atop = None; run_max = float(h[i5]); im = i5; k_start = max(j0, (kc + 1) if need_choch else i5 + 1)
                for k in range(i5 + 1, jw):
                    if atop is not None and k >= k_start:              # (1) филл раньше отмены
                        A = atop - p5; lvl = atop - f * A
                        if o[k] <= lvl:
                            fill = (k, float(o[k]), atop, A, "гэп/open"); break
                        if l[k] < lvl - abs(lvl) * PASS:
                            fill = (k, lvl, atop, A, "проход"); break
                    if l[k] < p5:                                        # пятая пробита до филла — сценарий отменён
                        break
                    if h[k] > run_max:
                        run_max, im = float(h[k]), k
                        if atop is not None and h[k] > atop:
                            atop = None
                    if atop is None and (t3[k] - t3[im]) >= np.timedelta64(60, "m") and (not need_choch or im > kc) and run_max - p5 >= abs(p5) * 0.003:
                        atop = run_max                                   # ордер выставлен на закрытии k, работает с k+1
            if fill is None:
                if tag != "PEAK":
                    skipped["нет A/отмена"] += 1
                continue
            k, e, atop, A, ftype = fill
            sl = p5 - abs(p5) * BUF if (tag == "PEAK" or sname == "p5") else atop - 0.886 * A
            if sl >= e:
                continue
            risk = (e - sl) / abs(e) * 100
            if risk < MIN_RISK:
                skipped["стоп<0.35%"] += 1; continue
            tg = dict(tg0); tg["Atop"] = atop if atop is not None else e * 1e6; tg["T1"] = e + A if A is not None else e * 1e6
            tg_rel = {n: (v - e) / abs(e) for n, v in tg.items()}
            end = min(len(t3) - 1, int(np.searchsorted(t3, t3[k] + np.timedelta64(HOLD_H, "h"))))
            rec = {**base, "v": name, "risk": risk, "fill": ftype, "h5": float((t3[k] - t3[i5]) / np.timedelta64(1, "h"))}
            for xn, legs in EXITS.items():
                if tag == "PEAK" and xn == "X3":
                    continue
                rec[xn] = (sl - e) / abs(e) * 100 - COST if l[k] <= sl else run_exit(h, l, c, k + 1, e, sl, tg, legs, end)
                if rec[xn] is None:
                    continue
                rec["ctl " + xn] = ctl_eval(risk, tg_rel, legs)
                if xn in ("Y0", "Z1"):
                    rec["ctlT " + xn] = ctl_time(sym, t3[k], risk, tg_rel, legs)
            rows.append(rec)
    print(f"{sym} готово · строк {len(rows)}", flush=True)
f = pd.DataFrame(rows); f.to_pickle(os.environ.get("OUT", f"fib3m_v2_{SIDE}.pkl"))
print("пропуски:", skipped, "· строк", len(f), "· сетапов", f[["sym", "ts"]].drop_duplicates().shape[0], flush=True)
