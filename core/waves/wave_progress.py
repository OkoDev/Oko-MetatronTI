"""🌊 Волновой аналитик · режим «ХОД В ПРОЦЕССЕ» (Егор 14.09, BCH: «аналитик молчит, пока пятёрка не завершена»).

Когда завершённой пятёрки/диагонали нет, разбираем текущий ход так же, как вручную на BCH:
  · счёт от последнего непробитого экстремума: 0-1-2-3-4 (1h, свинг 60 ≈ масштаб ядра 4h/15) с правилами Эллиотта;
  · что сейчас идёт (волна 2 / 3 / 4 / 5) и что его отменяет;
  · уровни завершения: цели волны (0.618/1/1.618), правило «3 < 1 ⇒ 5 < 3», альтернатива ABC (C = A, C = 1.618A),
    фибо дневной ноги (0.786/0.886/1.0), классические пивоты D/W/M → ЗОНА = самое плотное скопление уровней;
  · треугольники на 15m: расширяющийся / сходящийся (по Эллиотту это волна 4 или B — бросок после них обычно по старому тренду).
Всё причинно: только закрытые бары, свинги подтверждены к последнему бару. Вероятностей не выдумываем."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.smc.oko_sm_engine import _swings
from core.waves.wave5_core import _fix_same_kind


def count_in_progress(d1: pd.DataFrame, sw: int = 60, back: int = 9) -> Optional[Dict[str, Any]]:
    """Счёт незавершённого хода на закрытых барах d1. Начало (0) — самый ранний из последних `back` свингов, который цена
    с тех пор не прошла и от которого 1..4 последующих свинга проходят правила импульса. Возврат: точки, k, направление,
    текущий провизорный экстремум после последнего свинга."""
    dr = d1.reset_index(drop=True); t = len(dr) - 1
    hh, ll = dr.high.values.astype(float), dr.low.values.astype(float)
    sws = _fix_same_kind([s for s in _swings(dr.high, dr.low, sw) if s[0] <= t])
    if len(sws) < 3:
        return None
    best = None
    for j in range(max(0, len(sws) - back), len(sws) - 1):
        o = sws[j]; oi = int(o[1]); op = float(o[2]); down = bool(o[3])      # вершина → ход вниз
        if (down and hh[oi + 1:].max() >= op) or ((not down) and ll[oi + 1:].min() <= op):
            continue                                                         # начало уже пройдено
        pts = [(oi, op)] + [(int(s[1]), float(s[2])) for s in sws[j + 1:]]
        k = len(pts) - 1
        if not 1 <= k <= 4:
            continue
        g = -1 if down else 1; px = [p for _, p in pts]
        ok = True
        if k >= 2: ok &= g * (px[2] - px[0]) > 0 and abs(px[2] - px[1]) < abs(px[1] - px[0])      # R1: 2 не за 0
        if k >= 3: ok &= g * (px[3] - px[1]) > 0                                                  # 3 за концом 1
        if k >= 4: ok &= g * (px[4] - px[1]) > 0                                                  # R3: 4 не заходит на 1
        if not ok:
            continue
        best = {"down": down, "g": g, "k": k, "idx": [i for i, _ in pts], "px": px, "times": [d1.index[i] for i, _ in pts]}
        break                                                                # самый ранний валидный = самый крупный ход
    if best is None:
        return None
    # 🔑 провизорные точки (Егор 14.09, XLM: «волна 2», хотя цена давно выше конца первой). Свинг масштаба 60 подтверждается
    # через 60 баров, и счёт застревает. Если после последней точки был откат ≥ 0.236 прошлой волны и цена ушла ЗА эту точку —
    # откат становится предварительной точкой; если отката не было — последняя точка ещё не конец, её экстремум обновляется.
    best["prov"] = []
    for _ in range(2):
        li = best["idx"][-1]; lp = best["px"][-1]; kk = best["k"]
        if li >= t - 1 or kk >= 4:
            break
        last_top = (kk % 2 == 0) == best["down"]
        seg_h, seg_l = hh[li + 1:], ll[li + 1:]
        prev_len = abs(best["px"][-1] - best["px"][-2])
        if last_top:
            jx = li + 1 + int(seg_l.argmin()); after = hh[jx + 1:]
            if after.size and after.max() > lp and (lp - ll[jx]) >= 0.236 * prev_len:
                best["idx"].append(jx); best["px"].append(float(ll[jx])); best["times"].append(d1.index[jx]); best["k"] += 1; best["prov"].append(best["k"])
                continue
            if seg_h.max() > lp:
                j2 = li + 1 + int(seg_h.argmax()); best["idx"][-1] = j2; best["px"][-1] = float(hh[j2]); best["times"][-1] = d1.index[j2]
                best["prov"].append(kk)
        else:
            jx = li + 1 + int(seg_h.argmax()); after = ll[jx + 1:]
            if after.size and after.min() < lp and (hh[jx] - lp) >= 0.236 * prev_len:
                best["idx"].append(jx); best["px"].append(float(hh[jx])); best["times"].append(d1.index[jx]); best["k"] += 1; best["prov"].append(best["k"])
                continue
            if seg_l.min() < lp:
                j2 = li + 1 + int(seg_l.argmin()); best["idx"][-1] = j2; best["px"][-1] = float(ll[j2]); best["times"][-1] = d1.index[j2]
                best["prov"].append(kk)
        break
    g_, pxs = best["g"], best["px"]
    if best["k"] >= 2 and not (g_ * (pxs[2] - pxs[0]) > 0):                  # провизорная 2 зашла за 0 — счёт недействителен
        return None
    li = best["idx"][-1]
    if li < t:
        seg_h, seg_l = hh[li + 1:], ll[li + 1:]
        # провизорный экстремум текущей волны (k+1): в направлении этой волны
        nxt_down = best["down"] if best["k"] % 2 == 0 else not best["down"]
        ci = li + 1 + int(seg_l.argmin() if nxt_down else seg_h.argmax())
        best["cur"] = (ci, float(ll[ci] if nxt_down else hh[ci]), d1.index[ci])
    best["price"] = float(dr.close.iloc[-1])
    return best


def pivots(d1: pd.DataFrame) -> Dict[str, float]:
    """Классические пивоты от последних ЗАКРЫТЫХ дня/недели/месяца (UTC)."""
    out = {}
    last = d1.index[-1]
    for nm, rule in (("D", "1D"), ("W", "W-MON"), ("M", "MS")):          # неделя с понедельника, как у терминала
        r = d1[["high", "low", "close"]].resample(rule, label="left", closed="left").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        span = {"D": pd.Timedelta(days=1), "W": pd.Timedelta(days=7)}.get(nm)
        closed = r[r.index + span <= last + pd.Timedelta(hours=1)] if span is not None else r.iloc[:-1]
        if closed.empty:
            continue
        H, L, C = closed.iloc[-1]; P = (H + L + C) / 3
        out.update({f"{nm} PP": P, f"{nm} R1": 2 * P - L, f"{nm} S1": 2 * P - H, f"{nm} R2": P + (H - L), f"{nm} S2": P - (H - L)})
    return out


def triangle_scan(frames: Dict[str, pd.DataFrame]) -> Optional[Dict[str, Any]]:
    """Ищет треугольник на нескольких ТФ/масштабах (3m: свинг 5/8/12, 15m: 3/5), окна из 5 свингов, оканчивающиеся на
    последнем или предпоследнем свинге. Первый найденный (от младшего масштаба к старшему)."""
    for tf, sws_ in (("3m", (5, 8, 12)), ("15m", (3, 5))):
        dl = frames.get(tf)
        for sw in sws_:
            for shift in (0, 1):
                r = triangle_ltf(dl, sw, shift)
                if r:
                    r["tf"], r["sw"] = tf, sw
                    return r
    return None


def triangle_ltf(dl: pd.DataFrame, sw: int = 5, shift: int = 0) -> Optional[Dict[str, Any]]:
    """Расширяющийся/сходящийся треугольник по 5 чередующимся свингам (a-b-c-d-e); shift — сколько последних свингов пропустить."""
    if dl is None or len(dl) < 100:
        return None
    dr = dl.reset_index(drop=True); t = len(dr) - 1
    allsw = _fix_same_kind([s for s in _swings(dr.high, dr.low, sw) if s[0] <= t])
    sws = allsw[len(allsw) - 5 - shift:len(allsw) - shift] if len(allsw) >= 5 + shift else []
    if len(sws) < 5:
        return None
    tops = [(int(s[1]), float(s[2])) for s in sws if s[3]]; bots = [(int(s[1]), float(s[2])) for s in sws if not s[3]]
    if len(tops) < 2 or len(bots) < 2:
        return None
    up_t = all(tops[i + 1][1] > tops[i][1] for i in range(len(tops) - 1)); dn_t = all(tops[i + 1][1] < tops[i][1] for i in range(len(tops) - 1))
    up_b = all(bots[i + 1][1] > bots[i][1] for i in range(len(bots) - 1)); dn_b = all(bots[i + 1][1] < bots[i][1] for i in range(len(bots) - 1))
    kind = "расширяющийся" if (up_t and dn_b) else "сходящийся" if (dn_t and up_b) else None
    if kind is None:
        return None
    (x1, y1), (x2, y2) = tops[-2], tops[-1]; (u1, v1), (u2, v2) = bots[-2], bots[-1]
    su = (y2 - y1) / max(1, x2 - x1); sl = (v2 - v1) / max(1, u2 - u1)
    upper = y2 + su * (t - x2); lower = v2 + sl * (t - u2); c = float(dr.close.iloc[-1])
    last_i = int(sws[-1][1]); span_ = last_i - int(sws[0][1])
    height = max(p for _, p in tops) - min(p for _, p in bots)
    if upper - lower < 0.25 * height or t - last_i > max(20, span_):   # у вершины (сходящийся выродился) или фигура давно в прошлом
        return None
    brk = "вверх" if c > upper else "вниз" if c < lower else "внутри"
    return {"kind": kind, "points": [(dl.index[int(s[1])], float(s[2]), bool(s[3])) for s in sws], "upper_now": upper, "lower_now": lower,
            "upper": ((dl.index[x1], y1), (dl.index[x2], y2)), "lower": ((dl.index[u1], v1), (dl.index[u2], v2)), "breakout": brk, "close": c}


def cluster_zone(levels: List[tuple], price: float, down: bool, width: float = 0.05, limit: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Самое плотное окно шириной `width` (доля цены) среди уровней по ходу движения; `limit` — жёсткая граница (правило волн),
    уровни за ней отбрасываются. Центры окон — уровни и середины между соседними; при равенстве — ближе к цене. levels: (имя, цена, вес)."""
    cand = [(n, v, w) for n, v, w in levels if v > 0 and ((v < price) if down else (v > price))
            and (limit is None or ((v >= limit) if down else (v <= limit)))]
    if len(cand) < 2:
        return None
    best = None
    vals = sorted(v for _, v, _ in cand)
    centers = vals + [(vals[i] + vals[i + 1]) / 2 for i in range(len(vals) - 1)]
    for v0 in centers:
        inside = [(n, v, w) for n, v, w in cand if v0 - width * price / 2 <= v <= v0 + width * price / 2]
        sc = sum(w for _, _, w in inside)
        if len(inside) >= 2 and (best is None or sc > best[0] or (sc == best[0] and abs(v0 - price) < abs(best[1] - price))):
            best = (sc, v0, inside)
    if best is None:
        return None
    vs = [v for _, v, _ in best[2]]
    return {"lo": min(vs), "hi": max(vs), "mid": float(np.mean(vs)), "score": best[0], "levels": sorted(best[2], key=lambda x: -x[1])}


def analyze_progress(sym: str, dh: pd.DataFrame, d1: pd.DataFrame, dl15: Optional[pd.DataFrame], now: pd.Timestamp,
                     leg_fn, rep: Dict[str, Any], dl3: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Заполняет rep для режима «ход в процессе». leg_fn(t0, want_top, p_ext, t_ext) → дневная нога (из wave_analyst.daily_leg)."""
    cnt = count_in_progress(d1)
    rep["mode"] = "progress"
    T = rep["text"]
    if cnt is None:
        T.append("Завершённой пятёрки нет, и текущий ход не складывается в счёт 0-1-2-3-4 по правилам (частые перекрытия) — "
                 "похоже на боковик/коррекцию сложной формы; аналитик не рисует натянутый счёт.")
        return rep
    down, g, k, px, times = cnt["down"], cnt["g"], cnt["k"], cnt["px"], cnt["times"]
    price = cnt["price"]; rep["price"] = price; rep["progress"] = cnt
    L = [abs(px[i + 1] - px[i]) for i in range(k)]
    word = "вниз" if down else "вверх"
    # экстремум хода по его направлению (провизорный экстремум учитывается, только если текущая волна идёт по ходу)
    ext_move = (min([px[i] for i in range(0, k + 1, 1)] + ([cnt["cur"][1]] if cnt.get("cur") and k % 2 == 0 else [])) if down
                else max([px[i] for i in range(0, k + 1, 1)] + ([cnt["cur"][1]] if cnt.get("cur") and k % 2 == 0 else [])))
    t_ext = times[int(np.argmin(px) if down else np.argmax(px))]
    leg = leg_fn(times[0], not down, ext_move, t_ext)                          # ход вниз корректирует дневную ногу вверх
    rep["leg"] = leg
    lv: List[tuple] = []
    names = {1: "волна 2 (откат)", 2: "волна 3", 3: "волна 4 (откат)", 4: "волна 5 / C"}
    prov = set(cnt.get("prov") or [])
    T.append(f"{sym}: завершённой пятёрки нет — идёт ход {word} от {px[0]:.6g} ({times[0]:%d.%m %H:%M} UTC). "
             f"Счёт (1h, свинг 60): " + " → ".join(f"{i} = {px[i]:.6g}{'*' if i in prov else ''}" for i in range(k + 1)) + f". Сейчас — {names[k]}, цена {price:.6g}.")
    if prov:
        T.append("* — предварительная точка: свинг масштаба 60 ещё не подтверждён (нужно 60 часов без обновления), счёт может сдвинуться.")
    scen = []
    if k == 4:
        l1, l3 = L[0], L[2]; p4 = px[4]
        lv += [("5 = 0.618×1", p4 + g * 0.618 * l1, 2), ("5 = 1×1", p4 + g * l1, 1.5), ("C = A (0-1-2 как A-B)", px[2] + g * l1, 2),
               ("C = 1.618A", px[2] + g * 1.618 * l1, 1), ("минимум пятой: за 3", px[3], 1)]
        limit = None
        if l3 < l1:
            limit = p4 + g * l3
            lv += [("5 = 0.618×3", p4 + g * 0.618 * l3, 2)]
            T.append(f"Третья короче первой ({l3:.4g} < {l1:.4g}) ⇒ пятая обязана быть короче третьей: предел {limit:.6g}.")
        T.append(f"Волна 2 откатила {L[1] / l1:.2f} первой, волна 4 — {L[3] / l3:.2f} третьей; перекрытия 4 и 1 нет (запас {abs(px[4] - px[1]):.4g}).")
    elif k == 3:
        l3 = L[2]
        for f_ in (0.236, 0.382, 0.5):
            lv.append((f"волна 4 = {f_} от 3", px[3] - g * f_ * l3, 1.5))
        T.append(f"Идёт волна 4: откат третьей. Граница — начало перекрытия с первой на {px[1]:.6g}: заход туда ломает импульс (это коррекция).")
    elif k == 2:
        l1 = L[0]
        for f_ in (1.0, 1.618, 2.618):
            lv.append((f"волна 3 = {f_}×1", px[2] + g * f_ * l1, 2 if f_ == 1.618 else 1.5))
        T.append(f"Идёт волна 3 от {px[2]:.6g}. Отмена счёта — возврат за начало {px[0]:.6g}.")
    else:
        l1 = L[0]
        for f_ in (0.5, 0.618, 0.786):
            lv.append((f"волна 2 = {f_} от 1", px[1] - g * f_ * l1, 1.5))
        T.append(f"Идёт волна 2 — откат первой ({px[0]:.6g} → {px[1]:.6g}). Классическая зона конца второй — 0.5–0.786; за {px[0]:.6g} счёт отменяется.")
    if leg:
        for kf in ("0.79", "0.886"):
            lv.append((f"дневная нога {kf}", leg["levels"][kf], 1.5))
        lv.append(("начало дневной ноги", leg["origin"], 1.5))
        T.append(f"1D: ход корректирует дневную ногу {leg['dir']} {leg['origin']:.6g} → {leg['ext']:.6g}; сейчас глубина {leg['depth']:.2f} — {leg['zone']}.")
    # зона: для k=4 — завершение хода; для k=1/3 — конец отката (против хода); для k=2 — цели третьей
    zone_dir_down = down if k in (2, 4) else not down
    pv = pivots(d1)
    for n, v in pv.items():                                        # пивоты — только по направлению поиска зоны
        if (n.endswith(("S1", "S2")) and zone_dir_down) or (n.endswith(("R1", "R2")) and not zone_dir_down):
            lv.append((n, v, 1.0))
    rep["pivots"] = pv; rep["levels"] = lv
    zlimit = (px[4] + g * L[2]) if (k == 4 and L[2] < L[0]) else px[0] if k == 1 else px[1] if k == 3 else None   # волна 2 не за 0, волна 4 не за 1
    zone = cluster_zone(lv, price, zone_dir_down, limit=zlimit)
    rep["zone"] = zone
    if zone is None and k in (1, 3):
        retr_down = not down                                           # откат идёт против хода
        ahead = sorted([(n, v) for n, v, _ in lv if ((v < price) if retr_down else (v > price))], key=lambda x: -x[1] if retr_down else x[1])
        if ahead:
            T.append(f"Впереди остался последний уровень отката: {ahead[0][0]} = {ahead[0][1]:.6g}; глубже — "
                     f"{'начало хода ' + format(px[0], '.6g') + ' (за ним волна 2 невозможна)' if k == 1 else 'конец первой ' + format(px[1], '.6g') + ' (заход ломает импульс)'}.")
        else:
            T.append(f"Откат уже глубже всех классических уровней — счёт под угрозой: "
                     f"{'за началом ' + format(px[0], '.6g') + ' волна 2 невозможна' if k == 1 else 'заход за конец первой ломает импульс'}.")
    if zone:
        T.append(f"Зона {'завершения хода' if k == 4 else 'конца отката' if k in (1, 3) else 'целей третьей'}: {zone['lo']:.6g}–{zone['hi']:.6g} — "
                 "сходятся " + ", ".join(f"{n} {v:.5g}" for n, v, _ in zone["levels"]) + ".")
    tri = triangle_scan({"3m": dl3, "15m": dl15}); rep["triangle"] = tri
    if tri:
        T.append(f"{tri['tf']} (свинг {tri['sw']}): {tri['kind']} треугольник (a-b-c-d-e), граница сверху {tri['upper_now']:.6g}, снизу {tri['lower_now']:.6g}, цена {tri['breakout']}. "
                 "По Эллиотту треугольник — это волна 4 или B: бросок после него обычно в сторону старого тренда; пробой против тренда подтверждать закреплением.")
    # сценарии
    rev = "лонг" if down else "шорт"
    if k == 4 and zone:
        whole = abs(zone["mid"] - px[0])
        tg = [(f"{f_} всего хода", zone["mid"] - g * f_ * whole) for f_ in (0.382, 0.5, 0.618)]
        scen.append({"name": f"A · пятая/C {word} до зоны, затем {rev}", "side": f"ждать {rev} в зоне",
                     "why": f"счёт 0-4 валиден, пятая не завершена; в зоне {zone['lo']:.6g}–{zone['hi']:.6g} ждать слом младшего ТФ против хода и откат.",
                     "targets": [("точка 4", px[4])] + tg, "invalid": f"закрытие 1h {'выше' if down else 'ниже'} точки 4 = {px[4]:.6g}"})
        scen.append({"name": f"B · низ/верх уже стоит ({'ABC завершена' if L[2] < L[0] else 'усечение пятой'})", "side": rev,
                     "why": f"без обновления {px[3]:.6g} и со сломом 1h против хода — ход закончен на точке 3 (C ≈ {L[2] / L[0]:.2f}A).",
                     "targets": [("точка 4", px[4]), ("0.382 хода", px[3] - g * 0.382 * abs(px[3] - px[0])), ("0.618 хода", px[3] - g * 0.618 * abs(px[3] - px[0]))],
                     "invalid": f"обновление {px[3]:.6g}"})
    elif k == 3:
        tg5 = [("5 = 0.618×1", (zone["mid"] if zone else px[3]) + g * 0.618 * L[0]), ("5 = 1×1", (zone["mid"] if zone else px[3]) + g * L[0])]
        scen.append({"name": "A · четвёртая заканчивается → пятая по ходу", "side": f"{'шорт' if down else 'лонг'} по ходу из зоны отката",
                     "why": "откат третьей в зоне 0.236–0.5 и слом младшего ТФ по ходу.", "targets": tg5, "invalid": f"заход за конец первой {px[1]:.6g}"})
        scen.append({"name": "B · перекрытие с первой → это коррекция, не импульс", "side": "нейтрально",
                     "why": "если откат уходит за конец первой, счёт 0-3 — это ABC или сложная коррекция.", "targets": [("начало хода", px[0])],
                     "invalid": f"новый экстремум за {px[3]:.6g}"})
    elif k == 2:
        scen.append({"name": "A · третья волна идёт к целям", "side": f"{'шорт' if down else 'лонг'} по ходу",
                     "why": "третья — самая сильная; входы на откатах младшего ТФ.", "targets": [(n, v) for n, v, _ in lv[:3]],
                     "invalid": f"возврат за начало хода {px[0]:.6g}"})
    else:
        scen.append({"name": "A · вторая волна в зоне → вход на третью", "side": f"{'шорт' if down else 'лонг'} по ходу",
                     "why": "откат 0.5–0.786 первой и слом младшего ТФ по ходу.", "targets": [("3 = 1×1 от зоны", (zone["mid"] if zone else price) + g * L[0]), ("3 = 1.618×1 от зоны", (zone["mid"] if zone else price) + g * 1.618 * L[0])],
                     "invalid": f"за начало {px[0]:.6g}"})
    rep["scenarios"] = scen
    return rep


def render_progress(rep: Dict[str, Any], dh: pd.DataFrame, d1: pd.DataFrame, dl15: Optional[pd.DataFrame], out: Path,
                    dl3: Optional[pd.DataFrame] = None) -> Path:
    """Схема режима «ход в процессе»: 1D нога · 1h счёт + зона + уровни отрезками + стрелки сценариев · 15m треугольник · текст."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, FancyArrowPatch
    from core.waves.wave_analyst import to_daily
    BG, FG, GRID, UP, DN, WAVE, ACC, VIO, GRN = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#9575cd", "#66bb6a"

    def candles(ax, w):
        x = np.arange(len(w)); o, h, l, c = (w[k_].values.astype(float) for k_ in ("open", "high", "low", "close"))
        for i in range(len(w)):
            col = UP if c[i] >= o[i] else DN
            ax.vlines(x[i], l[i], h[i], color=col, lw=.6); ax.add_patch(Rectangle((x[i] - .32, min(o[i], c[i])), .64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, lw=0))

    def style(ax, t_):
        ax.set_facecolor(BG); [s_.set_color(GRID) for s_ in ax.spines.values()]; ax.tick_params(colors=FG, labelsize=7.5)
        ax.grid(True, color=GRID, lw=.5, alpha=.4); ax.set_title(t_, color=FG, fontsize=9.5, loc="left")

    def xi(w, tt):
        return int(w.index.get_indexer([pd.Timestamp(tt)], method="nearest")[0])

    def seg(ax, x0, x1, y, txt, col, ls="--", lw=.9, side="right"):
        ax.hlines(y, min(x0, x1), max(x0, x1), colors=col, linestyles=ls, lw=lw)
        if txt:
            ax.annotate(f"{txt} {y:.5g}", (max(x0, x1) if side == "right" else min(x0, x1), y), color=col, fontsize=6.8, va="center",
                        ha="left" if side == "right" else "right", xytext=(3 if side == "right" else -3, 0), textcoords="offset points")

    def arrow(ax, p0, p1, col, ls, txt=None, off=(5, 0)):
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=14, color=col, lw=1.6, linestyle=ls, zorder=7))
        if txt:
            ax.annotate(txt, p1, color=col, fontsize=7.5, fontweight="bold", xytext=off, textcoords="offset points", va="center",
                        bbox=dict(boxstyle="round,pad=0.2", fc=BG, ec="none", alpha=.85))

    from core.waves.wave_analyst import build_text_columns, text_height_in, draw_text_columns, FIG_W
    cnt = rep.get("progress"); leg = rep.get("leg")
    TL, TR = build_text_columns(rep, f"{rep['sym']} · волновой разбор · ход в процессе")
    th = text_height_in(TL, TR); CH_H = 12.0; H = CH_H + th + 0.6
    fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[.9, 1.3, .85], hspace=.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
    ax1 = fig.add_subplot(gs[0]); dd = to_daily(dh); w = dd.iloc[-160:]; candles(ax1, w)
    style(ax1, "1D · дневная нога, которую корректирует ход")
    if leg:
        xo, xe = xi(w, leg["origin_t"]), xi(w, leg["ext_t"])
        ax1.plot([xo, xe], [leg["origin"], leg["ext"]], color=WAVE, lw=1.1, ls="--")
        for kf, v in leg["levels"].items():
            seg(ax1, xo, xe, v, kf, ACC if kf in ("0.618", "0.705", "0.786", "0.79") else VIO, ":", .8, side="left")
    ax1.set_xlim(-12, len(w) + 8)
    ax2 = fig.add_subplot(gs[1])
    if cnt:
        i0 = max(0, cnt["idx"][0] - 30); w1 = d1.iloc[i0:]; candles(ax2, w1); n = len(w1) - 1; F = max(40, int(.25 * len(w1)))
        xs = [i - i0 for i in cnt["idx"]]; ys = cnt["px"]
        ax2.plot(xs + [n], ys + [rep["price"]], color=WAVE, lw=1.6); ax2.scatter(xs, ys, color=WAVE, s=30, zorder=6)
        for i, (x_, y_) in enumerate(zip(xs, ys)):
            ax2.annotate(str(i), (x_, y_), color=WAVE, fontsize=10, fontweight="bold", xytext=(-4, 9 if (cnt["g"] < 0) == (i % 2 == 0) else -15), textcoords="offset points")
        style(ax2, f"1h · ход {'вниз' if cnt['down'] else 'вверх'}: счёт 0–{cnt['k']}, волна {cnt['k'] + 1} в процессе · зона и сценарии")
        z = rep.get("zone")
        pr = rep["price"]
        for nm, v, _ in rep.get("levels", []):
            if abs(v / pr - 1) > 0.20:
                continue
            inz = bool(z and z["lo"] <= v <= z["hi"])
            seg(ax2, n - 25, n + F, v, nm if inz else "", ACC if inz else "#4a5160", "-." if inz else ":", 1 if inz else .6)
        if rep.get("limit5"):
            seg(ax2, cnt["idx"][-1] - i0, n + F, rep["limit5"], "предел пятой (5 < 3)", DN, "--", 1.1)
        ys_all = [v for _, v, _ in rep.get("levels", []) if abs(v / pr - 1) <= .2] + list(cnt["px"]) + [pr]
        ax2.set_ylim(min(ys_all) * .97, max(ys_all) * 1.02)
        if z:
            ax2.add_patch(Rectangle((n + 6, z["lo"]), F - 12, z["hi"] - z["lo"], color=ACC, alpha=.16, lw=0))
            ax2.annotate("зона", (n + F / 2, z["hi"]), color=ACC, fontsize=8, ha="center", va="bottom")
            sc = rep.get("scenarios") or []
            arrow(ax2, (n, rep["price"]), (n + F * .35, z["mid"]), ACC, "-.", "A", (4, 0))
            if sc and sc[0]["targets"]:
                arrow(ax2, (n + F * .35, z["mid"]), (n + F * .9, sc[0]["targets"][min(1, len(sc[0]["targets"]) - 1)][1]), GRN, "--", None)
            if len(sc) > 1 and sc[1]["targets"]:
                arrow(ax2, (n, rep["price"]), (n + F * .3, sc[1]["targets"][0][1]), UP if cnt["down"] else DN, "--", "B", (4, 0))
        ax2.set_xlim(-5, n + F + 40)
    else:
        style(ax2, "1h · счёт не складывается")
    ax3 = fig.add_subplot(gs[2]); tri = rep.get("triangle")
    src = dl3 if (tri and tri.get("tf") == "3m" and dl3 is not None) else dl15
    if src is not None and len(src):
        w3 = src[src.index >= tri["points"][0][0] - (src.index[-1] - src.index[-2]) * 40].iloc[-400:] if tri else src.iloc[-200:]
        candles(ax3, w3)
        style(ax3, f"{tri['tf'] + ' (свинг ' + str(tri['sw']) + ') · ' + tri['kind'] + ' треугольник a-b-c-d-e, цена ' + tri['breakout'] if tri else '15m · треугольника нет'}")
        if tri:
            for (ta, ya), (tb, yb) in (tri["upper"], tri["lower"]):
                xa, xb = xi(w3, ta), xi(w3, tb); slope = (yb - ya) / max(1, xb - xa); xe_ = len(w3) - 1
                ax3.plot([xa, xe_], [ya, ya + slope * (xe_ - xa)], color=ACC, lw=1.1, ls="--")
            for i, (tt, pp, top) in enumerate(tri["points"]):
                x_ = xi(w3, tt); ax3.scatter([x_], [pp], color=WAVE, s=24, zorder=6)
                ax3.annotate("abcde"[i], (x_, pp), color=WAVE, fontsize=9, xytext=(-3, 7 if top else -13), textcoords="offset points")
    draw_text_columns(fig, TL, TR, 0.2, th)
    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)
    return out
