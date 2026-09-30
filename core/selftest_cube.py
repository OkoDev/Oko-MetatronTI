"""
SelfTest Куба Метатрона (ARCH-73 / DEV-121 расширение).

Проверяет что 13 сфер и все рёбра между ними живы и подключены.
Работает поверх bot instance — полноценный selftest запускается после init.

Три слоя:
  L13 — Cube Spheres:   статус всех 13 сфер (ACTIVE / SHADOW / MISSING)
  L14 — Cube Edges:     рёбра — связи между сферами (callbacks, references)
  L15 — Feedback Loops: циклы обратной связи замкнуты (PostTrade → weights/bus)

Вызов:
    from core.selftest_cube import run_cube_selftest
    results = await run_cube_selftest(bot)
    for r in results: print(r)

Интеграция с основным selftest:
    В core/selftest.py add_layer() вызывает run_cube_selftest() и дополняет отчёт.

Куб Метатрона (13 сфер вокруг Shared Context Bus):
    1 DataCollector       | 2 WSFeed             | 3 MTF WT Specialist
    4 MTF SMC Specialist  | 5 Cross-Market       | 6 MarketRegime
    7 TradingIntelligence | 8 TradeSimulator     | 9 Exit Manager
    10 PostTradeAnalyser  | 11 NarrativeBuilder  | 12 ML Outcome
    13 PairContextBus (центр)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── Статусы ──────────────────────────────────────────────────────────────
ACTIVE  = "ACTIVE"   # компонент работает и влияет на решения
SHADOW  = "SHADOW"   # код есть, но отключён (shadow mode / disabled)
MISSING = "MISSING"  # отсутствует / не инициализирован

STATUS_ICON = {ACTIVE: "✅", SHADOW: "⚠️", MISSING: "🔴"}


@dataclass
class CubeCheckResult:
    """Результат проверки сферы / ребра / цикла."""
    layer:   str           # "L13_sphere", "L14_edge", "L15_loop"
    code:    str           # "S1", "E_TS_PTA", "LOOP_ADAPT_WEIGHTS"
    name:    str
    status:  str           # ACTIVE | SHADOW | MISSING
    detail:  str = ""

    def line(self) -> str:
        icon = STATUS_ICON.get(self.status, "?")
        return f"  {icon} [{self.code}] {self.name}: {self.status}" + (f" — {self.detail}" if self.detail else "")


def _spec_state(spec) -> tuple:
    """Состояние ML-специалиста через ПУБЛИЧНЫЙ интерфейс (is_trained / info()).

    Раньше читались `is_fitted` / `n_samples` — таких атрибутов у специалистов нет
    (внутри `_trained` / `_n_samples`), getattr молча отдавал False/0, и обученные
    на 7.4k сделках модели показывались как пустые. Отсюда ложный вывод «сферы 3/4
    не обучены» при живых моделях. Публичный интерфейс не даст соврать молча.
    """
    try:
        info = spec.info() if hasattr(spec, "info") else {}
    except Exception:
        info = {}
    fitted = bool(info.get("trained", getattr(spec, "is_trained", False)))
    n = int(info.get("n_samples", 0) or 0)
    auc = info.get("cv_auc")
    auc_s = f"{auc:.3f}" if isinstance(auc, (int, float)) else "n/a"
    return fitted, n, auc_s


# ═════════════════════════════════════════════════════════════════════════
# L13 — СФЕРЫ
# ═════════════════════════════════════════════════════════════════════════

def _check_sphere_1_data_collector(bot) -> CubeCheckResult:
    dc = getattr(bot, "data_collector", None)
    if dc is None:
        return CubeCheckResult("L13_sphere", "S1", "DataCollector", MISSING, "bot.data_collector не найден")
    try:
        engine = getattr(dc, "_engine", None)
        if engine is None:
            return CubeCheckResult("L13_sphere", "S1", "DataCollector", SHADOW, "_engine отсутствует (старый API)")
        stats = engine.cache_stats() if hasattr(engine, "cache_stats") else {}
        return CubeCheckResult("L13_sphere", "S1", "DataCollector", ACTIVE,
                               f"cache={stats.get('cache_size','?')} cb={stats.get('cb_state','?')}")
    except Exception as e:
        return CubeCheckResult("L13_sphere", "S1", "DataCollector", SHADOW, f"error: {e}")


def _check_sphere_2_ws_feed(bot) -> CubeCheckResult:
    ws = getattr(bot, "ws_feed", None)
    if ws is None:
        return CubeCheckResult("L13_sphere", "S2", "WSFeed", MISSING, "bot.ws_feed не найден")
    # Читаем ПУБЛИЧНЫЙ stats(): раньше искались `is_running` (метод зовётся is_alive)
    # и `_subscriptions` (такого атрибута нет) — обе давали тихий False/0.
    try:
        st = ws.stats() if hasattr(ws, "stats") else {}
    except Exception:
        st = {}
    running = bool(st.get("running", getattr(ws, "_running", False)))
    tickers = int(st.get("active_tickers", 0) or 0)
    alive = ws.is_alive() if hasattr(ws, "is_alive") else running
    up = int(st.get("uptime_sec", 0) or 0)
    detail = f"alive={alive} tickers={tickers} ohlcv={st.get('active_ohlcv', 0)} uptime={up}s errors={st.get('errors', 0)}"
    if alive:
        return CubeCheckResult("L13_sphere", "S2", "WSFeed", ACTIVE, detail)
    # Селфтест идёт при старте, а ws_feed.start() — позже отдельной задачей:
    # «не запущен» в момент старта нормально, это не приговор сфере.
    return CubeCheckResult("L13_sphere", "S2", "WSFeed", SHADOW, detail + " (при старте — возможна гонка)")


def _check_sphere_3_mtf_wt(bot) -> CubeCheckResult:
    ti = getattr(bot, "trading_intelligence", None)
    if ti is None:
        return CubeCheckResult("L13_sphere", "S3", "MTF WT Specialist", MISSING, "trading_intelligence отсутствует")
    spec = getattr(ti, "_wt_specialist", None)
    if spec is None:
        return CubeCheckResult("L13_sphere", "S3", "MTF WT Specialist", MISSING, "_wt_specialist не инициализирован")
    fitted, n, auc = _spec_state(spec)
    gate_on = False
    try:
        gate_on = bool(bot.config.get("trading.verdict_gate.enabled", False))
    except Exception:
        pass
    # 12.08: модель ОБУЧАЕТСЯ на каждом старте, но её predict НЕ ВЫЗЫВАЕТСЯ нигде —
    # DEV-161 заменил ML на rule-based derive_wt_verdict. Обучение = чистая трата
    # ~7с старта. Статус ACTIVE тут был бы ложью: сфера не влияет на решения.
    return CubeCheckResult("L13_sphere", "S3", "MTF WT Specialist", SHADOW,
                           f"fitted={fitted} n={n} auc={auc} gate={gate_on} — "
                           f"predict НЕ вызывается (DEV-161 заменил rule-based), обучение впустую")


def _check_sphere_4_mtf_smc(bot) -> CubeCheckResult:
    ti = getattr(bot, "trading_intelligence", None)
    if ti is None:
        return CubeCheckResult("L13_sphere", "S4", "MTF SMC Specialist", MISSING, "trading_intelligence отсутствует")
    spec = getattr(ti, "_smc_specialist", None)
    if spec is None:
        return CubeCheckResult("L13_sphere", "S4", "MTF SMC Specialist", MISSING, "_smc_specialist не инициализирован")
    fitted, n, auc = _spec_state(spec)
    gate_on = False
    try:
        gate_on = bool(bot.config.get("trading.verdict_gate.enabled", False))
    except Exception:
        pass
    status = ACTIVE if (fitted and gate_on) else SHADOW
    return CubeCheckResult("L13_sphere", "S4", "MTF SMC Specialist", status,
                           f"fitted={fitted} n={n} auc={auc} gate={gate_on}")


def _check_sphere_5_cross_market(bot) -> CubeCheckResult:
    """ARCH-78: S5 = BTCRegimeProvider (Supertrend) + btc_market_gate (shadow).
    ACTIVE если BTCRegimeProvider инициализирован и обновлён хотя бы раз.
    SHADOW если провайдер есть, но gate в shadow_mode (наблюдаем, не блокируем).
    MISSING если нет ни провайдера, ни gate.
    """
    # ARCH-78: BTCRegimeProvider — основная проверка
    btc_prov = getattr(bot, "btc_regime_provider", None)
    if btc_prov is not None:
        updated = getattr(btc_prov, "_updated_at", None) is not None
        mode    = getattr(btc_prov, "_btc_mode", "NEUTRAL")
        try:
            cfg = getattr(bot, "config", None)
            gate_cfg  = (cfg.get("trading", {}) or {}).get("btc_market_gate", {}) if cfg else {}
            shadow    = bool(gate_cfg.get("shadow_mode", True))
        except Exception:
            shadow = True
        status = SHADOW if shadow else ACTIVE
        detail = f"BTCRegimeProvider mode={mode} updated={updated} gate_shadow={shadow}"
        return CubeCheckResult("L13_sphere", "S5", "Cross-Market (BTC gate)", status, detail)
    # fallback: старый gate без провайдера
    try:
        cfg = getattr(bot, "config", None)
        if cfg is None:
            return CubeCheckResult("L13_sphere", "S5", "Cross-Market (BTC gate)", MISSING, "btc_regime_provider отсутствует")
        gate_cfg = (cfg.get("trading", {}) or {}).get("btc_market_gate", {})
        enabled  = bool(gate_cfg.get("enabled", False))
        shadow   = bool(gate_cfg.get("shadow_mode", True))
    except Exception as e:
        return CubeCheckResult("L13_sphere", "S5", "Cross-Market (BTC gate)", MISSING, f"cfg error: {e}")
    if not enabled:
        return CubeCheckResult("L13_sphere", "S5", "Cross-Market (BTC gate)", MISSING, "btc_market_gate.enabled=false, provider отсутствует")
    status = SHADOW if shadow else ACTIVE
    return CubeCheckResult("L13_sphere", "S5", "Cross-Market (BTC gate)", status, f"старый gate enabled={enabled} shadow={shadow}")


def _check_sphere_6_market_regime(bot) -> CubeCheckResult:
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        _ = MarketRegimeClassifier()
        return CubeCheckResult("L13_sphere", "S6", "MarketRegime", ACTIVE, "classify доступен")
    except Exception as e:
        return CubeCheckResult("L13_sphere", "S6", "MarketRegime", MISSING, f"import/init error: {e}")


def _check_sphere_7_trading_intelligence(bot) -> CubeCheckResult:
    ti = getattr(bot, "trading_intelligence", None)
    if ti is None:
        return CubeCheckResult("L13_sphere", "S7", "TradingIntelligence", MISSING, "отсутствует")
    strategies = list(getattr(ti, "strategies", {}).keys()) if hasattr(ti, "strategies") else []
    active = getattr(ti, "active_strategy_name", "?")
    return CubeCheckResult("L13_sphere", "S7", "TradingIntelligence", ACTIVE,
                           f"active={active} strats={len(strategies)}")


def _check_sphere_8_trade_simulator(bot) -> CubeCheckResult:
    ts = getattr(bot, "trade_simulator", None)
    if ts is None:
        return CubeCheckResult("L13_sphere", "S8", "TradeSimulator", MISSING, "отсутствует")
    db = getattr(ts, "db_path", None)
    cb_set = ts._post_trade_callback is not None
    return CubeCheckResult("L13_sphere", "S8", "TradeSimulator", ACTIVE,
                           f"db={db} post_cb={cb_set}")


def _check_sphere_9_exit_manager(bot) -> CubeCheckResult:
    oe = getattr(bot, "order_executor", None)
    if oe is None:
        return CubeCheckResult("L13_sphere", "S9", "Exit Manager", MISSING, "order_executor отсутствует")
    try:
        mode = oe.mode.value if hasattr(oe.mode, "value") else str(oe.mode)
    except Exception:
        mode = "?"
    is_live = oe.is_live() if hasattr(oe, "is_live") else False
    status = ACTIVE if is_live else SHADOW
    return CubeCheckResult("L13_sphere", "S9", "Exit Manager", status, f"mode={mode} live={is_live}")


def _check_sphere_10_post_trade_analyser(bot) -> CubeCheckResult:
    pta = getattr(bot, "post_analyser", None)
    if pta is None:
        return CubeCheckResult("L13_sphere", "S10", "PostTradeAnalyser", MISSING, "отсутствует")
    ctx_set  = getattr(pta, "_ctx", None) is not None
    intel    = getattr(pta, "_intelligence", None) is not None  # ARCH-72
    ev_set   = getattr(pta, "_event_bus", None) is not None     # ARCH-72
    status = ACTIVE if (ctx_set and intel and ev_set) else SHADOW
    return CubeCheckResult("L13_sphere", "S10", "PostTradeAnalyser", status,
                           f"ctx={ctx_set} intel={intel} event_bus={ev_set}")


def _check_sphere_11_narrative_builder(bot) -> CubeCheckResult:
    """NarrativeBuilder запускается в analyze_symbol ВСЕГДА (флаг меняет только INFO vs DEBUG лог).
    Статус ACTIVE если модуль импортируется — он реально работает независимо от флага.
    """
    try:
        from core.intelligence.narrative_builder import NarrativeBuilder  # noqa: F401
        exists = True
    except Exception:
        exists = False
    if not exists:
        return CubeCheckResult("L13_sphere", "S11", "NarrativeBuilder", MISSING, "модуль не импортируется")
    try:
        log_enabled = bool(bot.config.get("trading.narrative.enabled", False))
    except Exception:
        log_enabled = False
    # Код в TI.analyze_symbol вызывает build() независимо от флага — флаг только меняет уровень лога
    return CubeCheckResult("L13_sphere", "S11", "NarrativeBuilder", ACTIVE,
                           f"build() всегда вызывается, INFO-лог={'вкл' if log_enabled else 'выкл (debug)'}")


def _check_sphere_12_ml_outcome(bot) -> CubeCheckResult:
    ti = getattr(bot, "trading_intelligence", None)
    if ti is None:
        return CubeCheckResult("L13_sphere", "S12", "ML Outcome", MISSING, "trading_intelligence отсутствует")
    predictor = getattr(ti, "outcome_predictor", None)
    use_pred  = False
    try:
        use_pred = bool(bot.config.get("ml.use_outcome_predictor", False))
    except Exception:
        pass
    if predictor is None:
        return CubeCheckResult("L13_sphere", "S12", "ML Outcome", MISSING, "outcome_predictor отсутствует")
    status = ACTIVE if use_pred else SHADOW
    return CubeCheckResult("L13_sphere", "S12", "ML Outcome", status, f"use={use_pred}")


def _check_sphere_13_pair_context_bus(bot) -> CubeCheckResult:
    pc = getattr(bot, "pair_context", None)
    if pc is None:
        return CubeCheckResult("L13_sphere", "S13", "PairContextBus (центр)", MISSING, "отсутствует")
    try:
        n_pairs = len(getattr(pc, "_states", {}) or {})
    except Exception:
        n_pairs = 0
    return CubeCheckResult("L13_sphere", "S13", "PairContextBus (центр)", ACTIVE, f"pairs={n_pairs}")


# ═════════════════════════════════════════════════════════════════════════
# L14 — РЁБРА (связи между сферами)
# ═════════════════════════════════════════════════════════════════════════

def _edge_ts_to_pta(bot) -> CubeCheckResult:
    """Ребро: TradeSimulator → PostTradeAnalyser (close_trade callback)."""
    ts = getattr(bot, "trade_simulator", None)
    pta = getattr(bot, "post_analyser", None)
    if not ts or not pta:
        return CubeCheckResult("L14_edge", "E_TS_PTA", "TradeSimulator→PostTradeAnalyser", MISSING,
                               "ts или pta отсутствует")
    cb_set = ts._post_trade_callback is not None
    match = (ts._post_trade_callback == pta.on_trade_closed) if cb_set else False
    status = ACTIVE if match else MISSING
    return CubeCheckResult("L14_edge", "E_TS_PTA", "TradeSimulator→PostTradeAnalyser", status,
                           f"callback_set={cb_set} match={match}")


def _edge_pta_to_pairctx(bot) -> CubeCheckResult:
    """Ребро: PostTradeAnalyser → PairContextBus (update cascade/post_tsl)."""
    pta = getattr(bot, "post_analyser", None)
    pc  = getattr(bot, "pair_context", None)
    if not pta or not pc:
        return CubeCheckResult("L14_edge", "E_PTA_PC", "PostTradeAnalyser→PairContextBus", MISSING)
    status = ACTIVE if getattr(pta, "_ctx", None) is pc else MISSING
    return CubeCheckResult("L14_edge", "E_PTA_PC", "PostTradeAnalyser→PairContextBus", status)


def _edge_pta_to_intel(bot) -> CubeCheckResult:
    """Ребро ARCH-72: PostTradeAnalyser → TradingIntelligence (update_signal_weights)."""
    pta = getattr(bot, "post_analyser", None)
    ti  = getattr(bot, "trading_intelligence", None)
    if not pta or not ti:
        return CubeCheckResult("L14_edge", "E_PTA_TI", "PostTradeAnalyser→TradingIntelligence", MISSING)
    linked = getattr(pta, "_intelligence", None) is ti
    status = ACTIVE if linked else MISSING
    return CubeCheckResult("L14_edge", "E_PTA_TI", "PostTradeAnalyser→TradingIntelligence", status,
                           f"linked={linked} (ARCH-72 adaptive weights)")


def _edge_pta_to_eventbus(bot) -> CubeCheckResult:
    """Ребро ARCH-72: PostTradeAnalyser → EventBus (trade_closed publish)."""
    pta = getattr(bot, "post_analyser", None)
    eb  = getattr(bot, "event_bus", None)
    if not pta or not eb:
        return CubeCheckResult("L14_edge", "E_PTA_EB", "PostTradeAnalyser→EventBus", MISSING)
    linked = getattr(pta, "_event_bus", None) is eb
    status = ACTIVE if linked else MISSING
    return CubeCheckResult("L14_edge", "E_PTA_EB", "PostTradeAnalyser→EventBus", status,
                           f"linked={linked} (ARCH-72 trade_closed)")


def _edge_ti_to_eventbus(bot) -> CubeCheckResult:
    """Ребро: TradingIntelligence → EventBus (wt_verdict_strong publish)."""
    ti = getattr(bot, "trading_intelligence", None)
    eb = getattr(bot, "event_bus", None)
    if not ti or not eb:
        return CubeCheckResult("L14_edge", "E_TI_EB", "TradingIntelligence→EventBus", MISSING)
    linked = getattr(ti, "_event_bus", None) is eb
    status = ACTIVE if linked else MISSING
    return CubeCheckResult("L14_edge", "E_TI_EB", "TradingIntelligence→EventBus", status,
                           f"linked={linked}")


def _edge_eventbus_consumer(bot) -> CubeCheckResult:
    """Ребро: EventBus → _fire_analysis (consume_loop запущен)."""
    eb = getattr(bot, "event_bus", None)
    if not eb:
        return CubeCheckResult("L14_edge", "E_EB_FIRE", "EventBus→_fire_analysis", MISSING, "event_bus отсутствует")
    enabled = getattr(eb, "enabled", False)
    shadow  = getattr(eb, "shadow", True)
    qs      = eb.queue_size() if hasattr(eb, "queue_size") else -1
    status = ACTIVE if (enabled and not shadow) else (SHADOW if enabled else MISSING)
    return CubeCheckResult("L14_edge", "E_EB_FIRE", "EventBus→_fire_analysis", status,
                           f"enabled={enabled} shadow={shadow} queue={qs}")


def _edge_dc_to_mr(bot) -> CubeCheckResult:
    """Ребро: DataCollector → MarketRegime (через fetch + classify)."""
    dc = getattr(bot, "data_collector", None)
    if dc is None:
        return CubeCheckResult("L14_edge", "E_DC_MR", "DataCollector→MarketRegime", MISSING)
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        _ = MarketRegimeClassifier()
        return CubeCheckResult("L14_edge", "E_DC_MR", "DataCollector→MarketRegime", ACTIVE,
                               "classify_from_dataframes готов")
    except Exception as e:
        return CubeCheckResult("L14_edge", "E_DC_MR", "DataCollector→MarketRegime", MISSING, str(e)[:60])


def _edge_ti_to_ts(bot) -> CubeCheckResult:
    """Ребро: TradingIntelligence → TradeSimulator (register_trade_async)."""
    ti = getattr(bot, "trading_intelligence", None)
    ts = getattr(bot, "trade_simulator", None)
    if not ti or not ts:
        return CubeCheckResult("L14_edge", "E_TI_TS", "TradingIntelligence→TradeSimulator", MISSING)
    ok = hasattr(ts, "register_trade_async") and hasattr(ts, "register_trade")
    return CubeCheckResult("L14_edge", "E_TI_TS", "TradingIntelligence→TradeSimulator",
                           ACTIVE if ok else MISSING,
                           f"register_trade_async={ok}")


def _edge_detectors_to_eventbus(bot) -> CubeCheckResult:
    """Ребро: детекторы → EventBus.

    30.09 (ARCH-101 гигиена): статус по ФАКТУ публикаций с запуска (`EventBus.stats()`),
    а не по флагу конфига — флаг давал ACTIVE, даже если не публиковал никто.
    `trade_closed` не считается: это отдельное ребро Post-Trade → EventBus.
    """
    eb = getattr(bot, "event_bus", None)
    if not eb:
        return CubeCheckResult("L14_edge", "E_DET_EB", "Детекторы→EventBus", MISSING)
    st = eb.stats() if hasattr(eb, "stats") else {}
    if not st.get("enabled", False):
        return CubeCheckResult("L14_edge", "E_DET_EB", "Детекторы→EventBus", SHADOW,
                               "event_bus.enabled=false")
    by_type: dict = {}
    for key in ("accepted_by_type", "rejected_by_type"):
        for t, n in (st.get(key) or {}).items():
            if t != "trade_closed":
                by_type[t] = by_type.get(t, 0) + n
    if not by_type:
        return CubeCheckResult("L14_edge", "E_DET_EB", "Детекторы→EventBus", SHADOW,
                               "0 публикаций с запуска (сразу после старта — норма)")
    top = ", ".join(f"{t}={n}" for t, n in sorted(by_type.items(), key=lambda x: -x[1])[:4])
    return CubeCheckResult("L14_edge", "E_DET_EB", "Детекторы→EventBus", ACTIVE,
                           f"{len(by_type)} типов, {sum(by_type.values())} публикаций: {top}")


def _edge_ws_to_dc(bot) -> CubeCheckResult:
    """Ребро: WSFeed → DataCollector (real-time тикеры)."""
    ws = getattr(bot, "ws_feed", None)
    dc = getattr(bot, "data_collector", None)
    if not ws or not dc:
        return CubeCheckResult("L14_edge", "E_WS_DC", "WSFeed→DataCollector", MISSING)
    # `is_running` не существует — метод зовётся is_alive() (учитывает активные тикеры)
    alive = ws.is_alive() if hasattr(ws, "is_alive") else bool(getattr(ws, "_running", False))
    return CubeCheckResult("L14_edge", "E_WS_DC", "WSFeed→DataCollector",
                           ACTIVE if alive else SHADOW,
                           f"alive={alive}")


# --- Дополнительные рёбра (покрывают связи существующие в коде) ---

def _edge_ts_to_wt(bot) -> CubeCheckResult:
    """Ребро: TradeSimulator → WT Specialist (wt_snap в features_json → обучение модели)."""
    ts = getattr(bot, "trade_simulator", None)
    ti = getattr(bot, "trading_intelligence", None)
    if not ts or not ti:
        return CubeCheckResult("L14_edge", "E_TS_WT", "TradeSimulator→WTSpecialist", MISSING)
    wt = getattr(ti, "_wt_specialist", None)
    ok = wt is not None and hasattr(wt, "predict")
    return CubeCheckResult("L14_edge", "E_TS_WT", "TradeSimulator→WTSpecialist",
                           ACTIVE if ok else SHADOW,
                           f"wt_specialist={'loaded' if ok else 'not loaded'} (wt_snap→train)")


def _edge_ts_to_smc(bot) -> CubeCheckResult:
    """Ребро: TradeSimulator → SMC Specialist (smc_snap в features_json → обучение модели)."""
    ts = getattr(bot, "trade_simulator", None)
    ti = getattr(bot, "trading_intelligence", None)
    if not ts or not ti:
        return CubeCheckResult("L14_edge", "E_TS_SMC", "TradeSimulator→SMCSpecialist", MISSING)
    smc = getattr(ti, "_smc_specialist", None)
    ok = smc is not None and hasattr(smc, "predict")
    return CubeCheckResult("L14_edge", "E_TS_SMC", "TradeSimulator→SMCSpecialist",
                           ACTIVE if ok else SHADOW,
                           f"smc_specialist={'loaded' if ok else 'not loaded'} (smc_snap→train)")


def _edge_wt_to_ti(bot) -> CubeCheckResult:
    """Ребро: WT Specialist → TradingIntelligence (predict → wt_verdict в metadata)."""
    ti = getattr(bot, "trading_intelligence", None)
    if not ti:
        return CubeCheckResult("L14_edge", "E_WT_TI", "WTSpecialist→TradingIntelligence", MISSING)
    wt = getattr(ti, "_wt_specialist", None)
    loaded = wt is not None and hasattr(wt, "predict")
    # `hasattr(wt, "predict")` проверял НАЛИЧИЕ метода, а не ИСПОЛЬЗОВАНИЕ ребра, и
    # рапортовал ACTIVE. На деле `_wt_specialist.predict` не вызывается ни в одном
    # модуле (12.08, grep): wt_verdict строит rule-based derive_wt_verdict (DEV-161).
    return CubeCheckResult("L14_edge", "E_WT_TI", "WTSpecialist→TradingIntelligence",
                           SHADOW,
                           f"модель={'загружена' if loaded else 'нет'}, но predict НЕ вызывается — "
                           f"wt_verdict идёт от rule-based (DEV-161). Ребро разорвано")


def _edge_smc_to_ti(bot) -> CubeCheckResult:
    """Ребро: SMC Specialist → TradingIntelligence (predict → smc_verdict в metadata)."""
    ti = getattr(bot, "trading_intelligence", None)
    if not ti:
        return CubeCheckResult("L14_edge", "E_SMC_TI", "SMCSpecialist→TradingIntelligence", MISSING)
    smc = getattr(ti, "_smc_specialist", None)
    ok = smc is not None and hasattr(smc, "predict")
    return CubeCheckResult("L14_edge", "E_SMC_TI", "SMCSpecialist→TradingIntelligence",
                           ACTIVE if ok else SHADOW,
                           f"TI._smc_specialist.predict={'ok' if ok else 'missing'}")


def _edge_mr_to_ti(bot) -> CubeCheckResult:
    """Ребро: MarketRegime → TradingIntelligence (classify_from_dataframes в analyze_symbol)."""
    ti = getattr(bot, "trading_intelligence", None)
    if not ti:
        return CubeCheckResult("L14_edge", "E_MR_TI", "MarketRegime→TradingIntelligence", MISSING)
    try:
        from core.indicators.market_regime import MarketRegimeClassifier
        has_classify = hasattr(MarketRegimeClassifier, "classify_from_dataframes")
        return CubeCheckResult("L14_edge", "E_MR_TI", "MarketRegime→TradingIntelligence",
                               ACTIVE if has_classify else SHADOW,
                               f"classify_from_dataframes={'ok' if has_classify else 'missing'}")
    except Exception as e:
        return CubeCheckResult("L14_edge", "E_MR_TI", "MarketRegime→TradingIntelligence", MISSING, str(e)[:60])


def _edge_ti_to_pairctx(bot) -> CubeCheckResult:
    """Ребро: TradingIntelligence → PairContextBus (wt_verdict + reversal_mode)."""
    ti = getattr(bot, "trading_intelligence", None)
    pc = getattr(bot, "pair_context", None)
    if not ti or not pc:
        return CubeCheckResult("L14_edge", "E_TI_PC", "TradingIntelligence→PairContextBus", MISSING)
    linked = getattr(ti, "_pair_context_bus", None) is pc
    return CubeCheckResult("L14_edge", "E_TI_PC", "TradingIntelligence→PairContextBus",
                           ACTIVE if linked else MISSING,
                           f"TI._pair_context_bus linked={linked}")


def _edge_wt_to_pairctx(bot) -> CubeCheckResult:
    """Ребро: WTSpecialist → PairContextBus (WT_SNAP_UPDATED event через TI._pair_context_bus)."""
    ti = getattr(bot, "trading_intelligence", None)
    pc = getattr(bot, "pair_context", None)
    if not ti or not pc:
        return CubeCheckResult("L14_edge", "E_WT_PC", "WTSpecialist→PairContextBus", MISSING)
    wt = getattr(ti, "_wt_specialist", None)
    ti_linked = getattr(ti, "_pair_context_bus", None) is pc
    ok = wt is not None and ti_linked
    return CubeCheckResult("L14_edge", "E_WT_PC", "WTSpecialist→PairContextBus",
                           ACTIVE if ok else (SHADOW if wt else MISSING),
                           f"wt={'ok' if wt else 'missing'} bus_linked={ti_linked}")


def _edge_ts_to_pairctx(bot) -> CubeCheckResult:
    """Ребро: TradeSimulator → PairContextBus (SphereEvent при open/close/tsl)."""
    ts = getattr(bot, "trade_simulator", None)
    pc = getattr(bot, "pair_context", None)
    if not ts or not pc:
        return CubeCheckResult("L14_edge", "E_TS_PC", "TradeSimulator→PairContextBus", MISSING)
    linked = getattr(ts, "_pair_context_bus", None) is pc
    return CubeCheckResult("L14_edge", "E_TS_PC", "TradeSimulator→PairContextBus",
                           ACTIVE if linked else MISSING,
                           f"TS._pair_context_bus linked={linked}")


def _edge_nb_to_ti(bot) -> CubeCheckResult:
    """Ребро: NarrativeBuilder → TradingIntelligence (build() per-call в analyze_symbol)."""
    ti = getattr(bot, "trading_intelligence", None)
    if not ti:
        return CubeCheckResult("L14_edge", "E_NB_TI", "NarrativeBuilder→TradingIntelligence", MISSING)
    try:
        from core.intelligence.narrative_builder import NarrativeBuilder
        has_build = hasattr(NarrativeBuilder, "build")
        # SHADOW: создаётся per-call, не постоянный атрибут TI
        return CubeCheckResult("L14_edge", "E_NB_TI", "NarrativeBuilder→TradingIntelligence",
                               SHADOW,
                               f"build={'ok' if has_build else 'missing'} (per-call, не постоянный ref)")
    except Exception as e:
        return CubeCheckResult("L14_edge", "E_NB_TI", "NarrativeBuilder→TradingIntelligence", MISSING, str(e)[:60])


def _edge_btc_to_ti(bot) -> CubeCheckResult:
    """ARCH-78: Ребро S5→S7: BTCRegimeProvider → TradingIntelligence (_btc_provider wire)."""
    ti  = getattr(bot, "trading_intelligence", None)
    prov = getattr(bot, "btc_regime_provider", None)
    if not ti or not prov:
        return CubeCheckResult("L14_edge", "E_BTC_TI", "BTCRegimeProvider→TradingIntelligence", MISSING,
                               f"provider={'ok' if prov else 'missing'} ti={'ok' if ti else 'missing'}")
    wired   = getattr(ti, "_btc_provider", None) is prov
    updated = getattr(prov, "_updated_at", None) is not None
    mode    = getattr(prov, "_btc_mode", "?")
    status  = ACTIVE if wired else MISSING
    return CubeCheckResult("L14_edge", "E_BTC_TI", "BTCRegimeProvider→TradingIntelligence", status,
                           f"wired={wired} updated={updated} mode={mode}")


def _edge_ws_to_pairctx(bot) -> CubeCheckResult:
    """Ребро: WSFeed → PairContextBus (tick_price SphereEvent)."""
    ws = getattr(bot, "ws_feed", None)
    pc = getattr(bot, "pair_context", None)
    if not ws or not pc:
        return CubeCheckResult("L14_edge", "E_WS_PC", "WSFeed→PairContextBus", MISSING)
    linked = getattr(ws, "_pair_context_bus", None) is pc
    return CubeCheckResult("L14_edge", "E_WS_PC", "WSFeed→PairContextBus",
                           ACTIVE if linked else MISSING,
                           f"WSFeed._pair_context_bus linked={linked}")


# ═════════════════════════════════════════════════════════════════════════
# L15 — ЦИКЛЫ ОБРАТНОЙ СВЯЗИ
# ═════════════════════════════════════════════════════════════════════════

def _loop_adaptive_weights(bot) -> CubeCheckResult:
    """ARCH-72: close_trade → PostTradeAnalyser → update_signal_weights каждые 50."""
    pta = getattr(bot, "post_analyser", None)
    ti  = getattr(bot, "trading_intelligence", None)
    if not pta or not ti:
        return CubeCheckResult("L15_loop", "LOOP_ADAPT_WEIGHTS", "Adaptive weights loop", MISSING)
    intel_linked = getattr(pta, "_intelligence", None) is ti
    count_attr   = hasattr(pta, "_close_count")
    has_updater  = hasattr(ti, "update_signal_weights")
    status = ACTIVE if (intel_linked and count_attr and has_updater) else MISSING
    return CubeCheckResult("L15_loop", "LOOP_ADAPT_WEIGHTS", "Adaptive weights loop", status,
                           f"linked={intel_linked} counter={count_attr} updater={has_updater}")


def _loop_cascade_tracking(bot) -> CubeCheckResult:
    """Cascade loop: close → PairContextBus.cascade_count → scan читает last_direction."""
    pta = getattr(bot, "post_analyser", None)
    pc  = getattr(bot, "pair_context", None)
    if not pta or not pc:
        return CubeCheckResult("L15_loop", "LOOP_CASCADE", "Cascade tracking loop", MISSING)
    ok = hasattr(pc, "update") and hasattr(pc, "get")
    return CubeCheckResult("L15_loop", "LOOP_CASCADE", "Cascade tracking loop",
                           ACTIVE if ok else MISSING,
                           "PairContextBus.update/get доступны" if ok else "интерфейс неполный")


def _loop_narrative(bot) -> CubeCheckResult:
    """Narrative loop: trade_closed → EventBus → NarrativeBuilder → metadata."""
    pta = getattr(bot, "post_analyser", None)
    eb  = getattr(bot, "event_bus", None)
    if not pta or not eb:
        return CubeCheckResult("L15_loop", "LOOP_NARRATIVE", "Narrative feedback loop", MISSING)
    linked = getattr(pta, "_event_bus", None) is eb
    try:
        enabled = bool(bot.config.get("trading.narrative.enabled", False))
    except Exception:
        enabled = False
    if not linked:
        return CubeCheckResult("L15_loop", "LOOP_NARRATIVE", "Narrative feedback loop", MISSING,
                               "PostTradeAnalyser не подключён к EventBus")
    status = ACTIVE if enabled else SHADOW
    return CubeCheckResult("L15_loop", "LOOP_NARRATIVE", "Narrative feedback loop", status,
                           f"publish OK, narrative.enabled={enabled}")


def _loop_ml_retrain(bot) -> CubeCheckResult:
    """ML retrain loop: закрытые сделки → ml_loop → train_all_models → outcome_predictor."""
    ti = getattr(bot, "trading_intelligence", None)
    if not ti:
        return CubeCheckResult("L15_loop", "LOOP_ML", "ML retrain loop", MISSING)
    try:
        use_pred = bool(bot.config.get("ml.use_outcome_predictor", False))
    except Exception:
        use_pred = False
    has_retrain = hasattr(ti, "train_all_models")
    status = ACTIVE if (use_pred and has_retrain) else SHADOW
    return CubeCheckResult("L15_loop", "LOOP_ML", "ML retrain loop", status,
                           f"use_pred={use_pred} retrain={has_retrain}")


# ═════════════════════════════════════════════════════════════════════════
# Главный раннер
# ═════════════════════════════════════════════════════════════════════════

SPHERE_CHECKS = [
    _check_sphere_1_data_collector,
    _check_sphere_2_ws_feed,
    _check_sphere_3_mtf_wt,
    _check_sphere_4_mtf_smc,
    _check_sphere_5_cross_market,
    _check_sphere_6_market_regime,
    _check_sphere_7_trading_intelligence,
    _check_sphere_8_trade_simulator,
    _check_sphere_9_exit_manager,
    _check_sphere_10_post_trade_analyser,
    _check_sphere_11_narrative_builder,
    _check_sphere_12_ml_outcome,
    _check_sphere_13_pair_context_bus,
]

EDGE_CHECKS = [
    # Оригинальные 10 (L14 v1)
    _edge_dc_to_mr,
    _edge_ti_to_ts,
    _edge_ts_to_pta,
    _edge_pta_to_pairctx,
    _edge_pta_to_intel,
    _edge_pta_to_eventbus,
    _edge_ti_to_eventbus,
    _edge_eventbus_consumer,
    _edge_detectors_to_eventbus,
    _edge_ws_to_dc,
    # Дополнительные 10 (L14 v2 — покрывают реальные связи в коде)
    _edge_ts_to_wt,
    _edge_ts_to_smc,
    _edge_wt_to_ti,
    _edge_smc_to_ti,
    _edge_mr_to_ti,
    _edge_ti_to_pairctx,
    _edge_wt_to_pairctx,
    _edge_ts_to_pairctx,
    _edge_nb_to_ti,
    _edge_ws_to_pairctx,
    # ARCH-78 (L14 v3)
    _edge_btc_to_ti,
]

LOOP_CHECKS = [
    _loop_adaptive_weights,
    _loop_cascade_tracking,
    _loop_narrative,
    _loop_ml_retrain,
]


async def run_cube_selftest(bot) -> List[CubeCheckResult]:
    """Запускает все проверки Куба. Возвращает плоский список результатов."""
    results: List[CubeCheckResult] = []
    for check in SPHERE_CHECKS + EDGE_CHECKS + LOOP_CHECKS:
        try:
            r = check(bot)
        except Exception as e:
            r = CubeCheckResult("L_CUBE", check.__name__, check.__name__, MISSING, f"check error: {e}")
        results.append(r)
    return results


def format_cube_report(results: List[CubeCheckResult]) -> str:
    """Человекочитаемый отчёт с разбивкой по слоям."""
    from collections import Counter

    spheres = [r for r in results if r.layer == "L13_sphere"]
    edges   = [r for r in results if r.layer == "L14_edge"]
    loops   = [r for r in results if r.layer == "L15_loop"]

    def _count(rows):
        c = Counter(r.status for r in rows)
        return f"ACTIVE={c.get(ACTIVE,0)} SHADOW={c.get(SHADOW,0)} MISSING={c.get(MISSING,0)}"

    lines = ["═══ КУБ МЕТАТРОНА: SELFTEST ═══"]
    lines.append(f"\n─── L13 СФЕРЫ ({_count(spheres)}) ───")
    lines.extend(r.line() for r in spheres)
    lines.append(f"\n─── L14 РЁБРА ({_count(edges)}) ───")
    lines.extend(r.line() for r in edges)
    lines.append(f"\n─── L15 ЦИКЛЫ ({_count(loops)}) ───")
    lines.extend(r.line() for r in loops)

    missing = [r for r in results if r.status == MISSING]
    if missing:
        lines.append(f"\n🔴 MISSING: {len(missing)} — требует внимания")
    lines.append("")
    return "\n".join(lines)


async def print_cube_selftest(bot) -> None:
    """Удобный вызов: запустить + напечатать."""
    results = await run_cube_selftest(bot)
    print(format_cube_report(results))


if __name__ == "__main__":
    # Раньше здесь подставлялся _Stub() вместо бота: проверки не находили ни одного
    # атрибута и печатали 38/38 MISSING на полностью живом Кубе. Отсюда и пошло
    # «сфер не существует» в документации. Теперь по умолчанию идём за ЖИВЫМ отчётом.
    import asyncio as _a
    import json as _json
    import sys as _sys
    import urllib.request as _url

    try:
        _sys.stdout.reconfigure(encoding="utf-8")  # иначе cp1251 роняет вывод на Windows
    except Exception:
        pass

    if "--stub" in _sys.argv:
        class _Stub:
            config = None
        print("⚠️  STUB-РЕЖИМ: бота нет. MISSING ниже означает «нечего проверять»,\n"
              "    а НЕ «сферы не существует». Настоящий статус — запуск без --stub.\n")
        _a.run(print_cube_selftest(_Stub()))
    else:
        _u = "http://127.0.0.1:8000/api/cube/selftest"
        try:
            with _url.urlopen(_u, timeout=30) as _r:
                print(_json.loads(_r.read().decode("utf-8"))["report"])
        except Exception as _e:
            print(f"🔴 Живой отчёт недоступен ({_u}): {_e}\n"
                  f"   Статусы сфер снимаются ТОЛЬКО с работающего бота — проверь, что он запущен.\n"
                  f"   `--stub` покажет каркас проверок без бота (там все MISSING — это норма).")
            _sys.exit(1)
