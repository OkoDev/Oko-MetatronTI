"""
Дрейф вселенной — режимный контекст для фейд-механик.

Найдено 21.08.2026 и подтверждено ДВУМЯ независимыми слепыми тестами: short механики
impulse_fib резко улучшается, когда медианная 30-дневная доходность вселенной высока.
Механизм: фейдим отскок внутри падающего рынка.

    короткая сторона + drift30 >= +10%  →  OOS PF 5.54 против базы 1.22
                                           охват 59% монет, безтоп10% +1931
    контроль: на длинной стороне то же правило УХУДШАЕТ (0.72 → 0.41)

🔴 ЛАГ ОБЯЗАТЕЛЕН. Замер брал значение за ВЧЕРАШНИЙ закрытый день. `get_drift()`
делает это сам: сегодняшний незакрытый день не берётся никогда. Не «оптимизировать»,
взяв свежее значение — это внесёт заглядывание вперёд и сломает соответствие замеру.

Данные наполняет `scripts/universe_drift.py` (pm2 `universe-drift`, ежечасно).
Читаем из `subscriptions.db` → таблица `universe_drift`.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DB = str(Path(__file__).resolve().parents[2] / "oko_feed" / "universe.db")   # N16 29.09: база universe-drift
_TTL_SEC = 600                      # значение меняется раз в сутки — 10 минут с запасом
_cache: dict = {"ts": 0.0, "val": None}

# Порог из пройденного слепого теста. Менять только вместе с новым замером.
SHORT_ZONE_PCT = 10.0


def get_drift(*, max_age_days: int = 3) -> dict | None:
    """
    Дрейф вселенной за ВЧЕРАШНИЙ закрытый день.

    Возвращает {'day','drift30','drift90','drift180','n_coins'} или None,
    если данных нет или они протухли (наполнитель не отработал).
    """
    now = time.time()
    if _cache["val"] is not None and now - _cache["ts"] < _TTL_SEC:
        return _cache["val"]

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    oldest = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, timeout=5) as c:
            row = c.execute(
                "SELECT day,drift30,drift90,drift180,n_coins FROM universe_drift "
                "WHERE day <= ? AND day >= ? ORDER BY day DESC LIMIT 1",
                (yesterday, oldest),
            ).fetchone()
            # 🔴 ПРОИЗВОДНАЯ d180 за 30 дней — «медведь выдыхается».
            # Слепой тест: slope ≥ +20 → OOS PF 4.75 против базы 1.22; в связке
            # с drift30 сильнее каждого по отдельности (корреляция всего +0.72).
            # Разворот цикла виден по РОСТУ дрейфа, а не по его знаку —
            # переключатель по УРОВНЮ проверен и провалился (0.79 против 1.22).
            slope = None
            if row is not None and row[3] is not None:
                prev = c.execute(
                    "SELECT drift180 FROM universe_drift WHERE day <= date(?, '-30 day') "
                    "AND drift180 IS NOT NULL ORDER BY day DESC LIMIT 1", (row[0],)
                ).fetchone()
                if prev is not None:
                    slope = float(row[3]) - float(prev[0])
    except sqlite3.Error as e:                       # таблицы ещё нет / БД занята
        logger.debug("[universe_drift] недоступен: %s", e)
        row = None

    val = None if row is None else {
        "day": row[0], "drift30": row[1], "drift90": row[2],
        "drift180": row[3], "n_coins": row[4], "slope180": slope,
    }
    if val is None:
        logger.debug("[universe_drift] нет свежего значения (нужен день <= %s)", yesterday)
    _cache.update(ts=now, val=val)
    return val


def in_short_zone() -> bool | None:
    """True/False — попадает ли текущий момент в зону, где short усилен. None — данных нет."""
    d = get_drift()
    if d is None or d.get("drift30") is None:
        return None
    return float(d["drift30"]) >= SHORT_ZONE_PCT


def features(direction: str = "") -> dict:
    """
    Поля для extra_features. ЧИСТО НАБЛЮДАТЕЛЬНЫЕ — решения не меняют.
    Пишем при каждом сигнале, чтобы через несколько недель сверить бой с замером.
    """
    d = get_drift()
    if d is None:
        return {"ud_ok": 0}
    out = {
        "ud_ok": 1,
        "ud_day": d["day"],
        "ud_d30": None if d["drift30"] is None else round(float(d["drift30"]), 2),
        "ud_d90": None if d["drift90"] is None else round(float(d["drift90"]), 2),
        "ud_d180": None if d["drift180"] is None else round(float(d["drift180"]), 2),
        "ud_coins": d["n_coins"],
    }
    sl = d.get("slope180")
    out["ud_slope"] = None if sl is None else round(float(sl), 2)
    if out["ud_d30"] is not None:
        out["ud_short_zone"] = int(out["ud_d30"] >= SHORT_ZONE_PCT)
    return out

def gate(direction: str, cfg=None, *, cfg_path: str = "trading.impulse_fib.drift_gate") -> tuple[bool, str]:
    """
    Дрейф-гейт: пропускать ли сигнал этого направления.

    Возвращает (пропустить, причина). Причина пишется в лог ВСЕГДА, даже при пропуске —
    закон проекта: молчаливых отказов быть не должно.

    🔴 БЕЗОПАСНОСТЬ ПО УМОЛЧАНИЮ: при любой неясности (нет конфига, нет данных,
    данные протухли, ошибка) гейт САМОУСТРАНЯЕТСЯ и пропускает сигнал. Стратегия
    не должна молча умирать из-за того, что наполнитель данных не отработал.
    """
    try:
        if cfg is None:
            from core.infra.config_loader import config as cfg
        g = cfg.get(cfg_path) or {}
        mode = str(g.get("mode", "off")).lower()
        if mode == "off":
            return True, "gate:off"
        sides = [str(x).lower() for x in (g.get("sides") or ["short"])]
        if str(direction).lower() not in sides:
            return True, f"gate:сторона {direction} не гейтится"

        d = get_drift(max_age_days=int(g.get("max_age_days", 3)))
        if d is None or d.get("drift30") is None:
            return True, "gate:НЕТ ДАННЫХ → пропускаю (fail-open)"

        thr = float(g.get("min_drift30", SHORT_ZONE_PCT))
        cur = float(d["drift30"])
        ok_d30 = cur >= thr
        # второе условие — производная. Если порог не задан или данных нет,
        # условие считается выполненным (fail-open): гейт не должен глушить
        # стратегию из-за отсутствующей истории.
        thr_sl = g.get("min_slope180")
        sl = d.get("slope180")
        if thr_sl is None or sl is None:
            ok_sl, sl_txt = True, ("производная —" if thr_sl is None else "производная нет данных")
        else:
            ok_sl = float(sl) >= float(thr_sl)
            sl_txt = f"производная={float(sl):+.1f} {'>=' if ok_sl else '<'} {float(thr_sl):+.1f}"
        ok = ok_d30 and ok_sl
        why = (f"drift30={cur:+.2f}% {'>=' if ok_d30 else '<'} {thr:+.1f}% · {sl_txt} "
               f"(день {d['day']}, монет {d['n_coins']})")
        if mode == "shadow":
            return True, f"gate:SHADOW {'пропустил бы' if ok else 'ЗАБЛОКИРОВАЛ БЫ'} — {why}"
        return ok, f"gate:{'пропуск' if ok else 'БЛОК'} — {why}"
    except Exception as e:                                   # noqa: BLE001
        logger.warning("[universe_drift] gate error → пропускаю: %s", e)
        return True, f"gate:ОШИБКА {type(e).__name__} → пропускаю (fail-open)"
