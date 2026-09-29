# -*- coding: utf-8 -*-
"""WEEKLY-HYPOTHESIS (13.07, Егор: «FUTURE PIVOTS знает уровни заблаговременно и по ним можно
прогнозировать, но мы этого не делаем никогда! мы не торгуем гипотезы хотя могли бы»).

Первый ПРОАКТИВНЫЙ слой: не ждём сигнал — строим план недели ЗАРАНЕЕ, как трейдер в воскресенье.
Уровни недели известны в пн 00:00 (future pivots, не лагают/не перерисовываются), правила — из
ИЗМЕРЕННОЙ карты поведения (scripts/pivot_behavior_study.py, memory pivot_behavior_map, 461 sym
48k недель), НЕ из головы:
  BEAR-режим: S1 ломается вниз 62% · R1 bounce 56%   |   reach за неделю: S1 43% R1 39% S2 17% R2 19%
  BULL-режим: R1 ломается вверх 57% · S1 bounce 57%
Режим = наклон недельного P (свежий 1W vs прошлый 1W_prev — оба уже в pivot_cache бота, reuse).

4 правила → гипотеза на пару: target / stretch / invalidation (все — уровни S1/S2/R1/R2, которые
логирует weekly_pivot_watch → резолвинг ЧИСТО по таблице касаний, ноль новых запросов).
НЕ торговля — форвард-проверка прогнозной силы. Скоринг: что коснулось раньше, target или inval.

Таблица: weekly_hypothesis (subscriptions.db). pm2 cron: раз в час.
Тест: python scripts/weekly_hypothesis.py
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
import sqlite3
import datetime as dt

DB = "subscriptions.db"

# Правила из ИЗМЕРЕННОЙ карты (pivot_behavior_map): (режим, зона открытия) → гипотеза.
# prob = вероятность пробоя/отбоя ключевого уровня из ретро (не reach!).
RULES = {
    ("BEAR", "S1..P"):  dict(code="bear_break_s1", side="SHORT", target="S1", stretch="S2",
                             inval="R1", prob=62,
                             text="BEAR+открытие под P: тянет к S1, пробой вниз (62%) → S2"),
    ("BEAR", "P..R1"):  dict(code="bear_fade_r1", side="SHORT", target="S1", stretch="S2",
                             inval="R2", prob=56,
                             text="BEAR+открытие над P: отбой от R1 (56%) → вниз к S1"),
    ("BULL", "P..R1"):  dict(code="bull_break_r1", side="LONG", target="R1", stretch="R2",
                             inval="S1", prob=57,
                             text="BULL+открытие над P: пробой R1 вверх (57%) → R2"),
    ("BULL", "S1..P"):  dict(code="bull_hold_s1", side="LONG", target="R1", stretch="R2",
                             inval="S2", prob=57,
                             text="BULL+открытие под P: S1 держит (57%) → возврат к P/R1"),
}


def _week_start_utc(now: dt.datetime) -> str:
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (d - dt.timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _ensure(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS weekly_hypothesis(
        symbol TEXT, week_start TEXT, regime TEXT, open_zone TEXT, hypo_code TEXT, side TEXT,
        target TEXT, stretch TEXT, inval TEXT, prob INTEGER, hypo_text TEXT,
        status TEXT DEFAULT 'OPEN',            -- OPEN / TARGET / STRETCH / INVALID / NONE
        created_at TEXT, resolved_at TEXT,
        PRIMARY KEY(symbol, week_start))""")
    c.commit()


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ws = _week_start_utc(now)
    # N16 29.09: своя база (один писатель); weekly_pivot_* — из базы weekly-pivot (ПЕРВОЙ: в базе бота остались
    # их старые копии), pivot_cache — из базы бота; обе только чтение
    from core.infra import sat_store
    c = sat_store.connect("weekly_hypothesis",
                          attach={"wp": sat_store.path("weekly_pivot"), "bot": sat_store.BOT_DB})
    c.row_factory = sqlite3.Row
    _ensure(c)

    # ── 1. Генерация: пары со снимком открытия (вотчер) + свежим 1W + 1W_prev (наклон P)
    have = {r["symbol"] for r in c.execute(
        "SELECT symbol FROM weekly_hypothesis WHERE week_start=?", (ws,)).fetchall()}
    gen = 0
    rows = c.execute("""
        SELECT o.symbol, o.open_zone, a.pp AS pp_new, b.pp AS pp_prev
        FROM weekly_pivot_open o
        JOIN pivot_cache a ON a.symbol=o.symbol AND a.timeframe='1W'  AND a.period_start LIKE ?
        JOIN pivot_cache b ON b.symbol=o.symbol AND b.timeframe='1W_prev'
        WHERE o.week_start=?""", (f"{ws}%", ws)).fetchall()
    for r in rows:
        if r["symbol"] in have or not (r["pp_new"] and r["pp_prev"]):
            continue
        regime = "BULL" if r["pp_new"] > r["pp_prev"] else "BEAR"
        rule = RULES.get((regime, r["open_zone"]))
        if not rule:            # above_R1 / below_S1 — вне карты, не гипотезируем
            continue
        c.execute("""INSERT OR IGNORE INTO weekly_hypothesis
            (symbol, week_start, regime, open_zone, hypo_code, side, target, stretch, inval,
             prob, hypo_text, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (r["symbol"], ws, regime, r["open_zone"], rule["code"], rule["side"],
                   rule["target"], rule["stretch"], rule["inval"], rule["prob"],
                   rule["text"], now.isoformat()))
        gen += 1

    # ── 2. Резолвинг открытых гипотез по касаниям вотчера (первое из target/inval побеждает)
    touches = {}
    for t in c.execute("SELECT symbol, level, ts FROM weekly_pivot_touch WHERE week_start=?", (ws,)):
        touches.setdefault(t["symbol"], {})[t["level"]] = t["ts"]
    resolved = []
    for h in c.execute("SELECT * FROM weekly_hypothesis WHERE week_start=? AND status='OPEN'", (ws,)).fetchall():
        tch = touches.get(h["symbol"], {})
        t_ts = tch.get(h["target"])
        i_ts = tch.get(h["inval"])
        status = None
        if t_ts and i_ts:
            status = "TARGET" if t_ts <= i_ts else "INVALID"
        elif t_ts:
            status = "TARGET"
        elif i_ts:
            status = "INVALID"
        if status == "TARGET" and tch.get(h["stretch"]):
            status = "STRETCH"
        if status:
            c.execute("UPDATE weekly_hypothesis SET status=?, resolved_at=? "
                      "WHERE symbol=? AND week_start=?", (status, now.isoformat(), h["symbol"], ws))
            resolved.append((h["symbol"].split("/")[0], h["hypo_code"], status))
    c.commit()

    # ── сводка
    n = {r["status"]: r["n"] for r in c.execute(
        "SELECT status, COUNT(*) n FROM weekly_hypothesis WHERE week_start=? GROUP BY status", (ws,))}
    tot = sum(n.values())
    print(f"[WEEKLY-HYPO] неделя {ws} | гипотез={tot} (+{gen}) "
          f"OPEN={n.get('OPEN',0)} TARGET={n.get('TARGET',0)} STRETCH={n.get('STRETCH',0)} "
          f"INVALID={n.get('INVALID',0)}")
    for r in c.execute("""SELECT hypo_code, COUNT(*) n FROM weekly_hypothesis
                          WHERE week_start=? GROUP BY hypo_code ORDER BY n DESC""", (ws,)):
        print(f"  {r['hypo_code']:14} n={r['n']}")
    for sym, code, st in resolved[:12]:
        mark = "✅" if st in ("TARGET", "STRETCH") else "❌"
        print(f"  {mark} {sym:12} {code} → {st}")
    c.close()


if __name__ == "__main__":
    main()
