# -*- coding: utf-8 -*-
"""ФАКТИЧЕСКОЕ ПРОСКАЛЬЗЫВАНИЕ ПО РЕАЛЬНЫМ ОРДЕРАМ (14.08.2026, Даат).

Пункт 3 бэклога [[backlog_vst_spread_poisons_forward]] по требованию Егора:
«сравнить фактические avgPrice».

В `simulated_trades` есть ДВА поля цены:
    entry_price         — цена сигнала (по ней считался риск и стоп)
    actual_entry_price  — фактическая цена исполнения ордера на бирже
Их разница со знаком по направлению сделки = НАЛОГ НА ИСПОЛНЕНИЕ, замеренный
не по стакану, а по 19 280 реальным ордерам.

Замер спреда стаканов (14.08) дал: VST 0.2992% против LIVE 0.0888%, то есть
фантомная надбавка +0.21% за круг = 60% от ставки костов 0.35%, которой мерился эдж.
Здесь проверяем, видна ли эта надбавка в фактических исполнениях.

Разрезы: execution_mode (vst/live) · сторона · ликвидность · размер стопа ·
время · доля сделок, где исполнение ХУЖЕ сигнальной цены.

Запуск:  python scripts/vst_actual_fill_slippage.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def stat(v, nm, ind="  "):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) < 20:
        print(f"{ind}{nm:<28} — мало данных ({len(v)})")
        return None
    print(f"{ind}{nm:<28} n={len(v):>6} медиана {np.median(v):>+8.4f}% "
          f"среднее {v.mean():>+8.4f}% · хуже сигнала {100 * (v > 0).mean():>5.1f}% "
          f"· p90 {np.percentile(v, 90):>+7.3f}%")
    return dict(n=len(v), med=float(np.median(v)), mean=float(v.mean()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="subscriptions.db")
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    d = pd.read_sql("""
        SELECT symbol, direction, entry_price, actual_entry_price, stop_loss,
               created_at, status, profit_pct, execution_mode, account_id,
               exchange_order_id, strategy_name, timeframe
        FROM simulated_trades
        WHERE exchange_order_id IS NOT NULL
          AND actual_entry_price IS NOT NULL AND actual_entry_price > 0
          AND entry_price IS NOT NULL AND entry_price > 0
    """, con)
    con.close()

    print("═" * 112)
    print("НАЛОГ НА ИСПОЛНЕНИЕ ПО ФАКТИЧЕСКИМ ОРДЕРАМ · entry_price против actual_entry_price")
    print("═" * 112)
    if d.empty:
        print("\nсделок с заполненным actual_entry_price нет — поле не пишется")
        return 0

    d["dir"] = d.direction.str.upper()
    # знак «хуже»: LONG исполнился ВЫШЕ сигнала — плохо; SHORT НИЖЕ — плохо
    sign = np.where(d["dir"] == "LONG", 1.0, -1.0)
    d["slip"] = (d.actual_entry_price - d.entry_price) / d.entry_price * 100 * sign
    d["t"] = pd.to_datetime(d.created_at, errors="coerce", utc=True, format="mixed")
    d["stop_pct"] = (d.entry_price - d.stop_loss).abs() / d.entry_price * 100
    d["mode"] = d.execution_mode.fillna("—").astype(str).str.lower()

    print(f"\nвсего ордеров с фактической ценой: {len(d)}")
    print(f"окно: {d.t.min()} → {d.t.max()}")
    print(f"режимы исполнения: {d['mode'].value_counts().to_dict()}")

    print(f"\n=== ОБЩИЙ НАЛОГ (положительное = исполнились ХУЖЕ сигнала) ===")
    stat(d.slip, "ВСЕ ОРДЕРА", "")

    print(f"\n=== ПО РЕЖИМУ ИСПОЛНЕНИЯ ===")
    for m, g in d.groupby("mode"):
        stat(g.slip, m)

    print(f"\n=== ПО СТОРОНЕ ===")
    for s, g in d.groupby("dir"):
        stat(g.slip, s)

    print(f"\n=== ПО РАЗМЕРУ СТОПА (насколько налог съедает риск) ===")
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        g = d[(d.stop_pct > lo) & (d.stop_pct <= hi)]
        s = stat(g.slip, f"стоп {lo}-{hi}%")
        if s:
            mid = (lo + min(hi, 20)) / 2
            print(f"      → налог = {100 * s['med'] / max(mid, 0.01):>5.1f}% от риска сделки")

    print(f"\n=== ПО МЕСЯЦАМ (менялось ли) ===")
    d["m"] = d.t.dt.to_period("M").astype(str)
    for m, g in d.groupby("m"):
        stat(g.slip, m)

    print(f"\n=== ХУДШИЕ 15 ПАР (медиана налога, n≥20) ===")
    p = d.groupby("symbol").slip.agg(["size", "median", "mean"])
    p = p[p["size"] >= 20].sort_values("median", ascending=False)
    print(f"  {'пара':<22} {'n':>6} {'медиана':>10} {'среднее':>10}")
    for s, v in p.head(15).iterrows():
        print(f"  {str(s).split('/')[0][:20]:<22} {int(v['size']):>6} "
              f"{v['median']:>+9.4f}% {v['mean']:>+9.4f}%")

    print(f"\n=== ЛУЧШИЕ 8 ПАР (наименьший налог) ===")
    for s, v in p.tail(8).iterrows():
        print(f"  {str(s).split('/')[0][:20]:<22} {int(v['size']):>6} "
              f"{v['median']:>+9.4f}% {v['mean']:>+9.4f}%")

    med = float(d.slip.median())
    print(f"\n" + "═" * 112)
    print(f"ИТОГ: медианный налог на ВХОД = {med:+.4f}%. За круг (вход+выход) ≈ {2 * med:+.4f}%.")
    print(f"Ставка костов в наших замерах эджа — 0.35% за круг.")
    if med > 0:
        print(f"→ фактическое исполнение добавляет {100 * 2 * med / 0.35:.0f}% к этой ставке.")
    print(f"Замер стаканов 14.08: VST 0.2992% против LIVE 0.0888% (надбавка +0.2104%).")
    print("═" * 112)
    return 0


if __name__ == "__main__":
    sys.exit(main())
