"""
cube_projection.py — урезанная проекция состояния пары для фильтр-конструктора терминала.

Одна функция на две стороны (инвариант «один калькулятор на признак»):
  • бот — `web/dashboard_server.py` `/api/cube/snapshot_all` (из PairState);
  • терминал — поверх хаба Куба (`cube-hub` GET /state, dict после JSON), ADR-003 шаг 2.
Хаб ничего не считает: проекцию применяет читатель.
"""
from __future__ import annotations


def filter_record(st) -> dict:
    """Урезанный per-coin стейт для фильтр-конструктора (Егор 29.07): WT per-TF + SMC by_tf +
    пивоты + флаги. Только то, по чему фильтруем — payload лёгкий для bulk по 500 монетам.
    `st` — PairState (бот) или dict его полей (хаб)."""
    g = st.get if isinstance(st, dict) else (lambda k: getattr(st, k, None))
    smc = g("smc_snap") or {}
    wt = g("wt_snap") or {}
    wt_out = {}
    for tf, w in (wt.items() if isinstance(wt, dict) else []):
        if isinstance(w, dict):
            # wt2 нужен фильтру, чтобы отличать СОСТОЯНИЕ кросса (wt1 выше/ниже сигнальной,
            # держится до обратного пересечения) от МОМЕНТА пересечения (живёт один бар).
            # Егор 19.08: «кросс — историческое событие, оно живёт до обратного кросса».
            wt_out[tf] = {"wt1": w.get("wt1"), "wt2": w.get("wt2"),
                          "zone": w.get("zone"), "cross": w.get("wt_cross"),
                          "trend": w.get("trend"), "atr": w.get("atr_trend")}
    smc_bt = {}
    for tf, s in (smc.get("by_tf") or {}).items():
        smc_bt[tf] = {"ob_bull": bool(s.get("ob_bull")), "ob_bear": bool(s.get("ob_bear")),
                      "ob_bull_d": (s.get("ob_bull") or {}).get("distance_pct"),
                      "ob_bear_d": (s.get("ob_bear") or {}).get("distance_pct"),
                      "fvg_bull": s.get("fvg_bull"), "fvg_bear": s.get("fvg_bear"),
                      "choch": s.get("choch"), "bos": s.get("bos")}
    piv = g("pivot_snap") or {}
    piv_out = {}
    for _ptf in ("1W", "1D", "1M"):
        _d = piv.get(_ptf) or {}
        _lv = {k: _d.get(k) for k in ("PP", "R1", "R2", "R3", "S1", "S2", "S3")
               if isinstance(_d.get(k), (int, float))}
        if _lv:
            piv_out[_ptf] = _lv
    return {"px": g("tick_price"), "regime": g("regime"), "wt": wt_out, "smc": smc_bt,
            "eqh_near": smc.get("eqh_near"), "eql_near": smc.get("eql_near"),
            "in_ote": smc.get("price_in_ote"), "piv": piv_out}
