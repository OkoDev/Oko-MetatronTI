# -*- coding: utf-8 -*-
"""Правила свечи — одно место на проект (паспорт данных, правило 1 · docs/DATA_CONTRACT.md · ARCH-147).

Формат бота: строки по возрастанию времени, колонки time/open/high/low/close/volume, `time` — время ОТКРЫТИЯ свечи,
UTC, миллисекунды. Индекс — номер строки, временем НЕ является; последняя строка может быть незакрытой свечой.

Зачем модуль. До 13.10.2026 «время последней свечи» каждый брал сам: кэш структуры — из `df.index[-1]` (номер
строки → снимок неделю отдавался старым), проверка свежести — оттуда же (исключение глоталось → свеча любой
давности считалась свежей). Плюс пять самодельных приведений формата с разной таймзоной. Здесь:
  • `last_bar_time` — ЕДИНСТВЕННЫЙ способ узнать время последней свечи;
  • `violations`    — проверка формата, возвращает коды нарушений;
  • `WATCH`         — наблюдатель на поставщике (`DataCollector.get_ohlcv`): считает нарушения, работе не мешает.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COLUMNS = ("time", "open", "high", "low", "close", "volume")

# Таймфрейм → длительность в секундах (одно определение на проект; data_quality берёт отсюда)
TF_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400, "1w": 604800,
}

_MS_FLOOR = 1e11          # число меньше — это секунды, а не миллисекунды (1e11 мс = март 1973)
_CLOCK_SLACK_MS = 60_000  # запас на расхождение часов при проверке «свеча из будущего»


def last_bar_time(df: pd.DataFrame) -> Optional[datetime]:
    """Время открытия последней свечи (UTC) или None, если взять неоткуда.

    Колонка `time` (мс; секунды тоже понимает) — основной путь, DatetimeIndex — запасной. Номер строки временем не
    считается: для RangeIndex без `time` ответ — None, и вызывающий обязан обойтись без времени ЯВНО."""
    try:
        if df is None or len(df) == 0:
            return None
        if "time" in df.columns:
            v = df["time"].iloc[-1]
            if pd.api.types.is_number(v):
                v = float(v)
                ts = pd.Timestamp(v, unit="ms" if v > _MS_FLOOR else "s", tz="UTC")
            else:
                ts = pd.Timestamp(v)
        elif isinstance(df.index, pd.DatetimeIndex):
            ts = df.index[-1]
        else:
            return None
        if ts is pd.NaT:
            return None
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.to_pydatetime()
    except Exception as e:                                       # noqa: BLE001
        logger.warning("[candles] время последней свечи не читается: %s: %s", type(e).__name__, e)
        return None


def violations(df: Optional[pd.DataFrame], timeframe: Optional[str] = None,
               now: Optional[datetime] = None) -> list[str]:
    """Коды нарушений формата бота. Пустой список — таблица чистая.

    `gap` — пропуск свечей: это свойство данных (у неликвида поток молчит без сделок), а не ошибка формы; считается
    отдельно, чтобы его было видно. Остальные коды — ошибки производителя."""
    if df is None or len(df) == 0:
        return ["empty"]
    miss = [c for c in COLUMNS if c not in df.columns]
    if miss:
        return ["no_column:" + ",".join(miss)]          # дальше проверять нечем
    t = df["time"].to_numpy()
    if not np.issubdtype(t.dtype, np.number):
        return ["time_not_number"]
    t = t.astype("float64", copy=False)
    out: list[str] = []
    if np.isnan(t).any():
        return ["time_nan"]
    last = float(t[-1])
    is_ms = last > _MS_FLOOR
    if not is_ms:
        out.append("time_not_ms")
    d = np.diff(t)
    if d.size:
        if (d < 0).any():
            out.append("time_not_sorted")
        if (d == 0).any():
            out.append("time_duplicate")
        step = TF_SECONDS.get(timeframe or "")
        if step and is_ms:
            pos = d[d > 0]
            if pos.size:
                ms = step * 1000.0
                if (pos % ms != 0).any():
                    out.append("step_off_grid")         # шаг не кратен таймфрейму — перепутан ТФ или склейка
                elif (pos > ms).any():
                    out.append("gap")
    if is_ms:
        now_ms = (now or datetime.now(timezone.utc)).timestamp() * 1000.0
        if last > now_ms + _CLOCK_SLACK_MS:
            out.append("time_in_future")
    for c in ("open", "high", "low", "close"):
        tail = df[c].to_numpy()[-3:]
        try:
            if np.isnan(tail.astype("float64")).any():
                out.append("ohlc_nan")
                break
        except (TypeError, ValueError):
            out.append("ohlc_not_number")
            break
    return out


class CandleWatch:
    """Наблюдатель на поставщике свечей: считает нарушения и хранит по одному примеру на вид. Работе не мешает."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        self.checked = 0
        self.bad = 0
        self.kinds: Counter = Counter()
        self.examples: dict[str, str] = {}

    def observe(self, df: Optional[pd.DataFrame], timeframe: str, symbol: str = "") -> list[str]:
        try:
            v = violations(df, timeframe)
        except Exception as e:                                   # noqa: BLE001 — наблюдатель не роняет поставщика
            v = [f"check_error:{type(e).__name__}"]
        with self._lock:
            self.checked += 1
            if v:
                self.bad += 1
                for k in v:
                    self.kinds[k] += 1
                    self.examples.setdefault(k, f"{symbol} {timeframe}")
        return v

    def report(self, reset: bool = True) -> dict:
        with self._lock:
            rep = {"checked": self.checked, "bad": self.bad, "kinds": dict(self.kinds), "examples": dict(self.examples)}
            if reset:
                self._reset()
        return rep


WATCH = CandleWatch()


def report_line(rep: dict) -> str:
    """Строка отчёта для лога: сколько проверено, сколько с замечаниями, виды и по одному примеру."""
    if not rep.get("checked"):
        return "свечи: проверок не было"
    kinds = rep.get("kinds") or {}
    form = {k: n for k, n in kinds.items() if k != "gap"}
    parts = [f"свечи: проверено {rep['checked']}", f"с нарушением формы {sum(form.values())}",
             f"с пропусками {kinds.get('gap', 0)}"]
    if form:
        ex = rep.get("examples") or {}
        parts.append("виды: " + ", ".join(f"{k}×{n} ({ex.get(k, '?')})" for k, n in sorted(form.items(), key=lambda x: -x[1])))
    return " · ".join(parts)
