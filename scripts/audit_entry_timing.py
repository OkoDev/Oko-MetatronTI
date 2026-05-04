#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCH-95 H1+H2: Аудит таймингов входа и дистанции SL.

Read-only. Только post-fix эра (created_at >= 2026-04-15).

H1 (поздние входы) — косвенные прокси из features_json:
  - distance_to_pivot_pct: для pivot_reversal — насколько entry далёк от уровня
  - wt1_value at entry: для wt_signal — глубина зоны на момент входа
  - rr_at_entry: реальный R:R на момент регистрации
  - mtf_bias_strength: согласованность MTF
Сравнение распределений по статусу (SL vs TP) — если "поздние" чаще закрываются SL,
значит вход реально опоздал.

H2 (тесный SL) — sl_dist_pct = |entry - sl| / entry * 100
Сравнение медиан по (signal_type, status). Если SL-исходы имеют медиану sl_dist_pct
меньше TP-исходов — SL поставлен в шум, цена выбивает на нормальном откате.

Запуск:
  python scripts/audit_entry_timing.py
  python scripts/audit_entry_timing.py --signal-type pivot_reversal
  python scripts/audit_entry_timing.py --since 2026-04-20
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import statistics
from collections import defaultdict
from typing import Any

DB_DEFAULT = "subscriptions.db"
ERA_START_DEFAULT = "2026-04-15"


def _q(c: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    c.row_factory = sqlite3.Row
    return c.execute(sql, params).fetchall()


def _fmt_pct(v: float | None, w: int = 6) -> str:
    if v is None:
        return " " * w
    return f"{v:>{w}.2f}"


def _percentiles(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"n": 0, "p25": None, "p50": None, "p75": None, "mean": None}
    s = sorted(vals)
    n = len(s)
    def pct(p: float) -> float:
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return s[idx]
    return {
        "n": n,
        "p25": pct(0.25),
        "p50": pct(0.50),
        "p75": pct(0.75),
        "mean": statistics.mean(s),
    }


def header(text: str) -> None:
    print()
    print("=" * 100)
    print(text)
    print("=" * 100)


def section(text: str) -> None:
    print()
    print("-" * 100)
    print(text)
    print("-" * 100)


# ── H2: SL distance distribution by (signal_type, status) ─────────────────────

def audit_h2_sl_distance(conn: sqlite3.Connection, since: str, st_filter: str | None) -> None:
    header("H2 — SL distance: медиана |entry-sl|/entry*100 по (signal_type, status)")
    print("Гипотеза: SL у проигрышных сделок ближе чем у выигрышных → SL ловит шум, не движение.")

    where = "created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL"
    params: list[Any] = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, status, entry_price, stop_loss, R_multiple, sl_source
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    bucket: dict[tuple[str, str], list[float]] = defaultdict(list)
    bucket_r: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        ep, sl = r["entry_price"], r["stop_loss"]
        if not ep or not sl or ep <= 0:
            continue
        d_pct = abs(ep - sl) / ep * 100.0
        bucket[(r["signal_type"], r["status"])].append(d_pct)
        bucket_r[(r["signal_type"], r["status"])].append(r["R_multiple"] or 0.0)

    # Группируем по signal_type
    types = sorted({k[0] for k in bucket.keys()})
    print(f"\n{'signal_type':22s} {'status':8s} {'n':>5s}  {'p25':>6s}  {'p50':>6s}  {'p75':>6s}  {'mean':>6s}  {'avgR':>7s}")
    for st in types:
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            key = (st, status)
            if key not in bucket:
                continue
            p = _percentiles(bucket[key])
            avgr = statistics.mean(bucket_r[key]) if bucket_r[key] else 0.0
            print(f"{st:22s} {status:8s} {p['n']:>5d}  "
                  f"{_fmt_pct(p['p25'])}  {_fmt_pct(p['p50'])}  "
                  f"{_fmt_pct(p['p75'])}  {_fmt_pct(p['mean'])}  "
                  f"{avgr:>+7.2f}")
        print()

    # Флаг: median(SL) < median(TP)?
    section("ФЛАГ H2: signal_type где median(sl_dist% при SL) < median при TP — SL слишком тесный")
    flagged = []
    for st in types:
        sl_med = _percentiles(bucket.get((st, "SL"), [])).get("p50")
        tp_med = _percentiles(bucket.get((st, "TP"), [])).get("p50")
        tsl_med = _percentiles(bucket.get((st, "TSL"), [])).get("p50")
        wins_med = None
        wins = bucket.get((st, "TP"), []) + bucket.get((st, "TSL"), [])
        if wins:
            wins_med = _percentiles(wins)["p50"]
        if sl_med is not None and wins_med is not None:
            ratio = sl_med / wins_med if wins_med > 0 else 0
            flag = "🚩 ТЕСНЫЙ" if ratio < 0.85 else ("⚠️  близко" if ratio < 0.95 else "ok")
            flagged.append((st, sl_med, wins_med, ratio, flag))
            print(f"  {st:22s}  SL_p50={sl_med:5.2f}%  WIN_p50={wins_med:5.2f}%  "
                  f"ratio={ratio:.2f}  {flag}")
    if not flagged:
        print("  (нет данных для сравнения)")


# ── H1: pivot_reversal — distance_to_pivot at entry by status ────────────────

def _safe_json(s: str | None) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {}


def audit_h1_pivot_distance(conn: sqlite3.Connection, since: str) -> None:
    header("H1 (PROXY): pivot_reversal — distance_to_pivot_pct на момент входа")
    print("Гипотеза: поздние входы — entry сделан когда цена уже отошла от уровня.")
    print("           SL-исходы должны иметь БОЛЬШЕЕ distance_to_pivot_pct чем TP-исходы.\n")

    rows = _q(conn, """
        SELECT status, R_multiple, features_json
        FROM simulated_trades
        WHERE signal_type='pivot_reversal' AND created_at >= ?
          AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL
    """, (since,))

    by_status: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        d = fj.get("distance_to_pivot_pct")
        if d is None:
            continue
        try:
            by_status[r["status"]].append(float(d))
        except Exception:
            pass

    print(f"{'status':10s} {'n':>5s}  {'p25':>6s}  {'p50':>6s}  {'p75':>6s}  {'mean':>6s}")
    for status in ("SL", "TSL", "TP", "EXPIRED"):
        p = _percentiles(by_status.get(status, []))
        if p["n"] == 0:
            continue
        print(f"{status:10s} {p['n']:>5d}  "
              f"{_fmt_pct(p['p25'])}  {_fmt_pct(p['p50'])}  "
              f"{_fmt_pct(p['p75'])}  {_fmt_pct(p['mean'])}")

    sl = by_status.get("SL", [])
    wins = by_status.get("TP", []) + by_status.get("TSL", [])
    if sl and wins:
        sl_med = _percentiles(sl)["p50"]
        win_med = _percentiles(wins)["p50"]
        delta = sl_med - win_med
        flag = "🚩 ПОЗДНИЙ ВХОД" if delta > 0.05 else ("⚠️  тенденция" if delta > 0 else "ok")
        print(f"\n  ИТОГ: SL median={sl_med:.3f}%  WIN median={win_med:.3f}%  "
              f"Δ={delta:+.3f}%  {flag}")


# ── H1: wt_signal / wt_b_signal — wt1 zone depth at entry by status ──────────

def audit_h1_wt_zone(conn: sqlite3.Connection, since: str) -> None:
    header("H1 (PROXY): wt_signal — wt1_value на момент входа")
    print("Гипотеза: для LONG нужен wt1 < -60 (OS). Если на момент входа wt1 уже выше -50 →")
    print("           зона перепроданности уже отыграна, входим поздно.\n")

    rows = _q(conn, """
        SELECT direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE signal_type IN ('wt_signal','wt_b_signal') AND created_at >= ?
          AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL
    """, (since,))

    by_dir_status: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        wt1 = fj.get("wt1_value")
        if wt1 is None:
            wt1 = fj.get("wt1")
        if wt1 is None:
            continue
        try:
            by_dir_status[(r["direction"], r["status"])].append(float(wt1))
        except Exception:
            pass

    for direction in ("LONG", "SHORT"):
        print(f"\n  {direction}:")
        print(f"    {'status':10s} {'n':>5s}  {'p25':>6s}  {'p50':>6s}  {'p75':>6s}  {'mean':>6s}")
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            p = _percentiles(by_dir_status.get((direction, status), []))
            if p["n"] == 0:
                continue
            print(f"    {status:10s} {p['n']:>5d}  "
                  f"{_fmt_pct(p['p25'])}  {_fmt_pct(p['p50'])}  "
                  f"{_fmt_pct(p['p75'])}  {_fmt_pct(p['mean'])}")

    # Гайд: для LONG лучше wt1 ближе к -80, для SHORT ближе к +80
    print("\n  Эталон: LONG entry должен быть в OS (wt1<-60, идеально <-70). SHORT: wt1>+60.")


# ── H1: rr_at_entry distribution by status ───────────────────────────────────

def audit_h1_rr_at_entry(conn: sqlite3.Connection, since: str, st_filter: str | None) -> None:
    header("H1 (PROXY): rr_at_entry — реальный R:R на момент регистрации")
    print("Если rr_at_entry < 2.0 для большинства SL-исходов — TP не дотянулся, тесный SL/далёкий TP.\n")

    where = "created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL"
    params: list[Any] = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, status, features_json
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    by_st_status: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        rr = fj.get("rr_at_entry")
        if rr is None:
            continue
        try:
            by_st_status[(r["signal_type"], r["status"])].append(float(rr))
        except Exception:
            pass

    types = sorted({k[0] for k in by_st_status.keys()})
    if not types:
        print("  (rr_at_entry не найден в features_json — поле не пишется)")
        return
    print(f"{'signal_type':22s} {'status':8s} {'n':>5s}  {'p25':>5s}  {'p50':>5s}  {'p75':>5s}")
    for st in types:
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            p = _percentiles(by_st_status.get((st, status), []))
            if p["n"] == 0:
                continue
            print(f"{st:22s} {status:8s} {p['n']:>5d}  "
                  f"{_fmt_pct(p['p25'], 5)}  {_fmt_pct(p['p50'], 5)}  {_fmt_pct(p['p75'], 5)}")
        print()


# ── H1: MTF alignment correlation with outcome ───────────────────────────────

def audit_h1_mtf_alignment(conn: sqlite3.Connection, since: str) -> None:
    header("H1 (PROXY): MTF bias на входе — согласованы ли ТФ с направлением сделки?")
    print("Если SL-сделки имеют слабый mtf_bias_strength или mtf_bias=NEUTRAL — вход без MTF подтверждения.\n")

    rows = _q(conn, """
        SELECT direction, status, R_multiple, signal_type, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    counters: dict[tuple[str, str, str], int] = defaultdict(int)
    avg_r: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for r in rows:
        fj = _safe_json(r["features_json"])
        mtf = (fj.get("mtf_bias") or "").upper()
        if not mtf:
            continue
        direction = (r["direction"] or "").upper()
        # Aligned: LONG+BULL or SHORT+BEAR
        if (direction == "LONG" and mtf in ("BULL", "LONG")) or \
           (direction == "SHORT" and mtf in ("BEAR", "SHORT")):
            align = "ALIGNED"
        elif mtf in ("NEUTRAL", "MIXED"):
            align = "NEUTRAL"
        else:
            align = "AGAINST"
        counters[(align, r["signal_type"], r["status"])] += 1
        avg_r[(align, r["signal_type"], r["status"])].append(r["R_multiple"] or 0.0)

    section("Сводка по alignment × status (все signal_type)")
    by_align: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (align, _st, status), rs in avg_r.items():
        by_align[align][status].extend(rs)

    print(f"{'alignment':10s} {'status':8s} {'n':>5s}  {'avgR':>7s}")
    for align in ("ALIGNED", "NEUTRAL", "AGAINST"):
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            rs = by_align[align].get(status, [])
            if not rs:
                continue
            print(f"{align:10s} {status:8s} {len(rs):>5d}  {statistics.mean(rs):>+7.2f}")

    # Per signal_type: WR by alignment
    section("WR по alignment (TP+TSL / total) × signal_type")
    types = sorted({k[1] for k in counters.keys()})
    print(f"{'signal_type':22s} {'aligned WR':>12s}  {'neutral WR':>12s}  {'against WR':>12s}")
    for st in types:
        row_parts = [f"{st:22s}"]
        for align in ("ALIGNED", "NEUTRAL", "AGAINST"):
            wins = counters.get((align, st, "TP"), 0) + counters.get((align, st, "TSL"), 0)
            total = sum(counters.get((align, st, s), 0) for s in ("SL","TSL","TP","EXPIRED"))
            if total < 5:
                row_parts.append(f"{'(n<5)':>12s}")
            else:
                row_parts.append(f"{wins/total*100:>10.1f}% (n={total})")
        print(f"{row_parts[0]} {row_parts[1]:>12s}  {row_parts[2]:>12s}  {row_parts[3]:>12s}")


# ── Summary ──────────────────────────────────────────────────────────────────

def summary(conn: sqlite3.Connection, since: str) -> None:
    header("СВОДКА — закрытые сделки post-fix (с {since})".format(since=since))
    rows = _q(conn, """
        SELECT signal_type, COUNT(*) AS n,
               SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS n_sl,
               SUM(CASE WHEN status='TSL' THEN 1 ELSE 0 END) AS n_tsl,
               SUM(CASE WHEN status='TP' THEN 1 ELSE 0 END) AS n_tp,
               SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) AS n_exp,
               ROUND(AVG(R_multiple),3) AS avg_r
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED') AND R_multiple IS NOT NULL
        GROUP BY signal_type
        ORDER BY n DESC
    """, (since,))
    print(f"{'signal_type':22s} {'n':>5s}  {'SL':>5s}  {'TSL':>5s}  {'TP':>4s}  {'EXP':>4s}  "
          f"{'WR%':>6s}  {'avgR':>7s}")
    for r in rows:
        wr = (r["n_tp"] + r["n_tsl"]) / r["n"] * 100 if r["n"] else 0
        print(f"{r['signal_type']:22s} {r['n']:>5d}  {r['n_sl']:>5d}  {r['n_tsl']:>5d}  "
              f"{r['n_tp']:>4d}  {r['n_exp']:>4d}  {wr:>5.1f}%  {r['avg_r']:>+7.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_DEFAULT)
    parser.add_argument("--since", default=ERA_START_DEFAULT,
                        help="created_at >= <since>; default 2026-04-15 (post-fix era)")
    parser.add_argument("--signal-type", default=None,
                        help="фильтр по signal_type (необязательно)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: db not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    try:
        summary(conn, args.since)
        audit_h2_sl_distance(conn, args.since, args.signal_type)
        audit_h1_pivot_distance(conn, args.since)
        audit_h1_wt_zone(conn, args.since)
        audit_h1_rr_at_entry(conn, args.since, args.signal_type)
        audit_h1_mtf_alignment(conn, args.since)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
