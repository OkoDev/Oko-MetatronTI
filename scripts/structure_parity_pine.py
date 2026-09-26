# -*- coding: utf-8 -*-
"""Сверка Pine-блока структуры OKO (docs/reference/OkoSM_structure_block.pine) с core/structure.

Бары и метки берутся с графика TradingView через MCP и сохраняются в JSON:
  bars   — data_get_ohlcv (все загруженные бары, summary=false);
  labels — data_get_pine_labels (study_filter="OKO", max_labels=500).
Python считает структуру на тех же барах с того же первого бара и сравнивает метки сломов
(«CHoCH»/«BOS» — старший масштаб, «choch»/«bos» — младший) и равных уровней («EQH»/«EQL») по цене.
Pine хранит только последние 500 меток, поэтому проверяется, что каждая метка графика есть
среди ожидаемых Python и что совпало столько же, сколько меток на графике.

Бары можно не выгружать с графика (MCP отдаёт не больше 500): включите в индикаторе
«Сведения для сверки с Python» — он покажет t0 (время первого бара) и n, и скрипт скачает
те же n свечей с BingX, начиная с t0.

Запуск:  python scripts/structure_parity_pine.py --bars bars.json --labels labels.json
         python scripts/structure_parity_pine.py --bingx SOL-USDT --interval 1h --t0 1700000000000 --n 5000 \
                --labels labels.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.structure import (MINOR, active_leg, dc_swings, day_pivots, equal_levels,  # noqa: E402
                            ote_on_leg, pivot_target, trace_structure)

KINDS = {"CHoCH", "BOS", "choch", "bos", "EQH", "EQL", "dc+", "dc-"}


def _load_bars(path: str) -> pd.DataFrame:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("bars", data) if isinstance(data, dict) else data
    df = pd.DataFrame(rows)
    df.columns = [str(c).lower() for c in df.columns]
    df = df.sort_values("time").reset_index(drop=True)
    return df[["open", "high", "low", "close"]].astype(float)


_STEP_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
            "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}


def _fetch_bingx(symbol: str, interval: str, t0: int, n: int) -> pd.DataFrame:
    """n свечей BingX perpetual с бара t0 (мс). Окна ≤1000 баров: на длинное окно API отдаёт его хвост."""
    import requests
    step = _STEP_MS[interval]
    rows, start = {}, t0
    while len(rows) < n:
        end = start + 1000 * step - 1
        r = requests.get("https://open-api.bingx.com/openApi/swap/v3/quote/klines", timeout=20,
                         params={"symbol": symbol, "interval": interval, "startTime": start,
                                 "endTime": end, "limit": 1000})
        data = r.json().get("data") or []
        for k in data:
            rows[int(k["time"])] = k
        if not data:
            break
        start = end + 1
    got = sorted(rows.values(), key=lambda k: int(k["time"]))
    got = [k for k in got if int(k["time"]) >= t0][:n]
    return pd.DataFrame(got)[["open", "high", "low", "close"]].astype(float)


def _load_labels(path: str) -> list[tuple[str, float]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "text" in node and "price" in node:
                found.append((str(node["text"]).strip(), float(node["price"])))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return [(t, p) for t, p in found if t in KINDS]


def expected(df: pd.DataFrame, major: int, minor: int, eq_len: int, eq_tol: float,
             dc: tuple[float, int] | None = None) -> list[tuple[int, str, float]]:
    """(бар создания метки, текст, цена) в порядке создания, как рисует Pine-блок."""
    events = []
    for b in trace_structure(df, major=major, minor=minor).breaks:
        text = b.kind if b.scale != MINOR else b.kind.lower()
        events.append((b.bar, text, b.level))
    for p in equal_levels(df, window=eq_len, tolerance=eq_tol):
        events.append((p.second_bar + eq_len, "EQH" if p.highs else "EQL", p.second_price))
    if dc:
        for ext_i, price, conf_i, up in dc_swings(df, atr_mult=dc[0], atr_len=dc[1]):
            events.append((conf_i, "dc+" if up else "dc-", price))
    return sorted(events, key=lambda e: e[0])


def check_table(df: pd.DataFrame, rows: list[str], major: int, minor: int, mode: str, digits: int) -> list[str]:
    """Сверка строк таблицы «Сведений»: нога, OTE и цель на последнем баре против Python.
    Пивоты берутся из той же таблицы (piv=H/L/C прошлого дня), чтобы сверять правило цели, а не источник свечей."""
    import re
    text = " ".join(rows)
    num = lambda k: float(re.search(rf"{k}=(-?[\d.]+|NaN)", text).group(1))
    leg = active_leg(trace_structure(df, major=major, minor=minor))
    want_dir = 0 if not leg else (1 if leg["trend"] == "long" else -1)
    problems = []
    if int(num("leg")) != want_dir:
        problems.append(f"направление ноги: Pine {int(num('leg'))}, Python {want_dir}")
    if leg:
        r = lambda x: round(x, digits)
        if (r(num("o")), r(num("e"))) != (r(leg["origin"]), r(leg["extreme"])):
            problems.append(f"нога: Pine {num('o')}/{num('e')}, Python {leg['origin']}/{leg['extreme']}")
        ote = ote_on_leg(leg)
        near_far = (ote["levels"][0][1], ote["levels"][-1][1])
        m = re.search(r"ote=(-?[\d.]+)/(-?[\d.]+)", text)
        if (r(float(m.group(1))), r(float(m.group(2)))) != (r(near_far[0]), r(near_far[1])):
            problems.append(f"OTE: Pine {m.group(1)}/{m.group(2)}, Python {near_far}")
        h, l, c = (float(x) for x in re.search(r"piv=([\d.]+)/([\d.]+)/([\d.]+)", text).groups())
        tgt = pivot_target(day_pivots(h, l, c), num("close"), want_dir == 1, mode=mode)
        m = re.search(r"tgt=(\w*)@(-?[\d.]+|NaN)", text)
        pine_tgt = (m.group(1), round(float(m.group(2)), digits)) if m.group(1) else None
        py_tgt = (tgt[0], round(tgt[1], digits)) if tgt else None
        if pine_tgt != py_tgt:
            problems.append(f"цель: Pine {pine_tgt}, Python {py_tgt}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", help="JSON баров с графика (data_get_ohlcv)")
    ap.add_argument("--bingx", help="символ BingX perpetual, например SOL-USDT (вместо --bars)")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--t0", type=int, help="время первого бара графика, мс (из «Сведений для сверки»)")
    ap.add_argument("--n", type=int, help="число баров графика (из «Сведений для сверки»)")
    ap.add_argument("--labels", required=True)
    ap.add_argument("--major", type=int, default=50)
    ap.add_argument("--minor", type=int, default=5)
    ap.add_argument("--eq-len", type=int, default=3)
    ap.add_argument("--eq-tol", type=float, default=0.1)
    ap.add_argument("--digits", type=int, default=8, help="округление цены при сравнении")
    ap.add_argument("--dc", default="", help="сверять ноги DC: 'множитель,ATR', например 3,43")
    ap.add_argument("--table", nargs="*", default=[], help="строки таблицы «Сведений» (нога, OTE, цель)")
    ap.add_argument("--mode", default="egor", choices=["egor", "second"], help="правило цели в индикаторе")
    args = ap.parse_args()

    if args.bingx:
        df = _fetch_bingx(args.bingx, args.interval, args.t0, args.n)
    else:
        df = _load_bars(args.bars)
    chart = [(t, round(p, args.digits)) for t, p in _load_labels(args.labels)]
    dc = tuple(float(x) for x in args.dc.split(",")) if args.dc else None
    dc = (dc[0], int(dc[1])) if dc else None
    exp = [(t, round(p, args.digits)) for _, t, p in expected(df, args.major, args.minor, args.eq_len, args.eq_tol, dc)]
    tail = Counter(exp[-max(len(chart) * 2, 50):])       # запас: у Pine ещё метки ноги и периодов
    have = Counter(chart)
    missing = have - tail
    matched = sum((have & tail).values())

    print(f"баров {len(df)} · меток на графике {len(chart)} · ожидаемых Python {len(exp)}")
    print(f"совпало {matched}/{len(chart)} ({matched / max(len(chart), 1) * 100:.1f}%)")
    for (t, p), k in list(missing.items())[:15]:
        print(f"  ✗ на графике, нет у Python: {t} @ {p} ×{k}")
    ok = not missing and matched == len(chart) and len(chart) > 0
    if args.table:
        problems = check_table(df, args.table, args.major, args.minor, args.mode, args.digits)
        print("таблица (нога · OTE · цель):", "совпала" if not problems else "; ".join(problems))
        ok = ok and not problems
    print("ПАРИТЕТ PINE ↔ PYTHON:", "ПРОЙДЕН" if ok else "НЕ ПРОЙДЕН")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
