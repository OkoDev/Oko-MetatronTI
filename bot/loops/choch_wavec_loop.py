# -*- coding: utf-8 -*-
"""CHoCH → ОТКАТ 0.236 → ВОЛНА C — луп механики, прошедшей OOS (18.08.2026, Даат).

Единственная механика проекта, пережившая перекрёстный OOS (OOS-монеты × OOS-время:
n=1150, WR 53.1%, PF 1.17) — [[choch_pullback_waveC_oos_passed]]. Расчёт целиком в
`core/smc/choch_wavec.py`; здесь только вселенная, дедуп, журнал и отправка.

🔴 ПО УМОЛЧАНИЮ SHADOW: сигналы пишутся в таблицу `choch_shadow` и резолвятся по
свечам, на биржу НЕ идут. Причина — единственный вопрос, который бэктест закрыть НЕ
может: исполнятся ли ЛИМИТКИ по заявленной цене. Бэктест считает фил по касанию
`high >= entry`, биржа — по стакану. Плюс [[backlog_vst_spread_poisons_forward]]:
спред VST в 10–350× шире боевого, поэтому мерить надо не «сколько дал VST», а
«совпала ли цена фила с заявленной». Снимать shadow — только после ≥20-30 филов.

Живой режим (shadow: false) шлёт в router source=choch_wavec с LIMIT-входом —
рыночный вход съедает 0.44% налога на исполнение ([[live_root_cause_costs_eat_tight_stops]]),
а вся экономика механики считана на лимите (косты 0.35%).

Gated: trading.choch_wavec.enabled (по умолчанию ВЫКЛЮЧЕН).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass

import pandas as pd

from core.smc.choch_wavec import WAIT_BARS, boosters, find_setup, is_junk

logger = logging.getLogger(__name__)

POLL_SEC = 900          # бар 1h закрывается раз в час — чаще сканировать нечего
HOLD_BARS = 96          # столько держим позицию после фила (из бэктеста механики)
SRC = "choch_wavec"


@dataclass(frozen=True)
class Instance:
    """ТФ-инстанс механики. Всё, чем инстансы отличаются друг от друга.

    🔴 28.09 второй инстанс (4h) — по замеру расширения по масштабу. Окна КАЛЕНДАРНЫЕ:
    ожидание фила 12 ч и удержание 96 ч одинаковы на всех ТФ, в барах они разные.
    Константа в барах, перенесённая между ТФ молча, уже стоила нам 15m-близнеца
    ([[twins_15m_stabilized_by_measure]]).
    """
    src: str                 # имя источника = ключ политики и trade_mode
    tf: str                  # таймфрейм свечей
    tf_hours: float          # длительность бара в часах — из неё считаются окна
    table: str               # таблица исследовательского журнала
    tag: str                 # тег в логе

    @property
    def wait_bars(self) -> int:
        """Окно ожидания фила В БАРАХ этого ТФ (календарно всегда 12 ч)."""
        return max(1, int(round(WAIT_BARS / self.tf_hours)))

    @property
    def hold_bars(self) -> int:
        """Горизонт удержания В БАРАХ этого ТФ (календарно всегда 96 ч)."""
        return max(1, int(round(HOLD_BARS / self.tf_hours)))

    @property
    def cfg_key(self) -> str:
        return f"trading.{self.src}"


INSTANCE_1H = Instance(src="choch_wavec", tf="1h", tf_hours=1.0, table="choch_shadow", tag="CHOCH-C")
INSTANCE_4H = Instance(src="choch_wavec_4h", tf="4h", tf_hours=4.0, table="choch_shadow_4h", tag="CHOCH-C4")

_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT DEFAULT (datetime('now')),
    symbol       TEXT NOT NULL,
    choch_ts     TEXT NOT NULL,          -- бар слома: ключ дедупа вместе с symbol
    entry        REAL NOT NULL,          -- заявленная лимитная цена
    stop_loss    REAL NOT NULL,
    take_profit  REAL NOT NULL,
    stop_pct     REAL,
    price_at_signal REAL,
    block        REAL,                   -- вес магнитов на пути (обратный: меньше = лучше)
    shield       REAL,                   -- вес магнитов в зоне стопа
    atr_pct      REAL,
    under_s1w    INTEGER,
    good_hour    INTEGER,
    boosters_n   INTEGER,
    status       TEXT DEFAULT 'WAITING', -- WAITING|FILLED|TP|SL|EXPIRED|INVALID
    filled_at    TEXT,
    resolved_at  TEXT,
    result_pct   REAL,                   -- итог в % от входа (SHORT: вход>выход = плюс)
    bars_to_fill INTEGER,
    UNIQUE(symbol, choch_ts)
)
"""


def _conn(bot, inst: Instance = None):
    inst = inst or INSTANCE_1H
    c = sqlite3.connect(bot.trade_simulator.db_path, timeout=10)
    c.execute(_TABLE.format(table=inst.table))
    return c


async def _fetch_tf(bot, symbol: str, limit: int, tf: str = "1h"):
    """OHLCV нужного ТФ → DatetimeIndex UTC. D-042: data_collector отдаёт колонку 'time' (мс)."""
    try:
        df = await bot.data_collector.get_ohlcv(symbol, timeframe=tf, limit=limit)
    except Exception:                                          # noqa: BLE001
        return None
    if df is None or len(df) < 300:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    ts_col = "ts" if "ts" in df.columns else ("time" if "time" in df.columns else None)
    if ts_col is not None:
        df[ts_col] = pd.to_datetime(df[ts_col], unit="ms", utc=True, errors="coerce")
        df = df.set_index(ts_col)
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    return df


def _resolve(conn, symbol: str, df: pd.DataFrame, inst: Instance = None) -> None:
    inst = inst or INSTANCE_1H
    tbl = inst.table
    """Догоняет статусы незакрытых записей символа по закрытым барам.

    Порядок проверок повторяет бэктест: сначала «стоп задет ДО входа» (сетап умер, а не
    убыток), затем фил, затем исход. 🔴 Урок замера 18.08: при «ни стоп, ни цель не
    сработали» обе переменные равнялись 10**9 и сравнение индексов давало ложный СТОП —
    база показывала PF 0.27 вместо 1.15. Поэтому «ничего не сработало» проверяется ЯВНО.
    """
    rows = conn.execute(
        f"SELECT id,choch_ts,entry,stop_loss,take_profit,status,filled_at FROM {tbl} "
        "WHERE symbol=? AND status IN ('WAITING','FILLED')", (symbol,)).fetchall()
    if not rows:
        return
    d = df.iloc[:-1]                                    # только закрытые бары
    for rid, choch_ts, entry, sl, tp, status, filled_at in rows:
        try:
            t0 = pd.Timestamp(filled_at if status == "FILLED" else choch_ts, tz="UTC")
        except Exception:                                      # noqa: BLE001
            continue
        w = d[d.index > t0]
        if w.empty:
            continue
        hi, lo, idx = w.high.values, w.low.values, w.index

        if status == "WAITING":
            # 🔴 ОКНО ФИЛА = WAIT_BARS баров, как в замере (`range(i+1, i+1+wait)`).
            # Поиск по ВСЕЙ истории завышал число входов: бот заходил бы на протухших
            # сетапах, которых в бэктесте не было. Проверка B в verify_choch_loop.py
            # поймала это на 1086 из 1807 сетапов.
            win = min(len(hi), inst.wait_bars)
            f_entry = next((k for k in range(win) if hi[k] >= entry), None)
            f_stop = next((k for k in range(win) if hi[k] >= sl), None)
            if f_stop is not None and (f_entry is None or f_stop < f_entry):
                conn.execute(f"UPDATE {tbl} SET status='INVALID',"
                             "resolved_at=? WHERE id=?", (str(idx[f_stop]), rid))
                continue
            if f_entry is None:
                if len(hi) >= inst.wait_bars:                # окно отката исчерпано
                    conn.execute(f"UPDATE {tbl} SET status='EXPIRED',"
                                 "resolved_at=? WHERE id=?", (str(idx[win - 1]), rid))
                continue
            conn.execute(f"UPDATE {tbl} SET status='FILLED',filled_at=?,"
                         "bars_to_fill=? WHERE id=?", (str(idx[f_entry]), f_entry + 1, rid))
            hi, lo, idx = hi[f_entry + 1:], lo[f_entry + 1:], idx[f_entry + 1:]
            if len(hi) == 0:
                continue

        # Позиция живёт HOLD_BARS баров от фила — дальше выход по close, как в замере.
        hold = min(len(hi), inst.hold_bars)
        h_tp = next((k for k in range(hold) if lo[k] <= tp), None)
        h_sl = next((k for k in range(hold) if hi[k] >= sl), None)
        if h_tp is None and h_sl is None:
            if len(hi) >= inst.hold_bars:                    # вышли по времени — считаем по close
                out = float(w.close.values[len(w) - len(hi) + hold - 1])
                conn.execute(f"UPDATE {tbl} SET status='EXPIRED',resolved_at=?,"
                             "result_pct=? WHERE id=?",
                             (str(idx[hold - 1]), (entry - out) / entry * 100, rid))
            continue
        if h_sl is not None and (h_tp is None or h_sl <= h_tp):
            conn.execute(f"UPDATE {tbl} SET status='SL',resolved_at=?,result_pct=?"
                         " WHERE id=?", (str(idx[h_sl]), (entry - sl) / entry * 100, rid))
        else:
            conn.execute(f"UPDATE {tbl} SET status='TP',resolved_at=?,result_pct=?"
                         " WHERE id=?", (str(idx[h_tp]), (entry - tp) / entry * 100, rid))


async def choch_wavec_loop(bot, inst: Instance = None):
    inst = inst or INSTANCE_1H
    tbl = inst.table
    cfg = (bot.config.get(inst.cfg_key, {}) or {})
    if not cfg.get("enabled", False):
        logger.info("[%s] выключен (%s.enabled=false)", inst.tag, inst.cfg_key)
        return

    shadow = bool(cfg.get("shadow", True))
    top_n = int(cfg.get("universe_top", 250))
    # 🔑 КОРИДОР СТОПА 8-15% (замер 19.08 на 198 монетах, 4885 сделок, окно 2022-2026):
    # PF базы 1.07 → 1.21, медиана +0.055% → +0.881%, хрупкость безтоп10% −6193 → −1738.
    # Фильтр поднимает PF в КАЖДОМ из пяти лет (1.48→1.80 · 0.65→0.79 · 1.08→1.17 ·
    # 1.38→1.48 · 0.92→1.03) — это не подгонка под год. Совпадает с законом размера
    # ([[bigflush_edge_size_not_timeframe]]): мёртвая зона — малые стопы, где косты
    # съедают цель. Ниже 8% PF 1.01, выше 15% PF 0.88.
    min_stop = float(cfg.get("min_stop_pct", 8.0))
    max_stop = float(cfg.get("max_stop_pct", 15.0))
    # 🔑 ВТОРАЯ ПОЛОВИНА ЯДРА — ВЫСОКАЯ ВОЛАТИЛЬНОСТЬ (замер 19.08, 120 монет):
    # «стоп 8-15% + ATR>1.59%» — ЕДИНСТВЕННАЯ конфигурация с ПОЛОЖИТЕЛЬНЫМ безтоп10%
    # (+99), то есть плюс не висит на хвосте. По годам против контроля (случайный вход
    # той же геометрии): 2022 PF 1.99/1.20 · 2023 0.62/0.68 ❌ · 2024 1.85/0.84 ·
    # 2025 1.48/1.11 · 2026 **3.06/0.99** (WR 76%, медиана +4.69%, n=25).
    # Провал один — 2023, бычий год: шортовая механика против режима.
    min_atr = float(cfg.get("min_atr_pct", 1.59))
    min_boost = int(cfg.get("min_boosters", 0))
    cap = int(cfg.get("max_open", 8))
    # 🔴 22.08 ДВА ЛИМИТА (DEV-239): позиции = рыночный риск, заявки = резерв маржи.
    # Вход у choch_wavec ЛИМИТНЫЙ → ожидающая заявка занимала слот риска, не будучи
    # в рынке. У impulse_fib это стоило 8 часов простоя ([[cap_pending_not_risk_slot]]).
    cap_pending = int(cfg.get("max_pending", cap))
    bars = int(cfg.get("bars", 1000))
    logger.info("[%s] старт · %s · вселенная top%d · стоп %.0f-%.0f%% · ATR>%.2f%% · "
                "усилителей≥%d · кап %d позиций / %d заявок · окно фила %d бар · удержание %d бар",
                inst.tag, "SHADOW (на биржу НЕ шлём)" if shadow else "🔴 ЖИВОЙ",
                top_n, min_stop, max_stop, min_atr, min_boost, cap, cap_pending,
                inst.wait_bars, inst.hold_bars)

    from core.signals.signal_models import (MarketContext, SignalDirection,
                                            TradingRecommendation)
    from core.context.context_factory import build_market_context, turnover_snapshot

    while True:
        conn = None
        try:
            await asyncio.sleep(POLL_SEC)
            pair_ctx = getattr(bot, "pair_context", None)
            if pair_ctx is None:
                continue

            # Вселенная = та, на которой мерился эдж: крипта, топ по обороту.
            # Расширение 250 → 400 монет роняло PF 1.15 → 1.06 (мусор разбавляет).
            turn = turnover_snapshot(bot)   # 29.09: через шину — один источник оборота
            # 🔴 29.09 FAIL-CLOSED: при пустой карте (bulk-запрос тикеров упал) у всех пар ключ
            # 0.0, сортировка вырождается, и «топ-250 по обороту» становится ПРОИЗВОЛЬНЫМИ 250.
            # А расширение вселенной 250 → 400 уже роняло PF 1.15 → 1.06 (строка выше).
            # Лучше пропустить цикл, чем торговать по неизвестной вселенной
            # ([[turnover_gate_fails_open]]).
            if not turn:
                logger.warning("[%s] карта оборотов ПУСТА — цикл пропущен, вселенная неизвестна",
                               inst.tag)
                continue
            syms = [s for s in pair_ctx.all_symbols() if not is_junk(s)]
            syms.sort(key=lambda s: -turn.get(s.split("/")[0], 0.0))
            syms = syms[:top_n]

            conn = _conn(bot, inst)
            # 🔴 21.08: КЭП ПО РЕАЛЬНЫМ СДЕЛКАМ, а не по журналу. Журнал —
            # исследовательский: в нём остаются и сетапы, которых на бирже нет (отбил
            # гейт), и они навсегда занимают слоты. Тот же дефект чинили в impulse_fib.
            if shadow:
                n_open = conn.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE status IN ('WAITING','FILLED')"
                ).fetchone()[0]
                n_pend = 0            # в shadow биржи нет — заявкам взяться неоткуда
            else:
                from core.trading.source_registry import slots as _slots
                _st = _slots(conn, inst.src, max_open=cap, max_pending=cap_pending)
                n_open, n_pend = _st["open"], _st["pending"]
                if not _st["can_place"]:
                    logger.info("[%s] новых заявок не будет: %s", inst.tag, _st["why"])
            found = 0
            hour = time.gmtime().tm_hour

            for sym in syms:
                df = await _fetch_tf(bot, sym, bars, inst.tf)
                await asyncio.sleep(0.05)
                if df is None:
                    continue
                _resolve(conn, sym, df, inst)
                # 🔴 N16 29.09: UPDATE из _resolve держал запись subscriptions.db до commit в КОНЦЕ
                # прохода — через все await _fetch_tf по 250 парам (полосы «database is locked» до 20 мин).
                conn.commit()
                # shadow: журнал сам себе кэп. Бой: ДВА лимита раздельно.
                if shadow:
                    if n_open + found >= cap:
                        continue
                elif n_open >= cap or n_pend + found >= cap_pending:
                    continue

                s = find_setup(df, symbol=sym)
                if not s or "reason" in s or not s["live"]:
                    continue
                if not (min_stop <= s["stop_pct"] <= max_stop):
                    continue
                if s["atr_pct"] < min_atr:
                    continue
                b = boosters(s, hour_utc=hour)
                if b["count"] < min_boost:
                    continue
                dup = conn.execute(f"SELECT 1 FROM {tbl} WHERE symbol=? AND choch_ts=?",
                                   (sym, s["choch_ts"])).fetchone()
                if dup:
                    continue

                conn.execute(
                    f"INSERT INTO {tbl} (symbol,choch_ts,entry,stop_loss,take_profit,"
                    "stop_pct,price_at_signal,block,shield,atr_pct,under_s1w,good_hour,"
                    "boosters_n) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sym, s["choch_ts"], s["entry"], s["sl"], s["tp"], s["stop_pct"],
                     s["price"], s["block"], s["shield"], s["atr_pct"],
                     int(b["under_s1w"]), int(b.get("good_hour", False)), b["count"]))
                conn.commit()
                found += 1
                logger.info("[%s] %s %s лимит %.6g (%.2f%% от цены) · стоп %.6g (%.2f%%) "
                            "· цель %.6g · помеха %.0f · ATR %.2f%% · усилителей %d",
                            inst.tag, "📓" if shadow else "🔴", sym, s["entry"],
                            (s["entry"] - s["price"]) / s["price"] * 100, s["sl"],
                            s["stop_pct"], s["tp"], s["block"], s["atr_pct"], b["count"])

                if shadow:
                    continue
                rec = TradingRecommendation(
                    symbol=sym, action="SELL", direction=SignalDirection.SHORT,
                    overall_strength=65, confidence=0.6, risk_level="MEDIUM",
                    signals_count=1, supporting_signals=[], conflicting_signals=[],
                    # 29.09: контекст собирает ШИНА (было volume_24h=0.0 — оборот терялся)
                    market_context=build_market_context(bot, sym, current_price=s["price"]),
                    entry_price=s["entry"], stop_loss=s["sl"], take_profit=s["tp"],
                    sl_source=f"{inst.src}:leg_origin", tp_source=f"{inst.src}:waveC")
                res = await bot.trade_router.submit(rec, source=inst.src, extra_features={
                    # 🔴 28.09 ИМЕНЕМ ИНСТАНСА, не константой SRC: под `trade_mode` реестр ищет
                    # пороги, а под `signal_type` считается вся статистика источника. С жёстким
                    # SRC сделки 4h подписывались именем 1h — инстансы было не разделить, и при
                    # расхождении порогов 4h молча получил бы чужие ([[bug_gate_lives_in_two_places]]).
                    "signal_type_override": inst.src, "trade_mode": inst.src,
                    "cw_tf": inst.tf,
                    "cw_choch_ts": s["choch_ts"], "cw_age": s["age"],
                    "cw_leg_pct": round(s["leg_len"] / s["entry"] * 100, 2),
                    "cw_stop_pct": round(s["stop_pct"], 2),
                    "cw_block": round(s["block"], 1), "cw_shield": round(s["shield"], 1),
                    "cw_atr_pct": round(s["atr_pct"], 2),
                    "cw_under_s1w": int(b["under_s1w"]),
                    "cw_good_hour": int(b.get("good_hour", False)),
                    "cw_boosters": b["count"]})

                # 🔴 21.08 OPEN → PENDING_ENTRY. Вход ЛИМИТНЫЙ: до фила позиции нет, а
                # register_trade пишет сразу OPEN — и TSL начинает трейлить НЕСУЩЕСТВУЮЩУЮ
                # позицию. Поймано живьём на BITLIGHT #58333: стоп ушёл 0.19249 → 0.15828
                # (ниже входа 0.173964) при actual_entry=None. Тот же дефект чинили в
                # impulse_fib; сюда он не был перенесён и жил в бою.
                try:
                    _oe = getattr(bot, "order_executor", None)
                    if _oe is not None and hasattr(_oe, "invalidate_balance"):
                        _oe.invalidate_balance()
                except Exception:                              # noqa: BLE001
                    pass
                try:
                    tid = getattr(res, "trade_id", None)
                    oid = getattr(res, "exchange_order_id", None)
                    if tid and not oid:
                        # ордер на биржу не ушёл → позиции нет → и записи быть не должно
                        with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as _c:
                            _c.execute("UPDATE simulated_trades SET status='CANCELLED' "
                                       "WHERE id=? AND status='OPEN' AND (exchange_order_id "
                                       "IS NULL OR exchange_order_id='') AND "
                                       "(actual_entry_price IS NULL OR actual_entry_price<=0)",
                                       (int(tid),))
                            _c.commit()
                        logger.warning("[%s] #%s ордер на биржу не ушёл → CANCELLED", inst.tag, tid)
                    elif tid:
                        from bot.loops.radar_armed_loop import _mark_pending
                        if _mark_pending(bot.trade_simulator.db_path, int(tid)):
                            logger.info("[%s] #%s → PENDING_ENTRY (лимитка ждёт фила)", inst.tag, tid)
                        # окно гонки: TSL мог зацепить строку до перевода в PENDING
                        with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as _c:
                            _r = _c.execute(
                                "UPDATE simulated_trades SET stop_loss=original_sl, "
                                "tsl_activated=0 WHERE id=? AND original_sl IS NOT NULL "
                                "AND original_sl>0 AND stop_loss<>original_sl "
                                "AND (actual_entry_price IS NULL OR actual_entry_price<=0)",
                                (int(tid),))
                            _c.commit()
                            if _r.rowcount:
                                logger.warning("[%s] #%s стоп восстановлен из original_sl", inst.tag, tid)
                except Exception as _mp:                       # noqa: BLE001
                    logger.warning("[%s] mark_pending: %s", inst.tag, _mp)

            conn.commit()
            stats = dict(conn.execute(
                f"SELECT status,COUNT(*) FROM {tbl} GROUP BY status").fetchall())
            logger.info("[%s] скан %d пар · новых %d · журнал: %s",
                        inst.tag, len(syms), found, stats or "пусто")
        except asyncio.CancelledError:
            raise
        except Exception as e:                                 # noqa: BLE001
            logger.error("[%s] ошибка цикла: %s", inst.tag, e, exc_info=True)
        finally:
            # 🔴 21.08: соединение закрывается ВСЕГДА. Без finally исключение внутри прохода
            # оставляло его открытым с незавершённой транзакцией — а это само порождало
            # `database is locked` на следующем проходе, то есть отказ самоусиливался.
            try:
                if conn is not None:
                    conn.close()
            except Exception:                                  # noqa: BLE001
                pass
            conn = None
