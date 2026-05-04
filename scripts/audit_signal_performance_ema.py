"""
ARCH-95 H7 — Аудит: EMA avg_R vs full-history avg_R per signal_type.

Сравнивает как адаптивные веса реагировали бы при разных half_life:
  1. full-history AVG (старый режим, method=full_history)
  2. EMA hl=20  (очень реактивный)
  3. EMA hl=50  (текущий production default)
  4. EMA hl=100 (консервативный)

Формула веса: new_weight = base × clamp(1.0 + avg_R × 0.4, 0.5, 2.0)
Порог: min 20 закрытых сделок на тип.
Источник истины: core/trading/performance_engine.py:132 (by_signal_type_ema).

Показывает:
  * где EMA детектит деградацию раньше full-history
  * «rolling EMA» на хронологии — куда тренд идёт прямо сейчас
  * сколько реальных сделок остаётся в каждой выборке
  * что даёт таблица signal_weights_history (сохранённые снэпшоты)

Только read-only, не меняет БД.
Запуск: python scripts/audit_signal_performance_ema.py
"""
import sqlite3
import os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'subscriptions.db')
POST_FIX = '2026-04-15'

BASE_WEIGHTS = {
    'pivot_reversal': 0.20,
    'trend_signal':   0.10,
    'wt_signal':      0.10,
    'wt_b_signal':    0.10,
    'anomaly':        0.10,
    'divergence':     0.10,
    'mtf_bias':       0.10,
    'confluence':     0.10,
    'watch_list_breach': 0.10,
}
MIN_TRADES = 20


def connect():
    return sqlite3.connect(f'file:{DB_PATH}?mode=ro&immutable=1', uri=True)


def section(title):
    print(f'\n{"="*70}')
    print(f'  {title}')
    print('='*70)


def factor(avg_r):
    return max(0.5, min(2.0, 1.0 + avg_r * 0.4))


def ema_alpha(hl):
    return 1.0 - 0.5 ** (1.0 / float(hl))


def fetch_closed(conn, data_era='post_fix'):
    """Возвращает dict signal_type → [(closed_at, R_multiple), ...] по хронологии."""
    sql = """
        SELECT signal_type, R_multiple, status, closed_at
        FROM simulated_trades
        WHERE status IN ('TP','SL','TSL')
          AND R_multiple IS NOT NULL
          AND json_extract(features_json,'$.data_era') = ?
        ORDER BY closed_at ASC
    """
    c = conn.cursor()
    c.execute(sql, (data_era,))
    by_type = defaultdict(list)
    for st, r, status, closed_at in c.fetchall():
        by_type[st].append((closed_at, float(r), status))
    return by_type


def compute_ema(values, hl):
    """Инкрементальная EMA по списку чисел."""
    if not values:
        return None
    a = ema_alpha(hl)
    ema = values[0]
    for v in values[1:]:
        ema = a * v + (1.0 - a) * ema
    return ema


def compute_full(values):
    return sum(values) / len(values) if values else None


def main():
    conn = connect()

    section('0. Выборка (post_fix, закрытые TP/SL/TSL)')
    by_type = fetch_closed(conn)
    total = sum(len(v) for v in by_type.values())
    print(f'\n  Всего сделок: {total}')
    print(f"  {'signal_type':22} {'n':>6}")
    print(f"  {'-'*32}")
    for st, trades in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {st:22} {len(trades):>6}")

    # ── 1. Сравнение методов ──────────────────────────────────────
    section('1. avg_R & factor per signal_type: FULL vs EMA(20/50/100)')
    print(f"\n  {'signal_type':22} {'n':>4} "
          f"{'avg_R_full':>10} {'f_full':>7} "
          f"{'EMA_20':>8} {'f_20':>6} "
          f"{'EMA_50':>8} {'f_50':>6} "
          f"{'EMA_100':>8} {'f_100':>6}")
    print(f"  {'-'*105}")

    rankings = {'full': [], 'ema20': [], 'ema50': [], 'ema100': []}
    for st in sorted(by_type.keys(), key=lambda s: -len(by_type[s])):
        trades = by_type[st]
        n = len(trades)
        if n < MIN_TRADES:
            continue
        rs = [t[1] for t in trades]
        avg_full = compute_full(rs)
        ema20  = compute_ema(rs, 20)
        ema50  = compute_ema(rs, 50)
        ema100 = compute_ema(rs, 100)

        base = BASE_WEIGHTS.get(st, 0.10)
        w_full = round(base * factor(avg_full), 4)
        w_20   = round(base * factor(ema20), 4)
        w_50   = round(base * factor(ema50), 4)
        w_100  = round(base * factor(ema100), 4)

        rankings['full'].append((st, avg_full, w_full))
        rankings['ema20'].append((st, ema20, w_20))
        rankings['ema50'].append((st, ema50, w_50))
        rankings['ema100'].append((st, ema100, w_100))

        print(f"  {st:22} {n:>4} "
              f"{avg_full:>+10.3f} {factor(avg_full):>7.3f} "
              f"{ema20:>+8.3f} {factor(ema20):>6.3f} "
              f"{ema50:>+8.3f} {factor(ema50):>6.3f} "
              f"{ema100:>+8.3f} {factor(ema100):>6.3f}")

    # ── 2. Δ avg_R (EMA50 − full): кто деградирует / ускоряется ──
    section('2. Δ (EMA50 − full): знак показывает направление тренда')
    deltas = []
    full_by_st = {st: r for st, r, _ in rankings['full']}
    ema50_by_st = {st: r for st, r, _ in rankings['ema50']}
    for st in full_by_st:
        d = ema50_by_st[st] - full_by_st[st]
        deltas.append((st, full_by_st[st], ema50_by_st[st], d))
    deltas.sort(key=lambda x: x[3])

    print(f"\n  {'signal_type':22} {'full':>8} {'ema50':>8} {'Δ':>8}  Тренд")
    print(f"  {'-'*55}")
    for st, full, ema, d in deltas:
        if d < -0.15:
            trend = 'ДЕГРАДАЦИЯ (EMA ниже full)'
        elif d > 0.15:
            trend = 'разогревается'
        else:
            trend = 'стабильно'
        print(f"  {st:22} {full:>+8.3f} {ema:>+8.3f} {d:>+8.3f}  {trend}")

    # ── 3. Rolling EMA50: траектория по мере поступления сделок ──
    section('3. Rolling EMA50: как менялся avg_R на последних сделках')
    a = ema_alpha(50)
    for st, trades in sorted(by_type.items(), key=lambda x: -len(x[1])):
        if len(trades) < MIN_TRADES:
            continue
        rs = [t[1] for t in trades]
        ema = rs[0]
        series = [ema]
        for v in rs[1:]:
            ema = a * v + (1.0 - a) * ema
            series.append(ema)
        # Срезы: старт / 1/4 / середина / 3/4 / конец
        n = len(series)
        cuts = [0, n // 4, n // 2, (3 * n) // 4, n - 1]
        vals = [series[i] for i in cuts]
        print(f"\n  {st:22} (n={n})")
        print(f"    {'начало':>9} {'25%':>9} {'50%':>9} {'75%':>9} {'сейчас':>9}")
        print(f"    " + " ".join(f"{v:>+9.3f}" for v in vals))

    # ── 4. Сохранённые снэпшоты (signal_weights_history) ──────────
    section('4. signal_weights_history: что писал production')
    try:
        c = conn.cursor()
        c.execute("""
            SELECT signal_type, ema_avg_r, full_avg_r, adapted_weight, base_weight,
                   n_trades, half_life, method, computed_at
            FROM signal_weights_history
            WHERE computed_at >= ?
            ORDER BY computed_at DESC LIMIT 40
        """, (POST_FIX,))
        rows = c.fetchall()
        if rows:
            print(f"\n  {'computed_at':20} {'st':22} {'ema':>7} {'full':>7} "
                  f"{'w':>6} {'n':>4} {'hl':>4} {'method':>7}")
            print(f"  {'-'*85}")
            for r in rows[:25]:
                st, ema, full, w, base, n, hl, method, ts = r
                print(f"  {str(ts)[:19]:20} {st:22} "
                      f"{(ema if ema is not None else 0):>+7.3f} "
                      f"{(full if full is not None else 0):>+7.3f} "
                      f"{w:>6.3f} {n:>4} {hl:>4.0f} {str(method):>7}")
            print(f"\n  (всего записей после {POST_FIX}: {len(rows)})")
        else:
            print(f"\n  Таблица пуста после {POST_FIX} — production ещё не писал снэпшоты.")
    except Exception as e:
        print(f"\n  signal_weights_history недоступна: {e}")

    # ── ИТОГ ──────────────────────────────────────────────────────
    section('ИТОГ H7')
    print("""
  МЕТОДИКА (совпадает с production):
  - α = 1 − 0.5^(1/hl); при hl=50 сделка 50-й давности весит 0.5
  - factor = clamp(1.0 + avg_R × 0.4, 0.5, 2.0); base × factor = adapted_weight
  - Минимум 20 сделок на тип, иначе вес не меняется.

  ЧТО ПОКАЗЫВАЕТ ТАБЛИЦА 2 (Δ = EMA50 − full):
  - Δ << 0  → последние сделки хуже исторического среднего → деградация,
             full-history вес всё ещё высокий, но качество уже упало.
             Именно здесь EMA ловит проблему раньше.
  - Δ >> 0  → обратное: сигнал разогревается, EMA даст больше веса быстрее.
  - |Δ|<0.15 → режимы практически эквивалентны.

  ЧТО ПОКАЗЫВАЕТ ТАБЛИЦА 3:
  - Траектория EMA50 на срезах 0/25/50/75/100% сделок — видно, в какой
    момент avg_R развернулся. Если сейчас < начало → тренд вниз.

  КАК ЧИТАТЬ РЕЗУЛЬТАТЫ:
  - hl=20  — реактивно: реагирует на 20 последних сделок (≈ 2-3 дня при
    текущем потоке). Годится для раннего детектирования деградации,
    но шумит на малых выборках.
  - hl=50  — production default. ≈ неделя свежей истории. Баланс.
  - hl=100 — консервативный. ≈ 2 недели. Почти как full при 200+ сделок.
    """)

    conn.close()


if __name__ == '__main__':
    main()
