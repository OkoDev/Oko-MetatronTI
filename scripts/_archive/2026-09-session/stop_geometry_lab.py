# -*- coding: utf-8 -*-
"""ГЕОМЕТРИЯ СТОПА НА БОЕВЫХ ВХОДАХ + РАЗБОР ВЫБИТЫХ (05.09.2026).

Вопрос Егора: «если коридор чрезмерно велик — значит входим не там, и выбивает поэтому.
Нужно исследовать движения ПОСЛЕ стопа и учиться на ошибках, не искать улучшения в редком +».

Две части:
  A. КОНТРФАКТ ГЕОМЕТРИИ. Берём ФАКТИЧЕСКИЕ боевые входы (символ, время, сторона) и
     меняем ТОЛЬКО выход: стоп × цель × горизонт. Вход не трогаем — значит разница
     чисто геометрическая.
  B. РАЗБОР ВЫБИТЫХ. Для сделок, выбитых боевым стопом: куда пошла цена ПОСЛЕ стопа?
       · вернулась к цели  → стоп стоял в шуме, вход был верен (лечится геометрией);
       · продолжила против → вход неверен по направлению (геометрия НЕ спасёт).
     Это разделение и есть ответ на вопрос «стоп не там или вход не там».

🔴 Всё в % ЦЕНЫ после костов. R не используется как критерий: он оказался фейковым
([[law_recorded_pf_needs_remeasure]], fakeR_quarantine). Косты вычитаются явной ставкой —
`costs_pct` в БД заполнен у 6% сделок ([[costs_pct_filled_only_6pct]]).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from research_harness import load                      # noqa: E402

COST = 0.35                     # % на сделку, лимитный вход
STOPS_PCT = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
TARGETS_R = [1.0, 2.0, 3.0]     # цель в кратности стопа
HOLDS = [24, 96, 192]           # баров 15m: 6 ч · 24 ч · 48 ч


def trades(limit: int, days: int) -> list[dict]:
    c = sqlite3.connect(str(ROOT / "subscriptions.db"))
    c.row_factory = sqlite3.Row
    q = f"""SELECT symbol, direction, entry_price, stop_loss, created_at, signal_type, status
            FROM simulated_trades
            WHERE execution_mode='VST' AND status NOT IN ('OPEN') AND entry_price>0
              AND created_at > datetime('now','-{days} day')
            ORDER BY RANDOM() LIMIT {limit}"""
    out = [dict(r) for r in c.execute(q)]
    c.close()
    return out


def simulate(H, L, pos, e, d, stop_pct, tgt_r, hold):
    """Исход одной сделки при заданной геометрии. Возвращает % цены (без костов).

    d = +1 long / -1 short. Порядок событий важен: что раньше — стоп или цель.
    Внутри бара при попадании обоих считаем СТОП (консервативно).
    """
    sl = e * (1 - d * stop_pct / 100.0)
    tp = e * (1 + d * stop_pct * tgt_r / 100.0)
    hi = H[pos:pos + hold]
    lo = L[pos:pos + hold]
    if len(hi) == 0:
        return None
    if d > 0:
        hit_sl = lo <= sl
        hit_tp = hi >= tp
    else:
        hit_sl = hi >= sl
        hit_tp = lo <= tp
    i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10 ** 9
    i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else 10 ** 9
    if i_sl == 10 ** 9 and i_tp == 10 ** 9:
        return None            # ни то ни другое — закроем по последней цене
    if i_sl <= i_tp:
        return -stop_pct
    return stop_pct * tgt_r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=4000)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()

    tr = trades(a.limit, a.days)
    print(f"выборка боевых входов: {len(tr)} · косты {a.cost}% · всё в % ЦЕНЫ")

    by = {}
    for t in tr:
        by.setdefault(t["symbol"].split(":")[0], []).append(t)

    # накопители: (stop, tgt, hold) → список исходов; плюс разбор выбитых
    grid: dict[tuple, list] = {}
    after_stop = []        # что было ПОСЛЕ боевого стопа
    matched = 0
    coins = 0

    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                       # noqa: BLE001
            continue
        if df is None or len(df) < 300:
            continue
        coins += 1
        idx = df.index
        H, L, C = df.high.values, df.low.values, df.close.values
        n = len(C)
        for t in items:
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                   # noqa: BLE001
                continue
            pos = int(idx.searchsorted(ts))
            if pos <= 0 or pos >= n - max(HOLDS) - 1:
                continue
            e = float(t["entry_price"])
            d = 1 if t["direction"] == "LONG" else -1
            matched += 1

            for sp in STOPS_PCT:
                for tg in TARGETS_R:
                    for hd in HOLDS:
                        r = simulate(H, L, pos, e, d, sp, tg, hd)
                        if r is None:
                            # не сработало ничего → выход по цене на конце горизонта
                            r = (float(C[min(pos + hd, n - 1)]) - e) / e * 100.0 * d
                        grid.setdefault((sp, tg, hd), []).append(r)

            # ── B. что было ПОСЛЕ боевого стопа ──────────────────────────
            bsl = t["stop_loss"]
            if not bsl:
                continue
            bsl = float(bsl)
            if (d > 0 and not (0 < bsl < e)) or (d < 0 and not bsl > e):
                continue
            w_h, w_l = H[pos:pos + 96], L[pos:pos + 96]
            hit = (w_l <= bsl) if d > 0 else (w_h >= bsl)
            if not hit.any():
                continue                        # боевой стоп не сработал
            k = pos + int(np.argmax(hit))       # бар срабатывания
            stop_pct = abs(e - bsl) / e * 100.0
            fwd_h, fwd_l = H[k + 1:k + 1 + 96], L[k + 1:k + 1 + 96]
            if len(fwd_h) < 10:
                continue
            # ход ПОСЛЕ стопа: в нашу сторону от цены входа и против
            back = (fwd_h.max() - e) / e * 100.0 if d > 0 else (e - fwd_l.min()) / e * 100.0
            away = (e - fwd_l.min()) / e * 100.0 if d > 0 else (fwd_h.max() - e) / e * 100.0
            after_stop.append(dict(sym=sym, st=t["signal_type"], stop_pct=stop_pct,
                                   back=back, away=away, bars_to_stop=k - pos))

    print(f"сопоставлено с кэшем: {matched} сделок · {coins} монет\n")

    # ── A. таблица геометрии ────────────────────────────────────────────
    print("=" * 100)
    print("A. КОНТРФАКТ ГЕОМЕТРИИ НА ТЕХ ЖЕ ВХОДАХ (net % на сделку после костов)")
    print("=" * 100)
    print(f"{'стоп':>6} {'цель':>6} " + "".join(f"{'hold ' + str(h):>14}" for h in HOLDS))
    best = []
    for sp in STOPS_PCT:
        for tg in TARGETS_R:
            cells = []
            for hd in HOLDS:
                v = np.array(grid.get((sp, tg, hd), []), dtype=float)
                if len(v) < 100:
                    cells.append("  —")
                    continue
                net = v.mean() - a.cost
                wr = 100.0 * (v > 0).mean()
                cells.append(f"{net:+7.3f}% W{wr:4.1f}")
                best.append((net, sp, tg, hd, len(v), wr))
            print(f"{sp:>5}% {tg:>5}R " + "".join(f"{c:>14}" for c in cells))
    print()
    if best:
        best.sort(reverse=True)
        print("ЛУЧШИЕ ЯЧЕЙКИ:")
        for net, sp, tg, hd, n_, wr in best[:6]:
            print(f"   стоп {sp}% · цель {tg}R · hold {hd} → net {net:+.3f}%/сделку · WR {wr:.1f}% · n={n_}")
        print("🔴 это ОТБОР по той же выборке — не вердикт, а карта. Слепая проверка отдельно.")

    # ── B. разбор выбитых ───────────────────────────────────────────────
    if after_stop:
        S = pd.DataFrame(after_stop)
        print("\n" + "=" * 100)
        print(f"B. ЧТО БЫЛО ПОСЛЕ БОЕВОГО СТОПА (n={len(S)}, горизонт 96 баров = 24 ч)")
        print("=" * 100)
        # «стоп был в шуме» = после выбития цена вернулась к цели 1R от входа
        S["came_back_1R"] = S.back >= S.stop_pct
        S["came_back_2R"] = S.back >= 2 * S.stop_pct
        print(f"   после стопа цена вернулась к +1R от ВХОДА: {100 * S.came_back_1R.mean():5.1f}%")
        print(f"   ...к +2R:                                   {100 * S.came_back_2R.mean():5.1f}%")
        print(f"   медиана хода ОБРАТНО в нашу сторону:        {S.back.median():5.2f}%")
        print(f"   медиана хода ДАЛЬШЕ против нас:             {S.away.median():5.2f}%")
        print(f"   медиана баров до срабатывания стопа:        {S.bars_to_stop.median():.0f}")
        print("\n   по механикам:")
        for st, g in S.groupby("st"):
            if len(g) < 40:
                continue
            print(f"      {str(st)[:20]:22s} n={len(g):>4}  вернулось к 1R {100 * g.came_back_1R.mean():5.1f}%  "
                  f"медиана назад {g.back.median():5.2f}%  дальше против {g.away.median():5.2f}%  "
                  f"баров до стопа {g.bars_to_stop.median():.0f}")
        print("\n   🔑 ЧТЕНИЕ: высокая доля «вернулось к 1R» = стоп стоял В ШУМЕ, вход верен.")
        print("      Низкая доля + большой ход ПРОТИВ = вход неверен, геометрия не спасёт.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
