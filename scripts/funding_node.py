"""INBOX-FUNDING-NODE + VST-FUNDING — data-слой: funding rate + стакан.

VST-FUNDING (08.06.2026): 172 perpetual-позиции висят днями, funding каждые 8ч.
  Оценивает стоимость удержания, НЕ в R_multiple.

INBOX-FUNDING-NODE (08.06.2026, Inbox2): узел данных биржи.
  - funding rate по монете (BingX REST, публичный)
  - глубокий стакан Binance spot depth=5000 (публичный, без ключа)

Использование:
  python scripts/funding_node.py                    # все OPEN позиции
  python scripts/funding_node.py XLM/USDT           # конкретная монета
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ccxt
import sqlite3


def get_open_positions(db_path: str, symbol: str = None):
    """Список OPEN VST позиций с длительностью."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    query = """
        SELECT symbol, signal_type, direction, entry_price, 
               ROUND((julianday('now') - julianday(created_at)) * 24, 1) as hours_open,
               R_multiple as current_r
        FROM simulated_trades
        WHERE status = 'OPEN'
          AND exchange_order_id IS NOT NULL AND exchange_order_id != 'SIM' AND exchange_order_id != ''
    """
    if symbol:
        query += f" AND symbol = '{symbol}'"
    query += " ORDER BY hours_open DESC"
    cur = db.execute(query)
    return [dict(r) for r in cur.fetchall()]


def fetch_funding_rates(symbols: list) -> dict:
    """BingX funding rate (публичный REST)."""
    ex = ccxt.bingx({'enableRateLimit': True, 'timeout': 10000})
    rates = {}
    for sym in symbols:
        try:
            ticker = ex.fetch_ticker(sym)
            funding = ticker.get('info', {}).get('fundingRate') or ticker.get('fundingRate')
            if funding is None:
                # try funding endpoint directly
                try:
                    fr = ex.fetch_funding_rate(sym)
                    funding = fr.get('fundingRate') or fr.get('rate')
                except Exception:
                    funding = None
            rates[sym] = float(funding) if funding else None
        except Exception as e:
            rates[sym] = None
    return rates


def fetch_orderbook_depth(symbol: str, limit: int = 20) -> dict:
    """Binance spot depth (публичный, без ключа). Возвращает bid/ask спред + топ-уровни."""
    ex = ccxt.binance({'enableRateLimit': True, 'timeout': 10000})
    try:
        ob = ex.fetch_order_book(symbol, limit)
        best_bid = ob['bids'][0][0] if ob['bids'] else None
        best_ask = ob['asks'][0][0] if ob['asks'] else None
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None
        spread_pct = (best_ask - best_bid) / mid * 100 if mid and best_bid and best_ask else None

        # Top levels
        bids_5 = [(p, q) for p, q in ob['bids'][:5]]
        asks_5 = [(p, q) for p, q in ob['asks'][:5]]

        # Estimate slippage: cost to eat top N levels
        def slip_est(levels, side):
            cost = 0; qty = 0
            base_price = levels[0][0] if levels else 0
            for p, q in levels:
                cost += abs(p - base_price) / base_price * q
                qty += q
            return cost / qty * 100 if qty > 0 else 0

        bid_slip = slip_est(bids_5, 'buy')
        ask_slip = slip_est(asks_5, 'sell')

        return {
            'symbol': symbol,
            'best_bid': best_bid, 'best_ask': best_ask, 'mid': mid,
            'spread_pct': round(spread_pct, 4) if spread_pct else None,
            'bid_slippage_est_pct': round(bid_slip, 4),
            'ask_slippage_est_pct': round(ask_slip, 4),
            'bids_top5': bids_5, 'asks_top5': asks_5,
        }
    except Exception as e:
        return {'symbol': symbol, 'error': str(e)}


def run():
    DB = str(ROOT / "subscriptions.db")
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else None

    # 1. Open positions
    positions = get_open_positions(DB, target_symbol)
    if not positions:
        print("No open VST positions.")
        return

    symbols = list(set(p['symbol'] for p in positions))
    print(f"Open positions: {len(positions)} across {len(symbols)} symbols\n")

    # 2. Funding rates
    print("=" * 60)
    print("  FUNDING RATES (BingX perpetual)")
    print("=" * 60)
    rates = fetch_funding_rates(symbols)

    # Per-symbol summary
    sym_stats = {}
    for p in positions:
        s = p['symbol']
        if s not in sym_stats:
            sym_stats[s] = {'n': 0, 'total_hours': 0, 'signal_types': set()}
        sym_stats[s]['n'] += 1
        sym_stats[s]['total_hours'] += p['hours_open']
        sym_stats[s]['signal_types'].add(p['signal_type'])

    total_funding_cost = 0
    for sym, stats in sorted(sym_stats.items(), key=lambda x: -x[1]['n']):
        fr = rates.get(sym)
        fr_str = f"{fr*100:.4f}%" if fr else "N/A"
        # Funding cost estimate: funding% × hours × positions
        if fr:
            # funding rate per 8h. Cost per position per hour = fr / 8 * entry_value
            est_cost = stats['total_hours'] * abs(fr) / 8 * stats['n'] * 0.01  # rough R estimate
            total_funding_cost += est_cost
            cost_str = f"~{est_cost:.1f}R"
        else:
            cost_str = "N/A"
        print(f"  {sym:15s}  n={stats['n']:>3d}  {stats['total_hours']:>6.0f}h total  "
              f"funding={fr_str:>10s}  est_cost={cost_str:>8s}  types={stats['signal_types']}")

    print(f"\n  Estimated total funding cost: ~{total_funding_cost:.1f}R")
    print(f"  (грубая оценка: funding_rate/8h × часы × позиции × 0.01R/позицию)")

    # 3. Orderbook (only for requested symbol or top-5 by position count)
    print(f"\n{'=' * 60}")
    print(f"  ORDERBOOK (Binance spot depth=20)")
    print(f"{'=' * 60}")

    top_symbols = sorted(sym_stats.items(), key=lambda x: -x[1]['n'])[:5]
    for sym, stats in top_symbols:
        ob = fetch_orderbook_depth(sym)
        if 'error' in ob:
            print(f"  {sym}: ERROR {ob['error']}")
            continue
        print(f"\n  {sym} (n={stats['n']})")
        print(f"    Bid: {ob['best_bid']:.6f}  Ask: {ob['best_ask']:.6f}  "
              f"Spread: {ob['spread_pct']:.4f}%")
        print(f"    Slippage est: bid={ob['bid_slippage_est_pct']:.4f}%  ask={ob['ask_slippage_est_pct']:.4f}%")
        if target_symbol:
            print(f"    Bids top5: {ob['bids_top5']}")
            print(f"    Asks top5: {ob['asks_top5']}")


if __name__ == "__main__":
    run()
