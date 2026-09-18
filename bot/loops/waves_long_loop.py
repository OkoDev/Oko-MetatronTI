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
Gated: trading.waves_long.enabled. Дедуп по `uid` (символ|ключ сетапа|вариант).
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


def _read_new(done: set) -> list:
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
            if r.get("uid") and r["uid"] not in done:
                out.append(r)
    except Exception as e:  # noqa: BLE001
        logger.warning("[WAVES_LONG] очередь не прочитана: %s", e)
    return out


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

    done = _load_done()
    logger.info("[WAVES_LONG] старт · очередь %s · обработано ранее %d", QUEUE, len(done))
    while True:
        try:
            fresh = _read_new(done)
            for r in fresh:
                uid = r["uid"]
                done.add(uid)                       # помечаем сразу: повтор при ошибке хуже пропуска
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
                    market_context=MarketContext(symbol=sym, current_price=float(entry), volume_24h=0.0,
                                                 volume_change_24h=0.0, price_change_24h=0.0, volatility=0.0),
                    entry_price=float(entry), stop_loss=float(stop), take_profit=float(tp))
                extra = {"signal_type_override": "waves_long", "trade_mode": "waves_long"}
                extra.update({k: v for k, v in r.items() if k.startswith("wv_")})
                try:
                    res = await bot.trade_router.submit(rec, source="waves_long", extra_features=extra)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[WAVES_LONG] %s ошибка отправки: %s", uid, e)
                    continue
                if res and getattr(res, "trade_id", None):
                    logger.info("[WAVES_LONG] ✅ %s %s вход %.8g стоп %.8g цель %.8g · trade_id=%s",
                                sym, r.get("wv_variant"), entry, stop, tp, res.trade_id)
                else:
                    drops = getattr(res, "hard_drops", None) or getattr(res, "drops", None)
                    logger.warning("[WAVES_LONG] ⛔ %s %s НЕ зарегистрирован: %s",
                                   sym, r.get("wv_variant"), drops)
            if fresh:
                _save_done(done)
        except Exception as e:  # noqa: BLE001
            logger.warning("[WAVES_LONG] цикл: %s", e)
        await asyncio.sleep(POLL_SEC)
