# -*- coding: utf-8 -*-
"""КОНТРФАКТ ВЫХОДА ПО ВСЕМ МЕХАНИКАМ (05.09.2026).

Запрос Егора: «проверку проведи и каскадов и других механик TSL, эскалация/деэскалация тоже».

Изолируем ВЫХОД: вход и стоп берём ФАКТИЧЕСКИЕ боевые (из БД), меняем только правило выхода.
  · боевой факт      — что реально получилось (profit_pct, косты вычитаем явно);
  · время 6/24/48 ч  — держим до горизонта, выходим по рынку, боевой стоп жив;
  · боевой TP        — стоп боевой + take_profit из БД, без TSL/BE.
Разница «время» минус «боевой факт» = цена управления позицией (TSL/BE/частичные).

🔴 Контроль обязателен и в ТОМ ЖЕ ОКНЕ (±сутки от сделки, та же монета и сторона) —
контроль по всей истории сравнивает с другим периодом и врёт
([[tsl_be_close_before_move_okoote]]).

Косты 0.35% явной ставкой: `costs_pct` в БД заполнен у 6% сделок
([[costs_pct_filled_only_6pct]]).
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

HOLDS = {"6ч": 24, "24ч": 96, "48ч": 192}
COST = 0.35


def run_exit(H, L, C, pos, e, d, sl, hold, tp=None):
    """Боевой стоп жив; выход по TP (если задан) или по рынку на конце горизонта."""
    lo, hi = L[pos:pos + hold], H[pos:pos + hold]
    if len(lo) == 0:
        return None
    hit_sl = (lo <= sl) if d > 0 else (hi >= sl)
    i_sl = int(np.argmax(hit_sl)) if hit_sl.any() else 10 ** 9
    i_tp = 10 ** 9
    if tp:
        hit_tp = (hi >= tp) if d > 0 else (lo <= tp)
        i_tp = int(np.argmax(hit_tp)) if hit_tp.any() else 10 ** 9
    if i_sl == 10 ** 9 and i_tp == 10 ** 9:
        return (float(C[min(pos + hold, len(C) - 1)]) - e) / e * 100.0 * d
    if i_sl <= i_tp:
        return (sl - e) / e * 100.0 * d
    return (tp - e) / e * 100.0 * d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--min-n", type=int, default=60)
    ap.add_argument("--cost", type=float, default=COST)
    a = ap.parse_args()

    c = sqlite3.connect(str(ROOT / "subscriptions.db"))
    c.row_factory = sqlite3.Row
    tr = [dict(r) for r in c.execute(
        f"""SELECT symbol, direction, entry_price, stop_loss, take_profit, created_at,
                   signal_type, profit_pct, tsl_activated, be_activated, duration_minutes
            FROM simulated_trades
            WHERE execution_mode='VST' AND status NOT IN ('OPEN') AND entry_price>0
              AND stop_loss>0 AND profit_pct IS NOT NULL
              AND created_at > datetime('now','-{a.days} day')""")]
    c.close()
    print(f"боевых сделок: {len(tr)} · косты {a.cost}% · горизонты {list(HOLDS)}\n")

    by: dict[str, list] = {}
    for t in tr:
        by.setdefault(t["symbol"].split(":")[0], []).append(t)

    rng = np.random.default_rng(5)
    rows = []
    for sym, items in by.items():
        try:
            df = load(sym, "15m")
        except Exception:                               # noqa: BLE001
            continue
        if df is None or len(df) < 400:
            continue
        idx, H, L, C = df.index, df.high.values, df.low.values, df.close.values
        for t in items:
            try:
                ts = pd.Timestamp(t["created_at"], tz="UTC")
            except Exception:                           # noqa: BLE001
                continue
            p = int(idx.searchsorted(ts))
            if p <= 200 or p >= len(C) - max(HOLDS.values()) - 1:
                continue
            e, sl = float(t["entry_price"]), float(t["stop_loss"])
            # 🔴 САНИТАЙЗЕР ДАННЫХ (05.09): цена входа обязана совпадать с баром кэша.
            # RAY 100% плоских свечей, STRAX 85%, WAVES 60% → расхождение до 12709%,
            # которое ломает СРЕДНИЕ (медиана переживает). 3% сделок несопоставимы.
            if abs(float(C[p]) - e) / e * 100.0 > 5.0:
                continue
            d = 1 if t["direction"] == "LONG" else -1
            if (d > 0 and sl >= e) or (d < 0 and sl <= e):
                continue
            tp = float(t["take_profit"]) if t["take_profit"] else None
            rec = dict(sym=sym, st=t["signal_type"], dir=t["direction"],
                       факт=float(t["profit_pct"]) - a.cost,
                       tsl=int(t["tsl_activated"] or 0), be=int(t["be_activated"] or 0),
                       dur=float(t["duration_minutes"] or 0))
            for nm, hd in HOLDS.items():
                r = run_exit(H, L, C, p, e, d, sl, hd)
                rec[nm] = (r - a.cost) if r is not None else np.nan
            r_tp = run_exit(H, L, C, p, e, d, sl, HOLDS["48ч"], tp=tp)
            rec["боевой TP"] = (r_tp - a.cost) if r_tp is not None else np.nan
            # контроль в том же окне
            q = int(np.clip(p + rng.integers(-96, 97), 200, len(C) - 200))
            rc = run_exit(H, L, C, q, float(C[q]), d,
                          float(C[q]) * (1 - d * abs(e - sl) / e), HOLDS["6ч"])
            rec["контроль 6ч"] = (rc - a.cost) if rc is not None else np.nan
            rows.append(rec)

    R = pd.DataFrame(rows)
    if R.empty:
        print("🔴 нет данных")
        return 1
    print(f"сопоставлено: {len(R)} сделок · {R.sym.nunique()} монет\n")

    cols = ["факт", "6ч", "24ч", "48ч", "боевой TP", "контроль 6ч"]
    print("=" * 118)
    print("КОНТРФАКТ ВЫХОДА: тот же вход, ТОТ ЖЕ боевой стоп, разные выходы — МЕДИАНА net %/сделку")
    print("=" * 118)
    print(f"{'механика':22s} {'n':>5} " + "".join(f"{c:>13}" for c in cols) + f"{'выигрыш 6ч':>13}")
    for st, g in sorted(R.groupby("st"), key=lambda x: -len(x[1])):
        if len(g) < a.min_n:
            continue
        vals = [g[c].median() for c in cols]
        gain = vals[1] - vals[0]
        print(f"{str(st)[:20]:22s} {len(g):>5} " + "".join(f"{v:>+12.3f}%" for v in vals) +
              f"{gain:>+12.3f}%")
    vals = [R[c].median() for c in cols]
    print(f"{'ВСЕ':22s} {len(R):>5} " + "".join(f"{v:>+12.3f}%" for v in vals) +
          f"{vals[1]-vals[0]:>+12.3f}%")

    # ── TSL / BE: срабатывал или нет ────────────────────────────────────
    print("\n" + "=" * 118)
    print("ВЛИЯНИЕ TSL И BE (сравнение внутри одной механики)")
    print("=" * 118)
    print(f"{'механика':22s} {'группа':16s} {'n':>5} {'факт':>10} {'6ч':>10} {'выигрыш':>10} {'длит.мин':>9}")
    for st, g in sorted(R.groupby("st"), key=lambda x: -len(x[1])):
        if len(g) < a.min_n:
            continue
        for nm, sub in (("TSL сработал", g[g.tsl == 1]), ("TSL нет", g[g.tsl == 0]),
                        ("BE сработал", g[g.be == 1]), ("BE нет", g[g.be == 0])):
            if len(sub) < 25:
                continue
            print(f"{str(st)[:20]:22s} {nm:16s} {len(sub):>5} {sub['факт'].mean():>+9.3f}% "
                  f"{sub['6ч'].mean():>+9.3f}% {sub['6ч'].mean()-sub['факт'].mean():>+9.3f}% "
                  f"{sub['dur'].mean():>9.0f}")
    print("\n🔑 «выигрыш» = удержание 6 ч минус боевой факт. Плюс = управление позицией ЗАБИРАЕТ деньги.")
    print("🔴 TSL/BE-группы — НЕ контрфакт: TSL включается только у сделок, ушедших в плюс (отбор).")
    print("   Читать надо колонку «выигрыш 6ч» в верхней таблице — там вход и стоп одинаковы.")

    out = ROOT / "cache" / "exit_counterfactual.parquet"
    try:
        R.to_parquet(out)
        print(f"\nсырые → {out}")
    except Exception as e:                              # noqa: BLE001
        print(f"(parquet не сохранён: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
