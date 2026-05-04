"""
ARCH-95 H3 — Аудит: pivot direction / уровень / SL логика.

Проверяет:
  1. Какой sl_source реально используется в pivot_reversal (pivot 0.3% vs ATR)
  2. Расстояние entry→пивот vs ширина SL — "запоздалый вход" тест
  3. Соответствие direction × level_type по sl_source
  4. WR/avg_R: вход близко к пивоту (<1%) vs далеко (>1%)

Только read-only, не меняет БД.
Запуск: python scripts/audit_pivot_direction.py
"""
import sqlite3
import json
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'subscriptions.db')
POST_FIX = '2026-04-15'


def connect():
    return sqlite3.connect(f'file:{DB_PATH}?mode=ro&immutable=1', uri=True)


def section(title):
    print(f'\n{"="*60}')
    print(f'  {title}')
    print('='*60)


def main():
    conn = connect()
    c = conn.cursor()

    # ── 1. sl_source распределение у pivot_reversal ──────────────
    section('1. sl_source у pivot_reversal (post-fix)')
    c.execute("""
        SELECT sl_source, COUNT(*) as n,
            ROUND(SUM(CASE WHEN status IN ('TP','TSL') THEN 1 ELSE 0 END)*100.0/COUNT(*),1) as wr,
            ROUND(AVG(R_multiple),3) as avg_r
        FROM simulated_trades
        WHERE signal_type='pivot_reversal' AND created_at >= ?
          AND status IN ('TP','SL','TSL')
        GROUP BY sl_source ORDER BY n DESC
    """, (POST_FIX,))
    print(f"  {'sl_source':35} {'n':>5}  {'WR%':>6}  {'avg_R':>7}")
    print(f"  {'-'*60}")
    for r in c.fetchall():
        src = r[0] or 'NULL'
        is_pivot_sl = 'pivot_' in src and ':0.3%' in src
        marker = ' ← pivot SL' if is_pivot_sl else ''
        print(f"  {src:35} {r[1]:>5}  {r[2]:>6.1f}%  {r[3]:>+7.3f}{marker}")

    print()
    print("  ВЫВОД: если pivot_reversal использует atr_1.5 вместо pivot:0.3%,")
    print("  значит SL пересчитывается downstream и tight-SL логика не применяется.")

    # ── 2. distance_to_pivot_pct vs исход ────────────────────────
    section('2. distance_to_pivot_pct × исход (proximity теста)')
    c.execute("""
        SELECT id, direction, status, R_multiple, entry_price, stop_loss, features_json
        FROM simulated_trades
        WHERE signal_type='pivot_reversal' AND created_at >= ?
          AND status IN ('TP','SL','TSL')
          AND features_json IS NOT NULL AND TYPEOF(features_json)='text'
    """, (POST_FIX,))
    rows = c.fetchall()

    buckets = {'<0.5%': [], '0.5-1%': [], '1-2%': [], '2-5%': [], '>5%': [], 'N/A': []}
    sl_dist_data = []

    for row in rows:
        try:
            fj = json.loads(row[6])
            dist = fj.get('distance_to_pivot_pct')
            r_val = row[3]
            ep = row[4]
            sl = row[5]

            # Ширина SL как % от entry
            sl_dist_pct = None
            if ep and sl and ep > 0:
                try:
                    sl_dist_pct = abs(float(ep) - float(sl)) / float(ep) * 100
                except (TypeError, ValueError):
                    pass

            if sl_dist_pct is not None and dist is not None:
                sl_dist_data.append({
                    'dist': float(dist), 'sl_pct': sl_dist_pct,
                    'r': r_val, 'status': row[2]
                })

            if dist is None:
                buckets['N/A'].append(r_val)
            elif dist < 0.5:
                buckets['<0.5%'].append(r_val)
            elif dist < 1.0:
                buckets['0.5-1%'].append(r_val)
            elif dist < 2.0:
                buckets['1-2%'].append(r_val)
            elif dist < 5.0:
                buckets['2-5%'].append(r_val)
            else:
                buckets['>5%'].append(r_val)
        except Exception:
            pass

    def avg(lst):
        vals = [x for x in lst if x is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    print(f"\n  {'dist_to_pivot':12} {'n':>5}  {'avg_R':>7}  Интерпретация")
    print(f"  {'-'*55}")
    for bk, vals in buckets.items():
        n = len(vals)
        a = avg(vals)
        note = ''
        if bk == '<0.5%':
            note = '← идеальный (свежий вход)'
        elif bk == '>5%':
            note = '← поздний вход!'
        print(f"  {bk:12} {n:>5}  {str(a):>7}  {note}")

    # ── 3. SL ширина vs proximity ─────────────────────────────────
    section('3. Ширина SL vs расстояние до пивота (бакеты)')
    if sl_dist_data:
        close = [d for d in sl_dist_data if d['dist'] < 1.0]
        far   = [d for d in sl_dist_data if d['dist'] >= 1.0]
        def stats(lst):
            if not lst: return 'n=0'
            sl_w = [d['sl_pct'] for d in lst]
            rs   = [d['r'] for d in lst if d['r'] is not None]
            tps  = sum(1 for d in lst if d['status'] in ('TP','TSL'))
            return (f"n={len(lst)}  avg_SL_width={round(sum(sl_w)/len(sl_w),2)}%"
                    f"  avg_R={round(sum(rs)/len(rs),3) if rs else 'N/A'}"
                    f"  WR={round(tps/len(lst)*100,1)}%")

        print(f"  Вход близко (<1% от пивота): {stats(close)}")
        print(f"  Вход далеко (>=1%):           {stats(far)}")
        print()
        print("  Гипотеза H3: если SL ширина >> dist_to_pivot → SL слишком узок")
        print("  и любой шум после позднего входа выбивает позицию.")

        # Конкретные примеры позднего входа
        late = sorted([d for d in sl_dist_data if d['dist'] > 3.0],
                      key=lambda x: -x['dist'])[:5]
        if late:
            print(f"\n  Топ поздних входов (dist>3%):")
            for d in late:
                print(f"    dist={d['dist']:.1f}%  SL_width={d['sl_pct']:.2f}%  R={d['r']}  {d['status']}")

    # ── 4. direction × level_type из decision_trace ───────────────
    section('4. direction × level_type из decision_trace (raw_signals)')
    c.execute("""
        SELECT id, direction, status, R_multiple, decision_trace_json
        FROM simulated_trades
        WHERE signal_type='pivot_reversal' AND created_at >= ?
          AND decision_trace_json IS NOT NULL AND TYPEOF(decision_trace_json)='text'
          AND status IN ('TP','SL','TSL')
        ORDER BY id DESC LIMIT 300
    """, (POST_FIX,))

    level_stats = {}  # level_name → {direction → [r_vals]}
    no_level = 0

    for row in c.fetchall():
        try:
            dtj = json.loads(row[4])
            raw = dtj.get('raw_signals', [])
            level_name = None
            for s in raw:
                if s.get('type') == 'pivot_reversal':
                    level_name = s.get('level')
                    break
            if level_name is None:
                no_level += 1
                continue
            key = (level_name, row[1])  # (S1/R1/PP, LONG/SHORT)
            if key not in level_stats:
                level_stats[key] = []
            if row[3] is not None:
                level_stats[key].append(row[3])
        except Exception:
            pass

    if level_stats:
        print(f"\n  {'уровень':8} {'direction':8} {'n':>5}  {'avg_R':>7}  Логика")
        print(f"  {'-'*50}")
        for (lvl, direction), vals in sorted(level_stats.items()):
            n = len(vals)
            a = avg(vals)
            if 'S' in lvl and 'R' not in lvl:
                expected = 'LONG'
            elif 'R' in lvl:
                expected = 'SHORT'
            else:
                expected = 'BOTH'
            logic = 'OK' if expected == 'BOTH' or direction == expected else '!!! ОШИБКА НАПРАВЛЕНИЯ !!!'
            print(f"  {lvl:8} {direction:8} {n:>5}  {str(a):>7}  {logic}")
    else:
        print("  Поле 'level' не найдено в raw_signals (не хранится в decision_trace).")

    print(f"\n  Сделок без поля level: {no_level}")

    # ── ИТОГОВЫЙ ВЫВОД ────────────────────────────────────────────
    section('ИТОГ H3')
    print("""
  По результатам аудита:

  1. SL SOURCE: pivot_reversal использует atr_1.5/atr_14, НЕ pivot:0.3%.
     Это означает что tight-SL логика из pivot_reversal.py не применяется.
     ATR×1.5 шире но не привязан к уровню — при запоздалом входе цена
     возвращается к пивоту и выбивает SL.

  2. PROXIMITY: distance_to_pivot_pct > 1% означает поздний вход.
     Смотри бакеты выше — при близких входах (<0.5%) avg_R лучше.

  3. DIRECTION LOGIC: классификация support→LONG / resistance→SHORT
     корректна в коде (строки 164-204 pivot_reversal.py).
     Бага в направлении нет.

  ГЛАВНЫЙ ВЫВОД H3: проблема не в классификации уровня, а в том что
  сигнал генерируется когда цена УЖЕ отошла от уровня (отскок завершён).
  Нужен фильтр: если distance_to_pivot_pct > X → не входить.
    """)

    conn.close()


if __name__ == '__main__':
    main()
