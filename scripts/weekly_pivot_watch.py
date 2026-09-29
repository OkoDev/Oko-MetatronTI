# -*- coding: utf-8 -*-
"""WEEKLY-PIVOT-WATCH (13.07, Егор «свежая неделя, пивоты пересчитались — данные поанализировать»).

Наблюдение, БЕЗ торговли. Пивоты НЕ считаем — бот уже держит свежие недельные в pivot_cache
(PivotCalculator.get_weekly_pivots, форс-пересчёт в пн + гард свежести period_start). Егор:
«мы же пивоты знаем заранее, зачем считать ещё раз» — ЗАКОН reuse≠дублирование.

Каждый прогон:
  1. батч-тикер BingX (1 запрос) → цены+объём ликвидных перпов;
  2. читаем СВЕЖИЕ 1W-пивоты из pivot_cache (period_start = текущая неделя — тот же гард, что у бота;
     несвежие символы пропускаем, бот догонит их сканом);
  3. фиксируем зону ОТКРЫТИЯ (первое наблюдение за неделю) + логируем первое касание S1/S2/R1/R2.

Тезис (13.07): мажоры над P, альты под P (S1..P) → S1 магнит вниз. Ретро: S1/R1 достаётся ~20% в
первые 2 дня, экстремумы S2/R2 ~5% ([[pivot-behavior-map]]).

Таблицы (subscriptions.db) — ТОЛЬКО то, чего нет у бота:
  weekly_pivot_open   — зона открытия недели (symbol, week_start, open_price, open_zone)
  weekly_pivot_touch  — касания (symbol, week_start, level, touch_price, pivot_val, open_zone, ts)

pm2 cron: каждые 15 мин. Тест: python scripts/weekly_pivot_watch.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import json
import sqlite3
import urllib.request
import datetime as dt

DB = "subscriptions.db"
MIN_VOL_USD = 2_000_000     # ликвидность: не наблюдаем неторгуемое
TICKER = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"


def _week_start_utc(now: dt.datetime) -> dt.datetime:
    """Понедельник 00:00 UTC текущей недели (граница недельной свечи)."""
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - dt.timedelta(days=d.weekday())


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=15))


def _ensure_tables(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS weekly_pivot_open(
        symbol TEXT, week_start TEXT, open_price REAL, open_zone TEXT, ts TEXT,
        PRIMARY KEY(symbol, week_start))""")
    c.execute("""CREATE TABLE IF NOT EXISTS weekly_pivot_touch(
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, week_start TEXT, level TEXT,
        touch_price REAL, pivot_val REAL, open_zone TEXT, ts TEXT)""")
    c.commit()


def _zone(px: float, pp: float, r1: float, s1: float) -> str:
    if px >= r1:
        return "above_R1"
    if px >= pp:
        return "P..R1"
    if px >= s1:
        return "S1..P"
    return "below_S1"


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ws = _week_start_utc(now)
    ws_key = ws.strftime("%Y-%m-%d")

    tk = _get(TICKER)
    prices = {}
    for t in (tk.get("data") or []):
        s = str(t.get("symbol", ""))
        if not s.endswith("-USDT"):
            continue
        try:
            last, qv = float(t["lastPrice"]), float(t.get("quoteVolume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if last > 0 and qv >= MIN_VOL_USD:
            prices[s[:-5]] = last

    # N16 29.09: своя база (один писатель); база бота — только чтение (pivot_cache)
    from core.infra import sat_store
    c = sat_store.connect("weekly_pivot", attach={"bot": sat_store.BOT_DB})
    c.row_factory = sqlite3.Row
    _ensure_tables(c)

    # СВЕЖИЕ пивоты бота: pivot_cache 1W, period_start = текущая неделя (тот же гард свежести)
    piv = {}
    for r in c.execute("SELECT symbol, pp, r1, s1, r2, s2 FROM pivot_cache "
                       "WHERE timeframe='1W' AND period_start LIKE ?", (f"{ws_key}%",)).fetchall():
        if r["pp"] and r["r1"] and r["s1"]:
            piv[str(r["symbol"])] = r

    # 🔴 01.09 ЭТОТ СКРИПТ ДЕРЖАЛ WRITE-LOCK subscriptions.db 22 СЕКУНДЫ КАЖДЫЕ 15 МИНУТ.
    # Замер (пробник BEGIN IMMEDIATE раз в 200мс, 15 мин): БД свободна 97% времени, 8 эпизодов
    # <1с и ОДИН на 22.3с — 15:00:02→15:00:25, ровно старт крона `*/15`. В это окно падали все
    # писатели с коротким терпением: закрытия сделок (`ok=False` без ретрая) и запись
    # DecisionTrace. Причина — транзакция открывалась первым INSERT и держалась до commit в
    # конце, а между ними шёл обход 568 символов с ОТДЕЛЬНЫМ SELECT на каждый.
    # Лечение: всё чтение — заранее, одним запросом; записи копим в памяти и пишем одной
    # короткой транзакцией. Лок теперь занят миллисекунды.
    opened = {r["symbol"] for r in c.execute(
        "SELECT symbol FROM weekly_pivot_open WHERE week_start=?", (ws_key,)).fetchall()}
    logged = {(r["symbol"], r["level"]) for r in c.execute(
        "SELECT symbol, level FROM weekly_pivot_touch WHERE week_start=?", (ws_key,)).fetchall()}
    # open_zone всех символов недели ОДНИМ запросом (был SELECT на каждый символ в цикле)
    open_zones = {r["symbol"]: r["open_zone"] for r in c.execute(
        "SELECT symbol, open_zone FROM weekly_pivot_open WHERE week_start=?", (ws_key,)).fetchall()}

    new_open = 0
    new_touches = []
    rows_open: list = []
    rows_touch: list = []
    for sym, r in piv.items():
        base = sym.split("/")[0]
        px = prices.get(base)
        if not px:
            continue
        pp, r1, s1, r2, s2 = r["pp"], r["r1"], r["s1"], r["r2"], r["s2"]
        oz = _zone(px, pp, r1, s1)
        # 1) снимок открытия недели (первое наблюдение)
        if sym not in opened:
            rows_open.append((sym, ws_key, px, oz, now.isoformat()))
            opened.add(sym)
            open_zones.setdefault(sym, oz)   # для касаний в этом же проходе
            new_open += 1
        # 2) касания уровней (первое за неделю)
        oz0 = open_zones.get(sym, oz)
        for level, val, hit in [("R2", r2, px >= r2), ("R1", r1, px >= r1),
                                ("S1", s1, px <= s1), ("S2", s2, px <= s2)]:
            if hit and (sym, level) not in logged:
                rows_touch.append((sym, ws_key, level, px, val, oz0, now.isoformat()))
                logged.add((sym, level))
                new_touches.append((base, level, px, val, oz0))

    if rows_open or rows_touch:      # одна короткая транзакция вместо 22-секундной
        if rows_open:
            c.executemany("INSERT OR IGNORE INTO weekly_pivot_open VALUES(?,?,?,?,?)", rows_open)
        if rows_touch:
            c.executemany("""INSERT INTO weekly_pivot_touch
                (symbol, week_start, level, touch_price, pivot_val, open_zone, ts)
                VALUES(?,?,?,?,?,?,?)""", rows_touch)
        c.commit()

    opens = c.execute("SELECT COUNT(*) FROM weekly_pivot_open WHERE week_start=?", (ws_key,)).fetchone()[0]
    touched = c.execute("SELECT COUNT(*) FROM weekly_pivot_touch WHERE week_start=?", (ws_key,)).fetchone()[0]
    print(f"[WEEKLY-PIVOT] неделя {ws_key} | свежих пивотов бота={len(piv)} снимков_открытия={opens}(+{new_open}) "
          f"касаний={touched} новых={len(new_touches)}")
    for base, level, px, val, oz in sorted(new_touches, key=lambda x: x[1]):
        arrow = "↓" if level.startswith("S") else "↑"
        print(f"  {arrow} {base:12} коснулась {level} @ {px:.6g} (уровень {val:.6g}, открылась {oz})")
    c.close()


if __name__ == "__main__":
    main()
