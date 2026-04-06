"""
Точный анализ оптимального breakeven_activation_r.
Использует first_profit_r / first_drawdown_r для определения хронологии движения.

Запускать после накопления данных (1-2 дня работы бота):
    python scripts/analyze_breakeven.py
"""
import sqlite3

conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

print('=== ТОЧНЫЙ АНАЛИЗ breakeven_activation_r ===')
print('(на основе first_profit_r / first_drawdown_r)')
print()

cur.execute('SELECT COUNT(*) FROM simulated_trades WHERE first_profit_r IS NOT NULL')
n = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM simulated_trades WHERE status != "OPEN"')
total = cur.fetchone()[0]
print(f'Закрытых сделок: {total} | с хронологией: {n}')
print()

if n < 20:
    print('Мало данных — подождите 1-2 дня накопления (нужно минимум 20 сделок с полями)')
else:
    print(f'{"Порог BE":8} | {"Точно спасено SL":>16} | {"Выгода":>8} | {"Срезано TSL":>11} | {"Потери":>8} | {"НЕТТО":>8}')
    print('-' * 75)
    for be_r in [0.3, 0.5, 0.7, 0.8, 1.0]:
        # ТОЧНО спасённые SL:
        # - цена СНАЧАЛА пошла в прибыль до be_r (first_profit_r >= be_r)
        # - не было отката ниже entry ДО этого (first_drawdown_r IS NULL)
        cur.execute('''
            SELECT COUNT(*), AVG(R_multiple) FROM simulated_trades
            WHERE status = "SL"
            AND first_profit_r >= ?
            AND (first_drawdown_r IS NULL OR first_drawdown_r > -0.1)
        ''', (be_r,))
        saved, avg_sl = cur.fetchone()
        avg_sl = avg_sl or 0
        gain = saved * abs(avg_sl)

        # ТОЧНО срезанные TSL:
        # - достигли порога BE (first_profit_r >= be_r)
        # - И был откат к entry (first_drawdown_r < -0.05) — мог сработать BE
        cur.execute('''
            SELECT COUNT(*), AVG(R_multiple) FROM simulated_trades
            WHERE status = "TSL"
            AND first_profit_r >= ?
            AND first_drawdown_r IS NOT NULL
            AND first_drawdown_r < -0.05
        ''', (be_r,))
        cut, avg_tsl = cur.fetchone()
        avg_tsl = avg_tsl or 0
        loss = cut * avg_tsl

        net = gain - loss
        print(f'{be_r}R      | {saved:>10d} ({gain:>5.0f}R) | {gain:>8.0f}R | {cut:>7d} ({loss:>5.0f}R) | {loss:>8.0f}R | {net:>+8.0f}R')

    print()
    print('Оптимальный порог = наибольшее положительное НЕТТО.')

    # Дополнительно: распределение first_profit_r
    print()
    print('=== Распределение first_profit_r (когда цена впервые шла в прибыль) ===')
    cur.execute('''
        SELECT ROUND(first_profit_r, 1), COUNT(*)
        FROM simulated_trades
        WHERE first_profit_r IS NOT NULL AND status != "OPEN"
        GROUP BY ROUND(first_profit_r, 1)
        ORDER BY first_profit_r
        LIMIT 20
    ''')
    for row in cur.fetchall():
        bar = '#' * row[1]
        print(f'  {row[0]:>5.1f}R: {row[1]:>4d} {bar[:40]}')

conn.close()
