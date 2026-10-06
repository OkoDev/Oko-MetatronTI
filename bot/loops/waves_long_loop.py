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


def _short_cell(entry, stop, core_full) -> bool:
    """Живая клетка ШОРТА: полное ядро И стоп ≥6% цены (замер 29.09, n=36).

    Оба условия обязательны вместе: стоп≥6% БЕЗ ядра даёт Δt −0.69 (мёртво), ядро без
    стопа — слабо, вместе Δt +4.41 при перестановке p=0.002 и пройденном суррогате.
    Коридор 30-50% импульса сюда НЕ переносится: он измерен для лонга, у шорта та же ось
    мертва (20-30% → −0.66, 30-50% → −2.22) — [[waves_sides_measured_both]].
    """
    if not core_full:
        return False
    try:
        e, s = float(entry), float(stop)
        if e <= 0:
            return False
        return abs(e - s) / e * 100.0 >= 6.0
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


def _open_on_symbol(bot, symbol: str) -> int:
    """Сколько открытых сделок семейства уже висит на монете (источник истины — симулятор)."""
    try:
        sim = getattr(bot, "trade_simulator", None) or getattr(bot, "simulator", None)
        if sim is None:
            return 0
        rows = sim.get_open_trades() if hasattr(sim, "get_open_trades") else []
        return sum(1 for t in rows
                   if str(t.get("symbol") or t.get("pair") or "") == symbol
                   and str(t.get("signal_type") or "") == "waves_long")
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
    logger.info("[WAVES_LONG] старт · очередь %s · обработано ранее %d (из них устаревших помечено %d) · "
                "дедуп по (uid, время события): повторные входы по тому же импульсу разрешены · "
                "ширина стопа в долях импульса → %s",
                QUEUE, len(done), len(stale), _mode)
    while True:
        try:
            fresh = _read_new(done)
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
                # 🌊 06.10 У ШОРТА СВОЯ КЛЕТКА — не коридор импульса, а `ядро ∧ стоп ≥6% цены`.
                # Коридор 30-50% импульса измерен ДЛЯ ЛОНГА; у шорта та же ось мертва
                # (20-30% → −0.66, 30-50% → −2.22). Переносить метку нельзя — это ровно тот
                # случай, о котором предупреждает протокол: перенос = мерить, не предполагать.
                if _is_short:
                    _in_cor = _short_cell(entry, stop, r.get("wv_core_full"))
                if cfg.get("trading.waves_long.stop_rel_gate", False) and not _in_cor:
                    logger.info("[WAVES_LONG] %s пропуск (gate=true): стоп %s импульса вне коридора [%s; %s)",
                                uid, "—" if _rel is None else f"{_rel:.3f}", _lo, _hi)
                    continue
                # одна открытая позиция на монету: у COOKIE/PROMPT за двое суток набралось по 4 входа
                # (три сетапа + повторные) — случай AEONBSC, где три варианта били по очереди
                if _open_on_symbol(bot, sym) >= int(cfg.get("trading.waves_long.max_per_symbol", 1) or 1):
                    logger.info("[WAVES_LONG] %s пропуск: по монете уже есть открытая позиция", uid)
                    continue
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
                                 cfg.get("trading.waves_long.short_cell_risk_mult", None)
                                 if _is_short else
                                 cfg.get("trading.waves_long.stop_rel_risk_mult", None),
                                 cfg.get("trading.risk_mult_cap", 1.5))
                if _rm is not None:
                    extra["risk_mult"] = _rm
                try:
                    res = await bot.trade_router.submit(rec, source="waves_long", extra_features=extra)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[WAVES_LONG] %s ошибка отправки: %s", uid, e)
                    continue
                if res and getattr(res, "trade_id", None):
                    logger.info("[WAVES_LONG] ✅ %s %s %s вход %.8g стоп %.8g цель %.8g · стоп %s имп (%s) · "
                                "вес %s (corr30 %s · vol30 %s) · trade_id=%s",
                                "SHORT" if _is_short else "LONG",
                                sym, r.get("wv_variant"), entry, stop, tp,
                                "—" if _rel is None else f"{_rel:.3f}",
                                ("В КЛЕТКЕ (ядро+стоп≥6%)" if _in_cor else "вне клетки") if _is_short
                                else ("В КОРИДОРЕ" if _in_cor else "вне"),
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
