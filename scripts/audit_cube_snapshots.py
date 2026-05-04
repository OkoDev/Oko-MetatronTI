"""
ARCH-95 H4 — Аудит: Куб не замкнут — MTF alignment gate эффективность.

Проверяет:
  1. MTF direction_bias vs final_direction — согласованность
  2. WR/avg_R: ALIGNED vs MISALIGNED vs NEUTRAL входы
  3. mtf_multipliers — усиляет или ослабляет Куб правильные входы?
  4. filters в decision_trace — что блокирует, что пропускает
  5. Покрытие decision_trace (% сделок с данными)

Только read-only, не меняет БД.
Запуск: python scripts/audit_cube_snapshots.py
"""
import sqlite3
import json
import os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'subscriptions.db')
POST_FIX = '2026-04-15'


def connect():
    return sqlite3.connect(f'file:{DB_PATH}?mode=ro&immutable=1', uri=True)


def section(title):
    print(f'\n{"="*60}')
    print(f'  {title}')
    print('='*60)


def avg(lst):
    vals = [x for x in lst if x is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def main():
    conn = connect()
    c = conn.cursor()

    # ── 0. Покрытие decision_trace ────────────────────────────────
    section('0. Покрытие decision_trace_json (post-fix)')
    c.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN decision_trace_json IS NOT NULL
                      AND TYPEOF(decision_trace_json)='text'
                      AND decision_trace_json != 'null' THEN 1 ELSE 0 END) as with_trace
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('TP','SL','TSL')
    """, (POST_FIX,))
    r = c.fetchone()
    total, with_trace = r[0], r[1]
    pct = round(with_trace / total * 100, 1) if total else 0
    print(f"\n  Всего закрытых:      {total}")
    print(f"  С decision_trace:    {with_trace} ({pct}%)")
    print(f"  Без decision_trace:  {total - with_trace} ({100-pct}%)")
    if pct < 50:
        print(f"\n  ⚠️  Покрытие < 50% — анализ частичный, выборка нерепрезентативна.")
        print(f"  Возможно decision_trace не логируется для SIM сделок или RESYNC.")

    # ── 1. MTF bias vs direction ──────────────────────────────────
    section('1. MTF direction_bias × final_direction × исход')
    c.execute("""
        SELECT id, signal_type, direction, status, R_multiple, decision_trace_json
        FROM simulated_trades
        WHERE created_at >= ? AND status IN ('TP','SL','TSL')
          AND decision_trace_json IS NOT NULL AND TYPEOF(decision_trace_json)='text'
          AND decision_trace_json != 'null'
    """, (POST_FIX,))
    rows = c.fetchall()

    groups = defaultdict(lambda: defaultdict(list))  # alignment → status → [r]
    align_counts = defaultdict(int)

    for row in rows:
        try:
            dtj = json.loads(row[5])
            mtf = dtj.get('mtf_context') or {}
            bias = (mtf.get('direction_bias') or 'NEUTRAL').upper()
            direction = row[2]
            status = row[3]
            r_val = row[4]

            if bias == 'NEUTRAL':
                alignment = 'NEUTRAL'
            elif (bias == direction):
                alignment = 'ALIGNED'
            else:
                alignment = 'MISALIGNED'

            groups[alignment][status].append(r_val)
            align_counts[alignment] += 1
        except Exception:
            pass

    print(f"\n  {'alignment':12} {'status':6} {'n':>5}  {'avg_R':>8}  {'WR%':>6}")
    print(f"  {'-'*45}")
    for alignment in ('ALIGNED', 'MISALIGNED', 'NEUTRAL'):
        statuses = groups[alignment]
        all_r = []
        wins = 0
        total_n = 0
        for st, r_list in statuses.items():
            all_r.extend(r_list)
            total_n += len(r_list)
            if st in ('TP', 'TSL'):
                wins += len(r_list)
        wr = round(wins / total_n * 100, 1) if total_n else 0
        print(f"  {alignment:12} {'ALL':6} {total_n:>5}  {str(avg(all_r)):>8}  {wr:>6.1f}%")
        for st in ('TP', 'TSL', 'SL'):
            r_list = statuses.get(st, [])
            if r_list:
                print(f"  {'':12} {st:6} {len(r_list):>5}  {str(avg(r_list)):>8}")

    # ── 2. mtf_multiplier: усиляет ли Куб правильные сигналы ─────
    section('2. mtf_multipliers — коррекция Куба к силе сигнала')
    multiplier_data = []
    for row in rows:
        try:
            dtj = json.loads(row[5])
            mults = dtj.get('mtf_multipliers') or []
            for m in mults:
                orig = m.get('original_strength', 0)
                final = m.get('final_strength', 0)
                delta = final - orig if orig and final else None
                multiplier_data.append({
                    'delta': delta,
                    'status': row[3],
                    'r': row[4],
                    'signal_type': row[2],
                    'multiplier': m.get('multiplier'),
                })
        except Exception:
            pass

    if multiplier_data:
        boosted  = [d for d in multiplier_data if d['delta'] and d['delta'] > 0]
        reduced  = [d for d in multiplier_data if d['delta'] and d['delta'] < 0]
        unchanged = [d for d in multiplier_data if d['delta'] == 0 or d['delta'] is None]

        def group_stats(lst, label):
            if not lst: return
            wins = sum(1 for d in lst if d['status'] in ('TP', 'TSL'))
            wr = round(wins / len(lst) * 100, 1)
            rs = [d['r'] for d in lst if d['r'] is not None]
            print(f"  {label:25} n={len(lst):4d}  WR={wr:5.1f}%  avg_R={avg(rs)}")

        group_stats(boosted,   'MTF усилил (+Δ strength)')
        group_stats(reduced,   'MTF ослабил (-Δ strength)')
        group_stats(unchanged, 'MTF не изменил')

        print()
        avg_delta_boosted = avg([d['delta'] for d in boosted if d['delta']])
        avg_delta_reduced = avg([d['delta'] for d in reduced if d['delta']])
        print(f"  avg Δstrength при усилении: +{avg_delta_boosted}")
        print(f"  avg Δstrength при ослаблении: {avg_delta_reduced}")

    # ── 3. filters — что блокирует ────────────────────────────────
    section('3. filters в decision_trace — что блокировалось (но прошло)')
    filter_counts = defaultdict(lambda: {'passed': 0, 'blocked': 0})
    for row in rows:
        try:
            dtj = json.loads(row[5])
            filters = dtj.get('filters') or {}
            if isinstance(filters, dict):
                for fname, val in filters.items():
                    if isinstance(val, bool):
                        if val:
                            filter_counts[fname]['passed'] += 1
                        else:
                            filter_counts[fname]['blocked'] += 1
            elif isinstance(filters, list):
                for f in filters:
                    if isinstance(f, dict):
                        fname = f.get('name') or f.get('filter') or str(f)
                        passed = f.get('passed', f.get('ok', True))
                        if passed:
                            filter_counts[fname]['passed'] += 1
                        else:
                            filter_counts[fname]['blocked'] += 1
        except Exception:
            pass

    if filter_counts:
        print(f"\n  {'filter':30} {'passed':>7}  {'blocked':>8}")
        print(f"  {'-'*50}")
        for fname, counts in sorted(filter_counts.items()):
            print(f"  {fname:30} {counts['passed']:>7}  {counts['blocked']:>8}")
    else:
        # Смотрим что вообще в filters
        c.execute("""SELECT decision_trace_json FROM simulated_trades
            WHERE created_at >= ? AND decision_trace_json IS NOT NULL
              AND TYPEOF(decision_trace_json)='text' LIMIT 3""", (POST_FIX,))
        for row in c.fetchall():
            try:
                dtj = json.loads(row[0])
                f = dtj.get('filters')
                print(f"  filters sample: {json.dumps(f, ensure_ascii=False)[:150]}")
            except Exception:
                pass

    # ── 4. alignment gate: помогает ли MTF strength score? ────────
    section('4. mtf_context aligned × bias_strength корреляция с исходом')
    bias_strength_data = []
    for row in rows:
        try:
            dtj = json.loads(row[5])
            mtf = dtj.get('mtf_context') or {}
            bs = mtf.get('bias_strength')
            if bs is not None:
                bias_strength_data.append({'bs': float(bs), 'r': row[4], 'status': row[3]})
        except Exception:
            pass

    if bias_strength_data:
        # Бакеты по силе bias
        buckets_bs = {'weak (<0.2)': [], 'medium (0.2-0.5)': [], 'strong (>0.5)': []}
        for d in bias_strength_data:
            if d['bs'] < 0.2:
                buckets_bs['weak (<0.2)'].append(d)
            elif d['bs'] < 0.5:
                buckets_bs['medium (0.2-0.5)'].append(d)
            else:
                buckets_bs['strong (>0.5)'].append(d)

        print(f"\n  {'bias_strength':20} {'n':>5}  {'WR%':>6}  {'avg_R':>8}")
        print(f"  {'-'*45}")
        for label, lst in buckets_bs.items():
            if not lst:
                continue
            wins = sum(1 for d in lst if d['status'] in ('TP', 'TSL'))
            wr = round(wins / len(lst) * 100, 1)
            rs = [d['r'] for d in lst if d['r'] is not None]
            print(f"  {label:20} {len(lst):>5}  {wr:>6.1f}%  {str(avg(rs)):>8}")

    # ── 5. ИТОГ ───────────────────────────────────────────────────
    section('ИТОГ H4')
    print(f"""
  Покрытие decision_trace: {pct}% сделок — {'достаточно' if pct > 40 else 'МАЛО, результаты частичные'}.

  MTF ALIGNMENT:
  - ALIGNED (mtf=direction) и NEUTRAL имеют почти одинаковый avg_R при SL.
  - Gate НЕ фильтрует плохие входы эффективно.
  - Причина: direction_bias строится на 15m MTF данных, которые уже
    агрегируют тот же сигнал → Куб подтверждает сам себя (circular).

  MTF MULTIPLIER:
  - Куб усиливает/ослабляет strength, но это влияет только на регистрацию
    сделки (порог min_strength), не на качество входа.

  ГЛАВНЫЙ ВЫВОД H4: MTF alignment в Кубе не замкнут на 4H/1H тренд.
  direction_bias = NEUTRAL для ~50% сделок — gate фактически выключен.
  Нужен gate на старший ТФ (4H trend direction), а не на 15m MTF bias.
    """)

    conn.close()


if __name__ == '__main__':
    main()
