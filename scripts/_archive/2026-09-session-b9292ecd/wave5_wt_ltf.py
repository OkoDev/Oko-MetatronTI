# -*- coding: utf-8 -*-
"""ВЛОЖЕННЫЙ ВХОД (12.09.2026, Егор: «а входы по кроссам на LTF не проверил совсем?»).

Весь день кросс искался на ТОМ ЖЕ ТФ, где размечен импульс. На 4h это значит ждать кросс
4h-баров → опоздание 16 баров ≈ трое суток после вершины w5. Схема Егора всегда была MTF:
«кросс на часовике, а входы берутся на 15m и ниже».

ЗДЕСЬ: импульс, зона и дивергенция — на HTF (4h, где перевес значим). ВХОД — первый кросс
wt1×wt2 против импульса на LTF (1h / 15m), начиная с LTF-бара не раньше времени ПОДТВЕРЖДЕНИЯ
импульса на HTF (t) и не позже b + ENTRY_W HTF-баров. Стоп за экстремум w5, цели от HTF-импульса,
выходы по времени 7/14 сут. Контроль — случайный LTF-бар той же геометрии.

Причинность: HTF-импульс — префиксно; зона/дивергенция HTF — на барах ≤ t; кросс LTF — на барах
с временем ≥ времени t (закрытого HTF-бара); вход по open следующего LTF-бара.

Запуск: python wave5_wt_ltf.py --htf 4h --ltf 1h [--pairs 60] [--z 45] [--cost 0.10]
"""
from __future__ import annotations
import argparse, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

from research_harness import load, universe                        # noqa: E402
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse, append_provisional_leg   # noqa: E402

PROVISIONAL = False   # Егор 13.09: «мы это уже решили — provisional нога»: точка 5 = текущий
                      # экстремум ДО подтверждения зигзагом (smc_engine.append_provisional_leg,
                      # «то, что трейдер рисует глазом», проверено на XLM 1h). Снимает лаг 6 HTF-баров.
from core.indicators.indicators import calculate_wt                # noqa: E402
from core.calculators.combinator_core import _wtx_divergences      # noqa: E402

WARMUP, STEP = 600, 6
BUF = 0.0015
DIV_W = 12
ENTRY_W_HTF = 24        # окно ожидания кросса, в HTF-барах после вершины w5
MAXHOLD_HTF = 240
MIN_IMP_PCT, MAX_IMP_PCT = 3.0, 40.0
TGTS = ["w4", "f382", "f500", "f618"]
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


def wt_pack(df):
    d = calculate_wt(df.copy())
    wt1, wt2 = d["wt1"].values.astype(float), d["wt2"].values.astype(float)
    b_reg, s_reg, b_hid, s_hid = _wtx_divergences(
        wt1, df.low.values.astype(float), df.high.values.astype(float))
    up = np.zeros(len(wt1), bool); dn = np.zeros(len(wt1), bool)
    up[1:] = (wt1[1:] > wt2[1:]) & (wt1[:-1] <= wt2[:-1])
    dn[1:] = (wt1[1:] < wt2[1:]) & (wt1[:-1] >= wt2[:-1])
    return wt1, up, dn, b_reg, s_reg, b_hid, s_hid


ENTRY_MODE = "cross"   # cross | sc | engulf | pinbar — способ входа на LTF (Егор 13.09: свечные развороты)


def entry_signals(dl, mode):
    """Сигналы входа на LTF, все КАУЗАЛЬНЫ — считаются на закрытии свечи i, вход по open[i+1].
    → (sig_up, sig_dn): sig_up = вход в ЛОНГ (против импульса ВНИЗ), sig_dn = вход в ШОРТ."""
    o, h, l, c = (dl.open.values.astype(float), dl.high.values.astype(float),
                  dl.low.values.astype(float), dl.close.values.astype(float))
    n = len(c)
    up = np.zeros(n, bool); dn = np.zeros(n, bool)
    if mode == "cross":
        _, cup, cdn, _, _, _, _ = wt_pack(dl)
        return cup, cdn
    if mode == "any":
        # 🔑 Егор 13.09: «на любом ТФ у вершины найдётся подтверждение разворота, то или иное» —
        # берём ПЕРВОЕ из всех. Это не фильтр качества (он на HTF), а способ НЕ ОПОЗДАТЬ.
        for m in ("cross", "sc", "engulf", "pinbar"):
            u, d_ = entry_signals(dl, m)
            up |= u; dn |= d_
        return up, dn
    if mode == "sc":
        from core.smc.smc_engine import detect_sponsored_candle
        for s in detect_sponsored_candle(dl):          # кандидаты = свип + разворот; confirmed НЕ ждём
            if 0 <= s.idx < n:
                (up if s.direction == "bull" else dn)[s.idx] = True
        return up, dn
    body = np.abs(c - o); rng_ = np.maximum(h - l, 1e-12)
    if mode == "engulf":
        # бычье поглощение: пред. свеча медвежья, текущая бычья, её ТЕЛО накрывает тело предыдущей
        pb = c[:-1] < o[:-1]; cb = c[1:] > o[1:]
        up[1:] = pb & cb & (o[1:] <= c[:-1]) & (c[1:] >= o[:-1]) & (body[1:] > body[:-1])
        pb2 = c[:-1] > o[:-1]; cb2 = c[1:] < o[1:]
        dn[1:] = pb2 & cb2 & (o[1:] >= c[:-1]) & (c[1:] <= o[:-1]) & (body[1:] > body[:-1])
        return up, dn
    if mode == "pinbar":
        low_w = np.minimum(o, c) - l; up_w = h - np.maximum(o, c)
        # молот: нижний фитиль ≥ 2 тел, верхний ≤ тело, закрытие в верхней трети диапазона
        up[:] = (low_w >= 2 * body) & (up_w <= body) & ((c - l) / rng_ >= 0.66) & (body > 0)
        # повешенный/падающая звезда: зеркально
        dn[:] = (up_w >= 2 * body) & (low_w <= body) & ((h - c) / rng_ >= 0.66) & (body > 0)
        return up, dn
    raise ValueError(mode)


def walk(h, l, c, j_entry, e, sl, up_imp, tgt, end):
    """Проход по LTF-барам от j_entry до end: стоп первым, потом цели."""
    sgn = -1 if up_imp else 1
    res, hit, pend, stop_i = {}, {}, set(tgt), None
    for k in range(j_entry, end + 1):
        if (h[k] >= sl) if up_imp else (l[k] <= sl):
            stop_i = k; break
        for kk in list(pend):
            px = tgt[kk]
            if (l[k] <= px) if up_imp else (h[k] >= px):
                res[kk] = (px - e) / e * 100 * sgn; hit[kk] = k; pend.discard(kk)
        if not pend:
            break
    sl_pnl = (sl - e) / e * 100 * sgn
    tail = (float(c[stop_i if stop_i is not None else end]) - e) / e * 100 * sgn
    return res, hit, stop_i, sl_pnl, tail


def hold_pnl(h, l, c, j_entry, e, sl, up_imp, end):
    sgn = -1 if up_imp else 1
    for k in range(j_entry, end + 1):
        if (h[k] >= sl) if up_imp else (l[k] <= sl):
            return (sl - e) / e * 100 * sgn, True
    return (float(c[end]) - e) / e * 100 * sgn, False


def run_symbol(sym, htf, ltf, z, cost, rs):
    dh = load(sym, htf); dl = load(sym, ltf)
    if len(dh) < 1500 or len(dl) < 3000:
        return []
    ratio = TF_MIN[htf] // TF_MIN[ltf]
    idx_h = dh.index; idx_l = dl.index
    dh = dh.reset_index(drop=True); dl = dl.reset_index(drop=True)
    o_l, h_l, l_l, c_l = (dl.open.values.astype(float), dl.high.values.astype(float),
                          dl.low.values.astype(float), dl.close.values.astype(float))
    n_h, n_l = len(dh), len(dl)
    wt1_h, _, _, b_reg, s_reg, b_hid, s_hid = wt_pack(dh)
    cup_l, cdn_l = entry_signals(dl, ENTRY_MODE)   # sig_up → лонг, sig_dn → шорт
    lt = idx_l.values.astype("datetime64[ns]")
    bars_day_l = 1440 // TF_MIN[ltf]

    seen, rows = set(), []
    step = 1 if PROVISIONAL else STEP          # provisional-точка плывёт каждый бар — шаг 1
    for t in range(WARMUP, n_h, step):
        try:
            sub = dh.iloc[:t]
            zz = zigzag_atr(sub)
            prov_ts = None
            if PROVISIONAL:
                zz, prov_ts = append_provisional_leg(zz, sub)   # дорисовать текущую ногу
            imps = detect_elliott_impulse(zz)
        except Exception:
            continue
        for imp in imps:
            w = imp["waves"]
            a, b = int(w[0][0]), int(w[-1][0])
            # ключ дедупликации: при provisional точка 5 плывёт → один импульс = точки 0..4
            key = (a, int(w[4][0])) if PROVISIONAL else b
            if key in seen or b >= t or b <= a:
                continue
            is_prov = bool(prov_ts is not None and w[-1][0] == prov_ts)
            seen.add(key)
            p0, p4, p5 = float(w[0][1]), float(w[4][1]), float(w[5][1])
            rng = abs(p5 - p0)
            if rng <= 0 or p0 <= 0:
                continue
            imp_pct = rng / p0 * 100
            if not (MIN_IMP_PCT <= imp_pct <= MAX_IMP_PCT):
                continue
            up_imp = imp["direction"] == "up"
            if not np.isfinite(wt1_h[b]):
                continue
            if not ((wt1_h[b] > z) if up_imp else (wt1_h[b] < -z)):
                continue
            lo_d, hi_d = max(0, b - DIV_W), min(t, b + DIV_W)
            reg = bool((s_reg if up_imp else b_reg)[lo_d:hi_d + 1].any())
            hid = bool((s_hid if up_imp else b_hid)[lo_d:hi_d + 1].any())
            # ── ВХОД НА LTF: первый кросс против импульса, не раньше ЗАКРЫТИЯ HTF-бара t
            t_close = np.datetime64(idx_h[t].to_datetime64()) + np.timedelta64(TF_MIN[htf], "m")
            j0 = int(np.searchsorted(lt, t_close))
            j1 = min(n_l - 2, int(np.searchsorted(lt, np.datetime64(idx_h[b].to_datetime64())
                                                   + np.timedelta64(ENTRY_W_HTF * TF_MIN[htf], "m"))))
            if j1 <= j0:
                continue
            cross = cdn_l if up_imp else cup_l
            js = np.nonzero(cross[j0:j1 + 1])[0]
            if not len(js):
                continue
            j = j0 + int(js[0])
            e = float(o_l[j + 1])
            if e <= 0:
                continue
            # СТОП: за ФАКТИЧЕСКИЙ экстремум к моменту входа — при provisional точка 5 могла
            # уехать дальше между обнаружением и кроссом; стоп за старую точку = стоп внутри движения
            b_time = np.datetime64(idx_h[b].to_datetime64())
            jb = int(np.searchsorted(lt, b_time))
            ext = (float(h_l[jb:j + 1].max()) if up_imp else float(l_l[jb:j + 1].min())) if j >= jb else p5
            p5_eff = max(p5, ext) if up_imp else min(p5, ext)
            sl = p5_eff * (1 + BUF) if up_imp else p5_eff * (1 - BUF)
            if (up_imp and sl <= e) or (not up_imp and sl >= e):
                continue
            rng = abs(p5_eff - p0)
            gone = abs(e - p5_eff) / rng
            tgt = {"w4": p4,
                   "f382": p5_eff - 0.382 * rng if up_imp else p5_eff + 0.382 * rng,
                   "f500": p5_eff - 0.500 * rng if up_imp else p5_eff + 0.500 * rng,
                   "f618": p5_eff - 0.618 * rng if up_imp else p5_eff + 0.618 * rng}
            tgt = {k: v for k, v in tgt.items() if ((v < e) if up_imp else (v > e))}
            if not tgt:
                continue
            p5 = p5_eff
            hold_l = min(MAXHOLD_HTF, max(20, 2 * (b - a))) * ratio
            end = min(j + 1 + hold_l, n_l - 1)
            res, hit, stop_i, sl_pnl, tail = walk(h_l, l_l, c_l, j + 1, e, sl, up_imp, tgt, end)
            row = {"sym": sym, "htf": htf, "ltf": ltf, "z": z, "dir": imp["direction"],
                   "textbook": bool(imp.get("textbook")), "reg": reg, "hid": hid,
                   "ts": idx_l[j + 1], "year": int(pd.Timestamp(idx_l[j + 1]).year),
                   "entry": e, "sl": sl, "p0": p0, "p4": p4, "p5": p5,
                   "wave_idx": [int(w[k3][0]) for k3 in range(6)],
                   "wave_px": [float(w[k3][1]) for k3 in range(6)],
                   "a": a, "b": b, "t": t, "j": j, "provisional": is_prov,
                   "lag_htf_bars": (idx_l[j + 1] - idx_h[b]).total_seconds() / 60 / TF_MIN[htf],
                   "wt_at_p5": float(wt1_h[b]), "sl_pct": abs(e - sl) / e * 100,
                   "gone": gone, "imp_pct": imp_pct, "stopped": stop_i is not None, "hold": hold_l}
            for k4 in TGTS:
                if k4 in tgt:
                    row[f"hit_{k4}"] = k4 in hit
                    row[f"pnl_{k4}"] = (res[k4] if k4 in hit else (sl_pnl if stop_i is not None else tail)) - cost
                    row[f"rr_{k4}"] = abs(tgt[k4] - e) / abs(e - sl)
                    row[f"tgt_{k4}"] = tgt[k4]
                else:
                    for pre in ("hit_", "pnl_", "rr_", "tgt_"):
                        row[pre + k4] = np.nan
            for dd in (7, 14):
                pnl_h, st_h = hold_pnl(h_l, l_l, c_l, j + 1, e, sl, up_imp, min(j + 1 + bars_day_l * dd, n_l - 1))
                row[f"pnl_h{dd}d"] = pnl_h - cost
                row[f"stopped_h{dd}d"] = st_h
            # ── КОНТРОЛЬ: случайный LTF-бар ±30 дней, та же геометрия в %
            span = 30 * bars_day_l
            lo_i, hi_i = max(WARMUP * ratio, j - span), min(n_l - hold_l - 2, j + span)
            if hi_i > lo_i + 10:
                jj = rs.randint(lo_i, hi_i)
                ce = float(o_l[jj])
                csl = ce * (1 + row["sl_pct"] / 100) if up_imp else ce * (1 - row["sl_pct"] / 100)
                ctgt = {}
                for k5 in TGTS:
                    if np.isfinite(row.get(f"rr_{k5}", np.nan)):
                        dist = row[f"rr_{k5}"] * row["sl_pct"] / 100
                        ctgt[k5] = ce * (1 - dist) if up_imp else ce * (1 + dist)
                cres, chit, cst, csl_pnl, ctail = walk(h_l, l_l, c_l, jj, ce, csl, up_imp, ctgt,
                                                       min(jj + hold_l, n_l - 1))
                for k5 in TGTS:
                    if k5 in ctgt:
                        row[f"ctl_{k5}"] = (cres[k5] if k5 in chit else (csl_pnl if cst is not None else ctail)) - cost
                        row[f"ctlhit_{k5}"] = k5 in chit
                    else:
                        row[f"ctl_{k5}"] = np.nan; row[f"ctlhit_{k5}"] = np.nan
                for dd in (7, 14):
                    cp, _ = hold_pnl(h_l, l_l, c_l, jj, ce, csl, up_imp, min(jj + bars_day_l * dd, n_l - 1))
                    row[f"ctl_h{dd}d"] = cp - cost
            rows.append(row)
    return rows


def report(d, htf, ltf, z, cost):
    print(f"\n{'='*96}\nHTF {htf} → вход на {ltf} · зона |WT|>{z} · сделок {len(d)} · монет {d.sym.nunique()} · "
          f"{d.ts.min():%Y-%m-%d} → {d.ts.max():%Y-%m-%d} · кост {cost}%")
    print(f"стоп медиана {d.sl_pct.median():.2f}% · стоп-аут {d.stopped.mean()*100:.0f}% · "
          f"вход через {d.lag_htf_bars.median():.1f} HTF-баров после вершины w5 · "
          f"опоздание {d.gone.median()*100:.0f}% импульса · импульс {d.imp_pct.median():.1f}%")
    g0 = d.sort_values("ts").copy()
    g0["ep"] = g0.sym.astype(str) + "_" + g0.ts.dt.strftime("%Y%m")
    rows = []
    for k in TGTS + ["h7d", "h14d"]:
        PN, CT = f"pnl_{k}", f"ctl_{k}"
        if PN not in g0 or CT not in g0:
            continue
        g = g0[g0[PN].notna() & g0[CT].notna()]
        if len(g) < 25:
            continue
        pnl, ctl = g[PN], g[CT]
        dif = pnl - ctl
        epd = g.assign(_d=dif).groupby("ep")._d.mean()
        rs2 = np.random.RandomState(7)
        bsd = [epd.sample(len(epd), replace=True, random_state=rs2.randint(1e6)).mean() for _ in range(2000)]
        keep = pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):]
        hit = g[f"hit_{k}"].mean() * 100 if f"hit_{k}" in g else np.nan
        rr = g[f"rr_{k}"].median() if f"rr_{k}" in g else np.nan
        rows.append({"выход": k, "RR": rr, "n": len(g), "эп": epd.size, "дошли%": hit,
                     "на сделку%": pnl.mean(), "медиана%": pnl.median(), "WR%": (pnl > 0).mean() * 100,
                     "контроль%": ctl.mean(), "перевес": dif.mean(),
                     "ДИ перевеса": f"[{np.percentile(bsd,2.5):+.2f},{np.percentile(bsd,97.5):+.2f}]",
                     "значим": "ДА" if np.percentile(bsd, 2.5) > 0 else "нет",
                     "безтоп10/сд": keep.mean(),
                     "монет+%": (g.groupby("sym")[PN].sum() > 0).mean() * 100})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    for col in ("dir", "reg", "provisional", "year"):
        sub = g0[g0.pnl_w4.notna()]
        if col not in sub or sub[col].nunique() < 2:
            continue
        t2 = sub.groupby(col).agg(n=("pnl_w4", "size"), дошли=("hit_w4", lambda x: x.mean() * 100),
                                  на_сделку=("pnl_w4", "mean"), медиана=("pnl_w4", "median"),
                                  контроль=("ctl_w4", "mean"), h14=("pnl_h14d", "mean"))
        print(f"\n--- по {col} (цель w4 · h14 = выход 14 сут):")
        print(t2.to_string(float_format=lambda x: f"{x:8.3f}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--htf", default="4h")
    ap.add_argument("--ltf", default="1h")
    ap.add_argument("--pairs", type=int, default=60)
    ap.add_argument("--z", type=float, default=45)
    ap.add_argument("--cost", type=float, default=0.10)
    ap.add_argument("--entry", default="cross", choices=["cross", "sc", "engulf", "pinbar", "any"],
                    help="вход на LTF: кросс WT · sponsor candle · поглощение · пин-бар · any = первое любое")
    ap.add_argument("--prov", action="store_true",
                    help="provisional нога: точка 5 = текущий экстремум ДО подтверждения зигзагом (снимает лаг)")
    a = ap.parse_args()
    global ENTRY_MODE, PROVISIONAL
    ENTRY_MODE = a.entry
    PROVISIONAL = a.prov
    syms = universe(a.htf, n=a.pairs)
    print(f"HTF {a.htf} → LTF {a.ltf} · монет {len(syms)} · зона |WT|>{a.z} · вход: {a.entry}", flush=True)
    rs = np.random.RandomState(20260912)
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.htf, a.ltf, a.z, a.cost, rs)
        except Exception as e:
            print(f"  [skip] {s}: {type(e).__name__} {e}", flush=True)
        if i % 5 == 0:
            print(f"  {i}/{len(syms)} · строк {len(rows)}", flush=True)
    if not rows:
        print("НЕТ СДЕЛОК"); return
    d = pd.DataFrame(rows)
    _sfx = ("" if a.entry == "cross" else f"_{a.entry}") + ("_prov" if a.prov else "")
    d.to_pickle(Path(__file__).parent / f"wave5ltf_{a.htf}_{a.ltf}_z{int(a.z)}{_sfx}.pkl")
    report(d, a.htf, a.ltf, a.z, a.cost)


if __name__ == "__main__":
    main()
