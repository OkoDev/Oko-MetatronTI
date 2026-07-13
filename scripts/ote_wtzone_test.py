# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА — вход ОТ WT-ЗОНЫ первично (docs/METHOD_MAP.md), не фильтром.

Каркас (подтверждён юзером 21.06):
  1. На 1h: WT заходит в OB (>+60) → SHORT  /  OS (<−60) → LONG   ← ОТБОР зоны (ПЕРВИЧНО).
  2. В окне после зоны: слом структуры 15m (find_setups_zz) в сторону D.
  3. Фиба OTE 0.618–0.786 на импульсе слома → вход на ретесте. SL = импульс-1.0 (честный).
  4. ПОЛЁТ (выход) до: противоположный CHoCH / fib 1.618 / противоположная зона WT (1h) / tp1(контраст) / hybrid.
     WT на 15m в момент входа может уже выйти из зоны — это норм (дивергенция).
Метрики: net R + $ (компаунд, риск1%) + WR + max R + хвост. Без lookahead.
Запуск: python scripts/ote_wtzone_test.py [--pairs N]
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa
import numpy as np   # noqa
from core.trading.tsl_engine import compute_hybrid_tsl, TSL_PROFILES

CACHE = ROOT / "ohlcv_cache.db"
OUT = ROOT / "data" / "research" / "2026-06-21--wtzone-method"
BUF, RT, MAXHOLD = 0.0015, 0.10, 2880
ZONE_WINDOW_H = 48     # окно (часов) после WT-зоны 1h на поиск слома 15m
OB, OS = 60.0, -60.0
POLICIES = ["tp1", "magnet_near", "magnet_score", "magnet_rr", "magnet_htf", "struct_htf",
            "struct_trail", "imp_tsl", "wave3", "fib-1", "hybrid"]


def _load(conn, sym, tf):
    df = pd.read_sql_query("SELECT time,open,high,low,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
                           conn, params=(sym, tf))
    if df.empty: return None
    df.index = pd.to_datetime(df["time"], unit="ms", utc=True); return df


_MW = {"fvg": 3.0, "ob": 3.5, "eqh": 3.0, "swing": 2.5, "fib": 2.5, "psycho": 2.0}


def _magnets(win, entry, D, imp_from, imp_to):
    """Магниты цены по направлению прибыли (long→выше / short→ниже). Веса = TPSelector _WEIGHTS."""
    from core.smc.smc_engine import (detect_fvg, detect_order_blocks, detect_structure_breaks,
                                     detect_equal_levels)
    is_long = D == "long"; mags = []
    def add(p, w):
        if p and p > 0 and ((is_long and p > entry) or (not is_long and p < entry)): mags.append((float(p), w))
    try:
        for fv in detect_fvg(win):
            top, bot, dr = max(fv[1], fv[2]), min(fv[1], fv[2]), fv[3]
            if (is_long and dr == "bear") or (not is_long and dr == "bull"): add((top + bot) / 2, _MW["fvg"])
    except Exception: pass
    try:
        sb = detect_structure_breaks(win, length=5)
        for ob in detect_order_blocks(win, sb):
            if (is_long and ob.kind == "bear") or (not is_long and ob.kind == "bull"): add((ob.top + ob.bottom) / 2, _MW["ob"])
    except Exception: pass
    try:
        for (t1, p1, t2, p2, lab) in detect_equal_levels(win):
            if (is_long and lab == "EQH") or (not is_long and lab == "EQL"): add((p1 + p2) / 2, _MW["eqh"])
    except Exception: pass
    for k in (1.0, 1.618, 2.618): add(imp_from + k * (imp_to - imp_from), _MW["fib"])
    add(win["high"].max() if is_long else win["low"].min(), _MW["swing"])
    return mags


TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


def test_pair(conn, sym, zone_tf="1h", break_tf="15m", dir_tf=None):
    from core.smc.smc_engine import (zigzag_atr, find_setups_zz, _zz_typed,
                                     detect_sponsored_candle, detect_fvg)
    from core.smc.elliott_engine import forecast_wave3, impulse_sharpness, count_legs_since
    from core.indicators.indicators import calculate_wt
    tfm = TF_MIN[break_tf]
    df1 = _load(conn, sym, zone_tf); df15 = _load(conn, sym, break_tf)
    if df1 is None or df15 is None or len(df1) < 100 or len(df15) < 300: return []
    # ВОЛНОВАЯ МУЛЬТИСТРУКТУРА: третий (старший) ТФ как фильтр направления (4h→1h→15m).
    # Вход только если СТАРШАЯ степень согласна по направлению (фрактальная вложенность волн).
    _dir_at = None
    if dir_tf:
        dfd = _load(conn, sym, dir_tf)
        if dfd is not None and len(dfd) >= 100:
            _dts = [(h["choch_ts"], h["direction"]) for h in find_setups_zz(zigzag_atr(dfd), dfd)]
            def _dir_at(ts, _dts=_dts):
                d = None
                for hts, hd in _dts:
                    if hts <= ts: d = hd
                    else: break
                return d
    try:
        wt1 = calculate_wt(df1.copy())["wt1"].values
    except Exception:
        return []
    wt1_s = pd.Series(wt1, index=df1.index)
    # ИСПРАВЛЕНО 22.06: направление ОТ СТРУКТУРЫ (CHoCH/BOS) + HTF-опора (df1=старший ТФ),
    # НЕ от WT-зоны (была перевёрнутая логика — см. MAGIC). WT = подтверждение.
    zz15 = zigzag_atr(df15)
    setups = find_setups_zz(zz15, df15)
    if not setups: return []
    htf_setups = find_setups_zz(zigzag_atr(df1), df1)
    if not htf_setups: return []
    posL = {ts: i for i, ts in enumerate(df15.index)}
    # типизированные пивоты зигзага 15m с барными индексами (для структурного трейла HL/LH)
    typed15 = [(posL.get(ts), p, t) for ts, p, t in _zz_typed(zz15) if posL.get(ts) is not None]
    LAGc = 5  # lag подтверждения зигзага (depth=11 → length=5 баров) — без lookahead
    # SMC-КОНФЛЮЕНЦИЯ (предвычисление на ТФ входа): SC(истинный разворот) + FVG(направление импульса)
    try:    _scs = detect_sponsored_candle(df15)
    except Exception: _scs = []
    try:    _fvgs = detect_fvg(df15)
    except Exception: _fvgs = []
    # WT + ДИВЕРГЕНЦИЯ на ТФ входа (поправка Егора: WT-экстремум на ДНЕ волны1, не на сломе)
    from core.indicators.divergence_detector import DivergenceDetector
    _dd = DivergenceDetector()
    df15w = df15.copy()
    try:    df15w["wt1"] = calculate_wt(df15)["wt1"].values
    except Exception: df15w["wt1"] = 0.0
    _wt15 = df15w["wt1"].values
    lo = df15["low"].values; hi = df15["high"].values; cl = df15["close"].values; n = len(df15)
    out = []
    used = set()
    # HTF-направление как функция времени: для слома берём ПОСЛЕДНИЙ HTF-слом ДО него
    htf_dir_ts = [(h["choch_ts"], h["direction"]) for h in htf_setups]
    def _htf_dir_at(ts):
        d = None
        for hts, hd in htf_dir_ts:
            if hts <= ts: d = hd
            else: break
        return d
    for s in setups:
        D = s["direction"]                        # ← ОТ СТРУКТУРЫ
        if _htf_dir_at(s["choch_ts"]) != D:       # MTF-опора: только ПО старшему ТФ (зона)
            continue
        if _dir_at is not None and _dir_at(s["choch_ts"]) != D:   # МУЛЬТИСТРУКТУРА: + старшая степень
            continue
        if True:
            ci = posL.get(s["choch_ts"])
            if ci is None or ci in used: continue
            # ВХОД = касание 0.618 (основной уровень коррекции Егора, «среднее для фиб»).
            # SL = Strong Low (levels[1.0]).
            e618 = s["levels"][0.62]
            ei = None
            for j in range(ci + 1, min(ci + 1 + 60, n)):
                if (lo[j] <= e618) if D == "long" else (hi[j] >= e618): ei = j; break
            if ei is None: continue
            used.add(ci)
            entry = e618
            slv = s["levels"][1.0] * (1 - BUF) if D == "long" else s["levels"][1.0] * (1 + BUF)
            risk = abs(entry - slv)
            if risk <= 0: continue
            fee = RT / (risk / entry * 100)
            x_end = min(ei + MAXHOLD, n - 1)
            imp_from = s["from"][1]; imp_to = s["to"][1]

            def slhit(j, slp): return (hi[j] >= slp) if D == "short" else (lo[j] <= slp)
            def closeR(): return ((entry - cl[x_end]) if D == "short" else (cl[x_end] - entry)) / risk
            res = {}
            # tp1
            r = None
            for j in range(ei, x_end + 1):
                if slhit(j, slv): r = -1.0; break
                if ((lo[j] <= entry - risk) if D == "short" else (hi[j] >= entry + risk)): r = 1.0; break
            res["tp1"] = (r if r is not None else closeR()) - fee
            # fib−0.62 (k=1.618) и fib−1 (k=2.0) — цели-расширения МЕТОДА (measured move как JASMY 0.0055)
            for kx, nm in ((1.618, "fib-0.62"), (2.0, "fib-1")):
                tgt = imp_from + kx * (imp_to - imp_from); r = None
                for j in range(ei, x_end + 1):
                    if slhit(j, slv): r = -1.0; break
                    if ((lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)):
                        r = ((entry - tgt) if D == "short" else (tgt - entry)) / risk; break
                res[nm] = (r if r is not None else closeR()) - fee
            # opp_choch: держать до противоположного слома 15m / SL
            opp = "long" if D == "short" else "short"; xi = None
            for s2 in setups:
                if s2["direction"] == opp:
                    j2 = posL.get(s2["choch_ts"])
                    if j2 is not None and j2 > ei: xi = j2; break
            xe2 = min(xi, x_end) if xi is not None else x_end; r = None
            for j in range(ei, xe2 + 1):
                if slhit(j, slv): r = -1.0; break
            res["opp_choch"] = (r if r is not None else (((entry - cl[xe2]) if D == "short" else (cl[xe2] - entry)) / risk)) - fee
            # wt_opp: держать пока 1h WT дойдёт до ПРОТИВОПОЛОЖНОЙ зоны (long→OB, short→OS) / SL
            r = None
            for j in range(ei, x_end + 1):
                if slhit(j, slv): r = -1.0; break
                wv = wt1_s.asof(df15.index[j])
                if pd.notna(wv) and ((wv >= OB) if D == "long" else (wv <= OS)):
                    r = ((cl[j] - entry) if D == "long" else (entry - cl[j])) / risk; break
            res["wt_opp"] = (r if r is not None else closeR()) - fee
            # hybrid
            ds = "LONG" if D == "long" else "SHORT"; prof = TSL_PROFILES.get("ote_nested")
            cur = slv; r = None
            for j in range(ei, x_end + 1):
                if (hi[j] >= cur) if D == "short" else (lo[j] <= cur):
                    r = ((entry - cur) if D == "short" else (cur - entry)) / risk; break
                dec = compute_hybrid_tsl(ds, entry, cl[j], slv, duration_minutes=(j - ei) * tfm, profile=prof)
                if dec.new_sl and dec.new_sl > 0:
                    cur = min(cur, dec.new_sl) if D == "short" else max(cur, dec.new_sl)
            res["hybrid"] = (r if r is not None else closeR()) - fee
            # ВЫХОД К МАГНИТУ (варианты): ближайший + макс-gravity-score + HTF-конфлюентный
            mwin = df15.iloc[max(0, ei - 120):ei + 1]
            mags = _magnets(mwin, entry, D, imp_from, imp_to)
            # HTF-магниты (df1=zone_tf): цели СТАРШЕГО ТФ — FVG/OB/EQH/swing/fib-расширение HTF.
            # «выход по магниту конфлюентный с HTF либо по структуре старшего ТФ» (Егор 22.06)
            ts_e = df15.index[ei]
            h_at = None
            for h in htf_setups:
                if h["choch_ts"] <= ts_e: h_at = h
                else: break
            htf_win = df1[df1.index <= ts_e].iloc[-150:]
            h_if = h_at["from"][1] if h_at else imp_from
            h_it = h_at["to"][1] if h_at else imp_to
            mags_htf = _magnets(htf_win, entry, D, h_if, h_it) if len(htf_win) >= 20 else []
            if mags:
                near = min(mags, key=lambda m: abs(m[0] - entry))[0]
                def _sc(m):
                    dd = abs(m[0] - entry) / entry * 100
                    return m[1] / (dd ** 1.5) if dd > 0.05 else 0.0
                best = max(mags, key=_sc)[0]
                # magnet_rr: ближайший ЗНАЧИМЫЙ магнит с RR≥1.5 (не микро впритык); иначе fib-1.618
                rr_cands = [m[0] for m in mags if abs(m[0] - entry) >= 1.5 * risk]
                if rr_cands:
                    near_rr = min(rr_cands, key=lambda p: abs(p - entry))
                else:
                    near_rr = imp_from + 1.618 * (imp_to - imp_from)
                x_mag = min(ei + int(2 * 1440 / tfm), x_end)   # time-stop 2 дня — магнит близкий, не висеть
                for nm, tgt in (("magnet_near", near), ("magnet_score", best), ("magnet_rr", near_rr)):
                    r = None; xj = x_mag
                    for j in range(ei, x_mag + 1):
                        if slhit(j, slv): r = -1.0; xj = j; break
                        if ((lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)):
                            r = ((entry - tgt) if D == "short" else (tgt - entry)) / risk; xj = j; break
                    if r is None:   # time-stop: выход по close на x_mag
                        r = ((entry - cl[x_mag]) if D == "short" else (cl[x_mag] - entry)) / risk
                    res[nm] = r - fee
                    if nm == "magnet_score":
                        res["e_ts"] = df15.index[ei]; res["x_ts"] = df15.index[xj]; res["R"] = res["magnet_score"]
                # ── magnet_htf: ВЫХОД ПО HTF-СТРУКТУРЕ (Егор: «R1 смешно при таком входе») ──
                # цель = HTF-магнит, конфлюентный с LTF (boost ×1.5 если рядом LTF-магнит),
                # ближайший ПО ХОДУ с RR≥1.5; нет HTF-кандидата → дальний HTF fib-1.618. Time-stop полный.
                TOLc = 0.004 * entry
                htf_conf = []
                for ph, wh in mags_htf:
                    if (ph > entry) if D == "long" else (ph < entry):
                        boost = 1.5 if any(abs(pl - ph) <= TOLc for pl, _ in mags) else 1.0
                        htf_conf.append((ph, wh * boost))
                htf_rr = [p for p, _ in htf_conf if abs(p - entry) >= 1.5 * risk]
                if htf_rr:
                    tgt_htf = min(htf_rr, key=lambda p: abs(p - entry))
                else:
                    tgt_htf = h_if + 1.618 * (h_it - h_if)
                r = None
                for j in range(ei, x_end + 1):
                    if slhit(j, slv): r = -1.0; break
                    if ((lo[j] <= tgt_htf) if D == "short" else (hi[j] >= tgt_htf)):
                        r = ((entry - tgt_htf) if D == "short" else (tgt_htf - entry)) / risk; break
                if r is None: r = closeR()
                res["magnet_htf"] = r - fee
            else:
                res["magnet_near"] = res["magnet_score"] = res["magnet_htf"] = res["tp1"]
                res["e_ts"] = df15.index[ei]; res["x_ts"] = df15.index[min(ei + 96, n - 1)]; res["R"] = res["tp1"]
            # ── struct_htf: ЦЕЛЬ = СТРУКТУРА (Егор 22.06: цена идёт H-L-H-L-H пока структура
            # не сломается; следующая цель = обновление структурной точки). Держим, пока HTF
            # (zone_tf) не сделает слом ПРОТИВ позиции (opp CHoCH на df1); SL = Strong Low. ───
            opp = "long" if D == "short" else "short"
            x_struct_ts = None
            for h in htf_setups:
                if h["choch_ts"] > ts_e and h["direction"] == opp:
                    x_struct_ts = h["choch_ts"]; break
            xs = min(int(df15.index.searchsorted(x_struct_ts)), x_end) if x_struct_ts is not None else x_end
            r = None
            for j in range(ei, xs + 1):
                if slhit(j, slv): r = -1.0; break
            if r is None:
                r = ((entry - cl[xs]) if D == "short" else (cl[xs] - entry)) / risk
            res["struct_htf"] = r - fee
            # ── struct_trail (Егор 22.06): SL под HL, ПОДТВЕРЖДЁННЫЙ следующим HH.
            # «HL без HH не структурная точка и может быть выбит» → перенос SL ТОЛЬКО после
            # нового HH (для long) / LL (для short). Активация с lag зигзага (без lookahead). ──
            updates = []   # (activation_bar, sl_level)
            if D == "long":
                prev_H = imp_to; pend_L = None
                for (pi, pp, pt) in typed15:
                    if pi is None or pi <= ei: continue
                    if pt == "L":
                        pend_L = pp
                    elif pp > prev_H:                       # HH подтверждает pend_L как HL
                        if pend_L is not None and pend_L > slv:
                            updates.append((pi + LAGc, pend_L))
                        prev_H = pp; pend_L = None
            else:
                prev_L = imp_to; pend_H = None
                for (pi, pp, pt) in typed15:
                    if pi is None or pi <= ei: continue
                    if pt == "H":
                        pend_H = pp
                    elif pp < prev_L:                       # LL подтверждает pend_H как LH
                        if pend_H is not None and pend_H < slv:
                            updates.append((pi + LAGc, pend_H))
                        prev_L = pp; pend_H = None
            updates.sort()
            sl_t = slv; ui = 0; r = None
            for j in range(ei, x_end + 1):
                while ui < len(updates) and updates[ui][0] <= j:
                    sl_t = max(sl_t, updates[ui][1]) if D == "long" else min(sl_t, updates[ui][1])
                    ui += 1
                if (lo[j] <= sl_t) if D == "long" else (hi[j] >= sl_t):
                    r = ((sl_t - entry) if D == "long" else (entry - sl_t)) / risk; break
            if r is None: r = closeR()
            res["struct_trail"] = r - fee
            # ── imp_tsl (Егор 22.06, вариант B): TSL включается ПОСЛЕ первого HH (цена прошла
            # выше импульсного swing) — «забираем импульс», далее вход на коррекции следующего. ──
            ds2 = "LONG" if D == "long" else "SHORT"; prof2 = TSL_PROFILES.get("ote_nested")
            cur2 = slv; r = None; hh = False
            for j in range(ei, x_end + 1):
                if (hi[j] >= cur2) if D == "short" else (lo[j] <= cur2):
                    r = ((entry - cur2) if D == "short" else (cur2 - entry)) / risk; break
                if not hh and ((hi[j] > imp_to) if D == "long" else (lo[j] < imp_to)):
                    hh = True
                if hh:
                    dec = compute_hybrid_tsl(ds2, entry, cl[j], slv, duration_minutes=(j - ei) * tfm, profile=prof2)
                    if dec.new_sl and dec.new_sl > 0:
                        cur2 = min(cur2, dec.new_sl) if D == "short" else max(cur2, dec.new_sl)
            if r is None: r = closeR()
            res["imp_tsl"] = r - fee
            # ГЛУБИНА коррекции (инсайт Егора: мелкая=сильный импульс, глубокая=вялый)
            rng = abs(imp_to - imp_from)
            if D == "long":
                mn = lo[ci:ei + 1].min() if ei > ci else lo[ei]
                res["depth"] = (imp_to - mn) / rng if rng > 0 else 0
            else:
                mx = hi[ci:ei + 1].max() if ei > ci else hi[ei]
                res["depth"] = (mx - imp_to) / rng if rng > 0 else 0
            # ── wave3 (ЭТАП 1, Elliott-движок): вход = конец ВОЛНЫ 2 (CHoCH-импульс=волна1 +
            # здоровый откат 0.5-0.7), цель = ВОЛНА 3 = entry + 1.618×|волна1| (measured move). ──
            fc = forecast_wave3(imp_from, imp_to, entry, D, s.get("kind", ""), depth=res["depth"])
            res["kind"] = s.get("kind", "")
            res["is_wave2"] = bool(fc and fc.confidence >= 1.0)   # CHoCH И здоровая глубина
            res["wave3_pot"] = fc.potential_r if fc else 0.0
            # Этап 2: качество волны 1 — РЕЗКОСТЬ (импульс vs диагональ) + позиция (legs от разворота)
            _fi = posL.get(s["from"][0]); _ti = posL.get(s["to"][0])
            _w1b = abs(_ti - _fi) if (_fi is not None and _ti is not None) else 0
            res["w1_slope"] = impulse_sharpness(rng / entry * 100, _w1b)
            res["legs"] = count_legs_since(typed15, _fi if _fi is not None else 0,
                                           _ti if _ti is not None else 0, D)
            # SMC-КОНФЛЮЕНЦИЯ (Этап 2.5): подтверждение разворота=волны1 + силы импульса
            _scd = "bull" if D == "long" else "bear"
            res["sc_conf"] = int(any(_sc.confirmed and _sc.direction == _scd
                                     and (ci - 12 <= _sc.idx <= ci + 3) for _sc in _scs))   # истинный разворот
            _ft = s["from"][0]; _ct = s["choch_ts"]
            res["fvg_dir"] = int(any(((fv[3] == "bull") == (D == "long")) and (_ft <= fv[4] <= _ct)
                                     for fv in _fvgs))                                       # имбаланс в импульсе в1
            # WT-экстремум на ДНЕ волны1 (поправка Егора 22.06: слом ПОСЛЕ выхода WT из зоны;
            # экстремум был на дне=точке разворота `from`, НЕ на choch).
            _fpos = _fi if _fi is not None else ci
            _wlo = _wt15[max(0, _fpos - 3):min(_fpos + 4, n)]
            res["wt_ext"] = int(len(_wlo) and (_wlo.min() <= OS if D == "long" else _wlo.max() >= OB))
            # ДИВЕРГЕНЦИЯ на развороте (бычья long / медвежья short на дне волны1 = подтверждение в1)
            res["div_rev"] = 0
            _seg = df15w.iloc[:_fpos + 4]
            if len(_seg) > 35:
                try:
                    _dv = (_dd.detect_regular_bullish(_seg, "wt1") if D == "long"
                           else _dd.detect_regular_bearish(_seg, "wt1"))
                    res["div_rev"] = int(_dv is not None)
                except Exception: pass
            res["confl"] = res["sc_conf"] + res["fvg_dir"] + res["wt_ext"] + res["div_rev"]
            if fc:
                tgt = fc.target; r = None
                for j in range(ei, x_end + 1):
                    if slhit(j, slv): r = -1.0; break
                    if ((lo[j] <= tgt) if D == "short" else (hi[j] >= tgt)):
                        r = ((entry - tgt) if D == "short" else (tgt - entry)) / risk; break
                if r is None: r = closeR()
                res["wave3"] = r - fee
            else:
                res["wave3"] = res["tp1"]
            # mfe
            mfe = 0.0
            for j in range(ei, x_end + 1):
                fav = ((entry - lo[j]) if D == "short" else (hi[j] - entry)) / risk
                mfe = max(mfe, fav)
                if slhit(j, slv): break
            res["mfe"] = mfe; res["dir"] = D; res["ts"] = df15.index[ei]
            out.append(res)
            # (без break — собираем ВСЕ сетапы пары для бэктеста; used предотвращает дубли ci)
    return out


def net_of(rows, key):
    vals = [r[key] for r in rows if key in r]; nn = len(vals)
    if not nn: return None
    return {"n": nn, "net": round(sum(vals) / nn, 3), "wr": round(100 * sum(1 for x in vals if x > 0) / nn)}


def portfolio_sim(trades, start=500.0, risk_pct=0.01, max_conc=50):
    """РЕАЛИСТИЧНО: $start, риск risk_pct/сделку, макс max_conc параллельных позиций.
    Капитал занят от e_ts до x_ts; если все слоты заняты — сделка пропущена (нет места)."""
    evs = []
    for t in trades:
        if all(k in t for k in ("e_ts", "x_ts", "R")):
            evs.append((t["e_ts"], 0, id(t), t))   # entry (0 = первым при равном ts → слот откроется)
            evs.append((t["x_ts"], 1, id(t), t))   # exit (1 = после входа)
    evs.sort(key=lambda x: (x[0], x[1]))
    bal = start; peak = start; mdd = 0.0; open_n = 0; pend = {}; taken = 0; skip = 0
    for ts, typ, tid, t in evs:
        if typ == 0:   # ВХОД
            if open_n < max_conc:
                pend[tid] = bal * risk_pct; open_n += 1; taken += 1
            else:
                skip += 1
        else:          # ВЫХОД
            if tid in pend:
                bal += t["R"] * pend.pop(tid); open_n -= 1
                if bal < 1: bal = 1.0
                peak = max(peak, bal); mdd = max(mdd, (peak - bal) / peak)
    return bal, mdd, taken, skip


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", type=int, default=0)
    ap.add_argument("--zone-tf", default="1h"); ap.add_argument("--break-tf", default="15m")
    ap.add_argument("--dir-tf", default=None, help="МУЛЬТИСТРУКТУРА: старший ТФ-фильтр направления (4h→1h→15m)")
    ap.add_argument("--map", action="store_true", help="карта по всем связкам ТФ зона→слом")
    a = ap.parse_args()
    conn = sqlite3.connect(CACHE, timeout=60)
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM ohlcv_cache WHERE timeframe='15m' ORDER BY symbol")]
    if a.pairs: syms = syms[:a.pairs]
    # ── 🗺️ КАРТА ПО ТФ: все связки зона→слом, выход magnet_score, фильтр средней глубины ──
    if a.map:
        LINKS = [("4h", "1h"), ("4h", "15m"), ("4h", "5m"), ("1h", "15m"), ("1h", "5m"), ("15m", "5m")]
        ML = ["# 🗺️ КАРТА ПО ТФ — связки зона→слом (выход=magnet_score, фильтр средней глубины 0.55-0.68)\n",
              f"> вход: WT-зона(зона-ТФ) → слом(слом-ТФ) → OTE 0.618 → ближний магнит. portfolio $500 риск1% 50парал.\n",
              "\n| зона→слом | n(всего) | n(ср.гл) | magnet net | WR | $500→ | maxDD | shadow? |",
              "|---|---|---|---|---|---|---|---|"]
        rank = []
        for ztf, btf in LINKS:
            rows = []
            for sym in syms:
                try: rows.extend(test_pair(conn, sym, ztf, btf))
                except Exception: pass
            mid = [r for r in rows if 0.55 <= r.get("depth", 1) < 0.68]
            for r in mid: r["R"] = r["magnet_score"]
            m = net_of(mid, "magnet_score")
            if not m or m["n"] < 50:
                ML.append(f"| {ztf}→{btf} | {len(rows)} | {len(mid)} | мало n | — | — | — | — |")
                print(f"[map] {ztf}→{btf}: n={len(mid)} мало", flush=True); continue
            bal, dd, tk, sk = portfolio_sim(mid, 500, 0.01, 50)
            shadow = "✅" if (m["net"] > 0 and m["wr"] >= 60) else "—"
            ML.append(f"| {ztf}→{btf} | {len(rows)} | {m['n']} | **{m['net']:+.3f}** | {m['wr']}% | ${bal:,.0f} | {round(100*dd)}% | {shadow} |")
            rank.append((m["net"], f"{ztf}→{btf}", m["wr"]))
            print(f"[map] {ztf}→{btf}: net{m['net']:+.3f} WR{m['wr']}% n{m['n']}", flush=True)
        conn.close()
        rank.sort(reverse=True)
        ML.append("\n## В SHADOW (сорт по net): " + " · ".join(f"{k}({n:+.3f},WR{w}%)" for n, k, w in rank if n > 0))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "TF_MAP.md").write_text("\n".join(ML), encoding="utf-8")
        print("\n".join(ML)); print(f"\n→ {OUT/'TF_MAP.md'}"); return
    _chain = f"{a.dir_tf}→{a.zone_tf}→{a.break_tf}" if a.dir_tf else f"{a.zone_tf}→{a.break_tf}"
    print(f"[wtzone] пар: {len(syms)} · {_chain}", flush=True)
    allr = []
    for i, sym in enumerate(syms):
        try: allr.extend(test_pair(conn, sym, a.zone_tf, a.break_tf, a.dir_tf))
        except Exception: pass
        if (i + 1) % 50 == 0: print(f"[wtzone] {i+1}/{len(syms)} | {len(allr)}", flush=True)
    conn.close()
    L = [f"# МЕТОД ЕГОРА — вход от WT-ЗОНЫ 1h (первично) → слом 15m → OTE → полёт — {len(allr)} сделок\n",
         f"> выходы: tp1 · fib1.618 · opp_choch · wt_opp(противопол.WT-зона) · hybrid. SL=импульс-1.0. комса {RT}%.\n",
         "\n## ИТОГ по политике (R + $ компаунд риск1%)\n| политика | n | net E[R] | WR | $×старт | maxDD | max R |\n|---|---|---|---|---|---|---|"]
    for p in POLICIES:
        m = net_of(allr, p)
        if not m: continue
        bal = 1000.0; peak = 1000.0; mdd = 0.0
        for r in sorted(allr, key=lambda x: x["ts"]):
            if p not in r: continue
            bal += r[p] * (bal * 0.01); bal = max(bal, 0.01)
            peak = max(peak, bal); mdd = max(mdd, (peak - bal) / peak)
        mx = max((r[p] for r in allr if p in r), default=0)
        flag = "🟢" if m["net"] > 0 else "🔴"
        L.append(f"| {p} | {m['n']} | **{m['net']:+.3f}** {flag} | {m['wr']}% | ×{bal/1000:.1f} | {round(100*mdd)}% | {mx:+.1f} |")
    # по направлению
    L.append("\n## по направлению (fib-1 / tp1 / wt_opp)\n| dir | n | fib-1 | tp1 | wt_opp |\n|---|---|---|---|---|")
    for D in ("long", "short"):
        sub = [r for r in allr if r["dir"] == D]
        if len(sub) < 20: continue
        mw = net_of(sub, "wt_opp"); mt = net_of(sub, "tp1"); mf = net_of(sub, "fib-1")
        L.append(f"| {D} | {len(sub)} | **{mf['net']:+.3f}**({mf['wr']}%) | {mt['net']:+.3f} | {mw['net']:+.3f} |")
    # 🔬 СПЛИТ ПО ГЛУБИНЕ КОРРЕКЦИИ (инсайт Егора: мелкая=сильный импульс=дальше едет)
    L.append("\n## 🔬 ГЛУБИНА коррекции = СИЛА импульса? (net по глубине + сравнение ВЫХОДОВ)\n"
             "| глубина | n | magnet_near | struct_trail | imp_tsl | magnet_htf | MFE медиана | ≥10R |\n"
             "|---|---|---|---|---|---|---|---|")
    for lab, lo_d, hi_d in [("мелкая ≤0.55", 0.0, 0.55), ("средняя 0.55-0.68", 0.55, 0.68), ("глубокая >0.68", 0.68, 9.0)]:
        sub = [r for r in allr if "depth" in r and lo_d <= r["depth"] < hi_d]
        if len(sub) < 30: continue
        mn = net_of(sub, "magnet_near"); mtr = net_of(sub, "struct_trail")
        mit = net_of(sub, "imp_tsl"); mh = net_of(sub, "magnet_htf")
        md = np.array([r["mfe"] for r in sub])
        def _c(m): return f"{m['net']:+.3f}({m['wr']}%)" if m else "—"
        L.append(f"| {lab} | {len(sub)} | **{_c(mn)}** | {_c(mtr)} | {_c(mit)} | {_c(mh)} | {np.median(md):.2f} | {round(100*(md>=10).mean(),1)}% |")
    # 🌊 ВОЛНОВОЙ ФИЛЬТР (Elliott Этап 1): is_wave2 (CHoCH + откат 0.5-0.7) → цель волна3 (1.618)
    L.append("\n## 🌊 ВОЛНОВОЙ ФИЛЬТР (Elliott Этап 1) — поднимает ли MFE отбор «волна 2»?\n"
             "| выборка | n | MFE медиана | ≥3R | wave3 net | wave3 WR | magnet_near | потенц.медиана |\n"
             "|---|---|---|---|---|---|---|---|")
    _w2all = [r for r in allr if r.get("is_wave2")]
    _msl = float(np.median([r["w1_slope"] for r in _w2all])) if _w2all else 0.0
    _clean = [r for r in _w2all if r.get("w1_slope", 0) >= _msl and r.get("legs", 9) <= 1]
    _ideal = [r for r in _clean if r.get("confl", 0) >= 2]
    for lab, sub in [("ВСЕ сетапы", allr),
                     ("CHoCH (любая глуб.)", [r for r in allr if r.get("kind") == "CHoCH"]),
                     ("is_wave2 (CHoCH+гл.0.5-0.7)", _w2all),
                     (f"CLEAN (+резкая в1≥{_msl:.2f}+legs≤1)", _clean),
                     ("IDEAL (CLEAN+конфлюенция≥2)", _ideal)]:
        if len(sub) < 30:
            L.append(f"| {lab} | {len(sub)} | мало n | | | | | |"); continue
        md = np.array([r["mfe"] for r in sub])
        w3 = net_of(sub, "wave3"); mn = net_of(sub, "magnet_near")
        pot = np.median([r.get("wave3_pot", 0) for r in sub])
        L.append(f"| {lab} | {len(sub)} | **{np.median(md):.2f}** | {round(100*(md>=3).mean())}% | "
                 f"{w3['net']:+.3f} | {w3['wr']}% | {mn['net']:+.3f}({mn['wr']}%) | {pot:.1f}R |")
    # вклад КАЖДОГО признака конфлюенции (на is_wave2): что несёт?
    L.append("\n### вклад признаков конфлюенции (на is_wave2)\n"
             "| признак | n | MFE медиана | magnet_near | wave3 |\n|---|---|---|---|---|")
    for fl in ("sc_conf", "fvg_dir", "wt_ext", "div_rev"):
        sub = [r for r in _w2all if r.get(fl)]
        if len(sub) < 30:
            L.append(f"| {fl} | {len(sub)} | мало n | | |"); continue
        md = np.median([r["mfe"] for r in sub]); mn = net_of(sub, "magnet_near"); w3 = net_of(sub, "wave3")
        L.append(f"| {fl} | {len(sub)} | **{md:.2f}** | {mn['net']:+.3f}({mn['wr']}%) | {w3['net']:+.3f} |")
    # 💵 РЕАЛИСТИЧНАЯ PORTFOLIO-СИМ ($500, риск1%, макс 50 параллельно) — выход magnet_score
    L.append("\n## 💵 РЕАЛЬНЫЕ $ — portfolio $500, риск 1%/сделку, макс 50 параллельных, выход=magnet_score")
    L.append("| вариант | n взято | финал $ | × | maxDD |\n|---|---|---|---|---|")
    allm = [r for r in allr if "e_ts" in r]
    b, d, tk, sk = portfolio_sim(allm, 500, 0.01, 50)
    L.append(f"| ВСЕ глубины | {tk}/{tk+sk} | ${b:,.0f} | ×{b/500:.1f} | {round(100*d)}% |")
    mid = [r for r in allm if 0.55 <= r.get("depth", 1) < 0.68]
    for r in mid: r["R"] = r["magnet_score"]
    b2, d2, tk2, sk2 = portfolio_sim(mid, 500, 0.01, 50)
    L.append(f"| СРЕДНЯЯ гл. 0.55-0.68 (фильтр) | {tk2}/{tk2+sk2} | ${b2:,.0f} | ×{b2/500:.1f} | {round(100*d2)}% |")
    L.append(f"\n> период данных ≈ 4.4 года. Реальный $ ниже множителя ×N из-за лимита 50 параллельных + занятости капитала.")
    mfe = np.array([r["mfe"] for r in allr]) if allr else np.array([0])
    L.append(f"\nMFE медиана {np.median(mfe):.2f}R · ≥3R {round(100*(mfe>=3).mean())}% · ≥10R {round(100*(mfe>=10).mean(),1)}% · max {mfe.max():.0f}R")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L)); print(f"\n→ {OUT/'RESULTS.md'}")


if __name__ == "__main__":
    main()
