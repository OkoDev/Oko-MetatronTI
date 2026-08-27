"""КОНТРФАКТ ПО ОТКЛОНЁННЫМ СИГНАЛАМ: какой гейт режет ПРИБЫЛЬ (12.08.2026).

543 916 записей `signal_drops` никто никогда не анализировал. Сделки не открывались,
исхода нет — поэтому исход РЕКОНСТРУИРУЕМ из кэша цен и применяем ОДНУ И ТУ ЖЕ линейку
к отклонённым и к прошедшим сигналам. Иначе метрики несопоставимы.

Прокси-исход: доходность по направлению за фиксированный горизонт от close бара,
СЛЕДУЮЩЕГО за меткой сигнала (причинность: вход не раньше, чем сигнал стал известен).
ЗАКОН №1 проекта: мерить в % net = ret% − costs%, не в R.

Запуск:
    python scripts/drops_counterfactual.py [--hours 24] [--limit 400000]
"""
from __future__ import annotations

import argparse
import bisect
import sqlite3
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "ohlcv_cache.db"
SUBS = ROOT / "subscriptions.db"
COSTS_PCT = 0.35            # round-trip, как во всех исследованиях проекта
BAR_MS = 15 * 60 * 1000


def to_ms(s: str) -> int | None:
    if not s:
        return None
    s = s.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(s[:26], fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


def load_cache(symbols: set[str]) -> dict[str, tuple[list[int], list[float]]]:
    """{symbol_base: (времена, close)} — отсортировано, для bisect."""
    con = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    out: dict[str, tuple[list[int], list[float]]] = {}
    q = "SELECT time, close FROM ohlcv_cache WHERE symbol=? AND timeframe='15m' ORDER BY time"
    for s in symbols:
        rows = con.execute(q, (s,)).fetchall()
        if len(rows) > 50:
            out[s] = ([r[0] for r in rows], [float(r[1]) for r in rows])
    con.close()
    return out


def outcome(bars, ts_ms: int, direction: str, horizon_bars: int) -> float | None:
    """% net по направлению за горизонт. Вход — close ПЕРВОГО бара строго после метки."""
    times, closes = bars
    i = bisect.bisect_right(times, ts_ms)
    if i >= len(times) or i + horizon_bars >= len(times):
        return None
    entry, exit_ = closes[i], closes[i + horizon_bars]
    if entry <= 0:
        return None
    ret = (exit_ - entry) / entry * 100.0
    if direction == "SHORT":
        ret = -ret
    return ret - COSTS_PCT


def frag(vals: list[float]) -> float:
    """Хрупкость: сумма без верхних 10% — отличает эдж от одного хвоста."""
    if not vals:
        return 0.0
    s = sorted(vals, reverse=True)
    return sum(s[max(1, int(len(s) * 0.10)):])


def report(name: str, vals: list[float], syms: set[str], indent: str = "") -> None:
    if not vals:
        print(f"{indent}{name:<32} n=0")
        return
    wins = sum(1 for v in vals if v > 0)
    print(f"{indent}{name:<32} n={len(vals):<6} WR={100*wins/len(vals):5.1f}%  "
          f"мед={st.median(vals):+6.2f}%  ср={st.fmean(vals):+6.2f}%  "
          f"сум={sum(vals):+10.1f}%  безтоп10%={frag(vals):+10.1f}%  монет={len(syms)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Контрфакт по отклонённым сигналам")
    ap.add_argument("--hours", type=int, default=24, help="горизонт прокси-исхода")
    ap.add_argument("--limit", type=int, default=400000)
    args = ap.parse_args()
    horizon = int(args.hours * 4)          # баров 15m

    con = sqlite3.connect(f"file:{SUBS}?mode=ro", uri=True)

    drops = con.execute(
        "SELECT symbol, direction, gate_name, strength, signal_type, dropped_at "
        "FROM signal_drops WHERE direction IN ('LONG','SHORT') "
        "ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    passed = con.execute(
        "SELECT symbol, direction, source_router, strength, created_at "
        "FROM simulated_trades WHERE direction IS NOT NULL AND created_at IS NOT NULL").fetchall()

    syms = {r[0].split(":")[0] for r in drops} | {r[0].split(":")[0] for r in passed}
    print(f"загрузка кэша: {len(syms)} символов…", file=sys.stderr)
    cache = load_cache(syms)
    print(f"кэш есть у {len(cache)} символов | горизонт {args.hours}ч ({horizon} баров 15m) | "
          f"косты {COSTS_PCT}%\n")

    by_gate: dict[str, list[float]] = defaultdict(list)
    gate_syms: dict[str, set[str]] = defaultdict(set)
    gate_month: dict[tuple[str, str], list[float]] = defaultdict(list)
    gate_side: dict[tuple[str, str], list[float]] = defaultdict(list)
    miss = 0

    for sym, side, gate, strength, sigtype, at in drops:
        base = sym.split(":")[0]
        bars = cache.get(base)
        ts = to_ms(at)
        if not bars or ts is None:
            miss += 1
            continue
        v = outcome(bars, ts, str(side).upper(), horizon)
        if v is None:
            miss += 1
            continue
        g = gate or "?"
        by_gate[g].append(v)
        gate_syms[g].add(base)
        gate_month[(g, str(at)[:7])].append(v)
        gate_side[(g, str(side).upper())].append(v)

    base_vals: list[float] = []
    base_syms: set[str] = set()
    for sym, side, src, strength, at in passed:
        b = sym.split(":")[0]
        bars = cache.get(b)
        ts = to_ms(at)
        if not bars or ts is None:
            continue
        v = outcome(bars, ts, str(side).upper(), horizon)
        if v is not None:
            base_vals.append(v)
            base_syms.add(b)

    print(f"отклонённых обсчитано: {sum(len(v) for v in by_gate.values())} | без цены: {miss}")
    print(f"ПРОШЕДШИХ обсчитано ТОЙ ЖЕ линейкой: {len(base_vals)}\n")
    print("═══ ЭТАЛОН: сигналы, которые бот ПРОПУСТИЛ в торговлю ═══")
    report("ПРОШЕДШИЕ (база)", base_vals, base_syms)
    base_med = st.median(base_vals) if base_vals else 0.0
    print()
    print("═══ ОТКЛОНЁННЫЕ по гейтам (сортировка: лучшая медиана сверху) ═══")
    print("   Гейт ВРЕДИТ, если его отклонённые ЛУЧШЕ базы — он резал прибыль.\n")

    ranked = sorted(by_gate.items(), key=lambda kv: -st.median(kv[1]) if kv[1] else 0)
    for g, vals in ranked:
        if len(vals) < 30:
            continue
        mark = "  🔴 ЛУЧШЕ БАЗЫ" if st.median(vals) > base_med else ""
        report(g, vals, gate_syms[g])
        if mark:
            print(f"      {mark} (мед {st.median(vals):+.2f}% против {base_med:+.2f}%)")

    print("\n═══ РАЗРЕЗ по стороне (только гейты ≥200 наблюдений) ═══")
    for g, vals in ranked:
        if len(vals) < 200:
            continue
        for side in ("LONG", "SHORT"):
            report(f"{g} · {side}", gate_side[(g, side)], set(), "  ")

    print("\n═══ РАЗРЕЗ по месяцам ═══")
    for g, vals in ranked:
        if len(vals) < 200:
            continue
        months = sorted(m for (gg, m) in gate_month if gg == g)
        line = "  ".join(
            f"{m}:{st.median(gate_month[(g, m)]):+.2f}%(n={len(gate_month[(g, m)])})"
            for m in months if gate_month[(g, m)])
        print(f"  {g:<26} {line}")

    print("\nНЕ проверено: один режим года (окно 3 мес 2026); ликвидность и размер стопа "
          "(в signal_drops нет цены входа и стопа); кластерность.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
