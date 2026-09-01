# -*- coding: utf-8 -*-
"""РЕЗОЛВЕР SHADOW-СДЕЛОК (11.08.2026).

Дыра, найденная сегодня: `method_shadow` пишет колонки `resolved`/`outcome` с 05.07,
но их НИКТО не заполнял — 135 строк за 5 недель, разрешено 0. Shadow, который не считает
исходы, не может ответить на вопрос, ради которого создан: он просто копит мусор.

Здесь — один резолвер на все shadow-таблицы (различия описаны спецификацией, не копипастой).
Берёт неразрешённые строки, тянет klines ПОСЛЕ времени сигнала и проигрывает сделку:
что случилось раньше — стоп или цель. Если ни то ни другое за TTL — закрывает по рынку
как EXPIRED и пишет фактический %.

ЗАКОН №1 проекта: меряем в %, не в R. Тугой стоп раздувает R и врёт.

Запуск: python scripts/shadow_resolve.py [--table ote_cell_shadow] [--dry-run]
pm2 (крон каждые 30 мин): --name shadow-resolve
"""
import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # корень проекта, не cwd
from oko_feed.store import conn

# спецификация таблиц: какие колонки где лежат и сколько часов ждём исход
SPECS = {
    "ote_cell_shadow": {
        "entry": "entry", "sl": "sl", "targets": [("tp1r", "pct_1r"), ("tp_ext", "pct_ext")],
        "ttl_h": 72,        # 1:1 с бэктестом (TTL 72 бара 1h)
    },
    "method_shadow": {
        "entry": "entry", "sl": "sl", "targets": [("tp1", "pct_1r")],
        "ttl_h": 96,
    },
}
BINANCE = "https://fapi.binance.com/fapi/v1/klines"


def klines_after(sym: str, ts: int, hours: int):
    """Часовые бары с момента сигнала. Возвращает [(open_ms, high, low, close), ...]."""
    limit = min(1000, hours + 4)
    url = f"{BINANCE}?symbol={sym}USDT&interval=1h&startTime={int(ts)*1000}&limit={limit}"
    try:
        arr = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "oko-resolve"}), timeout=12))
    except Exception as e:
        print(f"    klines {sym}: {e}")
        return []
    return [(int(k[0]), float(k[2]), float(k[3]), float(k[4])) for k in arr]


def resolve_row(row, spec, now_ts):
    """→ (outcome, exit_price, {колонка_%: значение}) или None если рано."""
    sym = row["symbol"].replace("/USDT:USDT", "").replace("USDT", "")
    side = 1 if row["direction"] == "LONG" else -1
    entry = float(row[spec["entry"]]); sl = float(row[spec["sl"]])
    age_h = (now_ts - row["ts"]) / 3600
    bars = klines_after(sym, row["ts"], spec["ttl_h"])
    if not bars:
        return None
    tgts = [(row[c], pc) for c, pc in spec["targets"] if row[c] is not None]
    hit_sl = None
    hit = {pc: None for _, pc in tgts}
    for _, hi, lo, _cl in bars:
        if hit_sl is None and ((side > 0 and lo <= sl) or (side < 0 and hi >= sl)):
            hit_sl = sl
        for tp, pc in tgts:
            if hit[pc] is None and ((side > 0 and hi >= tp) or (side < 0 and lo <= tp)):
                hit[pc] = float(tp)
        if hit_sl is not None and all(v is not None for v in hit.values()):
            break
    pct = lambda p: round(side * (p - entry) / entry * 100, 4)
    # первая цель определяет вердикт строки
    first_pc = tgts[0][1] if tgts else None
    cols = {}
    for tp, pc in tgts:
        cols[pc] = pct(hit[pc]) if hit[pc] is not None else (
            pct(hit_sl) if hit_sl is not None else None)
    if hit_sl is not None and (first_pc is None or hit[first_pc] is None):
        return "SL", sl, cols
    if first_pc and hit[first_pc] is not None:
        return "TP", float(hit[first_pc]), cols
    if age_h >= spec["ttl_h"]:
        last = bars[-1][3]
        for _tp, pc in tgts:
            if cols.get(pc) is None:
                cols[pc] = pct(last)
        return "EXPIRED", last, cols
    return None                                   # ещё в игре


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=None, help="одна таблица вместо всех")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tables = [a.table] if a.table else list(SPECS)
    now = int(time.time())
    for t in tables:
        spec = SPECS[t]
        c = conn()
        try:
            c.row_factory = __import__("sqlite3").Row
            try:
                rows = c.execute(f"SELECT rowid AS rid, * FROM {t} "
                                 "WHERE COALESCE(resolved,0)=0 ORDER BY ts").fetchall()
            except Exception as e:
                print(f"[{t}] нет таблицы: {e}")
                continue
            print(f"[{t}] неразрешённых: {len(rows)}")
            done = 0
            for r in rows:
                res = resolve_row(r, spec, now)
                if res is None:
                    continue
                outcome, exit_px, cols = res
                if a.dry_run:
                    print(f"    {dt.datetime.fromtimestamp(r['ts']):%d.%m %H:%M} "
                          f"{r['symbol']:10} {r['direction']:5} → {outcome:8} {cols}")
                else:
                    sets = ", ".join(f"{k}=?" for k in cols)
                    c.execute(f"UPDATE {t} SET resolved=1, outcome=?, exit_price=?, "
                              f"resolved_ts=?, {sets} WHERE rowid=?",
                              [outcome, exit_px, now] + list(cols.values()) + [r["rid"]])
                    # 🔴 01.09 ТОТ ЖЕ КЛАСС, ЧТО В phase_watch/weekly_pivot_watch: без этого
                    # commit транзакция жила до конца цикла, а внутри цикла идут ЗАПРОСЫ К
                    # БИРЖЕ (resolve_row → _klines) плюс sleep 0.12 на строку — write-lock
                    # subscriptions.db висел бы всё это время. Замер показал эпизоды 21-22с,
                    # в которые падали закрытия сделок бота.
                    c.commit()
                done += 1
                time.sleep(0.12)          # вежливо к API
            if not a.dry_run:
                c.commit()
            print(f"[{t}] разрешено за прогон: {done}")
        finally:
            c.close()


if __name__ == "__main__":
    main()
