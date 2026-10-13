# -*- coding: utf-8 -*-
"""MTF-КАРТОЧКА ЗОН ИНТЕРЕСА — прототип метода Егора (09.10.2026, «да давай тест на BTC»).

Метод (память feedback_whole_picture_multitf_impulse): импульс ищется на ВСЕХ ТФ; зона интереса = место, где сходятся
факторы; всегда две стороны (лонг / шорт / вправо) и «если зону провалили → следующая зона старшего ТФ».
Собрано из готового (опись — память mtf_analysis_components_inventory), новое — только три недостающих куска:
  каскад импульса по ТФ · профиль объёма · обе стороны со следующей зоной.

Факторы зоны (имя, цена, вес; вес растёт со степенью ТФ):
  откаты 0.5/0.618/0.705/0.79 каждого действующего импульса (1D 2.0 · 4h 1.5 · 1h 1.0 · 15m 0.5) и его начало;
  проекции волны C = 1.0/1.272/1.618 × A после импульса; FVG и ордер-блоки 4h (живые) — обе границы;
  пивоты D/W/M (вес 0.5/1/1.5); равные вершины/днища 4h (пулы ликвидности); профиль объёма 1h за 30 дней — POC и узлы.
Зона = ближайшее к цене окно, где сошлось ≥ 3 разных источников (семей); вес считается по семьям. Только закрытые бары.
Запуск: python scripts/mtf_zone_card.py --sym BTC [--out data/mtf_card]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:  # молчим: настройка кодировки консоли, на расчёт не влияет
    pass
from core.infra.market_store import read_bars                     # noqa: E402
from core.waves.wave5_core import impulses_on_bar                  # noqa: E402
from core.smc.oko_sm_engine import pivot_points                    # noqa: E402
from core.structure.zones import fair_value_gaps, order_blocks, equal_levels   # noqa: E402
from core.structure.levels import level_breaks                     # noqa: E402
from core.indicators.indicators import calculate_pivot_points      # noqa: E402

RET = (0.5, 0.618, 0.705, 0.79)
TFD = {"1w": "1W", "1d": "1D", "4h": "4h", "1h": "1h", "15m": "15m"}
# Два взгляда одним кодом (Егор 09.10: «давай старшие ТФ посмотрим так же — картину глобальнее»).
PROFILES = {
    "local": dict(scales=[("1d", 5, 200, 2.0), ("4h", 15, 400, 1.5), ("4h", 8, 400, 1.5), ("1h", 12, 700, 1.0),
                          ("15m", 12, 900, 0.5)],
                  fvg=[("4h", 0.75, 360)], ob=("4h", 10, 0.75, 360), eq=("4h", 360),
                  pivots=[("D", "D", 0.5), ("W-SUN", "W", 1.0), ("M", "M", 1.5)],
                  vp=("1h", 30, 0.25), zone_w=0.025, far=0.30, chart=("4h", 45), s_min=3.0),
    "global": dict(scales=[("1w", 3, 150, 3.0), ("1w", 5, 150, 3.0), ("1d", 10, 500, 2.0), ("1d", 5, 500, 2.0),
                           ("4h", 30, 2000, 1.5)],
                   fvg=[("1w", 1.5, 120), ("1d", 1.0, 500)], ob=("1d", 10, 1.0, 500), eq=("1d", 500),
                   pivots=[("M", "M", 1.0), ("Q", "Q", 1.5), ("Y", "Y", 2.0)],
                   vp=("1d", 365, 0.5), zone_w=0.05, far=0.60, chart=("1d", 480), s_min=3.5),
}


def bars(base: str, tf: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    if tf == "1w":                                   # недели — из дневок BingX, неделя с понедельника
        d = read_bars(base, "1d")
        if d.index.tz is not None:
            d.index = d.index.tz_convert(None)
        if now is not None:
            d = d[d.index + pd.Timedelta("1D") <= now]
        w = d.resample("W-MON", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        lim = now if now is not None else w.index[-1] + pd.Timedelta("7D")
        return w[w.index + pd.Timedelta("7D") <= lim]
    d = read_bars(base, tf)
    if d.index.tz is not None:
        d.index = d.index.tz_convert(None)
    step = pd.Timedelta(tf.replace("m", "min").replace("1d", "1D"))
    if now is not None:
        d = d[d.index + step <= now]                 # только закрытые к моменту
    return d


def impulses(d: pd.DataFrame, sw: int, scan: int) -> dict:
    """Последний пятиволновый импульс вверх и вниз на этом масштабе (merge=True — поглощение подструктуры)."""
    r = d.reset_index(drop=True)
    if len(r) < 4 * sw + 20:
        return {}
    S = pivot_points(r["high"], r["low"], sw)
    hh, lh = r.high.values.astype(float), r.low.values.astype(float)
    out = {}
    for tt in range(len(r) - 1, max(len(r) - 1 - scan, 0), -1):
        for imp in impulses_on_bar(S, tt, hh, lh, merge=True):
            k = imp["direction"]
            if k not in out:
                out[k] = {"waves": [(d.index[int(i)], float(px)) for i, px in imp["waves"]], "sw_pivots": S,
                          "i5": int(imp["waves"][5][0])}
        if len(out) == 2:
            break
    return out


def abc_after(d: pd.DataFrame, imp: dict, up: bool, sw: int) -> dict | None:
    """A — первый подтверждённый встречный свинг после пятой, B — следующий свинг, C — крайняя цена после B (текущая).
    Свинги коррекции — втрое крупнее подволн импульса: на масштабе подволн за A бралась мелкая ямка (BTC 22.09 85 077,
    «C = 3×A»), а Егор считает A/B на 28.09 и 02.10."""
    r = d.reset_index(drop=True)
    S, i5 = pivot_points(r["high"], r["low"], 3 * sw), imp["i5"]
    after = [s for s in S if int(s[1]) > i5]
    first = next((s for s in after if bool(s[3]) == (not up)), None)   # первый крупный встречный свинг — коррекция началась
    if first is None:
        return None
    # C — крайняя цена после него (текущая); B — крайняя точка в сторону импульса между первым свингом и C;
    # A — крайняя встречная точка между пятой и B (Егор, BTC: A 28.09 82 540 · B 02.10 87 200 · C 08.10 80 355)
    seg = d.iloc[int(first[1]):]
    i_c = int(np.argmin(seg.low.values)) if up else int(np.argmax(seg.high.values))
    c = float(seg.low.values[i_c]) if up else float(seg.high.values[i_c])
    mid = seg.iloc[:i_c + 1]
    if len(mid) < 3:
        return None
    i_b = int(np.argmax(mid.high.values)) if up else int(np.argmin(mid.low.values))
    B = float(mid.high.values[i_b]) if up else float(mid.low.values[i_b])
    ab = d.iloc[i5 + 1:int(first[1]) + i_b + 1]
    if ab.empty:
        return None
    A = float(ab.low.min()) if up else float(ab.high.max())
    p5 = imp["waves"][5][1]
    if (up and not (A < B and c < B)) or ((not up) and not (A > B and c > B)):
        return None
    return {"A": A, "A_t": ab.low.idxmin() if up else ab.high.idxmax(), "B": B, "B_t": mid.index[i_b], "C": c,
            "C_t": seg.index[i_c], "len_A": abs(p5 - A),
            "C_ratio": abs(B - c) / abs(p5 - A) if p5 != A else np.nan}


def volume_profile(d1h: pd.DataFrame, days: int = 30, bin_pct: float = 0.25):
    w = d1h[d1h.index >= d1h.index[-1] - pd.Timedelta(days=days)]
    lo, hi = float(w.low.min()), float(w.high.max())
    step = lo * bin_pct / 100
    edges = np.arange(lo, hi + step, step)
    vol = np.zeros(len(edges) - 1)
    for l_, h_, v in zip(w.low.values, w.high.values, w.volume.values):
        a, b = np.searchsorted(edges, l_, "right") - 1, np.searchsorted(edges, h_, "right") - 1
        a, b = max(a, 0), min(b, len(vol) - 1)
        vol[a:b + 1] += v / (b - a + 1)
    mids = (edges[:-1] + edges[1:]) / 2
    poc = float(mids[int(np.argmax(vol))])
    thr = np.quantile(vol, 0.80)
    hvn = [float(mids[i]) for i in range(1, len(vol) - 1) if vol[i] >= thr and vol[i] >= vol[i - 1] and vol[i] >= vol[i + 1]]
    return {"mids": mids, "vol": vol, "poc": poc, "hvn": hvn}


def prev_pivots(d1d: pd.DataFrame, freq: str, now: pd.Timestamp) -> dict:
    """Классические пивоты по ПОСЛЕДНЕМУ ЗАВЕРШЁННОМУ периоду (D / W-SUN / M / Q / Y) из закрытых дневок.
    🔴 12.10: было `resample(...).iloc[-2]` — но в закрытых дневках последняя группа УЖЕ завершённый период, если новый
    ещё не дал ни одной закрытой дневки. Дневные пивоты всегда считались от позавчера, недельные/месячные — в первый
    день периода от периода до прошлого (понедельник 12.10: неделя 28.09–04.10 вместо 05–11.10). Поймано вопросом Егора
    «как ложится на недельные пивоты?». Теперь период определяется календарём: всё, что раньше периода, где лежит now."""
    per = d1d.index.to_period(freq)
    cur = pd.Timestamp(now).to_period(freq)
    done = d1d[per < cur]
    if done.empty:
        return {}
    last = done[done.index.to_period(freq) == done.index.to_period(freq).max()]
    out = calculate_pivot_points(float(last.high.max()), float(last.low.min()), float(last.close.iloc[-1]))
    out["_period"] = f"{last.index[0]:%d.%m.%y}–{last.index[-1]:%d.%m.%y}"
    return out


HUB = "http://127.0.0.1:8020"                     # хаб шины Куба (pm2 cube-hub, ADR-003)


def bus_pivots(base: str) -> dict:
    """Пивоты D/W/M из ШИНЫ (Егор 12.10: «пивоты в шине») — те же, что видит бот; свои не считаем (reuse).
    Пара в шине — BASE/USDT:USDT. Хаб недоступен → пустой словарь, тогда запасной расчёт prev_pivots."""
    import json
    import urllib.parse
    import urllib.request
    try:
        url = f"{HUB}/state/" + urllib.parse.quote(f"{base}/USDT:USDT", safe="")
        st = json.load(urllib.request.urlopen(url, timeout=3))
        snap = (st.get("state", st) or {}).get("pivot_snap") or {}
        return {lab: snap[k] for k, lab in (("1D", "D"), ("1W", "W"), ("1M", "M")) if isinstance(snap.get(k), dict)}
    except Exception as e:                          # noqa: BLE001
        print(f"[пивоты] шина недоступна ({type(e).__name__}) — считаю сам из дневок")
        return {}


def family(name: str) -> str:
    """Семья источника. 12.10 (самопроверка): семь дневных пивотов узкого воскресенья (R3…S3 в полосе 2%) считались
    семью факторами и рисовали «зону» вплотную к цене. Один источник — один фактор, берётся самый весомый уровень."""
    if name.startswith("пивот "):
        return " ".join(name.split()[:2])                 # «пивот D»
    if name.startswith("профиль объёма"):
        return "профиль объёма"
    if name.startswith("откат "):
        return "откат " + name.split(" ", 2)[2]           # «откат импульса ↑ 1h sw12»
    if name.startswith("C = "):
        return "C " + name[name.index("("):]
    return name


def fam_best(inside: list) -> dict:
    best = {}
    for n, p_, w in inside:
        f = family(n)
        if f not in best or w > best[f][2]:
            best[f] = (n, p_, w)
    return best


def n_src(z: dict) -> int:
    """Сколько разных источников (семей) в зоне."""
    return len(fam_best(z["levels"]))


def zones_by_distance(levels: list, px: float, down: bool, zone_w: float, s_min: float = 3.0, n_min: int = 3,
                      k: int = 3) -> list:
    """Зоны по порядку удаления от цены (Егор: «провалят эту → следующая 76 и ниже»): ближайшая ЗНАЧИМАЯ, затем следующая.
    Окно шириной zone_w от ближайшего уровня в сторону от цены; вес зоны = сумма по СЕМЬЯМ (лучший уровень семьи),
    значима при весе ≥ s_min и семей ≥ n_min. Идея окна — как у wave_progress.cluster_zone, счёт — по семьям."""
    out, ref = [], px
    while len(out) < k:
        cand = sorted([l for l in levels if (l[1] < ref if down else l[1] > ref)], key=lambda l: abs(l[1] - ref))
        z = None
        for _, v0, _ in cand:
            lo, hi = (v0 - zone_w * px, v0) if down else (v0, v0 + zone_w * px)
            inside = [l for l in cand if lo <= l[1] <= hi]
            fb = fam_best(inside)
            sc = sum(w for _, _, w in fb.values())
            if sc >= s_min and len(fb) >= n_min:
                vs = [l[1] for l in inside]
                z = {"lo": min(vs), "hi": max(vs), "mid": float(np.mean(vs)), "score": sc, "levels": inside}
                break
        if z is None:
            break
        out.append(z)
        ref = z["lo"] if down else z["hi"]
    return out


def build(base: str, view: str = "local") -> dict:
    P = PROFILES[view]
    d1h = bars(base, "1h")
    now = d1h.index[-1] + pd.Timedelta("1h")
    D = {tf: bars(base, tf, now) for tf in ("1w", "1d", "4h", "1h", "15m")}
    px = float(D["1h"].close.iloc[-1])
    levels = {"LONG": [], "SHORT": []}

    def add(name, price, w, side=None):
        """side — чей это уровень по смыслу. 12.10 (самопроверка): без него откат импульса ВНИЗ после подъёма цены
        попадал в ЛОНГ-зону как «поддержка», и зоны сливались вплотную к цене. Чужая сторона → уровень не берём."""
        if not (price and np.isfinite(price) and abs(price / px - 1) < P["far"]):
            return
        pos_side = "LONG" if price < px else "SHORT"
        if side is None or side == pos_side:
            levels[pos_side].append((name, float(price), float(w)))

    found = []
    for tf, sw, scan, w in P["scales"]:
        if len(D[tf]) < 4 * sw + 20:
            continue
        imps = impulses(D[tf], sw, scan)
        for dirn, imp in imps.items():
            up = dirn == "up"
            p0, p5 = imp["waves"][0][1], imp["waves"][5][1]
            after = D[tf][D[tf].index > imp["waves"][5][0]]
            beyond = (after.high.max() > p5) if up else (after.low.min() < p5)
            broken = (after.low.min() < p0) if up else (after.high.max() > p0)
            rec = {"tf": tf, "sw": sw, "dir": dirn, "waves": imp["waves"], "range_pct": abs(p5 - p0) / min(p0, p5) * 100,
                   "valid": bool(not beyond and not broken), "depth": abs(px - p5) / abs(p5 - p0),
                   "ote_edge": p5 - (1 if up else -1) * 0.5 * abs(p5 - p0)}
            found.append(rec)
            if not rec["valid"]:
                continue
            tag = f"{TFD[tf]} sw{sw}"
            sd_ = "LONG" if up else "SHORT"
            for f in (0.382,) + RET:           # 0.382 — мелкая коррекция, вес ниже зоны OTE 0.5–0.79
                add(f"откат {f} импульса {'↑' if up else '↓'} {tag}", p5 - (1 if up else -1) * f * abs(p5 - p0),
                    w * (0.6 if f == 0.382 else 1.0), sd_)
            add(f"начало импульса {'↑' if up else '↓'} {tag}", p0, w * 0.8, sd_)
            abc = abc_after(D[tf], imp, up, sw)
            rec["abc"] = abc
            if abc:
                for k in (1.0, 1.272, 1.618):
                    add(f"C = {k}×A ({tag})", abc["B"] - (1 if up else -1) * k * abc["len_A"], w * 0.8, sd_)
    # FVG, ордер-блоки, равные уровни: живые на момент, за последние recent баров своего ТФ
    fvgs = []
    for tf, w, recent in P["fvg"]:
        dd_ = D[tf]
        for g in fair_value_gaps(dd_.reset_index(drop=True)):
            if g.filled_bar == -1 and g.bar >= len(dd_) - recent:
                name = f"FVG {TFD[tf]} {'↑' if g.bullish else '↓'} {dd_.index[g.bar]:%d.%m.%y}"
                fvgs.append({"t": dd_.index[g.bar], "top": g.top, "bottom": g.bottom, "bullish": g.bullish, "tf": tf,
                             "name": name})
                for edge in (g.top, g.bottom):
                    add(name, edge, w / 2, "LONG" if g.bullish else "SHORT")   # одна FVG = один источник
    tf, win, w, recent = P["ob"]
    dd_ = D[tf]; r_ = dd_.reset_index(drop=True)
    obs = [b for b in order_blocks(r_, level_breaks(r_, window=win)) if b.gone_bar == -1 and b.origin_bar >= len(dd_) - recent]
    for b in obs:
        for edge in (b.top, b.bottom):
            add(f"OB {TFD[tf]} {'↑' if b.bullish else '↓'} {dd_.index[b.origin_bar]:%d.%m.%y}", edge, w / 2,
                "LONG" if b.bullish else "SHORT")
    tf, recent = P["eq"]
    dd_ = D[tf]
    for e in [e for e in equal_levels(dd_.reset_index(drop=True)) if e.second_bar >= len(dd_) - recent]:
        add(f"{'равные вершины' if e.highs else 'равные днища'} {TFD[tf]} (ликвидность)",
            (e.first_price + e.second_price) / 2, 1.0, "SHORT" if e.highs else "LONG")
    piv = {}
    bus = bus_pivots(base)
    for rule, lab, w in P["pivots"]:
        pv = bus.get(lab) or prev_pivots(D["1d"], rule, now)     # Q и Y в шине нет — считаются из дневок
        piv["_src_" + lab] = "шина" if lab in bus else "дневки"
        piv[lab] = pv
        for k in ("PP", "S1", "S2", "S3", "R1", "R2", "R3"):
            if k in pv:
                add(f"пивот {lab} {k}", pv[k], w)
    piv_all = {lab: pv for lab, pv in piv.items() if not lab.startswith("_")}   # для опции --pivots: + недельные
    if "W" not in piv_all:
        piv_all["W"] = bus.get("W") or prev_pivots(D["1d"], "W-SUN", now)
        piv["_src_W"] = "шина" if "W" in bus else "дневки"
    vtf, vdays, vbin = P["vp"]
    vp = volume_profile(D[vtf], vdays, vbin)
    vp["label"] = f"объём {vdays}д"
    add(f"профиль объёма {vdays}д: POC", vp["poc"], 1.5)
    for h in vp["hvn"]:
        if abs(h / vp["poc"] - 1) > vbin / 100 * 1.5:
            add(f"профиль объёма {vdays}д: узел", h, 1.0)

    zones = {}
    for side, down in (("LONG", True), ("SHORT", False)):
        zl = zones_by_distance(levels[side], px, down, P["zone_w"], s_min=P["s_min"])
        # цена уже ВНУТРИ OTE импульса этой стороны (откат 0.5–0.79): уровень 0.5 пройден и в уровни не попал —
        # возвращаем его границей зоны 1, иначе карточка пишет «между зонами», когда цена в зоне
        for rec in found:
            if rec["valid"] and (rec["dir"] == "up") == down and 0.5 <= rec["depth"] <= 0.79 and zl:
                z0 = zl[0]
                if down and z0["hi"] < rec["ote_edge"]:
                    z0["hi"] = rec["ote_edge"]
                elif (not down) and z0["lo"] > rec["ote_edge"]:
                    z0["lo"] = rec["ote_edge"]
                z0["entered"] = f"OTE импульса {'↑' if rec['dir'] == 'up' else '↓'} {TFD[rec['tf']]}, откат {rec['depth']:.2f}"
        zones[side] = {"zone": zl[0] if zl else None, "next": zl[1] if len(zl) > 1 else None, "all": zl}
    return {"sym": base, "now": now, "px": px, "impulses": found, "zones": zones, "fvgs": fvgs, "obs": obs,
            "vp": vp, "pivots": piv, "piv_all": piv_all, "link_pivots": False, "chart": D[P["chart"][0]], "chart_tf": P["chart"][0], "chart_days": P["chart"][1],
            "view": view, "levels_n": {k: len(v) for k, v in levels.items()}}


def scenarios(R: dict) -> list[str]:
    """Сценарии словами: где цена сейчас, лонг, шорт, провал. Только уровни из зон — без выдуманных вероятностей."""
    L, S, px = R["zones"]["LONG"]["all"], R["zones"]["SHORT"]["all"], R["px"]
    f = lambda z: f"{z['lo']:.0f}–{z['hi']:.0f}"                              # noqa: E731
    out = ["СЕЙЧАС:"]
    inside = [(sd, j, z) for sd, zz in (("ЛОНГ", L), ("ШОРТ", S)) for j, z in enumerate(zz, 1) if z["lo"] <= px <= z["hi"]]
    if inside:
        sd, j, z = inside[0]
        out.append(f"  цена {px:.0f} — в зоне {sd} {j}")
        if z.get("entered"):
            out.append(f"  ({z['entered']})")
    elif L and S:
        dl, ds = (px / L[0]["hi"] - 1) * 100, (S[0]["lo"] / px - 1) * 100
        out.append(f"  цена {px:.0f}: до ЛОНГ 1 {dl:.1f}%, до ШОРТ 1 {ds:.1f}%")
        out.append("  между зонами — «вправо», ждём реакцию")
    ups = [r for r in R["impulses"] if r["valid"] and r["dir"] == "up"]
    if L:
        tg = [f(z) for z in S[:2]] or ["нет зоны сверху"]
        out += ["ЛОНГ:", f"  реакция в ЛОНГ 1" + (" или ЛОНГ 2" if len(L) > 1 else ""), "  цели: " + " → ".join(tg)]
    if S:
        tg = [f(z) for z in L[:2]] or ["нет зоны снизу"]
        out += ["ШОРТ:", "  реакция в ШОРТ 1" + (" или ШОРТ 2" if len(S) > 1 else ""), "  цели: " + " → ".join(tg)]
    if len(L) > 2:
        out += ["ПРОВАЛ ЛОНГ 1–2:", f"  ЛОНГ 3 ({f(L[2])})" + (f" → начало {ups[0]['waves'][0][1]:.0f}" if ups else ""),
                "  дальше — сетап старшего ТФ"]
    return out


def near_pivot(R: dict, price: float, tol: float = 0.015) -> str:
    """Опция --pivots (Егор 12.10: «как ложится на недельные пивоты?»): ближайший пивот старших периодов к уровню
    гипотезы — « ≈W R1 86758». Дальше tol от уровня — пусто: за уши не притягиваем. Без опции — всегда пусто."""
    if not R.get("link_pivots"):
        return ""
    cand = [(f"{lab} {k}", val) for lab, pv in R["piv_all"].items() for k, val in pv.items()
            if k in ("PP", "S1", "S2", "S3", "R1", "R2", "R3")]
    if not cand:
        return ""
    name, val = min(cand, key=lambda t: abs(t[1] - price))
    return f" ≈{name} {val:.0f}" if abs(val / price - 1) <= tol else ""


def hypotheses(R: dict) -> dict | None:
    """ГИПОТЕЗЫ, А НЕ ПЛАН (Егор 12.10: «важны гипотезы, а не строгое утверждение одного плана; знать, когда каждая
    отменяется и что делать дальше»). Детектор даёт один счёт волн — здесь он раскладывается на три гипотезы от самого
    свежего действующего импульса (0…5), для любого направления:
      1 — растянутая третья: точки 3 и 4 детектора — подволны, текущий откат = 4-я, впереди 5-я;
      2 — пятёрка завершена: идёт коррекция всего хода;
      3 — весь ход — коррекция старшего встречного импульса, старший ход продолжится.
    У каждой: подтверждение, цели, отмена и к какой гипотезе переходить. Только уровни — без вероятностей."""
    val = [r for r in R["impulses"] if r["valid"]]
    if not val:
        return None
    m = max(val, key=lambda r: r["waves"][5][0])
    sg = 1 if m["dir"] == "up" else -1
    w = [p_ for _, p_ in m["waves"]]
    ch = R["chart"]
    after = ch[ch.index > m["waves"][5][0]]
    corr = w[5] if after.empty else (float(after.low.min()) if sg > 0 else float(after.high.max()))
    l1, alt3, full = abs(w[1] - w[0]), abs(w[5] - w[2]), abs(w[5] - w[0])
    up, dn = ("выше", "ниже") if sg > 0 else ("ниже", "выше")
    px = R["px"]
    soft4 = w[5] - sg * 0.5 * alt3
    beyond5 = (px - w[5]) * sg > 0
    h1_ok = (corr - w[1]) * sg > 0 and (corr - soft4) * sg > 0
    lv = lambda p_: f"{p_:.0f}" + near_pivot(R, p_)                           # noqa: E731  уровень (+ пивот при --pivots)
    H = [dict(n=1, name="4-я волна перед 5-й (третья растянута)",
              status="подтверждается" if beyond5 else ("в игре" if h1_ok else "отменена"),
              confirm=f"{up} {lv(w[5])}",
              target=" / ".join(lv(corr + sg * k * l1) for k in (0.618, 1.0, 1.618)) + "  (0.618 / 1 / 1.618 первой)",
              cancel=f"{dn} {lv(soft4)} → гипотеза 2 (жёстко — {dn} {lv(w[1])})",
              depth=abs(w[5] - corr) / alt3),
         dict(n=2, name="пять волн завершены, коррекция всего хода",
              status="отменена" if beyond5 else "в игре",
              confirm=f"{dn} {lv(corr)}, затем {dn} {lv(w[4])}",
              target=" / ".join(lv(w[5] - sg * f * full) for f in (0.382, 0.5, 0.618)) + "  (0.382 / 0.5 / 0.618 хода)",
              cancel=f"{up} {w[5]:.0f} → гипотеза 1; {dn} {w[0]:.0f} → гипотеза 3")]
    par = [r for r in val if r["dir"] != m["dir"] and abs(r["waves"][5][1] / w[0] - 1) < 0.01]
    levels = [(w[5], f"{lv(w[5])} — подтв. гип. 1"), (soft4, f"{lv(soft4)} — отмена гип. 1"), (w[0], f"{w[0]:.0f} — начало хода")]
    if abs(corr - w[5]) > 0:
        levels.append((corr, f"{lv(corr)} — подтв. гип. 2"))
    if par:
        pr = max(par, key=lambda r: r["range_pct"])
        p0 = pr["waves"][0][1]; lp = abs(p0 - w[0])
        weak = w[0] + sg * 0.618 * lp
        H.append(dict(n=3, name=f"весь ход — коррекция старшего импульса {'↓' if sg > 0 else '↑'} ({TFD[pr['tf']]})",
                      status="отменена" if (px - p0) * sg > 0 else "в игре",
                      confirm=f"{dn} {lv(w[0])}",
                      target=" / ".join(lv(w[5] - sg * k * lp) for k in (0.5, 0.618)) + "  (нога 0.5 / 0.618 старшей)",
                      cancel=f"{up} {lv(weak)} слабеет (отыграно > 0.618), {up} {lv(p0)} — отменена",
                      retr=full / lp))
        levels[2] = (w[0], f"{lv(w[0])} — подтв. гип. 3")
    return {"main": m, "corr": corr, "H": H, "levels": levels}


def hypo_lines(R: dict) -> list[str]:
    hy = hypotheses(R)
    if not hy:
        return ["нет действующего импульса — гипотез нет"]
    m = hy["main"]; w = m["waves"]
    out = [f"ГИПОТЕЗЫ · импульс {TFD[m['tf']]} {'↑' if m['dir'] == 'up' else '↓'} {w[0][1]:.0f} → {w[5][1]:.0f}, откат до {hy['corr']:.0f}"]
    for h in hy["H"]:
        extra = f" · 4-я = {h['depth']:.2f} третьей" if "depth" in h else (f" · отыграно {h['retr']:.2f}" if "retr" in h else "")
        out += [f"{h['n']}. {h['name']} — {h['status']}{extra}", f"    подтверждение: {h['confirm']}",
                f"    цели: {h['target']}", f"    отмена: {h['cancel']}"]
    return out


def draw(R: dict, path: Path) -> None:
    dc = R["chart"]; v = dc[dc.index >= R["now"] - pd.Timedelta(days=R["chart_days"])]
    fig = plt.figure(figsize=(16, 9), dpi=90)
    ax = fig.add_axes([0.04, 0.30, 0.78, 0.65]); axv = fig.add_axes([0.82, 0.30, 0.10, 0.65], sharey=ax)
    x = np.arange(len(v)); up = v.close >= v.open
    ax.vlines(x, v.low, v.high, color=np.where(up, "#2b8a3e", "#c92a2a"), linewidth=0.7)
    ax.bar(x, (v.close - v.open).abs().clip(lower=v.close * 1e-4), bottom=np.minimum(v.open, v.close),
           color=np.where(up, "#8ce99a", "#ffa8a8"), width=0.7)
    pos = lambda t: int(np.searchsorted(v.index, pd.Timestamp(t)))   # noqa: E731
    in_zones = {n for sd in ("LONG", "SHORT") for z in R["zones"][sd]["all"] for n, _, _ in z["levels"]}
    for g in R["fvgs"]:
        if g.get("name") not in in_zones:      # только FVG, которые вошли в зоны (самопроверка 09.10: каша)
            continue
        xs = pos(g["t"])
        if xs < len(v):
            ax.fill_between([max(xs, 0), len(v)], g["bottom"], g["top"], color="#74c0fc" if g["bullish"] else "#ffc078",
                            alpha=0.18)
    best = {}                                  # (сторона, время пятой) → больший по ходу импульс
    for rec in R["impulses"]:
        if not rec["valid"] or rec["waves"][0][0] < v.index[0]:
            continue                           # отработанные не рисуем — путают (самопроверка 09.10)
        k_ = (rec["dir"], rec["waves"][5][0].floor("D"))
        if k_ not in best or rec["range_pct"] > best[k_]["range_pct"]:
            best[k_] = rec
    for rec in best.values():
        c = "#e03131" if rec["dir"] == "up" else "#862e9c"
        xs = [pos(t) for t, _ in rec["waves"]]; ys = [p for _, p in rec["waves"]]
        ax.plot(xs, ys, color=c, linewidth=1.6 if rec["valid"] else 0.9, linestyle="-" if rec["valid"] else "--",
                alpha=1.0 if rec["valid"] else 0.6)
        dx = max(1, len(v) // 120) * (1 if rec["dir"] == "up" else -1)
        for j, (xw, yw) in enumerate(zip(xs, ys)):
            ax.text(xw + dx, yw, str(j), color=c, fontsize=8, fontweight="bold", ha="center",
                    va="bottom" if (j % 2 == 1) == (rec["dir"] == "up") else "top")
        ab = rec.get("abc")
        if ab and ab["A_t"] >= v.index[0]:
            for lab, t_, p_ in (("A", ab["A_t"], ab["A"]), ("B", ab["B_t"], ab["B"]), ("C", ab["C_t"], ab["C"])):
                ax.text(pos(t_), p_, lab, color=c, fontsize=11, fontweight="bold", ha="center",   # цвет своего импульса
                        va="top" if lab != "B" and rec["dir"] == "up" else "bottom")
    for side, col in (("LONG", "#2f9e44"), ("SHORT", "#e8590c")):
        for j, z in enumerate(R["zones"][side]["all"], 1):
            ax.axhspan(z["lo"], z["hi"], color=col, alpha=0.24 if j == 1 else 0.12)
            ax.text(1, z["mid"], f" {'ЛОНГ' if side == 'LONG' else 'ШОРТ'} {j}: {z['lo']:.0f}–{z['hi']:.0f} · факторов {n_src(z)} · вес {z['score']:.1f}",
                    color=col, fontsize=10 if j == 1 else 9, fontweight="bold" if j == 1 else "normal", va="center")
    ax.axhline(R["px"], color="#343a40", linewidth=0.8, linestyle=":")
    hy = hypotheses(R) if R["view"] == "global" else None
    if hy:
        for lvl, lab in hy["levels"]:
            ax.hlines(lvl, len(v) * 0.72, len(v) + 2, color="#212529", linewidth=1.1, linestyles=(0, (4, 3)))
            ax.text(len(v) * 0.72, lvl, lab + " ", color="#212529", fontsize=8, ha="right", va="center",
                    bbox=dict(facecolor="white", alpha=0.75, edgecolor="none", pad=1))
    zs = [z for sd in ("LONG", "SHORT") for z in R["zones"][sd]["all"]]
    lo_y = min([v.low.min()] + [z["lo"] for z in zs]); hi_y = max([v.high.max()] + [z["hi"] for z in zs])
    ax.set_ylim(lo_y - (hi_y - lo_y) * 0.03, hi_y + (hi_y - lo_y) * 0.03)
    step = max(1, len(v) // 10)
    ax.set_xticks(x[::step]); ax.set_xticklabels([t.strftime("%d.%m" if R["view"] == "local" else "%d.%m.%y")
                                                   for t in v.index[::step]], fontsize=8)
    ax.set_title(f"{R['sym']} · {TFD[R['chart_tf']]} · {'ГЛОБАЛЬНО' if R['view'] == 'global' else 'локально'} · "
                 f"{R['now']:%d.%m.%y %H:%M} UTC · цена {R['px']:.6g}", loc="left", fontsize=12)
    ax.grid(alpha=0.15)
    vp = R["vp"]
    axv.barh(vp["mids"], vp["vol"], height=(vp["mids"][1] - vp["mids"][0]) * 0.9, color="#adb5bd")
    axv.axhline(vp["poc"], color="#495057", linewidth=1); axv.text(vp["vol"].max() * 0.5, vp["poc"], " POC", fontsize=8, va="bottom")
    axv.set_xticks([]); axv.tick_params(labelleft=False); axv.set_title(vp.get("label", "объём"), fontsize=9)
    tx = fig.add_axes([0.04, 0.02, 0.92, 0.25]); tx.axis("off")
    cols = []
    for side in ("LONG", "SHORT"):
        lines = []
        for j, z in enumerate(R["zones"][side]["all"], 1):
            top = sorted(fam_best(z["levels"]).values(), key=lambda t: -t[2])[:4 if j == 1 else 3]
            lines.append(f"{'ЛОНГ' if side == 'LONG' else 'ШОРТ'} {j}: {z['lo']:.0f}–{z['hi']:.0f}  ({n_src(z)} факторов)")
            lines += [f"   • {n} {p_:.0f}" for n, p_, _ in top]
        cols.append("\n".join(lines) or "нет схождения")
    if R["view"] == "global":
        tx.text(0.0, 1.0, cols[0], va="top", fontsize=7.5, family="monospace")
        tx.text(0.25, 1.0, cols[1], va="top", fontsize=7.5, family="monospace")
        tx.text(0.50, 1.0, "\n".join(scenarios(R)[:3] + [""] + hypo_lines(R)), va="top", fontsize=8.5)
    else:
        tx.text(0.0, 1.0, cols[0], va="top", fontsize=8.5, family="monospace")
        tx.text(0.36, 1.0, cols[1], va="top", fontsize=8.5, family="monospace")
        tx.text(0.70, 1.0, "\n".join(scenarios(R)), va="top", fontsize=9)
    fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTC")
    ap.add_argument("--view", default="local", choices=list(PROFILES))
    ap.add_argument("--out", default=str(ROOT / "data" / "mtf_card"))
    ap.add_argument("--pivots", action="store_true", help="опция: связать уровни гипотез с пивотами W/M/Q/Y (W и M — из шины)")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    R = build(a.sym.upper(), a.view)
    R["link_pivots"] = a.pivots
    print(f"{R['sym']} · {R['now']} · цена {R['px']:.2f} · уровней: лонг {R['levels_n']['LONG']}, шорт {R['levels_n']['SHORT']}")
    print("ИМПУЛЬСЫ (каскад ТФ):")
    for rec in R["impulses"]:
        w = rec["waves"]
        ab = rec.get("abc")
        print(f"  {TFD[rec['tf']]:>3} sw{rec['sw']:<2} {'↑' if rec['dir'] == 'up' else '↓'} {rec['range_pct']:5.1f}% "
              f"{w[0][0]:%d.%m} {w[0][1]:.0f} → {w[5][0]:%d.%m} {w[5][1]:.0f} · "
              + (f"действует, откат {rec['depth']:.2f}" if rec["valid"] else "отработан/сломан")
              + (f" · ABC: A {ab['A']:.0f} B {ab['B']:.0f} C {ab['C']:.0f} (C = {ab['C_ratio']:.2f}×A)" if ab else ""))
    for side in ("LONG", "SHORT"):
        z, n = R["zones"][side]["zone"], R["zones"][side]["next"]
        print(f"\n{side}-ЗОНА: " + (f"{z['lo']:.0f}–{z['hi']:.0f} · вес {z['score']:.1f} · факторов {n_src(z)}" if z else "нет"))
        if z:
            for name, p_, w in sorted(z["levels"], key=lambda t: t[1], reverse=True):
                print(f"   {p_:10.0f}  {w:.2f}  {name}")
        for j, n in enumerate(R["zones"][side]["all"][1:], 2):
            print(f"  если провалят → зона {j}: {n['lo']:.0f}–{n['hi']:.0f} · вес {n['score']:.1f}: "
                  + "; ".join(f"{nm} {p_:.0f}" for nm, p_, _ in sorted(n["levels"], key=lambda t: -t[2])[:7]))
    if a.view == "global":
        print()
        print("\n".join(hypo_lines(R)))
    if a.pivots:
        print("\nПИВОТЫ для связи с гипотезами:")
        for lab, pv in R["piv_all"].items():
            print(f"  {lab} ({R['pivots'].get('_src_' + lab, '?')}): "
                  + " · ".join(f"{k} {pv[k]:.0f}" for k in ("S3", "S2", "S1", "PP", "R1", "R2", "R3") if k in pv))
    png = out / f"{R['sym']}_{a.view}{'_piv' if a.pivots else ''}.png"
    draw(R, png)
    hy = hypotheses(R) if a.view == "global" else None
    js = {"sym": R["sym"], "now": str(R["now"]), "px": R["px"], "hypotheses": hy["H"] if hy else None,
          "zones": {s: [{**{kk: vv for kk, vv in z.items() if kk != "levels"}, "levels": [list(l) for l in z["levels"]]}
                        for z in R["zones"][s]["all"]] for s in ("LONG", "SHORT")}}
    (out / f"{R['sym']}_{a.view}{'_piv' if a.pivots else ''}.json").write_text(json.dumps(js, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n→ {png}")


if __name__ == "__main__":
    main()
