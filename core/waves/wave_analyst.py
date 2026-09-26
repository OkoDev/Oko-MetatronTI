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

from core.smc.oko_sm_engine import run_structure, pivot_points
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


def daily_leg(dh: pd.DataFrame, t0, want_top: bool, p5: float, t5x, now, d_sw: int = 10,
              dd: Optional[pd.DataFrame] = None) -> Optional[Dict[str, Any]]:
    """Дневная нога, которую корректирует 4h-ход: для хода вверх (want_top=True) — нога вниз от дневного свинг-хая, и наоборот.
    Начало — последний подтверждённый к `now` дневной свинг до начала хода t0, лежащий ЗА экстремумом хода p5; если такого нет —
    последний свинг (глубина > 1). Уровни фибо ноги, расширения, глубина и зона экстремума хода."""
    dd = to_daily(dh) if dd is None else dd                    # dd — готовые ЗАКРЫТЫЕ дневные бары (шина: 1D биржи)
    dsw = pivot_points(dd["high"], dd["low"], d_sw)
    cand = [s_ for s_ in dsw if bool(s_[3]) == want_top and dd.index[int(s_[1])] < t0 and dd.index[int(s_[0])] + pd.Timedelta(days=1) <= now]
    beyond = [s_ for s_ in cand if (float(s_[2]) > p5 if want_top else float(s_[2]) < p5)]
    pick = beyond[-1] if beyond else (cand[-1] if cand else None)
    if pick is None:
        return None
    o_i = int(pick[1]); origin = float(pick[2])
    seg = dd.iloc[o_i:]; seg = seg[seg.index <= t5x]
    if seg.empty:
        return None
    ext = float(seg.low.min()) if want_top else float(seg.high.max())       # противоположный конец ноги
    ext_t = seg.low.idxmin() if want_top else seg.high.idxmax()
    # 🔑 начало ноги — НАСТОЯЩИЙ экстремум (Егор 15.09, NCCOPALLADIUM2USD: «не вся нога» — взят свинг 13.07 1210, а ход
    # начался с минимума 25.06 1155). Идём назад по дневным свингам того же типа, что начало: более крайний свинг становится
    # началом, если промежуточный встречный ход между ним и текущим началом — ПОДВОЛНА (не за концом ноги и ≤ 0.618 всей ноги).
    # Граница степени: REDSTONE/SOLV без неё уезжали к январскому хаю — это уже нога старшей степени.
    hi_v, lo_v = dd.high.values.astype(float), dd.low.values.astype(float)
    same = [s_ for s_ in dsw if bool(s_[3]) == want_top and dd.index[int(s_[0])] + pd.Timedelta(days=1) <= now]
    for s_ in reversed([x for x in same if int(x[1]) < o_i]):
        ci, cp = int(s_[1]), float(s_[2])
        if not ((cp > origin) if want_top else (cp < origin)):
            continue
        mid = float(lo_v[ci:o_i + 1].min()) if want_top else float(hi_v[ci:o_i + 1].max())   # встречный ход между ними
        leg_len = abs(cp - ext)
        if ((mid <= ext) if want_top else (mid >= ext)) or abs(mid - cp) > 0.618 * leg_len:
            break
        o_i, origin = ci, cp
    span = abs(origin - ext)
    if span <= 0:
        return None
    depth = abs(p5 - ext) / span; sg = np.sign(origin - ext)
    lvl = {f"{r}": ext + sg * r * span for r in FIB_RET}
    xt = {f"-{r}": ext - sg * r * span for r in FIB_EXT if ext - sg * r * span > 0}
    zone = leg_zone(depth)
    return {"origin": origin, "origin_t": dd.index[o_i], "ext": ext, "ext_t": ext_t, "depth": depth, "zone": zone, "levels": lvl,
            "extensions": xt, "dir": "вниз" if want_top else "вверх", "d_sw": d_sw}


def leg_zone(depth: float) -> str:
    """Зона глубины в дневной ноге — одна формула для разбора, шины и замеров.
    19.09 «все на канон!»: корзины берутся из core.smc.fibonacci.ote_band (те же границы, один источник)."""
    from core.smc.fibonacci import ote_band
    return ote_band(depth)


# ─── ШИНА КУБА (Сфера 20): волновой контекст пары ────────────────────────────────────────────────
# Егор 15.09: «потребителей найдём — боевые на OTE, а OTE детектили нечётко». Замер того же дня
# (memory wave_3m_program): вход ote_nested в OTE 0.62–0.79 дневной ноги аналитика +0.54%/сд против базы +0.32 (SIM,
# перц 98), в мелкой части ноги (<0.5, 55% входов) — хуже базы. SHADOW: публикуем и пишем в features, не гейтим.
def _leg_brief(leg: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not leg:
        return None
    return {"origin": leg["origin"], "origin_t": str(leg["origin_t"])[:10], "ext": leg["ext"], "ext_t": str(leg["ext_t"])[:10],
            "depth": round(leg["depth"], 3), "zone": leg["zone"],
            "ote": [round(leg["levels"]["0.618"], 10), round(leg["levels"]["0.79"], 10)]}


def wave_bus_context(d4: pd.DataFrame, dd: Optional[pd.DataFrame], now: pd.Timestamp) -> Dict[str, Any]:
    """Поля шины по паре. d4 / dd — ЗАКРЫТЫЕ бары 4h и 1D с DatetimeIndex UTC.
    wave_leg_up — дневная нога вверх (контекст откатов для LONG), wave_leg_dn — вниз (для SHORT): глубина текущей цены и зона;
    wave5_setup — последняя завершённая 4h-пятёрка ядра за 5 суток."""
    from core.waves.wave5_core import mark_impulse, WaveParams
    price = float(d4.close.iloc[-1])
    out: Dict[str, Any] = {"wave_ctx_updated_at": now.to_pydatetime() if hasattr(now, "to_pydatetime") else now}
    for key, want_top in (("wave_leg_up", False), ("wave_leg_dn", True)):
        try:
            out[key] = _leg_brief(daily_leg(d4, now, want_top, price, now, now, dd=dd))
        except Exception:
            out[key] = None
    try:
        st = mark_impulse(d4, now, WaveParams(), "4h", lookback=30)
    except Exception:
        st = []
    s = st[0] if st else None
    out["wave5_setup"] = ({"side": s["side"], "top_time": str(s["top_time"])[:16], "p0": s["p0"], "p4": s["p4_target"], "p5": s["p5"],
                           "imp_pct": s["imp_pct"], "core": s["core"], "core_full": s["core_full"]} if s else None)
    return out


def wave_zone_for(state, side: str, price: float) -> Dict[str, Any]:
    """Признаки для features_json сделки из состояния шины (PairState или dict): зона и глубина ЦЕНЫ ВХОДА в дневной ноге
    своей стороны (нога из шины, глубина пересчитана на цену входа), отношение к последней 4h-пятёрке, возраст контекста."""
    g = (lambda k: getattr(state, k, None)) if not isinstance(state, dict) else state.get
    leg = g("wave_leg_up") if side == "LONG" else g("wave_leg_dn")
    upd = g("wave_ctx_updated_at")
    if upd is None:
        return {"wave_ctx": "нет в шине"}
    out: Dict[str, Any] = {"wave_ctx": "ok", "wave_ctx_age_h": round((pd.Timestamp.utcnow() - pd.Timestamp(upd)).total_seconds() / 3600, 1)}
    if leg and price:
        span = abs(leg["origin"] - leg["ext"])
        if span > 0:
            dep = abs(price - leg["ext"]) / span
            out.update(wave_zone_1d=leg_zone(dep), wave_depth_1d=round(dep, 3), wave_leg_origin=leg["origin"], wave_leg_ext=leg["ext"])
    else:
        out["wave_zone_1d"] = "нет ноги"
    s5 = g("wave5_setup")
    out["wave5_rel"] = ("по ходу" if s5["side"] == side else "против") if s5 else "нет"
    out["wave5_core_full"] = bool(s5 and s5.get("core_full"))
    return out


def fit_y(ax, w: pd.DataFrame, extra=(), pad: float = 0.06) -> None:
    """Ось цены по свечам окна + уровни, лежащие рядом (не дальше ×3 вниз / ×1.5 вверх). Размах > 6 раз — лог-шкала
    (Егор 14.09: после взрывного пампа свечи сплющивались в линию, а расширения ноги растягивали ось)."""
    lo, hi = float(w.low.min()), float(w.high.max())
    vals = [float(v) for v in extra if v is not None and np.isfinite(v) and lo / 3 <= float(v) <= hi * 1.5]
    lo2, hi2 = min([lo] + vals), max([hi] + vals)
    if lo2 > 0 and hi2 / lo2 > 6:
        from matplotlib.ticker import FuncFormatter, LogLocator
        ax.set_yscale("log"); ax.set_ylim(lo2 / 1.08, hi2 * 1.08)
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=()))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.4g}"))
    else:
        r = (hi2 - lo2) or abs(hi2) * 0.01
        ax.set_ylim(lo2 - r * pad, hi2 + r * pad)

def decision_card(rep: Dict[str, Any]) -> Dict[str, Any]:
    """Карточка решения (Егор 15.09: «текстом читать долго — в трейдинге нужно быстро всё схватывать»): светофор статуса,
    вход/стоп/цели с % и RR, отмена, второй сценарий строкой, признаки чипами. Только уровни из разбора — ничего не выдумывается;
    стоп и RR — только там, где у механики есть правило стопа (разворот: 0.886 волны A)."""
    price = float(rep.get("price") or 0); sc = rep.get("scenarios") or []; leg = rep.get("leg") or {}
    card: Dict[str, Any] = {"sym": rep["sym"], "price": price, "now": str(rep.get("now", ""))[:16], "entry": None, "stop": None,
                            "targets": [], "invalid": sc[0]["invalid"] if sc else "", "chips": [], "alt": None}
    pct = lambda v: (v / price - 1) * 100 if price else 0.0
    if leg:
        card["chips"].append(f"1D: {leg['zone']} ({leg['depth']:.2f})")
    st = rep.get("structure")
    if st is not None:
        long_ = not st["up"]; card["side"] = "LONG" if long_ else "SHORT"
        ls = rep.get("ltf_state") or {}
        card["chips"] += [f"слом {rep.get('ltf', '3m')} {'✓' if ls.get('choch_int') else '✗'}", f"волна A {'✓' if ls.get('a_done') else '✗'}",
                          "импульс" if st["kind"] == "impulse" else "диагональ"]
        if rep.get("invalid5"):
            iv = rep["invalid5"]
            card.update(light="off", status=f"ПЯТАЯ ОБНОВИЛА {'МАКСИМУМ' if st['up'] else 'МИНИМУМ'} {iv['price']:.5g} — разбор отменён")
        elif ls.get("A"):
            z = ls["zone"]; lo, hi = sorted((z[0.5], z[0.705])); card["entry"] = (lo, hi); card["stop"] = ls["stop_886"]
            r_ = ls.get("retr_now")
            if r_ is None or r_ < 0:
                card.update(light="off", status="откат пропущен — цена ушла за вершину A")
            elif r_ < 0.5:
                card.update(light="wait", status=f"ЖДАТЬ откат в зону (сейчас {r_:.2f} от A)")
            elif r_ <= 0.886:
                card.update(light="go", status=f"ЦЕНА В ЗОНЕ ВХОДА ({r_:.2f} от A)")
            else:
                card.update(light="off", status="откат глубже 0.886 — сценарий сломан")
        else:
            card.update(light="wait", status=f"ЖДАТЬ слом {rep.get('ltf', '3m')} против хода")
    else:
        cnt = rep.get("progress") or {}; zn = rep.get("zone") if isinstance(rep.get("zone"), dict) else None
        k = cnt.get("k"); down = cnt.get("down")
        card["side"] = ("LONG" if down else "SHORT") if (k == 4 and not cnt.get("nested")) else ("SHORT" if down else "LONG")
        card["chips"] += ["счёт 0-1-2-(i)-(ii)" if cnt.get("nested") else (f"счёт 0–{k}" if k is not None else "счёта нет")] + (["треугольник"] if rep.get("triangle") else [])
        if cnt.get("nested") and rep.get("corr_first"):
            fl = rep.get("fork_levels") or {}
            card["side"] = "LONG" if down else "SHORT"        # сторона основного счёта (коррекция к старшей ноге)
            card.update(light="info", status=f"РАЗВИЛКА: коррекция ABC или (iii) из 3 — ждать выход за "
                                             f"{fl.get('third', 0):.5g} / {fl.get('corr', 0):.5g}")
        elif k == 2 or cnt.get("nested"):
            # идёт третья волна: зона — это ЦЕЛИ, а не вход (GRT 15.09: карточка писала «ждать зону +45%»). Вход — по ходу на
            # откатах, стоп — за точкой отмены счёта: (ii) для вложенного, 0 для 0-1-2
            px_ = cnt.get("px") or []
            inv = px_[4] if cnt.get("nested") and len(px_) > 4 else (px_[0] if px_ else None)
            card["stop"] = inv
            card.update(light="wait", status=("ИДЁТ (iii) ИЗ 3" if cnt.get("nested") else "ИДЁТ ВОЛНА 3") +
                        (f" — входы на откатах, отмена за {inv:.5g}" if inv else ""))
        elif zn:
            card["entry"] = (zn["lo"], zn["hi"])
            inside = zn["lo"] <= price <= zn["hi"]
            card.update(light="go" if inside else "wait",
                        status="ЦЕНА В ЗОНЕ — ждать слом младшего ТФ" if inside else f"ЖДАТЬ зону ({pct((zn['lo'] + zn['hi']) / 2):+.1f}% до середины)")
        else:
            card.update(light="info", status="ход в процессе — зоны схождения нет")
    if rep.get("invalid5"):                                  # отменённый разбор: цели и сценарии от старой разметки не показываем
        card.update(invalid="ждать пересчёт разметки на закрытии 4h", taken=[])
        return card
    if sc:
        ent = (sum(card["entry"]) / 2) if card["entry"] else price
        risk = abs(ent - card["stop"]) if card["stop"] else None
        for n, v in sc[0]["targets"]:
            if v is None or v != v:
                continue
            card["targets"].append((n, float(v), pct(v), (abs(v - ent) / risk) if risk else None))
            if len(card["targets"]) == 3:
                break
        # цель уже взята: цена за ней по ходу сделки (REDSTONE 15.09: цель 1 выше цены шорта показывалась как будущая)
        card["taken"] = [(price >= v) if card.get("side") == "LONG" else (price <= v) for _, v, _, _ in card["targets"]]
        if len(sc) > 1:
            t2 = next(((n, v) for n, v in sc[1]["targets"] if v is not None and v == v), None)
            card["alt"] = {"name": sc[1]["name"], "target": t2, "invalid": sc[1]["invalid"]}
        card["name"] = sc[0]["name"]
    return card


def card_figure(card: Dict[str, Any], bg: str = "#0f1116"):
    """Картинка карточки решения ~16:9 — последняя в альбоме."""
    import textwrap
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    FG, MUT, ACC, UP, DN, GRID = "#e6e8ee", "#9aa3b2", "#f5c542", "#26a69a", "#ef5350", "#2a2f3a"
    LIGHT = {"go": ("🟢", UP), "wait": ("🟡", ACC), "off": ("🔴", DN), "info": ("⚪", MUT)}
    f_ = plt.figure(figsize=(10.0, 5.8), facecolor=bg); ax = f_.add_axes([0, 0, 1, 1]); ax.axis("off"); ax.set_facecolor(bg)
    sc = UP if card.get("side") == "LONG" else DN
    ax.text(.04, .92, card["sym"], fontsize=30, fontweight="bold", color=FG, va="center")
    ax.text(.04 + .032 * len(card["sym"]) + .03, .92, card.get("side", ""), fontsize=24, fontweight="bold", color=sc, va="center")
    ax.text(.96, .935, f"{card['price']:.6g}", fontsize=24, color=FG, ha="right", va="center", family="monospace")
    ax.text(.96, .875, f"{card['now']} UTC", fontsize=12, color=MUT, ha="right", va="center")
    _, col = LIGHT.get(card.get("light", "info"))
    ax.add_patch(FancyBboxPatch((.04, .745), .92, .085, boxstyle="round,pad=0.005,rounding_size=0.015", fc=col, ec="none", alpha=.22))
    ax.add_patch(FancyBboxPatch((.04, .745), .012, .085, boxstyle="square,pad=0", fc=col, ec="none"))
    ax.text(.07, .788, card.get("status", ""), fontsize=20, fontweight="bold", color=col, va="center")
    rows = []
    if card.get("entry"):
        lo, hi = card["entry"]; rows.append(("ВХОД", f"{lo:.5g}–{hi:.5g}", "", "", FG))
    if card.get("stop"):
        ent = sum(card["entry"]) / 2 if card.get("entry") else card["price"]
        rows.append(("СТОП", f"{card['stop']:.5g}", f"{(card['stop'] / ent - 1) * 100:+.1f}%", "", DN))
    taken = card.get("taken") or []
    for i, (n, v, p, rr) in enumerate(card.get("targets", []), 1):
        if i <= len(taken) and taken[i - 1]:
            rows.append((f"ЦЕЛЬ {i} ✓", f"{v:.5g}", "взята", "", MUT))
        else:
            rows.append((f"ЦЕЛЬ {i}", f"{v:.5g}", f"{p:+.1f}%", f"RR {rr:.1f}" if rr is not None else "", UP))
    y = .64
    for lab, val, p, rr, c in rows:
        ax.text(.04, y, lab, fontsize=15, color=MUT, va="center")
        ax.text(.17, y, val, fontsize=21, color=c, va="center", family="monospace", fontweight="bold")
        ax.text(.435, y, p, fontsize=16, color=c, va="center", family="monospace", ha="right")
        ax.text(.585, y, rr, fontsize=16, color=ACC, va="center", family="monospace", ha="right")
        y -= .092
    ax.plot([.62, .62], [.14, .69], color=GRID, lw=1.2)
    yy = .66
    if card.get("name"):
        w_ = textwrap.wrap(card["name"], 26)
        ax.text(.65, yy, "\n".join(w_), fontsize=14, color=ACC, fontweight="bold", va="top"); yy -= .055 * len(w_) + .03
    w_ = textwrap.wrap("ОТМЕНА: " + card.get("invalid", ""), 30)
    ax.text(.65, yy, "\n".join(w_), fontsize=13, color=DN, va="top"); yy -= .05 * len(w_) + .07
    alt = card.get("alt")
    if alt:
        w_ = textwrap.wrap(alt["name"], 31)
        ax.text(.65, yy, "\n".join(w_), fontsize=12.5, color=FG, va="top"); yy -= .05 * len(w_) + .015
        if alt.get("target"):
            ax.text(.65, yy, f"→ {alt['target'][0]}: {alt['target'][1]:.5g}", fontsize=12.5, color=MUT, va="top", family="monospace")
    ax.text(.04, .06, "   ·   ".join(card.get("chips", [])), fontsize=14, color=MUT, va="center")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)                   # линия-разделитель не должна менять шкалу
    return f_


def text_figure(rep: Dict[str, Any], title: str, up_: Optional[bool] = None, best: Optional[float] = None, bg: str = "#0f1116"):
    """Четвёртая картинка альбома — разбор текстом, две колонки (Егор 15.09: «три картинки + разбор, всё вместе»):
    подпись альбома в TG ограничена 1024 символами, полный разбор туда не помещается. Кадр ~квадратный — на телефоне крупно."""
    import matplotlib.pyplot as plt
    L, R = build_text_columns(rep, title, up_, best, wrap=46)
    th = text_height_in(L, R)
    f_ = plt.figure(figsize=(10.0, th + 0.4), facecolor=bg)
    draw_text_columns(f_, L, R, 0.2, th)
    return f_


def save_parts(figs, out: Path, bg: str) -> List[Path]:
    """Панели по отдельным файлам <stem>_1.png, _2.png, _3.png (для альбома в TG)."""
    import matplotlib.pyplot as plt
    paths = []
    for i, f_ in enumerate(figs, 1):
        for ax in f_.axes:                                  # кадр вдвое уже общей схемы — запас справа под подписи уровней
            if ax.axison:
                l_, r_ = ax.get_xlim(); ax.set_xlim(l_, r_ + (r_ - l_) * 0.10)
        pth = Path(out).with_name(f"{Path(out).stem}_{i}.png")
        f_.savefig(pth, dpi=PART_DPI, facecolor=bg); plt.close(f_); paths.append(pth)
    return paths


def time_axis(ax, w: pd.DataFrame, nbins: int = 10) -> None:
    """Подписи оси X — дата/время бара вместо номера (Егор 15.09). Правее последнего бара (зона прогноза) время
    продолжается шагом ТФ."""
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    idx = w.index
    if len(idx) < 2:
        return
    step = pd.Timedelta(idx.to_series().diff().median())
    fmt = "%d.%m.%y" if step >= pd.Timedelta(days=1) else "%d.%m %H:%M"

    def lab(x, _):
        k = int(round(x))
        t = idx[0] + step * k if k < 0 else (idx[-1] + step * (k - len(idx) + 1) if k >= len(idx) else idx[k])
        return t.strftime(fmt)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=nbins, integer=True))
    ax.xaxis.set_major_formatter(FuncFormatter(lab))


def draw_micro(ax, w: pd.DataFrame, src: pd.DataFrame, sw_len: int = 50, int_len: int = 5, lbl_len: int = 8,
               up_col: str = "#26a69a", dn_col: str = "#ef5350", fg: str = "#e6e8ee") -> None:
    """Микроструктура на младшем ТФ (Егор 15.09: «15м жалко без микроструктуры»): OKO-SM BOS/CHoCH отрезком от свинга
    до пробоя (internal — тонко, swing — жирно), свинги HH/HL/LH/LL, незакрытые FVG. `w` — хвост `src` (структура
    считается по всему `src`, чтобы был прогрев)."""
    from matplotlib.patches import Rectangle
    off = len(src) - len(w)
    sr = run_structure(src[["open", "high", "low", "close"]].reset_index(drop=True), swing_len=sw_len, internal_len=int_len)
    for e in sr.events:
        if e.i < off or e.level_i is None or e.level_i < 0:
            continue
        col = up_col if e.bull else dn_col
        x0, x1 = max(e.level_i - off, 0), e.i - off
        ax.hlines(e.level, x0, x1, colors=col, linestyles="-" if not e.internal else "--", lw=1.4 if not e.internal else .7, alpha=.9)
        ax.annotate(e.kind if e.internal else e.kind + " swing", ((x0 + x1) / 2, e.level), color=col, ha="center",
                    fontsize=6 if e.internal else 7.5, fontweight="normal" if e.internal else "bold",
                    xytext=(0, 2 if e.bull else -8), textcoords="offset points")
    last = {True: None, False: None}
    for _, si, pr, top in pivot_points(src.high.reset_index(drop=True), src.low.reset_index(drop=True), lbl_len):
        prev, last[top] = last[top], pr
        if si < off or prev is None:
            continue
        tag = ("HH" if pr > prev else "LH") if top else ("HL" if pr > prev else "LL")
        ax.annotate(tag, (si - off, pr), color=fg, alpha=.75, fontsize=6.5, ha="center", xytext=(0, 4 if top else -10), textcoords="offset points")
    h, l = w.high.values.astype(float), w.low.values.astype(float)
    rng = float(np.median(h - l)) or 1e-12
    for k in range(2, len(w)):
        for bull, lo_, hi_ in ((True, h[k - 2], l[k]), (False, h[k], l[k - 2])):
            if hi_ - lo_ < .5 * rng:
                continue
            fut = slice(k + 1, len(w))
            filled = (l[fut] <= lo_).any() if bull else (h[fut] >= hi_).any()
            if not filled:
                ax.add_patch(Rectangle((k - 1, lo_), len(w) - k + 1, hi_ - lo_, color=up_col if bull else dn_col, alpha=.13, lw=0))
                ax.annotate("FVG", (len(w) - 1, (lo_ + hi_) / 2), color=up_col if bull else dn_col, fontsize=6, va="center",
                            xytext=(3, 0), textcoords="offset points")


# ─── текстовый блок схемы: под графиками, две колонки, крупный шрифт (Егор 14.09: «текст крупнее и читабельнее») ───
FIG_W = 16.0
# TG (Егор 15.09: «очень мелко в TG») — каждая панель отдельной картинкой: 8×4.6 дюйма при 225 dpi ≈ 1800×1035 px,
# шрифты относительно кадра вдвое крупнее, чем в общей схеме шириной 16 дюймов
PART_W, PART_H, PART_DPI = 8.0, 4.6, 225
TXT_FS, TXT_H = 12.0, 14.5
LINE_IN = 12.0 * 1.55 / 72          # высота строки основного текста, дюймы


def build_text_columns(rep: Dict[str, Any], title: str, up_: Optional[bool] = None, best: Optional[float] = None, wrap: int = 66):
    """→ (левая колонка «Разбор», правая «Сценарии»): списки (текст, стиль). Стили: h1, meta, h2, body, bullet, target, took, fork, bad."""
    import textwrap
    L = [(title, "h1"), (f"{pd.Timestamp(rep['now']):%d.%m.%Y %H:%M} UTC · цена {rep.get('price', float('nan')):.6g}", "meta"), ("", "gap"),
         ("Разбор", "h2")]
    for para in rep.get("text", []):
        lines = textwrap.wrap(para, wrap - 2)
        for i, ln in enumerate(lines):
            L.append((("• " if i == 0 else "  ") + ln, "body"))
        L.append(("", "small"))
    R = [("Сценарии", "h2")]
    price = rep.get("price") or 0
    for sc in rep.get("scenarios", []):
        R.append(("", "small"))
        for i, ln in enumerate(textwrap.wrap(sc["name"], wrap - 6)):
            R.append((ln, "h3"))
        for ln in textwrap.wrap(f"{sc['side']}. {sc['why']}", wrap):
            R.append((ln, "body"))
        for nm, v in sc["targets"]:
            if v != v:                                               # примечание без цены
                R.append((f"  · {nm}", "took")); continue
            took = best is not None and up_ is not None and ((best <= v) if up_ else (best >= v))
            d = (v / price - 1) * 100 if price else 0
            R.append((f"  {'✓' if took else '→'} {nm}: {v:.6g}  " + ("взята" if took else f"({d:+.1f}%)"), "took" if took else "target"))
        if sc.get("fork"):
            R.append((f"  развилка: {min(sc['fork']):.6g} – {max(sc['fork']):.6g}", "fork"))
        for i, ln in enumerate(textwrap.wrap(f"отмена: {sc['invalid']}", wrap - 2)):
            R.append(("  " + ln, "bad"))
    return L, R


def text_height_in(L, R) -> float:
    def h(col):
        return sum({"h1": 1.7, "meta": 1.1, "h2": 1.55, "h3": 1.3, "gap": .6, "small": .45}.get(st, 1.0) for _, st in col) * LINE_IN
    return max(h(L), h(R)) + 0.4


def draw_text_columns(fig, L, R, bottom_in: float, height_in: float):
    """Рисует две колонки в нижней части фигуры (координаты в дюймах от низа)."""
    BG, FG, ACC, GRN, DN, MUT = "#0f1116", "#e6e8ee", "#f5c542", "#66bb6a", "#ef5350", "#9aa3b2"
    H = fig.get_size_inches()[1]
    sty = {"h1": dict(fontsize=18, color=FG, fontweight="bold"), "meta": dict(fontsize=11, color=MUT),
           "h2": dict(fontsize=14.5, color=ACC, fontweight="bold"), "h3": dict(fontsize=13, color=ACC, fontweight="bold"),
           "body": dict(fontsize=TXT_FS, color=FG), "target": dict(fontsize=TXT_FS, color=GRN, family="monospace"),
           "took": dict(fontsize=TXT_FS, color="#6b7485", family="monospace"), "fork": dict(fontsize=TXT_FS, color=ACC, family="monospace"),
           "bad": dict(fontsize=TXT_FS, color=DN)}
    step = {"h1": 1.7, "meta": 1.1, "h2": 1.55, "h3": 1.3, "gap": .6, "small": .45}
    for col, x0 in ((L, 0.04), (R, 0.53)):
        ax = fig.add_axes([x0, bottom_in / H, 0.45, height_in / H]); ax.axis("off"); ax.set_facecolor(BG)
        y = height_in
        for txt, st in col:
            if txt and st in sty:
                ax.text(0, y / height_in, txt, va="top", transform=ax.transAxes, **sty[st])
            y -= step.get(st, 1.0) * LINE_IN
    fig.add_artist(__import__("matplotlib").lines.Line2D([0.04, 0.97], [(bottom_in + height_in + 0.15) / H] * 2, color="#2a2f3a", lw=1))


# ─── разбор ─────────────────────────────────────────────────────────────────────────────────────
def analyze(sym: str, dh: pd.DataFrame, dl: Optional[pd.DataFrame] = None, ltf: str = "15m",
            now: Optional[pd.Timestamp] = None, p: AnalystParams = AnalystParams(),
            d1: Optional[pd.DataFrame] = None, dl15: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
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
        sw = pivot_points(dhr["high"], dhr["low"], p.sw4h)
        for tt in range(t, max(t - p.lookback, 0), -1):
            dg = diagonal_on_bar(sw, tt, hh, lh)
            if dg:
                st = dg; break
    if st is None:
        if d1 is not None and len(d1) > 400:
            # 🌊 режим «ход в процессе» (Егор 14.09, BCH): счёт незавершённого хода, зона завершения, сценарии
            from core.waves.wave_progress import analyze_progress
            leg_fn = lambda t0_, want_top_, p_ext, t_ext: daily_leg(dh, t0_, want_top_, p_ext, t_ext, now, p.d_sw)
            return analyze_progress(sym, dh, d1, dl15, now, leg_fn, rep, dl3=dl)
        rep["text"].append("На 4h (масштаб ядра) нет завершённой пятёрки или конечной диагонали за последние 15 суток — "
                           "разворотного сценария нет, аналитик молчит.")
        return rep
    # фактический экстремум пятой — по всем барам после неё (он мог обновиться)
    i5 = st["wave_idx"][5]
    if st["up"]:
        k = i5 + int(hh[i5:].argmax()); st["p5x"] = float(hh[k])
    else:
        k = i5 + int(lh[i5:].argmin()); st["p5x"] = float(lh[k])
    st["t5x"] = dh.index[k]
    # точка 0 = крайний экстремум с момента, когда цена последний раз была за концом волны 1: подтверждённый свинг
    # может стоять ниже шпиля, с которого на деле началась нога (RECALL: свинг 0.0526, шпиль 0.0577)
    i0_, i1_ = st["wave_idx"][0], st["wave_idx"][1]; p1_ = float(st["wave_px"][1])
    beyond1 = np.where(lh[:i0_] < p1_)[0] if st["up"] is False else np.where(hh[:i0_] > p1_)[0]
    kb = int(beyond1[-1]) + 1 if len(beyond1) else max(0, i0_ - 60)
    if st["up"]:
        k0 = kb + int(lh[kb:i1_].argmin()); better = lh[k0] < st["wave_px"][0]; v0 = float(lh[k0])
    else:
        k0 = kb + int(hh[kb:i1_].argmax()); better = hh[k0] > st["wave_px"][0]; v0 = float(hh[k0])
    st["p0_detector"] = float(st["wave_px"][0])
    if better and k0 != i0_:
        st["wave_idx"] = [k0] + list(st["wave_idx"][1:]); st["wave_px"] = [v0] + list(st["wave_px"][1:])
        st["p0_moved"] = True
    st["times"] = [dh.index[i] for i in st["wave_idx"]]
    rep["structure"] = st
    g = 1 if st["up"] else -1                             # направление 4h-хода; разворот — против (−g)
    p0, p5 = float(st["wave_px"][0]), st["p5x"]; rng = abs(p5 - p0)
    corr = {f"{r}": p5 - g * r * rng for r in (0.382, 0.5, 0.618, 0.786)}
    rep["corr"] = corr

    # 1D: дневная нога, против которой шёл 4h-ход (для хода вверх — нога вниз от свинг-хая, и наоборот).
    # Начало ноги — последний дневной свинг ЗА экстремумом пятой (пятая его не прошла). Масштаб свинга неоднозначен
    # (SOLV 14.09: свинг 10 дней берёт апрельский шпиль 0.00937, Егор — майский хай 0.00634) → считаем две ноги.
    t0 = st["times"][0]; want_top = st["up"]
    _leg = lambda d_sw: daily_leg(dh, t0, want_top, p5, st["t5x"], now, d_sw)

    leg = _leg(p.d_sw); alt = _leg(5)
    if leg and alt and abs(alt["origin"] - leg["origin"]) / leg["origin"] < 0.01:
        alt = None
    # 🔴 основной ногой всегда свинг d_sw (10 дней): выбор «той, что попала в зону» — подгонка (ревью 14.09); по перемеру v2
    # OTE по свингу 10 держится над контролем по времени (Δ +1.0…+1.4), по свингу 5 — нет (Δ −0.2…−0.3). Нога 5 — справочно.
    rep["leg_alt"] = alt
    rep["leg"] = leg

    # LTF: слом против хода после пятой, волна A и зона отката
    if dl is not None and len(dl) > 300:
        d2 = dl[dl.index >= st["t5x"] - pd.Timedelta(hours=48)]
        base = dl.iloc[max(0, len(dl) - len(d2) - 400):]
        sr = run_structure(base[["open", "high", "low", "close"]].reset_index(drop=True), swing_len=p.ltf_sw, internal_len=p.ltf_il)
        bt = base.index; bh, bl = base.high.values.astype(float), base.low.values.astype(float)
        want_bull = not st["up"]
        # точный экстремум пятой на младшем ТФ внутри её 4h-бара; сломы «после пятой» — строго после него
        j5a = int(np.searchsorted(bt, st["t5x"])); j5b = int(np.searchsorted(bt, st["t5x"] + pd.Timedelta(hours=4)))
        j5 = j5a + int((bh[j5a:j5b].argmax() if not want_bull else bl[j5a:j5b].argmin())) if j5b > j5a else min(j5a, len(bt) - 1)
        evs = [e for e in sr.events if e.bull == want_bull and e.kind == "CHoCH" and e.i > j5]
        ltf_state = {"choch_int": None, "choch_sw": None}
        if evs:
            ei = [e for e in evs if e.internal]; es = [e for e in evs if not e.internal]
            if ei:
                e = ei[0]; ltf_state["choch_int"] = {"t": bt[e.i], "level": float(e.level),
                                                     "t0": bt[e.level_i] if e.level_i is not None and e.level_i >= 0 else bt[e.i]}
                ltf_state["t5"] = bt[j5]                     # точное время экстремума пятой на младшем ТФ
                back = [x for x in sr.events if x.internal and x.bull != want_bull and x.kind == "CHoCH" and x.i > e.i]
                jb = max(back[0].i if back else len(bt) - 1, j5)   # откат B подтверждён встречным сломом → A закончена
                ltf_state["a_done"] = bool(back)
                if want_bull:
                    ka = j5 + int(bh[j5:jb + 1].argmax()); a_top = float(bh[ka]); A = a_top - p5
                    cur_retr = (a_top - float(base.close.iloc[-1])) / A if A > 0 else None
                else:
                    ka = j5 + int(bl[j5:jb + 1].argmin()); a_top = float(bl[ka]); A = p5 - a_top
                    cur_retr = (float(base.close.iloc[-1]) - a_top) / A if A > 0 else None
                if A > 0:
                    sgn = 1 if want_bull else -1
                    z05 = a_top - sgn * 0.5 * A
                    tail = base.iloc[ka + 1:]
                    hit = tail.index[(tail.low <= z05) if want_bull else (tail.high >= z05)]
                    ltf_state["zone_touch_t"] = hit[0] if len(hit) else None
                    stop_886 = a_top - sgn * 0.886 * A
                    # зона живёт до пробоя стопа 0.886 (Егор 18.09: «прямоугольник зоны входа рисовать до сегодня,
                    # пока актуальна»); касание зоны её не гасит — цена может вернуться
                    dead = tail.index[(tail.low <= stop_886) if want_bull else (tail.high >= stop_886)]
                    ltf_state["zone_dead_t"] = dead[0] if len(dead) else None
                    ltf_state.update({"a_top": a_top, "a_t": bt[ka], "A": A, "retr_now": cur_retr,
                                      "zone": {f: a_top - sgn * f * A for f in (0.5, 0.618, 0.705)},
                                      "stop_886": stop_886})
            if es:
                e2 = es[0]
                ltf_state["choch_sw"] = {"t": bt[e2.i], "level": float(e2.level),
                                         "t0": bt[e2.level_i] if e2.level_i is not None and e2.level_i >= 0 else bt[e2.i]}
        rep["ltf_state"] = ltf_state

    # сценарии
    # цена — самый свежий закрытый бар (младший ТФ новее 4h: 15.09 REDSTONE в шапке стояло закрытие 4h 0.1396 при 3m 0.1413)
    fresh = dl is not None and len(dl) and dl.index[-1] > dh.index[-1]
    price = float(dl.close.iloc[-1]) if fresh else float(dh.close.iloc[-1]); rep["price"] = price
    after = dh[dh.index > st["t5x"]]
    rep["best_since5"] = (float(after.low.min()) if st["up"] else float(after.high.max())) if len(after) else price
    rev = "лонг" if not st["up"] else "шорт"
    if leg and leg["depth"] <= 1.0:
        # для 4h-хода вверх разворот — шорт к низу ноги (ext), расширения — дальше; для хода вниз — к хаю ноги
        if st["up"]:
            tg = [("низ дневной ноги", leg["ext"])] + [(f"расширение {k}", v) for k, v in leg["extensions"].items() if k in ("-0.272", "-0.618", "-1.0")]
        else:
            tg = [("хай дневной ноги", leg["ext"])] + [(f"расширение {k}", v) for k, v in leg["extensions"].items() if k in ("-0.272", "-0.618", "-1.0")]
        far = [t_ for t_ in tg if (t_[1] > price * 3) or (t_[1] < price / 3)]
        tg = [t_ for t_ in tg if t_ not in far]
        if far:
            tg.append((f"дальние уровни ноги опущены ({len(far)}): за ×3 от цены", float("nan")))
        rep["scenarios"].append({"name": "A · старший ход продолжается", "side": rev,
                                 "why": f"4h-{st['form']} {'вверх' if st['up'] else 'вниз'} закончился в зоне «{leg['zone']}» дневной ноги {leg['dir']} "
                                        f"(глубина {leg['depth']:.2f}) — это коррекция ноги, её тренд продолжается.",
                                 "targets": [("0.382 4h-хода", corr["0.382"]), ("0.618 4h-хода", corr["0.618"])] + tg,
                                 "invalid": ("выше" if st["up"] else "ниже") + f" начала ноги {leg['origin']:.6g} (глубина 1.0)"})
    fork_mid = (corr["0.5"] + corr["0.618"]) / 2
    rep["forecast"] = {"fork": (corr["0.5"], corr["0.618"]),
                       "A": (leg["ext"], "A · к хаю/низу ноги") if leg and leg["depth"] <= 1.0 else None,
                       "B": (fork_mid + g * 1.0 * rng, "B · волна 3 ≥1.0×w1")}
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
    if st.get("p0_moved"):
        T.append(f"Точка 0 уточнена до экстремума ноги: детектор взял подтверждённый свинг {st['p0_detector']:.6g}, "
                 f"нога началась с {p0:.6g} — коррекции считаются от него.")
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
    # 🔴 АКТУАЛЬНОСТЬ (Егор 15.09, HOME: «разбор актуальность не потерял?»): 4h видит только закрытые бары, а младший ТФ уже
    # может быть за экстремумом пятой — тогда точка 5 не подтверждена (пятая удлиняется), зона A и стоп недействительны.
    if dl is not None and len(dl):
        tail = dl[dl.index >= st["t5x"]]
        if len(tail):
            ext_l = float(tail.high.max()) if st["up"] else float(tail.low.min())
            if (ext_l > p5) if st["up"] else (ext_l < p5):
                t_l = tail.high.idxmax() if st["up"] else tail.low.idxmin()
                rep["invalid5"] = {"t": t_l, "price": ext_l}
                T.insert(1, f"⚠️ РАЗБОР ОТМЕНЁН: на {ltf} цена обновила экстремум пятой — {ext_l:.6g} {'>' if st['up'] else '<'} {p5:.6g} "
                            f"({t_l:%d.%m %H:%M} UTC). Точка 5 не подтверждена (пятая удлиняется или это не конец хода): зона отката A и стоп "
                            f"недействительны, сценарии ниже — от старой разметки, до пересчёта на закрытии 4h.")
    return rep


# ─── схема ──────────────────────────────────────────────────────────────────────────────────────
def render(rep: Dict[str, Any], dh: pd.DataFrame, dl: Optional[pd.DataFrame], out: Path, parts: bool = False):
    """Схема разбора. Правило Егора 14.09: фибо и сломы — ОТРЕЗКАМИ между точками замера (не через весь экран);
    прогноз — штрихпунктирной стрелкой к зоне развилки и двумя пунктирными стрелками вариантов A/B из неё."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, FancyArrowPatch
    BG, FG, GRID, UP, DN, WAVE, ACC, LINE, VIO, GRN = "#0f1116", "#e6e8ee", "#2a2f3a", "#26a69a", "#ef5350", "#8ab4f8", "#f5c542", "#ff8f00", "#9575cd", "#66bb6a"

    def candles(ax, w):
        x = np.arange(len(w)); o, h, l, c = (w[k].values.astype(float) for k in ("open", "high", "low", "close"))
        for i in range(len(w)):
            col = UP if c[i] >= o[i] else DN
            ax.vlines(x[i], l[i], h[i], color=col, lw=0.6, alpha=0.85)
            ax.add_patch(Rectangle((x[i] - 0.32, min(o[i], c[i])), 0.64, max(abs(c[i] - o[i]), (h[i] - l[i]) * 1e-3), color=col, alpha=0.9, lw=0))

    def style(ax, title):
        ax.set_facecolor(BG); [sp.set_color(GRID) for sp in ax.spines.values()]
        ax.tick_params(colors=FG, labelsize=7.5); ax.grid(True, color=GRID, lw=0.5, alpha=0.4)
        ax.set_title((f"{rep['sym']} · " if parts else "") + title, color=FG, fontsize=9.5, loc="left")

    def seg(ax, x0, x1, y, txt, col, ls="--", lw=0.9, side="right"):
        xa, xb = sorted((x0, x1))
        ax.hlines(y, xa, xb, colors=col, linestyles=ls, lw=lw, alpha=0.95)
        if txt:
            ax.annotate(f"{txt} {y:.5g}", (xb if side == "right" else xa, y), color=col, fontsize=6.8,
                        ha="left" if side == "right" else "right", va="center",
                        xytext=(3 if side == "right" else -3, 0), textcoords="offset points")

    def xi(w, tt):
        return int(w.index.get_indexer([pd.Timestamp(tt)], method="nearest")[0])

    def arrow(ax, x0, y0, x1, y1, col, ls, txt=None, lw=1.6):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=14, color=col, lw=lw, linestyle=ls, zorder=7))
        if txt:
            ax.annotate(f"{txt}\n{y1:.5g}", (x1, y1), color=col, fontsize=7.5, fontweight="bold", xytext=(4, 0), textcoords="offset points", va="center")

    st, leg = rep["structure"], rep["leg"]; up_ = st["up"]
    TL, TR = build_text_columns(rep, f"{rep['sym']} · волновой разбор", up_, rep.get("best_since5", rep.get("price")))
    th = text_height_in(TL, TR); CH_H = 12.0; H = CH_H + th + 0.6
    if parts:
        figs = [plt.figure(figsize=(PART_W, PART_H), facecolor=BG) for _ in range(3)]
        axes = [f_.add_axes([0.085, 0.1, 0.88, 0.8]) for f_ in figs]
    else:
        fig = plt.figure(figsize=(FIG_W, H), facecolor=BG)
        gs = fig.add_gridspec(3, 1, height_ratios=[1, 1.2, 0.95], hspace=0.3, left=0.05, right=0.97, top=1 - 0.25 / H, bottom=(th + 0.6) / H)
        axes = [fig.add_subplot(gs[i]) for i in range(3)]

    # 1D: нога, фибо отрезками от начала до конца ноги
    ax1 = axes[0]; dd = to_daily(dh); w = dd.iloc[-200:]; candles(ax1, w)
    style(ax1, "1D · дневная нога (фибо от её начала до конца) и где закончилась пятая")
    if leg:
        xo, xe = xi(w, leg["origin_t"]), xi(w, leg["ext_t"])
        ax1.plot([xo, xe], [leg["origin"], leg["ext"]], color=WAVE, lw=1.1, ls="--", alpha=0.8)
        for k, v in leg["levels"].items():
            seg(ax1, xo, xe, v, k, ACC if k in ("0.618", "0.705", "0.79") else VIO, "-" if k == "0.705" else ":", 0.8, side="left")
        for k, v in leg["extensions"].items():
            seg(ax1, xo, xe, v, k, GRN, "-.", 0.7, side="left")
        y1_, y2_ = sorted((leg["levels"]["0.618"], leg["levels"]["0.79"]))
        ax1.add_patch(Rectangle((min(xo, xe), y1_), abs(xe - xo), y2_ - y1_, color=ACC, alpha=0.10, lw=0))
        x5 = xi(w, st["t5x"]); ax1.scatter([x5], [st["p5x"]], color=WAVE, s=36, zorder=6)
        ax1.annotate(f"5 · глубина {leg['depth']:.2f} · {leg['zone']}", (x5, st["p5x"]), color=ACC, fontsize=8,
                     xytext=(-6, -14 if not up_ else 8), textcoords="offset points", ha="right")
    ax1.set_xlim(-12, len(w) + 8)
    fit_y(ax1, w, (list(leg["levels"].values()) + list(leg["extensions"].values()) + [st["p5x"]]) if leg else [st["p5x"]])
    time_axis(ax1, w)

    # 4h: счёт, коррекции отрезком 0→5, развилка, прогноз стрелками
    ax2 = axes[1]; i0 = max(0, st["wave_idx"][0] - 25); w4 = dh.iloc[i0:]; candles(ax2, w4)
    style(ax2, f"4h · {'импульс' if st['kind'] == 'impulse' else 'конечная диагональ · ' + st['form']} 0-5 · прогноз из зоны развилки")
    xs = [i - i0 for i in st["wave_idx"]]; ys = list(st["wave_px"][:5]) + [st["p5x"]]; xs[5] = xi(w4, st["t5x"])
    ax2.plot(xs, ys, color=WAVE, lw=1.7); ax2.scatter(xs, ys, color=WAVE, s=30, zorder=5)
    for kk, (xk, yk) in enumerate(zip(xs, ys)):
        ax2.annotate(str(kk), (xk, yk), color=WAVE, fontsize=10, fontweight="bold",
                     xytext=(-3, 9 if (kk % 2 == (0 if up_ else 1)) else -15), textcoords="offset points")
    if st["kind"] == "diagonal":
        for a_, b_ in ((1, 3), (2, 4)):
            ax2.plot([xs[a_], xs[b_]], [ys[a_], ys[b_]], color=LINE, lw=1, ls="--")
    for k, v in rep["corr"].items():
        seg(ax2, xs[0], xs[5], v, f"{k}", GRN if k in ("0.5", "0.618") else VIO, "--", 0.8, side="left")
    n4 = len(w4) - 1; F = max(18, int(0.45 * len(w4)))
    fc = rep.get("forecast") or {}
    lo, hi = sorted(fc.get("fork", (rep["corr"]["0.5"], rep["corr"]["0.618"])))
    xf0, xf1 = n4 + int(F * 0.30), n4 + int(F * 0.45)
    ax2.add_patch(Rectangle((xf0, lo), xf1 - xf0, hi - lo, color=GRN, alpha=0.18, lw=0))
    ax2.annotate("развилка A/B", (xf0, hi), color=GRN, fontsize=8, xytext=(0, 3), textcoords="offset points")
    ym = (lo + hi) / 2; price = rep["price"]
    ax2.scatter([n4], [price], color=FG, s=18, zorder=6)
    arrow(ax2, n4, price, xf0, ym, FG, "-.", None, 1.3)                       # штрихпунктир — путь к развилке
    if fc.get("A"):
        ya, ta = fc["A"]; arrow(ax2, xf1, ym, n4 + F, ya, ACC, "--", ta)       # пунктир — вариант A
    if fc.get("B"):
        yb, tb = fc["B"]; arrow(ax2, xf1, ym, n4 + int(F * 0.9), yb, DN if not up_ else UP, "--", tb)
    ax2.set_xlim(-12, n4 + F + 34)
    fit_y(ax2, w4, list(rep["corr"].values()) + [price, lo, hi] + [v[0] for v in (fc.get("A"), fc.get("B")) if v])
    time_axis(ax2, w4)

    # младший ТФ: сломы от свинга до пересечения, фибо A отрезком 5→A, зона от A до касания
    ax3 = axes[2]; ls = rep.get("ltf_state") or {}
    if dl is not None and len(dl):
        w3 = dl[dl.index >= st["t5x"] - pd.Timedelta(hours=3)]
        step = max(1, int(np.ceil(len(w3) / 360)))
        if step > 1:
            w3 = w3.resample(pd.Timedelta(w3.index.to_series().diff().median() * step), label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        candles(ax3, w3); n3 = len(w3) - 1
        if step == 1:
            draw_micro(ax3, w3, dl, up_col=UP, dn_col=DN, fg=FG)
        tfm = int((w3.index.to_series().diff().median()).total_seconds() // 60)
        style(ax3, f"{rep['ltf']} (свечи {tfm}m) · от пятой: слом, волна A, зона отката")
        x5 = xi(w3, ls.get("t5", st["t5x"])); ax3.scatter([x5], [st["p5x"]], color=WAVE, s=40, zorder=6)
        ax3.annotate("5", (x5, st["p5x"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
        for key_, nm, col in (("choch_int", "CHoCH", LINE), ("choch_sw", "CHoCH старший", UP if not up_ else DN)):
            c = ls.get(key_)
            if c:
                seg(ax3, xi(w3, c["t0"]), xi(w3, c["t"]), c["level"], nm, col, "-", 1.2)
        if ls.get("A"):
            xa = xi(w3, ls["a_t"]); ax3.scatter([xa], [ls["a_top"]], color=WAVE, s=40, zorder=6)
            ax3.annotate("A", (xa, ls["a_top"]), color=WAVE, fontsize=10, fontweight="bold", xytext=(4, 0), textcoords="offset points")
            ax3.plot([x5, xa], [st["p5x"], ls["a_top"]], color=WAVE, lw=1, alpha=0.8)
            z = ls["zone"]
            for f_, v in z.items():
                seg(ax3, x5, xa, v, f"{f_}", ACC, ":", 0.9, side="left")
            # прямоугольник зоны — до сегодня (последний бар), пока зона жива; гаснет только пробоем стопа 0.886
            xt_ = xi(w3, ls["zone_dead_t"]) if ls.get("zone_dead_t") is not None else n3
            ax3.add_patch(Rectangle((xa, min(z[0.5], z[0.705])), max(1, xt_ - xa), abs(z[0.5] - z[0.705]), color=ACC, alpha=0.22, lw=0))
            seg(ax3, xa, n3, ls["stop_886"], "стоп 0.886", DN, "--", 0.9)
        ax3.set_xlim(-25, n3 + 30)
        fit_y(ax3, w3, [st["p5x"]] + ([ls["a_top"], ls["stop_886"]] + list(ls["zone"].values()) if ls.get("A") else []))
        time_axis(ax3, w3)
    else:
        style(ax3, "младший ТФ не загружен")

    if parts:
        figs.append(card_figure(decision_card(rep), BG))
        return save_parts(figs, out, BG)
    draw_text_columns(fig, TL, TR, 0.2, th)
    fig.savefig(out, dpi=115, facecolor=BG); plt.close(fig)
    return out


def report_for(sym: str, ltf: str = "3m", out_dir: Optional[Path] = None, now: Optional[pd.Timestamp] = None,
               parts: bool = False) -> Dict[str, Any]:
    """Разбор под ключ: свечи BingX v3 → analyze → схема + json + md в out_dir (по умолчанию data/wave_analyst).
    Возвращает сводку: png/json имена, есть ли структура, зона пятой, сценарии, текст."""
    import json as _json
    from core.waves.bingx_klines import fetch_closed
    now = now or pd.Timestamp.utcnow()
    out_dir = Path(out_dir or Path(__file__).resolve().parents[2] / "data" / "wave_analyst"); out_dir.mkdir(parents=True, exist_ok=True)
    base = sym.split("/")[0].split(":")[0].upper()
    dh = fetch_closed(base, "4h", 1500, now=now)
    dl = fetch_closed(base, ltf, {"1m": 12000, "3m": 5000, "5m": 3000, "15m": 1500}.get(ltf, 1500), now=now)
    d1 = fetch_closed(base, "1h", 1500, now=now); dl15 = fetch_closed(base, "15m", 600, now=now)
    rep = analyze(base, dh, dl, ltf, now=now, d1=d1, dl15=dl15)
    stem = f"{base}_{now:%Y%m%d_%H%M}"
    png = None; part_names = []
    if rep["structure"] is not None:
        render(rep, dh, dl, out_dir / f"{stem}.png"); png = f"{stem}.png"
        if parts:
            part_names = [x.name for x in render(rep, dh, dl, out_dir / f"{stem}.png", parts=True)]
    elif rep.get("mode") == "progress" and rep.get("progress"):
        from core.waves.wave_progress import render_progress
        render_progress(rep, dh, d1, dl15, out_dir / f"{stem}.png", dl3=dl); png = f"{stem}.png"
        if parts:
            part_names = [x.name for x in render_progress(rep, dh, d1, dl15, out_dir / f"{stem}.png", dl3=dl, parts=True)]
    clean = {k: v for k, v in rep.items() if k != "structure"}
    clean["scenarios"] = [{**sc, "targets": [(n, (v if v == v else None)) for n, v in sc["targets"]]} for sc in rep.get("scenarios", [])]
    if rep["structure"] is not None:
        st = rep["structure"]
        clean["structure"] = {"kind": st["kind"], "form": st["form"], "up": st["up"], "p0": st["wave_px"][0], "p5": st["p5x"], "t5": str(st["t5x"])}
    (out_dir / f"{stem}.json").write_text(_json.dumps(clean, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    leg = rep.get("leg") or {}
    ls = rep.get("ltf_state") or {}; cnt = rep.get("progress") or {}; tri = rep.get("triangle") or {}
    zn = rep.get("zone") if isinstance(rep.get("zone"), dict) else None
    # отпечаток разбора — для постов-обновлений в TG ответом на прошлую версию (core.waves.wave_tg.state_diff)
    state = {"mode": rep.get("mode", "reversal"), "zone_1d": leg.get("zone"),
             "p5": float(rep["structure"]["p5x"]) if rep["structure"] is not None else None,
             "choch": float(ls["choch_int"]["level"]) if ls.get("choch_int") else None,
             "choch_sw": float(ls["choch_sw"]["level"]) if ls.get("choch_sw") else None,
             "a_done": bool(ls.get("a_done")), "zone_touch": ls.get("zone_touch_t") is not None,
             "count_k": cnt.get("k"), "count_px": [float(x) for x in cnt.get("px", [])],
             "zone_lo": float(zn["lo"]) if zn else None, "zone_hi": float(zn["hi"]) if zn else None,
             "tri": f"{tri['tf']} {tri['kind']} · цена {tri['breakout']}" if tri else None,
             "invalid5": bool(rep.get("invalid5")),
             "scen": [sc["name"] for sc in rep.get("scenarios", [])]}
    return {"sym": base, "png": png, "json": f"{stem}.json", "has": rep["structure"] is not None, "mode": rep.get("mode", "reversal"), "zone": leg.get("zone"),
            "state": state, "parts": part_names, "now": rep.get("now"), "card": decision_card(rep),
            "depth": round(leg["depth"], 3) if leg else None, "text": rep["text"], "price": rep.get("price"),
            "scenarios": [{"name": sc["name"], "side": sc.get("side"), "why": sc.get("why"), "fork": sc.get("fork"),
                           "targets": [(n, (float(v) if v == v else None)) for n, v in sc["targets"]], "invalid": sc["invalid"]} for sc in rep["scenarios"]]}
