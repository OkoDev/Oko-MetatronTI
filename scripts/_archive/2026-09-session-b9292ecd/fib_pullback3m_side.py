"""Механика Егора (14.09, RECALL 3m): пятая → CHoCH 3m (волна A) → откат B в зону фибо 0.5–0.705 от A (ретест пробитого
уровня CHoCH) → ЛИМИТ-вход в зоне → CHoCH 15m потом лишь подтверждение. 3m = ресемпл 1m-паркетов (29 монет с базой, 2025-01+).
Каузально: A_top = максимум от пятой до бара k-1; лимит на A_top − f·A выставлен до бара k; филл = min(уровень, open).
Отмена: цена ниже пятой до филла или 72 ч от детекции 4h-пятёрки. Вход не раньше закрытия 4h-бара детекции.
Стопы: под пятую (−0.15%) · под 0.79 A · под 0.886 A.   Цели: A_top (ретест вершины A) · T1 = филл + A (C=A) · T1.618 · W4.
Выходы: X1 100% A_top · X2 100% T1 · X3 50% A_top + 50% T1 (стоп→вход после A_top) · X4 50% T1 + 50% T1.618 (стоп→вход после T1).
Контроль: 30 случайных входов в том же окне, тот же % стопа и те же % до целей. Косты 0.10%."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, ".")
sys.path.insert(0, r"E:\MTF BOT\CURSOR\crypto_volume_bot")
from wave5_sm import load, TF_MIN
from alternation import prep as prep_alt
from core.smc.oko_sm_engine import run_structure, _swings

COST, BUF, WIN_H, HOLD_H, NCTL = 0.10, 0.0015, 72, 240, 30
rng = np.random.default_rng(17)
# Егор 14.09: «вход на 3m, а цели — по большому движению» → фибо-коррекция всего 4h-импульса (p0→p5)
EXITS = {"X3 микро: 50 вершина A + 50 C=A": [(.5, "Atop"), (.5, "T1")],
         "Y1 100% 0.382 4h": [(1.0, "C382")], "Y2 100% 0.5 4h": [(1.0, "C500")],
         "Y3 50 0.382 + 50 0.618": [(.5, "C382"), (.5, "C618")], "Y4 ⅓ 0.382·⅓ 0.5·⅓ 0.618": [(1/3, "C382"), (1/3, "C500"), (1/3, "C618")],
         "Y0 100% конец w4": [(1.0, "W4")],
         # этап 2: частичные выходы (стоп → вход после первой цели, → первая цель после второй)
         "Z1 ½ 0.382 + ½ w4 (БУ)": [(.5, "C382"), (.5, "W4")],
         "Z2 ⅓ 0.382·⅓ 0.618·⅓ w4": [(1/3, "C382"), (1/3, "C618"), (1/3, "W4")]}


def run_exit(h, l, c, k0, e, sl0, tg, legs, end):
    lv = sorted([(fr, tg[n]) for fr, n in legs], key=lambda x: x[1])      # цели по порядку цены
    if any(p <= e for _, p in lv):
        return None
    sl, taken, pnl = sl0, 0, 0.0
    for k in range(k0, end + 1):
        if l[k] <= sl:
            return pnl + sum(fr for fr, _ in lv[taken:]) * (sl - e) / abs(e) * 100 - COST
        while taken < len(lv) and h[k] >= lv[taken][1]:
            pnl += lv[taken][0] * (lv[taken][1] - e) / abs(e) * 100; taken += 1
            if len(lv) > 1:
                sl = e if taken == 1 else lv[taken - 2][1]
        if taken == len(lv):
            return pnl - COST
    return pnl + sum(fr for fr, _ in lv[taken:]) * (c[end] - e) / abs(e) * 100 - COST


SIDE = os.environ.get("SIDE", "down")          # down = пятёрка вниз → лонг; up = пятёрка вверх → шорт (зеркало знаком)
d = prep_alt("wave5sm_4h_15m_sw15_il4_hold240_ctx10_z45.pkl", side=SIDE)
d["alt_form"] = (d.ns2 - d.ns4).abs() >= 2
d["altern"] = d.alt_sharp_flat | d.alt_form
d["count_ok"] = ~(d.alt_exists.astype(bool) & (d.alt_w3_w1 >= 1.0) & (d.alt_w3_w1 > d.w3_ext))
d["fc"] = d.fractal_ok & (d.depth5 >= 0.5)
d["full"] = d.fc & d.altern & d.count_ok
htf = d.htf.iloc[0]
def neg(df):
    """Зеркало знаком: пятёрка вверх становится пятёркой вниз, фибо линейны, проценты — по модулю цены."""
    o = pd.DataFrame(index=df.index)
    o['open'], o['close'], o['high'], o['low'] = -df.open, -df.close, -df.low, -df.high
    if 'volume' in df: o['volume'] = df.volume
    return o


rows = []
ONLY = [x for x in os.environ.get("SYMS", "").split(",") if x]
for sym, g in d.groupby("sym"):
    if ONLY and sym not in ONLY:
        continue
    d3 = load(sym, "3m")
    if d3.empty:
        continue
    if SIDE == "up":
        d3 = neg(d3)
    dh = load(sym, htf)
    if SIDE == "up":
        dh = neg(dh)
    ih = dh.index.values.astype("datetime64[ns]")
    DD = {sym: dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()}
    DSW = {sym: {k_: _swings(DD[sym]["high"], DD[sym]["low"], k_) for k_ in (10, 5)}}
    h, l, c, o = (d3[k].values.astype(float) for k in ("high", "low", "close", "open")); t = d3.index.values.astype("datetime64[ns]")
    for _, r in g.iterrows():
        if SIDE == "up":
            r = r.copy(); r["p0"], r["p4"], r["p5"] = -r.p0, -r.p4, -r.p5; r["wave_px"] = [-float(x) for x in r.wave_px]
        t5 = ih[int(r.b)]; a5 = int(np.searchsorted(t, t5)); b5 = int(np.searchsorted(t, t5 + np.timedelta64(TF_MIN[htf], "m")))
        j0 = int(np.searchsorted(t, ih[int(r.t)] + np.timedelta64(TF_MIN[htf], "m"))); jw = j0 + WIN_H * 20
        if b5 <= a5 or a5 < 2000 or jw + HOLD_H * 20 >= len(t) or t[a5] - t5 > np.timedelta64(1, "h"):
            continue
        i5 = a5 + int(l[a5:b5].argmin()); p5 = float(l[i5])
        # точка 0 → экстремум ноги (правило аналитика 14.09) и глубина пятой в дневной ноге (свинги 10 и 5 дней)
        hh4, lh4 = dh.high.values.astype(float), dh.low.values.astype(float)
        wi = [int(x) for x in r.wave_idx]; p1 = float(r.wave_px[1])
        bz = np.where(lh4[:wi[0]] < p1)[0]; kb = int(bz[-1]) + 1 if len(bz) else max(0, wi[0] - 60)
        P0 = max(float(r.p0), float(hh4[kb:wi[1]].max()))
        R5 = P0 - float(r.p5)
        depth = np.nan
        dd_ = DD[sym]
        for dsw_len in (10, 5):
            sws = [x for x in DSW[sym][dsw_len] if (not x[3]) and dd_.index[int(x[1])] < dh.index[wi[0]] and dd_.index[int(x[0])] + pd.Timedelta(days=1) <= dh.index[int(r.t)] + pd.Timedelta(hours=4) and float(x[2]) < float(r.p5)]
            if not sws:
                continue
            o_i = int(sws[-1][1]); L = float(sws[-1][2]); seg_ = dd_.iloc[o_i:]; seg_ = seg_[seg_.index <= dh.index[int(r.b)] + pd.Timedelta(hours=4)]
            H = float(seg_.high.max())
            if H > L:
                dp = (H - float(r.p5)) / (H - L)
                if np.isnan(depth) or (0.62 <= dp <= 1.0 and not (0.62 <= depth <= 1.0)):
                    depth = dp
        st = run_structure(d3.iloc[i5 - 1500:jw + 1][["open", "high", "low", "close"]].reset_index(drop=True), swing_len=50, internal_len=5)
        ich = [x.i + i5 - 1500 for x in st.events if x.internal and x.bull and x.kind == "CHoCH" and x.i + i5 - 1500 > i5]
        kc = ich[0] if ich else None
        base = dict(sym=sym, ts=r.ts, year=r.year, fc=bool(r.fc), full=bool(r.full), day=str(pd.Timestamp(r.ts).date()), depth=depth)
        if kc is not None and j0 <= kc < jw and kc + 1 < len(t):
            k = kc + 1; e = float(o[k]); slp = p5 - abs(p5) * BUF; end = min(len(t) - 1, k + HOLD_H * 20)
            tg = {"Atop": e * 10, "T1": e * 10, "T1618": e * 10, "W4": float(r.p4), "C382": float(r.p5) + .382 * R5, "C500": float(r.p5) + .5 * R5, "C618": float(r.p5) + .618 * R5}
            if slp < e:
                risk = (e - slp) / abs(e) * 100; dist = {n: pp / e - 1 for n, pp in tg.items()}
                rec = {**base, "v": "PEAK: вход на CHoCH 3m · стоп под пятую", "risk": risk, "h5": (t[k] - t[i5]) / np.timedelta64(1, "h"), "A%": np.nan, "rr382": (tg["C382"] - e) / (e - slp)}
                for xn, legs in EXITS.items():
                    if xn.startswith("X3"):
                        rec[xn] = None; rec["ctl " + xn] = np.nan; continue
                    rec[xn] = (slp - e) / abs(e) * 100 - COST if l[k] <= slp else run_exit(h, l, c, k + 1, e, slp, tg, legs, end)
                    cp = []
                    for kr in rng.integers(j0, jw, NCTL):
                        er = float(o[kr])
                        if l[kr] <= er - abs(er) * risk / 100:
                            cp.append(-risk - COST); continue
                        pr = run_exit(h, l, c, kr + 1, er, er - abs(er) * risk / 100, {n: er * (1 + dd) for n, dd in dist.items()}, legs, min(len(t) - 1, kr + HOLD_H * 20))
                        if pr is not None: cp.append(pr)
                    rec["ctl " + xn] = np.mean(cp) if cp else np.nan
                rows.append(rec)
        for need_choch in (True, False):
            if need_choch and kc is None:
                continue
            k_start = max(j0, (kc + 1) if need_choch else i5 + 1)
            for N in (20,):                                  # подтверждение вершины A: N баров 3m без обновления (30 мин / 1 ч / 2 ч)
                for f in (0.5, 0.618):
                    fill = None; atop = None; ia = None; run_max = float(h[i5]); im = i5
                    for k in range(i5 + 1, jw):
                        if l[k] < p5:
                            break                                   # новый минимум — сценарий отменён
                        if atop is not None and k >= k_start:
                            A = atop - p5; lvl = atop - f * A
                            if l[k] <= lvl:
                                if o[k] < atop - 0.886 * A:          # гэп сквозь зону — не входим
                                    break
                                fill = (k, min(lvl, o[k]), atop, A, ia); break
                        if h[k] > run_max:
                            run_max, im = float(h[k]), k
                            if atop is not None and h[k] > atop:
                                atop = None                         # вершина A обновлена — ждём новое подтверждение
                        if atop is None and k - im >= N and (not need_choch or im > kc) and run_max > p5 + abs(p5) * 0.003:
                            # вершина подтверждена на баре k; лимит — со следующего, если цена ещё не в зоне
                            if float(l[im + 1:k + 1].min()) > run_max - f * (run_max - p5):
                                atop, ia = run_max, im
                            else:
                                break
                    if fill is None:
                        continue
                    k, e, atop, A, ia = fill
                    end = min(len(t) - 1, k + HOLD_H * 20)
                    for sname, slp in (("под пятую", p5 - abs(p5) * BUF), ("под 0.886", atop - 0.886 * A)):
                        if slp >= e:
                            continue
                        risk = (e - slp) / abs(e) * 100
                        tg = {"Atop": atop, "T1": e + A, "T1618": e + 1.618 * A, "W4": float(r.p4), "C382": float(r.p5) + .382 * R5, "C500": float(r.p5) + .5 * R5, "C618": float(r.p5) + .618 * R5}
                        dist = {n: p / e - 1 for n, p in tg.items()}
                        rec = {**base, "v": f"{'CHoCH3m' if need_choch else 'без CHoCH'} · верш.N{N} · фибо {f} · стоп {sname}", "risk": risk,
                               "h5": (t[k] - t[i5]) / np.timedelta64(1, "h"), "A%": A / abs(p5) * 100, "rr382": (tg["C382"] - e) / (e - slp)}
                        for xn, legs in EXITS.items():
                            rec[xn] = (slp - e) / abs(e) * 100 - COST if l[k] <= slp else run_exit(h, l, c, k + 1, e, slp, tg, legs, end)
                            cp = []
                            for kr in rng.integers(max(j0, i5 + 1), jw, NCTL):
                                er = float(o[kr])
                                if l[kr] <= er - abs(er) * risk / 100:
                                    cp.append(-risk - COST); continue
                                pr = run_exit(h, l, c, kr + 1, er, er - abs(er) * risk / 100, {n: er * (1 + dd) for n, dd in dist.items()}, legs,
                                              min(len(t) - 1, kr + HOLD_H * 20))
                                if pr is not None:
                                    cp.append(pr)
                            rec["ctl " + xn] = np.mean(cp) if cp else np.nan
                        rows.append(rec)
f = pd.DataFrame(rows); f.to_pickle(os.environ.get("OUT", "fib3m_full.pkl")); print("строк", len(f), "сетапов", f[["sym","ts"]].drop_duplicates().shape[0], flush=True)
