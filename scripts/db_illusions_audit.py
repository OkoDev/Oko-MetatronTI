"""DB-ILLUSIONS: аудит достоверности R_multiple, MFE, метрик.

Проверяет гипотезу Claude: «R_multiple ХАОТИЧЕН, метрики завышены».

Usage: python scripts/db_illusions_audit.py
"""
import sqlite3, json
from pathlib import Path
import numpy as np

DB = Path(__file__).resolve().parent.parent / "subscriptions.db"


def _r_calc(direction, entry, exit_p, sl):
    """Вычисляет R = (exit-entry)/(entry-SL) для LONG, обратное для SHORT."""
    if not all(v and v > 0 for v in [entry, exit_p, sl]):
        return None
    if direction == "LONG":
        if entry <= sl: return None
        return (exit_p - entry) / (entry - sl)
    else:
        if sl <= entry: return None
        return (entry - exit_p) / (sl - entry)


def run():
    db = sqlite3.connect(str(DB))
    db.row_factory = sqlite3.Row

    # ── 1. R_multiple vs формула ───────────────────────────────
    print("=" * 65)
    print("  1. R_multiple БД vs (exit-entry)/(entry-SL)")
    print("=" * 65)

    rows = db.execute("""
        SELECT id, symbol, signal_type, direction, status,
               entry_price, exit_price, stop_loss, original_sl,
               R_multiple, profit_pct
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND entry_price > 0 AND exit_price > 0
          AND (stop_loss > 0 OR original_sl > 0)
          AND R_multiple IS NOT NULL
    """).fetchall()

    print(f"  Всего закрытых с ценой и SL: {len(rows)}")

    matches = 0
    mismatches = []
    for r in rows:
        sl = r["original_sl"] if r["original_sl"] else r["stop_loss"]
        calc = _r_calc(r["direction"], r["entry_price"], r["exit_price"], sl)
        if calc is None:
            continue
        db_r = r["R_multiple"]
        delta = abs(calc - db_r)
        if delta < 0.01:
            matches += 1
        else:
            mismatches.append({
                "id": r["id"], "sym": r["symbol"], "dir": r["direction"],
                "signal": r["signal_type"], "status": r["status"],
                "db_R": round(db_r, 3), "calc_R": round(calc, 3),
                "delta": round(delta, 3),
                "entry": r["entry_price"], "exit": r["exit_price"],
                "sl": round(sl, 6)
            })

    pct_ok = matches / len(rows) * 100 if rows else 0
    print(f"  Совпало (±0.01): {matches} ({pct_ok:.1f}%)")
    print(f"  Расходится:      {len(mismatches)} ({100-pct_ok:.1f}%)")

    if mismatches:
        # Show worst offenders
        mismatches.sort(key=lambda x: abs(x["delta"]), reverse=True)
        print(f"\n  Топ-10 расхождений:")
        print(f"  {'id':>5s} {'sym':<10s} {'dir':>5s} {'status':>7s} {'db_R':>8s} {'calc_R':>8s} {'delta':>8s}")
        for m in mismatches[:10]:
            print(f"  {m['id']:>5d} {m['sym']:<10s} {m['dir']:>5s} {m['status']:>7s} {m['db_R']:>8.2f} {m['calc_R']:>8.2f} {m['delta']:>8.2f}")

        # Distribution
        deltas = [abs(m["delta"]) for m in mismatches]
        print(f"\n  Распределение |delta|: med={np.median(deltas):.3f} mean={np.mean(deltas):.3f} max={max(deltas):.1f}")
        print(f"  delta>0.5: {sum(1 for d in deltas if d>0.5)}, delta>5: {sum(1 for d in deltas if d>5)}")

        # Impact on sumR
        sum_db = sum(m["db_R"] for m in mismatches)
        sum_calc = sum(m["calc_R"] for m in mismatches)
        print(f"\n  Sum R mismatch: DB={sum_db:+.1f} vs calc={sum_calc:+.1f} (d={sum_db-sum_calc:+.1f})")

        # By signal_type
        by_sig = {}
        for m in mismatches:
            s = m["signal"] or "?"
            if s not in by_sig:
                by_sig[s] = {"n": 0, "db": 0, "calc": 0}
            by_sig[s]["n"] += 1
            by_sig[s]["db"] += m["db_R"]
            by_sig[s]["calc"] += m["calc_R"]
        print(f"\n  По signal_type (расходящиеся):")
        for s, v in sorted(by_sig.items(), key=lambda x: -x[1]["n"]):
            d = v["db"] - v["calc"]
            print(f"    {s:25s} n={v['n']:>4d} db={v['db']:+.1f} calc={v['calc']:+.1f} D={d:+.1f}")

    # ── 2. R_multiple > max_R_possible ──────────────────────────
    print(f"\n{'=' * 65}")
    print(f"  2. R_multiple > max_R_possible (фантомный R)")
    print(f"{'=' * 65}")

    phantom = db.execute("""
        SELECT COUNT(*) n, SUM(R_multiple - max_R_possible) sum_excess,
               AVG(R_multiple - max_R_possible) avg_excess
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED')
          AND R_multiple IS NOT NULL AND max_R_possible IS NOT NULL
          AND R_multiple > max_R_possible
    """).fetchone()
    print(f"  Сделок: {phantom['n']}, фантомный R: {phantom['sum_excess']:+.1f}, средний: {phantom['avg_excess']:+.3f}")

    # ── 3. Реальный avgR/WR (очищенный) ─────────────────────────
    print(f"\n{'=' * 65}")
    print(f"  3. Реальный vs бумажный avgR/WR")
    print(f"{'=' * 65}")

    # Paper
    paper = db.execute("""
        SELECT COUNT(*) n, AVG(R_multiple) avgR, SUM(R_multiple) sumR,
               100.0*COUNT(CASE WHEN R_multiple>0 THEN 1 END)/COUNT(*) WR
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple IS NOT NULL
    """).fetchone()
    print(f"  БУМАЖНЫЙ:  n={paper['n']} avgR={paper['avgR']:+.3f} sumR={paper['sumR']:+.1f} WR={paper['WR']:.1f}%")

    # Cleaned: fix R for mismatches, EXPIRED→-1, R>MFE→clamp
    # Estimate: for each mismatch, use calc_R; for EXPIRED, use -1
    expired_r0 = db.execute("""
        SELECT COUNT(*) FROM simulated_trades
        WHERE status='EXPIRED' AND R_multiple=0
    """).fetchone()[0]

    # Total adjustment estimate
    sum_mismatch_delta = sum(m["calc_R"] - m["db_R"] for m in mismatches) if mismatches else 0
    expired_adj = -expired_r0  # each R=0 EXPIRED → -1
    phantom_adj = -(phantom["sum_excess"] or 0)  # remove phantom excess

    total_adj = sum_mismatch_delta + expired_adj + phantom_adj
    clean_sumR = (paper["sumR"] or 0) + total_adj

    print(f"  ОЧИЩЕННЫЙ: n={paper['n']} sumR≈{clean_sumR:+.1f} (D={total_adj:+.1f})")
    print(f"    Коррекция mismatch: {sum_mismatch_delta:+.1f}")
    print(f"    Коррекция EXPIRED→-1: {expired_adj:+.0f}")
    print(f"    Коррекция фантом R>MFE: {phantom_adj:+.1f}")

    # ── 4. zombie/orphan ────────────────────────────────────────
    print(f"\n{'=' * 65}")
    print(f"  4. Zombie / Orphan / R=0")
    print(f"{'=' * 65}")

    zombies = db.execute("""
        SELECT COUNT(*) FROM simulated_trades
        WHERE status IN ('SL','TSL','TP','EXPIRED')
          AND exchange_order_id IS NOT NULL AND exchange_order_id!='SIM' AND exchange_order_id!=''
    """).fetchone()[0]
    print(f"  Всего VST закрытых: {zombies}")

    r_zero = db.execute("SELECT COUNT(*) FROM simulated_trades WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple=0").fetchone()[0]
    print(f"  R=0 всего: {r_zero}")
    print(f"  Из них EXPIRED: {expired_r0}")

    # By signal_type for R=0
    r0_by_sig = db.execute("""
        SELECT signal_type, COUNT(*) n FROM simulated_trades
        WHERE status IN ('TP','SL','TSL','EXPIRED') AND R_multiple=0
        GROUP BY signal_type ORDER BY n DESC LIMIT 10
    """).fetchall()
    print(f"  R=0 по сигналам:")
    for r in r0_by_sig:
        print(f"    {r['signal_type'] or '?':25s} {r['n']:>4d}")

    # ── 5. Вердикт ──────────────────────────────────────────────
    print(f"\n{'=' * 65}")
    print(f"  5. ВЕРДИКТ")
    print(f"{'=' * 65}")

    if paper["sumR"] and paper["sumR"] != 0:
        overstatement = abs(total_adj) / abs(paper["sumR"]) * 100
        print(f"  R_multiple совпадает с формулой: {pct_ok:.1f}%")
        print(f"  Расходится: {len(mismatches)} сделок ({100-pct_ok:.1f}%)")
        print(f"  Суммарная коррекция: {total_adj:+.1f}R")
        print(f"  Завышение метрик: ~{overstatement:.0f}% от sumR")
        print(f"  Бумажный sumR: {paper['sumR']:+.1f} → Очищенный: {clean_sumR:+.1f}")
    print(f"  Фантом R>MFE: {phantom['n']} сделок, +{phantom['sum_excess']:+.1f}R")
    print(f"  EXPIRED R=0: {expired_r0} сделок (реально ~{expired_r0}R потерь)")

    db.close()


if __name__ == "__main__":
    run()
