"""
radar_pump_geometry.py — какая геометрия извлекает форвард сигнала `pump` (02.10.2026).

Предыстория. `radar_signal_info.py` показал: сигнал `pump` ЖИВОЙ — медиана форварда в сторону сигнала
**+1.5% за 24 ч** против контроля той же волатильности, устойчиво 3/3 месяца. При этом в бою радар терял:
цели строились по магнитам и недельным пивотам (кратно больше форварда), а корзина стопов ≥5% дала
−2.15%/сделку. Вопрос: существует ли геометрия, которая этот форвард забирает.

Метод (без подгонки):
  • вход по рынку в момент сигнала (чистая мера эджа сигнала; лимитный вход радара — отдельный слой);
  • сетка: цель × стоп × горизонт удержания; выход по касанию, стоп приоритетнее в одном баре;
  • косты 0.10% на сделку; свечи 15m BingX из хранилища Сферы 1;
  • 🔑 СЛЕПОЙ ОТБОР: геометрия выбирается на IS (июль–август), проверяется на OOS (сентябрь–октябрь).
    Отдельно печатается контроль (та же геометрия, случайный момент той же волатильности ±25%) —
    без него «плюс» может быть свойством рынка, а не сигнала.
  • метрики: медиана и доля>0 (средние забиты хвостами мемкоинов), PF, сумма, хрупкость (без верхних 10%),
    охват монет. Разрез по сторонам обязателен.

    python scripts/radar_pump_geometry.py
"""
from __future__ import annotations

import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.infra import market_store as ms          # noqa: E402

TF, STEP_MIN, COST = "15m", 15, 0.10
TARGETS = (0.75, 1.0, 1.5, 2.0, 3.0, 5.0)          # цель, % от входа
STOPS = (0.75, 1.0, 1.5, 2.0, 3.0)                 # стоп, %
HOLDS = (4, 16, 48, 96)                            # горизонт, бары 15m = 1ч / 4ч / 12ч / 24ч
IS_MONTHS, OOS_MONTHS = ("2026-07", "2026-08"), ("2026-09", "2026-10")
PRE_BARS, TOL, CTRL_N, CTRL_DAYS = 12, 0.25, 2, 30
_cache: dict = {}


def bars(base: str):
    if base not in _cache:
        d = ms.read_bars(base, TF)
        if len(d):
            d = d.copy(); d.index = d.index.tz_localize(None)
        _cache[base] = d if len(d) else None
    return _cache[base]


def at(d, t):
    if d is None:
        return None, None
    pos = d.index.searchsorted(t, side="right") - 1
    if pos < PRE_BARS or pos >= len(d) - 1:
        return None, None
    pre = d.iloc[pos - PRE_BARS + 1:pos + 1]
    px = float(d.close.values[pos])
    return pos, (float((pre.high - pre.low).mean() / px * 100) if px else None)


def trade(d, pos, long_: bool, tgt: float, stop: float, hold: int) -> float | None:
    """Результат сделки по рынку: % с костами. None — не хватило баров."""
    px = float(d.close.values[pos])
    tp = px * (1 + tgt / 100) if long_ else px * (1 - tgt / 100)
    sl = px * (1 - stop / 100) if long_ else px * (1 + stop / 100)
    end = min(pos + hold, len(d) - 1)
    if end <= pos:
        return None
    w = d.iloc[pos + 1:end + 1]
    for hi, lo in zip(w.high.values, w.low.values):
        hit_sl = (lo <= sl) if long_ else (hi >= sl)
        hit_tp = (hi >= tp) if long_ else (lo <= tp)
        if hit_sl:
            return -stop - COST                     # стоп приоритетнее в одном баре
        if hit_tp:
            return tgt - COST
    exit_px = float(w.close.values[-1])
    return ((exit_px - px) / px * 100) * (1 if long_ else -1) - COST


def stats(xs: list[float]) -> dict | None:
    if not xs:
        return None
    s = sorted(xs)
    w = sum(x for x in xs if x > 0); l = -sum(x for x in xs if x < 0)
    k = max(1, len(xs) // 10)
    return {"n": len(xs), "мед": s[len(s) // 2], "ср": sum(xs) / len(xs),
            "доля>0": sum(x > 0 for x in xs) / len(xs) * 100,
            "PF": (w / l) if l else float("inf"), "сумма": sum(xs),
            "безтоп10": sum(sorted(xs, reverse=True)[k:])}


def line(st: dict | None) -> str:
    if not st:
        return "—"
    return (f"n={st['n']:4d} мед={st['мед']:+6.2f}% ср={st['ср']:+6.2f}% доля>0={st['доля>0']:4.1f}% "
            f"PF={st['PF']:4.2f} Σ={st['сумма']:+8.0f} безтоп10%={st['безтоп10']:+8.0f}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rnd = random.Random(41)
    r = sqlite3.connect(f"file:{ROOT / 'oko_feed' / 'external_data.db'}?mode=ro", uri=True, timeout=20)
    rows = r.execute("SELECT ts, symbol, side FROM radar_orders WHERE sig_type='pump' ORDER BY ts").fetchall()
    sigs = []
    for ts, sym, side in rows:
        t = pd.Timestamp(ts, unit="s")
        d = bars(sym)
        pos, atr = at(d, t)
        if pos is None or not atr:
            continue
        sigs.append((sym, d, pos, (side or "").upper() == "LONG", t.strftime("%Y-%m"), atr, t))
    print(f"ИНВЕНТАРИЗАЦИЯ: сигналов pump с ценами {len(sigs)} из {len(rows)}; "
          f"IS {IS_MONTHS} / OOS {OOS_MONTHS}; вход по рынку; косты {COST}%")
    by_m = defaultdict(int)
    for s in sigs:
        by_m[s[4]] += 1
    print("   по месяцам: " + " · ".join(f"{k} {v}" for k, v in sorted(by_m.items())))
    print(f"   по стороне: LONG {sum(1 for s in sigs if s[3])} · SHORT {sum(1 for s in sigs if not s[3])}")
    print(f"   сетка: цели {TARGETS} × стопы {STOPS} × горизонты {[h // 4 for h in HOLDS]}ч "
          f"= {len(TARGETS) * len(STOPS) * len(HOLDS)} комбинаций (множественность!)\n")

    grid = {}
    for tgt in TARGETS:
        for stop in STOPS:
            for hold in HOLDS:
                is_, oos = [], []
                for sym, d, pos, long_, m, atr, t in sigs:
                    v = trade(d, pos, long_, tgt, stop, hold)
                    if v is None:
                        continue
                    (is_ if m in IS_MONTHS else oos).append(v)
                grid[(tgt, stop, hold)] = (stats(is_), stats(oos))

    # 🔴 ЗАКОН №1: отбор по ДЕНЬГАМ (среднее/сумма), а не по медиане. Медиана может быть +1.9%,
    # а система убыточной, если стоп больше цели: редкие большие минусы съедают частые малые плюсы.
    print("=== IS (июль–август): топ-8 по СРЕДНЕМУ (деньги); отбор ТОЛЬКО по IS ===")
    ranked = sorted([k for k, v in grid.items() if v[0] and v[0]["n"] >= 300],
                    key=lambda k: -grid[k][0]["ср"])
    for k in ranked[:8]:
        tgt, stop, hold = k
        print(f"  цель {tgt}% стоп {stop}% {hold // 4:>2}ч: IS  {line(grid[k][0])}")
    if not ranked:
        print("  нет комбинаций с достаточным n")
        return
    best = ranked[0]
    print(f"\n=== ПРОВЕРКА НА OOS (сентябрь–октябрь) — выбрана: цель {best[0]}% стоп {best[1]}% {best[2] // 4}ч ===")
    print(f"  IS : {line(grid[best][0])}")
    print(f"  OOS: {line(grid[best][1])}")
    print("\n  OOS по всем топ-8 (устойчивость отбора):")
    for k in ranked[:8]:
        print(f"    цель {k[0]}% стоп {k[1]}% {k[2] // 4:>2}ч: {line(grid[k][1])}")

    # контроль и срезы для лучшей комбинации
    tgt, stop, hold = best
    sig_all, ctl_all = [], []
    by_side, by_month, by_coin = defaultdict(list), defaultdict(list), defaultdict(list)
    for sym, d, pos, long_, m, atr, t in sigs:
        v = trade(d, pos, long_, tgt, stop, hold)
        if v is None:
            continue
        sig_all.append(v); by_side["LONG" if long_ else "SHORT"].append(v)
        by_month[m].append(v); by_coin[sym].append(v)
        got = 0
        for _ in range(40):
            if got >= CTRL_N:
                break
            tr = t + pd.Timedelta(days=rnd.uniform(-CTRL_DAYS, CTRL_DAYS))
            p2, a2 = at(d, tr)
            if p2 is None or not a2 or not (atr * (1 - TOL) <= a2 <= atr * (1 + TOL)):
                continue
            got += 1
            v2 = trade(d, p2, long_, tgt, stop, hold)
            if v2 is not None:
                ctl_all.append(v2)
    print(f"\n=== ЛУЧШАЯ ГЕОМЕТРИЯ целиком (IS+OOS): цель {tgt}% стоп {stop}% {hold // 4}ч ===")
    print(f"  сигнал:   {line(stats(sig_all))}")
    print(f"  контроль: {line(stats(ctl_all))}")
    a, b = stats(sig_all), stats(ctl_all)
    if a and b:
        d_ = []
        for _ in range(2000):
            ka, kb = min(len(sig_all), 800), min(len(ctl_all), 800)
            sa = sorted(rnd.choice(sig_all) for _ in range(ka))
            sb = sorted(rnd.choice(ctl_all) for _ in range(kb))
            d_.append(sa[ka // 2] - sb[kb // 2])
        d_.sort()
        print(f"  Δ медиан сигнал − контроль: {a['мед'] - b['мед']:+.3f} п.п. "
              f"(95% [{d_[50]:+.3f}; {d_[1950]:+.3f}])")
    for nm, g in (("сторона", by_side), ("месяц", by_month)):
        print(f"\n  — {nm}:")
        for k in sorted(g):
            print(f"      {k:10} {line(stats(g[k]))}")
    pos_coins = sum(1 for v in by_coin.values() if sum(v) > 0)
    print(f"\n  — охват монет: {len(by_coin)} · в плюсе {pos_coins} ({pos_coins / len(by_coin) * 100:.0f}%)")


if __name__ == "__main__":
    main()
