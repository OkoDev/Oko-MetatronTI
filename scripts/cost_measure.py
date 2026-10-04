#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ФАКТИЧЕСКИЙ КОСТ ИСПОЛНЕНИЯ — измеритель, а не оценка (04.10.2026).

Повод. Во всех выводах проекта про «косты съели эдж» стояло число 0.35%, из которого
подтверждена только комиссия 0.09% (taker 0.045 × 2); остальное было оценкой августа.
Попытка мерить через `live_orders.slip_pct` провалилась: `br.entry_price` в момент отправки
пуст, и ноль в поле означает «НЕ ИЗМЕРЕНО» (22 из 29 ордеров за 5 дней).

🔑 КАНОН: фактический филл лежит в `simulated_trades.actual_entry_price` — его пишут WS-fill
(`core/exchange/exec_ws_integration.py`) и backfill (`core/exchange/position_sync.py`).
Сравнение с `entry_price` (цена сигнала) и есть проскальзывание входа.

Знак: ПЛЮС = исполнились ХУЖЕ сигнала (LONG дороже, SHORT дешевле).
Главная величина — не сам slip, а его ДОЛЯ В РИСКЕ (slip / ширина стопа): именно она
объясняет, почему тугие стопы кровят, и подтверждает закон размера стопа на исполнении.

Запуск:
    python scripts/cost_measure.py                 # весь период
    python scripts/cost_measure.py --days 30       # последние 30 дней
    python scripts/cost_measure.py --source waves_long
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "subscriptions.db"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                                # noqa: BLE001
    pass

# исходная ширина стопа: `stop_loss` в колонке перезаписывается трейлингом, поэтому
# сначала ищем исходный риск в признаках (тот же порядок, что в замерах)
STOP_KEYS = ("wv_risk_pct", "rf_stop_pct", "cw_stop_pct", "original_sl_pct")
IMP_KEYS = ("wv_imp_pct", "amp_pct", "imp_pct")
COMMISSION_ROUND = 0.09          # taker 0.045 × 2, подтверждено


def load(days: int | None, source: str | None) -> list[dict]:
    where = ["actual_entry_price IS NOT NULL", "entry_price IS NOT NULL", "entry_price > 0"]
    params: list = []
    if days:
        where.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} day")
    if source:
        where.append("signal_type = ?")
        params.append(source)
    # 🔑 05.10 `filled_at` — время фактического исполнения. Для LIMIT-источников оно и есть
    # момент сделки: `created_at` у них только постановка заявки, и сравнение филла с той минутой
    # давало ложные «82-100% вне рынка». Где времени нет (старые записи) — остаётся created_at,
    # и это помечается в выводе.
    sql = ("SELECT signal_type, direction, entry_price, actual_entry_price, stop_loss, "
           "features_json, status, profit_pct, COALESCE(filled_at, created_at), "
           "filled_at IS NOT NULL FROM simulated_trades WHERE "
           + " AND ".join(where))
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as c:
        rows = c.execute(sql, params).fetchall()
    out = []
    for stype, d, sig, act, sl, fj, status, pnl, ca, has_ft in rows:
        try:
            sig, act = float(sig), float(act)
        except (TypeError, ValueError):
            continue
        if sig <= 0 or act <= 0:
            continue
        slip = (act - sig) / sig * 100
        if d != "LONG":
            slip = -slip
        try:
            f = json.loads(fj or "{}")
        except Exception:                                        # noqa: BLE001
            f = {}
        stop_pct = None
        for k in STOP_KEYS:
            if f.get(k):
                try:
                    stop_pct = abs(float(f[k]))
                    break
                except (TypeError, ValueError):
                    pass
        if stop_pct is None and sl:
            try:
                stop_pct = abs(sig - float(sl)) / sig * 100
            except (TypeError, ValueError):
                stop_pct = None
        out.append({"src": stype, "dir": d, "slip": slip, "stop_pct": stop_pct,
                    "copy": abs(act - sig) < 1e-12, "status": status, "pnl": pnl,
                    "ca": ca, "has_fill_time": bool(has_ft),
                    "imp": next((float(f[k]) for k in IMP_KEYS if f.get(k)), None)})
    return out


def line(lbl: str, g: list[dict], n_min: int = 5) -> str:
    if len(g) < n_min:
        return f"  {lbl:26} n={len(g):>5} —мало—"
    s = [x["slip"] for x in g]
    worse = 100 * sum(1 for v in s if v > 0) / len(s)
    sh = [x["slip"] / x["stop_pct"] * 100 for x in g if x["stop_pct"]]
    shs = f"доля риска мед {st.median(sh):+6.1f}%" if sh else "доля риска —"
    copies = 100 * sum(1 for x in g if x["copy"]) / len(g)
    return (f"  {lbl:26} n={len(g):>5} slip мед {st.median(s):+7.4f}% ср {st.mean(s):+7.4f}% "
            f"· хуже сигнала {worse:3.0f}% · {shs} · копий {copies:3.0f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--source", type=str, default=None)
    ap.add_argument("--with-copies", action="store_true",
                    help="включить записи, где actual == entry (филл не измерялся) — "
                         "по умолчанию они ИСКЛЮЧЕНЫ, иначе нули занижают медиану")
    a = ap.parse_args()

    raw_data = load(a.days, a.source)
    if not raw_data:
        print("нет сделок с фактическим филлом под эти условия")
        return
    copies = sum(1 for x in raw_data if x["copy"])
    print(f"сделок с фактическим филлом: {len(raw_data)}"
          + (f" · период: последние {a.days} дн" if a.days else " · весь период")
          + (f" · источник: {a.source}" if a.source else ""))
    print(f"⚠️ из них actual РОВНО == entry (копия, филл не настоящий): {copies} "
          f"({100*copies/len(raw_data):.0f}%)")
    _ft = sum(1 for x in raw_data if x.get("has_fill_time"))
    print(f"⏱️ с временем филла (filled_at): {_ft} ({100*_ft/len(raw_data):.0f}%); "
          f"у остальных берётся created_at — для LIMIT-источников это момент ПОСТАНОВКИ заявки, "
          f"и сравнивать их филл со свечой того момента нельзя")
    # 🔴 04.10 КОПИИ ИСКЛЮЧАЮТСЯ ИЗ РАСЧЁТА. Поймано на первом же прогоне этого скрипта:
    # за 60 дней медиана slip вышла ровно 0.0000% и круг «0.09%», хотя копий было 32-85%
    # по источникам — то есть ноль пришёл из записей, где филл не измерялся, а копировался.
    # Это тот же класс поля-пустышки, что `slip_pct`=0 и оборот=0 ([[law_no_finding_means_no_feature]]):
    # ноль здесь означает «НЕ ИЗМЕРЕНО». Считаем по настоящим филлам, копии — только в учёте.
    data = raw_data if a.with_copies else [x for x in raw_data if not x["copy"]]
    if a.with_copies:
        print("🔴 --with-copies: копии ВКЛЮЧЕНЫ, медиана будет занижена нулями")
    else:
        print(f"→ считаем по НАСТОЯЩИМ филлам: {len(data)} сделок "
              f"(копии исключены; --with-copies вернёт их)")
    if len(data) < 10:
        print("🔴 настоящих филлов меньше 10 — выводы по этой выборке делать нельзя")
        if not data:
            return

    print("\n=== ПОТОК ===")
    print(line("все", data))
    for d in ("LONG", "SHORT"):
        print(line(d, [x for x in data if x["dir"] == d]))

    print("\n=== ПО ИСТОЧНИКАМ (n≥10) ===")
    by: dict[str, list[dict]] = {}
    for x in data:
        by.setdefault(x["src"], []).append(x)
    for src, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(g) >= 10:
            print(line(src, g))

    print("\n=== 🔑 ДОЛЯ КОСТА В РИСКЕ по ширине стопа ===")
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 6), (6, 10), (10, 100)):
        print(line(f"стоп {lo}-{hi}% цены",
                   [x for x in data if x["stop_pct"] and lo <= x["stop_pct"] < hi]))
    print("  читается так: при тугом стопе вход съедает долю риска ДО движения цены;")
    print("  это закон размера стопа, измеренный на исполнении, а не на истории")

    s_all = [x["slip"] for x in data]
    rt = 2 * abs(st.median(s_all)) + COMMISSION_ROUND
    print(f"\n=== КРУГ ===\n  медиана slip входа {st.median(s_all):+.4f}% → круг "
          f"{2*abs(st.median(s_all)):.4f}% + комиссия {COMMISSION_ROUND}% = {rt:.4f}%")
    print(f"  против 0.35%, которые стоят в выводах проекта: "
          f"{'оценка ЧЕСТНА' if rt <= 0.45 else '🔴 оценка ЗАНИЖЕНА'}")

    print("\n=== ПО МЕСЯЦАМ ===")
    bym: dict[str, list[dict]] = {}
    for x in data:
        bym.setdefault(str(x["ca"])[:7], []).append(x)
    for m in sorted(bym)[-8:]:
        print(line(m, bym[m]))


if __name__ == "__main__":
    main()
