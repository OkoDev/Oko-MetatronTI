# -*- coding: utf-8 -*-
"""
ОБЩИЙ РАННЕР impulse_fib — один код на все ТФ-инстансы (фаза 3 реестра, 22.08.2026).

Что было: `impulse_fib_loop` (1h) и `impulse_fib_15m_loop` были почти точными клонами.
Замер diff'ом после нормализации имён: РАЗЛИЧИЙ СЕМЬ, и все — параметры
(ТФ · масштаб окон · имя источника · таблица журнала · путь к дрейф-гейту · тег в логе).
Остальные ~420 строк совпадали дословно.

Чем это опасно было: 22.08 в 15m-инстансе нашлось, что окна `WAIT_BARS`/`HOLD_BARS`
заданы В БАРАХ под 1h — и клон жил вчетверо короче своего замера
([[twins_15m_stabilized_by_measure]]). Правка в одном файле не доезжает до другого:
любой фикс исполнения приходится вносить дважды, и однажды его внесут один раз.

Как теперь: инстанс — это `Instance(...)`, а поведение живёт ЗДЕСЬ в одном экземпляре.
Добавить ТФ = добавить строку описания, а не копию файла.

    INSTANCE = Instance(src="impulse_fib", tf="1h", tf_mult=1,
                        table="impulse_shadow", tag="IMPULSE")
    impulse_fib_loop = make_loop(INSTANCE)

🔴 МАСШТАБ ОКОН (`tf_mult`) — не украшение, а условие соответствия замеру. Механика
мерилась на КАЛЕНДАРНОЙ длительности: 12 ч ожидания фила и 96 ч удержания. На 1h это
12/96 баров, на 15m — 48/384. Меняя ТФ, множитель обязан меняться вместе с ним.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass

import pandas as pd

from core.context.market_regime import turnover_map as _turnover_map
from core.smc.impulse_fib import (HOLD_BARS, WAIT_BARS, find_setup, gates, is_junk,
                                  score, size_mult)
from core.trading.source_registry import slots as _slots

logger = logging.getLogger(__name__)

POLL_SEC = 900


@dataclass(frozen=True)
class Instance:
    """Описание ТФ-инстанса механики. Всё, чем инстансы отличаются друг от друга."""
    src: str                 # имя источника: оно же trade_mode, signal_type_override, ключ политики
    tf: str                  # таймфрейм свечей
    tf_mult: int             # во сколько раз бары мельче базового 1h (15m → 4)
    table: str               # таблица исследовательского журнала
    tag: str                 # тег в логе

    @property
    def wait_bars(self) -> int:
        """Окно ожидания фила В БАРАХ этого ТФ (календарно всегда 12 часов)."""
        return WAIT_BARS * self.tf_mult

    @property
    def hold_bars(self) -> int:
        """Горизонт удержания В БАРАХ этого ТФ (календарно всегда 96 часов)."""
        return HOLD_BARS * self.tf_mult

    @property
    def cfg_key(self) -> str:
        return f"trading.{self.src}"


def table_sql(inst: Instance) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {inst.table} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT DEFAULT (datetime('now')),
    symbol       TEXT NOT NULL,
    impulse_ts   TEXT NOT NULL,          -- бар конца импульса (от него считается зона входа)
    origin_ts    TEXT NOT NULL,          -- бар НАЧАЛА импульса: ключ дедупа с symbol
    side         TEXT NOT NULL,          -- long|short
    entry        REAL NOT NULL,          -- заявленная лимитная цена
    stop_loss    REAL NOT NULL,
    take_profit  REAL NOT NULL,
    stop_pct     REAL,
    price_at_signal REAL,
    vratio       REAL,                   -- объём импульса к средней (коридор 1.0-1.5)
    regime       REAL,                   -- ATR/SMA100
    with_trend   INTEGER,
    atr_pct      REAL,
    score        REAL,
    size_mult    REAL,
    status       TEXT DEFAULT 'WAITING', -- WAITING|FILLED|TP|SL|EXPIRED|INVALID
    filled_at    TEXT,
    resolved_at  TEXT,
    result_pct   REAL,                   -- итог в % от входа, знак учитывает сторону
    bars_to_fill INTEGER,
    -- 🔑 дедуп по НАЧАЛУ импульса: детектор видит один импульс на нескольких соседних
    -- барах, побеждает первый увиденный — ровно как в замере (см. find_impulses).
    UNIQUE(symbol, origin_ts)
)
"""


def _conn(bot, inst: Instance):
    c = sqlite3.connect(bot.trade_simulator.db_path, timeout=10)
    c.execute(table_sql(inst))
    return c


def _drift_gate(inst: Instance, side: str) -> tuple[bool, str]:
    """Дрейф-гейт. Любой сбой → пропускаем сигнал (fail-open), стратегия не умирает молча."""
    try:
        from core.context.universe_drift import gate
        return gate(side, cfg_path=f"{inst.cfg_key}.drift_gate")
    except Exception as e:                                   # noqa: BLE001
        return True, f"gate:ИМПОРТ УПАЛ {type(e).__name__} → пропускаю"


def _eqh_alt_entry(bot, inst: Instance, df, side: str) -> tuple[bool, str]:
    """
    АЛЬТЕРНАТИВНЫЙ ВХОД: цена у скопления стопов (EQH сверху / EQL снизу).

    Замер 29.08 на 6730 сделках: `short` в пределах 0.25 ATR от уровня равных хаёв даёт
    PF 5.06 против 2.40 у чистого дрейф-гейта, безтоп10% +525, охват 64%, зеркало на
    long — 0.75 (идёт прямо в стопы). P(перестановка) = 0.000, плато порога проверено
    (0.1→1.5 ATR монотонно), временной OOS train ×1.41 → test ×2.18
    ([[eqh_liquidity_short_works_in_2026]]).

    🔑 Почему это АЛЬТЕРНАТИВА, а не добавка к дрейф-гейту: по годам они конкуренты,
    а не партнёры. В 2026 EQH даёт 1.93 при хрупкости +5, дрейф-гейт — 1.06 при −200,
    а их ПЕРЕСЕЧЕНИЕ (1.19) хуже чистого EQH. В 2024 наоборот сильнее гейт. Поэтому
    сигнал проходит, если выполнено ЛЮБОЕ из двух условий, и какое именно — пишется в лог.

    🔴 FAIL-CLOSED, в отличие от `_drift_gate`. Дрейф-гейт при сбое ПРОПУСКАЕТ (иначе
    стратегия умирает молча). Здесь наоборот: функция РАСШИРЯЕТ поток, и её поломка
    открыла бы шлюз. Любая неясность → «не пропускаю».
    """
    try:
        cfg = bot.config.get(f"{inst.cfg_key}.eqh_entry", {}) or {}
        if not bool(cfg.get("enabled", False)):
            return False, "eqh:выключен"
        if side not in (cfg.get("sides") or ["short"]):
            return False, f"eqh:сторона {side} не разрешена"

        from core.smc.impulse_fib import _atr
        from core.smc.smc_engine import detect_equal_levels

        tol = float(cfg.get("tolerance_atr", 0.25))
        # уровень должен быть ПОДТВЕРЖДЁН: `detect_equal_levels(eq_len)` помечает пивот
        # только через eq_len баров, поэтому хвост ряда ещё не окончателен
        # ([[detector_lag_is_a_parameter_not_statistics]]).
        lag = int(cfg.get("confirm_bars", 3))
        atr = float(_atr(df).iloc[-1])
        if not atr or atr <= 0:
            return False, "eqh:ATR недоступен"
        price = float(df["close"].iloc[-1])
        tag = "EQH" if side == "short" else "EQL"
        cutoff = df.index[-lag] if len(df) > lag else df.index[-1]

        best = None
        for e in detect_equal_levels(df):
            if len(e) < 5 or str(e[4]).upper() != tag:
                continue
            if pd.Timestamp(e[2]) > cutoff:        # уровень ещё не подтверждён
                continue
            lvl = (float(e[1]) + float(e[3])) / 2.0
            d = abs(price - lvl) / atr
            if best is None or d < best[0]:
                best = (d, lvl)
        if best is None:
            return False, f"eqh:{tag} не найден"
        if best[0] <= tol:
            return True, f"eqh:{tag} на {best[0]:.2f} ATR (порог {tol})"
        return False, f"eqh:{tag} далеко {best[0]:.2f} ATR"
    except Exception as e:                                   # noqa: BLE001
        return False, f"eqh:СБОЙ {type(e).__name__} → не пропускаю"


def _ud_feats() -> dict:
    """Режимный контекст (наблюдательный). Любой сбой → пустой словарь, луп не страдает."""
    try:
        from core.context.universe_drift import features
        return features()
    except Exception:                                        # noqa: BLE001
        return {"ud_ok": 0}


async def _fetch(bot, inst: Instance, symbol: str, limit: int):
    """OHLCV → DatetimeIndex UTC. D-042: data_collector отдаёт колонку 'time' (мс)."""
    try:
        df = await bot.data_collector.get_ohlcv(symbol, timeframe=inst.tf, limit=limit)
    except Exception:                                        # noqa: BLE001
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


def make_resolve(inst: Instance):
    """Резолвер журнала для инстанса (окна берутся из `inst`, а не из модуля механики)."""

    def _resolve(conn, symbol: str, df: pd.DataFrame) -> None:
        """Догоняет статусы незакрытых записей символа по закрытым барам.

        🔴 ОКНО ФИЛА = inst.wait_bars, как в замере. Поиск по всей истории завышал число
        входов — бот заходил бы на протухших сетапах, которых в бэктесте не было
        (поймано регрессией на `choch_wavec`: 1086 из 1807 сетапов расходились).
        Порядок проверок повторяет замер: стоп ДО входа = сетап умер, а не убыток.
        """
        wait_bars, hold_bars = inst.wait_bars, inst.hold_bars
        rows = conn.execute(
            "SELECT id,impulse_ts,side,entry,stop_loss,take_profit,status,filled_at "
            f"FROM {inst.table} WHERE symbol=? AND status IN ('WAITING','FILLED')",
            (symbol,)).fetchall()
        if not rows:
            return
        d = df.iloc[:-1]                                     # только закрытые бары
        for rid, imp_ts, side, entry, sl, tp, status, filled_at in rows:
            try:
                t0 = pd.Timestamp(filled_at if status == "FILLED" else imp_ts, tz="UTC")
            except Exception:                                # noqa: BLE001
                continue
            w = d[d.index > t0]
            if w.empty:
                continue
            hi, lo, idx = w.high.values, w.low.values, w.index
            up = side == "long"

            if status == "WAITING":
                win = min(len(hi), wait_bars)
                if up:
                    f_entry = next((k for k in range(win) if lo[k] <= entry), None)
                    f_stop = next((k for k in range(win) if lo[k] <= sl), None)
                else:
                    f_entry = next((k for k in range(win) if hi[k] >= entry), None)
                    f_stop = next((k for k in range(win) if hi[k] >= sl), None)
                if f_stop is not None and (f_entry is None or f_stop < f_entry):
                    conn.execute(f"UPDATE {inst.table} SET status='INVALID',"
                                 "resolved_at=? WHERE id=?", (str(idx[f_stop]), rid))
                    continue
                if f_entry is None:
                    if len(hi) >= wait_bars:                 # окно отката исчерпано
                        conn.execute(f"UPDATE {inst.table} SET status='EXPIRED',"
                                     "resolved_at=? WHERE id=?", (str(idx[win - 1]), rid))
                    continue
                conn.execute(f"UPDATE {inst.table} SET status='FILLED',filled_at=?,"
                             "bars_to_fill=? WHERE id=?",
                             (str(idx[f_entry]), f_entry + 1, rid))
                hi, lo, idx = hi[f_entry + 1:], lo[f_entry + 1:], idx[f_entry + 1:]
                if len(hi) == 0:
                    continue

            # Выход ФИКСИРОВАННЫЙ: БУ и трейлинг измерены и забирают до 25% дохода.
            hold = min(len(hi), hold_bars)
            if up:
                h_tp = next((k for k in range(hold) if hi[k] >= tp), None)
                h_sl = next((k for k in range(hold) if lo[k] <= sl), None)
            else:
                h_tp = next((k for k in range(hold) if lo[k] <= tp), None)
                h_sl = next((k for k in range(hold) if hi[k] >= sl), None)
            sgn = 1.0 if up else -1.0
            if h_tp is None and h_sl is None:
                if len(hi) >= hold_bars:                     # вышли по времени — по close
                    out = float(w.close.values[len(w) - len(hi) + hold - 1])
                    conn.execute(f"UPDATE {inst.table} SET status='EXPIRED',resolved_at=?,"
                                 "result_pct=? WHERE id=?",
                                 (str(idx[hold - 1]), sgn * (out - entry) / entry * 100, rid))
                continue
            if h_sl is not None and (h_tp is None or h_sl <= h_tp):
                conn.execute(f"UPDATE {inst.table} SET status='SL',resolved_at=?,result_pct=?"
                             " WHERE id=?", (str(idx[h_sl]), sgn * (sl - entry) / entry * 100, rid))
            else:
                conn.execute(f"UPDATE {inst.table} SET status='TP',resolved_at=?,result_pct=?"
                             " WHERE id=?", (str(idx[h_tp]), sgn * (tp - entry) / entry * 100, rid))

    return _resolve


def make_loop(inst: Instance):
    """Собирает корутину лупа для инстанса. Поведение — одно на все ТФ."""
    _resolve = make_resolve(inst)
    TAG = inst.tag
    SRC = inst.src

    async def _loop(bot):
        cfg = (bot.config.get(inst.cfg_key, {}) or {})
        if not cfg.get("enabled", False):
            logger.info("[%s] выключен (%s.enabled=false)", TAG, inst.cfg_key)
            return

        shadow = bool(cfg.get("shadow", True))
        top_n = int(cfg.get("universe_top", 250))
        min_stop = float(cfg.get("min_stop_pct", 0.0))
        max_stop = float(cfg.get("max_stop_pct", 30.0))
        require_gates = bool(cfg.get("require_gates", True))
        cap = int(cfg.get("max_open", 8))
        cap_pending = int(cfg.get("max_pending", cap * 2))
        bars = int(cfg.get("bars", 1000))
        sides = set(cfg.get("sides", ["long", "short"]))
        logger.info("[%s] старт · %s · ТФ %s · вселенная top%d · стоп %.1f-%.1f%% · гейты %s · "
                    "стороны %s · позиций %d · заявок %d · до %d на монету/сторону · окна %d/%d баров",
                    TAG, "SHADOW (на биржу НЕ шлём)" if shadow else "🔴 ЖИВОЙ", inst.tf,
                    top_n, min_stop, max_stop, "ДА" if require_gates else "нет",
                    "/".join(sorted(sides)), cap, cap_pending,
                    int(cfg.get("max_per_symbol", 1)), inst.wait_bars, inst.hold_bars)

        from core.signals.signal_models import (MarketContext, SignalDirection,
                                                TradingRecommendation)

        while True:
            conn = None
            try:
                await asyncio.sleep(POLL_SEC)
                pair_ctx = getattr(bot, "pair_context", None)
                if pair_ctx is None:
                    continue

                turn = _turnover_map()
                syms = [s for s in pair_ctx.all_symbols() if not is_junk(s)]
                syms.sort(key=lambda s: -turn.get(s.split("/")[0], 0.0))
                syms = syms[:top_n]

                conn = _conn(bot, inst)
                # 🔴 20.08: КЭП СЧИТАЕТСЯ ПО РЕАЛЬНЫМ СДЕЛКАМ, а не по журналу. Журнал —
                # исследовательский: в нём остаются и сетапы, которых на бирже нет (отбил
                # гейт), и они блокировали слоты. Ровно это и случилось в первый день: 8
                # записей WAITING держали кэп, а сделок на бирже было НОЛЬ.
                # В shadow-режиме биржи нет вовсе → там кэп по журналу, как и было.
                # 🔴 22.08 ДВА ЛИМИТА: позиции = рыночный риск, заявки = резерв маржи.
                # Ожидающая лимитка не в рынке — слот РИСКА занимать не должна.
                # Подробности: core/trading/source_registry.slots
                if shadow:
                    n_open = conn.execute(
                        f"SELECT COUNT(*) FROM {inst.table} WHERE status IN ('WAITING','FILLED')"
                    ).fetchone()[0]
                    n_pend = 0
                else:
                    st = _slots(conn, SRC, max_open=cap, max_pending=cap_pending)
                    n_open, n_pend = st["open"], st["pending"]
                    if not st["can_place"]:
                        logger.info("[%s] новых заявок не будет: %s", TAG, st["why"])
                found = 0
                # 🔴 25.08 ВОРОНКА (правило Егора: «self-test'ы не втихую»). Строка
                # «скан 250 пар · новых 0» не объясняла себя — чтобы понять, кто убил
                # сетапы, уходили часы и офлайн-замеры. Теперь каждый отсев считается
                # ПО ИМЕНИ и печатается в той же строке. Молчаливых continue не осталось.
                fn: dict[str, int] = {}
                def _drop(reason: str) -> None:
                    fn[reason] = fn.get(reason, 0) + 1

                for sym in syms:
                    df = await _fetch(bot, inst, sym, bars)
                    await asyncio.sleep(0.05)
                    if df is None:
                        _drop("нет данных")
                        continue
                    _resolve(conn, sym, df)
                    if shadow:
                        if n_open + found >= cap:
                            _drop("кэп журнала")
                            continue
                    elif n_open >= cap or n_pend + found >= cap_pending:
                        _drop("кэп позиций" if n_open >= cap else "кэп заявок")
                        continue                   # рынок полон ИЛИ маржа исчерпана

                    # wait_bars задаёт, насколько СВЕЖИМ должен быть импульс. Дефолт модуля
                    # калиброван для 1h; на младших ТФ его обязан масштабировать инстанс.
                    s = find_setup(df, symbol=sym, wait_bars=inst.wait_bars)
                    if not s:
                        _drop("импульса нет")
                        continue
                    if "reason" in s:
                        _drop(f"детектор: {s['reason']}")
                        continue
                    if not s["live"]:
                        _drop("сетап не live (импульс устарел)")
                        continue
                    if s["side"] not in sides:
                        _drop(f"сторона {s['side']} выключена")
                        continue
                    # 🔴 21.08 ДРЕЙФ-ГЕЙТ (short): фейдим отскок ВНУТРИ падающего рынка.
                    # Слепой тест ×2: OOS PF 5.54 против базы 1.22. Отсекает ~93% времени —
                    # это конструкция. Отказ ЛОГИРУЕТСЯ (закон: молчаливых отказов нет).
                    # При любой неясности gate() пропускает (fail-open) — см. universe_drift.
                    _pass_gate, _why = _drift_gate(inst, s["side"])
                    if not _pass_gate:
                        # 🔴 29.08 ВТОРАЯ ДВЕРЬ: цена у скопления стопов (EQH). По замеру
                        # эта ось и дрейф-гейт — КОНКУРЕНТЫ, а не партнёры: в 2026 EQH
                        # даёт 1.93 против 1.06 у гейта, а их пересечение хуже обоих.
                        # Поэтому вход открыт при выполнении ЛЮБОГО условия, и в лог
                        # пишется, какая именно дверь сработала — иначе через месяц
                        # будет не разобрать, что принесло сделки.
                        _pass_alt, _alt_why = _eqh_alt_entry(bot, inst, df, s["side"])
                        if not _pass_alt:
                            _drop("дрейф-гейт")
                            logger.info("[%s] %s %s ОТКЛОНЁН: %s · %s",
                                        TAG, sym, s["side"].upper(), _why, _alt_why)
                            continue
                        logger.info("[%s] %s %s ПРОПУЩЕН ПО EQH (гейт был против): %s",
                                    TAG, sym, s["side"].upper(), _alt_why)
                        _drop("вход по EQH (не отсев)")
                    if not (min_stop <= s["stop_pct"] <= max_stop):
                        _drop("стоп уже зоны" if s["stop_pct"] < min_stop else "стоп шире зоны")
                        continue
                    g = gates(s)
                    if require_gates and not g["passed"]:
                        # Поимённо: `gates()` возвращает три условия OOS-сборки, и слитое
                        # «гейты механики» не говорит, какое именно душит. Считаем каждое.
                        for _gk in ("vol_band", "with_trend", "high_regime"):
                            if not g.get(_gk):
                                _drop(f"гейт {_gk}")
                        continue
                    sc = score(s)
                    mult = size_mult(sc)
                    dup = conn.execute(f"SELECT 1 FROM {inst.table} WHERE symbol=? AND origin_ts=?",
                                       (sym, s["origin_ts"])).fetchone()
                    if dup:
                        _drop("дубль origin_ts")
                        continue
                    # 🔴 25.08 ЛИМИТ НА СИМВОЛ СТАЛ НАСТРАИВАЕМЫМ (решение Егора «открой
                    # возможность нескольких сделок на монету»). Было жёстко «один символ —
                    # одна позиция»: детектор видит один ход с соседних баров начала
                    # (SOL: origin 20:00, 21:00, 22:00) — формально разные импульсы, а зона
                    # входа та же (82.9714 против 82.9409). Для РЕАЛЬНЫХ денег это двойной
                    # риск при 100% корреляции; на ПЕСОЧНИЦЕ это дополнительные наблюдения.
                    # Счёт ведём ПО СТОРОНЕ: long и short на одной монете — независимые
                    # позиции (hedge), а не дубль. max_per_symbol=0 снимает лимит совсем.
                    _max_sym = int(cfg.get("max_per_symbol", 1))
                    if not shadow and _max_sym > 0:
                        _busy = conn.execute(
                            "SELECT COUNT(*) FROM simulated_trades WHERE symbol=? AND signal_type=? "
                            "AND direction=? AND status IN ('OPEN','PENDING_ENTRY')",
                            (sym, SRC, "LONG" if s["side"] == "long" else "SHORT")).fetchone()[0]
                        if _busy >= _max_sym:
                            _drop("лимит на монету")
                            continue

                    conn.execute(
                        f"INSERT INTO {inst.table} (symbol,impulse_ts,origin_ts,side,entry,"
                        "stop_loss,take_profit,stop_pct,price_at_signal,vratio,regime,with_trend,"
                        "atr_pct,score,size_mult) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, s["impulse_ts"], s["origin_ts"], s["side"], s["entry"], s["sl"],
                         s["tp"], s["stop_pct"], s["price"], s["vratio"], s["regime"],
                         int(s["with_trend"]), s["atr_pct"], sc, mult))
                    conn.commit()
                    found += 1
                    # 🔑 `скор ×N` НЕ применяется к размеру — ступени не подтвердились перемером
                    # (см. score()), значение только пишется в журнал. В логе помечено «журн.»,
                    # чтобы строка не обещала сайзинга, которого нет.
                    logger.info("[%s] %s %s %s лимит %.6g (%.2f%% от цены) · стоп %.6g "
                                "(%.2f%%) · цель %.6g (+%.1f%%) · RR %.2f · объём %.2f · "
                                "режим %.2f · скор %.2f (журн. ×%.1f, размер НЕ меняет)",
                                TAG, "📓" if shadow else "🔴", sym,
                                s["side"].upper(), s["entry"],
                                (s["entry"] - s["price"]) / s["price"] * 100, s["sl"],
                                s["stop_pct"], s["tp"],
                                abs(s["tp"] - s["entry"]) / s["entry"] * 100,
                                s["rr"], s["vratio"], s["regime"], sc, mult)

                    if shadow:
                        continue
                    is_long = s["side"] == "long"
                    rec = TradingRecommendation(
                        symbol=sym, action="BUY" if is_long else "SELL",
                        direction=SignalDirection.LONG if is_long else SignalDirection.SHORT,
                        overall_strength=65, confidence=0.6, risk_level="MEDIUM",
                        signals_count=1, supporting_signals=[], conflicting_signals=[],
                        market_context=MarketContext(symbol=sym, current_price=s["price"],
                                                     volume_24h=0.0, volume_change_24h=0.0,
                                                     price_change_24h=0.0),
                        entry_price=s["entry"], stop_loss=s["sl"], take_profit=s["tp"],
                        sl_source=f"{SRC}:atr25", tp_source=f"{SRC}:fib_side")
                    res = await bot.trade_router.submit(rec, source=SRC, extra_features={
                        "signal_type_override": SRC, "trade_mode": SRC,
                        "if_impulse_ts": s["impulse_ts"], "if_age": s["age"],
                        "if_amp_pct": round(s["amp"] / s["entry"] * 100, 2),
                        "if_stop_pct": round(s["stop_pct"], 2),
                        "if_vratio": round(s["vratio"], 2),
                        "if_regime": round(s["regime"], 2),
                        "if_with_trend": int(s["with_trend"]),
                        "if_atr_pct": round(s["atr_pct"], 2),
                        "if_score": round(sc, 2), "if_size_mult": mult,
                        # 21.08 SHADOW: режимный контекст пишем НАБЛЮДАТЕЛЬНО, решения не меняем.
                        # Слепой тест (дважды): short при drift30 ≥ +10% даёт OOS PF 5.54
                        # против базы 1.22. Копим боевые сделки, чтобы сверить с замером.
                        **_ud_feats()})

                    # 🔴 20.08 OPEN → PENDING_ENTRY. Вход ЛИМИТНЫЙ: до фила позиции нет, а
                    # register_trade пишет сразу OPEN. Первый же боевой скан показал цену этой
                    # ошибки: TSL увидел «прибыль» (цена 87.5 против лимита 83.08, которого
                    # никто не касался) и подтянул стоп SOL с 81.40 на 86.67 — ВЫШЕ входа.
                    # PENDING-строка невидима для TSL/BE/close-by-price; fill и TTL ведёт
                    # `_check_pending` в radar_armed_loop (там же account-aware cancel и
                    # обработка гонки fill→exit — переиспользуем, а не дублируем).
                    # ⚠️ Зависимость: при trading.radar_armed.enabled=false лайфцикл встанет.
                    try:
                        # 🔴 20.08: сбрасываем кеш свободной маржи — иначе вся пачка лимиток
                        # считается от ОДНОГО снимка баланса и риск по сделкам расходится
                        # (замер: первая в пачке $8.69, восьмая $5.03 при одинаковых 2%).
                        try:
                            _oe = getattr(bot, "order_executor", None)
                            if _oe is not None and hasattr(_oe, "invalidate_balance"):
                                _oe.invalidate_balance()
                        except Exception:                      # noqa: BLE001
                            pass
                        tid = getattr(res, "trade_id", None)
                        oid = getattr(res, "exchange_order_id", None)
                        if tid and not oid:
                            # 🔴 Ордер на биржу НЕ ушёл (гейт/ошибка), а запись уже OPEN —
                            # такую строку подхватывает TSL и портит ей стоп (ARB #58349:
                            # стоп ушёл выше входа у сделки, которой на бирже нет).
                            # Позиции нет → и записи быть не должно.
                            with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as _c:
                                _c.execute("UPDATE simulated_trades SET status='CANCELLED' "
                                           "WHERE id=? AND status='OPEN' AND (exchange_order_id "
                                           "IS NULL OR exchange_order_id='') AND "
                                           "(actual_entry_price IS NULL OR actual_entry_price<=0)",
                                           (int(tid),))
                                _c.commit()
                            logger.warning("[%s] #%s ордер на биржу не ушёл → CANCELLED", TAG, tid)
                        elif tid:
                            from bot.loops.radar_armed_loop import _mark_pending
                            if _mark_pending(bot.trade_simulator.db_path, int(tid)):
                                logger.info("[%s] #%s → PENDING_ENTRY (лимитка ждёт фила)", TAG, tid)
                            # 🔴 ОКНО ГОНКИ: между INSERT (status=OPEN) и mark_pending проходит
                            # 10-20 сек, и TSL-цикл успевает зацепить строку. XRP #58346 поймали
                            # живьём: tsl_activated=1, стоп 1.0723 → 1.1541, ВЫШЕ входа 1.0931.
                            # Пока фила нет, стоп обязан быть исходным — восстанавливаем из
                            # original_sl. Условие actual_entry гарантирует, что реальную
                            # позицию (где трейлинг законен) мы не трогаем.
                            with sqlite3.connect(bot.trade_simulator.db_path, timeout=10) as _c:
                                _r = _c.execute(
                                    "UPDATE simulated_trades SET stop_loss=original_sl, "
                                    "tsl_activated=0 WHERE id=? AND original_sl IS NOT NULL "
                                    "AND original_sl>0 AND stop_loss<>original_sl "
                                    "AND (actual_entry_price IS NULL OR actual_entry_price<=0)",
                                    (int(tid),))
                                _c.commit()
                                if _r.rowcount:
                                    logger.warning("[%s] #%s стоп восстановлен из original_sl "
                                                   "(TSL зацепил строку до PENDING)", TAG, tid)
                    except Exception as _mp:                   # noqa: BLE001
                        logger.warning("[%s] mark_pending: %s", TAG, _mp)

                conn.commit()
                stats = dict(conn.execute(
                    f"SELECT status,COUNT(*) FROM {inst.table} GROUP BY status").fetchall())
                # Воронка — от самого частого отсева к редкому. Ответ на «почему новых 0»
                # обязан читаться из ОДНОЙ строки лога, а не выясняться замерами (правило Егора).
                _funnel = " · ".join(f"{k}: {v}" for k, v in
                                     sorted(fn.items(), key=lambda kv: -kv[1]))
                logger.info("[%s] скан %d пар · новых %d · журнал: %s\n"
                            "         └─ воронка: %s",
                            TAG, len(syms), found, stats or "пусто", _funnel or "всё прошло")
            except asyncio.CancelledError:
                raise
            except Exception as e:                             # noqa: BLE001
                logger.error("[%s] ошибка цикла: %s", TAG, e, exc_info=True)
            finally:
                # 🔴 20.08: соединение закрывается ВСЕГДА. Без finally любое исключение внутри
                # прохода оставляло его открытым с незавершённой транзакцией — а это само же
                # порождало `database is locked` на следующем проходе, то есть отказ
                # самоусиливался. Поймано живьём: проход умер после 7 символов из 250.
                try:
                    if conn is not None:
                        conn.close()
                except Exception:                              # noqa: BLE001
                    pass
                conn = None

    return _loop
