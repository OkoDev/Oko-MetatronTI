# -*- coding: utf-8 -*-
"""СБОРКА ИМПУЛЬСА ПО CHoCH+BOS (мысль Егора 10.08 про волновую теорию).

Один калькулятор для бэктестов и живых shadow — различия параметрами, не копипастой.

Идея: одна нога (`current_leg`) — это ПОДСЕГМЕНТ, а импульсная волна складывается из
нескольких. Складывать её надо не на глаз, а по структуре: **CHoCH задаёт СТАРТ импульса,
каждый последующий BOS приваривает ногу, текущий экстремум — КОНЕЦ**.

Методика ICT говорит то же: свинг годен под OTE только ПОСЛЕ того как дал BOS/CHoCH, и фибо
тянут от лоу, С КОТОРОГО начался ход, до хая, КОТОРЫМ он закончился.

Измерено ([[ote_impulse_assembly_choch_bos]], 150 монет, 10k сделок, косты 0.35%):
отделение свингов с BOS от свингов без него поднимает PF 0.76 → 1.00.
Разрез по фазе и стороне ([[ote_short_impulsive_first_robust_cell]]):
импульсный режим + SHORT + n_bos≥1 → PF 2.10, WR 70%, безтоп10% +266%.
"""
from __future__ import annotations

from typing import Optional


def assemble_impulse(st, high, low, internal: bool = True) -> Optional[dict]:
    """Собрать импульс из состояния структуры `SMState` (см. core/smc/oko_sm_engine).

    high/low — массивы/Series ТОГО ЖЕ окна, на котором считался `st`.
    internal=True — внутренняя шкала (len5), False — старшая (swing50).

    Возвращает dict(origin, extreme, is_long, n_bos, i_choch) или None.
    n_bos = сколько ног приварилось BOS-ами после CHoCH («длина» импульса).
    """
    evs = [e for e in st.events if bool(e.internal) == internal]
    if not evs:
        return None
    is_long = (st.itrend if internal else st.trend) > 0
    i_ch = pos = None
    for k in range(len(evs) - 1, -1, -1):          # последний CHoCH В СТОРОНУ тренда
        if evs[k].kind == "CHoCH" and bool(evs[k].bull) == is_long:
            i_ch = int(evs[k].i); pos = k
            break
    if i_ch is None:
        return None
    # origin = структурный экстремум ДО слома характера
    i_prev = int(evs[pos - 1].i) if pos > 0 else max(0, i_ch - 60)
    a, b = max(0, min(i_prev, i_ch - 1)), i_ch + 1
    if b - a < 2:
        return None
    hi = getattr(high, "values", high)
    lo = getattr(low, "values", low)
    origin = float(min(lo[a:b])) if is_long else float(max(hi[a:b]))
    extreme = float(max(hi[i_ch:])) if is_long else float(min(lo[i_ch:]))
    if (is_long and extreme <= origin) or ((not is_long) and extreme >= origin):
        return None
    n_bos = sum(1 for e in evs[pos + 1:] if e.kind == "BOS" and bool(e.bull) == is_long)
    return {"origin": origin, "extreme": extreme, "is_long": is_long,
            "n_bos": n_bos, "i_choch": i_ch}


def ote_zone(origin: float, extreme: float, is_long: bool,
             lo_fib: float = 0.618, hi_fib: float = 0.786) -> tuple[float, float]:
    """Зона OTE отката собранного импульса → (нижняя граница, верхняя границa)."""
    rng = abs(extreme - origin)
    if is_long:
        return extreme - hi_fib * rng, extreme - lo_fib * rng
    return extreme + lo_fib * rng, extreme + hi_fib * rng
