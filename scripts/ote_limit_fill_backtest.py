# -*- coding: utf-8 -*-
"""OTE-LIMIT-FILL — вердикт A/B входа на записанных экстремумах (22.07, шаг 3).

Вопрос: отдыхающий LIMIT на reaction-close (как ставит бот) восстанавливает эдж (A) или
страдает adverse selection (B)? ote не в проде (VST 0 с 16.07) → решаем на ИСТОРИИ SIM.

Механика: ote entry = закрытие реакционной свечи (_check_shot→c[k]). Лимит отдыхает на entry.
Фила ⟺ цена ВЕРНУЛАСЬ к entry после сигнала:
  LONG  BUY@entry  фила если пост-входовый min_price ≤ entry (цена опустилась к входу);
  SHORT SELL@entry фила если пост-входовый max_price ≥ entry (цена поднялась к входу).
Не вернулась → раннер УШЁЛ, лимит ПРОПУСТИЛ. Сравниваем net% филов vs пропусков.
  ❌ пропуски ЛУЧШЕ филов = adverse selection (лимит фила лосей, пропускает винеров) = B.
  ✅ филы в плюсе = LIMIT работает, берём меньше но чисто = A.

Экстремумы min/max = пост-входовые (trade_simulator пишет из баров после created_at). Это
fill-rate ВЕРХНЯЯ граница (без TTL — поздние возвраты тоже считаются филом; с TTL было бы ниже).
net% = profit_pct − costs_pct (ЗАКОН №1). Запуск: python scripts/ote_limit_fill_backtest.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import sqlite3

DB = "subscriptions.db"


def _stat(rows):
    if not rows:
        return 0, None, None
    n = len(rows)
    wr = 100.0 * sum(1 for x in rows if x > 0) / n
    return n, wr, sum(rows) / n


def _report(label, trades):
    filled, missed = [], []
    fill_win_frac = miss_win_frac = 0
    for d, entry, mn, mx, net in trades:
        if d == "LONG":
            hit = mn is not None and mn <= entry
        else:
            hit = mx is not None and mx >= entry
        (filled if hit else missed).append(net)
    nf, wrf, netf = _stat(filled)
    nm, wrm, netm = _stat(missed)
    tot = nf + nm
    print(f"── {label} (n={tot}) ──")
    if not tot:
        print("   нет данных\n"); return
    base_net = sum(filled + missed) / tot
    print(f"   BASELINE SIM (идеальный вход): net={base_net:+.3f}%")
    print(f"   fill-rate(верх.гр.) = {100*nf/tot:.0f}%")
    if nf: print(f"   🟢 ФИЛЫ    n={nf:4} WR{wrf:3.0f}% net={netf:+.3f}%")
    if nm: print(f"   ⚪ ПРОПУСКИ n={nm:4} WR{wrm:3.0f}% net={netm:+.3f}%  ← лимит НЕ взял")
    if nf and nm:
        dlt = netf - netm
        print(f"   Δ(ФИЛЫ−ПРОПУСКИ) = {dlt:+.3f}%")
        if netm > netf + 0.10:
            print(f"   ❌ ADVERSE SELECTION: пропущенные ЛУЧШЕ → лимит фила лосей, пропускает винеров (B)")
        elif netf > 0.10:
            print(f"   ✅ филы в плюсе → LIMIT работает, чище но меньше сделок (A)")
        else:
            print(f"   ⚪ филы не в плюсе — эдж лимитом не восстанавливается")
    print()


def main():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    rows = c.execute(
        """SELECT direction, entry_price, min_price, max_price, profit_pct, costs_pct, timeframe
           FROM simulated_trades WHERE signal_type='ote_nested' AND execution_mode!='VST'
           AND status IN ('SL','TP','TSL') AND profit_pct IS NOT NULL AND entry_price>0
           AND min_price IS NOT NULL AND max_price IS NOT NULL AND created_at>='2026-06-04'""").fetchall()
    all_t = [(r["direction"].upper(), float(r["entry_price"]), float(r["min_price"]),
              float(r["max_price"]), float(r["profit_pct"]) - float(r["costs_pct"] or 0)) for r in rows]
    long_t = [t for t in all_t if t[0] == "LONG"]
    short_t = [t for t in all_t if t[0] == "SHORT"]

    print(f"🎯 OTE LIMIT-FILL — вердикт A/B (ote SIM июнь-июль, n={len(all_t)})")
    print("   лимит на reaction-close: фила ⟺ цена вернулась к входу; иначе раннер пропущен\n")
    _report("ВСЕ", all_t)
    _report("LONG", long_t)
    _report("SHORT", short_t)


if __name__ == "__main__":
    main()
