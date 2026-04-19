"""
DEV-178: Data Integrity Audit — разделение сделок по эрам качества данных.

Эры:
  pre_157   < 2026-03-15           — до DEV-157 (min_sl_dist), micro-SL артефакты
  post_157  2026-03-15..2026-04-14 — после DEV-157, но TSL ещё сломан (3 бага)
  post_fix  >= 2026-04-15          — после DEV-174 TSL fix + DEV-175 slippage fix (чистые данные)

Режимы запуска:
  python scripts/data_integrity_audit.py          — только отчёт в консоль
  python scripts/data_integrity_audit.py --tag    — пометить существующие сделки (data_era в features_json)
  python scripts/data_integrity_audit.py --export — сохранить CSV отчёт в backtest_reports/
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime
from typing import List, Optional

DB_PATH = os.environ.get("DB_PATH", "subscriptions.db")

# ── Границы эр ──────────────────────────────────────────────────────────────
ERA_BOUNDARIES = {
    "pre_157":  (None,           "2026-03-15"),   # < 2026-03-15
    "post_157": ("2026-03-15",   "2026-04-15"),   # 2026-03-15 .. 2026-04-15
    "post_fix": ("2026-04-15",   None),           # >= 2026-04-15 (чистые данные)
}

MICRO_SL_PCT = 0.1  # порог "micro-SL" — SL ближе 0.1% к entry считается артефактом


# ── SQL helpers ──────────────────────────────────────────────────────────────

def era_where(era: str) -> str:
    lo, hi = ERA_BOUNDARIES[era]
    parts = []
    if lo:
        parts.append(f"created_at >= '{lo}'")
    if hi:
        parts.append(f"created_at < '{hi}'")
    return " AND ".join(parts) if parts else "1=1"


def is_micro_sl(row) -> bool:
    try:
        ep = float(row["entry_price"] or 0)
        sl = float(row["stop_loss"] or 0)
        if ep <= 0 or sl <= 0:
            return False
        return abs(ep - sl) / ep * 100 < MICRO_SL_PCT
    except Exception:
        return False


# ── Статистика ───────────────────────────────────────────────────────────────

def compute_stats(rs: List[float]) -> dict:
    n = len(rs)
    if n == 0:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    wr = len(wins) / n * 100
    avg_r = sum(rs) / n
    sorted_rs = sorted(rs)
    median_r = sorted_rs[n // 2]
    std_r = math.sqrt(sum((r - avg_r) ** 2 for r in rs) / n) if n > 1 else 0
    sharpe = avg_r / std_r * math.sqrt(n) if std_r > 0 else 0
    max_dd = 0.0
    peak = 0.0
    cumulative = 0.0
    for r in rs:
        cumulative += r
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return {
        "n": n,
        "wr_pct": round(wr, 1),
        "avg_r": round(avg_r, 3),
        "median_r": round(median_r, 3),
        "sharpe": round(sharpe, 2),
        "max_dd_r": round(max_dd, 2),
        "wins": len(wins),
    }


def fmt(stats: dict) -> str:
    if stats["n"] == 0:
        return "n=0"
    return (
        f"n={stats['n']:4d}  WR={stats['wr_pct']:5.1f}%  "
        f"avgR={stats['avg_r']:+.3f}  medR={stats['median_r']:+.3f}  "
        f"Sharpe={stats['sharpe']:+.2f}  MaxDD={stats['max_dd_r']:.1f}R"
    )


# ── Основной аудит ───────────────────────────────────────────────────────────

def run_audit(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    print("=" * 70)
    print(f"DEV-178 Data Integrity Audit  [{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}]")
    print(f"DB: {DB_PATH}")
    print("=" * 70)

    total = conn.execute("SELECT COUNT(*) FROM simulated_trades").fetchone()[0]
    open_cnt = conn.execute("SELECT COUNT(*) FROM simulated_trades WHERE status='OPEN'").fetchone()[0]
    print(f"\nВсего сделок: {total}  (открытых: {open_cnt}, закрытых: {total - open_cnt})\n")

    for era, (lo, hi) in ERA_BOUNDARIES.items():
        where = era_where(era)
        rows = conn.execute(
            f"SELECT * FROM simulated_trades WHERE ({where}) AND status != 'OPEN'"
        ).fetchall()

        rs_all = [float(r["R_multiple"]) for r in rows if r["R_multiple"] is not None]
        rs_clean = [
            float(r["R_multiple"])
            for r in rows
            if r["R_multiple"] is not None and not is_micro_sl(r)
        ]
        micro_sl_count = sum(1 for r in rows if is_micro_sl(r))

        lo_str = lo or "начало"
        hi_str = hi or "сейчас"
        print(f"─── Era: {era}  ({lo_str} → {hi_str}) ───")
        print(f"  Все:         {fmt(compute_stats(rs_all))}")
        print(f"  Без micro-SL:{fmt(compute_stats(rs_clean))}")
        print(f"  micro-SL (< {MICRO_SL_PCT}%): {micro_sl_count} сделок")

        # По типам сигналов (без micro-SL)
        by_type: dict[str, list] = {}
        for r in rows:
            if r["R_multiple"] is None or is_micro_sl(r):
                continue
            t = r["signal_type"] or "unknown"
            by_type.setdefault(t, []).append(float(r["R_multiple"]))

        if by_type:
            print("  По типам (без micro-SL):")
            for sig_type, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
                if len(rs) < 5:
                    continue
                s = compute_stats(rs)
                print(f"    {sig_type:22s}  n={s['n']:4d}  WR={s['wr_pct']:5.1f}%  avgR={s['avg_r']:+.3f}")
        print()

    # Сводка по micro-SL
    print("─── Суммарно: micro-SL артефакты ───")
    micro_rows = conn.execute("""
        SELECT * FROM simulated_trades
        WHERE entry_price > 0 AND stop_loss > 0
        AND ABS(entry_price - stop_loss)/entry_price*100 < ?
        AND status != 'OPEN'
    """, (MICRO_SL_PCT,)).fetchall()
    rs_micro = [float(r["R_multiple"]) for r in micro_rows if r["R_multiple"] is not None]
    print(f"  {fmt(compute_stats(rs_micro))}")
    print(f"  → Эти сделки ИСКАЖАЮТ avgR. Без них post_157 avgR ещё хуже.\n")

    # Рекомендация для ML
    post_fix_clean = conn.execute("""
        SELECT COUNT(*) FROM simulated_trades
        WHERE created_at >= '2026-04-15'
        AND status != 'OPEN'
        AND (entry_price = 0 OR stop_loss = 0
             OR ABS(entry_price - stop_loss)/entry_price*100 >= ?)
    """, (MICRO_SL_PCT,)).fetchone()[0]
    print("─── Рекомендации для ML ───")
    print(f"  Чистых сделок для обучения (post_fix без micro-SL): {post_fix_clean}")
    print(f"  Минимум для OutcomePredictor: 200 сделок.")
    if post_fix_clean < 200:
        print(f"  ⚠ Недостаточно — продолжаем накапливать. Дата готовности: ~28.04.")
    else:
        print(f"  ✅ Достаточно — переобучить OutcomePredictor на data_era=post_fix.")


# ── Backfill data_era ────────────────────────────────────────────────────────

def backfill_era_tags(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """
    Помечает существующие сделки полем data_era в features_json.
    Правила:
      - is_micro_sl → data_era = 'micro_sl_artifact'
      - created_at < 2026-03-15 → data_era = 'pre_157'
      - created_at < 2026-04-15 → data_era = 'post_157'
      - иначе                  → data_era = 'post_fix'
    Не перезаписывает уже размеченные (data_era уже есть).
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, created_at, entry_price, stop_loss, features_json FROM simulated_trades").fetchall()

    updated = 0
    skipped_already = 0
    for row in rows:
        fj_raw = row["features_json"]
        fj: dict = {}
        if fj_raw:
            try:
                fj = json.loads(fj_raw)
            except Exception:
                pass

        if "data_era" in fj:
            skipped_already += 1
            continue

        created = row["created_at"] or ""
        if is_micro_sl(row):
            era = "micro_sl_artifact"
        elif created < "2026-03-15":
            era = "pre_157"
        elif created < "2026-04-15":
            era = "post_157"
        else:
            era = "post_fix"

        fj["data_era"] = era
        new_fj = json.dumps(fj, ensure_ascii=False)

        if not dry_run:
            conn.execute(
                "UPDATE simulated_trades SET features_json = ? WHERE id = ?",
                (new_fj, row["id"]),
            )
        updated += 1

    if not dry_run:
        conn.commit()

    print(f"\n─── Backfill data_era ───")
    print(f"  Размечено:           {updated}")
    print(f"  Уже были размечены:  {skipped_already}")
    if dry_run:
        print("  (dry-run — изменения НЕ применены)")
    else:
        print("  ✅ Изменения применены в БД")


# ── Export CSV ───────────────────────────────────────────────────────────────

def export_csv(conn: sqlite3.Connection) -> None:
    import csv
    os.makedirs("backtest_reports", exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")
    path = f"backtest_reports/data_integrity_{ts}.csv"

    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, symbol, signal_type, direction, created_at, status,
               entry_price, stop_loss, R_multiple,
               ABS(entry_price - stop_loss)/entry_price*100 as sl_dist_pct,
               features_json
        FROM simulated_trades
        WHERE status != 'OPEN'
        ORDER BY created_at
    """).fetchall()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "symbol", "signal_type", "direction", "created_at",
                         "status", "entry_price", "stop_loss", "R_multiple",
                         "sl_dist_pct", "is_micro_sl", "data_era"])
        for r in rows:
            fj: dict = {}
            if r["features_json"]:
                try:
                    fj = json.loads(r["features_json"])
                except Exception:
                    pass
            sl_dist = r["sl_dist_pct"]
            micro = "1" if (sl_dist is not None and sl_dist < MICRO_SL_PCT) else "0"
            era = fj.get("data_era", "")
            writer.writerow([r["id"], r["symbol"], r["signal_type"], r["direction"],
                             r["created_at"], r["status"], r["entry_price"],
                             r["stop_loss"], r["R_multiple"],
                             f"{sl_dist:.4f}" if sl_dist else "",
                             micro, era])

    print(f"\n✅ CSV сохранён: {path}  ({len(rows)} строк)")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DEV-178: Data Integrity Audit")
    parser.add_argument("--tag",    action="store_true", help="Пометить сделки data_era в features_json")
    parser.add_argument("--dry-run",action="store_true", help="Показать что будет помечено, без записи")
    parser.add_argument("--export", action="store_true", help="Экспорт в CSV")
    parser.add_argument("--db",     default=DB_PATH,     help=f"Путь к БД (default: {DB_PATH})")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, timeout=30)
    conn.execute("PRAGMA busy_timeout=10000")

    run_audit(conn)

    if args.tag or args.dry_run:
        backfill_era_tags(conn, dry_run=args.dry_run)

    if args.export:
        export_csv(conn)

    conn.close()


if __name__ == "__main__":
    main()
