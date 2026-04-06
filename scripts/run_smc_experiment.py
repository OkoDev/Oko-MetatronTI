#!/usr/bin/env python3
"""
SMC эксперимент: cfg1/cfg2/cfg3 — проверяет гипотезу "OB+FVG улучшает WR".

cfg1: use_smc=True, smc_require_ob=False  — базовая линия (без фильтра OB)
cfg2: use_smc=True, smc_require_ob=True   — только сделки с OB у цены
cfg3: use_smc=True, smc_require_ob=True, smc_require_fvg=True  — суперсетап OB+FVG

Запуск:
  python scripts/run_smc_experiment.py
  python scripts/run_smc_experiment.py --symbols ETH/USDT SOL/USDT
  python scripts/run_smc_experiment.py --start 2023 --end 2024
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
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


def _sep(char="─", width=80):
    print(char * width)


def _fmt(m: dict) -> str:
    if not m:
        return "—"
    return (f"n={m.get('total_trades',0)}"
            f"  WR={m.get('win_rate',0):.1f}%"
            f"  AvgR={m.get('avg_r_multiple',0):.3f}"
            f"  Sharpe={m.get('sharpe_ratio',0):.2f}"
            f"  DD={m.get('max_drawdown_pct',0):.1f}%")


async def run_smc_configs(
    symbols: List[str],
    data_source: str,
    start_year: int,
    end_year: int,
    concurrency: int,
    smc_ob_pairs: Optional[List[str]] = None,
) -> dict:
    from scripts.backtesting_engine import run_bot_backtest

    start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end_dt   = datetime(end_year, 3, 22, tzinfo=timezone.utc)

    configs = [
        {"name": "cfg1_no_filter",    "use_smc": True, "smc_require_ob": False, "smc_require_fvg": False},
        {"name": "cfg2_ob_filter",    "use_smc": True, "smc_require_ob": True,  "smc_require_fvg": False},
        {"name": "cfg3_ob_fvg_super", "use_smc": True, "smc_require_ob": True,  "smc_require_fvg": True},
    ]

    sem = asyncio.Semaphore(concurrency)
    results = {c["name"]: [] for c in configs}

    async def _run_one(sym: str, cfg: dict):
        async with sem:
            print(f"  ▶ {sym} [{cfg['name']}] ...", end="", flush=True)
            try:
                r = await run_bot_backtest(
                    symbol=sym,
                    start_date=start_dt,
                    end_date=end_dt,
                    data_source=data_source,
                    atr_period=43, atr_factor=1.0,
                    tp_r=2.0, tsl_activation_r=1.0,
                    use_smc=cfg["use_smc"],
                    smc_require_ob=cfg.get("smc_require_ob", False),
                    smc_require_fvg=cfg.get("smc_require_fvg", False),
                    smc_ob_pairs=smc_ob_pairs,
                )
            except Exception as e:
                logger.warning("Ошибка %s [%s]: %s", sym, cfg["name"], e)
                r = {}
            m = r.get("metrics", {})
            print(f" {m.get('total_trades',0)} trades  WR={m.get('win_rate',0):.0f}%  AvgR={m.get('avg_r_multiple',0):.3f}")
            results[cfg["name"]].append({"symbol": sym, "metrics": m})

    # Запускаем каждый символ × каждый конфиг последовательно по конфигам
    for cfg in configs:
        print(f"\n--- {cfg['name']} ---")
        tasks = [_run_one(sym, cfg) for sym in symbols]
        await asyncio.gather(*tasks)

    return results


def _aggregate(sym_results: list) -> dict:
    """Агрегат метрик по символам."""
    valid = [r for r in sym_results if r.get("metrics", {}).get("total_trades", 0) >= 5]
    if not valid:
        return {}
    wrs = [r["metrics"]["win_rate"] for r in valid]
    avgs = [r["metrics"]["avg_r_multiple"] for r in valid]
    return {
        "n_valid": len(valid),
        "median_wr": round(float(np.median(wrs)), 1),
        "median_avg_r": round(float(np.median(avgs)), 3),
        "mean_wr": round(float(np.mean(wrs)), 1),
        "mean_avg_r": round(float(np.mean(avgs)), 3),
    }


async def main(args):
    symbols = args.symbols or ["ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT", "XRP/USDT"]
    data_source = args.source
    start_year = args.start
    end_year = args.end
    concurrency = args.conc

    print(f"\nSMC Experiment")
    print(f"  Symbols:    {', '.join(symbols)}")
    print(f"  Period:     {start_year}-{end_year}")
    print(f"  Source:     {data_source}")
    print(f"  Concurrency: {concurrency}\n")

    # smc_ob_pairs: None = применять OB-фильтр ко всем символам
    # --ob-pairs BTC/USDT ETH/USDT = только к этим (per-asset режим)
    ob_pairs = args.ob_pairs if args.ob_pairs else None
    if ob_pairs:
        print(f"  OB-фильтр применяется только к: {', '.join(ob_pairs)}")
    results = await run_smc_configs(symbols, data_source, start_year, end_year, concurrency, smc_ob_pairs=ob_pairs)

    # ── Итоговая таблица ─────────────────────────────────────────────────────
    print("\n")
    _sep("═")
    print(f"{'Конфиг':<24} {'n':>5} {'Med WR%':>9} {'Med AvgR':>10} {'Mean WR%':>10} {'Mean AvgR':>11}")
    _sep()
    agg_data = {}
    for cfg_name, sym_res in results.items():
        agg = _aggregate(sym_res)
        agg_data[cfg_name] = agg
        if not agg:
            print(f"{cfg_name:<24}  {'—':>5}")
            continue
        print(
            f"{cfg_name:<24}"
            f"  {agg['n_valid']:>5}"
            f"  {agg['median_wr']:>8.1f}%"
            f"  {agg['median_avg_r']:>10.3f}"
            f"  {agg['mean_wr']:>9.1f}%"
            f"  {agg['mean_avg_r']:>10.3f}"
        )
    _sep()

    # ── Вывод по символам ─────────────────────────────────────────────────────
    print("\nПо символам:")
    _sep()
    for sym in symbols:
        print(f"\n  {sym}:")
        for cfg_name, sym_res in results.items():
            found = next((r for r in sym_res if r["symbol"] == sym), None)
            if found:
                m = found["metrics"]
                trades = m.get("total_trades", 0)
                wr     = m.get("win_rate", 0)
                avg_r  = m.get("avg_r_multiple", 0)
                print(f"    {cfg_name:<24}  {trades:>5} trades  WR={wr:.1f}%  AvgR={avg_r:.3f}")
    _sep()

    # ── JSON ─────────────────────────────────────────────────────────────────
    report = {
        "run_at": datetime.utcnow().isoformat(),
        "symbols": symbols,
        "data_source": data_source,
        "period": {"start": str(start_year), "end": str(end_year)},
        "configs": list(results.keys()),
        "aggregate": agg_data,
        "by_config": {
            cfg_name: [{"symbol": r["symbol"], "metrics": r["metrics"]} for r in sym_res]
            for cfg_name, sym_res in results.items()
        },
    }
    out_dir = Path(__file__).parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"smc_experiment_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nОтчёт: {out_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SMC Experiment cfg1/cfg2/cfg3")
    parser.add_argument("--symbols",  nargs="+", default=None)
    parser.add_argument("--source",   default="binance")
    parser.add_argument("--start",    type=int, default=2023)
    parser.add_argument("--end",      type=int, default=2024)
    parser.add_argument("--conc",     type=int, default=2)
    parser.add_argument("--ob-pairs", nargs="+", default=None,
                        help="Per-asset OB-фильтр: применять только к этим символам (None=все).\n"
                             "Пример: --ob-pairs ETH/USDT BTC/USDT SOL/USDT BNB/USDT XRP/USDT")
    args = parser.parse_args()
    asyncio.run(main(args))
