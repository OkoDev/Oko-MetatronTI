# -*- coding: utf-8 -*-
"""МЕТОД ЕГОРА — единый детектор (05.07). Reuse-ядро для бэктеста и live-SHADOW.

Геометрия (валидирована 05.07, `scripts/test_ote_retest_honest.py`, WR 34%→55% на масштабе):
  1. ВХОД НА ОТКАТЕ — `ote_retest_setups(provisional=True)`: слом CHoCH → OTE → РЕТЕСТ (первый
     бар отката в OTE) = вход. provisional дорисовывает текущую ногу live (chart-builder Егора).
  2. СТОРОНА = РАЗВОРОТ у экстремума большого HTF-импульса (`structure_trend` 4h):
     SHORT-ретест у ВЕРШИНЫ большого ВОСХОДЯЩЕГО (trend=long, price у extreme=HH);
     LONG-ретест  у ДНА большого НИСХОДЯЩЕГО (trend=short, price у extreme=LL).
     Это mean-reversion ПРОТИВ HTF-тренда (в момент разворота 4h ещё смотрит в старую сторону).
  3. ЦЕЛИ = OTE самого большого импульса (0.5/0.62/0.705 отката), СТОП = локальный тугой
     (из движка ote_retest) → асимметрия «стоп короткий, цель огромная».

⚠️ Последний кусок метода — ТОЛПА/funding/OI у экстремума (топливо разворота) — в OHLCV НЕТ.
Историчка выжата до WR55/безубыток; эдж достраивается на живом крае (SHADOW + контекст радара).

htf-контекст (trend/break/extreme) передаётся снаружи — в live считается один раз
`structure_trend(df_htf)`, в бэктесте предпосчитывается по HTF-барам (скорость).
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from core.smc.smc_engine import ote_retest_setups

OTE_TARGET_FIBS = (0.5, 0.62, 0.705)


def method_targets(htf_trend: str, htf_break: float, htf_extreme: float) -> Optional[list]:
    """OTE-цели большого импульса: откат от экстремума на 0.5/0.62/0.705 размаха.
    long-импульс (вверх): big>0, цели = ext−f·big (вниз от вершины) для SHORT-разворота.
    short-импульс (вниз): big<0, цели = ext−f·big (вверх от дна) для LONG-разворота.
    """
    if htf_break is None or htf_extreme is None:
        return None
    big = htf_extreme - htf_break
    if abs(big) < 1e-12:
        return None
    return [htf_extreme - f * big for f in OTE_TARGET_FIBS]


def detect_method_egor(
    df_ltf: pd.DataFrame,
    *,
    htf_trend: Optional[str],
    htf_break: Optional[float],
    htf_extreme: Optional[float],
    entry_price: Optional[float] = None,
    edge: float = 0.5,
    depth: int = 11,
    fresh_bars: int = 1,
    only_choch: bool = True,
) -> List[dict]:
    """Свежий сетап метода Егора на конце df_ltf (или пусто).

    df_ltf — младший ТФ (1h), последний бар = «сейчас». htf_* — сторона из structure_trend(4h).
    entry_price — цена входа (по умолч. close последнего бара df_ltf). Возвращает список dict:
      {direction, entry_ts, entry, sl, targets, confluence, pos, htf_trend}.
    """
    if htf_trend is None or htf_break is None or htf_extreme is None:
        return []
    setups = ote_retest_setups(df_ltf, provisional=True, only_choch=only_choch, depth=depth)
    if not setups:
        return []
    # свежий ретест — вход в последних fresh_bars баров (только что виден live)
    if len(df_ltf) <= fresh_bars:
        return []
    cutoff = df_ltf.index[-fresh_bars]
    fresh = [s for s in setups if s["entry_ts"] >= cutoff]
    if not fresh:
        return []
    s = fresh[-1]
    lng = s["direction"] == "long"
    entry = float(entry_price) if entry_price is not None else float(df_ltf["close"].iloc[-1])
    big = htf_extreme - htf_break
    if abs(big) < 1e-12:
        return []
    pos = (entry - htf_break) / big          # 0 = у break, 1 = у экстремума
    # РАЗВОРОТ: SHORT у вершины большого long-импульса / LONG у дна большого short-импульса
    if not lng and htf_trend == "long" and pos >= edge:
        pass
    elif lng and htf_trend == "short" and pos >= edge:
        pass
    else:
        return []
    targets = method_targets(htf_trend, htf_break, htf_extreme)
    if targets is None:
        return []
    sl = s["sl"]                              # локальный тугой стоп из движка (асимметрия)
    # sanity: цена по правильную сторону стопа и целей
    if (entry <= sl) if lng else (entry >= sl):
        return []
    if lng and not all(t > entry for t in targets):
        return []
    if not lng and not all(t < entry for t in targets):
        return []
    return [{
        "direction": "LONG" if lng else "SHORT",
        "entry_ts": s["entry_ts"], "entry": entry, "sl": sl, "targets": targets,
        "confluence": s.get("confluence", 0), "pos": pos, "htf_trend": htf_trend,
        "htf_break": htf_break, "htf_extreme": htf_extreme,
    }]
