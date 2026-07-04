# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА V2-MTF — фрактальный вход (Егор 04.07: «вход на младших ТФ на опережение,
в третью волну первой волны старшего ТФ»).

Старший ТФ (4h) начинает импульс = ВОЛНА 1 старшего. Внутри неё младший (1h) рисует свою
5-волновку. ВХОД = ВОЛНА 3 младшего (сильнейшая, импульсная) — опережение: старший ещё в
волне 1, тренд старшего не подтверждён, а мы уже в позиции через волну 3 младшего.

Волновой счёт через структуру (Эллиотт→SMC):
  волна 1 = CHoCH младшего (первый импульс после старта старшего)
  волна 2 = откат (не пробивает начало волны 1)
  волна 3 = BOS младшего (пробой конца волны 1) = ВХОД, стоп за волну 2, цель по старшему.

Walk-forward-safe: старший скан на закрытых 4h-барах; младший вход из 1h-баров ≤ момента.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from core.smc.smc_engine import detect_structure_breaks


@dataclass
class MtfSetup:
    direction: str       # 'LONG' | 'SHORT'
    htf_wave1_ts: object # старт волны 1 старшего (разворот 4h)
    entry_ts: object     # бар волны-3-BOS младшего
    entry: float         # пробитый уровень конца волны 1 (вход на ретесте/по рынку)
    sl: float            # за волну 2 (откат) младшего
    targets: list        # цели по старшему импульсу (продолжение)
    htf_lo: float
    htf_hi: float
    w1_len: int          # баров младшего в волне 1 (для наблюдения)
    conf: bool = False   # КОНФЛЮЭНЦИЯ: вход совпал с уровнем единой сетки ПРЕДЫДУЩЕГО 4h-импульса
                         # (±0.3%) — «вход в пересечении сеток» (на одномасштабном давало +0.6..+3.5%)


def detect_v2_mtf(
    df_htf: pd.DataFrame,      # старший (4h): контекст-импульс (волна 1 старшего)
    df_ltf: pd.DataFrame,      # младший (15m): слом у дна/вершины = вход в волну 3
    len_htf: int = 30,         # значимая структура старшего
    len_ltf: int = 5,          # внутренняя структура младшего (15m слом)
    wave1_window_bars_htf: int = 6,   # окно «волна 1 старшего» (N баров 4h после старта)
    sl_buf_pct: float = 0.3,
    min_htf_range_pct: float = 3.0,
    edge_extreme: float = 0.4,        # «у дна/вершины»: основание волны 3 в крайних 40% окна
) -> List[MtfSetup]:
    """Фрактальный MTF-вход: старт импульса старшего → волна 3 младшего внутри."""
    H = df_htf.copy(); H.columns = [c.lower() for c in H.columns]
    L = df_ltf.copy(); L.columns = [c.lower() for c in L.columns]
    if len(H) < len_htf * 2 + 5 or len(L) < 100:
        return []

    br_htf = detect_structure_breaks(H, length=len_htf)
    br_ltf = detect_structure_breaks(L, length=len_ltf)
    if not br_htf or not br_ltf:
        return []

    Hidx = H.index
    Lidx = L.index
    Lhigh, Llow, Lclose = L["high"].values, L["low"].values, L["close"].values
    Hhigh, Hlow = H["high"].values, H["low"].values

    # единая шкала конфлюэнции (уровни предыдущего 4h-импульса, «−1/−2 = вход» Егора)
    conf_fibs = (-2.0, -1.618, -1.0, -0.62, -0.27, 0.0, 0.27, 0.5, 0.62, 0.705, 0.79, 1.0)

    def _conf(entry_px, plo, phi, prev_bull):
        if phi <= plo or entry_px <= 0:
            return False
        start, end = (plo, phi) if prev_bull else (phi, plo)
        for f in conf_fibs:
            lvl = end - f * (end - start)
            if lvl > 0 and abs(entry_px - lvl) / entry_px * 100 <= 0.3:
                return True
        return False

    out: List[MtfSetup] = []
    for hbk, hb in enumerate(br_htf):
        # старт волны 1 старшего = слом структуры 4h (смена характера / начало импульса)
        htf_dir = "LONG" if hb.direction == "bull" else "SHORT"
        h_i = hb.idx
        # предыдущий 4h-импульс (противоположного направления) для конфлюэнции сеток
        prev_lo = prev_hi = 0.0
        prev_bull = hb.direction == "bear"
        for pk in range(hbk - 1, -1, -1):
            if br_htf[pk].direction != hb.direction:
                pa = br_htf[pk].from_idx if br_htf[pk].from_idx >= 0 else br_htf[pk].idx
                prev_lo = float(Hlow[pa:h_i + 1].min())
                prev_hi = float(Hhigh[pa:h_i + 1].max())
                break
        # окно поиска волны 1 старшего = TTL сетапа: [слом .. +N баров 4h]. Это ЛИМИТ времени
        # входа (в реале: волна 3 должна прийти в течение N баров, иначе сетап протух),
        # не look-ahead — вход w3 определит реальное «сейчас», цели считаются от баров ≤ w3.ts.
        h_end = min(h_i + wave1_window_bars_htf, len(H) - 1)
        t0, t1 = Hidx[h_i], Hidx[h_end]
        # младшие сломы ВНУТРИ окна волны 1 старшего
        inner = [b for b in br_ltf if t0 <= b.ts <= t1]
        if len(inner) < 2:
            continue
        want = "bull" if htf_dir == "LONG" else "bear"
        # волна 1 младшего = первый CHoCH ПО направлению старшего внутри окна
        w1 = next((b for b in inner if b.kind == "CHoCH" and b.direction == want), None)
        if w1 is None:
            continue
        # волна 3 младшего = первый BOS ПО направлению ПОСЛЕ w1 (пробой конца волны 1)
        w3 = next((b for b in inner if b.idx > w1.idx and b.kind == "BOS"
                   and b.direction == want), None)
        if w3 is None:
            continue
        e_i = w3.idx
        entry = float(w3.price)                        # пробитый уровень = вход
        # 🔴 LOOK-AHEAD FIX: диапазон старшего импульса для целей — ТОЛЬКО 4h-бары,
        # закрытые ДО момента входа (w3.ts). Иначе seg_hi/seg_lo подглядывают в будущее
        # старшего (окно [h_i..h_end] брало +6 баров ВПЕРЁД). Честно: h_now = последний
        # 4h-бар с ts <= w3.ts. Импульс = [h_i .. h_now].
        w3_ts = w3.ts
        h_now = h_i
        for hk in range(h_i, len(H)):
            if Hidx[hk] <= w3_ts:
                h_now = hk
            else:
                break
        seg_hi = float(Hhigh[h_i:h_now + 1].max())
        seg_lo = float(Hlow[h_i:h_now + 1].min())
        if seg_lo <= 0 or (seg_hi - seg_lo) / seg_lo * 100 < min_htf_range_pct:
            continue
        rng = seg_hi - seg_lo
        # волна 2 = откат между w1 и w3 → стоп за её экстремум (у дна/вершины)
        seg = slice(w1.idx, e_i + 1)
        # «15m слом У ДНА/ВЕРШИНЫ» (Егор): основание волны 3 должно быть в крайней зоне
        # окна старшего импульса, не в середине. Окно младшего [t0..e_i].
        win_lo = float(Llow[w1.idx - 20 if w1.idx >= 20 else 0:e_i + 1].min())
        win_hi = float(Lhigh[w1.idx - 20 if w1.idx >= 20 else 0:e_i + 1].max())
        wrng = win_hi - win_lo
        if wrng <= 0:
            continue
        if htf_dir == "LONG":
            base = float(Llow[seg].min())              # дно волны 2 (откат)
            if (base - win_lo) / wrng > edge_extreme:  # не у дна → пропуск
                continue
            sl = base * (1 - sl_buf_pct / 100)
            tg = [seg_hi, seg_hi + 0.62 * rng, seg_hi + 1.0 * rng]
            if not (sl < entry < tg[0]):
                continue
        else:
            base = float(Lhigh[seg].max())             # вершина волны 2
            if (win_hi - base) / wrng > edge_extreme:  # не у вершины → пропуск
                continue
            sl = base * (1 + sl_buf_pct / 100)
            tg = [seg_lo, seg_lo - 0.62 * rng, seg_lo - 1.0 * rng]
            if not (tg[0] < entry < sl):
                continue
        cf = _conf(entry, prev_lo, prev_hi, prev_bull)
        out.append(MtfSetup(htf_dir, t0, w3.ts, entry, sl, tg, seg_lo, seg_hi, e_i - w1.idx, cf))
    return out
