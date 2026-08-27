# -*- coding: utf-8 -*-
"""Полная статистика signal_drops по гейтам (все окна). DS 13.08."""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

con = sqlite3.connect("subscriptions.db")
n = con.execute("SELECT COUNT(*) FROM signal_drops").fetchone()[0]
r = con.execute("SELECT MIN(dropped_at), MAX(dropped_at) FROM signal_drops").fetchone()
print(f"всего дропов: {n}")
print(f"период: {r[0]}  ->  {r[1]}")
print()

# по годам
print("по годам:")
for yr, c in con.execute(
    "SELECT substr(dropped_at,1,4), COUNT(*) FROM signal_drops GROUP BY 1 ORDER BY 1"
).fetchall():
    print(f"  {yr}: {c}")
print()

# ПОЛНОЕ окно
rows = con.execute(
    "SELECT gate_name, COUNT(*) n FROM signal_drops GROUP BY gate_name ORDER BY n DESC"
).fetchall()
tot = sum(r[1] for r in rows)
print(f"== ПОЛНОЕ ОКНО (все {tot} дропов) ==")
for g, c in rows:
    print(f"  {g:<34} {c:>9}  {100*c/tot:6.2f}%")

# 90 дней
print()
rows90 = con.execute(
    "SELECT gate_name, COUNT(*) n FROM signal_drops "
    "WHERE dropped_at >= datetime('now','-90 days') GROUP BY gate_name ORDER BY n DESC"
).fetchall()
tot90 = sum(r[1] for r in rows90)
print(f"== 90 ДНЕЙ ({tot90} дропов) ==")
for g, c in rows90:
    print(f"  {g:<34} {c:>9}  {100*c/tot90:6.2f}%")

# 180 дней
print()
rows180 = con.execute(
    "SELECT gate_name, COUNT(*) n FROM signal_drops "
    "WHERE dropped_at >= datetime('now','-180 days') GROUP BY gate_name ORDER BY n DESC"
).fetchall()
tot180 = sum(r[1] for r in rows180)
print(f"== 180 ДНЕЙ ({tot180} дропов) ==")
for g, c in rows180:
    print(f"  {g:<34} {c:>9}  {100*c/tot180:6.2f}%")

con.close()
