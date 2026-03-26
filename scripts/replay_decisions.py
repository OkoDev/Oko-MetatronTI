#!/usr/bin/env python3
"""
DEV-12 (Этап 8.4.8): Replay Decision Trace — анализ "что бы изменилось".

Читает decision_trace_json из закрытых сделок и анализирует:
- Какие фильтры блокировали входы (filters_applied)
- Распределение причин WATCH vs BUY/SELL
- Какие сигналы чаще всего ослаблялись MTF-множителями
- Топ символов где ML-корректировка меняла решение

Запуск:
    python scripts/replay_decisions.py
    python scripts/replay_decisions.py --days 7
    python scripts/replay_decisions.py --status SL  # только SL-сделки
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "subscriptions.db")


def load_traces(db_path: str, days: Optional[int] = None, status: Optional[str] = None) -> List[Dict]:
    """Загружает закрытые сделки с decision_trace_json."""
    conditions = ["status IN ('TP', 'SL', 'TSL')", "decision_trace_json IS NOT NULL"]
    params: List[Any] = []

    if days:
        conditions.append("created_at >= datetime('now', ?)")
        params.append(f"-{days} days")
    if status:
        conditions.append("status = ?")
        params.append(status.upper())

    where = " AND ".join(conditions)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(f"""
                SELECT id, symbol, signal_type, direction, strength, confidence,
                       status, R_multiple, regime, created_at, decision_trace_json
                FROM simulated_trades
                WHERE {where}
                ORDER BY created_at DESC
            """, params)
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                try:
                    d["_trace"] = json.loads(d["decision_trace_json"] or "{}")
                except Exception:
                    d["_trace"] = {}
                rows.append(d)
            return rows
    except sqlite3.OperationalError as e:
        if "no such column: decision_trace_json" in str(e):
            print("⚠️  Колонка decision_trace_json отсутствует в БД.")
            print("   Decision Trace (DEV-12/8.4.6) ещё не реализован для этих сделок.")
            return []
        raise


def analyze_filters(rows: List[Dict]) -> None:
    """Анализ фильтров — что чаще всего блокирует."""
    filter_counts: Counter = Counter()
    filter_by_action: Dict[str, Counter] = defaultdict(Counter)

    for row in rows:
        trace = row["_trace"]
        filters = trace.get("filters_applied", [])
        action = trace.get("final_action", "?")
        for f in filters:
            name = f.get("name", "?")
            passed = f.get("passed", True)
            if not passed:
                filter_counts[name] += 1
                filter_by_action[name][action] += 1

    print("\n🚦 ФИЛЬТРЫ (топ блокировщики):")
    if not filter_counts:
        print("  Нет данных о фильтрах (decision_trace_json пустой или старый формат)")
        return
    for name, count in filter_counts.most_common(10):
        actions_str = ", ".join(f"{a}={n}" for a, n in filter_by_action[name].items())
        print(f"  {name}: {count} блокировок [{actions_str}]")


def analyze_mtf_multipliers(rows: List[Dict]) -> None:
    """Анализ MTF-множителей — где сигналы ослаблялись."""
    reductions: List[float] = []  # насколько strength был снижен
    strong_reduction_symbols: List[str] = []

    for row in rows:
        trace = row["_trace"]
        mults = trace.get("mtf_multipliers", {})
        for sig, mult_data in mults.items():
            combined = mult_data.get("combined", 1.0) if isinstance(mult_data, dict) else 1.0
            if combined < 0.8:
                reductions.append(combined)
                if combined < 0.5:
                    strong_reduction_symbols.append(f"{row['symbol']} ({combined:.2f}×)")

    print(f"\n📡 MTF МНОЖИТЕЛИ:")
    print(f"  Сигналов с ослаблением <0.8: {len(reductions)}")
    if reductions:
        avg = sum(reductions) / len(reductions)
        print(f"  Средний коэффициент ослабления: {avg:.2f}×")
    if strong_reduction_symbols[:5]:
        print(f"  Сильное ослабление (<0.5×): {', '.join(strong_reduction_symbols[:5])}")


def analyze_ml_adjustments(rows: List[Dict]) -> None:
    """Анализ ML-корректировок confidence."""
    adjustments = []
    for row in rows:
        trace = row["_trace"]
        ml = trace.get("ml_adjustment")
        if not ml:
            continue
        orig = ml.get("original_conf", 0)
        blended = ml.get("blended", orig)
        delta = blended - orig
        adjustments.append({
            "symbol": row["symbol"],
            "orig": orig,
            "blended": blended,
            "delta": delta,
            "status": row["status"],
            "R": row["R_multiple"],
        })

    print(f"\n🤖 ML КОРРЕКТИРОВКИ CONFIDENCE:")
    if not adjustments:
        print("  Нет данных (ml_adjustment отсутствует)")
        return

    print(f"  Всего с ML: {len(adjustments)}")
    up = [a for a in adjustments if a["delta"] > 0.02]
    down = [a for a in adjustments if a["delta"] < -0.02]
    print(f"  Повышено (+2%+): {len(up)}, снижено (-2%-): {len(down)}")

    # Лучшие ML-поднятые сделки (status=TP)
    good_up = [a for a in up if a["status"] in ("TP", "TSL")]
    if good_up:
        print(f"  ML поднял → TP: {len(good_up)}/{len(up)} ({100*len(good_up)/len(up):.0f}%)")


def analyze_signal_types(rows: List[Dict]) -> None:
    """WR по signal_type из трассировок."""
    by_type: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        sig_type = row.get("signal_type") or "?"
        by_type[sig_type].append(row["status"])

    print("\n📊 WR ПО SIGNAL_TYPE (закрытые сделки):")
    for sig_type, statuses in sorted(by_type.items(), key=lambda x: -len(x[1])):
        wins = sum(1 for s in statuses if s in ("TP", "TSL"))
        total = len(statuses)
        wr = 100 * wins / total if total else 0
        print(f"  {sig_type:20} WR={wr:.0f}% ({wins}/{total})")


def analyze_regime_drift(rows: List[Dict]) -> None:
    """Анализ WR по режиму рынка."""
    by_regime: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        regime = row.get("regime") or "UNKNOWN"
        by_regime[regime].append(row["status"])

    print("\n🏛️ WR ПО РЕЖИМУ РЫНКА:")
    for regime, statuses in sorted(by_regime.items()):
        wins = sum(1 for s in statuses if s in ("TP", "TSL"))
        total = len(statuses)
        wr = 100 * wins / total if total else 0
        print(f"  {regime:15} WR={wr:.0f}% ({wins}/{total})")


def main():
    parser = argparse.ArgumentParser(description="Replay Decision Trace анализ")
    parser.add_argument("--days", type=int, default=None, help="Анализировать последние N дней")
    parser.add_argument("--status", type=str, default=None, help="Фильтр по статусу: TP / SL / TSL")
    parser.add_argument("--db", type=str, default=DB_PATH, help="Путь к БД")
    args = parser.parse_args()

    print(f"📋 REPLAY DECISION TRACE")
    print(f"БД: {args.db}")
    filter_desc = []
    if args.days:
        filter_desc.append(f"последние {args.days} дней")
    if args.status:
        filter_desc.append(f"status={args.status}")
    if filter_desc:
        print(f"Фильтры: {', '.join(filter_desc)}")
    print()

    rows = load_traces(args.db, days=args.days, status=args.status)
    if not rows:
        print("Нет данных для анализа.")
        return

    print(f"Загружено сделок с decision_trace: {len(rows)}")

    analyze_signal_types(rows)
    analyze_regime_drift(rows)
    analyze_filters(rows)
    analyze_mtf_multipliers(rows)
    analyze_ml_adjustments(rows)

    print("\n✅ Анализ завершён")


if __name__ == "__main__":
    main()
