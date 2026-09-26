# -*- coding: utf-8 -*-
"""Устойчива ли разница слоёв к ГЕОМЕТРИИ входа?

Закон проекта: «весь эдж в РАЗМЕРЕ стопа» — вывод, сделанный на одной геометрии,
переворачивался уже трижды. Основной прогон (`struct_layers_run.py`) фиксирует
стоп 2.0 ATR / цель 3.0 ATR / 48 баров. Здесь тот же сравнительный тест
прогоняется по сетке геометрий: если преимущество слоя живёт только в одной
клетке — это подгонка, а не свойство слоя.

Флаги не считаются (не нужны) → прогон быстрый.

Запуск: python scripts/struct_layers_geometry.py [n_symbols] [tf]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research_harness import load, universe, COST_LIMIT  # noqa: E402

WARMUP = 400
GRID = [(1.0, 1.5), (1.5, 2.25), (2.0, 3.0), (3.0, 4.5), (4.0, 6.0)]   # (стоп ATR, цель ATR)
HOLDS = [24, 48, 96]


def _atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def _sim(dd, atr, bar, up, sl_k, tp_k, hold):
    n = len(dd)
    if bar + hold + 1 >= n or bar < WARMUP or not np.isfinite(atr[bar]) or atr[bar] <= 0:
        return None
    o, h, l, c = dd.open.values, dd.high.values, dd.low.values, dd.close.values
    e = float(o[bar]); d = 1.0 if up else -1.0
    sl = e - d * sl_k * atr[bar]; tp = e + d * tp_k * atr[bar]
    for j in range(bar, min(bar + hold, n)):
        if (l[j] <= sl) if up else (h[j] >= sl):
            return (sl - e) / e * 100 * d - COST_LIMIT
        if (h[j] >= tp) if up else (l[j] <= tp):
            return (tp - e) / e * 100 * d - COST_LIMIT
    x = float(c[min(bar + hold, n - 1)])
    return (x - e) / e * 100 * d - COST_LIMIT


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    syms = universe(tf, n=n_sym)
    print(f"вселенная {len(syms)} монет · {tf} · косты {COST_LIMIT}%")

    from core.smc.oko_sm_engine import run_structure
    cache = []
    for i, s in enumerate(syms, 1):
        df = load(s, tf)
        if len(df) < 6000:
            continue
        dd = df.reset_index(drop=True)
        st = run_structure(dd, swing_len=50, internal_len=5, record_legs=False)
        cache.append((s, dd, _atr(dd), st.events))
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)}", flush=True)
    print(f"готово: {len(cache)} монет\n")

    print(f'{"геометрия":22s} {"слой":7s} {"n":>7s} {"медиана":>9s} {"среднее":>9s} '
          f'{"PF":>6s} {"безтоп10%":>11s} {"монет+":>7s}')
    for hold in HOLDS:
        for sl_k, tp_k in GRID:
            for layer in ("swing", "micro"):
                want = (layer == "micro")
                pnl, by_sym = [], {}
                for s, dd, atr, events in cache:
                    for e in events:
                        if e.internal != want:
                            continue
                        r = _sim(dd, atr, e.i + 1, e.bull, sl_k, tp_k, hold)
                        if r is not None:
                            pnl.append(r)
                            by_sym.setdefault(s, []).append(r)
                if not pnl:
                    continue
                p = np.array(pnl)
                frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
                cov = np.mean([sum(v) > 0 for v in by_sym.values()]) * 100
                w, l_ = p[p > 0].sum(), -p[p < 0].sum()
                pf = w / l_ if l_ > 0 else float("inf")
                tag = f"SL{sl_k}/TP{tp_k}/H{hold}"
                print(f"{tag:22s} {layer:7s} {len(p):7d} {np.median(p):+8.3f}% "
                      f"{p.mean():+8.3f}% {pf:6.2f} {frag:+10.1f}% {cov:6.0f}%")
        print()


if __name__ == "__main__":
    main()
