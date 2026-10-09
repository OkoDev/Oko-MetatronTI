# -*- coding: utf-8 -*-
"""ЧЕТЫРЕ НОГИ НА ОДНОМ ГРАФИКЕ — «сначала глазами» (09.10.2026, Егор: «OTE строится по ноге — под сомнением волновой
детектор и верность выбора ноги»).

В проекте минимум четыре определения «ноги», и OTE по ним даёт разное: по ноге OKO-SM swing 50 откат пуст у 12 механик
(21.09), по дневной ноге волн — улучшает недельные сетапы (09.10), клетка OTE строит свою ногу по CHoCH+BOS. Прежде чем
мерить, Егор отмечает глазами, какая нога «правильная». Каждая нога — тем вызовом, которым пользуется живой потребитель:
  1 клетка OTE   run_structure(4h, окно 400, swing 50 / internal 5) → assemble_impulse(internal=True)  (ote_cell_shadow)
  2 OKO-SM 50    current_leg(той же структуры)                                                       (контекст OTE 21.09)
  3 волны 1D     wave_analyst.daily_leg — нога вверх и вниз, рисуется та, чей конец свежее          (журнал, шина wave_leg)
  4 DC 3×ATR43   dc_legs.active_leg(4h, atr_mult=3.0, atr_len=43)                                   (ядро структуры)
Данные — BingX из хранилища (закрытые бары), момент — последний закрытый 4h. Зона OTE — канон 0.5–0.79 для всех.
Запуск: python scripts/leg_compare_view.py [--syms BTC,ETH] [--out data/leg_compare]
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
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from core.infra.market_store import read_bars          # noqa: E402
from core.smc.oko_sm_engine import run_structure, current_leg   # noqa: E402
from core.smc.impulse_assembly import assemble_impulse  # noqa: E402
from core.smc.fibonacci import OTE_TOP, OTE_BOTTOM      # noqa: E402
from core.smc.dc_legs import active_leg as dc_active    # noqa: E402
from core.waves.wave_analyst import daily_leg           # noqa: E402

COLORS = {1: "#e8590c", 2: "#1c7ed6", 3: "#2f9e44", 4: "#ae3ec9"}
NAMES = {1: "клетка OTE (CHoCH+BOS 4h)", 2: "OKO-SM swing 50 (4h)", 3: "волны: дневная нога", 4: "DC 3×ATR43 (4h)"}
DEFAULT = "BTC,ETH,SOL,XRP,DOGE,NEAR,LINK,AVAX,SUI,TIA,ARB,OP,INJ,WIF,APT,LDO"


def legs_for(base: str) -> dict | None:
    d4 = read_bars(base, "4h")
    dd = read_bars(base, "1d")
    if len(d4) < 450 or len(dd) < 60:
        return None
    for x in (d4, dd):
        if x.index.tz is not None:
            x.index = x.index.tz_convert(None)
    now = d4.index[-1] + pd.Timedelta("4h")                  # момент: закрытие последнего 4h
    px = float(d4.close.iloc[-1])
    out = {"sym": base, "now": now, "px": px, "legs": {}}
    # 1–2: структура 4h на окне 400 закрытых баров — как ote_cell_shadow
    w = d4.iloc[-400:].reset_index()
    tcol = w.columns[0]
    st = run_structure(w[["open", "high", "low", "close", "volume"]], swing_len=50, internal_len=5)
    imp = assemble_impulse(st, w["high"], w["low"], internal=True)
    if imp:
        i_ch = imp["i_choch"]
        evs = [e for e in st.events if bool(e.internal)]
        pos = next(k for k in range(len(evs) - 1, -1, -1) if int(evs[k].i) == i_ch and evs[k].kind == "CHoCH")
        i_prev = int(evs[pos - 1].i) if pos > 0 else max(0, i_ch - 60)
        a, b = max(0, min(i_prev, i_ch - 1)), i_ch + 1
        lo_, hi_ = w["low"].values, w["high"].values
        oi = a + int(np.argmin(lo_[a:b]) if imp["is_long"] else np.argmax(hi_[a:b]))
        ei = i_ch + int(np.argmax(hi_[i_ch:]) if imp["is_long"] else np.argmin(lo_[i_ch:]))
        assert np.isclose(lo_[oi] if imp["is_long"] else hi_[oi], imp["origin"])
        out["legs"][1] = {"up": imp["is_long"], "o": imp["origin"], "e": imp["extreme"],
                          "ot": w[tcol].iat[oi], "et": w[tcol].iat[ei], "n_bos": imp["n_bos"]}
    cl = current_leg(st)
    if cl:
        out["legs"][2] = {"up": cl["trend"] == "long", "o": cl["origin"], "e": cl["extreme"],
                          "ot": w[tcol].iat[int(cl["origin_i"])], "et": w[tcol].iat[int(cl["extreme_i"])]}
    # 3: дневная нога волн — как журнал общего состояния (_leg_block): обе, рисуем ту, чей конец свежее
    ddc = dd[dd.index + pd.Timedelta(days=1) <= now]
    cands = []
    for want_top in (False, True):
        try:
            L = daily_leg(d4, now, want_top, px, now, now, dd=ddc)
        except Exception:                                   # noqa: BLE001
            L = None
        if L:
            cands.append({"up": not want_top, "o": L["origin"], "e": L["ext"], "ot": L["origin_t"], "et": L["ext_t"]})
    if cands:
        cands.sort(key=lambda z: z["et"])
        out["legs"][3] = cands[-1]
        out["legs"][3]["other"] = cands[0] if len(cands) > 1 else None
    # 4: DC 3×ATR43 на 4h
    dc = dc_active(d4.reset_index(drop=True), len(d4) - 1, atr_mult=3.0, atr_len=43)
    if dc:
        out["legs"][4] = {"up": dc["up"], "o": dc["origin"], "e": dc["extreme"],
                          "ot": d4.index[dc["a"]], "et": d4.index[dc["b"]]}
    for k, L in out["legs"].items():
        span = abs(L["o"] - L["e"])
        L["span_pct"] = span / min(L["o"], L["e"]) * 100
        L["depth"] = abs(px - L["e"]) / span if span > 0 else np.nan     # 0 — у конца ноги, 1 — у начала
        # для ноги вверх зона ниже конца: e − 0.5·span … e − 0.79·span; для ноги вниз — выше конца
        sg = -1 if L["up"] else 1
        z1, z2 = L["e"] + sg * OTE_TOP * span, L["e"] + sg * OTE_BOTTOM * span
        L["zone"] = (min(z1, z2), max(z1, z2))
        L["in_ote"] = bool(L["zone"][0] <= px <= L["zone"][1])
    out["d4"] = d4
    return out


def draw(r: dict, path: Path) -> None:
    d4 = r["d4"]
    t_min = min([L["ot"] for L in r["legs"].values()] + [d4.index[-150]])
    t_min = max(t_min - pd.Timedelta(days=5), d4.index[0])
    v = d4[d4.index >= t_min]
    if len(v) > 900:                                         # слишком длинно для 4h — дневки
        v = r["d4"].resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        v = v[v.index >= t_min]
    fig, ax = plt.subplots(figsize=(15, 7.5), dpi=90)
    x = np.arange(len(v)); idx = v.index
    up = v.close >= v.open
    ax.vlines(x, v.low, v.high, color=np.where(up, "#2b8a3e", "#c92a2a"), linewidth=0.7)
    ax.bar(x, (v.close - v.open).abs().clip(lower=v.close * 1e-4), bottom=np.minimum(v.open, v.close),
           color=np.where(up, "#8ce99a", "#ffa8a8"), edgecolor=np.where(up, "#2b8a3e", "#c92a2a"), width=0.7, linewidth=0.5)
    pos = lambda t: int(np.searchsorted(idx, pd.Timestamp(t)))            # noqa: E731
    lines = []
    for k in sorted(r["legs"]):
        L = r["legs"][k]; c = COLORS[k]
        xo, xe = pos(L["ot"]), pos(L["et"])
        ax.plot([xo, xe], [L["o"], L["e"]], color=c, linewidth={1: 6.5, 2: 4.5, 3: 2.6, 4: 1.2}[k], alpha=0.85,
                solid_capstyle="round")       # толщина убывает: совпадающие ноги видны вложенными полосами
        ax.scatter([xo, xe], [L["o"], L["e"]], color=c, s=28, zorder=5)
        ax.text(xe, L["e"], f" {k}", color=c, fontsize=12, fontweight="bold", va="bottom" if L["up"] else "top")
        ax.fill_between([xe, len(v) + 2], L["zone"][0], L["zone"][1], color=c, alpha=0.10)
        ax.hlines(L["zone"], xe, len(v) + 2, color=c, linewidth=0.8, linestyles="--", alpha=0.7)
        lines.append(f"{k} {NAMES[k]}: {'↑' if L['up'] else '↓'} {L['span_pct']:.1f}% · глубина {L['depth']:.2f}"
                     f"{' · В OTE' if L['in_ote'] else ''}")
    same = []                                                            # какие ноги совпадают (начало и конец ±0.5%)
    ks = sorted(r["legs"])
    for i_, a_ in enumerate(ks):
        for b_ in ks[i_ + 1:]:
            A, B = r["legs"][a_], r["legs"][b_]
            if A["up"] == B["up"] and abs(A["o"] / B["o"] - 1) < 0.005 and abs(A["e"] / B["e"] - 1) < 0.005:
                same.append(f"{a_}={b_}")
    if same:
        lines.append("совпадают: " + ", ".join(same))
    ax.axhline(r["px"], color="#343a40", linewidth=0.8, linestyle=":")
    step = max(1, len(v) // 10)
    ax.set_xticks(x[::step]); ax.set_xticklabels([t.strftime("%d.%m") for t in idx[::step]], fontsize=8)
    ax.set_xlim(-2, len(v) + 3)
    ax.set_title(f"{r['sym']} · {('4h' if (idx[1] - idx[0]) < pd.Timedelta('1D') else '1d')} · момент {r['now']:%d.%m %H:%M} UTC · "
                 f"цена {r['px']:.6g}", fontsize=12, loc="left")
    ax.text(0.005, 0.99, "\n".join(lines), transform=ax.transAxes, va="top", fontsize=9.5,
            bbox=dict(facecolor="white", alpha=0.85, edgecolor="#ced4da"))
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", default=DEFAULT)
    ap.add_argument("--out", default=str(ROOT / "data" / "leg_compare"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    meta = []
    for s in [x.strip().upper() for x in a.syms.split(",") if x.strip()]:
        try:
            r = legs_for(s)
        except Exception as e:                               # noqa: BLE001
            print(f"{s}: ошибка {type(e).__name__}: {e}")
            continue
        if not r:
            print(f"{s}: мало истории"); continue
        png = out / f"{s}.png"
        draw(r, png)
        row = {"sym": s, "px": r["px"], "now": str(r["now"]), "png": png.name, "legs": {}}
        for k, L in r["legs"].items():
            row["legs"][str(k)] = {"name": NAMES[k], "dir": "↑" if L["up"] else "↓", "origin": L["o"], "extreme": L["e"],
                                   "origin_t": str(L["ot"])[:16], "extreme_t": str(L["et"])[:16],
                                   "span_pct": round(L["span_pct"], 2), "depth": round(float(L["depth"]), 3),
                                   "in_ote": L["in_ote"], "zone": [round(z, 8) for z in L["zone"]]}
        meta.append(row)
        print(f"{s:6} " + " | ".join(f"{k}:{v['dir']}{v['span_pct']:.0f}% г{v['depth']:.2f}{'*' if v['in_ote'] else ''}"
                                      for k, v in row["legs"].items()))
    (out / "legs.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
