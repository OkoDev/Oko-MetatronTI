# -*- coding: utf-8 -*-
"""Общие заготовки данных В ФОРМАТЕ БОТА (паспорт данных, правило 8 · docs/DATA_CONTRACT.md).

Тест на всё, что касается свечей, времени или кэша, берёт таблицу отсюда, а не строит удобную сам. 13.10.2026
внешний аудит нашёл две ошибки, которые свои тесты пропустили: тесты были на таблице с временем в индексе и с
растущим окном, а в бою время лежит в колонке `time`, окно постоянной длины, индекс — номер строки.
"""
from __future__ import annotations

import time

import pandas as pd

TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
         "1d": 86_400_000}


def bot_bars(n: int = 200, tf: str = "15m", last_open_ms: int | None = None, last_open_age_sec: float | None = None,
             price: float = 100.0, time_unit: str = "ms") -> pd.DataFrame:
    """Свечи как их отдаёт `DataCollector.get_ohlcv`: RangeIndex с нуля, колонка `time` — время ОТКРЫТИЯ, UTC.

    Время последней свечи задаётся одним из двух способов: точной отметкой `last_open_ms` или возрастом
    `last_open_age_sec` (сколько секунд назад она открылась). По умолчанию — 5 минут назад, по сетке таймфрейма.
    Цены меняются от строки к строке, чтобы разные окна давали разные данные."""
    step = TF_MS[tf]
    if last_open_ms is None:
        age = 300.0 if last_open_age_sec is None else last_open_age_sec
        last_open_ms = int((time.time() - age) * 1000) // step * step if last_open_age_sec is None \
            else int((time.time() - age) * 1000)
    t = [last_open_ms - (n - 1 - i) * step for i in range(n)]
    base = [price + ((x // step) % 50) * 0.1 for x in t]          # цена привязана ко времени, а не к номеру строки
    df = pd.DataFrame({"time": t, "open": base, "high": [b + 0.5 for b in base], "low": [b - 0.5 for b in base],
                       "close": [b + 0.2 for b in base], "volume": [1000.0] * n})
    if time_unit == "s":
        df["time"] = df["time"] // 1000
    return df


def shifted(df: pd.DataFrame, bars: int, tf: str = "15m") -> pd.DataFrame:
    """То же окно через `bars` свечей: длина и номера строк те же, время и цены — другие. Так окно выглядит в бою."""
    return bot_bars(n=len(df), tf=tf, last_open_ms=int(df["time"].iloc[-1]) + bars * TF_MS[tf])
