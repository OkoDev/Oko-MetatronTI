#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARCH-95 H5+H6: Аудит slippage detector→entry и глубокий MTF alignment.

Read-only. Только post-fix эра (created_at >= 2026-04-15).

H5 (slippage detector→entry):
  - entry_price (signal-time close 15m) vs actual_entry_price (биржа fill)
  - Распределение slippage % per signal_type, direction, status
  - Корреляция slippage vs R_multiple
  - Адверс-slippage: LONG with positive slippage (entry хуже) или SHORT с negative

H6 (MTF alignment — глубоко):
  - mtf_aligned_pct (% TF в одном направлении): бакеты vs WR/avgR
  - mtf_senior_matches (0..3): матчи 1h/4h/1d → vs WR/avgR
  - mtf_direction_bias × trade.direction → ALIGNED/NEUTRAL/AGAINST
  - atr_trend_1h_bias × direction
  - Двойной gate: MTF + atr_trend (если оба согласны → должно быть лучше)

Запуск:
  python scripts/audit_slippage_mtf.py
  python scripts/audit_slippage_mtf.py --signal-type pivot_reversal
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
    return f"{v:>{w}.3f}"


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


# ── H5: SLIPPAGE detector vs actual ──────────────────────────────────────────

def audit_h5_slippage(conn, since, st_filter):
    header("H5 — Slippage: entry_price (signal-time) vs actual_entry_price (биржа fill)")
    print("Гипотеза: между генерацией сигнала и реальным fill цена сдвигается.")
    print("           Адверс-slippage = LONG fill ВЫШЕ signal price / SHORT fill НИЖЕ.")
    print("           Если адверс-slippage коррелирует с SL — значит лаг детектор→ордер критичен.\n")

    where = """created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
               AND R_multiple IS NOT NULL
               AND actual_entry_price IS NOT NULL AND entry_price IS NOT NULL
               AND entry_price > 0"""
    params = [since]
    if st_filter:
        where += " AND signal_type = ?"
        params.append(st_filter)

    rows = _q(conn, f"""
        SELECT signal_type, direction, status, R_multiple,
               entry_price, actual_entry_price, stop_loss
        FROM simulated_trades
        WHERE {where}
    """, tuple(params))

    print(f"Покрытие: {len(rows)} сделок post-fix с actual_entry_price (≈20% всех)\n")

    if not rows:
        print("  (нет данных)")
        return

    # signed slippage:
    #  LONG: actual > entry → ПЛОХО (+slippage)  → sign = +1 если actual > entry
    #  SHORT: actual < entry → ПЛОХО                → sign = +1 если actual < entry
    by_st_status: dict[tuple, list[float]] = defaultdict(list)
    by_st_R: dict[tuple, list[tuple]] = defaultdict(list)  # (slippage, R)

    for r in rows:
        ep, ap = r["entry_price"], r["actual_entry_price"]
        if not ep or ep <= 0 or not ap:
            continue
        d = (r["direction"] or "").upper()
        # raw slippage % (signed by adverse direction)
        if d == "LONG":
            slip = (ap - ep) / ep * 100.0    # +adverse
        else:
            slip = (ep - ap) / ep * 100.0
        by_st_status[(r["signal_type"], r["status"])].append(slip)
        by_st_R[r["signal_type"]].append((slip, r["R_multiple"] or 0.0))

    section("Adverse slippage по (signal_type × status)")
    print("(+ = вход хуже теоретического; - = лучше)\n")
    print(f"{'signal_type':22s} {'status':8s} {'n':>5s}  {'p25':>6s}  {'p50':>6s}  {'p75':>6s}  {'mean':>6s}")
    types = sorted({k[0] for k in by_st_status.keys()})
    for st in types:
        for status in ("SL", "TSL", "TP", "EXPIRED"):
            v = by_st_status.get((st, status), [])
            p = _percentiles(v)
            if p["n"] == 0:
                continue
            print(f"{st:22s} {status:8s} {p['n']:>5d}  "
                  f"{_f(p['p25'])}  {_f(p['p50'])}  "
                  f"{_f(p['p75'])}  {_f(p['mean'])}")
        print()

    section("Slippage vs исход — дельта медиан (SL_p50 - WIN_p50)")
    print("Положительная дельта = SL-сделки имели бóльшую adverse slippage → лаг = причина SL\n")
    for st in types:
        sl = by_st_status.get((st, "SL"), [])
        wins = by_st_status.get((st, "TP"), []) + by_st_status.get((st, "TSL"), [])
        if len(sl) >= 5 and len(wins) >= 3:
            sl_p50 = _percentiles(sl)["p50"]
            win_p50 = _percentiles(wins)["p50"]
            delta = sl_p50 - win_p50
            flag = "🚩 СИГНАЛ" if delta > 0.05 else ("⚠️" if delta > 0 else "ok")
            print(f"  {st:22s}  SL p50={sl_p50:+.3f}%  WIN p50={win_p50:+.3f}%  "
                  f"Δ={delta:+.3f}%  {flag}")
        elif len(sl) >= 1:
            sl_p50 = _percentiles(sl)["p50"]
            print(f"  {st:22s}  SL p50={sl_p50:+.3f}%  (мало WIN: n={len(wins)})")

    section("Slippage VS SL distance — критичность")
    print("Если adverse slippage > 30% от SL distance — он съедает запас.\n")
    for r in rows:
        pass  # placeholder (per-signal_type stat in next block)

    by_st_eat: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        ep, ap, sl_price = r["entry_price"], r["actual_entry_price"], r["stop_loss"]
        if not ep or ep <= 0 or not ap or not sl_price:
            continue
        d = (r["direction"] or "").upper()
        if d == "LONG":
            slip = (ap - ep) / ep * 100.0
        else:
            slip = (ep - ap) / ep * 100.0
        sl_dist_pct = abs(ep - sl_price) / ep * 100.0
        if sl_dist_pct <= 0:
            continue
        eat_ratio = slip / sl_dist_pct * 100.0  # % of SL eaten by adverse slippage
        by_st_eat[r["signal_type"]].append(eat_ratio)

    print(f"{'signal_type':22s} {'n':>5s}  {'p25%':>7s}  {'p50%':>7s}  {'p75%':>7s}  {'mean%':>7s}")
    for st in sorted(by_st_eat.keys()):
        p = _percentiles(by_st_eat[st])
        print(f"{st:22s} {p['n']:>5d}  "
              f"{_f(p['p25'], 7)}  {_f(p['p50'], 7)}  "
              f"{_f(p['p75'], 7)}  {_f(p['mean'], 7)}")


# ── H6: MTF alignment deep ───────────────────────────────────────────────────

def audit_h6_mtf_aligned_pct(conn, since):
    header("H6 — MTF aligned_pct: % ТФ в одном направлении на момент входа")
    print("Эталон: для качественного MTF-входа нужен aligned_pct ≥ 65%.")
    print("Гипотеза: SL-сделки имеют меньший aligned_pct → MTF-фильтр пропускает несогласованных.\n")

    rows = _q(conn, """
        SELECT signal_type, direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    by_bucket: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        ap = fj.get("mtf_aligned_pct")
        if ap is None:
            continue
        try:
            ap = float(ap)
        except Exception:
            continue
        if ap < 50:
            bucket = "<50%"
        elif ap < 65:
            bucket = "50-65%"
        elif ap < 75:
            bucket = "65-75%"
        elif ap < 85:
            bucket = "75-85%"
        else:
            bucket = "≥85%"
        by_bucket[bucket].append((r["status"], r["R_multiple"] or 0.0))

    print(f"{'bucket':10s} {'n':>5s}  {'WR%':>6s}  {'avgR':>7s}  {'avgR(SL)':>9s}")
    for bucket in ("<50%", "50-65%", "65-75%", "75-85%", "≥85%"):
        items = by_bucket.get(bucket, [])
        if not items:
            continue
        wins = [r for s, r in items if s in ("TP", "TSL")]
        all_r = [r for _, r in items]
        sl_r = [r for s, r in items if s == "SL"]
        wr = len(wins) / len(items) * 100 if items else 0
        avgR = statistics.mean(all_r) if all_r else 0
        avgR_sl = statistics.mean(sl_r) if sl_r else 0
        print(f"{bucket:10s} {len(items):>5d}  {wr:>5.1f}%  {avgR:>+7.2f}  {avgR_sl:>+9.2f}")


def audit_h6_senior_matches(conn, since):
    header("H6 — MTF senior_matches: согласие 1h/4h/1d (0..3)")
    print("Эталон: senior_matches ≥ 2 (минимум 2 из 3 старших ТФ согласны с направлением).")
    print("Если 0/1 не блокируют сделку — MTF gate пропускает мусор.\n")

    rows = _q(conn, """
        SELECT direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    by_match: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        m = fj.get("mtf_senior_matches")
        if m is None:
            continue
        try:
            m = int(m)
        except Exception:
            continue
        by_match[m].append((r["status"], r["R_multiple"] or 0.0))

    print(f"{'matches':10s} {'n':>5s}  {'WR%':>6s}  {'avgR':>7s}  {'avgR(SL)':>9s}")
    for m in sorted(by_match.keys()):
        items = by_match[m]
        wins = [r for s, r in items if s in ("TP", "TSL")]
        all_r = [r for _, r in items]
        sl_r = [r for s, r in items if s == "SL"]
        wr = len(wins) / len(items) * 100 if items else 0
        avgR = statistics.mean(all_r) if all_r else 0
        avgR_sl = statistics.mean(sl_r) if sl_r else 0
        print(f"  {m}/3      {len(items):>5d}  {wr:>5.1f}%  {avgR:>+7.2f}  {avgR_sl:>+9.2f}")


def audit_h6_direction_bias(conn, since):
    header("H6 — mtf_direction_bias × direction: ALIGNED / NEUTRAL / AGAINST")
    print("Per-signal_type разрез: даёт ли alignment реальное преимущество.\n")

    rows = _q(conn, """
        SELECT signal_type, direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    bucket: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        bias = (fj.get("mtf_direction_bias") or "").upper()
        if not bias:
            continue
        d = (r["direction"] or "").upper()
        if (d == "LONG" and bias in ("BULL", "LONG", "UP")) or \
           (d == "SHORT" and bias in ("BEAR", "SHORT", "DOWN")):
            align = "ALIGNED"
        elif bias in ("NEUTRAL", "MIXED", ""):
            align = "NEUTRAL"
        else:
            align = "AGAINST"
        bucket[(r["signal_type"], align)].append((r["status"], r["R_multiple"] or 0.0))

    types = sorted({k[0] for k in bucket.keys()})
    print(f"{'signal_type':22s} {'align':10s}  {'n':>5s}  {'WR%':>6s}  {'avgR':>7s}")
    for st in types:
        for align in ("ALIGNED", "NEUTRAL", "AGAINST"):
            items = bucket.get((st, align), [])
            if not items:
                continue
            wins = [r for s, r in items if s in ("TP", "TSL")]
            all_r = [r for _, r in items]
            wr = len(wins) / len(items) * 100
            avgR = statistics.mean(all_r) if all_r else 0
            print(f"{st:22s} {align:10s}  {len(items):>5d}  {wr:>5.1f}%  {avgR:>+7.2f}")
        print()


def audit_h6_atr_trend_1h(conn, since):
    header("H6 — atr_trend_1h_bias × direction: независимый gate (не из Куба)")
    print("Гипотеза H4: MTF gate из Куба — circular logic. atr_trend_1h_bias — независимый.\n")

    rows = _q(conn, """
        SELECT signal_type, direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    bucket: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        atr_bias = (fj.get("atr_trend_1h_bias") or "").upper()
        if not atr_bias:
            continue
        d = (r["direction"] or "").upper()
        if (d == "LONG" and atr_bias in ("BULL", "UP", "LONG")) or \
           (d == "SHORT" and atr_bias in ("BEAR", "DOWN", "SHORT")):
            align = "ALIGNED"
        elif atr_bias in ("NEUTRAL", "FLAT", ""):
            align = "NEUTRAL"
        else:
            align = "AGAINST"
        bucket[align].append((r["status"], r["R_multiple"] or 0.0))

    print(f"{'atr_1h':10s}  {'n':>5s}  {'WR%':>6s}  {'avgR':>7s}")
    for align in ("ALIGNED", "NEUTRAL", "AGAINST"):
        items = bucket.get(align, [])
        if not items:
            continue
        wins = [r for s, r in items if s in ("TP", "TSL")]
        all_r = [r for _, r in items]
        wr = len(wins) / len(items) * 100
        avgR = statistics.mean(all_r) if all_r else 0
        print(f"{align:10s}  {len(items):>5d}  {wr:>5.1f}%  {avgR:>+7.2f}")


def audit_h6_double_gate(conn, since):
    header("H6 — Двойной gate: MTF aligned + atr_trend_1h aligned")
    print("Если MTF AND atr_trend_1h оба ALIGNED — должно дать заметно лучший WR.\n")

    rows = _q(conn, """
        SELECT direction, status, R_multiple, features_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('SL','TSL','TP','EXPIRED')
          AND R_multiple IS NOT NULL
    """, (since,))

    bucket: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        fj = _safe_json(r["features_json"])
        bias = (fj.get("mtf_direction_bias") or "").upper()
        atr = (fj.get("atr_trend_1h_bias") or "").upper()
        d = (r["direction"] or "").upper()
        if not bias or not atr:
            continue

        def matches(b, side):
            if side == "LONG":
                return b in ("BULL", "LONG", "UP")
            if side == "SHORT":
                return b in ("BEAR", "SHORT", "DOWN")
            return False

        mtf_ok = matches(bias, d)
        atr_ok = matches(atr, d)

        if mtf_ok and atr_ok:
            tag = "BOTH_ALIGNED"
        elif mtf_ok or atr_ok:
            tag = "ONE_ALIGNED"
        else:
            tag = "NONE_ALIGNED"
        bucket[tag].append((r["status"], r["R_multiple"] or 0.0))

    print(f"{'gate':16s}  {'n':>5s}  {'WR%':>6s}  {'avgR':>7s}  {'avgR(SL)':>9s}")
    for tag in ("BOTH_ALIGNED", "ONE_ALIGNED", "NONE_ALIGNED"):
        items = bucket.get(tag, [])
        if not items:
            continue
        wins = [r for s, r in items if s in ("TP", "TSL")]
        all_r = [r for _, r in items]
        sl_r = [r for s, r in items if s == "SL"]
        wr = len(wins) / len(items) * 100
        avgR = statistics.mean(all_r) if all_r else 0
        avgR_sl = statistics.mean(sl_r) if sl_r else 0
        print(f"{tag:16s}  {len(items):>5d}  {wr:>5.1f}%  {avgR:>+7.2f}  {avgR_sl:>+9.2f}")


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
        audit_h5_slippage(conn, args.since, args.signal_type)
        audit_h6_mtf_aligned_pct(conn, args.since)
        audit_h6_senior_matches(conn, args.since)
        audit_h6_direction_bias(conn, args.since)
        audit_h6_atr_trend_1h(conn, args.since)
        audit_h6_double_gate(conn, args.since)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
