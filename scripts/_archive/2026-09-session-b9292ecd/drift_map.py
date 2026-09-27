# -*- coding: utf-8 -*-
"""КАРТА РАМКИ (12.09.2026, вопрос Егора «где вообще лежит маленький кусочек»).

НЕ про сетапы. Мерим САМ РЫНОК: если войти в СЛУЧАЙНЫЙ момент и держать ровно N баров
(без стопа, без цели — чистое движение), какая медиана и среднее? По горизонтам × сторонам ×
годам. Плюс: сколько из этого съедает комиссия (0.10% круг) — порог окупаемости.

Зачем: 11 недель мы меняли ПОВОД для входа внутри рамки (стоп 5%, цель RR 3-6, удержание сутками),
в которой даже случайный вход теряет (медиана −2.38%). Если у рынка нет горизонта с неотрицательной
медианой — никакой детектор не спасёт. Если есть — повод надо искать ТОЛЬКО внутри него.

Горизонты на 1h: 1 · 4 · 12 · 24 · 72 · 168 баров (час … неделя).
Считаем ПО ВСЕМ барам (не сэмплируем): это не бэктест, это свойство ряда.
"""
from __future__ import annotations
import sqlite3, sys, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

ROOT = Path(r"E:\MTF BOT\CURSOR\crypto_volume_bot")
CACHE = ROOT / "ohlcv_cache.db"
TF = "1h"
HOR = [1, 4, 12, 24, 72, 168]
COST = 0.10          # % круг
PAIRS = 100


def main():
    conn = sqlite3.connect(str(CACHE))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM ohlcv_cache WHERE timeframe=? GROUP BY symbol HAVING COUNT(*)>5000 "
        "ORDER BY COUNT(*) DESC", (TF,))][:PAIRS]
    print(f"монет: {len(syms)} · ТФ {TF} · горизонты(бары): {HOR} · кост {COST}% круг", flush=True)
    parts = []
    for i, s in enumerate(syms, 1):
        df = pd.read_sql_query(
            "SELECT time,close FROM ohlcv_cache WHERE symbol=? AND timeframe=? ORDER BY time",
            conn, params=(s, TF))
        if len(df) < 2000:
            continue
        df["dt"] = pd.to_datetime(df.time, unit="ms", utc=True)
        c = df.close.values
        out = {"year": df.dt.dt.year.values}
        for h in HOR:
            fwd = np.full(len(c), np.nan)
            fwd[:-h] = (c[h:] - c[:-h]) / c[:-h] * 100
            out[f"h{h}"] = fwd
        parts.append(pd.DataFrame(out))
        if i % 25 == 0:
            print(f"  {i}/{len(syms)}", flush=True)
    d = pd.concat(parts, ignore_index=True)
    print(f"\nнаблюдений: {len(d):,}\n")

    print("=== ЧИСТОЕ ДВИЖЕНИЕ ЗА N БАРОВ (LONG = как есть, SHORT = знак минус), всё окно")
    rows = []
    for h in HOR:
        v = d[f"h{h}"].dropna()
        rows.append({
            "баров": h, "часов": h,
            "медиана LONG": v.median(), "среднее LONG": v.mean(),
            "медиана SHORT": (-v).median(), "среднее SHORT": (-v).mean(),
            "LONG>0 %": (v > 0).mean() * 100,
            "медиана |ход|": v.abs().median(),
            "кост/|ход| %": COST / max(v.abs().median(), 1e-9) * 100,
            "LONG нетто": v.median() - COST, "SHORT нетто": (-v).median() - COST,
        })
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:9.3f}"))

    print("\n=== МЕДИАНА ДВИЖЕНИЯ ПО ГОДАМ (LONG), % за N баров")
    t = d.groupby("year")[[f"h{h}" for h in HOR]].median()
    print(t.to_string(float_format=lambda x: f"{x:8.3f}"))

    print("\n=== СРЕДНЕЕ ПО ГОДАМ (LONG), % за N баров  — разрыв со медианой = перекос хвостом")
    t2 = d.groupby("year")[[f"h{h}" for h in HOR]].mean()
    print(t2.to_string(float_format=lambda x: f"{x:8.3f}"))

    print("\n=== ДОЛЯ ПОЛОЖИТЕЛЬНЫХ ИСХОДОВ ПО ГОДАМ (LONG), %")
    t3 = d.groupby("year")[[f"h{h}" for h in HOR]].apply(lambda g: (g > 0).mean() * 100)
    print(t3.to_string(float_format=lambda x: f"{x:8.2f}"))


if __name__ == "__main__":
    main()
