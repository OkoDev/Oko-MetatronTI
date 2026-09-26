# -*- coding: utf-8 -*-
"""ПРИЧИННАЯ версия замера угасания импульсов (третья итерация, 03.09.2026).

История двух артефактов — обязательна к прочтению, класс ошибки повторяемый:

  ИТЕРАЦИЯ 1: вход на баре ПОСЛЕ вершины импульса → WR 87.9% · PF 15.65.
    Look-ahead: `zigzag_atr` размечает ВСЮ историю, вершина попадает в разметку
    ПОТОМУ ЧТО после неё случился разворот. Мерился не эдж, а определение вершины.

  ИТЕРАЦИЯ 2: добавлен лаг подтверждения 6 баров (префиксный аудит: лаг РОВНО 6
    на всех символах) → PF 5.47. Всё ещё вдвое выше лучших честных находок проекта.
    Причина — SURVIVORSHIP: зигзаг ПЕРЕРИСОВЫВАЕТСЯ. Импульсы, видимые в реальном
    времени, из финальной разметки исчезают: HYPE 40% · GRT 62% · SOL 73% · LINK 66%.
    Тест торговал только «выжившие» — то есть заведомо настоящие сигналы.

  ЗДЕСЬ: сбор ПРЕФИКСНЫЙ. Идём по истории шагом STEP, на каждом шаге спрашиваем
    детектор о том, что видно ТОЛЬКО из прошлого, и торгуем каждый импульс в
    момент его ПЕРВОГО появления — включая те, что позже исчезнут.
    Ровно так его увидел бы бот.

Проверяем два тезиса Егора: угасание энергии импульсов и порядковый номер
в однонаправленной серии («три импульса вверх → ABC»).

Запуск: python scripts/impulse_decay_causal.py [n_symbols] [tf] [step]
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

HOLD = 60
STOP_ATR = 3.0
WARMUP = 600


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


def collect_symbol(sym: str, tf: str, step: int) -> list[dict]:
    from core.smc.smc_engine import zigzag_atr, detect_elliott_impulse
    df = load(sym, tf)
    if len(df) < 2000:
        return []
    idx = df.index
    df = df.reset_index(drop=True)
    n = len(df)
    atr, rsi = _atr(df), _rsi(df)
    vmean = df.volume.rolling(200).mean().values
    o, h, l, c, v = (df.open.values, df.high.values, df.low.values,
                     df.close.values, df.volume.values)

    seen: dict[int, dict] = {}          # b → признаки импульса на момент обнаружения
    order: list[tuple[int, int, dict]] = []   # (бар обнаружения, b, признаки)
    for t in range(WARMUP, n, step):
        try:
            imps = detect_elliott_impulse(zigzag_atr(df.iloc[:t]))
        except Exception:               # noqa: BLE001
            continue
        for i in imps:
            w = i["waves"]
            a, b = int(w[0][0]), int(w[-1][0])
            if b in seen or b >= t or b <= a:
                continue
            if not np.isfinite(vmean[b]) or vmean[b] <= 0:
                continue
            move = (w[-1][1] / w[0][1] - 1) * 100
            f = {"a": a, "b": b, "dir": i["direction"], "move": move,
                 "vol": float(v[a:b + 1].mean() / vmean[b]),
                 "speed": move / max(b - a, 1),
                 "rsi": float(rsi[b]) if np.isfinite(rsi[b]) else np.nan,
                 "w3": float(i["w3_ext"])}
            seen[b] = f
            order.append((t, b, f))     # t = бар, на котором ВПЕРВЫЕ увидели

    out = []
    prev_by_dir: dict[str, dict] = {}
    serie = 0
    prev_dir = None
    for t, b, f in order:               # порядок = хронология ОБНАРУЖЕНИЯ
        serie = serie + 1 if f["dir"] == prev_dir else 1
        prev_dir = f["dir"]
        p = prev_by_dir.get(f["dir"])
        prev_by_dir[f["dir"]] = f
        entry_bar = t                   # вход в момент обнаружения
        if p is None or entry_bar + HOLD >= n:
            continue
        if not np.isfinite(atr[entry_bar]) or atr[entry_bar] <= 0:
            continue
        up = f["dir"] == "up"
        top = float(h[b]) if up else float(l[b])
        e = float(o[entry_bar])

        def _trade(against: bool) -> float:
            """against=True — против импульса (ждём откат/ABC);
            against=False — ПО направлению (продолжение). Геометрия одна."""
            dd_ = (1.0 if up else -1.0) if against else (-1.0 if up else 1.0)
            sl_ = e + dd_ * STOP_ATR * atr[entry_bar]
            long_ = dd_ < 0            # сделка в лонг, если стоп ниже входа
            for j2 in range(entry_bar, min(entry_bar + HOLD, n)):
                if (l[j2] <= sl_) if long_ else (h[j2] >= sl_):
                    return (sl_ - e) / e * 100 * (1 if long_ else -1) - COST_LIMIT
            x2 = float(c[min(entry_bar + HOLD, n - 1)])
            return (x2 - e) / e * 100 * (1 if long_ else -1) - COST_LIMIT

        pnl = _trade(True)
        pnl_pro = _trade(False)
        out.append({
            "pnl_pro": pnl_pro,
            "sym": sym, "dir": f["dir"], "serie": serie,
            "year": int(pd.Timestamp(idx[entry_bar]).year),
            "lag": entry_bar - b,
            "gone": abs(top - e) / top * 100,
            "d_vol": f["vol"] / p["vol"] if p["vol"] > 0 else np.nan,
            "d_speed": f["speed"] / p["speed"] if p["speed"] > 0 else np.nan,
            "d_rsi": f["rsi"] - p["rsi"],
            "decay3": int((f["vol"] < p["vol"]) and (f["speed"] < p["speed"])
                          and (f["rsi"] < p["rsi"])),
            "pnl": pnl,
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
    q = R.pnl_pro.values
    wp, lp = q[q > 0].sum(), -q[q < 0].sum()
    pf_pro = wp / lp if lp > 0 else float("inf")
    print(f"{tag:34s} n={len(p):5d} | ПРОТИВ: PF {pf:5.2f} ср {p.mean():+6.2f}% "
          f"| ПО НАПРАВЛЕНИЮ: PF {pf_pro:5.2f} ср {q.mean():+6.2f}% "
          f"| лаг {R.lag.median():3.0f}б съедено {R.gone.median():5.2f}% монет+ {cov:4.0f}%")


def main() -> None:
    n_sym = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    tf = sys.argv[2] if len(sys.argv) > 2 else "4h"
    step = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    syms = universe(tf, n=n_sym)
    print(f"вселенная {len(syms)} монет · {tf} · ПРЕФИКСНЫЙ сбор, шаг {step} баров")
    print("вход в момент ПЕРВОГО появления импульса (включая исчезающие потом)\n")
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += collect_symbol(s, tf, step)
        except Exception as e:  # noqa: BLE001
            print(f"  [{s}] {type(e).__name__}: {str(e)[:50]}")
        if i % 5 == 0:
            print(f"  ... {i}/{len(syms)} · {len(rows)}", flush=True)
    R = pd.DataFrame(rows)
    if R.empty:
        print("НОЛЬ импульсов — отказ, а не вывод.")
        return
    print(f"\nсобрано {len(R)} импульсов · монет {R.sym.nunique()}\n")

    print("=" * 122)
    print("БАЗА — обе стороны при ОДНОЙ геометрии (стоп 3 ATR, 60 баров)")
    print("=" * 122)
    _line("ВСЁ", R)
    for d in ("up", "down"):
        _line(f"  импульс {d}", R[R.dir == d])
    print("\n── по годам ──")
    for y in sorted(R.year.unique()):
        _line(f"  {y}", R[R.year == y])

    print("\n" + "=" * 122)
    print("ТЕЗИС 1 — УГАСАНИЕ ЭНЕРГИИ")
    print("=" * 122)
    _line("энергия УПАЛА по всем 3", R[R.decay3 == 1])
    _line("энергия НЕ упала", R[R.decay3 == 0])
    _line("  объём упал", R[R.d_vol < 1.0])
    _line("  объём вырос", R[R.d_vol > 1.0])
    _line("  скорость упала", R[R.d_speed < 1.0])
    _line("  скорость выросла", R[R.d_speed > 1.0])
    _line("  RSI ниже", R[R.d_rsi < 0])
    _line("  RSI выше", R[R.d_rsi > 0])

    print("\n" + "=" * 122)
    print("ТЕЗИС 2 — НОМЕР В ОДНОНАПРАВЛЕННОЙ СЕРИИ")
    print("=" * 122)
    for k in sorted(R.serie.unique()):
        if k > 4:
            continue
        _line(f"импульс №{k} подряд", R[R.serie == k])
    _line("№3 и дальше", R[R.serie >= 3])
    print()
    _line("серия>=3 И энергия упала", R[(R.serie >= 3) & (R.decay3 == 1)])
    _line("серия>=3 И энергия НЕ упала", R[(R.serie >= 3) & (R.decay3 == 0)])


if __name__ == "__main__":
    main()
