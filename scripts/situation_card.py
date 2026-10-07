# -*- coding: utf-8 -*-
"""СИТУАЦИОННАЯ КАРТА — «что сейчас по монете и сколько такое состояние стоило за три года»
(Егор 08.10: «начинай! как карта ляжет на :3000 и :8010?»; видение 15.06 — бот как якорь против эмоции).

Карта — НЕ сигнал. Это базовая частота: в часах с тем же ключом ситуации за 2023→сейчас по всем монетам —
сколько в среднем дал лонг и шорт на 24 ч ПОСЛЕ коста 0.35, как часто вверх, худшие/лучшие 10%, и исход по
стопу/цели. Плюс то, что уже ИЗМЕРЕНО (реестр вердиктов), и стоп-кран для ручного входа.

Три части:
  · `build_cells()`  — таблица ячеек из журнала общего состояния (`G:/oko_lab/joint/1h`), раз в сутки после
    пересборки журнала (joint_daily). Ключ — 7 простых осей, заданных ДО подсчёта (см. `situation_key`).
  · `current_vector(base)` — та же строка журнала, но по ЖИВЫМ закрытым барам BingX из `market-store`
    (тот же код `joint_state_journal.build` → замер и бой видят один вектор). Кэш 10 мин.
  · `card(base, side)` — состояние по сферам словами + базовые частоты (вся вселенная и сама монета) +
    измеренные вердикты + уровень стоп-крана для стороны.

🔴 Честность: n часов завышено — соседние часы одного состояния зависимы; эффективная выборка — ДНИ (печатаем).
Ячейка не проходила карточку вердикта: «база не против» ≠ «эдж есть».
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

JOURNAL = Path("G:/oko_lab/joint/1h")
CELLS = Path("G:/oko_lab/joint/situation_cells.parquet")
COST = 0.35
KEY = ["k_wt1h", "k_wt4h", "k_tr4h", "k_vol", "k_legup", "k_legdn", "k_wave"]
NEED = ["wt_os_1h", "wt_ob_1h", "wt_os_4h__from_4h", "wt_ob_4h__from_4h", "atr_up_4h__from_4h",
        "atr_prank_1h", "legup_depth", "legdn_depth", "w_side", "fwd_24", "geo_wide_long", "geo_wide_short"]
TTL = 600
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


# ─────────────────────────────── ключ ситуации ───────────────────────────────

def _band3(x: np.ndarray, a: float, b: float) -> np.ndarray:
    return np.where(~np.isfinite(x), -1, np.where(x < a, 0, np.where(x <= b, 1, 2)))


def situation_key(D: pd.DataFrame) -> pd.DataFrame:
    """7 осей, заданных до подсчёта: WT 1h и 4h (OS/норма/OB) · ATR-тренд 4h · волатильность 1h к своей
    истории (терцили) · глубина дневной ноги вверх и вниз (мелкая <0.5 / 0.5–0.79 вкл. OTE / глубже) ·
    сторона видимой пятёрки ядра."""
    g = lambda c: D[c].astype(float).values if c in D.columns else np.full(len(D), np.nan)   # noqa: E731
    zone = lambda os_, ob_: np.where(g(os_) == 1, -1, np.where(g(ob_) == 1, 1, 0))           # noqa: E731
    up4 = g("atr_up_4h__from_4h")
    ws = g("w_side")
    return pd.DataFrame({
        "k_wt1h": zone("wt_os_1h", "wt_ob_1h"),
        "k_wt4h": zone("wt_os_4h__from_4h", "wt_ob_4h__from_4h"),
        "k_tr4h": np.where(~np.isfinite(up4), 0, np.where(up4 == 1, 1, -1)),
        "k_vol": _band3(g("atr_prank_1h"), 0.33, 0.66),
        "k_legup": _band3(g("legup_depth"), 0.5, 0.79),
        "k_legdn": _band3(g("legdn_depth"), 0.5, 0.79),
        "k_wave": np.where(np.isfinite(ws), ws, 0),
    }, index=D.index).astype(int)


# ─────────────────────────────── таблица ячеек ───────────────────────────────

def build_cells(out: Path = CELLS) -> pd.DataFrame:
    parts = []
    for f in sorted(JOURNAL.glob("*.parquet")):
        try:
            cols = [c for c in NEED if c in set(__import__("pyarrow.parquet", fromlist=["x"]).read_schema(f).names)]
            J = pd.read_parquet(f, columns=cols)
        except Exception:                                # noqa: BLE001
            continue
        K = situation_key(J)
        K["sym"] = f.stem
        K["day"] = J.index.floor("D")
        K["year"] = J.index.year
        K["fl"] = J["fwd_24"].astype(float).values
        K["gl"] = J["geo_wide_long"].astype(float).values if "geo_wide_long" in J else np.nan
        K["gs"] = J["geo_wide_short"].astype(float).values if "geo_wide_short" in J else np.nan
        parts.append(K[np.isfinite(K.fl.values)])
    A = pd.concat(parts, ignore_index=True)
    rows = []
    for key, g in A.groupby(KEY):
        r = dict(zip(KEY, key))
        r.update(n=len(g), n_days=g.day.nunique(), n_coins=g.sym.nunique())
        for side, v, geo in (("long", g.fl.values, g.gl.values), ("short", -g.fl.values, g.gs.values)):
            net = v - COST
            gn = geo[np.isfinite(geo)] - COST
            r[f"{side}_mean"] = net.mean()
            r[f"{side}_median"] = float(np.median(net))
            r[f"{side}_p_up"] = (net > 0).mean()
            r[f"{side}_p10"], r[f"{side}_p90"] = np.percentile(net, [10, 90])
            r[f"{side}_geo"] = gn.mean() if len(gn) else np.nan
            early, late = net[g.year.values <= 2024], net[g.year.values >= 2025]
            r[f"{side}_mean_23_24"] = early.mean() if len(early) else np.nan
            r[f"{side}_mean_25_26"] = late.mean() if len(late) else np.nan
        rows.append(r)
    C = pd.DataFrame(rows)
    C.attrs["built"] = pd.Timestamp.utcnow().isoformat()
    C.to_parquet(out)
    print(f"ячеек {len(C)} · строк журнала {len(A):,} · монет {A.sym.nunique()} · → {out}", flush=True)
    return C


# ─────────────────────────────── живой вектор ───────────────────────────────

def current_vector(base: str) -> pd.Series:
    """Последний ЗАКРЫТЫЙ час монеты: строка журнала по барам BingX из market-store (тот же build)."""
    import core.infra.market_store as M
    import joint_state_journal as JJ
    base = M.base_of(base)
    df = M.read_bars(base, "1h")
    if df is None or len(df) < 800:
        raise ValueError(f"мало 1h-баров BingX по {base}: {0 if df is None else len(df)}")
    d15 = M.read_bars(base, "15m")
    J = JJ.build(f"{base}/USDT", df, d15)
    return J.iloc[-1]


# ─────────────────────────────── реестр измеренного ───────────────────────────────
# Только то, что ИЗМЕРЕНО и записано в памяти; каждая строка — вердикт с источником. Пополнять отсюда.
# `when(r, x)`: r — строка вектора, x — контекст сделки ({"stop_pct": …} из окна ордера, если стоп известен).
# 08.10 (SKR из Oko-WAVES: стоп 0.59%, фрактал ✗): клетка ядра доказана ТОЛЬКО при стопе ≥6% — без проверки стопа
# вердикт 🟢 загорелся бы на сделке, которой клетка не касается.
CELL_STOP = 6.0


def _in_cell(r, x):
    s = x.get("stop_pct")
    return r.get("w_side") == 1 and r.get("w_core_full") == 1 and (s is None or s >= CELL_STOP)


def _why_out(r, x):
    out = []
    if r.get("w_core_full") != 1:
        out.append("ядро не полное")
    if x.get("stop_pct") is not None and x["stop_pct"] < CELL_STOP:
        out.append(f"стоп {x['stop_pct']:.2f}% < {CELL_STOP:.0f}%")
    return " · ".join(out)


REGISTRY = [
    {"id": "waves_long_core", "side": "BUY", "status": "🟢",
     "when": _in_cell,
     "text": lambda r, x: ("Лонг ядра волн в доказанной клетке (полное ядро, стоп ≥6%"
                           + ("" if x.get("stop_pct") is not None else " — стоп сделки не передан, проверь")
                           + "): PF 2.79, +4.56%/сд на 2023-26 (170 сд.), 4/4 года; форвард 23.08–07.10 — 16 сд., "
                             "PF 0.83. Держится в КЛАСТЕРАХ (одиночка −1.4%)"),
     "src": "wave_entry_delay_cost · verify_card_unified"},
    {"id": "waves_long_outside", "side": "BUY", "status": "🟡",
     "when": lambda r, x: r.get("w_side") == 1 and not _in_cell(r, x),
     "text": lambda r, x: (f"Сетап волн ЛОНГ ВНЕ доказанной клетки ({_why_out(r, x)}): все лонги ядра 2023-26 — "
                           "+1.31%/сд, PF 1.60, но медиана −1.74% и без лучших 10% −0.97% (держится на хвосте); "
                           "в бою риск 0.5%"),
     "src": "verify_card_unified (S1 вся база)"},
    {"id": "waves_short_none", "side": "SELL", "status": "⚠️",
     "when": lambda r, x: r.get("w_side") == -1,
     "text": "Шорт ядра волн: клетки НЕТ — полное ядро ∧ стоп ≥6% PF 0.64 (−2.04%/сд), шорт идёт за режимом года",
     "src": "waves_sides_measured_both"},
    {"id": "capitulation", "side": "BUY", "status": "🟡",
     "when": lambda r, x: r.get("wt_os_1h") == 1 and r.get("atr_vol_high_1h") == 1,
     "text": "Капитуляция (WT 1h в OS при высокой волатильности): лонг +1.11% за 24 ч на 2023-25, PF 1.52, 72% монет — "
             "но без 71 лучшего дня −1.34%: эффект живёт в днях обвалов. Карточку НЕ прошла",
     "src": "joint_trigger_search_wt_capitulation"},
]


# ─────────────────────────────── карта ───────────────────────────────

def _f(x, nd=1, sign=False):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def _zone(v):
    if v is None or not np.isfinite(v):
        return "—"
    return f"{v:+.0f}" + (" OS" if v < -60 else " OB" if v > 60 else "")


def _band_txt(d):
    if d is None or not np.isfinite(d):
        return "—"
    from core.smc.fibonacci import ote_band
    return f"{d:.2f} ({ote_band(d)})"


def _state(r: dict) -> dict:
    """Состояние по сферам — человеческим языком."""
    def flag(c):
        v = r.get(c)
        return v is not None and np.isfinite(v) and v == 1
    tr = lambda c: "↑" if flag(c) else ("↓" if r.get(c) is not None and np.isfinite(r.get(c)) else "?")   # noqa: E731
    wt = (f"15m {_zone(r.get('wt1_15m'))} · 1h {_zone(r.get('wt1_1h'))} · 4h {_zone(r.get('wt1_4h'))} · "
          f"1d {_zone(r.get('wt1_1d'))}")
    ev = [n for c, n in (("wt_cross_up_15m_in_h", "кросс вверх"), ("wt_cross_dn_15m_in_h", "кросс вниз"),
                         ("wt_enter_os_15m_in_h", "вход в OS"), ("wt_enter_ob_15m_in_h", "вход в OB")) if flag(c)]
    smc = [n for c, n in (("ote_long_1h", "OTE лонга 1h"), ("ote_short_1h", "OTE шорта 1h"),
                          ("ote_long_4h__from_4h", "OTE лонга 4h"), ("ote_short_4h__from_4h", "OTE шорта 4h"),
                          ("discount_4h__from_4h", "discount 4h"), ("premium_4h__from_4h", "premium 4h")) if flag(c)]
    liq = (f"до ликвидности снизу {_f(r.get('liq_dn_dist_pct_1h'))}% · сверху {_f(r.get('liq_up_dist_pct_1h'))}%")
    piv = [n for c, n in (("pivot_above_PP_1D", "выше PP дня"), ("pivot_below_PP_1D", "ниже PP дня"),
                          ("pivot_above_R1_1D", "выше R1 дня"), ("pivot_below_S1_1D", "ниже S1 дня"),
                          ("pivot_above_PP_1W", "выше PP недели"), ("pivot_below_PP_1W", "ниже PP недели")) if flag(c)]
    ws = r.get("w_side")
    if ws is not None and np.isfinite(ws) and ws != 0:
        wave = (f"видна пятёрка → сетап {'ЛОНГ' if ws > 0 else 'ШОРТ'}"
                f"{' (полное ядро)' if flag('w_core_full') else ''} · откат {_band_txt(r.get('w_retr'))} · "
                f"возраст {_f(r.get('w_age_h'), 0)} ч")
    else:
        wave = "пятёрки ядра 4h не видно"
    pr = r.get("atr_prank_1h")
    return {
        "WT": wt + (f" · за час 15m: {', '.join(ev)}" if ev else ""),
        "ATR-тренд": f"1h {tr('atr_up_1h')} · 4h {tr('atr_up_4h__from_4h')} · 1d {tr('atr_up_1d__from_1d')}",
        "Волатильность": (f"ATR 1h — {pr * 100:.0f}-й перцентиль своей истории" if pr is not None and np.isfinite(pr)
                          else "—"),
        "SMC": (", ".join(smc) + " · " if smc else "") + liq,
        "Пивоты": ", ".join(piv) or "—",
        "Волна ядра": wave,
        "Дневная нога": f"вверх {_band_txt(r.get('legup_depth'))} · вниз {_band_txt(r.get('legdn_depth'))}",
        "Режим": f"дрейф вселенной 30д {_f(r.get('mkt_drift30'), 1, True)}%",
        "Позиционирование": (f"розница L/S {_f(r.get('pos_retail_ls'), 2)} · топы {_f(r.get('pos_top_ls'), 2)} · "
                             f"ΔOI 24ч {_f(r.get('pos_doi_24h'), 1, True)}%"
                             if r.get("pos_retail_ls") is not None and np.isfinite(r.get("pos_retail_ls"))
                             else "нет свежих (Binance отдаёт метрики по вчера)"),
    }


def _rates(c: pd.Series | None) -> dict | None:
    if c is None:
        return None
    out = {"n": int(c.n), "n_days": int(c.n_days), "n_coins": int(c.n_coins)}
    for s in ("long", "short"):
        out[s] = {k: (None if not np.isfinite(c[f"{s}_{k}"]) else round(float(c[f"{s}_{k}"]), 3))
                  for k in ("mean", "median", "p_up", "p10", "p90", "geo", "mean_23_24", "mean_25_26")}
    return out


def _coin_rates(base: str, key: dict) -> dict | None:
    f = JOURNAL / f"{base}USDT.parquet"
    if not f.exists():
        return None
    import pyarrow.parquet as pq
    cols = [c for c in NEED if c in set(pq.read_schema(f).names)]
    J = pd.read_parquet(f, columns=cols)
    K = situation_key(J)
    m = np.ones(len(J), bool)
    for k, v in key.items():
        m &= K[k].values == v
    v = J.fwd_24.astype(float).values[m]
    v = v[np.isfinite(v)]
    if len(v) < 24:
        return {"n": int(len(v))}
    days = J.index[m].floor("D").nunique()
    return {"n": int(len(v)), "n_days": int(days),
            "long_mean": round(float(np.mean(v - COST)), 3), "short_mean": round(float(np.mean(-v - COST)), 3),
            "long_p_up": round(float(np.mean(v - COST > 0)), 3)}


REL = 0.2      # п.п.: насколько ситуация должна отличаться от ОБЫЧНОГО часа, чтобы это показывать


def side_base(C: pd.DataFrame) -> dict:
    """Обычный час: средний исход стороны по всем часам журнала (вес — число часов в ячейке)."""
    w = C.n.values.astype(float)
    return {s: float(np.average(C[f"{s}_mean"].values, weights=w)) for s in ("long", "short")}


def _stop_level(side: str | None, rates: dict | None, hits: list[dict], base: dict | None) -> dict:
    """Стоп-кран ОТНОСИТЕЛЬНО ОБЫЧНОГО ЧАСА (08.10). По абсолютному знаку он горел бы всегда: вход на сутки в
    случайный час — минус коста для обеих сторон (в плюсе лишь 10% часов лонга и 4% шорта).
    ⛔ — ситуация для этой стороны хуже обычного и в 2023-24, и в 2025-26 (дней ≥ 30);
    ⚠️ — хуже обычного в целом, но не в обоих периодах, или измеренный вердикт против;
    ✅ — лучше обычного в обоих периодах (это всё ещё НЕ сигнал); ➖ — как обычно."""
    if side not in ("BUY", "SELL"):
        return {"level": None}
    s = "long" if side == "BUY" else "short"
    nm = "лонг" if s == "long" else "шорт"
    why, lvl = [], "same"
    if rates and base and rates.get("n_days", 0) >= 30:
        r, b = rates[s], base[s]
        m, e, l_ = r.get("mean"), r.get("mean_23_24"), r.get("mean_25_26")
        if m is not None:
            d = m - b
            why.append(f"{nm} в похожих часах {m:+.2f}% за 24 ч после коста, в обычный час {b:+.2f}% "
                       f"→ {'хуже' if d < 0 else 'лучше'} обычного на {abs(d):.2f} п.п.")
            stable_bad = e is not None and l_ is not None and e < b and l_ < b
            stable_good = e is not None and l_ is not None and e > b and l_ > b
            if d < -REL and stable_bad:
                lvl = "stop"
                why.append(f"хуже обычного и в 2023-24 ({e:+.2f}%), и в 2025-26 ({l_:+.2f}%)")
            elif d < -REL:
                lvl = "warn"
            elif d > REL and stable_good:
                lvl = "better"
                why.append(f"лучше обычного и в 2023-24 ({e:+.2f}%), и в 2025-26 ({l_:+.2f}%) — но это не сигнал")
    elif rates is not None:
        why.append(f"похожих дней мало ({rates.get('n_days', 0)}) — база не говорит ничего")
    for h in hits:
        if h["side"] == side and h["status"] == "⚠️":
            lvl = "stop" if lvl == "stop" else "warn"
            why.append(h["text"])
    return {"level": lvl, "why": why}


def card(base: str, side: str | None = None, stop: float | None = None) -> dict:
    """stop — цена стопа сделки (окно ордера / пост сигнала): без неё вердикты, завязанные на размер стопа
    (клетка ядра волн — стоп ≥6%), честно пишут «стоп не передан»."""
    import core.infra.market_store as M
    base = M.base_of(base)
    side = (side or "").upper() or None
    now = time.time()
    with _lock:
        hit = _cache.get(base)
    if hit and now - hit[0] < TTL:
        vec_info = hit[1]
    else:
        row = current_vector(base)
        vec_info = {"row": {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else v)
                            for k, v in row.items() if k != "sym"},
                    "ts": str(row.name)}
        with _lock:
            _cache[base] = (now, vec_info)
    r = vec_info["row"]
    key = situation_key(pd.DataFrame([r])).iloc[0].to_dict()
    C = pd.read_parquet(CELLS) if CELLS.exists() else None
    cell = None
    if C is not None:
        m = np.ones(len(C), bool)
        for k, v in key.items():
            m &= C[k].values == v
        cell = C[m].iloc[0] if m.any() else None
    rates = _rates(cell)
    sb = side_base(C) if C is not None else None
    px = r.get("close")
    x = {"stop_pct": (abs(px - float(stop)) / px * 100) if stop and px else None}
    hits = [{"id": h["id"], "side": h["side"], "status": h["status"],
             "text": h["text"](r, x) if callable(h["text"]) else h["text"], "src": h["src"]}
            for h in REGISTRY if h["when"](r, x)]
    return {
        "base": base, "hour": vec_info["ts"], "price": r.get("close"),
        "state": _state(r), "key": key, "rates": rates, "coin": _coin_rates(base, key),
        "usual": None if sb is None else {k: round(v, 3) for k, v in sb.items()},
        "verdicts": hits, "stop": _stop_level(side, rates, hits, sb), "side": side,
        "cells_built": None if C is None else C.attrs.get("built"),
        "note": "Базовая частота, не сигнал: ячейка не проходила карточку вердикта. Часы зависимы — смотреть ДНИ.",
    }


def summary_text(c: dict) -> str:
    """Короткий текст для окна подтверждения ордера."""
    L = [f"КАРТА {c['base']} · закрытый час {str(c['hour'])[:16]} UTC"]
    for k in ("WT", "Волна ядра", "Дневная нога", "Режим"):
        L.append(f"{k}: {c['state'][k]}")
    r, u = c.get("rates"), c.get("usual") or {}
    if r:
        lo, sh = r["long"], r["short"]
        L.append(f"Похожих: {r['n_days']} дн., {r['n_coins']} монет · 24ч после коста: "
                 f"лонг {_f(lo['mean'], 2, True)}% (обычно {_f(u.get('long'), 2, True)}%) · "
                 f"шорт {_f(sh['mean'], 2, True)}% (обычно {_f(u.get('short'), 2, True)}%)")
    else:
        L.append("Похожих ситуаций в истории не найдено")
    for h in c["verdicts"]:
        L.append(f"{h['status']} {h['text']}")
    st = c.get("stop") or {}
    if st.get("level"):
        L.append(LEVEL_TXT[st["level"]] + (": " + "; ".join(st["why"]) if st.get("why") else ""))
    return "\n".join(L)


LEVEL_TXT = {"better": "✅ ЛУЧШЕ ОБЫЧНОГО для этой стороны (не сигнал)", "same": "➖ КАК ОБЫЧНО",
             "warn": "⚠️ ХУЖЕ ОБЫЧНОГО для этой стороны", "stop": "⛔ СТАБИЛЬНО ХУЖЕ ОБЫЧНОГО для этой стороны"}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                    # noqa: BLE001
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "card"
    if cmd == "cells":
        build_cells()
    else:
        b = sys.argv[2] if len(sys.argv) > 2 else "BTC"
        sd = sys.argv[3] if len(sys.argv) > 3 else None
        t0 = time.time()
        c = card(b, sd)
        print(summary_text(c))
        print(f"\n({time.time() - t0:.1f} с)")
