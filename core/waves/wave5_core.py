"""Детектор пятиволнового импульса на двухслойном эталоне OKO-SM + правила ядра.

Каузальность: разметка на последнем ЗАКРЫТОМ баре старшего ТФ; все точки, кроме пятой, —
подтверждённые свинги (`_swings`), пятая — текущий экстремум после последнего свинга (provisional).
Поля ядра (все известны в момент решения):
  fractal   — младшие сломы по направлению внутри волн 1 и 3, bos3 ≥ bos1 (импульс настоящий)
  depth5    — глубина пятой в канале Эллиотта (линия 2-4 + параллель через 3): ≥0.5 = импульс завершён
  altern    — чередование волн 2 и 4 по типу (глубина×время) и по форме (сложность по подсвингам)
  count_ok  — нет сдвинутого на два свинга счёта с более канонической третьей (не подволны)
  d_*       — дневной контекст (1D ресемплом из HTF): структура, пробой дневного свинга, WT 1D
  фибо-прогноз: цели пятой (5=0.618/1/1.618 × 1, параллель канала) и цели коррекции (w4, 0.382/0.5/0.618)
Измерено 2023-2026 (memory/wave5_core_oko_sm.md): лонг line24 полный набор 19/год WR 75% цель 66%;
кросс 34/год R 1.1; шорт только как коррекция дневного даун-тренда (6/год, WR 60%).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.smc.oko_sm_engine import run_structure, _swings          # эталонный двухслойный движок структуры
from core.indicators.indicators import calculate_wt                 # штатный WT (10/21/4)
from core.trading.source_registry import _TF_MIN as TF_MIN         # минуты в баре — единый словарь проекта

# 🔴 ПЕРЕИСПОЛЬЗОВАНИЕ (проверка 14.09): в проекте уже есть волновой детектор `core.smc.smc_engine.
# detect_elliott_impulse` (зигзаг ATR, depth 11) — на нём построена матрица признаков (augment_snap,
# swing_bridge). Он НЕ заменяется: замена = перемер всей матрицы. Этот модуль — второй детектор, на свингах
# OKO-SM (канон побил зигзаг: memory/elliott_canon_beats_my_proxy.md, wave5_core_oko_sm.md). Сфера Куба
# `core.intelligence.wave_service.WaveService` считает фазу N-up/N-down и current_leg на том же движке —
# подключение сетапов этого модуля к сфере (публикация в шину) — отдельная ARCH-задача.


@dataclass
class WaveParams:
    sw: int = 15            # свинг старшего слоя (бары HTF); рабочий масштаб ~60-80 ч (4h: 15)
    il: int = 4             # младший слой (≈ sw/4)
    z: float = 45.0         # зона WT на вершине пятой: |wt1| > z
    min_imp: float = 3.0    # импульс, % хода
    max_imp: float = 100.0
    ctx_sw: int = 10        # дневные свинги (дней) для контекста степени
    buf: float = 0.0015     # буфер стопа за экстремум пятой
    merge: bool = False     # поглощение подструктуры свингов (collapse_swings) — см. impulses_on_bar


def _fix_same_kind(pool):
    """Два соседних свинга одного типа (top,top / low,low) → остаётся более крайний."""
    pool = list(pool); i = 0
    while i < len(pool) - 1:
        a, b = pool[i], pool[i + 1]
        if a[3] == b[3]:
            pool[i:i + 2] = [b if ((b[2] >= a[2]) if a[3] else (b[2] <= a[2])) else a]
        else:
            i += 1
    return pool


def _inner_pairs(pool, tail):
    """Пары соседних свингов (i, i+1), целиком лежащие в диапазоне своих соседей (i-1, i+2) — волна
    младшей степени внутри старшей. Только в хвосте (i ≥ len-tail): поглощение раньше не меняет последние 5.
    Возвращает [(размах пары, i)] — самая мелкая пара первая."""
    out = []
    for i in range(max(1, len(pool) - tail), len(pool) - 2):
        a, b, c, d = pool[i - 1], pool[i], pool[i + 1], pool[i + 2]
        lo, hi = min(a[2], d[2]), max(a[2], d[2])
        if lo <= b[2] <= hi and lo <= c[2] <= hi:
            out.append((abs(b[2] - c[2]), i))
    return sorted(out)


def impulses_on_bar(swings, t, high, low, merge=False, pool_n=16, max_absorb=6):
    """Кандидаты 5-волновых импульсов на баре t: 5 подтверждённых свингов + provisional точка 5.
    merge=True (Егор 14.09, LINK 4h: «пятёрку не видит из-за сложной w4»): если последние 5 свингов
    «как есть» не импульс — поглощать подструктуру ПО ОДНОЙ паре (самая мелкая в хвосте первой) и после
    каждого шага проверять счёт заново; стоп на первом валидном. Минимальность важна: 1-2 тоже лежат
    внутри 0→3, жадное поглощение съедает их. Счёт без поглощений в приоритете — старые сетапы не меняются."""
    conf = [s for s in swings if s[0] <= t]
    if len(conf) < 5:
        return []
    out = _five(conf[-5:], t, high, low)
    if out or not merge:
        return out
    pool = _fix_same_kind(conf[-pool_n:]); gone = 0
    while len(pool) >= 5 and gone < max_absorb:
        pairs = _inner_pairs(pool, tail=6)
        if not pairs:
            return []
        i = pairs[0][1]; del pool[i:i + 2]; gone += 2
        out = _five(pool[-5:], t, high, low)
        if out:
            for o in out:
                o["absorbed"] = gone
            return out
    return []


def _five(last5, t, high, low):
    kinds = [s[3] for s in last5]
    if any(kinds[i] == kinds[i + 1] for i in range(4)):
        return []
    idx = [s[1] for s in last5]; px = [s[2] for s in last5]
    li = idx[-1]
    if li >= t:
        return []
    seg_h, seg_l = high[li + 1:t + 1], low[li + 1:t + 1]
    if last5[-1][3]:                                   # последний = top → импульс ВНИЗ, точка 5 = low
        p5i = li + 1 + int(seg_l.argmin()); p5 = float(seg_l.min())
        if p5 >= px[-1] or kinds != [True, False, True, False, True]:
            return []
        p0, p1, p2, p3, p4 = px
        if not (p1 < p0 and p2 < p0 and p3 < p1 and p4 < p1 and p5 < p3):   # R1, R3
            return []
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
        direction = "down"
    else:
        p5i = li + 1 + int(seg_h.argmax()); p5 = float(seg_h.max())
        if p5 <= px[-1] or kinds != [False, True, False, True, False]:
            return []
        p0, p1, p2, p3, p4 = px
        if not (p1 > p0 and p2 > p0 and p3 > p1 and p4 > p1 and p5 > p3):
            return []
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
        direction = "up"
    if l3 < l1 and l3 < l5:                            # R2: третья не самая короткая
        return []
    w_idx = idx + [p5i]; w_px = px + [p5]
    return [dict(waves=list(zip(w_idx, w_px)), direction=direction, lens=(l1, l3, l5),
                 w2_retr=abs(p2 - p1) / l1 if l1 else 0, w4_retr=abs(p4 - p3) / l3 if l3 else 0,
                 w3_ext=l3 / l1 if l1 else 0)]


def fractal_check(events, w_idx, up_imp, t):
    """Младшие сломы (CHoCH+BOS) по направлению внутри волн 1 и 3, только ev.i ≤ t."""
    ev = [e for e in events if e.i <= t and w_idx[0] <= e.i <= w_idx[5]]

    def seg(k):
        a, b = w_idx[k], w_idx[k + 1]
        return [e for e in ev if a < e.i <= b]

    def n_dir(es):
        return sum(1 for e in es if e.internal and e.bull == up_imp)
    b1, b3 = n_dir(seg(0)), n_dir(seg(2))
    return dict(fractal_ok=bool(b1 >= 1 and b3 >= 1 and b3 >= b1), bos1=b1, bos3=b3)


def depth5_of(w_idx, w_px, up):
    """Глубина точки 5 в канале Эллиотта: 0 — на базовой линии 2-4, 1 — на параллели через 3."""
    xi = [float(v) for v in w_idx]; px = [float(v) for v in w_px]; sgn = 1.0 if up else -1.0
    slope = (px[4] - px[2]) / (xi[4] - xi[2]) if xi[4] > xi[2] else 0.0
    width = sgn * (px[3] - (px[2] + slope * (xi[3] - xi[2])))
    depth = sgn * (px[5] - (px[4] + slope * (xi[5] - xi[4])))
    return depth / width if width > 0 else float("nan")


def mark_impulse(dh: pd.DataFrame, now: Optional[pd.Timestamp] = None, p: WaveParams = WaveParams(),
                 tf: str = "4h", lookback: int = 0) -> List[Dict[str, Any]]:
    """Разметка на последнем закрытом баре HTF. dh: OHLCV с DatetimeIndex (UTC), только ЗАКРЫТЫЕ бары.
    Возвращает список сетапов (обычно 0-1) со всеми полями ядра, без LTF-статуса (см. ltf_status).
    lookback>0 (монитор): если на последнем баре сетапа нет — искать на предыдущих барах до lookback назад
    и вернуть самый свежий (каузально: на баре tt видны только свинги/события, подтверждённые к tt)."""
    now = now or pd.Timestamp.utcnow()
    if len(dh) < 6 * p.sw + 50:
        return []
    idx_h = dh.index; hh, lh = dh.high.values.astype(float), dh.low.values.astype(float)
    dhr = dh.reset_index(drop=True); t = len(dhr) - 1
    st = run_structure(dhr[["open", "high", "low", "close"]], swing_len=p.sw, internal_len=p.il)
    swings = _swings(dhr["high"], dhr["low"], p.sw); swings_i = _swings(dhr["high"], dhr["low"], p.il)
    wt1_h = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    # дневной контекст из HTF-ресемпла (только закрытые дни)
    dd = dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    dd = dd[dd.index + pd.Timedelta(days=1) <= now]
    have_ctx = len(dd) > p.ctx_sw * 3
    d_ev = [e for e in run_structure(dd, swing_len=p.ctx_sw, internal_len=3).events if not e.internal] if have_ctx else []
    d_sw = _swings(dd["high"], dd["low"], p.ctx_sw) if have_ctx else []
    d_wt = calculate_wt(dd.copy())["wt1"].values.astype(float) if len(dd) > 30 else np.array([np.nan])
    tfm = TF_MIN[tf]
    out = []
    for tt in range(t, max(t - lookback, 0) - 1, -1):
        out = _setups_at(tt, dh, idx_h, hh, lh, st, swings, swings_i, wt1_h, d_ev, d_sw, d_wt, tfm, now, p, tf)
        if out:
            break
    return out


def _setups_at(t, dh, idx_h, hh, lh, st, swings, swings_i, wt1_h, d_ev, d_sw, d_wt, tfm, now, p, tf):
    out = []
    for imp in impulses_on_bar(swings, t, hh, lh, merge=p.merge):
        w = imp["waves"]; w_idx = [int(x[0]) for x in w]; w_px = [float(x[1]) for x in w]
        a, b = w_idx[0], w_idx[5]; p0, p4, p5 = w_px[0], w_px[4], w_px[5]; up = imp["direction"] == "up"
        rng = abs(p5 - p0); imp_pct = rng / p0 * 100 if p0 > 0 else 0
        if not (p.min_imp <= imp_pct <= p.max_imp):
            continue
        if not np.isfinite(wt1_h[b]) or not ((wt1_h[b] > p.z) if up else (wt1_h[b] < -p.z)):
            continue
        fr = fractal_check(st.events, w_idx, up, t)
        dep = depth5_of(w_idx, w_px, up)
        ns = [sum(1 for s in swings_i if s[0] <= t and w_idx[k] < s[1] <= w_idx[k + 1]) for k in range(5)]
        t2, t4 = w_idx[2] - w_idx[1], w_idx[4] - w_idx[3]
        alt_type = (imp["w2_retr"] > imp["w4_retr"] and t2 < t4) or (imp["w2_retr"] < imp["w4_retr"] and t2 > t4)
        alt_form = abs(ns[1] - ns[3]) >= 2
        # сдвинутый счёт: 0'=s[-7], 1'=s[-6], 2'=наш 0 … — если его третья каноничнее, наш счёт = подволны
        prev = [s for s in swings if s[0] <= t and s[1] < a]; count_ok = True; alt_w3_w1 = float("nan")
        if len(prev) >= 2 and prev[-2][3] == (not up) and prev[-1][3] == up:
            p0p, p1p = float(prev[-2][2]), float(prev[-1][2]); l1p = abs(p0p - p1p)
            ok = ((p0 <= p0p) if not up else (p0 >= p0p)) and ((w_px[1] < p1p) if not up else (w_px[1] > p1p))
            alt_w3_w1 = abs(p0 - w_px[1]) / l1p if l1p else float("nan")
            count_ok = not (ok and np.isfinite(alt_w3_w1) and alt_w3_w1 >= 1.0 and alt_w3_w1 > imp["w3_ext"])
        d_bull = d_broke = None; d_wt_last = float(d_wt[-1]) if np.isfinite(d_wt[-1]) else float("nan")
        if d_ev:
            d_bull = bool(d_ev[-1].bull)
            lows = [s for s in d_sw if not s[3]]; highs = [s for s in d_sw if s[3]]
            if not up and lows: d_broke = bool(p5 < lows[-1][2])
            if up and highs: d_broke = bool(p5 > highs[-1][2])
        # линия 2-4 как функция времени (цена = ref + slope_h × часов от ref_time) и параллель канала
        x2, x4 = float(w_idx[2]), float(w_idx[4]); y2, y4 = w_px[2], w_px[4]
        slope = (y4 - y2) / (x4 - x2) if x4 > x2 else 0.0             # цена за 1 бар HTF
        slope_h = slope / (tfm / 60.0)
        x3, y3 = float(w_idx[3]), w_px[3]
        hours_now = (now - idx_h[int(x4)]).total_seconds() / 3600
        chan_now = y3 + slope_h * (hours_now - (x3 - x4) * tfm / 60.0)   # параллель через 3 на текущий момент
        sg = 1.0 if up else -1.0; w1 = abs(w_px[1] - p0)
        fib = {"w5_618": p4 + sg * 0.618 * w1, "w5_eq1": p4 + sg * 1.0 * w1, "w5_1618": p4 + sg * 1.618 * w1, "w5_chan": chan_now,
               "corr_382": p5 - sg * 0.382 * rng, "corr_500": p5 - sg * 0.5 * rng, "corr_618": p5 - sg * 0.618 * rng, "corr_w4": p4}
        core = bool(fr["fractal_ok"] and np.isfinite(dep) and dep >= 0.5)
        out.append({
            "key": f"{idx_h[a]:%Y%m%d%H}|{idx_h[w_idx[4]]:%Y%m%d%H}", "side": "SHORT" if up else "LONG", "tf": tf,
            "top_time": idx_h[b], "hours_from_top": round((now - idx_h[b]).total_seconds() / 3600, 1),
            "p0": p0, "p4_target": p4, "p5": p5, "imp_pct": round(imp_pct, 1), "wt_top": round(float(wt1_h[b]), 1),
            "w2_retr": round(imp["w2_retr"], 2), "w4_retr": round(imp["w4_retr"], 2), "w3_ext": round(imp["w3_ext"], 2),
            "fractal": bool(fr["fractal_ok"]), "bos1": fr["bos1"], "bos3": fr["bos3"], "depth5": round(dep, 2) if np.isfinite(dep) else None,
            "altern_type": bool(alt_type), "altern_form": bool(alt_form), "altern": bool(alt_type or alt_form), "ns": ns, "count_ok": bool(count_ok),
            "alt_w3_w1": round(alt_w3_w1, 2) if np.isfinite(alt_w3_w1) else None,
            "d_bull": d_bull, "d_broke": d_broke, "d_wt": round(d_wt_last, 1) if np.isfinite(d_wt_last) else None,
            "core": core, "core_full": bool(core and (alt_type or alt_form) and count_ok),
            "line_ref_time": idx_h[int(x4)], "line_ref_price": float(y4), "line_slope_h": float(slope_h),
            **{k: float(v) for k, v in fib.items()},
            "wave_idx": w_idx, "wave_px": w_px, "wave_times": [idx_h[i] for i in w_idx], "a": a, "b": b, "t": t,
            "absorbed": int(imp.get("absorbed", 0)),
        })
    return out


def wave_diag(dh: pd.DataFrame, p: WaveParams = WaveParams(), n_sw: int = 9) -> Dict[str, Any]:
    """Диагностика для монитора, когда mark_impulse ничего не нашёл: последние свинги масштаба ядра
    (зигзаг, что детектор ВИДИТ) и причина, по которой последняя пятёрка — не импульс.
    dh: закрытые бары с DatetimeIndex. Возвращает {"zz": [(time, price, is_top)…], "why": str}."""
    if len(dh) < p.sw * 2 + 5:
        return {"zz": [], "why": "мало истории"}
    dhr = dh.reset_index(drop=True); t = len(dhr) - 1
    hh, lh = dhr["high"].values.astype(float), dhr["low"].values.astype(float)
    conf = [s for s in _swings(dhr["high"], dhr["low"], p.sw) if s[0] <= t]
    zz = [(dh.index[int(s[1])], float(s[2]), bool(s[3])) for s in conf[-n_sw:]]
    if len(conf) < 5:
        return {"zz": zz, "why": "меньше 5 подтверждённых свингов"}
    last5 = conf[-5:]; kinds = [s[3] for s in last5]; px = [float(s[2]) for s in last5]; li = int(last5[-1][1])
    if any(kinds[i] == kinds[i + 1] for i in range(4)):
        return {"zz": zz, "why": "свинги не чередуются (два подряд одного типа)"}
    if li >= t:
        return {"zz": zz, "why": "последний свинг на текущем баре"}
    p0, p1, p2, p3, p4 = px
    if kinds[-1]:                                                    # top → импульс вниз, 5 = low после
        p5 = float(lh[li + 1:t + 1].min()); dn = True
        r1 = p1 < p0 and p2 < p0; w3x = p3 < p1; r3 = p4 < p1; ext = p5 < p3
        l1, l3, l5 = p0 - p1, p2 - p3, p4 - p5
    else:
        p5 = float(hh[li + 1:t + 1].max()); dn = False
        r1 = p1 > p0 and p2 > p0; w3x = p3 > p1; r3 = p4 > p1; ext = p5 > p3
        l1, l3, l5 = p1 - p0, p3 - p2, p5 - p4
    if not r1:
        return {"zz": zz, "why": "R1: волна 2 забирает всю первую"}
    if not w3x:
        return {"zz": zz, "why": "третья не вышла за конец первой — структура ABC/флэт, не импульс"}
    if not r3:
        return {"zz": zz, "why": "R3: волна 4 заходит на территорию первой (перекрытие)"}
    if not ext:
        return {"zz": zz, "why": "пятая ещё не вышла за экстремум третьей (импульс не достроен)"}
    if l3 < l1 and l3 < l5:
        return {"zz": zz, "why": "R2: третья — самая короткая"}
    imp = abs(p5 - p0) / p0 * 100 if p0 else 0
    if not (p.min_imp <= imp <= p.max_imp):
        return {"zz": zz, "why": f"ход {imp:.1f}% вне [{p.min_imp:g}; {p.max_imp:g}]%"}
    wt = calculate_wt(dhr.copy())["wt1"].values.astype(float)
    seg = lh[li + 1:t + 1] if dn else hh[li + 1:t + 1]
    b = li + 1 + int(seg.argmin() if dn else seg.argmax())
    if np.isfinite(wt[b]) and not ((wt[b] < -p.z) if dn else (wt[b] > p.z)):
        return {"zz": zz, "why": f"WT на пятой {wt[b]:.0f}, нужно {'<-' if dn else '>'}{p.z:g}"}
    return {"zz": zz, "why": "проходит правила — сетап должен быть в mark_impulse"}


def _wt_cross(dl: pd.DataFrame):
    d = calculate_wt(dl.reset_index(drop=True).copy())
    w1, w2 = d["wt1"].values.astype(float), d["wt2"].values.astype(float)
    up = np.zeros(len(w1), bool); dn = np.zeros(len(w1), bool)
    up[1:] = (w1[1:] > w2[1:]) & (w1[:-1] <= w2[:-1]); dn[1:] = (w1[1:] < w2[1:]) & (w1[:-1] >= w2[:-1])
    return up, dn


def ltf_status(setup: Dict[str, Any], dl: pd.DataFrame, p: WaveParams = WaveParams()) -> Dict[str, Any]:
    """Статус входа по LTF-ряду (закрытые бары): первый кросс WT, пробой линии 2-4, экстремум пятой,
    достигнутые прогнозные уровни. Работает и без HTF-ряда — линия задана через время."""
    long_ = setup["side"] == "LONG"
    lt = dl.index.values.astype("datetime64[ns]"); c = dl.close.values.astype(float)
    up_c, dn_c = _wt_cross(dl)
    t5 = np.datetime64(pd.Timestamp(setup["top_time"]).to_datetime64()); jb = int(np.searchsorted(lt, t5))
    ref_t = np.datetime64(pd.Timestamp(setup["line_ref_time"]).to_datetime64())
    ref_p, sh = float(setup["line_ref_price"]), float(setup["line_slope_h"])

    def line_at(m):
        return ref_p + sh * ((lt[m] - ref_t) / np.timedelta64(60, "m"))
    broke = [m for m in range(jb, len(lt)) if ((c[m] > line_at(m)) if long_ else (c[m] < line_at(m)))]
    cross = up_c if long_ else dn_c; crosses = [m for m in range(jb, len(lt)) if cross[m]]
    if jb < len(lt):
        ext = float(dl.low.values[jb:].min()) if long_ else float(dl.high.values[jb:].max())
    else:
        ext = float(setup["p5"])
    p5e = min(float(setup["p5"]), ext) if long_ else max(float(setup["p5"]), ext)
    w5_hit = [k for k in ("w5_618", "w5_eq1", "w5_chan", "w5_1618") if ((p5e <= setup[k]) if long_ else (p5e >= setup[k]))]
    last = float(c[-1])
    corr_hit = [k for k in ("corr_382", "corr_500", "corr_618", "corr_w4") if ((last >= setup[k]) if long_ else (last <= setup[k]))]
    sl = p5e * (1 - p.buf) if long_ else p5e * (1 + p.buf)
    return {"cross_first": pd.Timestamp(lt[crosses[0]]) if crosses else None, "line24_broken": bool(broke),
            "line24_first": pd.Timestamp(lt[broke[0]]) if broke else None, "line24_now": float(line_at(len(lt) - 1)) if len(lt) else None,
            "p5_ext": p5e, "stop": sl, "last_close": last, "w5_reached": w5_hit, "corr_reached": corr_hit}
