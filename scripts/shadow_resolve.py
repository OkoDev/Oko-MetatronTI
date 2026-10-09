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


def klines_after(sym: str, ts: int, hours: int, src: str | None = None):
    """Часовые бары с момента сигнала. Возвращает [(open_ms, high, low, close), ...].
    src='bingx' (строки с 29.09) → закрытые 1h из хранилища Сферы 1: исход на той же бирже, что вход.
    Старые строки (src пуст) — Binance, как писались."""
    if src == "bingx":
        from core.infra.market_store import read_bars
        d = read_bars(sym, "1h", since_ms=int(ts) * 1000)
        d = d[d.index.asi8 // 1_000_000 >= int(ts) * 1000].iloc[:hours + 4]
        return [(int(t // 1_000_000), float(h), float(lo), float(cl))
                for t, h, lo, cl in zip(d.index.asi8, d["high"], d["low"], d["close"])]
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
    """→ (outcome, exit_price, {колонка_%: значение}) или None если рано.

    🔴 09.10 ПОРЯДОК СОБЫТИЙ. Раньше цель засчитывалась, если её достигли КОГДА-НИБУДЬ до конца срока —
    даже после сработавшего стопа (golden-case: стоп в 1-м баре, цель во 2-м → было TP). Все исходы
    method_shadow/ote_cell_shadow были смещены к TP. Теперь цель засчитана, только если её бар СТРОГО раньше
    бара стопа; стоп и цель в одном часовом баре → стоп (порядок внутри часа неизвестен — консервативно).
    Бары — только внутри срока (раньше смотрелись ещё +4 ч сверх него)."""
    sym = row["symbol"].replace("/USDT:USDT", "").replace("USDT", "")
    side = 1 if row["direction"] == "LONG" else -1
    entry = float(row[spec["entry"]]); sl = float(row[spec["sl"]])
    age_h = (now_ts - row["ts"]) / 3600
    bars = klines_after(sym, row["ts"], spec["ttl_h"], row["src"] if "src" in row.keys() else None)
    end_ms = (int(row["ts"]) + spec["ttl_h"] * 3600) * 1000
    bars = [b for b in bars if b[0] < end_ms]
    if not bars:
        return None
    tgts = [(row[c], pc) for c, pc in spec["targets"] if row[c] is not None]
    i_sl = None
    i_tp = {pc: None for _, pc in tgts}
    for i, (_, hi, lo, _cl) in enumerate(bars):
        if (side > 0 and lo <= sl) or (side < 0 and hi >= sl):
            i_sl = i
        for tp, pc in tgts:
            if i_tp[pc] is None and ((side > 0 and hi >= tp) or (side < 0 and lo <= tp)):
                i_tp[pc] = i
        if i_sl is not None:
            break                                 # после стопа сделки нет
    pct = lambda p: round(side * (p - entry) / entry * 100, 4)
    won = {pc: i_tp[pc] is not None and (i_sl is None or i_tp[pc] < i_sl) for _, pc in tgts}
    cols = {pc: (pct(float(tp)) if won[pc] else pct(sl) if i_sl is not None else None) for tp, pc in tgts}
    if any(v is None for v in cols.values()) and age_h < spec["ttl_h"]:
        return None                               # ещё в игре (в т.ч. дальняя цель после первой)
    if age_h >= spec["ttl_h"]:
        for _tp, pc in tgts:
            if cols[pc] is None:
                cols[pc] = pct(bars[-1][3])
    # первая цель определяет вердикт строки
    first_pc = tgts[0][1] if tgts else None
    if first_pc and won[first_pc]:
        return "TP", float(tgts[0][0]), cols
    if i_sl is not None:
        return "SL", sl, cols
    return "EXPIRED", bars[-1][3], cols


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
