#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
# Принудительно UTF-8 для Windows (cp1251 не поддерживает emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
"""
CLI для запуска бэктестов стратегий.

Использование:
    python run_backtest.py --strategy confluence_scanner --symbol BTC/USDT --days 30
    python run_backtest.py --strategy default --symbol ETH/USDT --from 2026-01-01 --to 2026-03-01
    python run_backtest.py --list-strategies
    python run_backtest.py --strategy confluence_scanner --symbol BTC/USDT --days 60 --tf 1h

Параметры:
    --strategy      Имя стратегии (default|confluence_scanner|conservative|...)
    --symbol        Торговая пара (BTC/USDT, ETH/USDT и т.д.)
    --tf            Таймфрейм (1h, 4h, 15m — дефолт 1h)
    --days          Количество дней назад от сегодня
    --from          Дата начала (YYYY-MM-DD)
    --to            Дата конца  (YYYY-MM-DD, дефолт сегодня)
    --no-htf        Отключить HTF фильтр
    --no-pp         Отключить фильтр по weekly PP
    --tp-rr         RR для TP (дефолт 2.0, для confluence_scanner 3.0)
    --list-strategies  Показать список доступных стратегий и выйти
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.WARNING,  # только WARNING+ чтобы не засорять вывод
    format="%(levelname)s %(name)s: %(message)s"
)
# Бэктест-движок логируем на INFO
logging.getLogger("__main__").setLevel(logging.INFO)
bt_logger = logging.getLogger("backtesting_engine")
bt_logger.setLevel(logging.INFO)


def list_strategies():
    """Выводит список доступных стратегий и выходит."""
    try:
        from strategies.registry import list_strategies as _ls, _load_built_in_strategies
        _load_built_in_strategies()
        names = _ls()
    except Exception as e:
        print(f"Ошибка загрузки реестра стратегий: {e}")
        names = []

    built_in = ["default", "confluence_scanner"] + names
    seen = set()
    unique = [x for x in built_in if not (x in seen or seen.add(x))]

    print("\n📋 Доступные стратегии:")
    print("─" * 40)
    for name in unique:
        marker = "  ●" if name in ("default", "confluence_scanner") else "  ○"
        print(f"{marker} {name}")
    print()
    print("  default            — текущие check_*_signals (wt + divergence + trend + anomaly)")
    print("  confluence_scanner — мульти-факторный сетап (WT OS/OB + TSL cross + пивот + дивер)")
    print("  conservative       — 3+ сигнала, узкий SL")
    print()


def print_results(result: dict, strategy: str, symbol: str, tf: str):
    """Форматированный вывод результатов бэктеста."""
    m = result.get("metrics", {})
    trades = result.get("trades", [])
    signals_found = result.get("signals_found", 0)
    data_points = result.get("data_points", 0)
    cfg = result.get("config")

    from_dt = cfg.start_date.strftime("%d.%m.%Y") if cfg else "?"
    to_dt   = cfg.end_date.strftime("%d.%m.%Y")   if cfg else "?"

    print()
    print(f"{'─'*55}")
    print(f"📊 Стратегия: {strategy}  |  {symbol}  |  {tf}")
    print(f"   Период: {from_dt} → {to_dt}  |  Свечей: {data_points}  |  Сигналов найдено: {signals_found}")
    print(f"{'─'*55}")
    print(f"  Сделок:       {m.get('total_trades', 0)}")
    print(f"  Win Rate:     {m.get('win_rate', 0):.1f}%")
    print(f"  Avg R:        {m.get('avg_r_multiple', 0):.2f}")
    print(f"  Profit Fct:   {m.get('profit_factor', 0):.2f}")
    print(f"  Sharpe:       {m.get('sharpe_ratio', 0):.2f}")
    print(f"  Max DD:       {m.get('max_drawdown_pct', 0):.1f}%")
    print(f"  Total Ret:    {m.get('total_return_pct', 0):.1f}%")
    expired_pct = m.get('expired_pct', 0)
    if expired_pct:
        print(f"  Expired:      {expired_pct:.1f}%")

    # По типам сигналов
    sig_perf = m.get("signal_performance", {})
    if sig_perf:
        print()
        print("  По типам сигналов:")
        for sig_type, sp in sig_perf.items():
            wr = sp.get("win_rate", 0)
            ar = sp.get("avg_r", 0)
            n  = sp.get("count", 0)
            print(f"    {sig_type:<22} n={n:<4} WR={wr:.0f}%  avgR={ar:.2f}")

    # Отдельно детали по confluence
    conf_trades = [t for t in trades if t.signal_type == "confluence"]
    if conf_trades:
        from backtesting_engine import BacktestResult
        wins = [t for t in conf_trades if t.result == BacktestResult.WIN]
        avg_r = sum(t.r_multiple for t in conf_trades) / len(conf_trades)
        print()
        print(f"  Confluence trades: {len(conf_trades)}  WR={len(wins)/len(conf_trades)*100:.0f}%  avgR={avg_r:.2f}")

    print(f"{'─'*55}")
    print()


async def run(args):
    from backtesting_engine import BacktestingEngine, BacktestConfig

    # Даты
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if args.days:
        start = now - timedelta(days=args.days)
        end = now
    else:
        start = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end   = datetime.strptime(args.to_date,   "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.to_date else now

    # Нормализуем символ: btc/usdt → BTC/USDT
    symbol = args.symbol.upper().replace(" ", "")
    strategy = args.strategy
    tp_rr = args.tp_rr if args.tp_rr else (3.0 if strategy == "confluence_scanner" else 2.0)

    cfg = BacktestConfig(
        symbol=symbol,
        timeframe=args.tf,
        start_date=start,
        end_date=end,
        use_htf_filter=not args.no_htf,
        use_pivot_filter=not args.no_pp,
        tp_r=tp_rr,
        strategy=strategy,
        strategy_config={"tp_rr": tp_rr, "min_strength": 60},
    )

    print(f"\n🚀 Запуск бэктеста: {strategy} | {symbol} | {args.tf}")
    print(f"   Период: {start.strftime('%d.%m.%Y')} → {end.strftime('%d.%m.%Y')}")
    print(f"   HTF фильтр: {'✓' if cfg.use_htf_filter else '✗'}  "
          f"PP фильтр: {'✓' if cfg.use_pivot_filter else '✗'}  "
          f"TP: {tp_rr:.1f}R")

    engine = BacktestingEngine(cfg)
    result = None
    try:
        result = await engine.run_backtest()
    except Exception as e:
        print(f"\n❌ Ошибка бэктеста: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Закрываем exchange всегда — предотвращает "Unclosed client session"
        try:
            await engine._swap_exchange.close()
        except Exception:
            pass

    if result is None:
        sys.exit(1)

    print_results(result, strategy, symbol, args.tf)


def main():
    parser = argparse.ArgumentParser(
        description="Бэктест торговых стратегий Oko MTF Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--strategy", default="default",
                        help="Стратегия: default|confluence_scanner|conservative (дефолт: default)")
    parser.add_argument("--symbol", default="BTC/USDT",
                        help="Торговая пара (дефолт: BTC/USDT)")
    parser.add_argument("--tf", default="1h",
                        help="Таймфрейм: 15m|1h|4h (дефолт: 1h)")
    parser.add_argument("--days", type=int, default=None,
                        help="Количество дней назад от сегодня")
    parser.add_argument("--from", dest="from_date", default="2026-01-01",
                        help="Дата начала YYYY-MM-DD (дефолт: 2026-01-01)")
    parser.add_argument("--to", dest="to_date", default=None,
                        help="Дата конца YYYY-MM-DD (дефолт: сегодня)")
    parser.add_argument("--no-htf", action="store_true",
                        help="Отключить HTF trend фильтр")
    parser.add_argument("--no-pp", action="store_true",
                        help="Отключить weekly PP фильтр")
    parser.add_argument("--tp-rr", type=float, default=None,
                        help="RR для TP (дефолт: 3.0 для confluence_scanner, 2.0 для остальных)")
    parser.add_argument("--list-strategies", action="store_true",
                        help="Показать список стратегий и выйти")

    args = parser.parse_args()

    if args.list_strategies:
        list_strategies()
        return

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
