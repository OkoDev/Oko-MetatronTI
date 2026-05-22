"""Аудит и исправление некорректных SL в открытых сделках.

TSL баг поднимал stop_loss ВЫШЕ initial SL для SHORT при росте цены против позиции.
Скрипт: парсит sl_source для извлечения initial SL, сравнивает с текущим,
флагует и опционально исправляет.

Запуск: python scripts/fix_sl_audit.py [--fix]
"""
import sqlite3
import re
import sys

DB = "subscriptions.db"
DRY_RUN = "--fix" not in sys.argv

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, symbol, direction, entry_price, stop_loss, take_profit,
           signal_type, sl_source, tsl_activated, exchange_order_id
    FROM simulated_trades
    WHERE status = 'OPEN'
    ORDER BY direction, id
""").fetchall()

print(f"Всего открытых: {len(rows)}")
if DRY_RUN:
    print("Режим: DRY RUN (добавь --fix для исправления)")
else:
    print("Режим: ИСПРАВЛЕНИЕ (записываем в БД)")
print()


def parse_initial_sl(sl_source: str) -> float | None:
    """Извлекает начальный SL из sl_source строки.

    Форматы: swing_high:0.02652, wl_pivot_swing_high:0.09182
    """
    if not sl_source:
        return None
    m = re.search(r":([0-9]+\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*$", sl_source)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


short_issues = []
long_issues = []

for r in rows:
    entry = float(r["entry_price"] or 0)
    sl = float(r["stop_loss"] or 0)
    direction = r["direction"]
    tsl = int(r["tsl_activated"] or 0)
    sl_src = r["sl_source"] or ""
    initial_sl = parse_initial_sl(sl_src)
    is_exch = bool(r["exchange_order_id"])

    if not entry or not sl:
        continue

    if direction == "SHORT":
        # Нормально: initial_sl > entry (SL выше входа для SHORT)
        # Баг: current_sl > initial_sl (TSL поднял SL ещё выше)
        if initial_sl is not None and initial_sl > entry:
            if sl > initial_sl * 1.001:
                excess_pct = (sl - initial_sl) / entry * 100
                short_issues.append({
                    "id": r["id"], "symbol": r["symbol"],
                    "entry": entry, "current_sl": sl,
                    "initial_sl": initial_sl, "excess_pct": excess_pct,
                    "tsl": tsl, "sl_source": sl_src, "exchange": is_exch,
                    "correct_sl": initial_sl,
                })

    elif direction == "LONG":
        sl_dist_pct = (sl - entry) / entry * 100

        # Проблема 1: initial_sl из sl_source ВЫШЕ entry (баг при входе)
        if initial_sl is not None and initial_sl > entry:
            long_issues.append({
                "id": r["id"], "symbol": r["symbol"],
                "entry": entry, "current_sl": sl,
                "initial_sl": initial_sl,
                "dist_pct": sl_dist_pct,
                "tsl": tsl, "sl_source": sl_src, "exchange": is_exch,
                "issue": f"initial_sl={initial_sl:.6f} > entry (sl_source уровень выше входа)",
                "correct_sl": entry * (1 - 0.015),  # fallback 1.5% ниже entry
            })

        # Проблема 2: SL ниже entry И очень далеко (>10% ниже) — чрезмерный риск
        elif sl < entry and sl_dist_pct < -10.0:
            long_issues.append({
                "id": r["id"], "symbol": r["symbol"],
                "entry": entry, "current_sl": sl,
                "initial_sl": initial_sl,
                "dist_pct": sl_dist_pct,
                "tsl": tsl, "sl_source": sl_src, "exchange": is_exch,
                "issue": f"SL слишком далеко {sl_dist_pct:.1f}% от entry",
                "correct_sl": None,
            })

        # Проблема 3: SL = 0 или отсутствует
        elif sl <= 0:
            long_issues.append({
                "id": r["id"], "symbol": r["symbol"],
                "entry": entry, "current_sl": sl,
                "initial_sl": None, "dist_pct": None,
                "tsl": tsl, "sl_source": sl_src, "exchange": is_exch,
                "issue": "SL = 0 (не выставлен!)",
                "correct_sl": None,
            })


# ── SHORT отчёт ─────────────────────────────────────────────────────────────
print(f"=== SHORT: найдено {len(short_issues)} с SL > initial (TSL баг) ===")
if short_issues:
    sim_short = [i for i in short_issues if not i["exchange"]]
    exch_short = [i for i in short_issues if i["exchange"]]
    print(f"  SIM: {len(sim_short)}, VST/Exchange: {len(exch_short)}\n")
    for i in short_issues:
        flag = "[VST] " if i["exchange"] else "[SIM] "
        print(f"  {flag} #{i['id']:5d} {i['symbol']:<25}  "
              f"entry={i['entry']:.6f}  initial={i['initial_sl']:.6f}  "
              f"current={i['current_sl']:.6f}  fix={i['correct_sl']:.6f}  "
              f"(+{i['excess_pct']:.2f}%)  tsl={i['tsl']}")
else:
    print("  Проблем не найдено.\n")

# ── LONG отчёт ──────────────────────────────────────────────────────────────
print(f"\n=== LONG: {len(rows) - len([r for r in rows if r['direction']=='SHORT'])} позиций, "
      f"найдено {len(long_issues)} с проблемами ===")
if long_issues:
    for i in long_issues:
        flag = "[VST] " if i["exchange"] else "[SIM] "
        dist = f"{i['dist_pct']:+.2f}%" if i["dist_pct"] is not None else "N/A"
        print(f"  {flag} #{i['id']:5d} {i['symbol']:<25}  "
              f"entry={i['entry']:.6f}  sl={i['current_sl']:.6f}  dist={dist}  "
              f"tsl={i['tsl']}  // {i['issue']}")
else:
    print("  LONG позиции: все SL корректны.")

# ── Аномально большие SL ────────────────────────────────────────────────────
print("\n=== Аномально большой SL dist (SHORT >5%, LONG >8% от entry) ===")
found_any = False
for r in rows:
    entry = float(r["entry_price"] or 0)
    sl = float(r["stop_loss"] or 0)
    direction = r["direction"]
    if not entry or not sl:
        continue
    dist_pct = (sl - entry) / entry * 100
    flag = "[VST]" if r["exchange_order_id"] else "[SIM]"
    if direction == "SHORT" and dist_pct > 5.0:
        print(f"  {flag} #{r['id']:5d} {r['symbol']:<25}  SHORT  dist={dist_pct:+.2f}%  sl={sl:.6f}  src={r['sl_source']}")
        found_any = True
    elif direction == "LONG" and dist_pct < -8.0:
        print(f"  {flag} #{r['id']:5d} {r['symbol']:<25}  LONG   dist={dist_pct:+.2f}%  sl={sl:.6f}  src={r['sl_source']}")
        found_any = True
if not found_any:
    print("  Аномалий нет.")

# ── Исправление ─────────────────────────────────────────────────────────────
all_issues = short_issues + [i for i in long_issues if i.get("correct_sl")]

if not DRY_RUN:
    if not all_issues:
        print("\nНечего исправлять.")
    else:
        print(f"\nИсправляем {len(all_issues)} записей...")
        sim_fixed = 0
        exch_list = []
        for i in all_issues:
            if not i["exchange"]:  # SIM — просто UPDATE в БД
                try:
                    conn.execute(
                        "UPDATE simulated_trades SET stop_loss=? WHERE id=? AND status='OPEN'",
                        (i["correct_sl"], i["id"]),
                    )
                    sim_fixed += 1
                except Exception as e:
                    print(f"  ОШИБКА SIM #{i['id']}: {e}")
            else:
                exch_list.append(i)
        conn.commit()
        print(f"  SIM: исправлено {sim_fixed} в БД.")
        if exch_list:
            print(f"\n  VST/Exchange: {len(exch_list)} требуют cancel+replace на бирже:")
            for i in exch_list:
                print(f"    #{i['id']:5d} {i['symbol']:<25}  sl {i['current_sl']:.6f} -> {i['correct_sl']:.6f}")
            print("\n  Обновляем stop_loss в БД для VST (биржевой ордер обновит бот при следующем цикле):")
            exch_fixed = 0
            for i in exch_list:
                try:
                    conn.execute(
                        "UPDATE simulated_trades SET stop_loss=? WHERE id=? AND status='OPEN'",
                        (i["correct_sl"], i["id"]),
                    )
                    exch_fixed += 1
                except Exception as e:
                    print(f"  ОШИБКА VST #{i['id']}: {e}")
            conn.commit()
            print(f"  VST: {exch_fixed} записей обновлено в БД.")
            print("  Бот при следующем check_open_trades обнаружит расхождение и отправит cancel+replace на биржу.")
else:
    if all_issues:
        print(f"\nДля исправления {len(all_issues)} записей: python scripts/fix_sl_audit.py --fix")

conn.close()
