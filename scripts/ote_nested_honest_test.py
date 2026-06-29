# -*- coding: utf-8 -*-
"""NESTED честно — ПЕРЕМЕР таблицы юзера (4h→15m и т.д.) на ЧЕСТНОМ SL + TP@1R.

Старая таблица (ote_remine.py) = синтетика: ТУГОЙ 6-баровый LTF-SL + метрика MFE (потолок),
не реальный P&L → раздутые net@3R. Здесь ЧЕСТНО, метод юзера:
  1. HTF (4h/1h): слом структуры → OTE-зона (find_setups_zz на HTF). Это «ГДЕ смотреть».
  2. Цена ретестит HTF-OTE → внутри окна ищем LTF-слом (15m/5m) в сторону HTF → ВХОД.
  3. SL = LTF-импульс-1.0 (структурный, РЕАЛЬНОЕ расстояние LTF — НЕ тугой 6-бар). risk×10 естественно.
  4. ВЫХОД = TP@1R (реальный walk: TP или SL что раньше, без lookahead). + runner для контраста.
Связки как в таблице: 4h→1h/15m/5m, 1h→15m/5m × long/short. SL=честный, выход=TP@1R.
Запуск: python scripts/ote_nested_honest_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa
from core.trading.tsl_engine import compute_hybrid_tsl, TSL_PROFILES, TSLProfile  # наш гибридный TSL
# Широкий профиль — дать дышать до ~30R (ловить крипто-хвост 1:N, не обрезать на 8R)
PROF_WIDE = TSLProfile(gear1_be_atr=1.0, gear2_atr=4.0, gear3_atr=30.0, gear3_hours=240.0)

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--ote-nested-honest"
BUF, RT, MAXHOLD_LTF = 0.0015, 0.10, 2880   # 2880 LTF-баров = дать длинным трендам ехать (хвост 1:N)
TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
PAIRS_TF = [("4h", "1h"), ("4h", "15m"), ("4h", "5m"), ("1h", "15m"), ("1h", "5m")]
HTF_HOLD_BARS = 30   # окно ретеста HTF-OTE (в HTF-барах) для поиска LTF-входа


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


def _walk_exits(D, entry, slv, ei, x_end, lo, hi, cl, tf_min, imp_from=None, imp_to=None):
    """Все политики выхода за ОДИН проход (без lookahead, SL проверяется первым в баре)."""
    risk = abs(entry - slv); fee = RT / (risk / entry * 100)
    def adv(j, lvl):
        tgt = entry - lvl * risk if D == "short" else entry + lvl * risk
        return (lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)
    def slhit(j, slp):
        return (hi[j] >= slp) if D == "short" else (lo[j] <= slp)
    def close_R():
        return ((entry - cl[x_end]) if D == "short" else (cl[x_end] - entry)) / risk
    res = {}
    # tp1 (1:1 диагноз)
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
        if adv(j, 1.0): r = 1.0; break
    res["tp1"] = (r if r is not None else close_R()) - fee
    # runner (SL fixed, до окна)
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
    res["runner"] = (r if r is not None else close_R()) - fee
    # be1_run: BE после 1R → раннер
    be = False; r = None
    for j in range(ei, x_end + 1):
        slp = entry if be else slv
        if slhit(j, slp): r = (0.0 if be else -1.0); break
        if not be and adv(j, 1.0): be = True
    res["be1_run"] = (r if r is not None else close_R()) - fee
    # tp_2R (2:1)
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
        if adv(j, 2.0): r = 2.0; break
    res["tp_2R"] = (r if r is not None else close_R()) - fee
    # tp_3R (3:1)
    r = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): r = -1.0; break
        if adv(j, 3.0): r = 3.0; break
    res["tp_3R"] = (r if r is not None else close_R()) - fee
    # half1_tr: ½ фикс @1R + остаток (BE-стоп, цель 3R)
    reached = False; r1 = None
    for j in range(ei, x_end + 1):
        if slhit(j, slv): break
        if adv(j, 1.0): reached = True; r1 = j; break
    if not reached:
        res["half1_tr"] = -1.0 - fee
    else:
        rem = None
        for j in range(r1, x_end + 1):
            if slhit(j, entry): rem = 0.0; break       # остаток выбит в BE
            if adv(j, 3.0): rem = 3.0; break           # хвост дошёл до 3R
        if rem is None: rem = close_R()
        res["half1_tr"] = 0.5 * 1.0 + 0.5 * rem - fee
    # hybrid — НАШ движок compute_hybrid_tsl (профиль ote_nested), трейл bar-by-bar
    ds = "LONG" if D == "long" else "SHORT"
    prof = TSL_PROFILES.get("ote_nested")
    cur = slv; r = None
    for j in range(ei, x_end + 1):
        if (hi[j] >= cur) if D == "short" else (lo[j] <= cur):   # триггер по SL прошлого бара
            r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
        dur = (j - ei) * tf_min
        dec = compute_hybrid_tsl(ds, entry, cl[j], slv, duration_minutes=dur, profile=prof)
        if dec.new_sl and dec.new_sl > 0:
            cur = min(cur, dec.new_sl) if D == "short" else max(cur, dec.new_sl)
    res["hybrid"] = (r if r is not None else close_R()) - fee
    # MFE (потолок до SL)
    mfe = 0.0
    for j in range(ei, x_end + 1):
        fav = ((entry - lo[j]) if D == "short" else (hi[j] - entry)) / risk
        mfe = max(mfe, fav)
        if slhit(j, slv): break
    # cascade: эмуляция каскада 15m→1h→4h — трейл РАСШИРЯЕТСЯ по фазам R + anti-degrade(R≥5) +
    #          R-gradient de-escalation (откат >15% от пика R, peak≥3 = DEV-91). BE@1R.
    entry_atr = risk / 1.5
    cur = slv; peak_r = 0.0; r = None
    for j in range(ei, x_end + 1):
        if (hi[j] >= cur) if D == "short" else (lo[j] <= cur):
            r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
        cr = ((entry - cl[j]) if D == "short" else (cl[j] - entry)) / risk   # тек. R по close (консерв.)
        peak_r = max(peak_r, cr)
        if peak_r >= 3.0 and cr < peak_r * 0.85:        # R-gradient drop → выход
            r = cr; break
        if cr < 1.5:   tdist = 1.5 * entry_atr          # 15m-фаза (близко)
        elif cr < 5.0: tdist = 4.0 * entry_atr          # 1h-фаза (шире)
        else:          tdist = 10.0 * entry_atr         # 4h-фаза (широко, anti-degrade ракеты)
        if D == "long":
            lvl = cl[j] - tdist
            if cr >= 1.0: lvl = max(lvl, entry)         # BE@1R
            cur = max(cur, lvl)
        else:
            lvl = cl[j] + tdist
            if cr >= 1.0: lvl = min(lvl, entry)
            cur = min(cur, lvl)
    res["cascade"] = (r if r is not None else close_R()) - fee
    # fib-выходы (по гайду): цель = проекция ноги импульса target_k = from + k·(to−from). SL структурный.
    if imp_from is not None and imp_to is not None:
        imp_len = imp_to - imp_from
        for k in (1.0, 1.618, 2.618, 3.0, 3.618, 4.168):
            tgt = imp_from + k * imp_len
            rr = None
            for j in range(ei, x_end + 1):
                if slhit(j, slv): rr = -1.0; break
                hit = (lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)
                if hit:
                    rr = ((entry - tgt) if D == "short" else (tgt - entry)) / risk; break
            if rr is None: rr = close_R()
            res[f"fib{k}"] = rr - fee
    # half1_casc: ½ фикс на 1R + ½ каскад (WR + хвост через широкий 4h-трейл)
    # half1_run: ½ фикс на 1R (WR) + ½ раннер (ловит хвост 1:N). fee сокращается.
    res["half1_run"] = 0.5 * res["tp1"] + 0.5 * res["runner"]
    res["half1_casc"] = 0.5 * res["tp1"] + 0.5 * res["cascade"]
    # hybrid_wide: наш TSL но ШИРОКИЙ профиль (дышит до 30R — ловить хвост, не обрезать)
    cur = slv; r = None
    for j in range(ei, x_end + 1):
        if (hi[j] >= cur) if D == "short" else (lo[j] <= cur):
            r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
        dec = compute_hybrid_tsl(ds, entry, cl[j], slv, duration_minutes=(j - ei) * tf_min, profile=PROF_WIDE)
        if dec.new_sl and dec.new_sl > 0:
            cur = min(cur, dec.new_sl) if D == "short" else max(cur, dec.new_sl)
    res["hybrid_wide"] = (r if r is not None else close_R()) - fee
    # half1_wide: ½ фикс на 1R + ½ hybrid_wide (WR от фикса + хвост от широкого трейла)
    res["half1_wide"] = 0.5 * res["tp1"] + 0.5 * res["hybrid_wide"]
    # struct_trail (Егор 29.06): широкий SL вход → ПОСЛЕ +0.5R переносим SL за LTF-структуру
    # (min/max последних K баров = свежий swing после разворота = имитация «перенос за LTF-
    # структурный после слома»). Широкий вход выживает прокол, затем риск сокращается.
    K = 5; cur = slv; act = False; r = None
    for j in range(ei, x_end + 1):
        if slhit(j, cur):
            r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
        cr = ((entry - cl[j]) if D == "short" else (cl[j] - entry)) / risk
        if not act and cr >= 0.5: act = True
        if act and j > ei:
            w0 = max(ei, j - K)
            if D == "long": cur = max(cur, float(min(lo[w0:j + 1])))
            else:           cur = min(cur, float(max(hi[w0:j + 1])))
    res["struct_trail"] = (r if r is not None else close_R()) - fee
    res["mfe"] = mfe
    return res, risk


def _ltf_entry_R(s_l, df_l, posL, htf_lo, htf_hi, D, tf_min, wt_l=None, wt_h=None,
                 wt_mode="off", dbull=None, dbear=None, fib_mode=False):
    """Вход по LTF-слому s_l внутри HTF-OTE → net по всем политикам. Честный SL=LTF-импульс-1.0.
    fib_mode (27.06): только LONG + сильный импульс (>30%) для fib-расширений.
    wt_mode (КАРТА Егора): off | ltf (WT экстремум на LTF) | htf (WT на старшем ТФ — «WT на 1h») |
                           div (дивергенция на LTF — «может не быть OB/OS из-за div») | htf_or_div."""
    ote_lo, ote_hi = s_l["ote"]
    entry = (ote_lo + ote_hi) / 2.0
    if not (htf_lo <= entry <= htf_hi):   # вход должен быть в HTF-OTE
        return None
    # FIB-MODE: ТОЛЬКО LONG
    if fib_mode:
        if D != "long":
            return None
    ci = posL.get(s_l["choch_ts"])
    if ci is None: return None
    lo = df_l["low"].values; hi = df_l["high"].values; cl = df_l["close"].values; n = len(df_l)
    ei = None
    for j in range(ci + 1, min(ci + 1 + 60, n)):
        if not (lo[j] <= ote_hi and hi[j] >= ote_lo): continue
        if wt_mode != "off":
            ok_ltf = ok_htf = ok_div = False
            if wt_l is not None and j < len(wt_l):
                w = wt_l[j]; ok_ltf = (w >= 60) if D == "short" else (w <= -60)
            if wt_h is not None:
                try:
                    wh = wt_h.asof(df_l.index[j])
                    ok_htf = pd.notna(wh) and ((wh >= 60) if D == "short" else (wh <= -60))
                except Exception: pass
            if dbull is not None:
                w0 = max(0, j - 10)
                arr = dbear if D == "short" else dbull
                ok_div = bool(arr[w0:j + 1].any())
            passed = {"ltf": ok_ltf, "htf": ok_htf, "div": ok_div,
                      "htf_or_div": ok_htf or ok_div}.get(wt_mode, True)
            if not passed: continue
        ei = j; break
    if ei is None: return None
    slv = s_l["levels"][1.0] * (1 - BUF) if D == "long" else s_l["levels"][1.0] * (1 + BUF)
    risk = abs(entry - slv)
    if risk <= 0: return None
    x_end = min(ei + MAXHOLD_LTF, n - 1)
    ex, _ = _walk_exits(D, entry, slv, ei, x_end, lo, hi, cl, tf_min,
                        imp_from=s_l["from"][1], imp_to=s_l["to"][1])
    ex["sl_pct"] = round(risk / entry * 100, 3); ex["ts"] = df_l.index[ei]
    # WT при входе (вопрос юзера: вход от OS/OB или из середины?)
    ex["wt_ltf"] = float(wt_l[ei]) if (wt_l is not None and ei < len(wt_l)) else None
    if wt_h is not None:
        try:
            v = wt_h.asof(df_l.index[ei]); ex["wt_htf"] = float(v) if pd.notna(v) else None
        except Exception:
            ex["wt_htf"] = None
    return ex


def test_pair(conn, sym, wt_mode="off", fib_mode=False, smc_filter=None):
    from core.smc.smc_engine import zigzag_atr, find_setups_zz
    from core.indicators.indicators import calculate_wt
    from core.calculators.combinator_core import _wtx_divergences
    out = defaultdict(list)
    cache = {}; wtc = {}; divc = {}
    def get(tf):
        if tf not in cache:
            d = _load(conn, sym, tf); cache[tf] = d
            wl = ws = None; db = dr = None
            if d is not None and len(d) > 60:
                try:
                    w = calculate_wt(d.copy())["wt1"].values
                    wl = w; ws = pd.Series(w, index=d.index)
                    _br, _ber, _bh, _beh = _wtx_divergences(w, d["low"].values, d["high"].values)
                    db = np.asarray(_br, bool) | np.asarray(_bh, bool)
                    dr = np.asarray(_ber, bool) | np.asarray(_beh, bool)
                except Exception:
                    pass
            wtc[tf] = (wl, ws); divc[tf] = (db, dr)
        return cache[tf]
    for htf, ltf in PAIRS_TF:
        df_h = get(htf); df_l = get(ltf)
        if df_h is None or df_l is None or len(df_h) < 100 or len(df_l) < 300: continue
        setups_h = find_setups_zz(zigzag_atr(df_h), df_h)
        setups_l = find_setups_zz(zigzag_atr(df_l), df_l)
        if not setups_h or not setups_l: continue
        wt_l, _ = wtc[ltf]; _, wt_h = wtc[htf]
        dbull, dbear = divc[ltf]
        # SMC features for filtering
        smc_ell_ts = set()
        if smc_filter:
            from core.smc.smc_engine import detect_elliott_impulse
            zz_h = zigzag_atr(df_h)
            ell_imp = detect_elliott_impulse(zz_h)
            for e in ell_imp:
                smc_ell_ts.add(e['waves'][5][0])  # choch timestamp
        posL = {ts: i for i, ts in enumerate(df_l.index)}
        hold = pd.Timedelta(minutes=HTF_HOLD_BARS * TF_MIN[htf])
        for s_h in setups_h:
            D = s_h["direction"]; htf_lo, htf_hi = s_h["ote"]; h_ts = s_h["choch_ts"]
            w_end = h_ts + hold
            # первый LTF-слом в направлении HTF, в окне, внутри HTF-OTE
            for s_l in setups_l:
                if s_l["direction"] != D: continue
                if not (h_ts < s_l["choch_ts"] <= w_end): continue
                # SMC filter: CHoCH-only (trend change = wave 1 potential)
                if smc_filter and smc_filter in ('elliott','all','choch'):
                    if s_h['kind'] not in ('CHoCH',):
                        continue
                r = _ltf_entry_R(s_l, df_l, posL, htf_lo, htf_hi, D, TF_MIN[ltf], wt_l, wt_h, wt_mode, dbull, dbear, fib_mode=fib_mode)
                if r is not None:
                    r["key"] = f"{htf}→{ltf} {D}"; r["htf"] = htf; r["ltf"] = ltf; r["dir"] = D
                    out[r["key"]].append(r)
                    break   # один вход на HTF-сетап (первый)
    return out


POLICIES = ["tp1", "tp_2R", "tp_3R", "struct_trail", "fib1.0", "fib1.618", "fib2.618", "fib3.0", "fib3.618", "fib4.168", "cascade", "hybrid", "runner"]


def net_of(rows, key):
    vals = [r[key] for r in rows if key in r]
    n = len(vals)
    if not n: return None
    return {"n": n, "net": round(sum(vals) / n, 3), "wr": round(100 * sum(1 for x in vals if x > 0) / n)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0)
    ap.add_argument("--wt-mode", default="off", choices=["off", "ltf", "htf", "div", "htf_or_div"],
                    help="КАРТА: вход от WT OB/OS — ltf|htf(1h)|div(дивергенция)|htf_or_div")
    ap.add_argument("--fib-mode", action="store_true",
                    help="FIB-режим (27.06): только LONG + импульс>30% — проверка fib-расширений")
    ap.add_argument("--smc-filter", default=None,
                    help="SMC-фильтр: choch|all — только CHoCH (волна 1+3 паттерн)")
    a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    print(f"[nested] пар: {len(syms)} · WT-вход(карта): {a.wt_mode}", flush=True)
    allr = defaultdict(list)
    for i, sym in enumerate(syms):
        try:
            for k, v in test_pair(conn, sym, a.wt_mode, fib_mode=a.fib_mode, smc_filter=a.smc_filter).items(): allr[k].extend(v)
        except Exception: pass
        if (i + 1) % 25 == 0: print(f"[nested] {i+1}/{len(syms)} | связок {len(allr)}", flush=True)
    conn.close()
    L = [f"# NESTED ЧЕСТНО — политики ВЫХОДА на честном LTF-SL (перемер таблицы юзера)\n",
         f"> вход: LTF-слом ВНУТРИ HTF-OTE. SL=LTF-импульс-1.0 (честный). комса {RT}%.\n",
         f"> выходы: tp1=1:1 · be1_run=BE@1R→раннер · half1_tr=½@1R+½трейл до 3R · runner=держать.\n",
         "\n## по связке HTF→LTF × направление (net E[R] / WR; сорт по hybrid=наш TSL)\n"
         "| связка | n | tp1 | tp_2R | tp_3R | **hybrid** | runner | SL%med | MFEmed |\n|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for k, v in allr.items():
        if len(v) >= 30:
            rows.append((k, v, net_of(v, "hybrid")["net"]))
    rows.sort(key=lambda x: -x[2])
    for k, v, _ in rows:
        def cell(p):
            m = net_of(v, p); return f"{m['net']:+.3f}({m['wr']}%)"
        slm = round(float(np.median([r["sl_pct"] for r in v])), 2)
        mfm = round(float(np.median([r["mfe"] for r in v])), 2)
        L.append(f"| {k} | {len(v)} | {cell('tp1')} | {cell('tp_2R')} | {cell('tp_3R')} | **{cell('hybrid')}** | {cell('runner')} | {slm} | {mfm} |")
    # итог по политике (все связки)
    L.append("\n## ИТОГ по политике выхода (все связки)\n| политика | n | net E[R] | WR |\n|---|---|---|---|")
    flat = [r for v in allr.values() for r in v]
    for p in POLICIES:
        m = net_of(flat, p)
        if m:
            flag = "🟢" if m["net"] > 0 else "🔴"
            L.append(f"| {p} | {m['n']} | **{m['net']:+.3f}** {flag} | {m['wr']}% |")
    # ── 🎯 ХВОСТ R — реально ли 1:N? (распределение реализованного R, горизонт 2880 баров) ──
    L.append("\n## 🎯 ХВОСТ R — реально ли высокий 1:N? (доля сделок достигших N·R)\n"
             "| политика | max R | ≥3R | ≥5R | ≥10R | ≥16R | ≥30R | вклад ≥5R в общий sumR |\n|---|---|---|---|---|---|---|---|")
    for pol in ("runner", "cascade", "half1_casc", "half1_run", "hybrid", "tp1"):
        vals = np.array([r[pol] for r in flat if pol in r])
        if not len(vals): continue
        tot = vals.sum(); tail = vals[vals >= 5].sum()
        cells = " | ".join(f"{round(100*(vals >= k).mean(), 2)}%" for k in (3, 5, 10, 16, 30))
        contrib = round(100 * tail / tot) if tot > 0 else 0
        L.append(f"| {pol} | {vals.max():+.1f} | {cells} | {contrib}% |")
    # raw-MFE потолок (докуда ДОЕХАЛО бы без обрыва — потенциал хвоста)
    mfe_all = np.array([r["mfe"] for v in allr.values() for r in v])
    L.append(f"\n**MFE-потолок (потенциал):** max {mfe_all.max():.1f}R · ≥5R {round(100*(mfe_all>=5).mean(),1)}% · ≥10R {round(100*(mfe_all>=10).mean(),1)}% · ≥16R {round(100*(mfe_all>=16).mean(),2)}% · ≥30R {round(100*(mfe_all>=30).mean(),2)}%\n")
    # ── 💵 $-СИМУЛЯЦИЯ (компаундинг, риск 1%/сделку) — нам нужны $, не R ──
    flat_ts = sorted(flat, key=lambda r: r["ts"])
    L.append("\n## 💵 $-СИМУЛЯЦИЯ — старт $1000, риск 1%/сделку, последовательно, компаундинг\n| выход | финал $ | ×старт | maxDD | ср.время(бар) |\n|---|---|---|---|---|")
    for pol in ("tp1", "fib1.0", "fib1.618", "fib2.618", "cascade", "hybrid", "runner"):
        bal = 1000.0; peak = 1000.0; maxdd = 0.0
        for r in flat_ts:
            if pol not in r: continue
            bal += r[pol] * (bal * 0.01)
            if bal <= 0: bal = 0.01
            peak = max(peak, bal); maxdd = max(maxdd, (peak - bal) / peak)
        held = np.mean([r.get("held_" + pol, np.nan) for r in flat if "held_" + pol in r]) if any("held_" + pol in r for r in flat) else float("nan")
        L.append(f"| {pol} | ${bal:,.0f} | ×{bal/1000:.1f} | {round(100*maxdd)}% | {'' if held!=held else round(held)} |")
    L.append("\n> $ при фикс-риске ∝ sumR; но компаундинг усиливает хвост, а частые сделки (tp1) быстрее оборачивают капитал.")
    # ── 🔍 ГДЕ возникают ХВОСТЫ (runner≥10R): связка / направление / квартал ──
    from collections import Counter as _C
    tail = [r for r in flat if r.get("runner", 0) >= 10]
    L.append(f"\n## 🔍 ГДЕ возникают ИКСЫ (runner ≥10R, n={len(tail)} из {len(flat)})")
    if tail:
        bk = _C(r["key"] for r in tail); ba = _C(r.get("htf", "?") for r in tail)
        bq = _C(f"{r['ts'].year}Q{(r['ts'].month-1)//3+1}" for r in tail)
        base_k = _C(r["key"] for r in flat)
        L.append("**по связке (доля иксов внутри связки):**")
        for k, c in bk.most_common():
            L.append(f"  {k}: {c} иксов / {base_k[k]} ({round(100*c/base_k[k],1)}%)")
        L.append(f"**по HTF:** {dict(ba)}")
        L.append(f"**редкость во времени:** {dict(sorted(bq.items()))}")
    # ── 🌊 WT ПРИ ВХОДЕ (вопрос юзера: вход от OS/OB или из середины?) ──
    def wzone(w, D):
        if w is None: return None
        if D == "long":  return "OS✓(перепрод)" if w <= -60 else "OB✗(перекуп)" if w >= 60 else "mid(середина)"
        else:            return "OB✓(перекуп)" if w >= 60 else "OS✗(перепрод)" if w <= -60 else "mid(середина)"
    for tflab, key in (("LTF (вход)", "wt_ltf"), ("HTF (контекст)", "wt_htf")):
        ws = [r[key] for r in flat if r.get(key) is not None]
        if not ws: continue
        wa = np.array(ws)
        L.append(f"\n## 🌊 WT при входе — {tflab} (n={len(wa)})")
        L.append(f"распределение: OS<−60 **{round(100*(wa<=-60).mean())}%** · середина(−60..60) **{round(100*((wa>-60)&(wa<60)).mean())}%** · OB>+60 **{round(100*(wa>=60).mean())}%** · медиана {np.median(wa):.0f}")
        # сплит выходов по WT-зоне входа
        L.append("| WT-зона входа | n | tp1 net | fib2.618 net | runner net | max R |")
        L.append("|---|---|---|---|---|---|")
        buckets = defaultdict(list)
        for r in flat:
            z = wzone(r.get(key), r["dir"])
            if z: buckets[z].append(r)
        for z in ("OS✓(перепрод)", "OB✓(перекуп)", "mid(середина)", "OB✗(перекуп)", "OS✗(перепрод)"):
            sub = buckets.get(z, [])
            if len(sub) < 30: continue
            mt = net_of(sub, "tp1"); mf = net_of(sub, "fib2.618"); mr = net_of(sub, "runner")
            mx = max(r.get("runner", -9) for r in sub)
            L.append(f"| {z} | {len(sub)} | {mt['net']:+.3f}({mt['wr']}%) | {mf['net']:+.3f} | {mr['net']:+.3f} | {mx:+.1f} |")
    # ── WALK-FORWARD OOS ──
    from collections import defaultdict as _dd
    flat.sort(key=lambda r: r["ts"])
    byq = _dd(list)
    for r in flat:
        ts = r["ts"]; byq[f"{ts.year}Q{(ts.month - 1)//3 + 1}"].append(r)
    quarters = sorted(byq)
    # (A) net по кварталам — стабильность эджа во времени
    L.append("\n## 🔬 WALK-FORWARD (A): net по кварталам (OOS-стабильность)\n| квартал | n | tp1 | tp_2R | tp_3R | hybrid | runner |\n|---|---|---|---|---|---|---|")
    for q in quarters:
        sub = byq[q]
        if len(sub) < 50: continue
        L.append(f"| {q} | {len(sub)} | {net_of(sub,'tp1')['net']:+.3f} | {net_of(sub,'tp_2R')['net']:+.3f} | {net_of(sub,'tp_3R')['net']:+.3f} | {net_of(sub,'hybrid')['net']:+.3f} | {net_of(sub,'runner')['net']:+.3f} |")
    # (B) настоящий WF: train(всё до Q) ВЫБИРАЕТ политику → test=Q (OOS) проверяет
    L.append("\n## 🔬 WALK-FORWARD (B): train выбирает выход → OOS-квартал проверяет\n| OOS-квартал | n | выбран train | OOS net | OOS WR |\n|---|---|---|---|---|")
    hits = 0; tot = 0; oos_sum = 0.0
    for i in range(1, len(quarters)):
        train = [r for q in quarters[:i] for r in byq[q]]
        test = byq[quarters[i]]
        if len(train) < 300 or len(test) < 50: continue
        best = max(POLICIES, key=lambda p: net_of(train, p)["net"])
        m = net_of(test, best)
        flag = "🟢" if m["net"] > 0 else "🔴"
        L.append(f"| {quarters[i]} | {m['n']} | {best} | **{m['net']:+.3f}** {flag} | {m['wr']}% |")
        tot += 1; hits += (m["net"] > 0); oos_sum += m["net"]
    if tot:
        L.append(f"\n**WF-итог:** OOS-кварталов положительных **{hits}/{tot}** ({round(100*hits/tot)}%) · средний OOS net **{oos_sum/tot:+.3f}R**")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
