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
Зона = `wave_progress.cluster_zone` (плотнейшее окно уровней по весу). Всё каузально: только закрытые бары.
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
except Exception:
    pass
from core.infra.market_store import read_bars                     # noqa: E402
from core.waves.wave5_core import impulses_on_bar                  # noqa: E402
from core.smc.oko_sm_engine import pivot_points                    # noqa: E402
from core.waves.wave_progress import cluster_zone                  # noqa: E402
from core.structure.zones import fair_value_gaps, order_blocks, equal_levels   # noqa: E402
from core.structure.levels import level_breaks                     # noqa: E402
from core.indicators.indicators import calculate_pivot_points      # noqa: E402

SCALES = [("1d", 5, 200, 2.0), ("4h", 15, 400, 1.5), ("4h", 8, 400, 1.5), ("1h", 12, 700, 1.0), ("15m", 12, 900, 0.5)]
RET = (0.5, 0.618, 0.705, 0.79)
ZONE_W = 0.025                     # ширина окна зоны — 2.5% цены
TFD = {"1d": "1D", "4h": "4h", "1h": "1h", "15m": "15m"}


def bars(base: str, tf: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
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


def prev_pivots(d1d: pd.DataFrame, rule: str) -> dict:
    """Классические пивоты по ПРОШЛОМУ закрытому периоду (день/неделя/месяц) из дневок."""
    g = d1d.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(g) < 2:
        return {}
    last = g.iloc[-2]                                # прошлый ЗАКРЫТЫЙ период
    return calculate_pivot_points(float(last.high), float(last.low), float(last.close))


def zones_by_distance(levels: list, px: float, down: bool, s_min: float = 3.5, n_min: int = 3, k: int = 3) -> list:
    """Зоны по порядку удаления от цены (Егор: «провалят эту → следующая 76 и ниже»): ближайшая ЗНАЧИМАЯ (вес ≥ s_min,
    факторов ≥ n_min), затем следующая за ней. Внутри окрестности берётся лучшее окно — `wave_progress.cluster_zone`."""
    out, ref, pool = [], px, list(levels)
    while len(out) < k:
        cand = [l for l in pool if (l[1] < ref if down else l[1] > ref)]
        if len(cand) < 2:
            break
        cand.sort(key=lambda l: abs(l[1] - ref))
        z = None
        for _, v0, _ in cand:                         # ближайшая окрестность с достаточным весом
            near = [l for l in cand if abs(l[1] - v0) <= ZONE_W * px]
            zz = cluster_zone(near, ref, down, width=ZONE_W)
            if zz and zz["score"] >= s_min and len(zz["levels"]) >= n_min:
                z = zz
                break
        if z is None:
            break
        out.append(z)
        ref = z["lo"] if down else z["hi"]
        pool = [l for l in pool if (l[1] < z["lo"] if down else l[1] > z["hi"])]
    return out


def build(base: str) -> dict:
    d1h = bars(base, "1h")
    now = d1h.index[-1] + pd.Timedelta("1h")
    D = {tf: bars(base, tf, now) for tf in ("1d", "4h", "1h", "15m")}
    px = float(D["1h"].close.iloc[-1])
    levels = {"LONG": [], "SHORT": []}

    def add(name, price, w):
        if price and np.isfinite(price) and abs(price / px - 1) < 0.30:
            levels["LONG" if price < px else "SHORT"].append((name, float(price), float(w)))

    found = []
    for tf, sw, scan, w in SCALES:
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
                   "valid": bool(not beyond and not broken)}
            found.append(rec)
            if not rec["valid"]:
                continue
            tag = f"{TFD[tf]} sw{sw}"
            for f in RET:
                add(f"откат {f} импульса {'↑' if up else '↓'} {tag}", p5 - (1 if up else -1) * f * abs(p5 - p0), w)
            add(f"начало импульса {'↑' if up else '↓'} {tag}", p0, w * 0.8)
            abc = abc_after(D[tf], imp, up, sw)
            rec["abc"] = abc
            if abc:
                for k in (1.0, 1.272, 1.618):
                    add(f"C = {k}×A ({tag})", abc["B"] - (1 if up else -1) * k * abc["len_A"], w * 0.8)
    # FVG и ордер-блоки 4h: живые на момент, за последние 60 дней
    d4 = D["4h"].reset_index()
    t4 = d4.columns[0]
    recent = len(d4) - 360
    fvgs = [g for g in fair_value_gaps(d4) if g.filled_bar == -1 and g.bar >= recent]
    for g in fvgs:
        for edge in (g.top, g.bottom):
            add(f"FVG 4h {'↑' if g.bullish else '↓'} {d4[t4].iat[g.bar]:%d.%m}", edge, 0.75)
    obs = [b for b in order_blocks(d4, level_breaks(d4, window=10)) if b.gone_bar == -1 and b.origin_bar >= recent]
    for b in obs:
        for edge in (b.top, b.bottom):
            add(f"OB 4h {'↑' if b.bullish else '↓'} {d4[t4].iat[b.origin_bar]:%d.%m}", edge, 0.75)
    eqs = [e for e in equal_levels(d4) if e.second_bar >= recent]
    for e in eqs:
        add(f"{'равные вершины' if e.highs else 'равные днища'} 4h (ликвидность)", (e.first_price + e.second_price) / 2, 1.0)
    piv = {}
    for rule, lab, w in (("1D", "D", 0.5), ("W-SUN", "W", 1.0), ("MS", "M", 1.5)):
        pv = prev_pivots(D["1d"], rule)
        piv[lab] = pv
        for k in ("PP", "S1", "S2", "S3", "R1", "R2", "R3"):
            if k in pv:
                add(f"пивот {lab} {k}", pv[k], w)
    vp = volume_profile(D["1h"])
    add("профиль объёма 30д: POC", vp["poc"], 1.5)
    for h in vp["hvn"]:
        if abs(h / vp["poc"] - 1) > 0.003:
            add("профиль объёма 30д: узел", h, 1.0)

    zones = {}
    for side, down in (("LONG", True), ("SHORT", False)):
        zl = zones_by_distance(levels[side], px, down)
        zones[side] = {"zone": zl[0] if zl else None, "next": zl[1] if len(zl) > 1 else None, "all": zl}
    return {"sym": base, "now": now, "px": px, "impulses": found, "zones": zones, "fvgs": fvgs, "obs": obs,
            "vp": vp, "pivots": piv, "d4": D["4h"], "levels_n": {k: len(v) for k, v in levels.items()}}


def scenarios(R: dict) -> list[str]:
    """Сценарии словами: где цена сейчас, лонг, шорт, провал. Только уровни из зон — без выдуманных вероятностей."""
    L, S, px = R["zones"]["LONG"]["all"], R["zones"]["SHORT"]["all"], R["px"]
    f = lambda z: f"{z['lo']:.0f}–{z['hi']:.0f}"                              # noqa: E731
    out = ["СЕЙЧАС:"]
    inside = [(sd, j, z) for sd, zz in (("ЛОНГ", L), ("ШОРТ", S)) for j, z in enumerate(zz, 1) if z["lo"] <= px <= z["hi"]]
    if inside:
        out.append(f"  цена {px:.0f} — в зоне {inside[0][0]} {inside[0][1]}")
    elif L and S:
        out.append(f"  цена {px:.0f} между ЛОНГ 1 и ШОРТ 1 —")
        out.append("  «вправо», ждём реакцию у зоны")
    ups = [r for r in R["impulses"] if r["valid"] and r["dir"] == "up"]
    if L:
        tg = [f(S[0])] if S else []
        if ups:
            tg.append(f"вершина {ups[0]['waves'][5][1]:.0f}")
        out += ["ЛОНГ:", f"  реакция в ЛОНГ 1" + (" или ЛОНГ 2" if len(L) > 1 else ""), "  цели: " + " → ".join(tg)]
    if S:
        tg = [f(L[0])] if L else []
        if len(L) > 1:
            tg.append(f(L[1]))
        out += ["ШОРТ:", "  реакция в ШОРТ 1", "  цели: " + " → ".join(tg)]
    if len(L) > 2:
        out += ["ПРОВАЛ ЛОНГ 1–2:", f"  ЛОНГ 3 ({f(L[2])})" + (f" → начало {ups[0]['waves'][0][1]:.0f}" if ups else ""),
                "  дальше — сетап старшего ТФ"]
    return out


def draw(R: dict, path: Path) -> None:
    d4 = R["d4"]; v = d4[d4.index >= R["now"] - pd.Timedelta(days=45)]
    fig = plt.figure(figsize=(16, 9), dpi=90)
    ax = fig.add_axes([0.04, 0.30, 0.78, 0.65]); axv = fig.add_axes([0.82, 0.30, 0.10, 0.65], sharey=ax)
    x = np.arange(len(v)); up = v.close >= v.open
    ax.vlines(x, v.low, v.high, color=np.where(up, "#2b8a3e", "#c92a2a"), linewidth=0.7)
    ax.bar(x, (v.close - v.open).abs().clip(lower=v.close * 1e-4), bottom=np.minimum(v.open, v.close),
           color=np.where(up, "#8ce99a", "#ffa8a8"), width=0.7)
    pos = lambda t: int(np.searchsorted(v.index, pd.Timestamp(t)))   # noqa: E731
    for g in R["fvgs"]:
        if abs((g.top + g.bottom) / 2 / R["px"] - 1) > 0.10:      # дальние FVG не рисуем — сплющивают график
            continue
        xs = pos(R["d4"].index[g.bar])
        if xs < len(v):
            ax.fill_between([max(xs, 0), len(v)], g.bottom, g.top, color="#74c0fc" if g.bullish else "#ffc078", alpha=0.18)
    for rec in R["impulses"]:
        if not rec["valid"] or rec["waves"][0][0] < v.index[0]:
            continue
        c = "#e03131" if rec["dir"] == "up" else "#862e9c"
        xs = [pos(t) for t, _ in rec["waves"]]; ys = [p for _, p in rec["waves"]]
        ax.plot(xs, ys, color=c, linewidth=1.6)
        for j, (xw, yw) in enumerate(zip(xs, ys)):
            ax.text(xw, yw, str(j), color=c, fontsize=8, fontweight="bold", ha="center",
                    va="bottom" if (j % 2 == 1) == (rec["dir"] == "up") else "top")
        ab = rec.get("abc")
        if ab and ab["A_t"] >= v.index[0]:
            for lab, t_, p_ in (("A", ab["A_t"], ab["A"]), ("B", ab["B_t"], ab["B"]), ("C", ab["C_t"], ab["C"])):
                ax.text(pos(t_), p_, lab, color="#1864ab", fontsize=10, fontweight="bold", ha="center",
                        va="top" if lab != "B" and rec["dir"] == "up" else "bottom")
    for side, col in (("LONG", "#2f9e44"), ("SHORT", "#e8590c")):
        for j, z in enumerate(R["zones"][side]["all"], 1):
            ax.axhspan(z["lo"], z["hi"], color=col, alpha=0.24 if j == 1 else 0.12)
            ax.text(1, z["mid"], f" {'ЛОНГ' if side == 'LONG' else 'ШОРТ'} {j}: {z['lo']:.0f}–{z['hi']:.0f} · факторов {len(z['levels'])} · вес {z['score']:.1f}",
                    color=col, fontsize=10 if j == 1 else 9, fontweight="bold" if j == 1 else "normal", va="center")
    ax.axhline(R["px"], color="#343a40", linewidth=0.8, linestyle=":")
    zs = [z for sd in ("LONG", "SHORT") for z in R["zones"][sd]["all"]]
    lo_y = min([v.low.min()] + [z["lo"] for z in zs]); hi_y = max([v.high.max()] + [z["hi"] for z in zs])
    ax.set_ylim(lo_y - (hi_y - lo_y) * 0.03, hi_y + (hi_y - lo_y) * 0.03)
    step = max(1, len(v) // 10)
    ax.set_xticks(x[::step]); ax.set_xticklabels([t.strftime("%d.%m") for t in v.index[::step]], fontsize=8)
    ax.set_title(f"{R['sym']} · 4h · {R['now']:%d.%m %H:%M} UTC · цена {R['px']:.6g}", loc="left", fontsize=12)
    ax.grid(alpha=0.15)
    vp = R["vp"]
    axv.barh(vp["mids"], vp["vol"], height=(vp["mids"][1] - vp["mids"][0]) * 0.9, color="#adb5bd")
    axv.axhline(vp["poc"], color="#495057", linewidth=1); axv.text(vp["vol"].max() * 0.5, vp["poc"], " POC", fontsize=8, va="bottom")
    axv.set_xticks([]); axv.tick_params(labelleft=False); axv.set_title("объём 30д", fontsize=9)
    tx = fig.add_axes([0.04, 0.02, 0.92, 0.25]); tx.axis("off")
    cols = []
    for side in ("LONG", "SHORT"):
        lines = []
        for j, z in enumerate(R["zones"][side]["all"], 1):
            top = sorted(z["levels"], key=lambda t: -t[2])[:4 if j == 1 else 3]
            lines.append(f"{'ЛОНГ' if side == 'LONG' else 'ШОРТ'} {j}: {z['lo']:.0f}–{z['hi']:.0f}  ({len(z['levels'])} факторов)")
            lines += [f"   • {n} {p_:.0f}" for n, p_, _ in top]
        cols.append("\n".join(lines) or "нет схождения")
    tx.text(0.0, 1.0, cols[0], va="top", fontsize=8.5, family="monospace")
    tx.text(0.36, 1.0, cols[1], va="top", fontsize=8.5, family="monospace")
    tx.text(0.70, 1.0, "\n".join(scenarios(R)), va="top", fontsize=9)
    fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BTC")
    ap.add_argument("--out", default=str(ROOT / "data" / "mtf_card"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    R = build(a.sym.upper())
    print(f"{R['sym']} · {R['now']} · цена {R['px']:.2f} · уровней: лонг {R['levels_n']['LONG']}, шорт {R['levels_n']['SHORT']}")
    print("ИМПУЛЬСЫ (каскад ТФ):")
    for rec in R["impulses"]:
        w = rec["waves"]
        ab = rec.get("abc")
        print(f"  {TFD[rec['tf']]:>3} sw{rec['sw']:<2} {'↑' if rec['dir'] == 'up' else '↓'} {rec['range_pct']:5.1f}% "
              f"{w[0][0]:%d.%m} {w[0][1]:.0f} → {w[5][0]:%d.%m} {w[5][1]:.0f} · {'действует' if rec['valid'] else 'отработан/сломан'}"
              + (f" · ABC: A {ab['A']:.0f} B {ab['B']:.0f} C {ab['C']:.0f} (C = {ab['C_ratio']:.2f}×A)" if ab else ""))
    for side in ("LONG", "SHORT"):
        z, n = R["zones"][side]["zone"], R["zones"][side]["next"]
        print(f"\n{side}-ЗОНА: " + (f"{z['lo']:.0f}–{z['hi']:.0f} · вес {z['score']:.1f} · факторов {len(z['levels'])}" if z else "нет"))
        if z:
            for name, p_, w in sorted(z["levels"], key=lambda t: t[1], reverse=True):
                print(f"   {p_:10.0f}  {w:.2f}  {name}")
        for j, n in enumerate(R["zones"][side]["all"][1:], 2):
            print(f"  если провалят → зона {j}: {n['lo']:.0f}–{n['hi']:.0f} · вес {n['score']:.1f}: "
                  + "; ".join(f"{nm} {p_:.0f}" for nm, p_, _ in sorted(n["levels"], key=lambda t: -t[2])[:7]))
    png = out / f"{R['sym']}.png"
    draw(R, png)
    js = {"sym": R["sym"], "now": str(R["now"]), "px": R["px"],
          "zones": {s: [{**{kk: vv for kk, vv in z.items() if kk != "levels"}, "levels": [list(l) for l in z["levels"]]}
                        for z in R["zones"][s]["all"]] for s in ("LONG", "SHORT")}}
    (out / f"{R['sym']}.json").write_text(json.dumps(js, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n→ {png}")


if __name__ == "__main__":
    main()
