# -*- coding: utf-8 -*-
"""PHASE-FORWARD — судья Сферы Фазы (шаг 4, 22.07). НЕ торгует, только считает.

Вопрос, ради которого строилась Сфера (инсайт Егора «сторона зависит от ФАЗЫ рынка»):
  СДЕЛКИ ПО ФАЗЕ (fit=True) бьют СДЕЛКИ ПРОТИВ ФАЗЫ (fit=False) по чистому %?

Читает VST-сделки со снапшотом фазы в features_json (пишет trade_simulator, шаг 2-3),
группирует по fit / macro_fit / источник → net% = profit_pct − costs_pct (ЗАКОН №1).
Пока сделок мало — «⏳ рано». Через ~3 недели вердикт решает судьбу фаза-гейта
(config.trading.phase_guard_enabled: soft→hard ИЛИ закрытие автономии).

Reuse: та же формула net% и era, что forward_machine.py. Запуск: python scripts/phase_forward.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import sqlite3
from collections import defaultdict

DB = "subscriptions.db"
DATA_ERA = "2026-07-11"   # чистая линейка (sl_touch + costs_pct), как в forward_machine
NET_ALIVE = 0.10          # avg net% > → ЖИВ · [−0.10,+0.10] грань · < −0.10 льёт
MIN_N = 5                 # ниже — «⏳ рано»


def _verdict(n, net):
    if n < MIN_N or net is None:
        return "⏳ рано"
    if net > NET_ALIVE:
        return "🟢 ЖИВ"
    if net < -NET_ALIVE:
        return "🔴 льёт"
    return "⚪ грань"


def _stat(rows):
    """rows = [(net, win)] → (n, wr%, avg_net)."""
    if not rows:
        return 0, None, None
    n = len(rows)
    wr = 100.0 * sum(1 for _, w in rows if w) / n
    net = sum(net for net, _ in rows) / n
    return n, wr, net


def main():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT signal_type, direction, profit_pct, costs_pct, features_json "
        "FROM simulated_trades WHERE execution_mode='VST' AND status IN ('SL','TP','TSL') "
        "AND profit_pct IS NOT NULL AND created_at >= ? AND features_json LIKE '%\"phase\"%'",
        (DATA_ERA,)).fetchall()

    by_fit = defaultdict(list)          # True/False → [(net,win)]
    by_macro = defaultdict(list)        # True/False/None
    by_src_fit = defaultdict(list)      # (signal_type, fit) → [(net,win)]
    n_parsed = 0
    for r in rows:
        try:
            ph = (json.loads(r["features_json"]) or {}).get("phase")
        except Exception:
            ph = None
        if not ph:
            continue
        n_parsed += 1
        net = float(r["profit_pct"]) - float(r["costs_pct"] or 0)
        win = net > 0
        by_fit[bool(ph.get("fit"))].append((net, win))
        by_macro[ph.get("macro_fit")].append((net, win))
        by_src_fit[(r["signal_type"], bool(ph.get("fit")))].append((net, win))

    print(f"🧭 ФОРВАРД СФЕРЫ ФАЗЫ · era {DATA_ERA} · net%=profit−costs · порог n={MIN_N}")
    print(f"   VST-сделок со снапшотом фазы: {n_parsed}\n")
    if n_parsed == 0:
        print("   Пока ни одной — снапшоты пишутся с 22.07, копим ~3 недели. Возвращайся позже.")
        return

    print("── ПОЛНЫЙ ФИТ (макро+пара) ──")
    for key, lbl in ((True, "ПО фазе   "), (False, "ПРОТИВ фазы")):
        n, wr, net = _stat(by_fit.get(key, []))
        if n:
            print(f"  {_verdict(n, net)} {lbl}  n={n:3} WR{wr:3.0f}% net={net:+.2f}%")

    print("\n── МАКРО-ФИТ (сторона vs veto фазы рынка) ──")
    for key, lbl in ((True, "ПО фазе   "), (False, "ПРОТИВ фазы"), (None, "UNCLEAR   ")):
        n, wr, net = _stat(by_macro.get(key, []))
        if n:
            print(f"  {_verdict(n, net)} {lbl}  n={n:3} WR{wr:3.0f}% net={net:+.2f}%")

    print("\n── ПО ИСТОЧНИКАМ × фит ──")
    srcs = sorted({s for s, _ in by_src_fit})
    for s in srcs:
        parts = []
        for fit in (True, False):
            n, wr, net = _stat(by_src_fit.get((s, fit), []))
            if n:
                parts.append(f"{'fit' if fit else 'anti'} n={n} net={net:+.2f}%")
        if parts:
            print(f"  {str(s)[:22]:22} {' · '.join(parts)}")

    # приговор эксперимента: разделяет ли фаза?
    nf, _, netf = _stat(by_fit.get(True, []))
    na, _, neta = _stat(by_fit.get(False, []))
    print("\n── ПРИГОВОР ──")
    if nf >= MIN_N and na >= MIN_N and netf is not None and neta is not None:
        delta = netf - neta
        print(f"  Δ(ПО − ПРОТИВ) = {delta:+.2f}%/сделку "
              f"({'✅ фаза РАЗДЕЛЯЕТ — гейт оправдан' if delta > 0.15 else '❌ фаза НЕ разделяет'})")
    else:
        print(f"  ⏳ мало данных для приговора (ПО n={nf}, ПРОТИВ n={na}, нужно ≥{MIN_N} каждой)")


if __name__ == "__main__":
    main()
