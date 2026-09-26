"""Симуляция: что даёт cap на SL по размеру."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

# Базовая выборка: все закрытые post-15.04 с данными
cur.execute("""
SELECT signal_type, direction, R_multiple, tsl_activated, status,
       ABS(entry_price - stop_loss)/entry_price*100 as sl_pct,
       max_R_possible, sl_source
FROM simulated_trades
WHERE created_at > '2026-04-15' AND status != 'OPEN'
  AND entry_price > 0 AND stop_loss > 0
  AND R_multiple IS NOT NULL AND sl_pct > 0
""")
rows = cur.fetchall()
print(f"Всего сделок: {len(rows)}")

def stats(subset, label):
    if not subset: return
    n = len(subset)
    avgR = sum(r[2] for r in subset) / n
    totalR = sum(r[2] for r in subset)
    wr = sum(1 for r in subset if r[2] > 0) * 100 / n
    tsl = sum(1 for r in subset if r[3] == 1) * 100 / n
    print(f"  {label:<45} n={n:>5}  avgR={avgR:>+.3f}  totalR={totalR:>+7.1f}  WR={wr:.0f}%  TSL%={tsl:.0f}%")

all_rows = rows

# Текущее состояние
print("\n=== ТЕКУЩЕЕ vs CAP ФИЛЬТР ===")
stats(all_rows, "ВСЕ (baseline)")

for cap in [1.0, 1.5, 2.0, 2.5]:
    filtered = [r for r in all_rows if r[5] <= cap]
    rejected = [r for r in all_rows if r[5] > cap]
    stats(filtered, f"cap ≤ {cap}% (принятые)")
    if rejected:
        rej_avgR = sum(r[2] for r in rejected)/len(rejected)
        print(f"    → отклонено {len(rejected)} сделок, avgR={rej_avgR:+.3f}")

# По сигналам — что cap даёт конкретно для atr_change и WLB
print("\n=== atr_change: cap ≤ 1.5% vs > 1.5% ===")
for sig in ['atr_change', 'watch_list_breach', 'confluence', 'wt_sideways']:
    sub = [r for r in all_rows if r[0] == sig]
    if not sub: continue
    tight = [r for r in sub if r[5] <= 1.5]
    wide  = [r for r in sub if r[5] > 1.5]
    print(f"\n  {sig}:")
    stats(tight, f"    SL ≤ 1.5%")
    stats(wide,  f"    SL > 1.5% (было бы отклонено)")

# Главный вопрос: cap — это НЕ сужение стопа, это фильтр входа
# Но есть альтернатива: cap = заменить широкий SL на swing/pivot tight SL
# Проверим: если бы SL был max 1.5%, то 1R = меньше
# и TSL активируется при меньшем движении
print("\n=== CORE ВОПРОС: cap vs альтернатива ===")
# Сделки где SL > 1.5% и mfe > 0.5R (цена двигалась в нашу сторону)
opportunity_lost = [r for r in all_rows if r[5] > 1.5 and (r[6] or 0) > 0.5]
print(f"\n  Сделок с SL>1.5% И mfe>0.5R: {len(opportunity_lost)}")
print(f"  (входил бы при tight SL — цена шла в нашу сторону)")
if opportunity_lost:
    avgR = sum(r[2] for r in opportunity_lost)/len(opportunity_lost)
    tsl = sum(1 for r in opportunity_lost if r[3]==1)*100/len(opportunity_lost)
    print(f"  avgR={avgR:+.3f}  TSL%={tsl:.0f}%")
    # Сколько из них вышли по SL?
    sl_exits = [r for r in opportunity_lost if r[4] == 'SL']
    print(f"  Вышли по SL (потеряли): {len(sl_exits)} ({len(sl_exits)/len(opportunity_lost)*100:.0f}%)")

# Что если бы эти сделки не входили?
no_wide = [r for r in all_rows if r[5] <= 1.5]
wide_only = [r for r in all_rows if r[5] > 1.5]
print(f"\n=== ИТОГ: что даёт фильтр cap ≤ 1.5% ===")
if wide_only:
    print(f"  Сейчас: n={len(all_rows)}, avgR={sum(r[2] for r in all_rows)/len(all_rows):+.3f}, "
          f"totalR={sum(r[2] for r in all_rows):+.1f}")
    print(f"  После cap: n={len(no_wide)}, avgR={sum(r[2] for r in no_wide)/len(no_wide):+.3f}, "
          f"totalR={sum(r[2] for r in no_wide):+.1f}")
    delta_totalR = sum(r[2] for r in no_wide) - sum(r[2] for r in all_rows)
    delta_avgR   = sum(r[2] for r in no_wide)/len(no_wide) - sum(r[2] for r in all_rows)/len(all_rows)
    print(f"  Δ totalR={delta_totalR:+.1f}  Δ avgR={delta_avgR:+.3f}")
    print(f"  Отклонено {len(wide_only)} сделок (avgR={sum(r[2] for r in wide_only)/len(wide_only):+.3f})")

conn.close()
