# -*- coding: utf-8 -*-
"""Карта целей 2.0 (Егор 03.07: «какие конфлюенции полезны?!» → добро).

3 слоя целей для радар-алертов (PUMP/ПРУЖИНА), все — доказанные конфлюэнции:
  1. Магниты ликвидаций — reuse scripts/liq_magnets.build_magnets (магниты ЛИПНУТ к пивотам:
     GRT=R1, MANA=WPP — ретро 03.07).
  2. Пивоты D/W (floor pivots) — недельные R2/S2 = развороты 62/69%, reach 1й~40%/2й~18%
     (memory pivot_behavior_map); weekly S2 как TP пережил 4-летний бэктест atr_s2.
  3. Незакрытые FVG 15m — «цена всегда стремится заполнить имбаланс» (Егор), цель = midline.

Конфлюэнция: уровни разных слоёв в ±0.3% кластеризуются → «★ цель усилена».
Считается ЛЕНИВО — только при сформированном алерте (до 5 REST-запросов, редко).
"""
import json
import sys
import urllib.request

sys.path.insert(0, ".")

CLUSTER_TOL_PCT = 0.3   # уровни ближе — один кластер (одна усиленная цель)
MAX_DIST_PCT = 15       # цели дальше ±15% от цены не показываем
MAX_TARGETS = 3


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 oko-feed"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _fmt_usd(u: float) -> str:
    return f"${u/1e6:.1f}M" if u >= 1e6 else f"${u/1e3:.0f}k"


def _magnet_levels(sym: str, side: str) -> list[tuple[float, str]]:
    """Слой 1: топ-3 магнита ликвидаций в сторону цели (reuse liq_magnets, не дублируем)."""
    try:
        from scripts.liq_magnets import build_magnets
        m = build_magnets(sym)
    except Exception:
        return []
    if not m:
        return []
    arr = m["below"] if side == "SHORT" else m["above"]
    return [(lvl, f"магнит {_fmt_usd(usd)}") for lvl, usd in
            sorted(arr, key=lambda x: -x[1])[:3]]


def _pivot_levels(sym: str, side: str, px: float) -> list[tuple[float, str]]:
    """Слой 2: floor pivots от ПРЕДЫДУЩЕГО дня (D-) и недели (W-)."""
    out = []
    for iv, pfx in (("1d", "D"), ("1w", "W")):
        try:
            k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval={iv}&limit=2")
        except Exception:
            continue
        if len(k) < 2:
            continue
        h, l, c = float(k[-2][2]), float(k[-2][3]), float(k[-2][4])
        pp = (h + l + c) / 3
        piv = {"PP": pp, "R1": 2 * pp - l, "S1": 2 * pp - h,
               "R2": pp + (h - l), "S2": pp - (h - l)}
        for name, v in piv.items():
            in_side = (v < px) if side == "SHORT" else (v > px)
            if in_side and abs(v / px - 1) * 100 <= MAX_DIST_PCT:
                out.append((v, f"{pfx}-{name}"))
    return out


def _fvg_levels(sym: str, side: str, px: float) -> list[tuple[float, str]]:
    """Слой 3: незакрытые FVG 15m (~24ч), цель = midline гэпа."""
    try:
        k = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}USDT&interval=15m&limit=96")
    except Exception:
        return []
    if len(k) < 5:
        return []
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    out = []
    for i in range(2, len(k)):
        if lows[i] > highs[i - 2]:                       # bull FVG — зона ПОД ценой (цель SHORT)
            top, bot, kind = lows[i], highs[i - 2], "SHORT"
            untouched = all(lo > top for lo in lows[i + 1:])
        elif highs[i] < lows[i - 2]:                     # bear FVG — зона НАД ценой (цель LONG)
            top, bot, kind = lows[i - 2], highs[i], "LONG"
            untouched = all(hi < bot for hi in highs[i + 1:])
        else:
            continue
        if kind != side or not untouched:
            continue
        mid = (top + bot) / 2
        in_side = (mid < px) if side == "SHORT" else (mid > px)
        if in_side and abs(mid / px - 1) * 100 <= MAX_DIST_PCT:
            out.append((mid, "FVG-mid 15m"))
    return out[-3:]                                      # свежайшие 3


def build_targets(sym: str, side: str, px: float) -> list[dict]:
    """3 слоя → кластеризация ±0.3% → до 3 целей (ближняя первой).

    side: 'SHORT' → цели НИЖЕ px, 'LONG' → ВЫШЕ. Возврат: [{px, tags, star}].
    """
    levels = (_magnet_levels(sym, side) + _pivot_levels(sym, side, px)
              + _fvg_levels(sym, side, px))
    if not levels:
        return []
    levels.sort(key=lambda x: x[0])
    clusters: list[dict] = []
    for lvl, tag in levels:
        if clusters and abs(lvl / clusters[-1]["px"] - 1) * 100 <= CLUSTER_TOL_PCT:
            c = clusters[-1]
            c["tags"].append(tag)
            c["px"] = (c["px"] * (len(c["tags"]) - 1) + lvl) / len(c["tags"])
        else:
            clusters.append({"px": lvl, "tags": [tag]})
    for c in clusters:
        c["star"] = len(c["tags"]) >= 2                  # конфлюэнция 2+ слоёв = усилена
    clusters.sort(key=lambda c: abs(c["px"] - px))       # ближняя цель первой
    return clusters[:MAX_TARGETS]


def format_targets_block(targets: list[dict], px: float) -> str:
    """Блок для TG-алерта (HTML). Пусто если целей нет."""
    if not targets:
        return ""
    lines = ["🧲 TP"]
    for t in sorted(targets, key=lambda c: abs(c["px"] - px)):
        star = " ★" if t["star"] else ""
        lines.append(f"✅ <code>{_fmt(t['px'])}</code> ({(t['px']/px-1)*100:+.1f}%){star} "
                     f"· {' + '.join(t['tags'])}")
    return "\n".join(lines)
