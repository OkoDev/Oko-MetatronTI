# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА V2 — двухмасштабный вход (ТЗ: docs/OTE_METHOD_ENTRY_V2.md, урок ZEC 04.07).

Оба масштаба на ОДНОМ ТФ (как показывал Егор на 1h): len50 = значимая структура
(направление большого импульса + подтверждение), len5 = внутренняя (триггеры).

Цикл: СТОРОНА (позиция ОСНОВАНИЯ слома в большом импульсе: у края → разворот) →
len5 CHoCH триггер → ВХОД на откате-ретесте сломанного уровня (стоп тугой за локальный
экстремум) → СЕРИЯ: пока структура серии жива, каждый следующий small-слом по направлению
= новый вход (Егор: «стоп короткий, цель огромная, на пути открываем на откатах в одном
направлении») → len50-флип в сторону серии = подтверждение (серия продолжается как
continuation) → цели = единая фибо-сетка БОЛЬШОГО импульса (0.5/0.62/0.705 отката;
формула Егора level(f) = end − f×range, отрицательные f = продолжение за конец).

Walk-forward-safe: сетап формируется строго на баре len5-слома из баров ≤ этого бара.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from core.smc.smc_engine import detect_structure_breaks


def fib_grid(start: float, end: float, fibs=(0.5, 0.62, 0.705)) -> list[float]:
    """Единая сетка Егора: level(f) = end − f×(end−start). f=0 конец, f=1 начало,
    f<0 — продолжение за конец (та же шкала, НЕ отдельный extension)."""
    rng = end - start
    return [end - f * rng for f in fibs]


@dataclass
class V2Setup:
    kind: str            # 'reversal' | 'series' (вход серии до len50) | 'continuation' (после)
    direction: str       # 'LONG' | 'SHORT'
    trigger_idx: int     # бар len5-слома (сетап известен с этого бара)
    trigger_ts: object
    entry: float         # ретест сломанного len5-уровня
    sl: float            # за основание слома (локальный экстремум)
    targets: list        # [t1, t2, t3] по большой сетке
    big_lo: float
    big_hi: float
    pos: float           # позиция ОСНОВАНИЯ слома в большом импульсе (0=lo, 1=hi)
    big_dir: str         # 'bull' | 'bear' на момент триггера
    conf: bool = False   # КОНФЛЮЭНЦИЯ: entry совпал с уровнем сетки ПРЕДЫДУЩЕГО большого
                         # импульса (урок Егора: «вход там, где сетки пересеклись»)


def detect_method_v2(
    df: pd.DataFrame,
    len_big: int = 50,
    len_small: int = 5,
    edge: float = 0.25,          # основание слома в крайней четверти большого импульса = «у края»
                                 # (ZEC: higher-low 385 при дне 368 = pos 0.17 — тоже край)
    sl_buf_pct: float = 0.3,
    min_range_pct: float = 3.0,  # большой импульс тоньше — шум/флэт, не размечаем
    max_series: int = 4,         # максимум входов одной серии (анти-размазывание)
) -> List[V2Setup]:
    """Все сетапы метода на df (event-driven, walk-forward)."""
    d = df.copy()
    d.columns = [c.lower() for c in d.columns]
    close = d["close"].values
    high = d["high"].values
    low = d["low"].values
    n = len(d)
    if n < len_big * 2 + 10:
        return []

    br_big = detect_structure_breaks(d, length=len_big)
    br_small = detect_structure_breaks(d, length=len_small)
    if not br_small:
        return []

    out: List[V2Setup] = []
    bi = 0
    big_state: list = []
    series_dir: str | None = None     # активная серия ('LONG'/'SHORT') после reversal-триггера
    series_n = 0
    series_grid: list = []            # цели серии (большая сетка на момент reversal)
    series_big: tuple = (0.0, 0.0)

    # полная шкала для конфлюэнции сеток (единая, с минус-уровнями — «−2 предыдущего = вход»)
    conf_fibs = (-2.0, -1.618, -1.0, -0.62, -0.27, 0.0, 0.27, 0.5, 0.62, 0.705, 0.79, 1.0)
    conf_tol_pct = 0.3

    def _conf(entry_px: float, prev_lo: float, prev_hi: float, prev_dir_bull: bool) -> bool:
        """entry совпал (±0.3%) с уровнем единой сетки ПРЕДЫДУЩЕГО импульса."""
        if prev_hi <= prev_lo or entry_px <= 0:
            return False
        start, end = (prev_lo, prev_hi) if prev_dir_bull else (prev_hi, prev_lo)
        for f in conf_fibs:
            lvl = end - f * (end - start)
            if lvl > 0 and abs(entry_px - lvl) / entry_px * 100 <= conf_tol_pct:
                return True
        return False

    for s in br_small:
        i = s.idx
        while bi < len(br_big) and br_big[bi].idx <= i:
            big_state.append(br_big[bi]); bi += 1
        if not big_state:
            continue
        big_dir = big_state[-1].direction
        j_start = 0
        j_prev = 0                    # начало ПРЕДЫДУЩЕГО импульса (для конфлюэнции сеток)
        _seen_opp = False
        for b in reversed(big_state):
            if not _seen_opp and b.direction != big_dir:
                j_start = b.idx
                _seen_opp = True
            elif _seen_opp and b.direction == big_dir:
                j_prev = b.idx
                break
        lo_imp = float(low[j_start:i + 1].min())
        hi_imp = float(high[j_start:i + 1].max())
        # предыдущий импульс (противоположный текущему): [j_prev .. j_start]
        prev_lo = float(low[j_prev:j_start + 1].min()) if j_start > j_prev else 0.0
        prev_hi = float(high[j_prev:j_start + 1].max()) if j_start > j_prev else 0.0
        if lo_imp <= 0 or (hi_imp - lo_imp) / lo_imp * 100 < min_range_pct:
            continue
        rng = hi_imp - lo_imp
        fi = s.from_idx if s.from_idx >= 0 else max(0, i - len_small * 3)
        base_lo = float(low[fi:i + 1].min())     # основание слома (для LONG-триггера)
        base_hi = float(high[fi:i + 1].max())    # для SHORT-триггера

        # ── отмена серии: small CHoCH против направления серии ──
        if series_dir == "LONG" and s.kind == "CHoCH" and s.direction == "bear":
            series_dir = None
        elif series_dir == "SHORT" and s.kind == "CHoCH" and s.direction == "bull":
            series_dir = None

        # ── РАЗВОРОТ у края (старт серии): CHoCH против big, основание в крайней зоне ──
        cf = _conf(float(s.price), prev_lo, prev_hi, big_dir == "bear")
        if series_dir is None and big_dir == "bull" and s.kind == "CHoCH" and s.direction == "bear" \
                and (base_hi - lo_imp) / rng >= 1 - edge:
            grid = fib_grid(lo_imp, hi_imp)
            out.append(V2Setup("reversal", "SHORT", i, s.ts, float(s.price),
                               base_hi * (1 + sl_buf_pct / 100), grid, lo_imp, hi_imp,
                               (base_hi - lo_imp) / rng, big_dir, cf))
            series_dir, series_n, series_grid, series_big = "SHORT", 1, grid, (lo_imp, hi_imp)
            continue
        if series_dir is None and big_dir == "bear" and s.kind == "CHoCH" and s.direction == "bull" \
                and (base_lo - lo_imp) / rng <= edge:
            grid = fib_grid(hi_imp, lo_imp)
            out.append(V2Setup("reversal", "LONG", i, s.ts, float(s.price),
                               base_lo * (1 - sl_buf_pct / 100), grid, lo_imp, hi_imp,
                               (base_lo - lo_imp) / rng, big_dir, cf))
            series_dir, series_n, series_grid, series_big = "LONG", 1, grid, (lo_imp, hi_imp)
            continue

        # ── СЕРИЯ: входы на откатах по направлению активной серии ──
        # kind='series' пока big против/не подтвердил; 'continuation' после len50-флипа.
        # ЦЕЛИ = ПРОДОЛЖЕНИЕ актуального импульса (extension за экстремум по единой шкале Егора),
        # НЕ старая сетка разворота — иначе поздние входы целятся в пройденные уровни (дефект v2.0).
        # Вход валиден только если entry НЕ за t1 (иначе цель уже взята — пропуск).
        if series_dir == "LONG" and s.direction == "bull" and series_n < max_series:
            confirmed = big_dir == "bull"
            tg = [hi_imp + 0.27 * rng, hi_imp + 0.62 * rng, hi_imp + 1.0 * rng]
            entry = float(s.price)
            if entry < tg[0]:                             # есть ход до первой цели
                out.append(V2Setup("continuation" if confirmed else "series", "LONG", i, s.ts,
                                   entry, base_lo * (1 - sl_buf_pct / 100),
                                   tg, lo_imp, hi_imp, (base_lo - lo_imp) / rng, big_dir, cf))
                series_n += 1
        elif series_dir == "SHORT" and s.direction == "bear" and series_n < max_series:
            confirmed = big_dir == "bear"
            tg = [lo_imp - 0.27 * rng, lo_imp - 0.62 * rng, lo_imp - 1.0 * rng]
            entry = float(s.price)
            if entry > tg[0] > 0:
                out.append(V2Setup("continuation" if confirmed else "series", "SHORT", i, s.ts,
                                   entry, base_hi * (1 + sl_buf_pct / 100),
                                   tg, lo_imp, hi_imp, (base_hi - lo_imp) / rng, big_dir, cf))
                series_n += 1
    return out
