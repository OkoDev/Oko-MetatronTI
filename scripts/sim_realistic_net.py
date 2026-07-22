# -*- coding: utf-8 -*-
"""SIM-REALISTIC — честный net% полигона с моделью реального входа (22.07, шаг 2).

Проблема: SIM входит по ИДЕАЛЬНОЙ сигнальной цене (fib 0.618/0.705), живьё фила там нет —
вход на +0.72% (ote) / +2.52% (oko_ote) хуже. SIM-эдж частично иллюзорен
([[ote_sim_edge_illusory_entry_slip]]). Этот скрипт НЕ трогает живой SIM (он хранит идеальную
базу «есть ли эдж у сигнала»), а добавляет АНАЛИТИЧЕСКИЙ слой: измеряет per-source входной
слиппедж из VST-фактов → вычитает из SIM net → показывает, что выживает после честного входа.

Слиппедж — МЕДИАНА (устойчива к катастрофным филлам). Первый порядок: net_real = net − slip.
Второй порядок (сдвиг SL/TP из-за худшего входа → больше SL) НЕ моделируется — реальность
ещё чуть хуже; для полной правды по VST-источникам смотри forward_machine (там факт).

net% = profit_pct − costs_pct (ЗАКОН №1). Запуск: python scripts/sim_realistic_net.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sqlite3
from statistics import median

DB = "subscriptions.db"
DATA_ERA = "2026-07-11"
ALIVE = 0.10   # net_real > → выживает


def _slip_by_source(c):
    """Медианный adverse входной слиппедж % по источнику из VST-фактов (actual vs signal)."""
    rows = c.execute(
        """SELECT signal_type, direction, entry_price, actual_entry_price
           FROM simulated_trades WHERE execution_mode='VST'
           AND actual_entry_price IS NOT NULL AND entry_price>0 AND actual_entry_price>0
           AND status IN ('SL','TP','TSL')""").fetchall()
    acc = {}
    for st, d, ep, aep in rows:
        slip = (aep - ep) / ep * 100 if d == "LONG" else (ep - aep) / ep * 100
        acc.setdefault(st, []).append(slip)
    return {st: median(v) for st, v in acc.items() if len(v) >= 20}


def main():
    c = sqlite3.connect(DB)
    slip = _slip_by_source(c)
    # SIM net по источникам (идеальный вход)
    rows = c.execute(
        f"""SELECT signal_type, COUNT(*) n,
               ROUND(100.0*SUM(profit_pct>0)/COUNT(*),0) wr,
               ROUND(AVG(profit_pct - COALESCE(costs_pct,0)),3) net
           FROM simulated_trades WHERE status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL
           AND execution_mode!='VST' AND created_at >= ?
           GROUP BY signal_type HAVING n >= 15 ORDER BY net DESC""", (DATA_ERA,)).fetchall()

    print(f"🧪 SIM-REALISTIC · era {DATA_ERA} · net_real = SIM_net − медианный_вход_слиппедж(VST)")
    print(f"   (слиппедж измерен по источникам с ≥20 VST-фактами; '?' = нет VST-данных)\n")
    print(f"   {'источник':20} {'n':>4} {'WR':>4} {'SIM_net':>9} {'слип':>7} {'net_РЕАЛ':>9}")
    print("   " + "─" * 62)
    survivors = []
    for st, n, wr, net in rows:
        sl = slip.get(st)
        if sl is None:
            # нет VST-факта → берём консервативную оценку класса (медиана всех известных)
            sl_est = median(list(slip.values())) if slip else 0.15
            net_real = round(net - sl_est, 3)
            mark = "⚪"
            slip_s = f"~{sl_est:.2f}"
        else:
            net_real = round(net - sl, 3)
            slip_s = f"{sl:.2f}"
            mark = "🟢" if net_real > ALIVE else ("🔴" if net_real < -ALIVE else "⚪")
        if net_real > ALIVE:
            survivors.append((st, n, net_real))
        print(f"   {mark} {str(st)[:18]:18} {n:4} {wr:3.0f}% {net:+8.3f}% {slip_s:>7} {net_real:+8.3f}%")

    print("\n── ВЫЖИВШИЕ после честного входа (net_real > +0.10%) ──")
    if survivors:
        for st, n, nr in sorted(survivors, key=lambda x: -x[2]):
            print(f"   🟢 {st:20} n={n} net_real={nr:+.3f}%")
    else:
        print("   ❌ никто — при честном входе полигон не даёт эджа после costs+slip.")
        print("   Вывод: эдж не в отборе сигнала, а в КАЧЕСТВЕ ИСПОЛНЕНИЯ (limit-вход без догона).")


if __name__ == "__main__":
    main()
