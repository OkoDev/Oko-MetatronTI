# -*- coding: utf-8 -*-
"""УГАСАНИЕ ЭНЕРГИИ ИМПУЛЬСОВ и ПОРЯДКОВЫЙ НОМЕР В СЕРИИ (Егор, 03.09.2026).

Два тезиса, оба проверяются здесь:
  1. «счёт волн на старшем даёт понимание структуры и её угасания» — энергия
     импульса убывает от импульса к импульсу, и это предвещает коррекцию;
  2. «три импульса вверх это уже много говорит хотя бы за коррекцию ABC» —
     порядковый номер импульса в однонаправленной серии сам по себе признак.

Замечено на HYPE 4h: три импульса вверх, объём участия 1.63× → 1.48× → 1.06×,
скорость 1.17 → 0.87 → 0.52 %/бар, RSI на вершине 68.0 → 66.9 → 65.2 при новых
максимумах цены. `w3_ext` угасания НЕ показывает (4.04 → 2.53 → 5.30) — он про
пропорцию волн, а не про энергию.

🔴 Этих признаков в матрице НЕТ вовсе: ни объёма участия импульса, ни его
скорости, ни RSI на вершине как СЕРИИ. Закон проекта: «находок нет = НЕТ
ПРИЗНАКА» — значит их и не могли найти.

Метрика — % ЦЕНЫ с костами (закон №1), считаем поведение ПОСЛЕ завершения
импульса: глубину отката и доходность шорта от вершины.

Запуск: python scripts/impulse_decay_series.py [n_symbols] [tf]
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

HOLD = 60          # баров наблюдения после вершины импульса
STOP_ATR = 3.0     # стоп шорта от вершины, в ATR

# 🔴🔴 ЛАГ ПОДТВЕРЖДЕНИЯ — без него весь замер был look-ahead.
# Первый прогон дал WR 87.9% / PF 15.65 / +13.95% на сделку. Такого не бывает:
# `detect_elliott_impulse` работает поверх `zigzag_atr`, а зигзаг строится по
# ВСЕЙ истории — вершина известна лишь потому, что после неё случился разворот.
# Префиксный аудит (детектор на df[:t] против детектора на полном df) показал
# ЛАГ РОВНО 6 БАРОВ, одинаковый на всех символах и всех импульсах: это параметр
# детектора, а не статистика ([[detector_lag_is_a_parameter_not_statistics]]).
# Вход разрешён только с бара b + CONFIRM_LAG + 1.
CONFIRM_LAG = 6


def _atr(df, n=14):
    h, l, c = df.high.values, df.low.values, df.close.values
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def _rsi(df, n=14):
    d = df.close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).values


def collect_symbol(sym: str, tf: str) -> list[dict]:
    from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse
    df = load(sym, tf)
    if len(df) < 2000:
        return []
    df = df.reset_index(drop=True)
    imp = detect_elliott_impulse(zigzag_atr(df))
    if len(imp) < 2:
        return []
    atr, rsi = _atr(df), _rsi(df)
    vmean = df.volume.rolling(200).mean().values
    o, h, l, c = df.open.values, df.high.values, df.low.values, df.close.values
    n = len(df)

    feats = []
    for i in imp:
        w = i["waves"]
        a, b = int(w[0][0]), int(w[-1][0])
        if b <= a or b >= n or not np.isfinite(vmean[b]) or vmean[b] <= 0:
            continue
        move = (w[-1][1] / w[0][1] - 1) * 100
        feats.append({
            "a": a, "b": b, "dir": i["direction"], "move": move,
            "vol": float(df.volume.values[a:b + 1].mean() / vmean[b]),
            "speed": move / max(b - a, 1),
            "rsi": float(rsi[b]) if np.isfinite(rsi[b]) else np.nan,
            "w3": float(i["w3_ext"]),
        })

    out = []
    serie = 0
    prev_dir = None
    for k, f in enumerate(feats):
        # порядковый номер в ОДНОНАПРАВЛЕННОЙ серии
        serie = serie + 1 if f["dir"] == prev_dir else 1
        prev_dir = f["dir"]
        if k == 0:
            continue
        p = feats[k - 1]
        if p["dir"] != f["dir"]:
            continue                      # сравниваем энергию только с однонаправленным
        b = f["b"]
        entry_bar = b + CONFIRM_LAG + 1          # 🔴 причинный вход, см. CONFIRM_LAG
        if entry_bar + HOLD >= n or not np.isfinite(atr[entry_bar]) or atr[entry_bar] <= 0:
            continue
        up = f["dir"] == "up"
        d = 1.0 if up else -1.0
        top = float(h[b]) if up else float(l[b])
        seg = slice(b + 1, b + 1 + HOLD)
        # описательно: глубина отката от вершины (не PnL — вершина постфактум)
        ext = float(l[seg].min()) if up else float(h[seg].max())
        depth = abs(top - ext) / top * 100
        # сколько хода СЪЕДЕНО за время подтверждения — цена ушла до входа
        gone = abs(top - float(o[entry_bar])) / top * 100
        # сделка ПРОТИВ импульса — только после подтверждения детектора
        e = float(o[entry_bar])
        sl = e + d * STOP_ATR * atr[entry_bar]
        pnl = None
        for j in range(entry_bar, min(entry_bar + HOLD, n)):
            if (h[j] >= sl) if up else (l[j] <= sl):
                pnl = (e - sl) / e * 100 * d - COST_LIMIT
                break
        if pnl is None:
            pnl = (e - float(c[min(entry_bar + HOLD, n - 1)])) / e * 100 * d - COST_LIMIT
        out.append({
            "sym": sym, "dir": f["dir"], "serie": serie,
            "year": int(pd.Timestamp(load(sym, tf).index[b]).year),
            "d_vol": f["vol"] / p["vol"] if p["vol"] > 0 else np.nan,
            "d_speed": f["speed"] / p["speed"] if p["speed"] > 0 else np.nan,
            "d_rsi": f["rsi"] - p["rsi"],
            "d_w3": f["w3"] / p["w3"] if p["w3"] > 0 else np.nan,
            "decay3": int((f["vol"] < p["vol"]) and (f["speed"] < p["speed"])
                          and (f["rsi"] < p["rsi"])),
            "depth": depth, "gone": gone, "pnl": pnl,
        })
    return out


def _line(tag, R):
    if len(R) < 25:
        print(f"{tag:34s} n={len(R):5d}  — мало")
        return
    p = R.pnl.values
    frag = np.sort(p)[:-max(1, len(p) // 10)].sum()
    cov = (R.groupby("sym").pnl.sum() > 0).mean() * 100
    w, l_ = p[p > 0].sum(), -p[p < 0].sum()
    pf = w / l_ if l_ > 0 else float("inf")
    print(f"{tag:34s} n={len(p):5d} WR {(p > 0).mean()*100:4.1f}% PF {pf:5.2f} "
          f"ср {p.mean():+6.2f}% откат {R.depth.median():5.2f}% съедено {R.gone.median():5.2f}% "
          f"безтоп10% {frag:+8.1f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    tf = sys.argv[2] if len(sys.argv) > 2 else "4h"
    syms = universe(tf, n=n_sym)
    print(f"вселенная {len(syms)} монет · {tf} · наблюдение {HOLD} баров после вершины\n")
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += collect_symbol(s, tf)
        except Exception as e:  # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:50]}")
        if i % 10 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    R = pd.DataFrame(rows)
    if R.empty:
        print("НОЛЬ импульсных пар — отказ, а не вывод.")
        return
    print(f"\nсобрано {len(R)} пар импульсов · монет {R.sym.nunique()}\n")

    print("=" * 118)
    print("БАЗА — вход ПРОТИВ импульса сразу после вершины")
    print("=" * 118)
    _line("ВСЁ", R)
    for d in ("up", "down"):
        _line(f"  импульс {d}", R[R.dir == d])

    print("\n" + "=" * 118)
    print("ТЕЗИС 1 — УГАСАНИЕ ЭНЕРГИИ (сравнение с предыдущим импульсом)")
    print("=" * 118)
    _line("энергия УПАЛА по всем 3 мерам", R[R.decay3 == 1])
    _line("энергия НЕ упала по всем 3", R[R.decay3 == 0])
    for col, nm in (("d_vol", "объём"), ("d_speed", "скорость"), ("d_w3", "w3_ext")):
        s = R[col].dropna()
        if len(s) < 50:
            continue
        _line(f"  {nm} упал (<1.0)", R[R[col] < 1.0])
        _line(f"  {nm} вырос (>1.0)", R[R[col] > 1.0])
    _line("  RSI на вершине НИЖЕ", R[R.d_rsi < 0])
    _line("  RSI на вершине ВЫШЕ", R[R.d_rsi > 0])

    print("\n" + "=" * 118)
    print("ТЕЗИС 2 — ПОРЯДКОВЫЙ НОМЕР В ОДНОНАПРАВЛЕННОЙ СЕРИИ")
    print("=" * 118)
    for k in sorted(R.serie.unique()):
        if k > 5:
            continue
        _line(f"импульс №{k} подряд", R[R.serie == k])
    _line("№3 и дальше", R[R.serie >= 3])

    print("\n" + "=" * 118)
    print("СВЯЗКА: 3-й импульс подряд И упавшая энергия")
    print("=" * 118)
    _line("серия>=3 + энергия упала", R[(R.serie >= 3) & (R.decay3 == 1)])
    _line("серия>=3 + энергия НЕ упала", R[(R.serie >= 3) & (R.decay3 == 0)])
    print("\n── по годам (связка) ──")
    B = R[(R.serie >= 3) & (R.decay3 == 1)]
    for y in sorted(B.year.unique()):
        _line(f"  {y}", B[B.year == y])


if __name__ == "__main__":
    main()
