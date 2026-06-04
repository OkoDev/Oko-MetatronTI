"""
DS-308: Аудит stale-кэша для OPEN сделок.
Проверяет расхождение между данными в БД и реальными ценами BingX.
Запуск: python scripts/audit_stale_cache.py
"""
import sqlite3
import sys
import os

DB_PATH = "subscriptions.db"


def get_open_trades(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT id, symbol, direction, entry_price, stop_loss, take_profit,
               max_price, min_price, tsl_activated, be_activated,
               created_at, signal_type, regime, source_router,
               exchange_order_id, R_multiple
        FROM simulated_trades
        WHERE status = 'OPEN'
        ORDER BY created_at DESC
    """)
    trades = [dict(r) for r in cur.fetchall()]
    conn.close()
    return trades


def fetch_current_prices(symbols):
    try:
        import ccxt.async_support as ccxt_async
        import asyncio

        async def _fetch():
            ex = ccxt_async.bingx({
                'enableRateLimit': False,
                'timeout': 10000,
            })
            try:
                tickers = await ex.fetch_tickers()
                result = {}
                for sym in symbols:
                    clean = sym.replace(':USDT', '').replace('/USDT', '')
                    for fmt in [sym, clean, clean + '/USDT', clean + '/USDT:USDT']:
                        if fmt in tickers:
                            t = tickers[fmt]
                            result[sym] = {
                                'last': t.get('last'),
                                'bid': t.get('bid'),
                                'ask': t.get('ask'),
                            }
                            break
                return result
            finally:
                await ex.close()

        return asyncio.run(_fetch())
    except Exception as e:
        print(f"  [!] BingX API error: {e}")
        return {}


def analyze(trades, prices):
    print(f"\n{'='*70}")
    print(f"Stale-cache audit: {len(trades)} OPEN trades")
    print(f"BingX prices: {len(prices)} symbols")
    print(f"{'='*70}\n")

    issues = []
    ok_count = 0

    for t in trades:
        sym = t['symbol']
        entry = t['entry_price']
        sl = t['stop_loss']
        tp = t.get('take_profit')
        direction = t['direction']
        price_data = prices.get(sym, {})

        if not price_data or not price_data.get('last'):
            continue

        current = price_data['last']
        issues_for_trade = []

        # 1. TSL/BE should have activated
        if direction == 'LONG' and sl:
            move_pct = (current - entry) / entry * 100
            if move_pct > 0.5 and not t['be_activated']:
                issues_for_trade.append(
                    f"Price +{move_pct:.1f}% from entry, BE not activated (threshold 0.5R)"
                )
            if move_pct > 1.0 and not t['tsl_activated']:
                issues_for_trade.append(
                    f"Price +{move_pct:.1f}% from entry, TSL not activated (threshold 1R)"
                )

        elif direction == 'SHORT' and sl:
            move_pct = (entry - current) / entry * 100
            if move_pct > 0.5 and not t['be_activated']:
                issues_for_trade.append(
                    f"Price -{move_pct:.1f}% from entry, BE not activated"
                )
            if move_pct > 1.0 and not t['tsl_activated']:
                issues_for_trade.append(
                    f"Price -{move_pct:.1f}% from entry, TSL not activated"
                )

        # 2. Price beyond SL
        if direction == 'LONG' and sl and current < sl:
            loss_pct = (sl - current) / sl * 100
            issues_for_trade.append(
                f"[SL] Current {current:.6f} < SL {sl:.6f} ({loss_pct:.2f}% beyond)"
            )
        elif direction == 'SHORT' and sl and current > sl:
            loss_pct = (current - sl) / sl * 100
            issues_for_trade.append(
                f"[SL] Current {current:.6f} > SL {sl:.6f} ({loss_pct:.2f}% beyond)"
            )

        # 3. TP was reached (max_price >= TP)
        if t.get('max_price') and tp:
            if direction == 'LONG' and t['max_price'] >= tp:
                issues_for_trade.append(
                    f"[TP] max_price={t['max_price']:.6f} >= TP={tp:.6f} but still OPEN"
                )
            elif direction == 'SHORT' and t['min_price'] and t['min_price'] <= tp:
                issues_for_trade.append(
                    f"[TP] min_price={t['min_price']:.6f} <= TP={tp:.6f} but still OPEN"
                )

        if issues_for_trade:
            print(f"[!] #{t['id']} {sym} {direction} {t.get('signal_type','?')}")
            print(f"    Entry={entry:.8f} SL={sl:.8f} Current={current:.8f}")
            print(f"    Created: {t['created_at'][:19] if t['created_at'] else '?'}")
            if t.get('exchange_order_id'):
                print(f"    Exchange order: {t['exchange_order_id']}")
            for issue in issues_for_trade:
                print(f"    -> {issue}")
            print()
            issues.append(t)
        else:
            ok_count += 1

    print(f"{'='*70}")
    print(f"RESULTS:")
    print(f"  [OK] No anomalies:  {ok_count}")
    print(f"  [!] With anomalies: {len(issues)}")
    print(f"  [?] No BingX data:  {len(trades) - ok_count - len(issues)}")
    print(f"{'='*70}")

    if issues:
        print("\n[!] WARNING: trades with stale-cache signs detected!")
        print("   TSL/BE may have failed due to outdated OHLCV data.")
        print("   Manual position check on exchange recommended.")
        # Check how many have exchange orders (real money)
        exchange_issues = [i for i in issues if i.get('exchange_order_id')]
        if exchange_issues:
            print(f"   [!] {len(exchange_issues)} of these are LIVE exchange positions!")

    return issues


if __name__ == "__main__":
    trades = get_open_trades()
    if not trades:
        print("No OPEN trades.")
        sys.exit(0)

    symbols = list(set(t['symbol'] for t in trades))
    print(f"Fetching prices for {len(symbols)} symbols...")
    prices = fetch_current_prices(symbols)

    analyze(trades, prices)
