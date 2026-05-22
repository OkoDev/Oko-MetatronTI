"""
ARCH-104 Observer Loop — наблюдение + опциональная регистрация VST сделок.

Запускается параллельно с основным scan_loop. Раз в N минут:
1. Для каждой пары собирает текущие active SMC/indicator flags
2. Прогоняет через ARCH104SignalAdapter (registry + RI v1)
3. Логирует решения в `risk_decisions_log` table
4. Если `arch104.vst_trading.enabled` в config + decision.apply=True —
   регистрирует сделку через trade_simulator (signal_type='arch104').

D-028 (2026-05-20): VST на BingX = production execution с реальными ценами.
Shadow поверх не нужен — VST trading сразу даёт реальные R-multiple данные.

D-030 (2026-05-21): VST trading enabled — паттерны открывают позиции через
register_trade_async когда decision.apply=True. signal_type='arch104' для
разделения с остальными стратегиями в БД.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Scan период — 10 минут (D-029 2026-05-21: было 300s, повышено до 600s
# чтобы снизить фоновую нагрузку на BingX API. Patterns живут часами,
# scan каждые 10 мин достаточен для shadow logging.)
OBSERVER_INTERVAL_SECONDS = 600

# Минимум баров для compute_flags
MIN_BARS = 200

# Параллелизм — observer не должен душить API больше чем scan_loop
# D-029 2026-05-21: было 8, снижено до 4 — main scan_loop тоже параллелит API,
# суммарная нагрузка на 241 паре приводила к HARD timeout в trading_intelligence
# (+70% timeout/час post-restart vs pre-restart).
OBSERVER_CONCURRENCY = 4


async def arch104_observer_loop(bot, interval_seconds: int = OBSERVER_INTERVAL_SECONDS):
    """Главный loop — раз в interval_seconds логирует ARCH-104 decisions для всех пар."""
    # Lazy imports
    try:
        from core.intelligence.arch104_signal_adapter import ARCH104SignalAdapter
    except ImportError as e:
        logger.error("ARCH-104 adapter import failed: %s", e)
        return

    adapter = ARCH104SignalAdapter(
        db_path=str(getattr(bot, "db_path", "subscriptions.db")),
        enable_v2=False,           # v2 отключён в Stage 1
        enable_lifecycle_check=True,
    )
    logger.info("[ARCH-104 observer] started. %d patterns loaded. Interval=%ds",
                len(adapter.registry.patterns), interval_seconds)

    # D-045 (2026-05-23): первый scan через 60s warmup (вместо полного interval).
    # Раньше после рестарта observer ждал 10 мин до первого scan + 5-7 мин scan =
    # 15-17 мин до первого результата. Теперь — 60s + 5-7 мин = ~7 мин total.
    # 60s достаточно для warmup data_collector кеша при старте.
    first_cycle = True
    while True:
        try:
            sleep_sec = 60 if first_cycle else interval_seconds
            first_cycle = False
            await asyncio.sleep(sleep_sec)
            t0 = time.time()
            scanned = 0
            decisions = 0

            # Получаем список пар из active subscriptions / pairs
            pairs = await _get_active_pairs(bot)
            if not pairs:
                logger.debug("[ARCH-104 observer] no active pairs")
                continue

            sem = asyncio.Semaphore(OBSERVER_CONCURRENCY)
            scanned_lock = asyncio.Lock()
            counters = {"scanned": 0, "decisions": 0}

            async def _bounded_scan(sym):
                async with sem:
                    try:
                        result = await _scan_one_pair(bot, sym, adapter)
                        async with scanned_lock:
                            counters["scanned"] += 1
                            if result:
                                counters["decisions"] += 1
                    except Exception as e:
                        logger.debug("[ARCH-104 observer] %s: %s", sym, e)

            await asyncio.gather(*[_bounded_scan(s) for s in pairs])
            scanned = counters["scanned"]
            decisions = counters["decisions"]

            elapsed = time.time() - t0
            logger.info("[ARCH-104 observer] scanned=%d decisions=%d in %.1fs (pairs=%d)",
                        scanned, decisions, elapsed, len(pairs))
            if elapsed > interval_seconds * 0.9:
                logger.warning("[ARCH-104 observer] цикл %.1fs близок к interval %ds — рассмотреть OBSERVER_CONCURRENCY+",
                               elapsed, interval_seconds)

        except asyncio.CancelledError:
            logger.info("[ARCH-104 observer] cancelled")
            break
        except Exception as e:
            logger.exception("[ARCH-104 observer] error: %s", e)
            await asyncio.sleep(60)


async def _get_active_pairs(bot) -> list[str]:
    """Get pairs из bot context — те же что сканит scan_all_pairs."""
    # 1. Primary: bot.monitored_pairs (тот же источник что и scan_all_pairs)
    mp = getattr(bot, "monitored_pairs", None)
    if mp:
        try:
            pairs = list(mp)
            if pairs:
                return pairs
        except Exception:
            pass

    # 2. Fallback: top пары
    return [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT",
        "XRP/USDT:USDT", "DOGE/USDT:USDT", "AVAX/USDT:USDT", "LINK/USDT:USDT",
        "DOT/USDT:USDT", "MATIC/USDT:USDT",
    ]


async def _fetch_df(data_collector, symbol: str, tf: str, limit: int):
    """Загружает OHLCV, приводит к стандартному виду.

    D-042 (2026-05-23): bot.data_collector.get_ohlcv возвращает колонку 'time'
    (не 'ts' как ccxt direct). Без преобразования в datetime index
    pd.Timedelta shift в _shift() не работает корректно — flags после shift
    некорректны → reindex даёт мусор → active_flags пусто → decisions=0
    на каждом scan. Это был root cause 5+ часов decisions=0 после
    D-035/D-036/D-040 фиксов — pivots и hidden div считались правильно,
    но observer не доходил до find_matching с правильными active_flags.
    """
    try:
        df = await data_collector.get_ohlcv(symbol, timeframe=tf, limit=limit)
    except Exception:
        return None
    if df is None or len(df) < 50:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    # Поддерживаем оба формата: 'ts' (ccxt) и 'time' (data_collector)
    ts_col = "ts" if "ts" in df.columns else ("time" if "time" in df.columns else None)
    if ts_col is not None:
        df[ts_col] = pd.to_datetime(df[ts_col], unit="ms", utc=True, errors="coerce")
        df = df.set_index(ts_col)
    # Если index всё ещё не datetime — bail (lookahead-shift не сработает корректно)
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    return df[["open", "high", "low", "close", "volume"]].dropna().sort_index()


async def _scan_one_pair(bot, symbol: str, adapter) -> bool:
    """Scan одной пары на ВСЕХ 4 TF (5m, 15m, 1h, 4h) → log decisions per TF.

    Логика:
      - Fetch данные для всех 4 TF параллельно
      - Compute flags на каждом TF (свои значения)
      - Для каждой LTF (5m/15m): aggregate flags с HTF (1h/4h/1d) через reindex
      - Pass total flag set в adapter для каждого TF detection
    """
    data_collector = getattr(bot, "data_collector", None)
    if data_collector is None:
        return False

    # Fetch 4 TF параллельно
    fetch_tasks = await asyncio.gather(
        _fetch_df(data_collector, symbol, "5m", 500),
        _fetch_df(data_collector, symbol, "15m", 400),
        _fetch_df(data_collector, symbol, "1h", 300),
        _fetch_df(data_collector, symbol, "4h", 200),
        return_exceptions=False,
    )
    df_5m, df_15m, df_1h, df_4h = fetch_tasks
    if df_1h is None or len(df_1h) < MIN_BARS:
        return False

    # Lazy import combinator
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools" / "pattern_mining"))
        import combinator_v2 as cb
    except Exception as e:
        logger.debug("[ARCH-104] combinator_v2 import: %s", e)
        return False

    # Compute flags per TF (исходные значения на собственной сетке).
    # D-035 (2026-05-22): include_pivots=True для 1h — без этого pivot_*_1D/1W
    # флаги всегда FALSE, и паттерны registry с pivot anchors никогда не срабатывают
    # в live observer (хотя в backtest pivot flags считаются через cb.process_symbol).
    # Это был корень decisions=0 на 9+ часов — registry имеет десятки patterns с pivot,
    # они невидимы без этого флага.
    try:
        f_1h = cb.compute_flags(df_1h, "1h", include_pivots=True)
        f_4h_src = cb.compute_flags(df_4h, "4h") if df_4h is not None and len(df_4h) >= 30 else None
        f_1d_src = cb.compute_flags(cb.aggregate_tf(df_1h, "1d"), "1d")
        f_15m_src = cb.compute_flags(df_15m, "15m") if df_15m is not None and len(df_15m) >= 100 else None
        f_5m_src = cb.compute_flags(df_5m, "5m") if df_5m is not None and len(df_5m) >= 100 else None
    except Exception as e:
        logger.debug("[ARCH-104] %s compute_flags failed: %s", symbol, e)
        return False

    # Shift HTF index перед reindex (lookahead-safe — D-001)
    def _shift(df_src, hours):
        if df_src is None:
            return None
        c = df_src.copy()
        c.index = c.index + pd.Timedelta(hours=hours)
        return c

    f_4h_shifted = _shift(f_4h_src, 4)
    f_1d_shifted = _shift(f_1d_src, 24)

    # Контекст (минимальный — TODO: расширить из bot state)
    context = {
        "signal_strength": 75,
        "regime": "UNKNOWN",
        "btc_regime": "UNKNOWN",
        "funding_pct_8h": 0.0,
        "ema_avg_r_30d": 0.0,
        "sharpe_30d": 0.0,
        "n_trades_30d": 0,
        "warnings_24h": 0,
    }

    any_decision = False

    # ─── Per-TF scan ───
    # Каждый TF — своя detection grid + reindexed HTF flags
    tf_configs = [
        ("5m",  df_5m,  f_5m_src,  10),    # sl_lookback bars
        ("15m", df_15m, f_15m_src, 10),
        ("1h",  df_1h,  f_1h,      10),
        ("4h",  df_4h,  f_4h_src,  10),
    ]

    for det_tf, df_det, f_det_src, sl_lookback in tf_configs:
        if df_det is None or f_det_src is None or len(df_det) < sl_lookback + 10:
            continue

        # Combine flags: detection TF native + HTF reindexed (lookahead-safe).
        # D-043 (2026-05-23): astype(bool) после fillna убирает pandas FutureWarning
        # про downcasting object dtype. Reindex даёт object dtype (NaN на новых index'ах),
        # fillna(False) заменяет NaN, astype(bool) явно конвертирует — без warning.
        def _reindex_bool(df_src, idx):
            return df_src.reindex(idx, method="ffill").fillna(False).astype(bool)
        try:
            target_idx = df_det.index
            combined = [f_det_src]
            if f_4h_shifted is not None and det_tf != "4h":
                combined.append(_reindex_bool(f_4h_shifted, target_idx))
            if f_1d_shifted is not None:
                combined.append(_reindex_bool(f_1d_shifted, target_idx))
            # Для 5m: добавить 15m+1h в reindex
            if det_tf == "5m":
                if f_15m_src is not None:
                    f_15m_shift = _shift(f_15m_src, 0)
                    f_15m_shift.index = f_15m_shift.index + pd.Timedelta(minutes=15)
                    combined.append(_reindex_bool(f_15m_shift, target_idx))
                f_1h_shift = f_1h.copy()
                f_1h_shift.index = f_1h_shift.index + pd.Timedelta(hours=1)
                combined.append(_reindex_bool(f_1h_shift, target_idx))
            elif det_tf == "15m":
                f_1h_shift = f_1h.copy()
                f_1h_shift.index = f_1h_shift.index + pd.Timedelta(hours=1)
                combined.append(_reindex_bool(f_1h_shift, target_idx))

            all_flags_df = pd.concat(combined, axis=1).astype(bool)
        except Exception as e:
            logger.debug("[ARCH-104] %s %s combine failed: %s", symbol, det_tf, e)
            continue

        # Last row = текущее состояние на этом TF
        last_row = all_flags_df.iloc[-1]
        active_flags = set(last_row[last_row].index.tolist())
        if not active_flags:
            continue

        price = float(df_det["close"].iloc[-1])
        sl_long = float(df_det["low"].iloc[-(sl_lookback + 1):].min()) * 0.999
        sl_short = float(df_det["high"].iloc[-(sl_lookback + 1):].max()) * 1.001

        # Per direction
        for direction in ["LONG", "SHORT"]:
            sl_price = sl_long if direction == "LONG" else sl_short
            decision = adapter.process(
                symbol=f"{symbol}@{det_tf}",
                direction=direction,
                active_flags=active_flags,
                price=price,
                sl_price=sl_price,
                context=context,
                detection_tf=det_tf,         # NEW: фильтр patterns по их detection_tf
            )
            if decision.pattern_id:
                any_decision = True
                logger.info(
                    "[ARCH-104] %s@%s %s pattern=%s apply=%s risk_pct=%.2f%% sl=%.4f",
                    symbol, det_tf, direction, decision.pattern_id,
                    decision.apply, decision.risk_pct, sl_price,
                )
                # D-030: VST trading — если decision.apply и flag в config
                if decision.apply and bool(bot.config.get("arch104.vst_trading.enabled", False)):
                    await _try_register_vst_trade(
                        bot, symbol, det_tf, direction, decision,
                        adapter.registry, price, sl_price,
                    )

    return any_decision


# ─────────── VST trading helper (D-030) ───────────

async def _try_register_vst_trade(
    bot, symbol: str, det_tf: str, direction: str, decision,
    registry, price: float, sl_price: float,
):
    """Регистрирует ARCH-104 сделку через trade_simulator (VST).

    SL = sl_price (swing low/high из _scan_one_pair, lookahead-safe)
    TP = entry ± fallback_tp_r × SL distance (по pattern.tp.fallback_tp_r)
    signal_type = 'arch104' (override в extra_features)
    """
    try:
        from core.signals.signal_models import (
            TradingRecommendation, SignalDirection, MarketContext,
        )
    except ImportError as e:
        logger.warning("[ARCH-104 VST] import failed: %s", e)
        return

    pattern = registry.get(decision.pattern_id)
    if pattern is None:
        return

    sl_dist = abs(price - sl_price)
    if sl_dist <= 0:
        return

    fallback_tp_r = float(getattr(pattern, "fallback_tp_r", 2.0))
    if direction == "LONG":
        tp_price = price + fallback_tp_r * sl_dist
        side_enum = SignalDirection.LONG
        action = "BUY"
    else:
        tp_price = price - fallback_tp_r * sl_dist
        side_enum = SignalDirection.SHORT
        action = "SELL"

    # strength = производная от pattern.weight (10-19) → 60-95
    strength = max(60, min(95, 50 + int(getattr(pattern, "weight", 10)) * 2))
    confidence = max(0.55, min(0.95, 0.55 + float(decision.risk_pct) * 0.1))

    rec = TradingRecommendation(
        symbol=symbol,
        action=action,
        direction=side_enum,
        overall_strength=strength,
        confidence=confidence,
        risk_level="MEDIUM",
        signals_count=1,
        supporting_signals=[],
        conflicting_signals=[],
        market_context=MarketContext(
            symbol=symbol, current_price=price,
            volume_24h=0.0, volume_change_24h=0.0, price_change_24h=0.0,
        ),
        entry_price=price,
        stop_loss=sl_price,
        take_profit=tp_price,
        sl_source=f"arch104:swing_{det_tf}",
        tp_source=f"arch104:{getattr(pattern, 'tp_strategy', 'no_trail')}_r{fallback_tp_r}",
    )

    extra = {
        "signal_type_override": "arch104",
        "trigger_source": f"arch104:{decision.pattern_id}",
        "arch104_pattern_id": decision.pattern_id,
        "arch104_detection_tf": det_tf,
        "arch104_risk_pct": float(decision.risk_pct),
        "arch104_leverage": int(getattr(decision, "leverage", 1)),
        "arch104_time_exit_hours": int(getattr(pattern, "time_exit_hours", 24)),
        "arch104_tp_strategy": getattr(pattern, "tp_strategy", "no_trail"),
        "arch104_matched_patterns": list(getattr(decision, "matched_patterns", [])),
        "trade_mode": "arch104",   # dedup: разные режимы не блокируют
    }

    # D-044 (2026-05-23): идём через trade_router (как atr_change/confluence/etc.)
    # для exchange execution на VST. Без router register_trade_async создаёт
    # только SIM запись (exchange_order_id=NULL).
    trade_id = None
    exchange_id = None
    if bool(bot.config.get("signal_router.enabled", False)) and hasattr(bot, "trade_router"):
        try:
            _sr_result = await bot.trade_router.submit(
                rec, source="arch104", extra_features=extra,
            )
            trade_id = _sr_result.trade_id
            exchange_id = getattr(_sr_result, "exchange_order_id", None)
            if not trade_id:
                _hd_names = ",".join(g for g, _ in getattr(_sr_result, "hard_drops", [])) or "none"
                logger.info(
                    "[ARCH-104 VST] %s@%s %s pattern=%s router dropped: %s",
                    symbol, det_tf, direction, decision.pattern_id, _hd_names,
                )
                return
        except Exception as e:
            logger.exception("[ARCH-104 VST] %s router error: %s", symbol, e)
            return
    else:
        # Fallback (router отключён) — SIM-only
        try:
            trade_id = await bot.trade_simulator.register_trade_async(
                rec, bot.data_collector, extra_features=extra,
            )
        except Exception as e:
            logger.exception("[ARCH-104 VST] %s register_trade_async error: %s", symbol, e)
            return

    if trade_id:
        logger.info(
            "[ARCH-104 VST] %s@%s %s pattern=%s → trade #%d str=%d sl=%.4f tp=%.4f risk=%.2f%% exch=%s",
            symbol, det_tf, direction, decision.pattern_id,
            trade_id, strength, sl_price, tp_price, float(decision.risk_pct),
            exchange_id or "none",
        )
    else:
        logger.info(
            "[ARCH-104 VST] %s@%s %s pattern=%s — dropped (dedup/gate/strength)",
            symbol, det_tf, direction, decision.pattern_id,
        )


# ─────────── Self-test ───────────

if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

    # Mock test — без bot context
    print("ARCH-104 Observer Loop — standalone module")
    print(f"  Default interval: {OBSERVER_INTERVAL_SECONDS}s ({OBSERVER_INTERVAL_SECONDS//60} min)")
    print("  Logs decisions to risk_decisions_log table")
    print("  Modes: observer (default), active (future)")
    print("\n✅ Ready to integrate via:")
    print("  asyncio.create_task(arch104_observer_loop(bot))  # in bot/core/bot.py")
