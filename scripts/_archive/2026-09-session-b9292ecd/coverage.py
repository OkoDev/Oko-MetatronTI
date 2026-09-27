"""Покрытие данных после докачки: сколько монет живёт в каждом году и какой у года режим.
Нужно до любого замера (протокол вердикта, п.1: инвентаризация окна и режима каждого года, а не t0 из прошлого скрипта).
Режим года считается по дневным барам: медиана годовой доходности монеты и доля растущих."""
from pathlib import Path
import numpy as np, pandas as pd
import tfcache

syms = sorted(p.stem for p in Path("C:/oko_history/1m").glob("*.parquet"))
rows, ret = [], {}
for s in syms:
    try:
        d = tfcache.load_tf(s, "1d", cols=["close"])
    except Exception:
        continue
    rows.append({"sym": s, "t0": d.index[0], "t1": d.index[-1], "days": len(d)})
    for y, g in d.groupby(d.index.year):
        if len(g) >= 60:                       # год считается покрытым, если монета торговалась ≥60 дней
            ret.setdefault(y, {})[s] = float(g.close.iloc[-1] / g.close.iloc[0] - 1) * 100

inv = pd.DataFrame(rows)
print(f"монет: {len(inv)} · баров 1d суммарно: {inv.days.sum():,}")
print(f"история: {inv.t0.min():%Y-%m-%d} … {inv.t1.max():%Y-%m-%d} · медиана глубины {inv.days.median():.0f} дней "
      f"({inv.days.median() / 365:.1f} года)")
print(f"монет с историей ≥3 лет: {(inv.days >= 1095).sum()} · ≥2 лет: {(inv.days >= 730).sum()} · <1 года: {(inv.days < 365).sum()}\n")

print(f"{'год':>5} {'монет':>6} {'медиана год.дох.':>17} {'доля растущих':>14}  режим")
for y in sorted(ret):
    v = pd.Series(ret[y])
    med, up = v.median(), (v > 0).mean() * 100
    reg = "БЫК" if med > 15 else ("МЕДВЕДЬ" if med < -15 else "НЕЙТРАЛЬ")
    print(f"{y:>5} {len(v):>6} {med:>16.1f}% {up:>13.0f}%  {reg}")

old = 163
new_syms = [r["sym"] for r in rows][old:]
print(f"\nбыло 163 монеты — стало {len(inv)}: выборка для замеров выросла в {len(inv) / 163:.1f} раза")
short = inv[inv.days < 365]
print(f"молодых (<1 года) {len(short)} — их нельзя пускать в годовые срезы 2023-24, но они нужны для 2026")
