#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strip-down эксперимент: сравнение main vs strip-бота.

Читает обе БД (main = ./subscriptions.db, strip = ../crypto_volume_bot_strip/subscriptions.db)
и выводит side-by-side метрики:
  - WR (effective_status DEV-190)
  - avgR
  - catastrophic R<-3 rate
  - per-regime / per-signal_type breakdown
  - sample overlap (одинаковые символы)

Запуск:
  python scripts/compare_main_vs_strip.py
  python scripts/compare_main_vs_strip.py --since "2026-04-28T00:00:00"
  python scripts/compare_main_vs_strip.py --strip-db /path/to/strip.db
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from typing import Any

DEFAULT_MAIN_DB = "subscriptions.db"
DEFAULT_STRIP_DB = "../crypto_volume_bot_strip/subscriptions.db"
DEFAULT_SINCE = "2026-04-27T17:00:00"  # после restart-2 / strip launch

# Effective status (DEV-190) — точная формула production
WIN_SQL = """
CASE
    WHEN status = 'TP' THEN 1
    WHEN status = 'TSL' THEN 1
    WHEN status = 'SL' AND tsl_activated = 1 AND R_multiple > 0.10 THEN 1
    ELSE 0
END
"""


def section(title: str) -> None:
    print()
    print("=" * 100)
    print(title)
    print("=" * 100)


def header(title: str) -> None:
    print()
    print("-" * 100)
    print(title)
    print("-" * 100)


def open_db(path: str) -> sqlite3.Connection | None:
    if not os.path.exists(path):
        return None
    return sqlite3.connect(path)


def fetch_summary(conn: sqlite3.Connection, since: str) -> dict[str, Any]:
    """Базовые метрики: n / wins / WR / avgR / catastrophic / open."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
          COUNT(*) AS n,
          SUM({WIN_SQL}) AS wins,
          ROUND(AVG(R_multiple), 3) AS avg_r,
          SUM(CASE WHEN R_multiple < -3 THEN 1 ELSE 0 END) AS catastrophic,
          SUM(CASE WHEN R_multiple > 3 THEN 1 ELSE 0 END) AS big_win,
          ROUND(SUM(R_multiple), 1) AS sum_r
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL') AND R_multiple IS NOT NULL
          AND created_at >= ?
    """, (since,))
    row = cur.fetchone()
    n, wins, avg_r, cat, big, sum_r = row
    open_n = cur.execute(
        "SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN' AND created_at >= ?",
        (since,)
    ).fetchone()[0]
    wr = wins / n * 100 if n else 0
    cat_pct = cat / n * 100 if n else 0
    return {
        "n_closed": n or 0,
        "n_open": open_n,
        "wins": wins or 0,
        "wr": wr,
        "avg_r": avg_r,
        "sum_r": sum_r,
        "catastrophic": cat or 0,
        "catastrophic_pct": cat_pct,
        "big_win": big or 0,
    }


def fetch_per_signal(conn: sqlite3.Connection, since: str) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(f"""
        SELECT signal_type,
               COUNT(*) AS n,
               SUM({WIN_SQL}) AS wins,
               ROUND(AVG(R_multiple), 3) AS ar,
               ROUND(SUM(R_multiple), 1) AS sum_r
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL') AND R_multiple IS NOT NULL
          AND created_at >= ?
        GROUP BY signal_type
        ORDER BY n DESC
    """, (since,))
    return cur.fetchall()


def fetch_per_regime(conn: sqlite3.Connection, since: str) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(f"""
        SELECT COALESCE(regime, 'NONE') AS reg,
               COUNT(*) AS n,
               SUM({WIN_SQL}) AS wins,
               ROUND(AVG(R_multiple), 3) AS ar
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL') AND R_multiple IS NOT NULL
          AND created_at >= ?
        GROUP BY reg
        ORDER BY n DESC
    """, (since,))
    return cur.fetchall()


def fetch_symbols(conn: sqlite3.Connection, since: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT symbol FROM simulated_trades "
        "WHERE created_at >= ? AND status IN ('TP','SL','TSL','OPEN')",
        (since,)
    )
    return {r[0] for r in cur.fetchall()}


def fetch_daily(conn: sqlite3.Connection, since: str) -> list[tuple]:
    cur = conn.cursor()
    cur.execute(f"""
        SELECT date(closed_at) AS d,
               COUNT(*) AS n,
               SUM({WIN_SQL}) AS wins,
               ROUND(AVG(R_multiple), 3) AS ar
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL') AND R_multiple IS NOT NULL
          AND closed_at >= ?
        GROUP BY d
        ORDER BY d
    """, (since,))
    return cur.fetchall()


def print_summary(label: str, s: dict) -> None:
    print(f"  [{label}] closed={s['n_closed']}  open={s['n_open']}  WR={s['wr']:.1f}%  "
          f"avgR={s['avg_r']}  sumR={s['sum_r']}  catastr={s['catastrophic']} ({s['catastrophic_pct']:.1f}%)  "
          f"big_win={s['big_win']}")


def print_side_by_side(left_label: str, left_data: list, right_label: str, right_data: list,
                        key_idx: int = 0) -> None:
    """Two columns side-by-side by key (index 0)."""
    left_d = {row[key_idx]: row for row in left_data}
    right_d = {row[key_idx]: row for row in right_data}
    keys = sorted(set(left_d.keys()) | set(right_d.keys()))

    print(f"  {'key':22s} | {left_label:>30s} | {right_label:>30s}")
    print(f"  {'-'*22} | {'-'*30} | {'-'*30}")
    for k in keys:
        L = left_d.get(k)
        R = right_d.get(k)
        L_str = "—"
        R_str = "—"
        if L is not None:
            n, wins = L[1] or 0, L[2] or 0
            wr = wins / n * 100 if n else 0
            L_str = f"n={n:>4d} WR={wr:>5.1f}% avgR={L[3]}"
        if R is not None:
            n, wins = R[1] or 0, R[2] or 0
            wr = wins / n * 100 if n else 0
            R_str = f"n={n:>4d} WR={wr:>5.1f}% avgR={R[3]}"
        print(f"  {str(k):22s} | {L_str:>30s} | {R_str:>30s}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-db", default=DEFAULT_MAIN_DB)
    parser.add_argument("--strip-db", default=DEFAULT_STRIP_DB)
    parser.add_argument("--since", default=DEFAULT_SINCE,
                        help="Only consider trades created after this timestamp")
    args = parser.parse_args()

    conn_main = open_db(args.main_db)
    conn_strip = open_db(args.strip_db)

    if conn_main is None:
        print(f"ERROR: main DB not found: {args.main_db}")
        sys.exit(1)
    if conn_strip is None:
        print(f"ERROR: strip DB not found: {args.strip_db}")
        print("       (Запусти strip-бота сначала — см. docs/STRIP_DOWN_SETUP.md)")
        sys.exit(1)

    print(f"Main DB:  {args.main_db}")
    print(f"Strip DB: {args.strip_db}")
    print(f"Since:    {args.since}")

    # ── Summary ────────────────────────────────────────────────────────────
    section("SUMMARY")
    s_main = fetch_summary(conn_main, args.since)
    s_strip = fetch_summary(conn_strip, args.since)
    print_summary("MAIN ", s_main)
    print_summary("STRIP", s_strip)

    print()
    print("  ДЕЛЬТА (strip - main):")
    if s_main['n_closed'] > 0 and s_strip['n_closed'] > 0:
        d_wr = s_strip['wr'] - s_main['wr']
        d_ar = (s_strip['avg_r'] or 0) - (s_main['avg_r'] or 0)
        d_cat = s_strip['catastrophic_pct'] - s_main['catastrophic_pct']
        flag_wr = "✓" if d_wr >= 5 else ("⚠️ " if d_wr >= 0 else "🚩")
        flag_ar = "✓" if d_ar >= 0.1 else ("⚠️ " if d_ar >= 0 else "🚩")
        flag_cat = "✓" if d_cat <= 0 else ("⚠️ " if d_cat <= 1 else "🚩")
        print(f"    ΔWR    = {d_wr:+.1f}pp  {flag_wr}")
        print(f"    ΔavgR  = {d_ar:+.3f}   {flag_ar}")
        print(f"    Δcatastr%= {d_cat:+.1f}pp {flag_cat}")
    else:
        print("    (мало данных в одной из БД)")

    # ── Per signal_type ─────────────────────────────────────────────────────
    section("PER SIGNAL_TYPE")
    main_sig = fetch_per_signal(conn_main, args.since)
    strip_sig = fetch_per_signal(conn_strip, args.since)
    print_side_by_side("MAIN", main_sig, "STRIP", strip_sig)

    # ── Per regime ──────────────────────────────────────────────────────────
    section("PER REGIME")
    main_reg = fetch_per_regime(conn_main, args.since)
    strip_reg = fetch_per_regime(conn_strip, args.since)
    print_side_by_side("MAIN", main_reg, "STRIP", strip_reg)

    # ── Symbol overlap ──────────────────────────────────────────────────────
    section("SYMBOL OVERLAP")
    main_syms = fetch_symbols(conn_main, args.since)
    strip_syms = fetch_symbols(conn_strip, args.since)
    overlap = main_syms & strip_syms
    main_only = main_syms - strip_syms
    strip_only = strip_syms - main_syms
    print(f"  MAIN unique symbols:  {len(main_syms)}")
    print(f"  STRIP unique symbols: {len(strip_syms)}")
    print(f"  OVERLAP:              {len(overlap)}")
    print(f"  MAIN-only:            {len(main_only)}  → {sorted(main_only)[:10]}{'...' if len(main_only)>10 else ''}")
    print(f"  STRIP-only:           {len(strip_only)} → {sorted(strip_only)[:10]}{'...' if len(strip_only)>10 else ''}")

    if not overlap:
        print("  ⚠️  Нет пересечений символов — выборки несравнимы")
    elif len(overlap) < 0.5 * min(len(main_syms), len(strip_syms)):
        print("  ⚠️  Малое пересечение — возможно стратегии видят разные пары")

    # ── Daily evolution ─────────────────────────────────────────────────────
    section("DAILY EVOLUTION")
    main_daily = fetch_daily(conn_main, args.since)
    strip_daily = fetch_daily(conn_strip, args.since)
    main_d = {r[0]: r for r in main_daily}
    strip_d = {r[0]: r for r in strip_daily}
    days = sorted(set(main_d.keys()) | set(strip_d.keys()))
    print(f"  {'date':12s} | {'MAIN':>30s} | {'STRIP':>30s}")
    print(f"  {'-'*12} | {'-'*30} | {'-'*30}")
    for day in days:
        M = main_d.get(day)
        S = strip_d.get(day)
        M_str = "—"
        S_str = "—"
        if M is not None:
            n, w = M[1], M[2] or 0
            M_str = f"n={n:>4d} WR={w/n*100:>5.1f}% avgR={M[3]}"
        if S is not None:
            n, w = S[1], S[2] or 0
            S_str = f"n={n:>4d} WR={w/n*100:>5.1f}% avgR={S[3]}"
        print(f"  {day:12s} | {M_str:>30s} | {S_str:>30s}")

    # ── Verdict ─────────────────────────────────────────────────────────────
    section("VERDICT")
    if s_main['n_closed'] < 30 or s_strip['n_closed'] < 30:
        print("  ⚠️  Менее 30 сделок в одной из БД — статзначимости нет.")
        print("      Подождать накопления (3-4 дня).")
    else:
        d_wr = s_strip['wr'] - s_main['wr']
        d_ar = (s_strip['avg_r'] or 0) - (s_main['avg_r'] or 0)
        if d_wr >= 5 and d_ar >= 0.1:
            print("  ✓ STRIP ≥ MAIN — patches вредны, применить strip-config в production")
        elif d_wr <= -5 and d_ar <= -0.1:
            print("  🚩 STRIP < MAIN — какие-то filters работают, копать что именно")
        else:
            print("  ≈ STRIP ≈ MAIN — patches нейтральны, можно упростить production до strip уровня")

    conn_main.close()
    conn_strip.close()


if __name__ == "__main__":
    main()
