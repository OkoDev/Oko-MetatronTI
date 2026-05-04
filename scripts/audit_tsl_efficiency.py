#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCH-95 Слой A — Аудит TSL: эффективность, преждевременность, потери.

Read-only. Только post-fix эра (created_at >= 2026-04-15).

Ключевые вопросы:
  1. Из активированных TSL (tsl_activated=1) — куда уходят сделки?
     SL (после активации = потеря BE), TP (TSL не помешал), TSL (TSL закрыл),
     EXPIRED (timeout).
  2. captured_R_pct: какой % от MFE мы реально берём?
  3. tsl_tf на момент закрытия: 15m шумит, 1h/4h адекватны.
  4. Exit R распределение для status=TSL: преждевременно (1-1.5) / норма (1.5-3) / хорошо (3+).
  5. "Потерянные сделки" — закрылись SL, но max_R_possible >= 1.0:
     либо TSL не активировался (?почему), либо активировался и не спас.
  6. DEV-106 эффективность: pivot fast exit реально применяется?

Запуск:
  python scripts/audit_tsl_efficiency.py
  python scripts/audit_tsl_efficiency.py --signal-type pivot_reversal
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from typing import Any

DB_DEFAULT = "subscriptions.db"
ERA_START_DEFAULT = "2026-04-15"


def _q(c, sql, params=()):
    c.row_factory = sqlite3.Row
    return c.execute(sql, params).fetchall()


def _safe_json(s):
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def _percentiles(vals):
    if not vals:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "mean": None}
    s = sorted(vals)
    n = len(s)
    pct = lambda p: s[max(0, min(n-1, int(round(p*(n-1)))))]
    return {"n": n, "p25": pct(0.25), "p50": pct(0.50),
            "p75": pct(0.75), "mean": statistics.mean(s)}


def _f(v, w=6):
    if v is None:
        return " " * w
    return f"{v:>{w}.2f}"


def header(t):
    print()
    print("=" * 100)
    print(t)
    print("=" * 100)


def section(t):
    print()
    print("-" * 100)
    print(t)
    print("-" * 100)


# ── 1. TSL fate matrix: куда уходят активированные TSL ────────────────────────

def audit_tsl_fate(conn, since, st_filter):
    header("1. TSL FATE — куда уходят сделки с tsl_activated=1?")
    print("Активация TSL = достигнут +1R. Дальше теоретически: TSL или TP. На практике —")
    print("часть сделок откатывается ДО SL (TSL не успел переместиться), часть в EXPIRED.\n")

    where = "created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL"
    params = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, status, tsl_activated, R_multiple,
               max_R_possible, captured_R_pct, tsl_tf
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    # Разбиение: tsl_activated × status
    by_st_act_status: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        act = int(r["tsl_activated"] or 0)
        by_st_act_status[(r["signal_type"], act, r["status"])].append(r["R_multiple"] or 0.0)

    types = sorted({k[0] for k in by_st_act_status.keys()})
    section("Распределение исходов: tsl_activated × status × signal_type")
    print(f"{'signal_type':22s} {'tsl_act':>7s}  {'SL':>5s}  {'TSL':>5s}  {'TP':>4s}  {'EXP':>4s}  "
          f"{'total':>6s}  {'WR%':>6s}  {'avgR':>7s}")
    for st in types:
        for act in (1, 0):
            row = {s: len(by_st_act_status.get((st, act, s), [])) for s in ("SL","TSL","TP","EXPIRED")}
            total = sum(row.values())
            if total == 0:
                continue
            wins = row["TP"] + row["TSL"]
            wr = wins / total * 100 if total else 0
            all_r = []
            for s in ("SL","TSL","TP","EXPIRED"):
                all_r.extend(by_st_act_status.get((st, act, s), []))
            avgr = statistics.mean(all_r) if all_r else 0
            tag = "ACT=1" if act else "ACT=0"
            print(f"{st:22s} {tag:>7s}  {row['SL']:>5d}  {row['TSL']:>5d}  "
                  f"{row['TP']:>4d}  {row['EXPIRED']:>4d}  {total:>6d}  "
                  f"{wr:>5.1f}%  {avgr:>+7.2f}")
        print()

    # Ключевой кейс: tsl_activated=1 → SL → ПОТЕРЯ BE-ЗАЩИТЫ
    section("🚩 КРИТИЧНО: tsl_activated=1 И status=SL — TSL активировался, но сделка ушла в SL")
    print("Эти сделки достигли +1R и должны были как минимум вернуться к BE+0.1%.\n")
    print(f"{'signal_type':22s} {'n':>5s}  {'avgR':>7s}  {'диагноз':<40s}")
    for st in types:
        items = by_st_act_status.get((st, 1, "SL"), [])
        if not items:
            continue
        avgr = statistics.mean(items) if items else 0
        # Если avgR < 0 значимо — TSL не сработал (BE не активирован после TP1)
        diag = "BE/TSL не сработали — потеря защиты" if avgr < -0.3 else "TSL частично спас"
        print(f"{st:22s} {len(items):>5d}  {avgr:>+7.2f}  {diag}")


# ── 2. captured_R_pct distribution ───────────────────────────────────────────

def audit_captured_r(conn, since, st_filter):
    header("2. captured_R_pct — какой % от MFE мы реально берём?")
    print("captured_R_pct = R_multiple / max_R_possible. 100% = взяли всё,")
    print("0% = взяли SL при наличии MFE. <50% — TSL преждевременен.\n")

    where = """created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
               AND R_multiple IS NOT NULL AND captured_R_pct IS NOT NULL
               AND max_R_possible IS NOT NULL AND max_R_possible > 0"""
    params = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, status, captured_R_pct, max_R_possible, R_multiple
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    by_st_status: dict[tuple, list[float]] = defaultdict(list)
    by_st_max_r: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        cap = float(r["captured_R_pct"] or 0.0)
        # captured_R_pct хранится как 0-100 или 0-1 — нормализуем
        if cap <= 1.0 and cap >= 0.0:
            cap *= 100
        by_st_status[(r["signal_type"], r["status"])].append(cap)
        by_st_max_r[(r["signal_type"], r["status"])].append(float(r["max_R_possible"] or 0.0))

    section("captured_R_pct по (signal_type, status) — медиана")
    print(f"{'signal_type':22s} {'status':8s} {'n':>5s}  {'cap p25':>8s}  {'cap p50':>8s}  "
          f"{'cap p75':>8s}  {'maxR p50':>9s}")
    types = sorted({k[0] for k in by_st_status.keys()})
    for st in types:
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            cap_p = _percentiles(by_st_status.get((st, status), []))
            max_p = _percentiles(by_st_max_r.get((st, status), []))
            if cap_p["n"] == 0:
                continue
            print(f"{st:22s} {status:8s} {cap_p['n']:>5d}  "
                  f"{_f(cap_p['p25'], 8)}  {_f(cap_p['p50'], 8)}  "
                  f"{_f(cap_p['p75'], 8)}  {_f(max_p['p50'], 9)}")
        print()

    section("🚩 Hidden potential — SL-сделки с MFE >= +1R (могли быть TSL)")
    print("Если max_R_possible >= 1.0 а исход SL — TSL должен был активироваться и спасти.\n")
    rows2 = _q(conn, f"""
        SELECT signal_type, COUNT(*) AS n,
               ROUND(AVG(max_R_possible), 2) AS avg_max_r,
               ROUND(AVG(R_multiple), 3) AS avg_r
        FROM simulated_trades
        WHERE {where} AND status='SL' AND max_R_possible >= 1.0
        GROUP BY signal_type
        ORDER BY n DESC
    """, tuple(params))
    print(f"{'signal_type':22s} {'n':>5s}  {'avg max_R':>10s}  {'avg R':>7s}")
    for r in rows2:
        print(f"{r['signal_type']:22s} {r['n']:>5d}  {r['avg_max_r']:>10.2f}  {r['avg_r']:>+7.2f}")


# ── 3. tsl_tf at close ───────────────────────────────────────────────────────

def audit_tsl_tf(conn, since):
    header("3. tsl_tf на момент закрытия — какой ТФ доминирует?")
    print("15m = реактивный (ловит шум), 1h/4h = адекватные. Cascade должен поднимать TF после TP1.\n")

    rows = _q(conn, """
        SELECT signal_type, status, tsl_tf, R_multiple, tsl_activated
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL AND tsl_tf IS NOT NULL
    """, (since,))

    bucket: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        bucket[(r["status"], r["tsl_tf"] or "?")].append(r["R_multiple"] or 0.0)

    section("Распределение tsl_tf × status (все signal_type)")
    tfs = sorted({k[1] for k in bucket.keys()})
    print(f"{'status':10s} " + " ".join(f"{tf:>10s}" for tf in tfs))
    for status in ("TSL", "SL", "TP", "EXPIRED"):
        n_row = []
        avgr_row = []
        for tf in tfs:
            items = bucket.get((status, tf), [])
            n_row.append(len(items))
            avgr_row.append(statistics.mean(items) if items else None)
        if sum(n_row) == 0:
            continue
        print(f"{status:10s} " + " ".join(
            f"{n:>4d}/{('%+.2f' % a) if a is not None else 'n/a':>5s}" for n, a in zip(n_row, avgr_row)
        ))


# ── 4. Exit R distribution for status=TSL ────────────────────────────────────

def audit_tsl_exit_r(conn, since, st_filter):
    header("4. Exit R при status=TSL — преждевременно vs нормально")
    print("Бакеты: 1.0–1.5 = TSL сорвался у активации (преждевременно),")
    print("        1.5–3.0 = норма, 3.0+ = хорошо удержали.\n")

    where = "created_at >= ? AND status='TSL' AND R_multiple IS NOT NULL"
    params = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, R_multiple, tsl_tf, max_R_possible
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    if not rows:
        print("  (нет данных)")
        return

    bucket: dict[tuple, int] = defaultdict(int)
    avg_r: dict[str, list[float]] = defaultdict(list)
    cap: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        rr = r["R_multiple"] or 0.0
        max_r = r["max_R_possible"] or 0.0
        if rr < 1.5:
            b = "1.0-1.5 (преждевр.)"
        elif rr < 3.0:
            b = "1.5-3.0 (норма)"
        elif rr < 5.0:
            b = "3.0-5.0 (хорошо)"
        else:
            b = "5.0+ (отлично)"
        bucket[(r["signal_type"], b)] += 1
        avg_r[b].append(rr)
        if max_r > 0:
            cap[b].append(rr / max_r * 100)

    section("Распределение exit R по бакетам (все signal_type)")
    print(f"{'bucket':22s} {'n':>5s}  {'avg R':>7s}  {'cap p50':>8s}")
    for b in ("1.0-1.5 (преждевр.)", "1.5-3.0 (норма)", "3.0-5.0 (хорошо)", "5.0+ (отлично)"):
        items = avg_r.get(b, [])
        if not items:
            continue
        cap_items = cap.get(b, [])
        cap_p50 = _percentiles(cap_items)["p50"] if cap_items else None
        print(f"{b:22s} {len(items):>5d}  {statistics.mean(items):>+7.2f}  {_f(cap_p50, 8) if cap_p50 else 'n/a':>8s}")

    section("Per signal_type")
    types = sorted({k[0] for k in bucket.keys()})
    print(f"{'signal_type':22s} " + " ".join(f"{b[:10]:>10s}" for b in
        ("1.0-1.5 (преждевр.)", "1.5-3.0 (норма)", "3.0-5.0 (хорошо)", "5.0+ (отлично)")))
    for st in types:
        row = []
        for b in ("1.0-1.5 (преждевр.)", "1.5-3.0 (норма)", "3.0-5.0 (хорошо)", "5.0+ (отлично)"):
            row.append(bucket.get((st, b), 0))
        print(f"{st:22s} " + " ".join(f"{n:>10d}" for n in row))


# ── 5. TSL inactive: сделка дошла до +1R, но tsl_activated=0 ─────────────────

def audit_tsl_inactive(conn, since):
    header("5. TSL не активировался при достигнутом max_R >= 1.0 — баг или замысел?")
    print("Сделки с max_R_possible >= 1.0 И tsl_activated=0 — TSL должен был включиться.\n")

    rows = _q(conn, """
        SELECT signal_type, status, COUNT(*) AS n,
               ROUND(AVG(max_R_possible), 2) AS avg_max_r,
               ROUND(AVG(R_multiple), 3) AS avg_r
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND max_R_possible >= 1.0 AND (tsl_activated=0 OR tsl_activated IS NULL)
          AND R_multiple IS NOT NULL
        GROUP BY signal_type, status
        ORDER BY n DESC
    """, (since,))
    if not rows:
        print("  (нет таких сделок — все с max_R>=1 имеют tsl_activated=1)")
        return
    print(f"{'signal_type':22s} {'status':8s} {'n':>5s}  {'avg max_R':>10s}  {'avg R':>7s}")
    for r in rows:
        print(f"{r['signal_type']:22s} {r['status']:8s} {r['n']:>5d}  "
              f"{r['avg_max_r']:>10.2f}  {r['avg_r']:>+7.2f}")


# ── 6. Coverage features_json (Слой B параллельно) ──────────────────────────

def coverage_check(conn, since):
    header("6. COVERAGE CHECK (Слой B) — валидация выводов H6")
    print("Проверка % покрытия features_json для ключевых полей. <80% = выводы шаткие.\n")

    fields = [
        "atr_trend_1h_bias",
        "mtf_direction_bias",
        "mtf_senior_matches",
        "mtf_aligned_pct",
        "mtf_bull_pct",
        "smc_trend",
        "weekly_bias",
        "wt1_value",
        "wt_zone",
        "distance_to_pivot_pct",
        "rr_at_entry",
        "btc_4h_regime",
        "entry_priority",
    ]

    rows = _q(conn, """
        SELECT created_at, features_json FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
    """, (since,))
    total = len(rows)

    # Per field: count + min(date) where present
    counters: dict[str, int] = defaultdict(int)
    first_seen: dict[str, str] = {}
    for r in rows:
        d = _safe_json(r["features_json"])
        for f in fields:
            if f in d and d[f] not in (None, "", []):
                counters[f] += 1
                if f not in first_seen or r["created_at"] < first_seen[f]:
                    first_seen[f] = r["created_at"]

    print(f"  Всего post-fix сделок: {total}\n")
    print(f"  {'field':25s} {'cov n':>7s}  {'cov %':>6s}  {'first_seen':>20s}  flag")
    for f in fields:
        n = counters.get(f, 0)
        cov_pct = n / total * 100 if total else 0
        first = first_seen.get(f, "—")
        flag = "ok" if cov_pct >= 80 else ("⚠️ <80%" if cov_pct >= 50 else "🚩 <50%")
        print(f"  {f:25s} {n:>7d}  {cov_pct:>5.1f}%  {first:>20s}  {flag}")


# ── Summary ──────────────────────────────────────────────────────────────────

def summary(conn, since):
    header(f"СВОДКА — TSL stats post-fix (с {since})")
    rows = _q(conn, """
        SELECT
          COUNT(*) AS n_total,
          SUM(CASE WHEN tsl_activated=1 THEN 1 ELSE 0 END) AS n_act,
          SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS n_tsl,
          SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) AS n_tp,
          SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS n_sl,
          SUM(CASE WHEN tsl_activated=1 AND status='SL' THEN 1 ELSE 0 END) AS n_act_sl,
          SUM(CASE WHEN max_R_possible >= 1.0 AND status='SL' THEN 1 ELSE 0 END) AS n_potential_sl
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL
    """, (since,))[0]
    print(f"  Всего закрытых:                 {rows['n_total']}")
    print(f"  TSL активирован (>= +1R):       {rows['n_act']} ({rows['n_act']/rows['n_total']*100:.1f}%)")
    print(f"  Закрыто по TSL:                 {rows['n_tsl']}")
    print(f"  Закрыто по TP:                  {rows['n_tp']}")
    print(f"  Закрыто по SL:                  {rows['n_sl']}")
    print()
    print(f"  🚩 ACT=1 → SL (потеря защиты):  {rows['n_act_sl']}")
    print(f"  🚩 SL при max_R>=1 (мог TSL):   {rows['n_potential_sl']}")
    if rows['n_act']:
        print()
        print(f"  Из активированных TSL: TSL={rows['n_tsl']} ({rows['n_tsl']/rows['n_act']*100:.0f}%), "
              f"TP={rows['n_tp']} ({rows['n_tp']/rows['n_act']*100:.0f}%), "
              f"SL={rows['n_act_sl']} ({rows['n_act_sl']/rows['n_act']*100:.0f}%)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_DEFAULT)
    parser.add_argument("--since", default=ERA_START_DEFAULT)
    parser.add_argument("--signal-type", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: db not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    try:
        summary(conn, args.since)
        coverage_check(conn, args.since)
        audit_tsl_fate(conn, args.since, args.signal_type)
        audit_captured_r(conn, args.since, args.signal_type)
        audit_tsl_tf(conn, args.since)
        audit_tsl_exit_r(conn, args.since, args.signal_type)
        audit_tsl_inactive(conn, args.since)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
