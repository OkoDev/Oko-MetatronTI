# -*- coding: utf-8 -*-
"""Общие заготовки данных В ФОРМАТЕ БОТА (паспорт данных, правило 8 · docs/DATA_CONTRACT.md).

Тест на всё, что касается свечей, времени или кэша, берёт таблицу отсюда, а не строит удобную сам. 13.10.2026
внешний аудит нашёл две ошибки, которые свои тесты пропустили: тесты были на таблице с временем в индексе и с
растущим окном, а в бою время лежит в колонке `time`, окно постоянной длины, индекс — номер строки.
"""
from __future__ import annotations

import time

import numpy as np
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


def trades(*, coins: int = 15, days: int = 40, per_day: int = 4, cand_share: float = 0.4,
           edge: float = 0.0, base: float = 0.0, noise: float = 1.0, start: str = "2024-01-01",
           years: int = 2, seed: int = 7, cand_coins: int | None = None,
           spike_days: int = 0, spike: float = 0.0, edge_by_year: tuple[float, ...] | None = None) -> pd.DataFrame:
    """Таблица сделок в контракте `scripts/research_verify.normalize`: sym · side · ts · pnl (% после коста).

    Для golden-case карточки вердикта: `edge` — надбавка кандидату в процентных пунктах, `cand_coins` —
    на скольких монетах она есть (остальным кандидатам ноль, проверка охвата), `spike_days`/`spike` —
    редкие дни с огромной прибылью (проверка хрупкости), `edge_by_year` — своя надбавка на каждый год
    (проверка устойчивости по годам: например (2.5, -1.0) — был эдж и пропал). Колонка `cand` — маска кандидата.
    """
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp(start)
    syms = [f"C{i:02d}/USDT:USDT" for i in range(coins)]
    edge_syms = set(syms if cand_coins is None else syms[:cand_coins])
    rows = []
    for y in range(years):
        for d in range(days):
            day = t0 + pd.DateOffset(years=y) + pd.Timedelta(days=d)
            hot = spike_days and d < spike_days
            for k in range(per_day):
                sym = syms[int(rng.integers(coins))]
                is_cand = rng.random() < cand_share
                pnl = base + rng.normal(0, noise)
                if is_cand:
                    e = edge if edge_by_year is None else edge_by_year[y % len(edge_by_year)]
                    pnl += e if sym in edge_syms else 0.0
                    if hot:
                        pnl += spike
                rows.append((sym, "LONG" if rng.random() < 0.5 else "SHORT",
                             day + pd.Timedelta(hours=int(rng.integers(24))), float(pnl), bool(is_cand)))
    df = pd.DataFrame(rows, columns=["sym", "side", "ts", "pnl", "cand"])
    return df.sort_values("ts").reset_index(drop=True)


def shifted(df: pd.DataFrame, bars: int, tf: str = "15m") -> pd.DataFrame:
    """То же окно через `bars` свечей: длина и номера строк те же, время и цены — другие. Так окно выглядит в бою."""
    return bot_bars(n=len(df), tf=tf, last_open_ms=int(df["time"].iloc[-1]) + bars * TF_MS[tf])
