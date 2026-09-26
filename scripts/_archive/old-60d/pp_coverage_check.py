import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('subscriptions.db')
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print('Таблицы:', [t for t in tables if 'pivot' in t.lower() or 'trade' in t.lower()])

if 'pivot_cache' in tables:
    cur.execute('PRAGMA table_info(pivot_cache)')
    cols = cur.fetchall()
    print('pivot_cache columns:', [c[1] for c in cols])
    cur.execute('SELECT COUNT(*) FROM pivot_cache')
    print('pivot_cache rows:', cur.fetchone()[0])
    cur.execute('SELECT COUNT(DISTINCT symbol) FROM pivot_cache')
    print('pivot_cache уник символов:', cur.fetchone()[0])
    cur.execute("SELECT COUNT(DISTINCT symbol) FROM pivot_cache WHERE timeframe='1W'")
    print('1W символов:', cur.fetchone()[0])
    cur.execute("SELECT COUNT(DISTINCT symbol) FROM pivot_cache WHERE timeframe='1D'")
    print('1D символов:', cur.fetchone()[0])

    # Проверим топ-5 символов по дате обновления
    cur.execute("SELECT symbol, timeframe, pp, updated_at FROM pivot_cache ORDER BY updated_at DESC LIMIT 10")
    print('\nПоследние обновления pivot_cache:')
    for row in cur.fetchall():
        print(f'  {row[0]} {row[1]}: PP={row[2]:.6f}, updated={row[3]}')
else:
    print('НЕТ таблицы pivot_cache!')

cur.execute("SELECT COUNT(DISTINCT symbol) FROM simulated_trades WHERE status!='OPEN'")
total_syms = cur.fetchone()[0]
print(f'\nСимволов в закрытых сделках: {total_syms}')

# Покрытие JOIN
cur.execute("""
SELECT COUNT(DISTINCT t.symbol) as matched
FROM simulated_trades t
JOIN pivot_cache w ON t.symbol = w.symbol AND w.timeframe = '1W' AND w.pp > 0
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL
""")
matched = cur.fetchone()[0]
print(f'Символов в JOIN (1W pivot_cache): {matched}')
print(f'Покрытие: {matched}/{total_syms} = {matched/total_syms*100:.1f}%')

# Сделки не попавшие в JOIN
cur.execute("""
SELECT t.symbol, COUNT(*) as cnt
FROM simulated_trades t
LEFT JOIN pivot_cache w ON t.symbol = w.symbol AND w.timeframe = '1W' AND w.pp > 0
WHERE t.status != 'OPEN' AND t.R_multiple IS NOT NULL AND w.symbol IS NULL
GROUP BY t.symbol
ORDER BY cnt DESC LIMIT 10
""")
rows = cur.fetchall()
if rows:
    print('\nТоп символов БЕЗ покрытия 1W pivot_cache:')
    for sym, cnt in rows:
        print(f'  {sym}: {cnt} сделок')

conn.close()
