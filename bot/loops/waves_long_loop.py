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
    logger.info("[WAVES_LONG] старт · очередь %s · обработано ранее %d (из них устаревших помечено %d) · "
                "дедуп по (uid, время события): повторные входы по тому же импульсу разрешены",
                QUEUE, len(done), len(stale))
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
                if r.get("side") != "LONG":
                    continue
                age_min = _signal_age_min(r)        # UTC (calendar.timegm), от времени события
                if age_min > MAX_AGE_MIN:
                    logger.info("[WAVES_LONG] %s пропуск: сигналу %.0f мин (>%d)", uid, age_min, MAX_AGE_MIN)
                    continue
                if tp <= entry or stop >= entry:    # 16.09 (SYN): цель за спиной = мгновенный «target» с убытком
                    logger.info("[WAVES_LONG] %s пропуск: цель/стоп не с той стороны", uid)
                    continue
                # одна открытая позиция на монету: у COOKIE/PROMPT за двое суток набралось по 4 входа
                # (три сетапа + повторные) — случай AEONBSC, где три варианта били по очереди
                if _open_on_symbol(bot, sym) >= int(cfg.get("trading.waves_long.max_per_symbol", 1) or 1):
                    logger.info("[WAVES_LONG] %s пропуск: по монете уже есть открытая позиция", uid)
                    continue
                rec = TradingRecommendation(
                    symbol=sym, action="BUY", direction=SignalDirection.LONG,
                    overall_strength=65, confidence=0.6, risk_level="MEDIUM", signals_count=1,
                    supporting_signals=[], conflicting_signals=[],
                    reasoning=f"waves_long {r.get('wv_variant')} · вершина {r.get('wv_top_time')}",
                    # 29.09: контекст собирает ШИНА (было volume_24h=0.0 — оборот терялся)
                    market_context=build_market_context(bot, sym, current_price=float(entry),
                                                        volatility=0.0),
                    entry_price=float(entry), stop_loss=float(stop), take_profit=float(tp))
                extra = {"signal_type_override": "waves_long", "trade_mode": "waves_long"}
                extra.update({k: v for k, v in r.items() if k.startswith("wv_")})
                # 🟢 22.09 ВЕС МОНЕТЫ (Егор: «вес монеты добавить!»): corr30 к BTC × vol30 → risk_mult 0.5…1.5 (см. wave5_shadow.coin_weight)
                try:
                    if r.get("wv_weight") is not None:
                        extra["risk_mult"] = max(0.5, min(1.5, float(r["wv_weight"])))
                except (TypeError, ValueError):
                    pass
                try:
                    res = await bot.trade_router.submit(rec, source="waves_long", extra_features=extra)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[WAVES_LONG] %s ошибка отправки: %s", uid, e)
                    continue
                if res and getattr(res, "trade_id", None):
                    logger.info("[WAVES_LONG] ✅ %s %s вход %.8g стоп %.8g цель %.8g · вес %s (corr30 %s · vol30 %s) · trade_id=%s",
                                sym, r.get("wv_variant"), entry, stop, tp, extra.get("risk_mult", "—"), r.get("wv_corr30", "—"), r.get("wv_vol30", "—"), res.trade_id)
                else:
                    drops = getattr(res, "hard_drops", None) or getattr(res, "drops", None)
                    logger.warning("[WAVES_LONG] ⛔ %s %s НЕ зарегистрирован: %s",
                                   sym, r.get("wv_variant"), drops)
            if fresh:
                _save_done(done)
        except Exception as e:  # noqa: BLE001
            logger.warning("[WAVES_LONG] цикл: %s", e)
        await asyncio.sleep(POLL_SEC)
