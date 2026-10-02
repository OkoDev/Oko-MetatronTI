"""
radar_signal_info.py — несёт ли СИГНАЛ радара информацию о движении цены (02.10.2026).

Возражение Егора на вердикт `radar_verdict.py`: «радар ведь использует динамические биржевые данные
(OI, объём, RSI), а не строгую геометрию». Верно — тот замер судил ГЕОМЕТРИЮ СДЕЛКИ (лимит/стоп/цель).
Здесь геометрии нет вообще: меряется чистое форвардное движение цены от момента сигнала.

Если сигнал предсказывает движение, радар можно оживить другой геометрией (закон «воскрешение стратегий
размером стопа»). Если не предсказывает — оживлять нечего.

Данные: ВСЕ сигналы журнала `radar_orders` (≈46 тыс., из них сделками стали 670 — остальные отсечены
лимитом портфеля и гейтами), 03.07–02.10.2026, 431 монета. Цены — 15m BingX из хранилища Сферы 1
(покрытие с 30.06 — полное). Форвард считается в СТОРОНУ сигнала: LONG = рост, SHORT = падение.
Нормировка на ATR% (средний размах 12 баров до сигнала) — иначе мемкоин и BTC несравнимы.

Контроль: тот же момент-сайз, но случайное время той же монеты С ТОЙ ЖЕ волатильностью (ATR% ±25%)
— ловушка, найденная 02.10: без подбора контроль попадает в вчетверо более спокойный рынок.

    python scripts/radar_signal_info.py [--limit N]
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.infra import market_store as ms          # noqa: E402

TF, STEP_MIN = "15m", 15
HORIZONS = {"15м": 1, "1ч": 4, "4ч": 16, "24ч": 96}      # в барах 15m
PRE_BARS, TOL, CTRL_N, CTRL_DAYS = 12, 0.25, 3, 30
_cache: dict = {}


def bars(base: str):
    if base not in _cache:
        d = ms.read_bars(base, TF)
        _cache[base] = d if len(d) else None
        if _cache[base] is not None:
            _cache[base] = _cache[base].copy()
            _cache[base].index = _cache[base].index.tz_localize(None)
    return _cache[base]


def at(d, t):
    """(индекс последнего бара <= t, ATR% до него) или (None, None)."""
    if d is None:
        return None, None
    pos = d.index.searchsorted(t, side="right") - 1
    if pos < PRE_BARS or pos >= len(d) - 1:
        return None, None
    pre = d.iloc[pos - PRE_BARS + 1:pos + 1]
    px = float(d.close.values[pos])
    atr = float((pre.high - pre.low).mean() / px * 100) if px else None
    return pos, atr


def forward(d, pos, long_: bool) -> dict:
    """Движение в сторону сигнала на каждом горизонте: % и в ATR."""
    px = float(d.close.values[pos])
    out = {}
    for name, n in HORIZONS.items():
        j = pos + n
        if j >= len(d):
            out[name] = None
            continue
        ret = (float(d.close.values[j]) - px) / px * 100
        out[name] = ret if long_ else -ret
    return out


def summary(xs: list[float]) -> str:
    if not xs:
        return "—"
    s = sorted(xs)
    return (f"n={len(xs):5d} ср={sum(xs) / len(xs):+6.3f}% мед={s[len(s) // 2]:+6.3f}% "
            f"доля>0={sum(x > 0 for x in xs) / len(xs) * 100:4.1f}%")


def boot_stat(a: list[float], b: list[float], rnd, stat="median", n=1500) -> tuple[float, float, float]:
    """Разница устойчивой статистики (медиана или доля>0) с 95% интервалом.
    🔴 Средние у радара забиты хвостами мемкоинов (±30%) — интервал шире эффекта; медиана и доля>0 устойчивы."""
    def f(xs):
        if stat == "median":
            s = sorted(xs); return s[len(s) // 2]
        return sum(x > 0 for x in xs) / len(xs) * 100
    if not a or not b:
        return 0.0, 0.0, 0.0
    ka, kb = min(len(a), 1500), min(len(b), 1500)
    d = []
    for _ in range(n):
        d.append(f([rnd.choice(a) for _ in range(ka)]) - f([rnd.choice(b) for _ in range(kb)]))
    d.sort()
    return f(a) - f(b), d[int(0.025 * n)], d[int(0.975 * n)]


def boot_diff(a: list[float], b: list[float], rnd, n=1500) -> tuple[float, float, float]:
    if not a or not b:
        return 0.0, 0.0, 0.0
    d = []
    for _ in range(n):
        ma = sum(rnd.choice(a) for _ in range(min(len(a), 400))) / min(len(a), 400)
        mb = sum(rnd.choice(b) for _ in range(min(len(b), 400))) / min(len(b), 400)
        d.append(ma - mb)
    d.sort()
    return sum(a) / len(a) - sum(b) / len(b), d[int(0.025 * n)], d[int(0.975 * n)]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rnd = random.Random(23)
    r = sqlite3.connect(f"file:{ROOT / 'oko_feed' / 'external_data.db'}?mode=ro", uri=True, timeout=20)
    q = "SELECT ts, symbol, sig_type, side, grade, wave_leg, status FROM radar_orders ORDER BY ts"
    rows = r.execute(q).fetchall()
    if args.limit:
        rows = rows[-args.limit:]
    print(f"ИНВЕНТАРИЗАЦИЯ: сигналов радара {len(rows)} (сделками стали лишь TAKEN); "
          f"цены {TF} BingX из хранилища; форвард в сторону сигнала; нормировка ATR%")

    sig: dict = defaultdict(list)        # (ось, ячейка, горизонт) → список
    ctl: dict = defaultdict(list)
    kept = skipped = 0
    for ts, symbol, stype, side, grade, wl, status in rows:
        t = pd.Timestamp(ts, unit="s")
        d = bars(symbol)
        pos, atr = at(d, t)
        if pos is None or not atr:
            skipped += 1
            continue
        long_ = (side or "").upper() == "LONG"
        f = forward(d, pos, long_)
        kept += 1
        cells = [("всё", "все сигналы"), ("тип", stype), ("тип×сторона", f"{stype} {side}"),
                 ("grade", str(grade)), ("статус", status),
                 ("wave_leg", "нет" if wl is None else ("leg≥3" if wl >= 3 else f"leg={wl}"))]
        for h, v in f.items():
            if v is None:
                continue
            for ax, cell in cells:
                sig[(ax, cell, h)].append(v)
        # контроль: та же монета и волатильность, случайный момент
        got = 0
        for _ in range(40):
            if got >= CTRL_N:
                break
            tr = t + pd.Timedelta(days=rnd.uniform(-CTRL_DAYS, CTRL_DAYS))
            p2, a2 = at(d, tr)
            if p2 is None or not a2 or not (atr * (1 - TOL) <= a2 <= atr * (1 + TOL)):
                continue
            got += 1
            for h, v in forward(d, p2, long_).items():
                if v is not None:
                    ctl[("всё", "все сигналы", h)].append(v)
                    ctl[("тип", stype, h)].append(v)
                    ctl[("тип×сторона", f"{stype} {side}", h)].append(v)
    print(f"судимых сигналов: {kept} · без данных: {skipped}\n")

    for h in HORIZONS:
        a, b = sig[("всё", "все сигналы", h)], ctl[("всё", "все сигналы", h)]
        dm, lo, hi = boot_diff(a, b, rnd)
        print(f"■ горизонт {h:>4}: сигнал {summary(a)}")
        print(f"               контроль {summary(b)}")
        print(f"               Δ сигнал − контроль = {dm:+.3f} п.п. (95% [{lo:+.3f}; {hi:+.3f}])"
              f"{'  ← значимо' if lo > 0 or hi < 0 else ''}")
    # устойчивые метрики: медиана и доля>0 против того же контроля
    print("\n=== УСТОЙЧИВЫЕ МЕТРИКИ (средние забиты хвостами): медиана и доля>0 против контроля ===")
    for ax in ("тип×сторона", "grade", "wave_leg"):
        print(f"\n— {ax}:")
        cells = sorted({c for (a, c, h) in sig if a == ax}, key=lambda c: -len(sig[(ax, c, "4ч")]))
        for c in cells:
            for h in ("4ч", "24ч"):
                a_, b_ = sig[(ax, c, h)], ctl[(ax, c, h)] or ctl[("всё", "все сигналы", h)]
                if len(a_) < 300:
                    continue
                dm, lo, hi = boot_stat(a_, b_, rnd, "median")
                dp, plo, phi = boot_stat(a_, b_, rnd, "share")
                mark = " ←ЗНАЧИМО" if (lo > 0 and plo > 0) or (hi < 0 and phi < 0) else ""
                print(f"    {str(c):18} {h:>4} медиана Δ={dm:+6.3f} п.п. [{lo:+6.3f}; {hi:+6.3f}] · "
                      f"доля>0 Δ={dp:+5.1f}% [{plo:+5.1f}; {phi:+5.1f}]{mark}")

    for ax in ("тип×сторона", "grade", "wave_leg", "статус"):
        print(f"\n— {ax} (горизонт 4ч и 24ч):")
        cells = sorted({c for (a, c, h) in sig if a == ax}, key=lambda c: -len(sig[(ax, c, "4ч")]))
        for c in cells:
            a4, a24 = sig[(ax, c, "4ч")], sig[(ax, c, "24ч")]
            if len(a4) < 50:
                continue
            extra = ""
            if ax == "тип×сторона":
                b4 = ctl[(ax, c, "4ч")]
                if b4:
                    dm, lo, hi = boot_diff(a4, b4, rnd)
                    extra = f" | Δ4ч {dm:+.3f} [{lo:+.3f}; {hi:+.3f}]{' ←!' if lo > 0 or hi < 0 else ''}"
            print(f"    {str(c):18} 4ч {summary(a4)} · 24ч {summary(a24)}{extra}")


if __name__ == "__main__":
    main()
