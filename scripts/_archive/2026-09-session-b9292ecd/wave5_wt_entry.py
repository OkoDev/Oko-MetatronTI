# -*- coding: utf-8 -*-
"""ПРАВИЛО ЕГОРА ЦЕЛИКОМ (12.09.2026): экстремум ВОЛНЫ 5 в зоне OB/OS + ДИВЕРГЕНЦИЯ →
вход по КРОССУ wt1×wt2 → выход ПО ФИБО.

Собирает воедино две линии дня:
  · волновую — `detect_elliott_impulse` (6 точек зигзага, hard-правила Эллиотта, extension w5);
  · WT-схему Егора — `calculate_wt` (10/21, wt2=SMA4) + `_wtx_divergences` (эталон OkoTrend,
    сравнение с ОДНИМ предыдущим фракталом, флаг на баре подтверждения — лаг 2 бара внутри).

🔑 ЗАЧЕМ: базовый замер (wave5_correction.py) входил в момент подтверждения импульса и ОПАЗДЫВАЛ —
на картинках видно: вход по 0.00909 при вершине 0.0105, стоп 15.4% при цели 6%. Кросс WT даёт
точку разворота, а фильтр «зона + дивергенция» отсекает неисчерпанные импульсы (канон: волна 5
слабая, идёт с дивергенцией).

ПРАВИЛО:
  1. импульс найден префиксным проходом (детектор видит только df[:t]) — без перерисовки;
  2. на баре завершения волны 5 (b): wt1[b] > +Z (импульс ВВЕРХ) или wt1[b] < −Z (ВНИЗ);
  3. в окне [b−DIV_W, t] есть дивергенция нужного знака (bear_* для up, bull_* для down);
  4. ВХОД: первый кросс wt1×wt2 против импульса на баре j ≥ max(t, b), j ≤ b+ENTRY_W → open[j+1];
  5. ВЫХОД: фибо-цели 0.382 / 0.5 / 0.618 и зона волны 4; стоп за экстремум волны 5.
Причинность: и зона, и дивергенция, и кросс берутся на барах ≤ бара входа. WT и дивергенции
не перерисовываются (EMA + фрактал с подтверждением), поэтому вне префиксного цикла считать можно.

Запуск: python wave5_wt_entry.py [--tf 1h] [--pairs 30] [--z 60] [--cost 0.10]
"""
from __future__ import annotations
import argparse, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

from research_harness import load, universe                       # noqa: E402
from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse  # noqa: E402
from core.indicators.indicators import calculate_wt               # noqa: E402
from core.calculators.combinator_core import _wtx_divergences     # noqa: E402

WARMUP, STEP = 600, 6
BUF = 0.0015
DIV_W = 12          # окно поиска дивергенции вокруг вершины волны 5
ENTRY_W = 24        # сколько баров ждём кросс после вершины волны 5
MAXHOLD = 240
MIN_IMP_PCT, MAX_IMP_PCT = 3.0, 40.0
SL_MULT = 1.0      # множитель расстояния до стопа: 1.0 = ровно за экстремум волны 5, 1.5/2.0 = шире
TGTS = ["w4", "f382", "f500", "f618"]


def wt_and_div(df):
    d = calculate_wt(df.copy())
    wt1 = d["wt1"].values.astype(float)
    wt2 = d["wt2"].values.astype(float)
    bull_reg, bear_reg, bull_hid, bear_hid = _wtx_divergences(
        wt1, df.low.values.astype(float), df.high.values.astype(float))
    up = np.zeros(len(wt1), bool); dn = np.zeros(len(wt1), bool)
    up[1:] = (wt1[1:] > wt2[1:]) & (wt1[:-1] <= wt2[:-1])   # кросс ВВЕРХ
    dn[1:] = (wt1[1:] < wt2[1:]) & (wt1[:-1] >= wt2[:-1])   # кросс ВНИЗ
    return wt1, wt2, up, dn, bull_reg, bear_reg, bull_hid, bear_hid


def run_symbol(sym, tf, z, cost, rs):
    df = load(sym, tf)
    if len(df) < 1500:
        return []
    idx = df.index
    df = df.reset_index(drop=True)
    o, h, l, c = (df.open.values.astype(float), df.high.values.astype(float),
                  df.low.values.astype(float), df.close.values.astype(float))
    n = len(df)
    wt1, wt2, cup, cdn, b_reg, s_reg, b_hid, s_hid = wt_and_div(df)

    seen, rows = set(), []
    for t in range(WARMUP, n, STEP):
        try:
            imps = detect_elliott_impulse(zigzag_atr(df.iloc[:t]))
        except Exception:
            continue
        for imp in imps:
            w = imp["waves"]
            a, b = int(w[0][0]), int(w[-1][0])
            if b in seen or b >= t or b <= a:
                continue
            seen.add(b)
            p0, p4, p5 = float(w[0][1]), float(w[4][1]), float(w[5][1])
            rng = abs(p5 - p0)
            if rng <= 0 or p0 <= 0:
                continue
            imp_pct = rng / p0 * 100
            if not (MIN_IMP_PCT <= imp_pct <= MAX_IMP_PCT):
                continue
            up_imp = imp["direction"] == "up"
            # ── 2. ЗОНА на экстремуме волны 5
            if not np.isfinite(wt1[b]):
                continue
            in_zone = (wt1[b] > z) if up_imp else (wt1[b] < -z)
            if not in_zone:
                continue
            # ── 3. ДИВЕРГЕНЦИЯ — 🔑 ВОЗМОЖНА, НЕ ОБЯЗАТЕЛЬНА (уточнение Егора 12.09).
            # Не отсекаем: пишем флагом и сравниваем в отчёте «с дивергенцией / без» —
            # усилитель это или нет, должны сказать данные, а не моё допущение.
            lo_d, hi_d = max(0, b - DIV_W), min(t, b + DIV_W)
            reg = bool((s_reg if up_imp else b_reg)[lo_d:hi_d + 1].any())
            hid = bool((s_hid if up_imp else b_hid)[lo_d:hi_d + 1].any())
            # ── 4. ВХОД по кроссу против импульса, не раньше бара обнаружения
            j0 = max(t, b)
            j1 = min(n - 2, b + ENTRY_W)
            cross = cdn if up_imp else cup
            js = np.nonzero(cross[j0:j1 + 1])[0]
            if not len(js):
                continue
            j = j0 + int(js[0])
            e = float(o[j + 1])
            if e <= 0:
                continue
            # СТОП: за экстремум волны 5, с множителем расстояния (SL_MULT).
            # 🔑 Замер 4h показал: перевес над случайным входом есть (36.5% против 26.9%
            # достижения цели), но стоп за w5 его съедает — стоп-аут 71%. По закону проекта
            # «весь эдж в РАЗМЕРЕ стопа» проверяем 1.0 / 1.5 / 2.0 одной и той же механикой.
            _d5 = abs(e - p5 * (1 + BUF)) if up_imp else abs(e - p5 * (1 - BUF))
            _d5 *= SL_MULT
            sl = e + _d5 if up_imp else e - _d5
            if (up_imp and sl <= e) or (not up_imp and sl >= e):
                continue
            gone = abs(e - p5) / rng
            tgt = {"w4": p4,
                   "f382": p5 - 0.382 * rng if up_imp else p5 + 0.382 * rng,
                   "f500": p5 - 0.500 * rng if up_imp else p5 + 0.500 * rng,
                   "f618": p5 - 0.618 * rng if up_imp else p5 + 0.618 * rng}
            tgt = {k: v for k, v in tgt.items() if ((v < e) if up_imp else (v > e))}
            if not tgt:
                continue
            hold = min(MAXHOLD, max(20, 2 * (b - a)))
            end = min(j + 1 + hold, n - 1)
            sgn = -1 if up_imp else 1
            res, hit = {}, {}
            pend = set(tgt); stop_i = None
            for k2 in range(j + 1, end + 1):
                if (h[k2] >= sl) if up_imp else (l[k2] <= sl):
                    stop_i = k2; break
                for kk in list(pend):
                    px = tgt[kk]
                    if (l[k2] <= px) if up_imp else (h[k2] >= px):
                        res[kk] = (px - e) / e * 100 * sgn
                        hit[kk] = k2; pend.discard(kk)
                if not pend:
                    break
            sl_pnl = (sl - e) / e * 100 * sgn
            tail = (float(c[stop_i if stop_i is not None else end]) - e) / e * 100 * sgn
            row = {"sym": sym, "tf": tf, "z": z, "dir": imp["direction"],
                   "textbook": bool(imp.get("textbook")), "reg": bool(reg), "hid": bool(hid),
                   "ts": idx[j + 1], "year": int(pd.Timestamp(idx[j + 1]).year),
                   "entry": e, "sl": sl, "p0": p0, "p4": p4, "p5": p5,
                   "wave_idx": [int(w[k3][0]) for k3 in range(6)],
                   "wave_px": [float(w[k3][1]) for k3 in range(6)],
                   "w2_retr": imp.get("w2_retr"), "w4_retr": imp.get("w4_retr"),
                   "w3_ext": imp.get("w3_ext"),
                   "a": a, "b": b, "t": t, "j": j, "lag_cross": j - b,
                   "wt_at_p5": float(wt1[b]), "sl_pct": abs(e - sl) / e * 100,
                   "sl_mult": SL_MULT,
                   "gone": gone, "imp_pct": imp_pct, "stopped": stop_i is not None,
                   "hold": hold}
            for k4 in TGTS:
                if k4 in tgt:
                    row[f"hit_{k4}"] = k4 in hit
                    row[f"pnl_{k4}"] = (res[k4] if k4 in hit else
                                        (sl_pnl if stop_i is not None else tail)) - cost
                    row[f"rr_{k4}"] = abs(tgt[k4] - e) / abs(e - sl)
                    row[f"tgt_{k4}"] = tgt[k4]
                else:
                    for pre in ("hit_", "pnl_", "rr_", "tgt_"):
                        row[pre + k4] = np.nan
            # ── ВЫХОД ПО ФИКСИРОВАННОМУ ГОРИЗОНТУ (сведение с картой рамки, 12.09).
            # Перевес правила над случайным входом ЗНАЧИМ (+2.25…+2.94 п.п. на 4h), но рамка
            # «цель в 2-3 риска, удержание сутками» убыточна сама по себе. Единственная
            # неотрицательная рамка по карте — удержание от 3 суток. Сводим: тот же вход,
            # тот же стоп, но выход просто через 7 и 14 суток, без фибо-цели.
            _bd = {"5m": 288, "15m": 96, "1h": 24, "4h": 6}[tf]
            for _dd in (7, 14):
                _e2 = min(j + 1 + _bd * _dd, n - 1)
                _st = None
                for m in range(j + 1, _e2 + 1):
                    if (h[m] >= sl) if up_imp else (l[m] <= sl):
                        _st = m
                        break
                _px = sl if _st is not None else float(c[_e2])
                row[f"pnl_h{_dd}d"] = (_px - e) / e * 100 * sgn - cost
                row[f"stopped_h{_dd}d"] = _st is not None
                # контроль для того же горизонта считается ниже, в блоке контроля
            # контроль: случайный вход той же геометрии в ±30 дней
            span = 30 * (1440 // {"5m": 5, "15m": 15, "1h": 60, "4h": 240}[tf])
            lo_i, hi_i = max(WARMUP, j - span), min(n - MAXHOLD - 2, j + span)
            if hi_i > lo_i + 10:
                jj = rs.randint(lo_i, hi_i)
                ce = float(o[jj])
                csl = ce * (1 + row["sl_pct"] / 100) if up_imp else ce * (1 - row["sl_pct"] / 100)
                for k5 in TGTS:
                    if not np.isfinite(row.get(f"rr_{k5}", np.nan)):
                        row[f"ctl_{k5}"] = np.nan; row[f"ctlhit_{k5}"] = np.nan; continue
                    dist = row[f"rr_{k5}"] * row["sl_pct"] / 100
                    cpx = ce * (1 - dist) if up_imp else ce * (1 + dist)
                    e2 = min(jj + hold, n - 1)
                    hk, st2 = False, False
                    for m in range(jj, e2 + 1):
                        if (h[m] >= csl) if up_imp else (l[m] <= csl):
                            st2 = True; break
                        if (l[m] <= cpx) if up_imp else (h[m] >= cpx):
                            hk = True; break
                    row[f"ctl_{k5}"] = ((cpx - ce) / ce * 100 * sgn if hk else
                                        ((csl - ce) / ce * 100 * sgn if st2 else
                                         (float(c[e2]) - ce) / ce * 100 * sgn)) - cost
                    row[f"ctlhit_{k5}"] = hk
                # контроль для ФИКСИРОВАННЫХ горизонтов: та же случайная точка, тот же стоп,
                # выход через 7/14 суток — иначе перевес на длинном горизонте не посчитать
                for _dd in (7, 14):
                    _ce2 = min(jj + _bd * _dd, n - 1)
                    _cst = None
                    for m in range(jj, _ce2 + 1):
                        if (h[m] >= csl) if up_imp else (l[m] <= csl):
                            _cst = m
                            break
                    _cpx2 = csl if _cst is not None else float(c[_ce2])
                    row[f"ctl_h{_dd}d"] = (_cpx2 - ce) / ce * 100 * sgn - cost
            rows.append(row)
    return rows


def report(d, tf, z, cost):
    print(f"\n{'='*96}\nТФ {tf} · зона |WT|>{z} · сделок {len(d)} · монет {d.sym.nunique()} · "
          f"{d.ts.min():%Y-%m-%d} → {d.ts.max():%Y-%m-%d} · кост {cost}%")
    print(f"стоп медиана {d.sl_pct.median():.2f}% · стоп-аут {d.stopped.mean()*100:.0f}% · "
          f"кросс через {d.lag_cross.median():.0f} баров после вершины w5 · "
          f"WT на вершине медиана {d.wt_at_p5.median():+.0f} · импульс {d.imp_pct.median():.1f}% · "
          f"опоздание {d.gone.median()*100:.0f}% импульса")
    g0 = d.sort_values("ts").copy()
    gap = (g0.groupby("sym").ts.diff().dt.total_seconds().fillna(1e9) > 86400 * 3).cumsum()
    g0["ep"] = g0.sym.astype(str) + "_" + gap.astype(str)
    rows = []
    for k in TGTS:
        g = g0[g0[f"pnl_{k}"].notna()]
        if len(g) < 25:
            continue
        pnl, ctl = g[f"pnl_{k}"], g[f"ctl_{k}"]
        keep = pnl.sort_values(ascending=False).iloc[int(len(g) * 0.1):]
        ep = g.groupby("ep")[f"pnl_{k}"].mean()
        rs2 = np.random.RandomState(7)
        bs = [ep.sample(len(ep), replace=True, random_state=rs2.randint(1e6)).mean() for _ in range(1500)]
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        rows.append({"цель": k, "RR": g[f"rr_{k}"].median(), "n": len(g), "эп": ep.size,
                     "дошли%": g[f"hit_{k}"].mean() * 100,
                     "на сделку%": pnl.mean(), "медиана%": pnl.median(),
                     "WR%": (pnl > 0).mean() * 100,
                     "контроль%": ctl.mean(), "к.дошли%": g[f"ctlhit_{k}"].mean() * 100,
                     "над контр": pnl.mean() - ctl.mean(),
                     "безтоп10/сд": keep.mean(), "ДИ": f"[{lo:+.2f},{hi:+.2f}]",
                     "✅": "ДА" if lo > 0 else "нет"})
    if rows:
        print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:7.3f}"))
    # ── ФИКСИРОВАННЫЕ ГОРИЗОНТЫ (сведение с картой рамки): выход через 7/14 суток без цели
    hrows = []
    for _dd in (7, 14):
        PH, CH2 = f"pnl_h{_dd}d", f"ctl_h{_dd}d"
        if PH not in g0:
            continue
        gh = g0[g0[PH].notna()]
        if len(gh) < 25:
            continue
        ep = gh.groupby("ep")[PH].mean()
        rs3 = np.random.RandomState(11)
        dif = (gh[PH] - gh[CH2]) if CH2 in gh else None
        epd = gh.assign(_d=dif).groupby("ep")._d.mean() if dif is not None else None
        bsd = ([epd.sample(len(epd), replace=True, random_state=rs3.randint(1e6)).mean()
                for _ in range(1500)] if epd is not None else [np.nan])
        hrows.append({"горизонт": f"{_dd} сут", "n": len(gh), "эп": ep.size,
                      "стоп-аут%": gh[f"stopped_h{_dd}d"].mean() * 100,
                      "на сделку%": gh[PH].mean(), "медиана%": gh[PH].median(),
                      "WR%": (gh[PH] > 0).mean() * 100,
                      "контроль%": gh[CH2].mean() if CH2 in gh else np.nan,
                      "перевес": dif.mean() if dif is not None else np.nan,
                      "ДИ перевеса": f"[{np.percentile(bsd,2.5):+.2f},{np.percentile(bsd,97.5):+.2f}]",
                      "значим": "ДА" if np.percentile(bsd, 2.5) > 0 else "нет"})
    if hrows:
        print("\n--- ВЫХОД ПО ВРЕМЕНИ (без фибо-цели, стоп тот же):")
        print(pd.DataFrame(hrows).to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
        for _dd in (7, 14):
            PH = f"pnl_h{_dd}d"
            if PH in g0 and g0[PH].notna().sum() > 40:
                t3 = g0[g0[PH].notna()].groupby("dir").agg(
                    n=(PH, "size"), на_сделку=(PH, "mean"), медиана=(PH, "median"),
                    контроль=(f"ctl_h{_dd}d", "mean"))
                print(f"    {_dd} сут по направлению импульса:")
                print(t3.to_string(float_format=lambda x: f"{x:8.3f}"))

    for col in ("dir", "textbook", "reg", "year"):
        sub = g0[g0.pnl_f382.notna()]
        if not len(sub):
            continue
        t2 = sub.groupby(col).agg(n=("pnl_f382", "size"), дошли=("hit_f382", lambda x: x.mean() * 100),
                                  на_сделку=("pnl_f382", "mean"), медиана=("pnl_f382", "median"),
                                  контроль=("ctl_f382", "mean"))
        print(f"\n--- по {col} (цель 0.382):")
        print(t2.to_string(float_format=lambda x: f"{x:8.3f}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--pairs", type=int, default=30)
    ap.add_argument("--z", type=float, default=60)
    ap.add_argument("--cost", type=float, default=0.10)
    ap.add_argument("--slmult", type=float, default=1.0,
                    help="множитель стопа: 1.0 = за экстремум волны 5, 1.5/2.0 = шире")
    a = ap.parse_args()
    global SL_MULT
    SL_MULT = a.slmult
    syms = universe(a.tf, n=a.pairs)
    print(f"ТФ {a.tf} · монет {len(syms)} · зона |WT|>{a.z} · окно кросса {ENTRY_W} баров · "
          f"стоп ×{SL_MULT}", flush=True)
    rs = np.random.RandomState(20260912)
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, a.tf, a.z, a.cost, rs)
        except Exception as e:
            print(f"  [skip] {s}: {type(e).__name__} {e}", flush=True)
        if i % 5 == 0:
            print(f"  {i}/{len(syms)} · строк {len(rows)}", flush=True)
    if not rows:
        print("НЕТ СДЕЛОК — правило не сработало ни разу (проверь порог зоны и окно кросса)")
        return
    d = pd.DataFrame(rows)
    _tag = f"wave5wt_{a.tf}_z{int(a.z)}" + ("" if a.slmult == 1.0 else f"_s{a.slmult:g}")
    d.to_pickle(Path(__file__).parent / f"{_tag}.pkl")
    report(d, a.tf, a.z, a.cost)


if __name__ == "__main__":
    main()
