# -*- coding: utf-8 -*-
"""ARCH-137.5: даёт ли МИКРОСТРУКТУРА (len=5) то, чего не давал старший слой (len=50)?

Повод: замер 02.09 показал, что структура была невидима майнингу — BOS/CHoCH
присутствовали в 1.3% живых снимков, и среди 75 флагов в 200 паттернах arch104
структурных не оказалось вовсе. После перевода `swing_bridge` на двухслойный
эталон событий стало в 9.8× больше. Вопрос: это просто БОЛЬШЕ событий или
среди них есть торгуемые.

Дизайн — сравнение при ОДИНАКОВОЙ геометрии (иначе слои несравнимы):
  · событие слома → вход на СЛЕДУЮЩЕМ баре (причинность: бар подтверждения закрыт);
  · стоп 2.0 ATR, цель 3.0 ATR, удержание 48 баров — одно и то же для обоих слоёв;
  · сторона = направление слома;
  · КОНТРОЛЬ (закон проекта): случайный вход той же геометрии на тех же барах.

Запуск:
    python scripts/struct_layers_run.py            # 25 монет, 15m
    python scripts/struct_layers_run.py 40 1h      # 40 монет, 1h
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import collect, report, blind_select, feature_cols  # noqa: E402

HOLD = 48          # баров удержания
SL_ATR = 2.0
TP_ATR = 3.0
WARMUP = 400       # эталону нужна история на свинги len=50


def _atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def _simulate(dd: pd.DataFrame, atr: np.ndarray, bar: int, up: bool) -> dict | None:
    """Одна сделка фиксированной геометрии. Вход на баре `bar` (уже следующий
    после события) по открытию — цена, доступная в реальности."""
    n = len(dd)
    if bar + HOLD + 1 >= n or bar < WARMUP or not np.isfinite(atr[bar]) or atr[bar] <= 0:
        return None
    o, h, l = dd.open.values, dd.high.values, dd.low.values
    e = float(o[bar])
    d = 1.0 if up else -1.0
    sl = e - d * SL_ATR * atr[bar]
    tp = e + d * TP_ATR * atr[bar]
    for j in range(bar, min(bar + HOLD, n)):
        # консервативно: стоп проверяем раньше цели (внутри бара порядок неизвестен)
        if (l[j] <= sl) if up else (h[j] >= sl):
            return {"entry_bar": bar, "side": "long" if up else "short",
                    "pnl_pct": (sl - e) / e * 100 * d}
        if (h[j] >= tp) if up else (l[j] <= tp):
            return {"entry_bar": bar, "side": "long" if up else "short",
                    "pnl_pct": (tp - e) / e * 100 * d}
    x = float(dd.close.values[min(bar + HOLD, n - 1)])
    return {"entry_bar": bar, "side": "long" if up else "short",
            "pnl_pct": (x - e) / e * 100 * d}


def _events(df: pd.DataFrame):
    """Оба слоя эталона за один прогон. Возвращает (dd, atr, список событий)."""
    from core.smc.oko_sm_engine import run_structure
    dd = df.reset_index(drop=True)
    st = run_structure(dd, swing_len=50, internal_len=5, record_legs=False)
    return dd, _atr(dd), st.events


def make_mechanic(layer: str):
    """layer: 'swing' (len=50) · 'micro' (len=5) · 'random' (контроль)."""
    def mechanic(df: pd.DataFrame, _tf: str) -> list[dict]:
        dd, atr, events = _events(df)
        want_internal = (layer == "micro")
        out = []
        if layer == "random":
            # КОНТРОЛЬ: столько же входов той же геометрии, но на случайных барах.
            # Число и стороны берём из микро-слоя, чтобы выборки были сопоставимы.
            ev = [e for e in events if e.internal]
            rng = np.random.default_rng(len(dd))
            bars = rng.integers(WARMUP, max(WARMUP + 1, len(dd) - HOLD - 2), size=len(ev))
            for e, b in zip(ev, bars):
                t = _simulate(dd, atr, int(b), e.bull)
                if t:
                    t["kind"] = "RANDOM"
                    out.append(t)
            return out
        for e in events:
            if e.internal != want_internal:
                continue
            t = _simulate(dd, atr, e.i + 1, e.bull)   # +1 = бар события закрыт
            if t:
                t["kind"] = e.kind
                out.append(t)
        return out
    return mechanic


def _line(tag: str, R: pd.DataFrame) -> None:
    p = R.pnl.values
    if not len(p):
        print(f"{tag:14s} — пусто")
        return
    frag = np.sort(p)[:-max(1, len(p) // 10)].sum()      # хрупкость: без верхних 10%
    cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100  # охват монет
    wins, loss = p[p > 0].sum(), -p[p < 0].sum()
    pf = wins / loss if loss > 0 else float("inf")
    print(f"{tag:14s} n={len(p):6d} медиана {np.median(p):+7.3f}% среднее {p.mean():+7.3f}% "
          f"сумма {p.sum():+9.1f}% PF {pf:5.2f} безтоп10% {frag:+9.1f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    res = {}
    for layer in ("swing", "micro", "random"):
        print(f"\n{'='*78}\nСЛОЙ: {layer}\n{'='*78}")
        R = collect(make_mechanic(layer), tf=tf, n_symbols=n_sym,
                    with_flags=(layer == "micro"))
        res[layer] = R

    print(f"\n{'='*78}\nСВОДКА — одинаковая геометрия (стоп {SL_ATR}ATR, цель {TP_ATR}ATR, "
          f"{HOLD} баров)\n{'='*78}")
    for layer in ("swing", "micro", "random"):
        _line(layer, res[layer])
    print("\n── по СТОРОНАМ ──")
    for layer in ("swing", "micro", "random"):
        for side in ("long", "short"):
            _line(f"{layer}/{side}", res[layer][res[layer].side == side])
    print("\n── по ТИПУ события ──")
    for layer in ("swing", "micro"):
        for k in ("BOS", "CHoCH"):
            _line(f"{layer}/{k}", res[layer][res[layer].kind == k])
    print("\n── по ГОДАМ (микро) ──")
    for y in sorted(res["micro"].year.unique()):
        _line(f"micro/{y}", res["micro"][res["micro"].year == y])

    print(f"\n{'='*78}\nОБЯЗАТЕЛЬНЫЕ СРЕЗЫ (микро-слой)\n{'='*78}")
    report(res["micro"])
    print(f"\n{'='*78}\nСЛЕПОЙ ОТБОР IS→OOS (микро-слой)\n{'='*78}")
    blind_select(res["micro"])


if __name__ == "__main__":
    main()
