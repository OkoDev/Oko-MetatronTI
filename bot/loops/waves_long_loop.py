# -*- coding: utf-8 -*-
"""WAVES_LONG LOOP (Егор 17.09: «давай уже на vst все в бой! 2% на сделку, без ограничения на слоты…
в бой идут все кандидаты нами найденные, с индивидуальной пометкой каждый»).

Мост между тенью и исполнением. Разметку волн считает `scripts/wave5_shadow.py` (отдельный процесс,
скан 588 монет раз в 4 часа), роутер живёт в боте — поэтому тень пишет сигналы в очередь
`data/wave5_shadow/exec_queue.jsonl`, а этот цикл их исполняет через `trade_router.submit`.

Варианты входа идут ОДНИМ источником `waves_long` с пометкой в `wv_variant`:
  cross · line24          — боевые триггеры ядра (кросс WT / пробой линии 2-4 на 15m)
  choch_swing_15m         — находка замера 16.09: Δ +2.51 против +1.87 у боевого, WR 49.5% против 33%
  choch_int_15m           — то же на internal-структуре
  reentry_3m              — повторный вход после выбитого стопа (слом 3m)
Признаки отбора (`wv_core_full`, `wv_imp_pct`, `wv_risk_pct`, `wv_mass_day`…) пишутся в сделку,
чтобы потом резать результат по ним, а не отбирать заранее.

ТОЛЬКО ЛОНГ: шорт-сторона втрое слабее, а разворотный шорт после лонга проиграл случайному входу
той же геометрии 2.5 п.п. (оба контроля посчитаны 16.09).
Gated: trading.waves_long.enabled.
🔴 21.09 (Егор: «молчаливый пропуск в лонгах починить! повторные входы мы разрешали»): дедуп был по `uid`
(символ|ключ сетапа|вариант) НАВСЕГДА — повторный вход тени по тому же импульсу после выбитого стопа (STAR line24
19.09 и 21.09) отбрасывался до логирования. Теперь ключ = uid + время события (`_event_key`): повторные входы
исполняются (при одной открытой позиции на монету), а всё, что пропущено, пишется в лог.
"""
import asyncio
import calendar
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

POLL_SEC = 30
ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "data" / "wave5_shadow" / "exec_queue.jsonl"
DONE = ROOT / "data" / "wave5_shadow" / "exec_done.json"
MAX_AGE_MIN = 45          # сигнал старше — не исполняем: цена ушла, вход уже не тот


def _load_done() -> set:
    try:
        return set(json.loads(DONE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_done(done: set) -> None:
    try:
        DONE.write_text(json.dumps(sorted(done)[-5000:], ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("[WAVES_LONG] не сохранил список обработанных: %s", e)


def _event_key(r: dict) -> str:
    """Ключ дедупа = uid + время СОБЫТИЯ (слом / кросс / минута записи для reentry_3m). Один и тот же
    импульс с новым входом — новый ключ, а не «уже обработан»."""
    for k in ("wv_choch_time", "wv_entry_time"):
        if r.get(k):
            return f"{r['uid']}|{str(r[k])[:16]}"
    return f"{r['uid']}|{str(r.get('ts', ''))[:16]}"


def _read_all() -> list:
    if not QUEUE.exists():
        return []
    out = []
    try:
        for line in QUEUE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("uid"):
                out.append(r)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WAVES_LONG] очередь не прочитана: %s", e)
    return out


def _read_new(done: set) -> list:
    return [r for r in _read_all() if _event_key(r) not in done]


def _canon(sym: str) -> str:
    """`GUN/USDT` → `GUN/USDT:USDT` (формат ccxt-swap, в котором живут роутер аккаунтов, БД и детектор сирот)."""
    s = sym.strip()
    if not s:
        return s
    base = s.split("/")[0].split(":")[0].split("-")[0]
    return f"{base}/USDT:USDT"


def _signal_age_min(r: dict) -> float:
    """Возраст СОБЫТИЯ, а не записи в очередь: тень пишет сигнал при скане, а слом/кросс мог быть часами
    раньше (STAR 17.09: сигнал 0.0413, вход на бирже 0.0535 — +30%). Берём время события, если оно есть."""
    for k in ("wv_choch_time", "wv_entry_time"):
        v = r.get(k)
        if v:
            try:
                return (time.time() - calendar.timegm(time.strptime(str(v)[:16], "%Y-%m-%d %H:%M"))) / 60
            except Exception:
                pass
    return (time.time() - calendar.timegm(time.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"))) / 60


def _stop_rel(entry, stop, imp_pct):
    """Ширина стопа в долях импульса: |вход−стоп|/вход, делённое на размер импульса в %.

    Считаем из цен сигнала, а не из `wv_risk_pct` тени: поле может отсутствовать у старых
    записей очереди, а цены есть всегда. None — если импульс неизвестен или нулевой
    (тогда решение принимает вызывающий, а не молчаливый ноль)."""
    try:
        e, s, i = float(entry), float(stop), float(imp_pct)
    except (TypeError, ValueError):
        return None
    if e <= 0 or i <= 0:
        return None
    return abs(e - s) / e * 100 / i


def _in_corridor(rel, lo, hi) -> bool:
    """Попадает ли ширина стопа в измеренный коридор [lo; hi).

    Верхняя граница ИСКЛЮЧЕНА — корзина 30-50% в замере считалась как [0.3; 0.5).
    Неизвестная ширина (нет `wv_imp_pct`) — это НЕ «в коридоре»: метка должна отличать
    «вне» от «не знаем», поэтому False, а признак `wv_stop_rel` в сделку просто не попадёт."""
    if rel is None:
        return False
    if lo is not None and rel < float(lo):
        return False
    if hi is not None and rel >= float(hi):
        return False
    return True


def _risk_frame(bot, cfg) -> tuple[bool, str]:
    """РИСК-КАРКАС (Егор 06.10 «делай»): можно ли открывать ЕЩЁ одну позицию.

    Два ограничителя, оба измеренные, а не придуманные:

    1. **Слоты.** Лимита не было вовсе (решение 17.09 «слоты не ограничиваем»), и
       за 60 дней максимум одновременно открытых по всем источникам достигал **130** —
       при риске 2% на сделку это 260% счёта в рынке одновременно. Считаем через
       общий `source_registry.slots()`, как `choch_wavec`, `impulse_fib`, `ds_advisor`.
    2. **Дневной лимит.** Его тоже не было. Худшие дни по сумме % хода: −212.2,
       −200.9, −126.8 при медиане дня −15.5.

    🔑 Зачем это, если каркас не даёт прибыли: единственное, что проходит линейку
    коста ([[cost_is_amplifier_not_cause]]), — редкие клетки с частотой 0.8–4.9
    сделки/мес. Им нужны МЕСЯЦЫ, чтобы себя показать, и счёт должен дожить.
    Каркас ограничивает ущерб, а не ищет доход — перемер 22.08 показал, что
    предохранитель ничего не отбирает ([[live_no_circuit_breaker_cost_95pct_loss]]).

    Возвращает (можно ли торговать, причина отказа).
    """
    max_open = cfg.get("trading.waves_long.max_open", None)
    day_lim = cfg.get("trading.waves_long.max_daily_loss_pct", None)
    if max_open is None and day_lim is None:
        return True, ""
    try:
        import sqlite3
        with sqlite3.connect(bot.db_path if hasattr(bot, "db_path") else "subscriptions.db") as conn:
            if max_open is not None:
                from core.trading.source_registry import slots as _slots
                st = _slots(conn, "waves_long", max_open=int(max_open))
                if not st["can_place"]:
                    return False, st["why"]
            if day_lim is not None:
                # сумма % хода по ЗАКРЫТЫМ за последние сутки; формат времени с `T`
                # нормализуем — иначе сравнение строк врёт ([[time_utc_vs_local_in_db]])
                # 🔴 08.10: только БИРЖЕВЫЕ сделки — недоказанный поток теперь в тени (SIM), и его убытки
                # не должны останавливать доказанные входы
                _exch = (" AND execution_mode IN ('VST','LIVE')" if _has_col(conn, "execution_mode") else "")
                row = conn.execute(
                    "SELECT COALESCE(SUM(profit_pct), 0) FROM simulated_trades "
                    "WHERE signal_type='waves_long' AND profit_pct IS NOT NULL "
                    "AND substr(replace(closed_at,'T',' '),1,19) >= datetime('now','-1 day')" + _exch
                ).fetchone()
                day_sum = float(row[0] or 0.0)
                if day_sum <= -abs(float(day_lim)):
                    return False, f"дневной лимит: {day_sum:+.1f}% за сутки (лимит −{abs(float(day_lim))}%)"
    except Exception as e:                               # noqa: BLE001
        # каркас не должен ронять торговлю: при сбое пропускаем, но ГРОМКО
        logger.warning("[WAVES_LONG] риск-каркас не проверен (%s) — пропускаю", e)
        return True, ""
    return True, ""


def _has_col(conn, col: str, table: str = "simulated_trades") -> bool:
    try:
        return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))
    except Exception:                                    # noqa: BLE001
        return False


def _risk_budget(bot, cfg, new_risk_pct: float, wt_abs) -> tuple[float | None, str]:
    """БЮДЖЕТ ОТКРЫТОГО РИСКА вместо числа позиций (08.10, Егор «1-3»: «именно поэтому лимиты и не ограничивал»).

    Портфельная симуляция (`scripts/wave_portfolio_sim.py`, доказанные лонги 2023→08.2026, учёт по закрытию):
    лимит 6 позиций +97% капитала · бюджет риска 15/25% +185% (просадка −29, худший день −22) · без лимита +312%
    при 141 позиции разом. Деньги клетки живут в КЛАСТЕРАХ дней капитуляции, и счёт позиций режет именно их.
    Маржа при плече «под стоп» (lev_set_to_max) ≈ риску позиции → бюджет риска держит и маржу.

    Правило: открытый риск биржевых позиций + новая ≤ мягкого — полный риск (1.0); сверх мягкого — только
    |WT на вершине пятой| ≥ порога ([[wave_fifth_wt_depth_cell]]: +9.06 против +3.26 при стопе ≥6%) и
    половиной риска, пока помещается под жёсткий потолок (0.5); иначе придержать (None).
    Бюджет не задан → (1.0, ""). Сбой подсчёта → (1.0, ...) громко: каркас не роняет торговлю."""
    soft = cfg.get("trading.waves_long.max_open_risk_pct", None)
    if soft is None:
        return 1.0, ""
    hard = float(cfg.get("trading.waves_long.max_open_risk_hard_pct", soft) or soft)
    wt_th = float(cfg.get("trading.waves_long.wt_priority_abs", 75.0) or 75.0)
    base = float(cfg.get("signal_router.source_policies.waves_long.risk_pct", 1.0) or 1.0)
    try:
        import sqlite3
        with sqlite3.connect(bot.db_path if hasattr(bot, "db_path") else "subscriptions.db") as conn:
            _exch = " AND execution_mode IN ('VST','LIVE')" if _has_col(conn, "execution_mode") else ""
            rows = conn.execute(
                "SELECT features_json FROM simulated_trades WHERE signal_type='waves_long' "
                "AND status IN ('OPEN','PENDING_ENTRY')" + _exch).fetchall()
        cur = 0.0
        for (fj,) in rows:
            try:
                rm = float((json.loads(fj or "{}") or {}).get("risk_mult") or 1.0)
            except Exception:                            # noqa: BLE001
                rm = 1.0
            cur += base * rm
    except Exception as e:                               # noqa: BLE001
        logger.warning("[WAVES_LONG] бюджет риска не посчитан (%s) — пропускаю полным риском", e)
        return 1.0, ""
    if cur + new_risk_pct <= float(soft) + 1e-9:
        return 1.0, ""
    try:
        deep = wt_abs is not None and abs(float(wt_abs)) >= wt_th
    except (TypeError, ValueError):
        deep = False
    if deep and cur + 0.5 * new_risk_pct <= hard + 1e-9:
        return 0.5, (f"открыто {cur:.1f}% риска > мягкого {float(soft):g}% — глубокая пятая (|WT| "
                     f"{abs(float(wt_abs)):.0f} ≥ {wt_th:g}) берётся ПОЛОВИНОЙ риска (потолок {hard:g}%)")
    return None, (f"открыто {cur:.1f}% риска: + {new_risk_pct:.2f}% выходит за мягкий {float(soft):g}%"
                  + ("" if deep else f", а |WT пятой| {wt_abs if wt_abs is not None else '—'} < {wt_th:g}")
                  + (f" и за жёсткий {hard:g}%" if deep else ""))


def _long_proven(entry, stop, in_corridor: bool, proven_stop_pct) -> bool:
    """ДОКАЗАННАЯ ЗОНА ЛОНГА: структурный стоп ≥ `proven_stop_pct` % цены ИЛИ коридор 30-50% импульса.

    07.10 (Егор: «заставить работать то, что уже доказано»). Замер боевым кодом
    (`scripts/wave_entry_delay_lab.py`, 198 монет, кост 0.35): лонг после завершённой пятёрки
    вниз со стопом ≥6% цены — плюс В КАЖДОМ году: 2023 PF 3.50 · 2024 1.43 · 2025 4.36 ·
    **2026 5.39 (183 сделки, 79% прибыльных, +7.59% в среднем)**. Коридор 30-50% импульса
    (метка с 03.10) тоже живой (n=126, PF 3.50) — он остаётся, зона его не заменяет, а
    расширяет. Стоп у доказанных сделок: медиана 9%, квартили 6.9–12.2%.
    """
    if in_corridor:
        return True
    if proven_stop_pct is None:
        return False
    try:
        e, s = float(entry), float(stop)
        if e <= 0:
            return False
        return abs(e - s) / e * 100.0 >= float(proven_stop_pct)
    except (TypeError, ValueError):
        return False


def _risk_mult(coin_weight, in_corridor: bool, out_mult, cap) -> float | None:
    """Итоговый множитель риска: вес монеты × множитель ТРЕКА.

    04.10 (Егор «да» на риск-вес вместо отсечения): трек вне измеренного коридора ширины стопа
    торгуется МЕНЬШИМ риском, а не выбрасывается — так данные исполнения продолжают набираться
    по обоим трекам ([[law_hard_filter_kills_execution_data]]), но деньги смещены в сторону
    измеренного эджа (коридор 30-50% импульса: ср +5.01, WR 80%, Δr +10.76 против +0.52…+2.89
    в корзинах 0-20%).

    Вес монеты (22.09) живёт в своих границах 0.5…1.5, трековый множитель применяется ПОВЕРХ,
    итог зажимается в [0.25; cap] — те же границы, что в `trade_router` (иначе ослабление
    срезалось бы там и правка оказалась бы декоративной).
    None — если ни веса, ни ослабления нет: тогда ключ в сделку не пишется и риск остаётся
    базовым (risk_pct источника), как было до правки."""
    m = None
    if coin_weight is not None:
        try:
            m = max(0.5, min(1.5, float(coin_weight)))
        except (TypeError, ValueError):
            m = None
    if not in_corridor and out_mult is not None:
        try:
            m = (1.0 if m is None else m) * float(out_mult)
        except (TypeError, ValueError):
            pass
    if m is None:
        return None
    try:
        hi = float(cap)
    except (TypeError, ValueError):
        hi = 1.5
    return round(max(0.25, min(m, hi)), 4)


def _open_on_symbol(bot, symbol: str, exchange: bool | None = None) -> int:
    """Сколько открытых сделок семейства уже висит на монете (источник истины — симулятор).
    exchange=True — только биржевые (VST/LIVE), False — только теневые (SIM), None — все.
    08.10: теневая (недоказанная) сделка на монете не должна блокировать доказанный вход по ней."""
    try:
        sim = getattr(bot, "trade_simulator", None) or getattr(bot, "simulator", None)
        if sim is None:
            return 0
        rows = sim.get_open_trades() if hasattr(sim, "get_open_trades") else []

        def _mode_ok(t):
            if exchange is None:
                return True
            on_ex = str(t.get("execution_mode") or "SIM").upper() in ("VST", "LIVE")
            return on_ex if exchange else not on_ex
        return sum(1 for t in rows
                   if str(t.get("symbol") or t.get("pair") or "") == symbol
                   and str(t.get("signal_type") or "") == "waves_long" and _mode_ok(t))
    except Exception:
        return 0


async def waves_long_loop(bot):
    cfg = getattr(bot, "config", None)
    if cfg is None or not cfg.get("trading.waves_long.enabled", False):
        logger.info("[WAVES_LONG] выключен (trading.waves_long.enabled=false)")
        return
    from core.signals.signal_models import TradingRecommendation, SignalDirection, MarketContext
    from core.context.context_factory import build_market_context

    done = _load_done()
    # миграция 21.09: старые записи очереди (старше окна исполнения) помечаем новым ключом, чтобы смена
    # формата ключа не выстрелила пачкой «сигналу N мин (>45)» по всей истории очереди
    stale = [_event_key(r) for r in _read_all() if _signal_age_min(r) > MAX_AGE_MIN]
    done.update(stale)
    _lo0, _hi0 = (cfg.get("trading.waves_long.stop_rel_min", None),
                  cfg.get("trading.waves_long.stop_rel_max", None))
    _gate_on = bool(cfg.get("trading.waves_long.stop_rel_gate", False))
    _rm0 = cfg.get("trading.waves_long.stop_rel_risk_mult", None)
    _mode = (f"ОТБОР: только коридор [{_lo0}; {_hi0}) — ожидаемо ~5 сделок/мес на вселенную"
             if _gate_on else
             f"МЕТКА: торгуем ОБА трека, коридор [{_lo0}; {_hi0}) помечается wv_in_corridor "
             f"(поток полный, ~69/мес — данные исполнения собираются по обоим)"
             + (f" · РИСК вне коридора ×{_rm0}" if _rm0 not in (None, 1, 1.0) else " · риск равный"))
    # 🛡️ каркас обязан объявить себя при старте: выключенный ограничитель, о котором
    # никто не знает, — это та же мина, что молчаливо выключенный источник
    # ([[feedback_selftest_every_strategy_loud]])
    _mo = cfg.get("trading.waves_long.max_open", None)
    _dl = cfg.get("trading.waves_long.max_daily_loss_pct", None)
    _sh = bool(cfg.get("trading.waves_long.short_enabled", False))
    _frame = (f"слоты {'не ограничены' if _mo is None else _mo} · дневной лимит −{_dl}% хода (биржевые)"
              if (_mo is not None or _dl is not None)
              else "🔴 НЕ ЗАДАН (ни слотов, ни дневного лимита)")
    _pp = cfg.get("trading.waves_long.proven_stop_pct", None)
    _srm = cfg.get("trading.waves_long.short_risk_mult", None)
    _shadow = bool(cfg.get("trading.waves_long.unproven_to_shadow", False))
    _br = cfg.get("trading.waves_long.max_open_risk_pct", None)
    _budget = (f"бюджет открытого риска {_br}% (сверх — |WT пятой| ≥ "
               f"{cfg.get('trading.waves_long.wt_priority_abs', 75)} половиной, потолок "
               f"{cfg.get('trading.waves_long.max_open_risk_hard_pct', _br)}%)" if _br is not None else "бюджет риска не задан")
    logger.info("[WAVES_LONG] старт · очередь %s · обработано ранее %d (из них устаревших помечено %d) · "
                "дедуп по (uid, время события): повторные входы по тому же импульсу разрешены · "
                "ширина стопа в долях импульса → %s · 🔑 ДОКАЗАННАЯ ЗОНА ЛОНГА: стоп ≥%s%% или коридор · "
                "🛡️ РИСК-КАРКАС: %s · %s · ШОРТ: %s · 🌒 НЕДОКАЗАННЫЕ (лонг вне зоны, шорт): %s",
                QUEUE, len(done), len(stale), _mode, _pp, _frame, _budget,
                (f"включён, доказанной зоны нет → риск ×{_srm}" if _sh else "выключен"),
                "ТЕНЬ — регистрируются без биржи" if _shadow else "на биржу пониженным риском")
    while True:
        try:
            # 08.10: пришедшие одновременно — глубже WT пятой первым: бюджет риска достаётся сильнейшим
            # ([[wave_fifth_wt_depth_cell]]); у старых записей без поля — в конец очереди
            fresh = sorted(_read_new(done), key=lambda r: -abs(float(r.get("wv_wt_top") or 0)))
            for r in fresh:
                uid = r["uid"]
                done.add(_event_key(r))             # помечаем сразу: повтор при ошибке хуже пропуска
                if uid in done or any(k.startswith(uid + "|") and k != _event_key(r) for k in done):
                    logger.info("[WAVES_LONG] %s ПОВТОРНЫЙ вход по тому же импульсу (событие %s) — исполняем",
                                uid, _event_key(r).rsplit("|", 1)[-1])
                # 🔴 18.09: символ ОБЯЗАН быть в формате бота `BASE/USDT:USDT`. Тень пишет `BASE/USDT`, и на
                # этом сломалось всё сразу: AccountRouter завёл дубли пар (`GUN/USDT` ≠ `GUN/USDT:USDT`) и
                # раскидал их по аккаунтам, account_id в БД записался не тот, детектор сирот не узнал свои
                # позиции и закрыл их по рынку через минуту после входа (GUN, STAR, JASMY, AIXBT, SKY, ONG…).
                sym = _canon(r.get("sym") or "")
                entry, stop, tp = r.get("entry"), r.get("stop"), r.get("target")
                if not sym or not entry or not stop or not tp:
                    logger.info("[WAVES_LONG] %s пропуск: нет цен в сигнале", uid)
                    continue
                # 🌊 06.10 ШОРТ ВКЛЮЧЁН (Егор «шорт-ядра +»). До этого отсекался наглухо
                # «замером 16.09». Замер 29.09 ([[waves_sides_measured_both]]) его подтвердил
                # НА ОБЩЕЙ БАЗЕ: шорт против рыночного момента ноль (Δt −0.09), при боевом
                # косте вся сторона в минусе (ср −0.22). 🔑 Но у шорта есть ОДНО живое место —
                # клетка `полное ядро ∧ стоп ≥6% цены`: n=36, ср +2.15, медиана +4.02, WR 58%,
                # Δt +4.41, безтоп10% +21, перестановка p=0.002, суррогат пройден (перевес
                # реала +5.77 против −1.82 на шуме). Поодиночке условия мертвы: стоп≥6% БЕЗ
                # ядра → Δt −0.69. Поэтому шорт идёт МЕТКОЙ с риск-весом, как лонг с 04.10:
                # поток данных исполнения собираем по обоим трекам, деньги смещаем в клетку.
                _side = str(r.get("side") or "").upper()
                if _side == "SHORT" and not cfg.get("trading.waves_long.short_enabled", False):
                    continue
                if _side not in ("LONG", "SHORT"):
                    continue
                _is_short = _side == "SHORT"
                age_min = _signal_age_min(r)        # UTC (calendar.timegm), от времени события
                if age_min > MAX_AGE_MIN:
                    logger.info("[WAVES_LONG] %s пропуск: сигналу %.0f мин (>%d)", uid, age_min, MAX_AGE_MIN)
                    continue
                # 16.09 (SYN): цель за спиной = мгновенный «target» с убытком. Для шорта
                # неравенства зеркальны — иначе каждый шорт отсеивался бы этой же строкой.
                _geom_bad = (tp >= entry or stop <= entry) if _is_short else (tp <= entry or stop >= entry)
                if _geom_bad:
                    logger.info("[WAVES_LONG] %s пропуск: цель/стоп не с той стороны", uid)
                    continue
                # 🌊🔑 03.10 ШИРИНА СТОПА В ДОЛЯХ ИМПУЛЬСА — МЕТКА, А НЕ ОТБОР.
                # Замер 02.10: эдж сидит в коридоре 30-50% импульса (ср +5.01, WR 80%, Δr +10.76),
                # а бой стоял на медиане 0.129 — в корзине 0-20%, где ср +0.52…+2.89.
                # 🔴 Жёсткий отбор был включён и в тот же день снят (Егор: «он не должен быть
                # единственным — такой подход лишает нас потока данных ИСПОЛНЕНИЯ; оставлять в
                # работе параллельно друг другу»): коридор оставлял 6% потока. Теперь в бой идут
                # ОБА трека, различимые по `wv_in_corridor`, и данные исполнения (филлы,
                # проскальзывание, косты) набираются по обоим на одной выборке.
                _rel = _stop_rel(entry, stop, r.get("wv_imp_pct"))
                _lo, _hi = (cfg.get("trading.waves_long.stop_rel_min", None),
                            cfg.get("trading.waves_long.stop_rel_max", None))
                _in_cor = _in_corridor(_rel, _lo, _hi)
                # 🔑 07.10 ЛОНГ: полный риск — доказанной зоне (стоп ≥6% цены ИЛИ коридор импульса).
                # 🔴 07.10 ШОРТ: доказанной зоны НЕТ. Клетка 06.10 (`core_full ∧ стоп≥6%`) на боевом
                # коде дала PF 0.64, −2.04; «верная» (ядро без порога глубины) — тоже 0.64, −1.99;
                # сторона целиком идёт за режимом года (2025 PF 1.43, 2023 0.57). Поэтому все шорты
                # торгуются одинаковым минимальным риском — ради данных исполнения, без «клетки».
                if _is_short:
                    _in_cor = False
                else:
                    _in_cor = _long_proven(entry, stop, _in_cor,
                                           cfg.get("trading.waves_long.proven_stop_pct", None))
                if cfg.get("trading.waves_long.stop_rel_gate", False) and not _in_cor:
                    logger.info("[WAVES_LONG] %s пропуск (gate=true): стоп %s импульса вне коридора [%s; %s)",
                                uid, "—" if _rel is None else f"{_rel:.3f}", _lo, _hi)
                    continue
                # 🌒 08.10 НЕДОКАЗАННЫЙ ПОТОК → ТЕНЬ (Егор «1-3»). Портфельная симуляция: лонг вне доказанной
                # зоны + шорт = −73% капитала без лимита, −161% с лимитом 3, и он забирал слоты у доказанных
                # (весь поток с лимитом 6 −97% против +100% у одних доказанных). Сделка регистрируется (SIM —
                # данные сигнала копятся), но на биржу не идёт и бюджет риска не занимает.
                _to_shadow = (_is_short or not _in_cor) and bool(cfg.get("trading.waves_long.unproven_to_shadow", False))
                # одна открытая позиция на монету: у COOKIE/PROMPT за двое суток набралось по 4 входа
                # (три сетапа + повторные) — случай AEONBSC, где три варианта били по очереди.
                # 08.10: считается в СВОЁМ контуре — теневая сделка не блокирует биржевой вход и наоборот
                _scope = (False if _to_shadow else True) if cfg.get("trading.waves_long.unproven_to_shadow", False) else None
                if _open_on_symbol(bot, sym, _scope) >= int(cfg.get("trading.waves_long.max_per_symbol", 1) or 1):
                    logger.info("[WAVES_LONG] %s пропуск: по монете уже есть открытая позиция%s", uid,
                                " (тень)" if _to_shadow else "")
                    continue
                _half = False
                if not _to_shadow:
                    # 🛡️ 06.10 РИСК-КАРКАС: слоты + дневной лимит (по биржевым). Проверяем ПОСЛЕДНИМ, прямо
                    # перед отправкой — чтобы в логе было видно, что сетап дошёл до конца и
                    # остановлен именно каркасом, а не фильтром (закон: молчаливых отказов нет).
                    _ok, _why = _risk_frame(bot, cfg)
                    if not _ok:
                        logger.info("[WAVES_LONG] 🛡️ %s ПРИДЕРЖАН каркасом: %s", uid, _why)
                        continue
                    # 08.10 БЮДЖЕТ ОТКРЫТОГО РИСКА (вместо числа позиций)
                    _rm_pre = _risk_mult(r.get("wv_weight"), bool(_in_cor),
                                         cfg.get("trading.waves_long.stop_rel_risk_mult", None),
                                         cfg.get("trading.risk_mult_cap", 1.5))
                    _new_risk = float(cfg.get("signal_router.source_policies.waves_long.risk_pct", 1.0) or 1.0) \
                        * (1.0 if _rm_pre is None else _rm_pre)
                    _use, _bwhy = _risk_budget(bot, cfg, _new_risk, r.get("wv_wt_top"))
                    if _use is None:
                        logger.info("[WAVES_LONG] 🛡️ %s ПРИДЕРЖАН бюджетом риска: %s", uid, _bwhy)
                        continue
                    if _use < 1.0:
                        _half = True
                        logger.info("[WAVES_LONG] 🛡️ %s %s", uid, _bwhy)
                rec = TradingRecommendation(
                    symbol=sym,
                    action="SELL" if _is_short else "BUY",
                    direction=SignalDirection.SHORT if _is_short else SignalDirection.LONG,
                    overall_strength=65, confidence=0.6, risk_level="MEDIUM", signals_count=1,
                    supporting_signals=[], conflicting_signals=[],
                    reasoning=f"waves_{'short' if _is_short else 'long'} {r.get('wv_variant')} · "
                              f"вершина {r.get('wv_top_time')}",
                    # 29.09: контекст собирает ШИНА (было volume_24h=0.0 — оборот терялся)
                    market_context=build_market_context(bot, sym, current_price=float(entry),
                                                        volatility=0.0),
                    entry_price=float(entry), stop_loss=float(stop), take_profit=float(tp))
                extra = {"signal_type_override": "waves_long", "trade_mode": "waves_long"}
                extra.update({k: v for k, v in r.items() if k.startswith("wv_")})
                # ширина стопа в долях импульса — в признаки сделки, чтобы результат резался
                # по ТОЙ ЖЕ величине, по которой шёл отбор (а не по пересчёту задним числом)
                if _rel is not None:
                    extra["wv_stop_rel"] = round(_rel, 4)
                if _rel is not None or _is_short:
                    extra["wv_in_corridor"] = bool(_in_cor)   # трек: клетка замера против остального
                # сторона пишется явно: `waves_long` как имя источника остаётся (чтобы не рвать
                # историю и отчёты), поэтому отличить шорт можно только по этому полю
                extra["wv_side"] = "SHORT" if _is_short else "LONG"
                # 🟢 22.09 ВЕС МОНЕТЫ (Егор: «вес монеты добавить!»): corr30 к BTC × vol30 → 0.5…1.5
                #   (см. wave5_shadow.coin_weight)
                # 🌊🔑 04.10 РИСК-ВЕС ТРЕКА: вне коридора ширины стопа — меньший риск, а не отказ.
                _rm = _risk_mult(r.get("wv_weight"), bool(_in_cor),
                                 cfg.get("trading.waves_long.short_risk_mult", None)
                                 if _is_short else
                                 cfg.get("trading.waves_long.stop_rel_risk_mult", None),
                                 cfg.get("trading.risk_mult_cap", 1.5))
                if _half:                                # сверх мягкого бюджета — половина риска
                    _rm = round((1.0 if _rm is None else _rm) * 0.5, 4)
                    extra["wv_risk_half"] = True
                if _rm is not None:
                    extra["risk_mult"] = _rm
                if _to_shadow:
                    extra["exchange_off"] = ("waves: шорт — доказанной зоны нет" if _is_short else
                                             "waves: лонг вне доказанной зоны (стоп <6% и не коридор)")
                    extra["wv_shadow"] = True
                try:
                    res = await bot.trade_router.submit(rec, source="waves_long", extra_features=extra)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[WAVES_LONG] %s ошибка отправки: %s", uid, e)
                    continue
                if res and getattr(res, "trade_id", None):
                    logger.info("[WAVES_LONG] %s %s %s %s вход %.8g стоп %.8g цель %.8g · стоп %s имп (%s) · "
                                "WT пятой %s · вес %s (corr30 %s · vol30 %s) · trade_id=%s",
                                "🌒 ТЕНЬ" if _to_shadow else "✅",
                                "SHORT" if _is_short else "LONG",
                                sym, r.get("wv_variant"), entry, stop, tp,
                                "—" if _rel is None else f"{_rel:.3f}",
                                "шорт: доказанной зоны нет" if _is_short
                                else ("В ДОКАЗАННОЙ ЗОНЕ" if _in_cor else "вне зоны"),
                                r.get("wv_wt_top", "—"),
                                extra.get("risk_mult", "—"), r.get("wv_corr30", "—"),
                                r.get("wv_vol30", "—"), res.trade_id)
                else:
                    drops = getattr(res, "hard_drops", None) or getattr(res, "drops", None)
                    logger.warning("[WAVES_LONG] ⛔ %s %s НЕ зарегистрирован: %s",
                                   sym, r.get("wv_variant"), drops)
            if fresh:
                _save_done(done)
        except Exception as e:  # noqa: BLE001
            logger.warning("[WAVES_LONG] цикл: %s", e)
        await asyncio.sleep(POLL_SEC)
