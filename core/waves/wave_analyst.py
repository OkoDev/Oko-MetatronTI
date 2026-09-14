"""🌊 Волновой аналитик Куба (сфера 20 · WaveService) — разбор монеты сценариями, как вручную делали 14.09 на RECALL/SOLV.

Егор 14.09: «таких разборов и прогнозов очень не хватает от Куба и бота — со схемами и пояснениями»;
«5 волн — это может быть и конечная диагональ, и другие разворотные фигуры».

Слои (все каузальны, только закрытые бары):
  1D  — дневная нога, которую корректирует/продолжает 4h-структура: где кончилась пятая (глубина, OTE 0.62-0.79),
        уровни ноги (фибо) и расширения (−0.27/−0.62/−1/−1.618).
  4h  — счёт: импульс ядра (`mark_impulse`) или КОНЕЧНАЯ ДИАГОНАЛЬ (перекрытие 4 и 1, сходящиеся/расходящиеся
        линии 1-3 и 2-4) — её правило R3 импульса выбрасывает, поэтому она ищется отдельно.
  LTF — слом младшего слоя OKO-SM против хода после пятой, волна A, зона отката 0.5-0.705 (механика Егора).
Сценарии:
  A «старший ход продолжается» — пятая внутри дневной ноги (глубина ≤ 1): цели — экстремум ноги и расширения.
  B «4h-ход — волна 1 нового» — разворот только коррекционный: цели 0.382/0.5/0.618 хода, в зоне 0.5-0.618 развилка.
Числа вероятностей НЕ выдумываются: в текст идут только правила, уровни и измеренные факты.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.smc.oko_sm_engine import run_structure, _swings
from core.waves.wave5_core import mark_impulse, WaveParams

FIB_RET = (0.382, 0.5, 0.618, 0.705, 0.79, 0.886)
FIB_EXT = (0.272, 0.618, 1.0, 1.618)


@dataclass
class AnalystParams:
    sw4h: int = 15          # масштаб ядра на 4h
    il4h: int = 4
    d_sw: int = 10          # дневные свинги (дней)
    lookback: int = 90      # сколько 4h-баров назад искать последнюю завершённую пятёрку (15 сут)
    ltf_sw: int = 50        # OKO-SM на младшем ТФ (как индикатор Егора)
    ltf_il: int = 5


def to_daily(dh: pd.DataFrame) -> pd.DataFrame:
    dd = dh[["open", "high", "low", "close"]].resample("1D", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return dd[dd.index + pd.Timedelta(days=1) <= dh.index[-1] + pd.Timedelta(hours=4)]


# ─── 4h: конечная диагональ ─────────────────────────────────────────────────────────────────────
def diagonal_on_bar(swings, t, high, low) -> Optional[Dict[str, Any]]:
    """Конечная диагональ на баре t: 5 подтверждённых свингов + provisional 5. В отличие от импульса
    перекрытие волн 4 и 1 ОБЯЗАТЕЛЬНО; линии 1-3 и 2-4 сходятся (клин) или расходятся."""
    conf = [s for s in swings if s[0] <= t]
    if len(conf) < 5:
        return None
    last5 = conf[-5:]; kinds = [s[3] for s in last5]
    if any(kinds[i] == kinds[i + 1] for i in range(4)):
        return None
    idx = [int(s[1]) for s in last5]; px = [float(s[2]) for s in last5]; li = idx[-1]
    if li >= t:
        return None
    up = not last5[-1][3]                               # последний = low → ход вверх, 5 = high после него
    seg = high[li + 1:t + 1] if up else low[li + 1:t + 1]
    p5i = li + 1 + int(seg.argmax() if up else seg.argmin()); p5 = float(seg.max() if up else seg.min())
    p0, p1, p2, p3, p4 = px; g = 1 if up else -1
    ok = (g * (p1 - p0) > 0 and g * (p2 - p0) > 0 and g * (p3 - p1) > 0 and g * (p4 - p2) > 0 and g * (p5 - p3) > 0
          and g * (p1 - p4) > 0)                        # 4 заходит на территорию 1
    if not ok:
        return None
    l1, l3, l5 = abs(p1 - p0), abs(p3 - p2), abs(p5 - p4)
    s13 = (p3 - p1) / max(1, idx[3] - idx[1]); s24 = (p4 - p2) / max(1, idx[4] - idx[2])
    contracting = (s24 * g > s13 * g) and l3 < l1 and l5 < l3
    expanding = (s24 * g < s13 * g) and l3 > l1 and l5 > l3
    if not (contracting or expanding):
        return None
    return {"kind": "diagonal", "form": "сходящаяся (клин)" if contracting else "расходящаяся", "up": up,
            "wave_idx": idx + [p5i], "wave_px": px + [p5], "lens": (l1, l3, l5)}


# ─── разбор ─────────────────────────────────────────────────────────────────────────────────────
def analyze(sym: str, dh: pd.DataFrame, dl: Optional[pd.DataFrame] = None, ltf: str = "15m",
            now: Optional[pd.Timestamp] = None, p: AnalystParams = AnalystParams()) -> Dict[str, Any]:
    now = now or pd.Timestamp.utcnow()
    rep: Dict[str, Any] = {"sym": sym, "now": str(now), "ltf": ltf, "structure": None, "leg": None, "ltf_state": None,
                           "scenarios": [], "text": []}
    # 4h: импульс ядра (последний за lookback) либо диагональ
    wp = WaveParams(sw=p.sw4h, il=p.il4h)
    imp = mark_impulse(dh, now, wp, "4h", lookback=p.lookback)
    dhr = dh.reset_index(drop=True); t = len(dhr) - 1
    hh, lh = dhr.high.values.astype(float), dhr.low.values.astype(float)
    st = None
    if imp:
        s = imp[0]
        st = {"kind": "impulse", "up": s["side"] == "SHORT", "wave_idx": s["wave_idx"], "wave_px": s["wave_px"],
              "setup": s, "form": "импульс"}
    else:
        sw = _swings(dhr["high"], dhr["low"], p.sw4h)
        for tt in range(t, max(t - p.lookback, 0), -1):
            dg = diagonal_on_bar(sw, tt, hh, lh)
            if dg:
                st = dg; break
    if st is None:
        rep["text"].append("На 4h (масштаб ядра) нет завершённой пятёрки или конечной диагонали за последние 15 суток — "
                           "разворотного сценария нет, аналитик молчит.")
        return rep
    st["times"] = [dh.index[i] for i in st["wave_idx"]]
    # фактический экстремум пятой — по всем барам после неё (он мог обновиться)
    i5 = st["wave_idx"][5]
    if st["up"]:
        k = i5 + int(hh[i5:].argmax()); st["p5x"] = float(hh[k])
    else:
        k = i5 + int(lh[i5:].argmin()); st["p5x"] = float(lh[k])
    st["t5x"] = dh.index[k]
    rep["structure"] = st
    g = 1 if st["up"] else -1                             # направление 4h-хода; разворот — против (−g)
    p0, p5 = float(st["wave_px"][0]), st["p5x"]; rng = abs(p5 - p0)
    corr = {f"{r}": p5 - g * r * rng for r in (0.382, 0.5, 0.618, 0.786)}
    rep["corr"] = corr

    # 1D: дневная нога, против которой шёл 4h-ход (для хода вверх — нога вниз от свинг-хая, и наоборот).
    # Начало ноги — последний дневной свинг ЗА экстремумом пятой (пятая его не прошла). Масштаб свинга неоднозначен
    # (SOLV 14.09: свинг 10 дней берёт апрельский шпиль 0.00937, Егор — майский хай 0.00634) → считаем две ноги.
    dd = to_daily(dh); t0 = st["times"][0]; want_top = st["up"]

    def _leg(d_sw):
        dsw = _swings(dd["high"], dd["low"], d_sw)
        cand = [s_ for s_ in dsw if bool(s_[3]) == want_top and dd.index[int(s_[1])] < t0 and dd.index[int(s_[0])] + pd.Timedelta(days=1) <= now]
        beyond = [s_ for s_ in cand if (float(s_[2]) > p5 if want_top else float(s_[2]) < p5)]
        pick = beyond[-1] if beyond else (cand[-1] if cand else None)
        if pick is None:
            return None
        o_i = int(pick[1]); origin = float(pick[2])
        seg = dd.iloc[o_i:]; seg = seg[seg.index <= st["t5x"]]
        ext = float(seg.low.min()) if want_top else float(seg.high.max())       # противоположный конец ноги
        span = abs(origin - ext)
        if span <= 0:
            return None
        depth = abs(p5 - ext) / span; sg = np.sign(origin - ext)
        lvl = {f"{r}": ext + sg * r * span for r in FIB_RET}
        xt = {f"-{r}": ext - sg * r * span for r in FIB_EXT if ext - sg * r * span > 0}
        zone = ("OTE 0.62–0.79" if 0.62 <= depth <= 0.79 else "глубокая 0.79–1.0" if 0.79 < depth <= 1.0 else
                "за пределами ноги (>1)" if depth > 1 else "мелкая 0.5–0.62" if depth >= 0.5 else "мелкая (<0.5)")
        return {"origin": origin, "origin_t": dd.index[o_i], "ext": ext, "depth": depth, "zone": zone, "levels": lvl,
                "extensions": xt, "dir": "вниз" if want_top else "вверх", "d_sw": d_sw}

    leg = _leg(p.d_sw); alt = _leg(5)
    if leg and alt and abs(alt["origin"] - leg["origin"]) / leg["origin"] < 0.01:
        alt = None
    if leg and alt and alt["zone"].startswith(("OTE", "глубокая")) and not leg["zone"].startswith(("OTE", "глубокая")):
        leg, alt = alt, leg                                   # основной — та нога, в зоне интереса которой кончилась пятая
    rep["leg_alt"] = alt
    rep["leg"] = leg

    # LTF: слом против хода после пятой, волна A и зона отката
    if dl is not None and len(dl) > 300:
        d2 = dl[dl.index >= st["t5x"] - pd.Timedelta(hours=48)]
        base = dl.iloc[max(0, len(dl) - len(d2) - 400):]
        sr = run_structure(base[["open", "high", "low", "close"]].reset_index(drop=True), swing_len=p.ltf_sw, internal_len=p.ltf_il)
        bt = base.index; bh, bl = base.high.values.astype(float), base.low.values.astype(float)
        want_bull = not st["up"]
        evs = [e for e in sr.events if e.bull == want_bull and e.kind == "CHoCH" and bt[e.i] > st["t5x"]]
        ltf_state = {"choch_int": None, "choch_sw": None}
        if evs:
            ei = [e for e in evs if e.internal]; es = [e for e in evs if not e.internal]
            if ei:
                e = ei[0]; ltf_state["choch_int"] = {"t": bt[e.i], "level": float(e.level)}
                j5 = int(np.searchsorted(bt, st["t5x"]))
                back = [x for x in sr.events if x.internal and x.bull != want_bull and x.kind == "CHoCH" and x.i > e.i]
                jb = back[0].i if back else len(bt) - 1        # откат B подтверждён встречным сломом → A закончена
                ltf_state["a_done"] = bool(back)
                if want_bull:
                    ka = j5 + int(bh[j5:jb + 1].argmax()); a_top = float(bh[ka]); A = a_top - p5
                    cur_retr = (a_top - float(base.close.iloc[-1])) / A if A > 0 else None
                else:
                    ka = j5 + int(bl[j5:jb + 1].argmin()); a_top = float(bl[ka]); A = p5 - a_top
                    cur_retr = (float(base.close.iloc[-1]) - a_top) / A if A > 0 else None
                if A > 0:
                    sgn = 1 if want_bull else -1
                    ltf_state.update({"a_top": a_top, "a_t": bt[ka], "A": A, "retr_now": cur_retr,
                                      "zone": {f: a_top - sgn * f * A for f in (0.5, 0.618, 0.705)},
                                      "stop_886": a_top - sgn * 0.886 * A})
            if es:
                ltf_state["choch_sw"] = {"t": bt[es[0].i], "level": float(es[0].level)}
        rep["ltf_state"] = ltf_state

    # сценарии
    price = float(dh.close.iloc[-1]); rep["price"] = price
    after = dh[dh.index > st["t5x"]]
    rep["best_since5"] = (float(after.low.min()) if st["up"] else float(after.high.max())) if len(after) else price
    rev = "лонг" if not st["up"] else "шорт"
    if leg and leg["depth"] <= 1.0:
        # для 4h-хода вверх разворот — шорт к низу ноги (ext), расширения — дальше; для хода вниз — к хаю ноги
        if st["up"]:
            tg = [("низ дневной ноги", leg["ext"])] + [(f"расширение {k}", v) for k, v in leg["extensions"].items() if k in ("-0.272", "-0.618", "-1.0")]
        else:
            tg = [("хай дневной ноги", leg["ext"])] + [(f"расширение {k}", v) for k, v in leg["extensions"].items() if k in ("-0.272", "-0.618", "-1.0")]
        rep["scenarios"].append({"name": "A · старший ход продолжается", "side": rev,
                                 "why": f"4h-{st['form']} {'вверх' if st['up'] else 'вниз'} закончился в зоне «{leg['zone']}» дневной ноги {leg['dir']} "
                                        f"(глубина {leg['depth']:.2f}) — это коррекция ноги, её тренд продолжается.",
                                 "targets": [("0.382 4h-хода", corr["0.382"]), ("0.618 4h-хода", corr["0.618"])] + tg,
                                 "invalid": ("выше" if st["up"] else "ниже") + f" начала ноги {leg['origin']:.6g} (глубина 1.0)"})
    rep["scenarios"].append({"name": "B · 4h-ход — волна 1 нового движения", "side": f"{rev} только до коррекции, затем против",
                             "why": f"пятёрка 4h {'вверх' if st['up'] else 'вниз'} может быть первой волной нового тренда — тогда разворот лишь ABC.",
                             "targets": [("0.382", corr["0.382"]), ("0.5", corr["0.5"]), ("0.618", corr["0.618"])],
                             "fork": (corr["0.5"], corr["0.618"]),
                             "invalid": f"за 0.786 хода ({corr['0.786']:.6g}) и тем более за его началом {p0:.6g} — это уже не волна 1"})
    # текст
    T = rep["text"]
    s0 = st.get("setup") or {}
    T.append(f"{sym}: на 4h {'завершена пятёрка' if st['kind'] == 'impulse' else 'завершена конечная диагональ (' + st['form'] + ')'} "
             f"{'вверх' if st['up'] else 'вниз'}: {p0:.6g} → {p5:.6g} ({rng / p0 * 100:.0f}%), экстремум {st['t5x']:%d.%m %H:%M} UTC.")
    if s0:
        T.append(f"Правила ядра: фрактал {'✓' if s0['fractal'] else '✗'}, канал {s0['depth5']}, чередование {'✓' if s0['altern'] else '✗'}, "
                 f"счёт {'✓' if s0['count_ok'] else '✗'}{' — ЯДРО' if s0['core_full'] else ''}. WT на пятой {s0['wt_top']}, WT 1D {s0['d_wt']}.")
    if st["kind"] == "diagonal":
        T.append("Диагональ: волна 4 заходит на территорию 1 — для импульса запрещено, для конечной диагонали обязательно. "
                 "После диагонали типичен резкий возврат к её началу.")
    if leg:
        T.append(f"1D: нога {leg['dir']} от {leg['origin']:.6g} ({leg['origin_t']:%d.%m}) до {leg['ext']:.6g}; пятая остановилась на глубине {leg['depth']:.2f} — {leg['zone']}.")
    if rep.get("leg_alt"):
        la = rep["leg_alt"]
        T.append(f"Альтернативная нога (другой масштаб свинга): от {la['origin']:.6g} ({la['origin_t']:%d.%m}) — глубина {la['depth']:.2f}, {la['zone']}.")
    ls = rep.get("ltf_state") or {}
    if ls.get("choch_int"):
        c = ls["choch_int"]
        T.append(f"{ltf}: слом младшего слоя против хода {c['t']:%d.%m %H:%M} (уровень {c['level']:.6g}) — волна A {'вверх' if not st['up'] else 'вниз'}.")
        if ls.get("A"):
            z = ls["zone"]
            T.append(f"Волна A {'закончена (откат подтверждён встречным сломом)' if ls.get('a_done') else 'ещё идёт'}: вершина {ls['a_top']:.6g}. "
                     f"Зона входа на откате: 0.5 {z[0.5]:.6g} · 0.618 {z[0.618]:.6g} · 0.705 {z[0.705]:.6g}; стоп за 0.886 {ls['stop_886']:.6g}. "
                     f"Сейчас цена {'за вершиной A — откат отработан' if ls['retr_now'] is not None and ls['retr_now'] < 0 else f'на откате {ls[chr(114)+chr(101)+chr(116)+chr(114)+chr(95)+chr(110)+chr(111)+chr(119)]:.2f} от A'}.")
    else:
        T.append(f"{ltf}: слома младшего слоя против хода после пятой ещё нет — разворот не подтверждён.")
    if ls.get("choch_sw"):
        T.append(f"{ltf}: слом старшего слоя подтверждён {ls['choch_sw']['t']:%d.%m %H:%M} (уровень {ls['choch_sw']['level']:.6g}).")
    return rep


# ─── схема ──────────────────────────────────────────────────────────────────────────────────────
def render(rep: Dict[str, Any], dh: pd.DataFrame, dl: Optional[pd.DataFrame], out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    BG, FG, GRID, UP, DN, WAVE, ACC, LINE, VIO, GRN = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#ff8f00", "#9575cd", "#66bb6a"

    def candles(ax, w):
        x = np.arange(len(w)); o, h, l, c = (w[k].values.astype(float) for k in ("open", "high", "low", "close"))
        for i in range(len(w)):
            col = UP if c[i] >= o[i] else DN
            ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
            ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, alpha=0.9, lw=0))
        return x

    def style(ax, title):
        ax.set_facecolor(BG); [sp.set_color(GRID) for sp in ax.spines.values()]
        ax.tick_params(colors=FG, labelsize=7.5); ax.grid(True, color=GRID, lw=0.5, alpha=0.5)
        ax.set_title(title, color=FG, fontsize=9.5, loc="left")

    def hline(ax, y, txt, col, ls="--", lw=0.9, xr=None):
        ax.axhline(y, color=col, ls=ls, lw=lw, alpha=0.9)
        ax.annotate(f"{txt} {y:.6g}", (1.0, y), xycoords=("axes fraction", "data"), color=col, fontsize=7, ha="right", va="bottom")

    st, leg = rep["structure"], rep["leg"]
    fig = plt.figure(figsize=(14, 13), facecolor=BG)
    gs = fig.add_gridspec(3, 2, height_ratios=[1, 1.1, 0.95], width_ratios=[1.35, 1], hspace=0.28, wspace=0.12)
    # 1D
    ax1 = fig.add_subplot(gs[0, 0]); dd = to_daily(dh); w = dd.iloc[-200:]; candles(ax1, w)
    style(ax1, f"1D · дневная нога и где закончилась пятая")
    if leg:
        for k, v in leg["levels"].items():
            col = ACC if k in ("0.618", "0.705", "0.79") else VIO
            hline(ax1, v, k, col, ":" if k not in ("0.705",) else "-", 0.8)
        for k, v in leg["extensions"].items():
            hline(ax1, v, k, GRN, "-.", 0.7)
        lo = min(leg["levels"]["0.886"], leg["ext"]); hi = max(leg["levels"]["0.886"], leg["ext"])
        y618, y79 = sorted((leg["levels"]["0.618"], leg["levels"]["0.79"]))
        ax1.axhspan(y618, y79, color=ACC, alpha=0.08)
        xi = w.index.get_indexer([leg["origin_t"]], method="nearest")[0]
        ax1.plot([xi, len(w) - 1], [leg["origin"], leg["ext"]], color=WAVE, lw=1, ls="--", alpha=0.7)
        ax1.annotate(f"пятая: глубина {leg['depth']:.2f} · {leg['zone']}", (0.01, 0.95), xycoords="axes fraction", color=ACC, fontsize=8.5, va="top")
    # 4h
    ax2 = fig.add_subplot(gs[1, 0]); i0 = max(0, st["wave_idx"][0] - 25); w4 = dh.iloc[i0:]; candles(ax2, w4)
    style(ax2, f"4h · {'импульс' if st['kind'] == 'impulse' else 'конечная диагональ · ' + st['form']} 0-5 и цели разворота")
    xs = [i - i0 for i in st["wave_idx"]]; ys = list(st["wave_px"][:5]) + [st["p5x"]]
    ax2.plot(xs, ys, color=WAVE, lw=1.7); ax2.scatter(xs, ys, color=WAVE, s=30, zorder=5)
    for kk, (xk, yk) in enumerate(zip(xs, ys)):
        ax2.annotate(str(kk), (xk, yk), color=WAVE, fontsize=10, fontweight="bold",
                     xytext=(-3, 9 if (kk % 2 == (0 if st["up"] else 1)) else -15), textcoords="offset points")
    if st["kind"] == "diagonal":
        for a_, b_ in ((1, 3), (2, 4)):
            sl_ = (ys[b_] - ys[a_]) / max(1, xs[b_] - xs[a_]); xe = len(w4) - 1
            ax2.plot([xs[a_], xe], [ys[a_], ys[a_] + sl_ * (xe - xs[a_])], color=LINE, lw=1, ls="--")
    for k, v in rep["corr"].items():
        hline(ax2, v, f"коррекция {k}", GRN if k in ("0.5", "0.618") else VIO, "--")
    f5, f6 = sorted((rep["corr"]["0.5"], rep["corr"]["0.618"])); ax2.axhspan(f5, f6, color=GRN, alpha=0.07)
    ax2.annotate("развилка A/B", (0.01, (f5 + f6) / 2), xycoords=("axes fraction", "data"), color=GRN, fontsize=8)
    hline(ax2, rep["price"], "цена", FG, "-", 0.8)
    # LTF
    ax3 = fig.add_subplot(gs[2, 0])
    ls = rep.get("ltf_state") or {}
    if dl is not None and len(dl):
        w3 = dl[dl.index >= st["t5x"] - pd.Timedelta(hours=3)]
        step = max(1, int(np.ceil(len(w3) / 360)))
        if step > 1:
            w3 = w3.resample(pd.Timedelta(w3.index.to_series().diff().median() * step), label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        candles(ax3, w3)
        tfm = int((w3.index.to_series().diff().median()).total_seconds() // 60)
        style(ax3, f"{rep['ltf']} (свечи {tfm}m) · от пятой: слом против хода, волна A, зона отката")
        def _x(tt):
            return int(w3.index.get_indexer([pd.Timestamp(tt)], method="nearest")[0])
        ax3.scatter([_x(st["t5x"])], [st["p5x"]], color=WAVE, s=40, zorder=6); ax3.annotate("5", (_x(st["t5x"]), st["p5x"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
        if ls.get("choch_int"):
            ax3.axvline(_x(ls["choch_int"]["t"]), color=LINE, lw=0.8, ls=":")
        if ls.get("a_t"):
            ax3.scatter([_x(ls["a_t"])], [ls["a_top"]], color=WAVE, s=40, zorder=6); ax3.annotate("A", (_x(ls["a_t"]), ls["a_top"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
        if ls.get("choch_int"):
            c = ls["choch_int"]; hline(ax3, c["level"], "CHoCH младший", LINE, "-", 1.1)
        if ls.get("choch_sw"):
            hline(ax3, ls["choch_sw"]["level"], "CHoCH старший", DN if st["up"] else UP, "-", 1.1)
        if ls.get("A"):
            z = ls["zone"]; ax3.axhspan(min(z[0.5], z[0.705]), max(z[0.5], z[0.705]), color=ACC, alpha=0.12)
            for f_, v in z.items():
                hline(ax3, v, f"A {f_}", ACC, ":")
            hline(ax3, ls["stop_886"], "стоп 0.886", DN, "--")
            hline(ax3, ls["a_top"], "вершина A", WAVE, "-")
    else:
        style(ax3, "младший ТФ не загружен")
    # текст справа
    axt = fig.add_subplot(gs[:, 1]); axt.axis("off"); axt.set_facecolor(BG)
    y = 0.99
    axt.text(0, y, f"{rep['sym']} · волновой разбор", color=FG, fontsize=15, fontweight="bold", va="top"); y -= 0.035
    axt.text(0, y, f"{pd.Timestamp(rep['now']):%d.%m.%Y %H:%M} UTC · цена {rep['price']:.6g}", color="#9aa3b2", fontsize=9, va="top"); y -= 0.035
    import textwrap
    for para in rep["text"]:
        for ln in textwrap.wrap(para, 58):
            axt.text(0, y, ln, color=FG, fontsize=8.8, va="top"); y -= 0.0215
        y -= 0.008
    for sc in rep["scenarios"]:
        y -= 0.01
        axt.text(0, y, sc["name"], color=ACC, fontsize=10.5, fontweight="bold", va="top"); y -= 0.026
        for ln in textwrap.wrap(f"сторона: {sc['side']}. {sc['why']}", 58):
            axt.text(0, y, ln, color=FG, fontsize=8.6, va="top"); y -= 0.0205
        up_ = rep["structure"]["up"]; best = rep.get("best_since5", rep["price"])
        for nm, v in sc["targets"]:
            took = (best <= v) if up_ else (best >= v)
            d = (v / rep["price"] - 1) * 100
            axt.text(0.03, y, f"{'✓' if took else '→'} {nm}: {v:.6g}  " + ("взята" if took else f"({d:+.1f}%)"),
                     color="#6b7485" if took else GRN, fontsize=8.6, va="top", family="monospace"); y -= 0.0195
        if sc.get("fork"):
            axt.text(0.03, y, f"развилка: {min(sc['fork']):.6g} – {max(sc['fork']):.6g}", color=ACC, fontsize=8.6, va="top", family="monospace"); y -= 0.0195
        for ln in textwrap.wrap(f"отмена: {sc['invalid']}", 56):
            axt.text(0.03, y, ln, color=DN, fontsize=8.6, va="top"); y -= 0.0195
    fig.savefig(out, dpi=105, facecolor=BG, bbox_inches="tight"); plt.close(fig)
    return out
