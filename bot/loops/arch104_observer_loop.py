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

from core.observability.decision_trace import record_drop

logger = logging.getLogger(__name__)

# Scan период — 10 минут (D-029 2026-05-21: было 300s, повышено до 600s
# чтобы снизить фоновую нагрузку на BingX API. Patterns живут часами,
# scan каждые 10 мин достаточен для shadow logging.)
OBSERVER_INTERVAL_SECONDS = 900

# Минимум баров для compute_flags
MIN_BARS = 200

# Параллелизм — observer не должен душить API больше чем scan_loop
# D-029 2026-05-21: было 8, снижено до 4 — main scan_loop тоже параллелит API,
# суммарная нагрузка на 241 паре приводила к HARD timeout в trading_intelligence
# (+70% timeout/час post-restart vs pre-restart).
OBSERVER_CONCURRENCY = 4

# DEV-232: TTL кэша HTF-флагов. Снижен 1800→600с (= ~1 цикл observer) чтобы
# gate реагировал на СОЗРЕВАНИЕ HTF-сетапа без лага → не запаздывать с ранним
# 5m-входом. Разгрузка сохраняется (строгость gate не трогаем, только свежесть).
# Стоимость: compute_flags на 1h/4h каждый цикл — дёшево (данные из общего кэша,
# REST не делается, только пересчёт индикаторов).
HTF_FLAGS_CACHE_TTL = 600.0


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
    # DEV-232: кэш HTF-флагов per-symbol между циклами. {symbol: (htf_flags_set, ts)}
    htf_flags_cache: dict[str, tuple[set, float]] = {}
    while True:
        try:
            sleep_sec = 60 if first_cycle else interval_seconds
            first_cycle = False
            await asyncio.sleep(sleep_sec)
            t0 = time.time()
            scanned = 0
            decisions = 0
            # DEV-232: счётчики разгрузки — сколько пар прошло HTF-gate (фетчили 5m)
            gate_stats = {"htf_only": 0, "ltf_fetched": 0}

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
                        result = await _scan_one_pair(bot, sym, adapter,
                                                      htf_flags_cache, gate_stats)
                        async with scanned_lock:
                            counters["scanned"] += 1
                            if result:
                                counters["decisions"] += 1
                    except Exception as e:
                        logger.warning("[ARCH-104 observer] %s: %s", sym, e)

            await asyncio.gather(*[_bounded_scan(s) for s in pairs])
            scanned = counters["scanned"]
            decisions = counters["decisions"]

            elapsed = time.time() - t0
            logger.info("[ARCH-104 observer] scanned=%d decisions=%d in %.1fs (pairs=%d) "
                        "[DEV-232 gate: ltf_fetched=%d htf_only=%d]",
                        scanned, decisions, elapsed, len(pairs),
                        gate_stats["ltf_fetched"], gate_stats["htf_only"])
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
                # ScanFairness (09.06): monitored_pairs = sorted (алфавит) → при нагрузке/семафоре
                # хвост (W-Z) систематически реже получал входы. scan уже shuffle'ит (scan_loop:2234),
                # а торговые observers (arch104/ote через _get_active_pairs) — НЕТ. Уравниваем.
                import random
                random.shuffle(pairs)
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


async def _scan_one_pair(bot, symbol: str, adapter,
                         htf_flags_cache: Optional[dict] = None,
                         gate_stats: Optional[dict] = None) -> bool:
    """Scan одной пары → log decisions per TF.

    DEV-232: HTF-gate на фетче. Сначала HTF (1h+4h+1d), вычисляем HTF-флаги
    (с кэшем между циклами), проверяем — может ли вообще сработать хоть один
    5m-паттерн (все его HTF-anchors активны). 5m фетчим ТОЛЬКО если gate открыт.
    15m фетчим всегда (дёшево — cache-hit от scan_loop, 15m=primary entry TF).

    Логика:
      - Fetch HTF (1h/4h) + compute HTF flags (+1d агрегат из 1h)
      - HTF-gate: open → fetch 5m, closed → skip 5m (экономия REST)
      - Для каждого detection TF: aggregate flags с HTF через reindex
    """
    data_collector = getattr(bot, "data_collector", None)
    if data_collector is None:
        return False

    # ARCH-118.3: ЧИСТЫЙ единый калькулятор из core (без sys.path/combinator_v2 хака)
    try:
        from core.calculators import combinator_core as cb
    except Exception as e:
        logger.debug("[ARCH-104] combinator_core import: %s", e)
        return False

    # ─── DEV-232: Шаг 1 — HTF first (1h+4h, 15m тоже — дёшев из кэша scan) ───
    fetch_tasks = await asyncio.gather(
        _fetch_df(data_collector, symbol, "15m", 400),
        _fetch_df(data_collector, symbol, "1h", 300),
        _fetch_df(data_collector, symbol, "4h", 200),
        return_exceptions=False,
    )
    df_15m, df_1h, df_4h = fetch_tasks
    if df_1h is None or len(df_1h) < MIN_BARS:
        return False

    # Compute HTF flags (исходные значения на собственной сетке).
    # D-035: include_pivots=True для 1h — без этого pivot_*_1D/1W всегда FALSE.
    try:
        f_1h = cb.compute_flags(df_1h, "1h", include_pivots=True)
        f_4h_src = cb.compute_flags(df_4h, "4h") if df_4h is not None and len(df_4h) >= 30 else None
        f_1d_src = cb.compute_flags(cb.aggregate_tf(df_1h, "1d"), "1d")
        f_15m_src = cb.compute_flags(df_15m, "15m") if df_15m is not None and len(df_15m) >= 100 else None
    except Exception as e:
        logger.debug("[ARCH-104] %s compute_flags failed: %s", symbol, e)
        return False

    # ─── DEV-232: Шаг 2 — HTF-gate. Активные HTF-флаги (last row 1h/4h/1d) ───
    # Кэшируем между циклами — HTF меняется медленно (1h-бар = 3600с).
    _now = time.time()
    active_htf_flags: Optional[set] = None
    if htf_flags_cache is not None:
        _cached = htf_flags_cache.get(symbol)
        if _cached and (_now - _cached[1]) < HTF_FLAGS_CACHE_TTL:
            active_htf_flags = _cached[0]
    if active_htf_flags is None:
        active_htf_flags = set()
        for _f_htf in (f_1h, f_4h_src, f_1d_src):
            if _f_htf is not None and len(_f_htf) > 0:
                _last = _f_htf.iloc[-1]
                # Только bool колонки — исключить числовые pivot-уровни (R2, S3, цены)
                _true_cols = [c for c in _last.index
                              if isinstance(_last[c], (bool, __import__('numpy').bool_))]
                active_htf_flags |= set(_true_cols)
        if htf_flags_cache is not None:
            htf_flags_cache[symbol] = (active_htf_flags, _now)

    # Gate: фетчим 5m только если хоть один 5m-паттерн может сработать
    _gate_5m_open = adapter.registry.htf_gate_open(active_htf_flags, "5m")
    df_5m = None
    f_5m_src = None
    if _gate_5m_open:
        df_5m = await _fetch_df(data_collector, symbol, "5m", 500)
        if df_5m is not None and len(df_5m) >= 100:
            try:
                f_5m_src = cb.compute_flags(df_5m, "5m")
            except Exception as e:
                logger.debug("[ARCH-104] %s 5m compute_flags failed: %s", symbol, e)
                df_5m = None
        if gate_stats is not None:
            gate_stats["ltf_fetched"] = gate_stats.get("ltf_fetched", 0) + 1
    else:
        if gate_stats is not None:
            gate_stats["htf_only"] = gate_stats.get("htf_only", 0) + 1

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
        # D-052 v2 (2026-05-24): pandas FutureWarning о downcasting object dtype
        # генерируется внутри `.fillna(False)` (когда df bool + reindex даёт NaN).
        # `.infer_objects()` после — бесполезно (warning уже выпущен).
        #
        # Правильно: `reindex(fill_value=False)` — заполняет NaN сразу как False
        # в момент reindex, БЕЗ object dtype intermediate. Native bool throughout.
        def _reindex_bool(df_src, idx):
            return df_src.reindex(idx, method="ffill", fill_value=False).astype(bool)
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
                        active_flags=active_flags,   # D-051: для shadow trigger check
                    )

    return any_decision


# ─────────── VST trading helper (D-030) ───────────

async def _try_register_vst_trade(
    bot, symbol: str, det_tf: str, direction: str, decision,
    registry, price: float, sl_price: float,
    active_flags: Optional[set] = None,   # D-051: shadow trigger check
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

    # DS-audit 13.06: arch104 LONG убыточен n=2422 → −56R, SHORT +1874R. Полный запрет LONG.
    if direction == "LONG":
        await record_drop(
            symbol, "arch104_long_banned",
            f"arch104 LONG заблокирован: data-audit 13.06 (n=2422 avgR<0)",
        )
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

    # DS-audit 13.06: strength<84 убыточен для arch104 SHORT. Порог 84.
    if strength < 84:
        await record_drop(
            symbol, "arch104_low_strength",
            f"arch104 strength={strength}<84 pattern={decision.pattern_id}",
        )
        return

    confidence = max(0.55, min(0.95, 0.55 + float(decision.risk_pct) * 0.1))

    # реальный 24h оборот (был хардкод 0.0 → ломал LIQ-GATE эксперимент: нечем split ликвид/неликвид)
    _vol24 = 0.0
    try:
        _tk = await bot.data_collector.get_ticker(symbol)
        if _tk:
            _vol24 = float(_tk.get("quoteVolume") or 0.0)
    except Exception:
        pass

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
            volume_24h=_vol24, volume_change_24h=0.0, price_change_24h=0.0,
        ),
        entry_price=price,
        stop_loss=sl_price,
        take_profit=tp_price,
        sl_source=f"arch104:swing_{det_tf}",
        tp_source=f"arch104:{getattr(pattern, 'tp_strategy', 'no_trail')}_r{fallback_tp_r}",
    )

    # D-051 (26.05.2026): wt_cross HARD gate для паттернов БЕЗ wt_cross_*_1h в anchor.
    # T8 паттерны уже содержат wt_cross_{dir}_1h в anchor_factors — им gate не нужен.
    # ARCH-128 04.06: gate ДУШИЛ весь DS-реестр (200/200 без wt_cross в anchor → требовал
    # strict wt_cross_{tf} в OS/OB зоне, активен редко → 0 срабатываний). DS-паттерны
    # намайнены walkforford БЕЗ wt_cross — конфлюенция anchor сама = подтверждение.
    # Gate теперь под config-флагом (default OFF — старых паттернов в реестре нет).
    cross_dir = "up" if direction == "LONG" else "down"
    wt_cross_1h = f"wt_cross_{cross_dir}_1h"
    anchor_factors = list(getattr(pattern, "anchor_factors", []))
    wt_cross_flag = None
    _d051_enabled = bool(bot.config.get("arch104.d051_wt_cross_gate", False))
    if _d051_enabled and wt_cross_1h not in anchor_factors:
        wt_cross_flag = f"wt_cross_{cross_dir}_{det_tf}"
        if active_flags is None or wt_cross_flag not in active_flags:
            logger.debug(
                "[ARCH-104 VST] %s@%s %s pattern=%s SKIP: no %s (D-051 gate)",
                symbol, det_tf, direction, decision.pattern_id, wt_cross_flag,
            )
            await record_drop(
                symbol=symbol,
                gate_name="arch104_d051_no_wt_cross",
                drop_reason=f"arch104/{direction}: missing {wt_cross_flag} for pattern={decision.pattern_id}",
                signal_type="arch104",
                direction=direction,
                strength=int(strength),
                features={
                    "pattern_id": decision.pattern_id,
                    "detection_tf": det_tf,
                    "required_flag": wt_cross_flag,
                    "anchor_factors": anchor_factors,
                    "active_flags_count": len(active_flags) if active_flags else 0,
                },
            )
            return

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
        "arch104_wt_cross_flag": wt_cross_flag,  # D-051: подтверждённый gate flag
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
