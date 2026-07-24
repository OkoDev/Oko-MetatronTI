"""
PairContextBus — Shared Context Bus / Центральная Сфера Куба Метатрона.

Полная mesh-шина: 13 сфер публикуют → подписчики реагируют → per-pair живое состояние.

Два уровня:
  1. PairState — персистентный снимок состояния пары (все 13 сфер)
  2. pub/sub — событийная шина: publish(symbol, event_type, data) → subscribers

EventBus (event_bus.py) — для ASYNC Full CALL триггеров (приоритетная очередь).
PairContextBus — для SYNC state sharing между сферами внутри одного цикла.

Жизненный цикл:
    bot.pair_context = PairContextBus()
    # Каждый детектор/модуль публикует в шину свои результаты
    # Каждый подписчик реагирует на события других сфер
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("SharedContextBus")


# ── Типы событий шины ───────────────────────────────────────────────────────

class SphereEvent:
    """Все типы событий Куба. Каждая сфера публикует и подписывается."""
    # Сфера 1 — DataCollector
    OHLCV_UPDATED     = "ohlcv_updated"       # {tf: str, rows: int}

    # Сфера 2 — WSFeed
    TICK_PRICE         = "tick_price"           # {price: float, volume_24h: float}
    VOLUME_SPIKE       = "volume_spike"         # {ratio: float, tf: str}

    # Сфера 3 — MTF WT Specialist
    WT_VERDICT         = "wt_verdict"           # {label: str, confidence: float, features: dict}
    WT_SNAP_UPDATED    = "wt_snap_updated"      # {tf: {wt1, wt2, zone, cross, atr_trend}}

    # Сфера 4 — MTF SMC Specialist
    SMC_VERDICT        = "smc_verdict"          # {label: str, confidence: float}
    SMC_SNAP_UPDATED   = "smc_snap_updated"     # {tf: {ob_bull, fvg_open, choch, bos, ...}}

    # Сфера 5 — Cross-Market Node
    CROSS_MARKET       = "cross_market"         # {btc_regime, btc_move_pct, direction}

    # Сфера 6 — Market Regime
    REGIME_UPDATED     = "regime_updated"       # {regime: str, mode: str}

    # Сфера 7 — Signal Detectors
    SIGNAL_DETECTED    = "signal_detected"      # {signal_type, direction, strength, tf}
    ANOMALY_DETECTED   = "anomaly_detected"     # {volume_ratio, tf}
    DIVERGENCE_FOUND   = "divergence_found"     # {type, direction, tf, strength}
    PIVOT_TOUCH        = "pivot_touch"          # {level, source, distance_pct}

    # Сфера 8 — Pivot Levels
    PIVOT_SNAP_UPDATED = "pivot_snap_updated"   # {1W: {PP, S1, R1, ...}, 1D: {...}}

    # Сфера 9 — Narrative Builder / TradeRouter (Decision Core)
    NARRATIVE_BUILT    = "narrative_built"       # {text, action, p_win, key_factors}
    POSITION_OPENED    = "position_opened"       # {side, source, trade_id, final_strength, soft_penalties, regime}
    POSITION_DROPPED   = "position_dropped"      # {side, source, hard_drops, soft_penalties, strength, regime}

    # Сфера 10 — Exit Manager
    TSL_MOVED          = "tsl_moved"            # {trade_id, old_sl, new_sl, tf}
    TP1_HIT            = "tp1_hit"              # {trade_id, r_at_tp1}
    POSITION_CLOSED    = "position_closed"      # {trade_id, status, r_multiple}

    # Сфера 11 — Post-Trade Analyser
    TRADE_CLOSED       = "trade_closed"         # {status, r_multiple, direction, signal_type}
    CASCADE_UPDATED    = "cascade_updated"      # {cascade_count, avg_r, direction}
    OTE_ZONE_SET       = "ote_zone_set"         # {ote_top, ote_bot, direction, ttl_hours}

    # Сфера 12 — Self-Diagnostics
    SPHERE_HEALTH      = "sphere_health"        # {sphere_id, status, last_update}


@dataclass
class PairState:
    """
    Полное состояние торговой пары — снимки всех 13 сфер.
    Обновляется через PairContextBus.update() или publish().
    """
    symbol: str

    # ── Сфера 1: DataCollector ──────────────────────────────────────────
    last_ohlcv_time: Optional[datetime] = None   # когда последний раз обновлялись данные
    ohlcv_tfs_loaded: List[str] = field(default_factory=list)  # какие TF загружены

    # ── Сфера 2: WSFeed ─────────────────────────────────────────────────
    tick_price: Optional[float] = None
    tick_time: Optional[datetime] = None

    # ── Сфера 3: MTF WT Specialist ──────────────────────────────────────
    wt_verdict: Optional[str] = None          # TREND_CONTINUATION / REVERSAL_SETUP / EXHAUSTION
    wt_confidence: float = 0.0
    wt_snap: Optional[Dict[str, Any]] = None  # {tf: {wt1, wt2, zone, cross, atr_trend}}

    # ── Сфера 4: MTF SMC Specialist ─────────────────────────────────────
    smc_verdict: Optional[str] = None         # STRONG_BULL_ZONE / WEAK_ZONE / STRONG_BEAR_ZONE
    smc_confidence: float = 0.0
    smc_snap: Optional[Dict[str, Any]] = None

    # ── Сфера 5: Cross-Market ───────────────────────────────────────────
    btc_regime: Optional[str] = None          # TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
    btc_move_pct: float = 0.0
    cross_market_time: Optional[datetime] = None

    # ── Сфера 6: Market Regime ──────────────────────────────────────────
    regime: Optional[str] = None              # TREND_UP / TREND_DOWN / RANGE / HIGH_VOL
    reversal_mode: Optional[str] = None       # TREND / REVERSAL / UNCLEAR
    sideways_bars: int = 0                    # счётчик последовательных RANGE-циклов
    sideways_mode_active: bool = False        # True когда sideways_bars >= threshold

    # ── Сфера 7: Signal Detectors ───────────────────────────────────────
    last_signal_type: Optional[str] = None
    last_signal_direction: Optional[str] = None
    last_signal_strength: float = 0.0
    last_signal_time: Optional[datetime] = None
    active_divergence: Optional[Dict] = None  # активная дивергенция (если есть)
    anomaly_active: bool = False

    # ── OTE LTF (ote_nested) — 5m триггер для вотчлиста/ручной торговли ──
    # ARCH-128: observability. ote_observer пишет ARMED (зреет) / FIRE (выстрел)
    # с полными вводными — чтобы пользователь видел сигнал ЗАРАНЕЕ и мог войти руками.
    ote_ltf_status: Optional[str] = None           # ARMED / FIRE / None
    ote_ltf_score: int = 0                          # conf_score (набрано подтверждений)
    ote_ltf_min: int = 3                            # min_confirmations (порог выстрела)
    ote_ltf_direction: Optional[str] = None         # long / short
    ote_ltf_trigger: Optional[str] = None           # FVG / OB / EQL / SC
    ote_ltf_entry: Optional[float] = None           # цена входа
    ote_ltf_sl: Optional[float] = None              # стоп-лосс
    ote_ltf_tp1: Optional[float] = None             # частичный +1R
    ote_ltf_tp: Optional[float] = None              # финальная цель (runner)
    ote_ltf_setup: Optional[str] = None             # setup_id из шкафа
    ote_ltf_time: Optional[datetime] = None

    # ── УНИВЕРСАЛЬНЫЙ WATCHLIST (WATCHLIST-UNI 22.06): реестр сигналов-кандидатов
    # ОТ ЛЮБОЙ стратегии. Ключ = имя стратегии ('oko_ote'/'ote_nested'/...), значение =
    # WatchlistEntry-dict {strategy,direction,status,entry,sl,targets,setup,confs,potential_pct,tf,ts}.
    # Новая стратегия = просто bus.set_watchlist(strategy, entry). potential в % (НЕ фейк-R).
    watchlist: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ── Сфера 8: Pivot Levels ───────────────────────────────────────────
    pivot_snap: Optional[Dict[str, Any]] = None   # {1W: {PP, S1, ...}, 1D: {...}}
    near_pivot: Optional[Dict] = None              # {level, source, distance_pct}

    # ── Сфера 9: Narrative Builder ──────────────────────────────────────
    last_narrative: Optional[str] = None
    last_narrative_time: Optional[datetime] = None
    last_p_win: float = 0.0

    # ── Сфера 10: Exit Manager ──────────────────────────────────────────
    open_trade_id: Optional[int] = None
    tsl_active: bool = False
    tp1_hit: bool = False

    # ── Сфера 11: Post-Trade Analyser ───────────────────────────────────
    cascade_count: int = 0
    last_direction: Optional[str] = None
    last_close_status: Optional[str] = None
    last_close_time: Optional[datetime] = None
    avg_r_cascade: float = 0.0
    post_tsl_data: Optional[dict] = None

    # ── Спринт «Замыкание разрывов» — ARCH-88: Per-pair Loss Memory ─────
    sl_streak_count: int = 0                                   # сбрасывается при TP/TSL с R>0
    last_n_outcomes: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    pair_avg_r_last_20: float = 0.0
    last_sl_at: Optional[datetime] = None
    pair_cooldown_until: Optional[datetime] = None             # gate заблокировал пару до этой точки

    # ── ARCH-91: Narrative feedback loop ────────────────────────────────
    last_narrative_outcome: Optional[dict] = None              # {status, R, lost_reason, closed_at}

    # ── Сфера 12: Self-Diagnostics ──────────────────────────────────────
    spheres_ok: int = 0               # сколько сфер обновляли данные за последний час
    last_diagnostic_time: Optional[datetime] = None


@dataclass
class AccountState:
    """L2 ПОРТФЕЛЬ-измерение шины (BUS-ACCOUNT-EPIC).

    Equity/маржа аккаунта живут в шине — push от EXEC-WS ACCOUNT_UPDATE (wb=wallet balance),
    НЕ REST-polling. Потребители (trading/status, position_sizer, Risk Monitor) читают отсюда.
    Параллельно PairState (L1 исполнение) — это L2 (портфель). Фундамент L3 TraderState.
    """
    account_id: int
    equity: float = 0.0
    available: Optional[float] = None
    used_margin: Optional[float] = None
    # symbol → {qty, side, entry, upnl, ts} — позиции аккаунта (push от EXEC-WS ACCOUNT_UPDATE P[])
    positions: Dict[str, dict] = field(default_factory=dict)
    updated_at: Optional[datetime] = None


class PairContextBus:
    """
    Центральная Сфера Куба Метатрона — Shared Context Bus.

    Mesh-связность: каждая сфера публикует → подписчики реагируют.
    Per-pair состояние: PairState (L1, 13 сфер) · Per-account: AccountState (L2: equity/позиции).

    Thread-safe в рамках asyncio event loop (+ AccountState читается из dashboard-потока под GIL).
    Данные теряются при перезапуске — пересчитываются за первый цикл.

    ═══════════════════════════════════════════════════════════════════════════════
    📜 КОНТРАКТ «КАК СЛУШАТЬ КУБ» (канон — для каждого нового слушателя, BACKLOG #10)
    ═══════════════════════════════════════════════════════════════════════════════
    Два паттерна доступа — НЕ плодить третий, НЕ дёргать REST из потребителя:

    ── PUSH (реакция на СОБЫТИЕ) ──────────────────────────────────────────────
      bus.subscribe_async(SphereEvent.SMC_SNAP_UPDATED, my_async_handler)
      • handler(symbol, data) — async, ЛЁГКИЙ (внутри create_task / очередь, не блокировать)
      • для: уведомления, real-time dashboard, реакции на trade_closed/regime/signal
      • publish() синхронный → subscribe_async оборачивает в create_task (изоляция ошибок)

    ── PULL (чтение СОСТОЯНИЯ) ────────────────────────────────────────────────
      bus.get(symbol) / get_full_state(symbol)      — L1 пара (snap/regime/wt/pivot)
      bus.get_account(id) / total_equity()          — L2 equity (живой, push от EXEC-WS)
      bus.all_positions()                           — L2 позиции (push от EXEC-WS + position_sync)
      • для: position_sizer, dashboard-рендер, аналитика, gate-проверки
      • НИКОГДА не REST из потребителя в threaded-контексте (cross-loop вис) — только шина

    ── PRODUCE (запись в шину) ────────────────────────────────────────────────
      bus.publish(symbol, event, data) — сфера публикует событие (scan_loop, sub_cube)
      bus.update(symbol, **fields)     — обновить PairState
      bus.update_account / update_position / set_account_positions — L2 (EXEC-WS, position_sync)

    Правило: данные ЖИВУТ в шине (push от источника) → потребители слушают/читают.
    Источник истины — шина, не REST-дёрганье. Это «дыхание Куба».
    """

    def __init__(self) -> None:
        self._states: dict[str, PairState] = {}
        self._accounts: dict[int, AccountState] = {}   # L2: account_id → equity/маржа
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_log: List[Dict] = []   # последние N событий для диагностики
        self._max_log = 200
        self._open_trades: list[dict] = []               # L2: снапшот открытых сделок (push от trade_tracker)
        self._open_trades_ts: Optional[datetime] = None  # ts последней публикации (None = цикл ещё не публиковал)

    def get(self, symbol: str) -> PairState:
        """Возвращает PairState для символа, создаёт если нет."""
        if symbol not in self._states:
            self._states[symbol] = PairState(symbol=symbol)
        return self._states[symbol]

    def update(self, symbol: str, **kwargs) -> None:
        """Обновляет поля PairState для символа."""
        state = self.get(symbol)
        for key, val in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, val)
            else:
                logger.debug("[Bus] неизвестное поле PairState: %s", key)

    def set_watchlist(self, symbol: str, strategy: str, entry: Optional[Dict[str, Any]]) -> None:
        """WATCHLIST-UNI: публикует/обновляет watchlist-запись стратегии (или удаляет если None).

        entry — dict единого формата: {direction,status,entry,sl,targets,setup,confs,potential_pct,tf}.
        Любая стратегия зовёт это; dashboard читает state.watchlist (все стратегии). % НЕ R.
        """
        state = self.get(symbol)
        if entry is None:
            state.watchlist.pop(strategy, None)
        else:
            e = dict(entry); e["strategy"] = strategy
            e.setdefault("ts", datetime.now(timezone.utc).isoformat())
            state.watchlist[strategy] = e

    def clear_watchlist(self, symbol: str, strategy: str) -> None:
        """Снять watchlist-запись стратегии (сетап исчез/инвалидирован)."""
        self.get(symbol).watchlist.pop(strategy, None)

    def all_symbols(self) -> list[str]:
        """Все символы с ненулевым состоянием."""
        return list(self._states.keys())

    def symbols_with_post_tsl(self) -> list[str]:
        """Символы с активной post_tsl_data (для TriggerBus)."""
        return [sym for sym, s in self._states.items() if s.post_tsl_data is not None]

    def reset(self, symbol: str) -> None:
        """Сбросить состояние по символу."""
        if symbol in self._states:
            del self._states[symbol]

    # ── L2: account-измерение (BUS-ACCOUNT-EPIC) ─────────────────────────
    def update_account(self, account_id: int, equity: Optional[float] = None,
                       available: Optional[float] = None,
                       used_margin: Optional[float] = None) -> None:
        """Обновить AccountState (push от EXEC-WS ACCOUNT_UPDATE). Создаёт если нет."""
        st = self._accounts.get(account_id)
        if st is None:
            st = AccountState(account_id=account_id)
            self._accounts[account_id] = st
        if equity is not None:
            st.equity = equity
        if available is not None:
            st.available = available
        if used_margin is not None:
            st.used_margin = used_margin
        st.updated_at = datetime.now(timezone.utc)

    def get_account(self, account_id: int) -> Optional[AccountState]:
        return self._accounts.get(account_id)

    def all_accounts(self) -> list[AccountState]:
        return list(self._accounts.values())

    def total_equity(self) -> Optional[float]:
        """Сумма equity всех аккаунтов из шины (живой deposit). None если шина пуста (cold start)."""
        vals = [s.equity for s in self._accounts.values() if s.equity and s.equity > 0]
        return round(sum(vals), 2) if vals else None

    def update_position(self, account_id: int, symbol: str, qty: float, side: str = "",
                        entry: Optional[float] = None, upnl: Optional[float] = None,
                        leverage: Optional[int] = None, mark: Optional[float] = None) -> None:
        """Обновить позицию аккаунта (push от EXEC-WS ACCOUNT_UPDATE P[]). qty=0 → удалить (закрыта).

        leverage/mark ACCOUNT_UPDATE НЕ несёт (приходят от position_sync REST) → если не
        переданы, СОХРАНЯЕМ из предыдущего снапшота (EXEC-WS не затирает реальные с биржи)."""
        st = self._accounts.get(account_id)
        if st is None:
            st = AccountState(account_id=account_id)
            self._accounts[account_id] = st
        if not qty:
            st.positions.pop(symbol, None)
        else:
            _old = st.positions.get(symbol, {})
            st.positions[symbol] = {
                "qty": qty, "side": side, "entry": entry, "upnl": upnl,
                "leverage": leverage if leverage is not None else _old.get("leverage"),
                "mark": mark if mark is not None else _old.get("mark"),
                "ts": datetime.now(timezone.utc),
            }
        st.updated_at = datetime.now(timezone.utc)

    def set_account_positions(self, account_id: int, positions: Dict[str, dict]) -> None:
        """Полная замена позиций аккаунта (snapshot от position_sync — удаляет закрытые).
        EXEC-WS update_position — инкремент между snapshot'ами."""
        st = self._accounts.get(account_id)
        if st is None:
            st = AccountState(account_id=account_id)
            self._accounts[account_id] = st
        st.positions = dict(positions)
        st.updated_at = datetime.now(timezone.utc)

    def all_positions(self) -> list[dict]:
        """Все позиции всех аккаунтов из шины (для dashboard sync-panel — без REST).

        ДЕДУП master↔sub (27.06): мастер-ключ (acc1) тянет позиции И суб-аккаунтов →
        одна позиция попадает дважды (acc1-фантом + acc2-реал; у Егора 21=11+10). Суб
        авторитетен для СВОИХ позиций (свой ключ), поэтому (symbol, side) из суба
        ВЫТЕСНЯЕТ копию мастера (acc1) — реальный account_id = суб, где он её держит.
        Дедуп на чтении: ACCOUNT_UPDATE суб-id не несёт → владельца на событии мастера
        знать нельзя; устойчиво к порядку стримов. Корень [[hedge_close_multiacct_root]]."""
        # суб-владельцы (account_id > 1 = не master) по (symbol, side)
        sub_owned: set[tuple[str, str]] = {
            (sym, str(p.get("side", "")).upper())
            for acc_id, st in self._accounts.items() if acc_id > 1
            for sym, p in st.positions.items()
        }
        out: list[dict] = []
        for acc_id, st in self._accounts.items():
            for sym, p in st.positions.items():
                # master-фантом: эту (symbol, side) уже держит суб → пропустить копию acc1
                if acc_id <= 1 and (sym, str(p.get("side", "")).upper()) in sub_owned:
                    continue
                out.append({"account_id": acc_id, "symbol": sym, **p})
        return out

    # ── Оперативный снапшот открытых сделок (источник для dashboard /api/open) ──
    # Лёгкий операционный набор полей (без features_json и пр.) — ровно то, что нужно дашборду.
    _OPEN_TRADE_FIELDS = (
        "id", "symbol", "direction", "signal_type", "entry_price", "stop_loss", "original_sl",
        "take_profit", "created_at", "execution_mode", "account_id", "tsl_activated", "qty",
    )

    def set_open_trades(self, rows: list[dict]) -> None:
        """PRODUCE: снапшот открытых сделок (push от trade_tracker — он и так грузит их
        каждый цикл get_open_trades). Проектируем на лёгкий набор → источник /api/open БЕЗ
        синхронного SQL по simulated_trades (29K, лок с пишущим горячим циклом → ~20с-таймаут).
        Пустой список — валидная публикация (все закрылись → дашборд очищается)."""
        self._open_trades = [{k: r.get(k) for k in self._OPEN_TRADE_FIELDS} for r in rows]
        self._open_trades_ts = datetime.now(timezone.utc)

    def open_trades_snapshot(self) -> tuple[list[dict], Optional[datetime]]:
        """PULL: оперативные открытые сделки из шины (dashboard /api/open, без тяжёлого SQL).
        Возвращает (копия списка, ts последней публикации). ts=None → цикл ещё не публиковал."""
        return [dict(t) for t in self._open_trades], self._open_trades_ts

    # ── BUS-CATALOG: «меню» данных шины (точка входа) ────────────────────
    def catalog(self) -> dict:
        """Программный каталог шины (события + L1 + L2): что есть, тип, источник, как подключить.
        Пришёл к шине → catalog() → выбрал «провод». Логика в core/context/bus_catalog.py."""
        from core.context.bus_catalog import catalog as _cat
        return _cat()

    def catalog_markdown(self) -> str:
        """Меню шины в markdown (для человека/дашборда)."""
        from core.context.bus_catalog import to_markdown as _md
        return _md()

    # ── pub/sub шина ─────────────────────────────────────────────────────

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """
        Регистрирует СИНХРОННЫЙ обработчик события.
        handler(symbol: str, data: dict) → None
        Одна сфера может подписаться на несколько типов событий.
        Вызывается синхронно в стеке publish() — handler ОБЯЗАН быть лёгким.
        """
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.debug("[Bus] subscribe: %s → %s", event_type, getattr(handler, "__qualname__", str(handler)))

    def subscribe_async(self, event_type: str, async_handler: Callable) -> None:
        """
        Регистрирует ASYNC-обработчик (внешний потребитель: Notification, Dashboard, AI).

        publish() синхронный → оборачиваем в sync-адаптер, который ставит
        `asyncio.create_task(async_handler(symbol, data))`. Так тяжёлый потребитель
        НЕ блокирует hot path scan_one — только постановка task в loop (дёшево).
        Ошибки изолированы: упавший подписчик не валит publish/scan_one.

        async_handler(symbol: str, data: dict) → awaitable
        """
        async def _safe_run(symbol: str, data: dict) -> None:
            # Исключения подписчика глушим здесь, иначе "Task exception was never
            # retrieved" в логах + потенциальная утечка. Подписчик НЕ валит ничего.
            try:
                await async_handler(symbol, data)
            except Exception as e:
                logger.debug("[Bus] async subscriber %s error: %s", event_type, e)

        def _adapter(symbol: str, data: dict) -> None:
            try:
                asyncio.get_running_loop().create_task(_safe_run(symbol, data))
            except RuntimeError:
                # нет running loop (publish из не-async контекста) — пропускаем
                logger.debug("[Bus] subscribe_async: no running loop for %s", event_type)
            except Exception as e:
                logger.debug("[Bus] subscribe_async adapter %s: %s", event_type, e)

        _adapter.__qualname__ = f"async:{getattr(async_handler, '__qualname__', str(async_handler))}"
        self._subscribers.setdefault(event_type, []).append(_adapter)
        logger.debug("[Bus] subscribe_async: %s → %s", event_type, _adapter.__qualname__)

    def publish(self, symbol: str, event_type: str, data: dict = None) -> None:
        """
        Публикует событие. Синхронно вызывает всех подписчиков.
        Также обновляет PairState соответствующими полями.
        """
        data = data or {}

        # Авто-обновление PairState по типу события
        self._auto_update_state(symbol, event_type, data)

        # Лог события
        if len(self._event_log) >= self._max_log:
            self._event_log.pop(0)
        self._event_log.append({
            "symbol": symbol, "event": event_type,
            "time": datetime.now(timezone.utc).isoformat(),
            "keys": list(data.keys()),
        })

        # Вызываем подписчиков
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                handler(symbol, data)
            except Exception as e:
                logger.warning("[Bus] subscriber error (%s → %s): %s",
                               event_type, getattr(handler, "__qualname__", "?"), e)

    def _auto_update_state(self, symbol: str, event_type: str, data: dict) -> None:
        """Автоматически обновляет PairState при публикации события."""
        state = self.get(symbol)
        now = datetime.now(timezone.utc)

        if event_type == SphereEvent.OHLCV_UPDATED:
            state.last_ohlcv_time = now
            tf = data.get("tf")
            if tf and tf not in state.ohlcv_tfs_loaded:
                state.ohlcv_tfs_loaded.append(tf)
            # Наполнение tick_price из OHLCV close — базовый источник цены в шине,
            # работает даже когда WsFeed off (TICK_PRICE не приходит). WsFeed (если on)
            # перезапишет живее между циклами. Единый источник цены = шина.
            _c = data.get("close")
            if _c:
                state.tick_price = float(_c)
                state.tick_time = now

        elif event_type == SphereEvent.TICK_PRICE:
            state.tick_price = data.get("price")
            state.tick_time = now

        elif event_type == SphereEvent.WT_VERDICT:
            state.wt_verdict = data.get("label")
            state.wt_confidence = data.get("confidence", 0.0)

        elif event_type == SphereEvent.WT_SNAP_UPDATED:
            state.wt_snap = data

        elif event_type == SphereEvent.SMC_VERDICT:
            state.smc_verdict = data.get("label")
            state.smc_confidence = data.get("confidence", 0.0)

        elif event_type == SphereEvent.SMC_SNAP_UPDATED:
            state.smc_snap = data

        elif event_type == SphereEvent.CROSS_MARKET:
            state.btc_regime = data.get("btc_regime")
            state.btc_move_pct = data.get("btc_move_pct", 0.0)
            state.cross_market_time = now

        elif event_type == SphereEvent.REGIME_UPDATED:
            state.regime = data.get("regime")
            state.reversal_mode = data.get("mode")
            if state.regime == "RANGE":
                state.sideways_bars = min(state.sideways_bars + 1, 10)
            else:
                state.sideways_bars = 0
            threshold = data.get("sideways_threshold", 3)
            state.sideways_mode_active = (state.sideways_bars >= threshold)

        elif event_type == SphereEvent.SIGNAL_DETECTED:
            state.last_signal_type = data.get("signal_type")
            state.last_signal_direction = data.get("direction")
            state.last_signal_strength = data.get("strength", 0.0)
            state.last_signal_time = now

        elif event_type == SphereEvent.ANOMALY_DETECTED:
            state.anomaly_active = True

        elif event_type == SphereEvent.DIVERGENCE_FOUND:
            state.active_divergence = data

        elif event_type == SphereEvent.PIVOT_TOUCH:
            state.near_pivot = data

        elif event_type == SphereEvent.PIVOT_SNAP_UPDATED:
            state.pivot_snap = data

        elif event_type == SphereEvent.NARRATIVE_BUILT:
            state.last_narrative = data.get("text")
            state.last_narrative_time = now
            state.last_p_win = data.get("p_win", 0.0)

        elif event_type == SphereEvent.TSL_MOVED:
            state.tsl_active = True
            state.open_trade_id = data.get("trade_id")

        elif event_type == SphereEvent.TP1_HIT:
            state.tp1_hit = True

        elif event_type == SphereEvent.POSITION_CLOSED:
            state.open_trade_id = None
            state.tsl_active = False
            state.tp1_hit = False

        elif event_type == SphereEvent.TRADE_CLOSED:
            state.last_close_status = data.get("status")
            state.last_close_time = now

        elif event_type == SphereEvent.CASCADE_UPDATED:
            state.cascade_count = data.get("cascade_count", 0)
            state.avg_r_cascade = data.get("avg_r", 0.0)
            state.last_direction = data.get("direction")

        elif event_type == SphereEvent.OTE_ZONE_SET:
            state.post_tsl_data = data

        # CUBE-08: пересчёт spheres_ok — сколько ключевых сфер уже заполнены
        state.spheres_ok = sum([
            state.last_ohlcv_time is not None,                      # сфера 1: данные загружены
            state.wt_snap is not None,                              # сфера 3: WT снапшот
            state.wt_verdict is not None,                           # сфера 3: WT вердикт
            state.smc_verdict is not None,                          # сфера 4: SMC вердикт
            bool(state.regime),                                     # сфера 6: режим рынка
            state.last_signal_type is not None,                     # сфера 7: последний сигнал
        ])

    # ── Полные снимки ────────────────────────────────────────────────────

    def get_full_state(self, symbol: str) -> dict:
        """Полный снимок состояния пары — для Narrative Builder и отладки."""
        state = self.get(symbol)
        return {
            # Сфера 1-2
            "last_ohlcv_time":   state.last_ohlcv_time,
            "tick_price":        state.tick_price,
            # Сфера 3
            "wt_verdict":        state.wt_verdict,
            "wt_confidence":     state.wt_confidence,
            "wt_snap":           state.wt_snap,
            # Сфера 4
            "smc_verdict":       state.smc_verdict,
            "smc_confidence":    state.smc_confidence,
            # 25.07 (DC-агент слеп): smc_snap/pivot_snap ЖИЛИ в шине, но НЕ экспортировались
            # get_full_state — API-дырка, все внешние читатели видели пусто.
            "smc_snap":          state.smc_snap,
            "pivot_snap":        state.pivot_snap,
            # Сфера 5
            "btc_regime":        state.btc_regime,
            "cross_market_time": state.cross_market_time,
            # Сфера 6
            "regime":            state.regime,
            "reversal_mode":     state.reversal_mode,
            # Сфера 7
            "last_signal_type":      state.last_signal_type,
            "last_signal_direction": state.last_signal_direction,
            "last_signal_strength":  state.last_signal_strength,
            "active_divergence":     state.active_divergence,
            "anomaly_active":        state.anomaly_active,
            # OTE LTF (ote_nested 5m trigger)
            "ote_ltf_status":    state.ote_ltf_status,
            "ote_ltf_score":     state.ote_ltf_score,
            "ote_ltf_min":       state.ote_ltf_min,
            "ote_ltf_direction": state.ote_ltf_direction,
            "ote_ltf_trigger":   state.ote_ltf_trigger,
            "ote_ltf_entry":     state.ote_ltf_entry,
            "ote_ltf_sl":        state.ote_ltf_sl,
            "ote_ltf_tp1":       state.ote_ltf_tp1,
            "ote_ltf_tp":        state.ote_ltf_tp,
            "ote_ltf_setup":     state.ote_ltf_setup,
            # WATCHLIST-UNI: универсальный реестр сигналов всех стратегий (% не R)
            "watchlist":         state.watchlist,
            # Сфера 8
            "near_pivot":        state.near_pivot,
            # Сфера 9
            "last_narrative":    state.last_narrative,
            "last_p_win":        state.last_p_win,
            # Сфера 10
            "open_trade_id":     state.open_trade_id,
            "tsl_active":        state.tsl_active,
            "tp1_hit":           state.tp1_hit,
            # Сфера 11
            "cascade_count":     state.cascade_count,
            "last_direction":    state.last_direction,
            "last_close_status": state.last_close_status,
            "avg_r_cascade":     state.avg_r_cascade,
            "post_tsl_data":     state.post_tsl_data,
            # Сфера 12
            "spheres_ok":        state.spheres_ok,
        }

    def get_event_log(self, limit: int = 50) -> List[Dict]:
        """Последние N событий — для диагностики."""
        return self._event_log[-limit:]

    def stats(self) -> dict:
        """Статистика шины — для /status и дашборда."""
        total_subs = sum(len(v) for v in self._subscribers.values())
        event_types = list(self._subscribers.keys())
        return {
            "pairs_tracked":    len(self._states),
            "event_types":      len(event_types),
            "total_subscribers": total_subs,
            "event_log_size":   len(self._event_log),
            "subscriptions":    {k: len(v) for k, v in self._subscribers.items()},
        }
