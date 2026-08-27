# -*- coding: utf-8 -*-
"""DIRECTIONAL CHANGE: разметка ног конечным автоматом (20.08.2026).

🔑 КОРЕНЬ ПРОБЛЕМЫ, который это чинит. Наш `impulse_fib.find_impulses` ищет ногу
ПЕРЕБОРОМ окна (`for back in range(5, 60)`) и берёт лучший по критериям ход. Обзор
открытых реализаций (ZigZag, Directional Change, LuxAlgo, Bry–Boschan, rolling-window)
показал: НИ ОДНА из них так не делает. Все — конечный автомат: держим бегущий экстремум
и его индекс, а порог решает только КОГДА подтвердить разворот. При такой форме origin
по построению равен индексу экстремума и физически не может оказаться в теле
предыдущего движения.

Именно перебор дал нам случай KAIA 20.08: origin встал на сутки раньше реального дна,
в «импульс» попал кусок чужого падения, а «откат внутри 34.9%» оказался не откатом,
а примесью. Порог 35% такой захват не ловит — он лишь ограничивает его размер.

Канон (neurotrader888/directional_change.py):
    экстремум обновляется по HIGH/LOW, подтверждение приходит по CLOSE,
    наружу отдаются ОБА индекса: бар экстремума и бар подтверждения.
🔴 У нас в `impulse_fib` якоря смешаны наоборот: ход меряется по close, а откат по H/L.

Два порога на выбор:
  · `sigma` — доля цены (классический DC/ZigZag, на дневках обычно 0.05);
  · `atr_mult` — порог в ATR (2.0–3.0 у ZigZag-ATR реализаций).

Причинность: ни одна величина не смотрит вперёд. Нога считается ПОДТВЕРЖДЁННОЙ только
на баре `conf_i`; до этого она `provisional` и торговать по ней нельзя — ровно та
ошибка, которую мы ловили как «флаг смещён на N баров».
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Leg:
    """Нога: от экстремума до экстремума. `conf_i` — бар, на котором она подтверждена."""
    ext_i: int          # бар экстремума (= origin следующей ноги)
    ext_price: float
    conf_i: int         # бар подтверждения разворота (раньше него ноги «не существует»)
    up: bool            # True = нога вверх (закончилась максимумом)

    @property
    def lag(self) -> int:
        return self.conf_i - self.ext_i


def _atr(df: pd.DataFrame, length: int = 14) -> np.ndarray:
    tr = pd.concat([df.high - df.low, (df.high - df.close.shift()).abs(),
                    (df.low - df.close.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean().values


def find_legs(df: pd.DataFrame, *, sigma: float | None = None,
              atr_mult: float | None = 2.0, atr_len: int = 14) -> list[Leg]:
    """Ноги по Directional Change. Возвращает список подтверждённых разворотов.

    sigma задаёт порог как долю цены; atr_mult — как кратность ATR. Указывать надо
    ровно один из них (sigma имеет приоритет).
    """
    h, l, c = df.high.values, df.low.values, df.close.values
    n = len(df)
    if n < atr_len + 2:
        return []
    atr = _atr(df, atr_len) if sigma is None else None

    legs: list[Leg] = []
    up_zig = True                    # ищем максимум
    tmp_max, tmp_max_i = h[0], 0
    tmp_min, tmp_min_i = l[0], 0

    for i in range(1, n):
        thr = (tmp_max * sigma) if sigma is not None else (atr[i] * atr_mult)
        if up_zig:
            if h[i] > tmp_max:                       # экстремум — по ФИТИЛЮ
                tmp_max, tmp_max_i = h[i], i
            elif c[i] < tmp_max - thr:               # подтверждение — по ЗАКРЫТИЮ
                legs.append(Leg(tmp_max_i, float(tmp_max), i, True))
                up_zig = False
                # 🔴 Дефект канонической реализации, который надо знать: новый бегущий
                # минимум сеется на баре ПОДТВЕРЖДЕНИЯ, поэтому лой между экстремумом и
                # подтверждением теряется. Берём минимум всего участка — иначе origin
                # следующей ноги снова уедет, только теперь вперёд.
                seg = l[tmp_max_i:i + 1]
                tmp_min_i = tmp_max_i + int(np.argmin(seg))
                tmp_min = float(l[tmp_min_i])
        else:
            thr = (tmp_min * sigma) if sigma is not None else (atr[i] * atr_mult)
            if l[i] < tmp_min:
                tmp_min, tmp_min_i = l[i], i
            elif c[i] > tmp_min + thr:
                legs.append(Leg(tmp_min_i, float(tmp_min), i, False))
                up_zig = True
                seg = h[tmp_min_i:i + 1]
                tmp_max_i = tmp_min_i + int(np.argmax(seg))
                tmp_max = float(h[tmp_max_i])
    return legs


def enforce_alternation(legs: list[Leg]) -> list[Leg]:
    """Альтернация Bry–Boschan: из подряд идущих вершин остаётся высшая, из впадин — низшая.

    В открытых трейдерских реализациях этого шага нет, он приходит из академической
    датировки циклов — и это ровно защита от «двух вершин подряд», когда вторая на самом
    деле часть той же ноги.
    """
    out: list[Leg] = []
    for lg in legs:
        if out and out[-1].up == lg.up:
            keep = (lg.ext_price > out[-1].ext_price) if lg.up else (lg.ext_price < out[-1].ext_price)
            if keep:
                out[-1] = lg
            continue
        out.append(lg)
    return out


def origin_floor(df: pd.DataFrame, *, atr_mult: float = 3.0,
                 atr_len: int = 43) -> np.ndarray:
    """Для каждого бара — индекс экстремума последней ПОДТВЕРЖДЁННОЙ ноги.

    Это нижняя граница для перебора в `impulse_fib.find_impulses`: начало импульса не
    имеет права уйти за неё, иначе в ход попадает чужое движение.

    🔴 ПОРОГ ОБЯЗАН БЫТЬ МАСШТАБА ИМПУЛЬСА. При atr_mult=2.0/atr_len=14 ноги выходят
    13-27 баров — граница встаёт вплотную к текущему бару и срезает почти все сетапы
    (это и есть механизм провала полной замены детектора). Дефолты здесь совпадают с
    механикой: 3.0 = MIN_ATR, 43 = период боевого ATR, иначе в одной механике
    работали бы два разных ATR.

    Причинно: на баре i известны только ноги с conf_i <= i.
    """
    legs = enforce_alternation(find_legs(df, atr_mult=atr_mult, atr_len=atr_len))
    out = np.full(len(df), -1, dtype=int)
    if not legs:
        return out
    k = 0
    cur = -1
    for i in range(len(df)):
        while k < len(legs) and legs[k].conf_i <= i:
            cur = legs[k].ext_i
            k += 1
        out[i] = cur
    return out


def active_leg(df: pd.DataFrame, at_bar: int, **kw) -> dict | None:
    """Последняя ПОДТВЕРЖДЁННАЯ нога на баре at_bar — то, что реально известно в моменте.

    Возвращает origin/extreme в том же формате, что остальные механики проекта, плюс
    `purity` (1 − максимальный контр-откат / длина хода) и `lag` подтверждения.
    """
    sub = df.iloc[:at_bar + 1]
    legs = enforce_alternation(find_legs(sub, **kw))
    legs = [x for x in legs if x.conf_i <= at_bar]
    if len(legs) < 2:
        return None
    prev, last = legs[-2], legs[-1]
    o, e = prev.ext_price, last.ext_price
    up = e > o
    a, b = prev.ext_i, last.ext_i
    if b <= a:
        return None
    hh, ll = df.high.values[a:b + 1], df.low.values[a:b + 1]
    move = abs(e - o)
    dd = (float(np.max(np.maximum.accumulate(hh) - ll)) if up
          else float(np.max(hh - np.minimum.accumulate(ll))))
    return {"origin": float(o), "extreme": float(e), "a": a, "b": b,
            "up": up, "trend": "long" if up else "short",
            "conf_i": last.conf_i, "lag": last.lag,
            "purity": 1.0 - (dd / move if move > 0 else 1.0),
            "age": at_bar - last.conf_i}
