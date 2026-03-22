#!/usr/bin/env python3
"""
Universe Backtest — бэктест на случайной выборке топ-200 альтов.

Запуск:
  python scripts/run_universe_backtest.py                     # дефолт: 30 монет, Binance, 2022-2026
  python scripts/run_universe_backtest.py --n 10 --seed 42    # быстрый тест
  python scripts/run_universe_backtest.py --source cryptocom  # другой источник
  python scripts/run_universe_backtest.py --symbols BTC/USDT ETH/USDT SOL/USDT  # фиксированный список

Выводит:
  - Сводная таблица по символам (WR, AvgR, Sharpe, MaxDD)
  - Разбивка по годам
  - Monte Carlo агрегат
  - JSON-отчёт в data/universe_backtest_{timestamp}.json
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

# Подавим шум от библиотек
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _year_of_bar(ts_ms: int) -> int:
    return datetime.utcfromtimestamp(ts_ms / 1000).year


def _split_trades_by_year(trades: list) -> dict:
    """Группирует сделки по году открытия."""
    by_year = {}
    for t in trades:
        y = _year_of_bar(int(t.entry_time)) if hasattr(t, 'entry_time') and t.entry_time else 0
        by_year.setdefault(y, []).append(t)
    return by_year


def _calc_summary(trades: list) -> dict:
    """Базовые метрики по списку сделок."""
    if not trades:
        return {}
    from scripts.backtesting_engine import BacktestResult
    wins = [t for t in trades if t.result == BacktestResult.WIN]
    wr = len(wins) / len(trades) * 100
    rs = [t.r_multiple for t in trades]
    avg_r = float(np.mean(rs))
    return {
        "trades": len(trades),
        "win_rate": round(wr, 1),
        "avg_r": round(avg_r, 3),
    }


def _print_separator(char="─", width=90):
    print(char * width)


def _print_results_table(results: list):
    """Выводит сводную таблицу по символам."""
    _print_separator("═")
    print(f"{'Символ':<14} {'Сделок':>6} {'WR%':>6} {'AvgR':>6} {'Sharpe':>7} {'MaxDD%':>8} {'Return%':>8}")
    _print_separator()
    for r in results:
        m = r.get("metrics", {})
        sym = r["symbol"][:13]
        print(
            f"{sym:<14} {m.get('total_trades',0):>6} "
            f"{m.get('win_rate',0):>6.1f} "
            f"{m.get('avg_r_multiple',0):>6.3f} "
            f"{m.get('sharpe_ratio',0):>7.2f} "
            f"{m.get('max_drawdown_pct',0):>8.1f} "
            f"{m.get('total_return_pct',0):>8.1f}"
        )
    _print_separator()


def _print_year_breakdown(all_trades: list):
    """Выводит метрики по годам."""
    from scripts.backtesting_engine import BacktestResult
    by_year = {}
    for t in all_trades:
        y = getattr(t, 'year', None)
        if y is None:
            continue
        by_year.setdefault(y, []).append(t)
    if not by_year:
        return
    print("\nРазбивка по годам:")
    _print_separator()
    print(f"{'Год':>6} {'Сделок':>7} {'WR%':>7} {'AvgR':>7}")
    _print_separator()
    for yr in sorted(by_year):
        s = _calc_summary(by_year[yr])
        print(f"  {yr:>4}  {s['trades']:>7}  {s['win_rate']:>6.1f}%  {s['avg_r']:>6.3f}")
    _print_separator()


def _aggregate_metrics(results: list) -> dict:
    """Агрегирует метрики по всем символам (медианы)."""
    all_wr = [r["metrics"].get("win_rate", 0) for r in results if r.get("metrics", {}).get("total_trades", 0) >= 5]
    all_r  = [r["metrics"].get("avg_r_multiple", 0) for r in results if r.get("metrics", {}).get("total_trades", 0) >= 5]
    if not all_wr:
        return {}
    return {
        "symbols_tested": len(results),
        "symbols_valid":  len(all_wr),
        "median_wr":      round(float(np.median(all_wr)), 1),
        "median_avg_r":   round(float(np.median(all_r)), 3),
        "mean_wr":        round(float(np.mean(all_wr)), 1),
        "mean_avg_r":     round(float(np.mean(all_r)), 3),
    }


# ── Основная логика ───────────────────────────────────────────────────────────

async def run_universe_backtest(
    n: int = 30,
    seed: int = 42,
    strata: tuple = (10, 10, 10),
    symbols: Optional[List[str]] = None,
    data_source: str = "binance",
    start_year: int = 2022,
    end_year: int = 2026,
    concurrency: int = 3,
) -> dict:
    """
    Главная функция: запускает бэктест на выборке символов.

    Параметры:
        n           — кол-во монет из CoinGecko (если symbols не задан)
        seed        — random seed
        strata      — стратификация (топ-10, 11-50, 51-200)
        symbols     — фиксированный список символов (переопределяет n/seed)
        data_source — "binance" | "cryptocom" | "bingx"
        start_year  — начальный год бэктеста
        end_year    — конечный год (включительно, до конца года)
        concurrency — сколько символов параллельно
    """
    from scripts.backtesting_engine import run_bot_backtest, monte_carlo_from_trades

    start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end_dt   = datetime(end_year, 3, 22, tzinfo=timezone.utc)  # до сегодня

    # 1. Получаем список символов
    if symbols:
        universe = symbols
        print(f"\n🔬 Universe Backtest: {len(universe)} символов (фиксированный список)")
    else:
        print(f"\n🌐 Загрузка universe из CoinGecko (n={n}, seed={seed}, strata={strata})...")
        from scripts.universe_builder import build_universe
        universe = await build_universe(n=n, seed=seed, strata=strata)
        print(f"✅ Universe: {len(universe)} символов")

    print(f"📅 Период: {start_dt.date()} → {end_dt.date()}")
    print(f"📡 Источник: {data_source}")
    print(f"🪙 Символы: {', '.join(universe[:10])}{'...' if len(universe) > 10 else ''}\n")

    # 2. Запускаем бэктест по символам (с ограниченным параллелизмом)
    sem = asyncio.Semaphore(concurrency)
    all_results = []
    all_trades = []

    async def _run_one(sym: str):
        async with sem:
            print(f"  ▶ {sym} ...", end="", flush=True)
            try:
                r = await run_bot_backtest(
                    symbol=sym,
                    start_date=start_dt,
                    end_date=end_dt,
                    data_source=data_source,
                    atr_period=43, atr_factor=1.0,
                    tp_r=2.0, tsl_activation_r=1.0,
                    on_progress=None,
                )
            except Exception as e:
                logger.warning("Ошибка %s: %s", sym, e)
                r = {}

            trades = r.get("trades", [])
            n_tr = len(trades)
            m = r.get("metrics", {})
            wr  = m.get("win_rate", 0)
            avg = m.get("avg_r_multiple", 0)
            print(f" {n_tr} сделок  WR={wr:.0f}%  AvgR={avg:.2f}")

            # Прикрепляем год к каждой сделке для разбивки
            for t in trades:
                if hasattr(t, 'open_bar_idx'):
                    pass  # TODO: use actual entry bar time
                t.year = start_year  # заглушка (нет entry_time в BacktestTrade — добавим позже)

            all_results.append({**r, "symbol": sym})
            all_trades.extend(trades)

    await asyncio.gather(*[_run_one(sym) for sym in universe])

    # 3. Фильтруем символы без сделок
    valid_results = [r for r in all_results if r.get("metrics", {}).get("total_trades", 0) > 0]

    print(f"\n{'='*90}")
    print(f"  Результаты: {len(valid_results)}/{len(universe)} символов с торговлей")
    _print_results_table(sorted(valid_results, key=lambda r: r.get("metrics", {}).get("avg_r_multiple", 0), reverse=True))

    # 4. Агрегат
    agg = _aggregate_metrics(valid_results)
    if agg:
        print(f"\nАгрегат ({agg['symbols_valid']} символов ≥5 сделок):")
        print(f"  Медиана  WR={agg['median_wr']}%  AvgR={agg['median_avg_r']}")
        print(f"  Среднее  WR={agg['mean_wr']}%  AvgR={agg['mean_avg_r']}")

    # 5. Monte Carlo по всем сделкам
    if len(all_trades) >= 20:
        mc = monte_carlo_from_trades(all_trades)
        print(f"\nMonte Carlo ({mc['n_trades']} сделок всего):")
        print(f"  WR:     p5={mc['wr_p5']}%  p50={mc['wr_p50']}%  p95={mc['wr_p95']}%")
        print(f"  Return: p5={mc['ret_p5']}%  p50={mc['ret_p50']}%  p95={mc['ret_p95']}%")
        print(f"  Max DD: медиана={mc['dd_p50']}%  worst-5%={mc['dd_p5']}%")
    else:
        mc = {}

    # 6. JSON-отчёт
    report = {
        "run_at":     datetime.utcnow().isoformat(),
        "universe":   universe,
        "data_source": data_source,
        "period":     {"start": str(start_dt.date()), "end": str(end_dt.date())},
        "aggregate":  agg,
        "monte_carlo": mc,
        "symbols": [
            {
                "symbol":  r["symbol"],
                "metrics": r.get("metrics", {}),
            }
            for r in valid_results
        ],
    }

    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"universe_backtest_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📄 Отчёт сохранён: {out_path}")

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universe Backtest — бэктест на выборке топ-200 альтов")
    parser.add_argument("--n",       type=int,   default=30,        help="Кол-во монет из CoinGecko")
    parser.add_argument("--seed",    type=int,   default=42,        help="Random seed")
    parser.add_argument("--strata",  type=str,   default="10,10,10",help="Стратификация тиров")
    parser.add_argument("--source",  type=str,   default="binance", help="Источник данных: binance | cryptocom | bingx")
    parser.add_argument("--start",   type=int,   default=2022,      help="Начальный год")
    parser.add_argument("--end",     type=int,   default=2026,      help="Конечный год")
    parser.add_argument("--conc",    type=int,   default=3,         help="Параллельных символов")
    parser.add_argument("--symbols", nargs="+",  default=None,      help="Фиксированный список символов")
    args = parser.parse_args()

    strata = tuple(int(x) for x in args.strata.split(","))

    asyncio.run(run_universe_backtest(
        n=args.n,
        seed=args.seed,
        strata=strata,
        symbols=args.symbols,
        data_source=args.source,
        start_year=args.start,
        end_year=args.end,
        concurrency=args.conc,
    ))
