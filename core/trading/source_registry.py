"""
source_registry.py — ЕДИНЫЙ РЕЕСТР СВОЙСТВ ИСТОЧНИКОВ.

Повод (Егор, 21.08.2026): «нужна унификация таких фильтров как фильтр
PENDING-лайфцикла, чтобы не появлялось даже намёка на такие ошибки в будущем».

Что было: список источников с лимитным входом перечислялся ВРУЧНУЮ в SQL-шаблонах.
При добавлении `impulse_fib_15m` строка `LIKE '%"trade_mode": "impulse_fib"%'`
его НЕ поймала — шаблон требует закрывающую кавычку, а в JSON лежало
`"impulse_fib_15m"`. Лимитки нового источника не проверялись на фил и не
отменялись по TTL: висели бы вечно и молча забили кэп. Ошибка молчаливая,
в логах ни следа. Таких мест в коде нашлось 15.

Как теперь: свойство объявляется ОДИН раз в конфиге источника, а механизмы
спрашивают реестр. Добавление стратегии не требует правок в чужих файлах.

    from core.trading.source_registry import pending_sources, pending_sql, ttl_for

    where = pending_sql()               # готовое SQL-условие по всем таким источникам
    ttl   = ttl_for("impulse_fib_15m")  # TTL в секундах с учётом ТФ источника

Объявление в config.yaml (signal_router.source_policies.<источник>):
    entry_order_type: LIMIT     # уже используется — LIMIT включает лайфцикл
    entry_ttl_bars: 12          # опционально: сколько баров живёт лимитка
    entry_tf: 15m               # опционально: ТФ источника (для перевода баров в секунды)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Минуты в баре по имени ТФ — для перевода «баров» в секунды.
_TF_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
           "1h": 60, "2h": 120, "4h": 240, "1d": 1440}

# Запасные значения для источников, объявленных до появления реестра.
# 🔴 Новые источники сюда добавлять НЕ НУЖНО — объявляйте свойства в config.yaml.
# 🔴 22.08: у `impulse_fib_15m` было 12 баров = 3 ЧАСА, а его эдж измерен на окне
# фила 48 баров = 12 часов (замер `short15_full.py`: «WAIT_BARS, HOLD_BARS = 48, 384
# — ×4 к 1h, та же длительность»). Заявка снималась вчетверо раньше, чем в замере,
# то есть бой торговал не ту механику, которую проверяли.
_LEGACY_TTL_BARS = {"impulse_fib": 12, "impulse_fib_15m": 48, "choch_wavec": 12}
_LEGACY_TF = {"impulse_fib": "1h", "impulse_fib_15m": "15m", "choch_wavec": "1h"}


def _policies(cfg=None) -> dict:
    if cfg is None:
        from core.infra.config_loader import config as cfg
    return (cfg.get("signal_router.source_policies", {}) or {})


# Источники, чей pending-лайфцикл ведёт `radar_armed_loop._check_pending`.
# 🔴 Не «все с LIMIT»: у `rangefade`/`ds_advisor` своя обработка в их лупах,
# и включение их сюда дало бы ДВОЙНУЮ обработку одной заявки.
# Явный список безопаснее вывода по типу ордера — но он в ОДНОМ месте,
# а не размазан по SQL-шаблонам в пяти файлах.
_CENTRAL_LIFECYCLE = {"radar", "atr_s2", "impulse_fib", "impulse_fib_15m", "choch_wavec"}


def pending_sources(cfg=None) -> list[str]:
    """
    Источники, чей вход ЛИМИТНЫЙ и чей лайфцикл ведёт ЦЕНТРАЛЬНЫЙ механизм
    (проверка фила, отмена по TTL, восстановление стопа).

    Управление: `pending_lifecycle: true|false` в политике источника.
    Если поле не задано — берётся из списка `_CENTRAL_LIFECYCLE` (совместимость).

    🔑 Добавляя стратегию с LIMIT-входом: поставьте `pending_lifecycle: true`
    в её политике — и она подхватится ВЕЗДЕ автоматически. Никаких правок
    в чужих файлах и SQL-шаблонах.
    """
    out = []
    for src, pol in _policies(cfg).items():
        pol = pol or {}
        if str(pol.get("entry_order_type", "")).upper() != "LIMIT":
            continue
        flag = pol.get("pending_lifecycle")
        if flag is None:
            flag = src in _CENTRAL_LIFECYCLE
        if flag:
            out.append(str(src))
    return sorted(out)


def pending_sql(column: str = "signal_type", cfg=None) -> str:
    """
    SQL-условие «запись принадлежит источнику с лимитным входом».

    Строится по реестру, поэтому новый источник подхватывается САМ.

    🔴 22.08 (DEV-238): ключ переведён с `features_json LIKE '%"trade_mode": "X"%'`
    на колонку `signal_type`. LIKE по JSON ломается о суффиксы — шаблон `impulse_fib`
    не ловил `impulse_fib_15m`, и лимитки нового источника молча выпали из лайфцикла
    (ни проверки фила, ни отмены по TTL). Подтипы (`radar_pump` и др.) включены.
    Эквивалентность проверена на боевой базе: PENDING 5=5, OPEN 4=4, всего 630=630,
    расхождений 0. Значение по умолчанию `column` изменено вместе с ключом.

    Возвращает `(...)` или `(1=0)`, если таких источников нет.
    """
    srcs = pending_sources(cfg)
    if not srcs:
        return "(1=0)"
    if column == "features_json":     # явный вызов старым ключом — прежнее поведение
        parts = [f"{column} LIKE '%\"trade_mode\": \"{s}\"%'" for s in srcs]
        return "(" + " OR ".join(parts) + ")"
    names = [n for s in srcs for n in signal_types(s, cfg)]
    quoted = ",".join("'" + n.replace("'", "''") + "'" for n in names)
    return f"({column} IN ({quoted}))"


def ttl_for(trade_mode: str, default_sec: float = 1800.0, cfg=None) -> float:
    """
    Сколько секунд живёт лимитка источника.

    🔴 ТФ ОБЯЗАТЕЛЕН В РАСЧЁТЕ. `impulse_fib` и `impulse_fib_15m` имеют
    одинаковый WAIT_BARS=12, но это 12 ЧАСОВ и 3 ЧАСА соответственно.
    Ветка, знавшая только `impulse_fib`, дала бы пятнадцатиминутке TTL
    вчетверо длиннее окна, на котором мерилась механика.
    """
    if not trade_mode:
        return default_sec
    pol = (_policies(cfg).get(trade_mode) or {})
    bars = pol.get("entry_ttl_bars", _LEGACY_TTL_BARS.get(trade_mode))
    tf = str(pol.get("entry_tf", _LEGACY_TF.get(trade_mode, "1h")))
    if bars is None:
        return default_sec
    minutes = _TF_MIN.get(tf, 60)
    return float(bars) * minutes * 60.0


def subtypes(source: str, cfg=None) -> list[str]:
    """
    Подтипы источника — имена, которые он пишет в `signal_type`.

    🔴 22.08: у `radar` их ЧЕТЫРЕ (`radar_pump`, `radar_spring`, `radar_build`,
    `radar_build_flip`) при одном `trade_mode='radar'` и одной политике. Порог,
    вписанный под подтипом, роутер (ctx.source='radar') не увидел бы вовсе —
    та же мина, что `wt_sideways`, только на третьем имени.
    Объявляется в политике: `signal_subtypes: [radar_pump, ...]`.
    """
    pol = (_policies(cfg).get(source) or {})
    return [str(x) for x in (pol.get("signal_subtypes") or [])]


def signal_types(source: str, cfg=None) -> list[str]:
    """Все имена, под которыми источник встречается в `simulated_trades.signal_type`."""
    if not source:
        return []
    return [source] + [s for s in subtypes(source, cfg) if s != source]


def types_sql(source: str, column: str = "signal_type", cfg=None) -> tuple[str, list]:
    """
    Готовое SQL-условие «запись принадлежит источнику ИЛИ его подтипу».

    Заменяет `features_json LIKE '%"trade_mode": "radar"%'`: LIKE по JSON ломается
    о суффиксы (шаблон с закрывающей кавычкой не поймал `impulse_fib_15m` и лимитки
    молча выпали из лайфцикла) и читает поле, которого может не быть.
    Возвращает `(условие, параметры)` для подстановки в execute.
    """
    names = signal_types(source, cfg)
    if not names:
        return "(1=0)", []
    return f"{column} IN ({','.join('?' * len(names))})", names


def _aliases(name: str, cfg=None) -> list[str]:
    """
    Вторые имена источника: `source` ↔ `trade_mode` ↔ подтипы из его политики.

    У большинства источников имена совпадают, и алиасов нет. У `wt_sideways`
    они разные (`source=wt_sideways`, `trade_mode=sideways`) — именно там
    порог, вписанный под одним именем, был невидим половине кода.
    У `radar` третья форма: подтипы в `signal_type` (`radar_pump` и др.).
    """
    if not name:
        return []
    out = []
    for src, pol in _policies(cfg).items():
        pol = pol or {}
        tm = str(pol.get("trade_mode", "") or "")
        subs = [str(x) for x in (pol.get("signal_subtypes") or [])]
        if name == src:
            if tm and tm != src:
                out.append(tm)
            out.extend(s for s in subs if s != src)
        elif name == tm and src != tm:
            out.append(str(src))
            out.extend(s for s in subs if s != src)
        elif name in subs:
            # подтип знает и своего родителя, и его trade_mode
            out.append(str(src))
            if tm and tm != src:
                out.append(tm)
    return out


def threshold(per_key: str, global_key: str, source: str = "", trade_mode: str = "",
              *, cfg=None, fallback: float = 0.0, label: str = "") -> float:
    """
    Порог стратегии по ЛЮБОМУ из её двух имён — общий резолвер реестра.

    🔴 Повод (реестр, фаза 2): один и тот же порог читался в нескольких местах
    РАЗНЫМИ ключами и с РАЗНЫМИ запасными значениями:

        min_sl_dist  gates/min_sl_dist.py  ctx.source    запас 0.5
                     trade_simulator.py    trade_mode    запас 0.5
                     order_manager.py      source        запас 0.1  ← другой!
        min_rr       gates/rr_filter.py    ctx.source    запас 2.0
                     trade_simulator.py    trade_mode    запас 2.0

    Пока имена совпадают, расхождения не видно. У `wt_sideways` они уже разошлись
    (source=`wt_sideways`, trade_mode=`sideways`): впиши порог под одним именем —
    и половина мест его не увидит, сигнал пройдёт роутер и молча умрёт дальше.
    Ровно так impulse_fib потерял 8 сигналов из 8 (memory/bug_gate_lives_in_two_places),
    а min_rr=2.0 однажды убил rangefade целиком (memory/bug_rr_gate_killed_tp1r_edge).

    Порядок: `source` → `trade_mode` → синоним по реестру → глобальный ключ.
    """
    if cfg is None:
        try:
            from core.infra.config_loader import config as cfg
        except Exception:                                    # noqa: BLE001
            return fallback
    hit = per_strategy(per_key, source, trade_mode, cfg=cfg, label=label)
    if hit is not None:
        return hit
    try:
        return float(cfg.get(f"trading.{global_key}", fallback))
    except Exception:                                        # noqa: BLE001
        return fallback


def per_strategy(per_key: str, source: str = "", trade_mode: str = "", *, cfg=None,
                 label: str = "") -> float | None:
    """
    Персональное значение источника из `trading.<per_key>` или None, если не объявлено.

    Отдельно от `threshold`, потому что не у каждой настройки есть глобальный
    напарник: у TSL персональный порог перекрывает РЕЖИМНЫЙ (RANGE), а не
    глобальный, и подмена одного другим сменила бы боевое поведение.
    """
    if cfg is None:
        try:
            from core.infra.config_loader import config as cfg
        except Exception:                                    # noqa: BLE001
            return None
    try:
        per = cfg.get(f"trading.{per_key}", {}) or {}
        if not isinstance(per, dict):
            return None
        hit_src = per.get(source) if source else None
        hit_tm = per.get(trade_mode) if trade_mode else None
        if hit_src is not None and hit_tm is not None and float(hit_src) != float(hit_tm):
            # Оба имени в таблице, но с РАЗНЫМИ значениями — это конфликт объявления,
            # а не рабочая настройка. Побеждает `source`, но молчать об этом нельзя.
            logger.warning(
                "[registry] %s: конфликт объявления — source=%s→%.2f, "
                "trade_mode=%s→%.2f. Применяю %.2f (по source)",
                label or per_key, source, float(hit_src), trade_mode,
                float(hit_tm), float(hit_src),
            )
        if hit_src is not None:
            return float(hit_src)
        if hit_tm is not None:
            return float(hit_tm)
        # Ни одно из переданных имён не нашлось. Последняя попытка — СИНОНИМ по реестру:
        # зовущий мог знать только одно имя пары (source ↔ trade_mode), а значение вписано
        # под другим. Без этого шага order_manager, которому известен только `source`,
        # не увидел бы порог, объявленный как `sideways`.
        for name in (source, trade_mode):
            for alias in _aliases(name, cfg):
                if alias in per:
                    return float(per[alias])
        return None
    except Exception:                                        # noqa: BLE001
        return None


def min_sl_dist_pct(source: str = "", trade_mode: str = "", *, cfg=None,
                    fallback: float = 0.5) -> float:
    """Минимальная дистанция стопа источника (%). См. `threshold`."""
    return threshold("min_sl_dist_per_strategy", "min_sl_dist_pct",
                     source, trade_mode, cfg=cfg, fallback=fallback, label="min_sl_dist")


def min_rr(source: str = "", trade_mode: str = "", *, cfg=None,
           fallback: float = 2.0) -> float:
    """
    Минимальный RR источника. См. `threshold`.

    🔴 Порог, который однажды убил стратегию целиком: у rangefade цель = 1R
    ПО КОНСТРУКЦИИ, глобальный 2.0 резал ВСЕ его сигналы, и форвард молча дал ноль
    сделок (memory/bug_rr_gate_killed_tp1r_edge).
    """
    return threshold("min_rr_per_strategy", "min_rr_ratio",
                     source, trade_mode, cfg=cfg, fallback=fallback, label="min_rr")


def in_list(cfg_key: str, source: str = "", trade_mode: str = "", *, cfg=None,
            default: list | None = None) -> bool:
    """
    Числится ли источник в списочной настройке (`single_tp_sources`, `rr_cap_exempt`).

    🔴 Та же мина, что у порогов, только в форме списка: проверка идёт по ОДНОМУ
    имени (`signal_type_override`), а вписать в конфиг могли другое. Плюс запасные
    списки хардкодом в коде разъезжаются с конфигом — `["ote_nested","impulse_fib"]`
    не содержит `impulse_fib_15m`, хотя в конфиге он есть. Источник, потерявший
    режим SINGLE, перестаёт распознавать достижение цели вовсе: DUAL_TP заполняет
    tp1_price, а детект в sim_exit требует tp1_price IS NULL (KAIA #58367 — выход
    по рынку 0.02566 вместо цели 0.031).

    Матчим по обоим именам источника и по синонимам реестра.
    """
    if cfg is None:
        try:
            from core.infra.config_loader import config as cfg
        except Exception:                                    # noqa: BLE001
            return bool(default) and (source in (default or []) or trade_mode in (default or []))
    try:
        lst = cfg.get(cfg_key)
        if not lst:
            lst = list(default or [])
        lst = [str(x) for x in lst]
        for name in (source, trade_mode):
            if name and (str(name) in lst or any(a in lst for a in _aliases(name, cfg))):
                return True
        return False
    except Exception:                                        # noqa: BLE001
        lst = [str(x) for x in (default or [])]
        return str(source) in lst or str(trade_mode) in lst


def tf_for(source: str, cfg=None, default: str = "") -> str:
    """
    Таймфрейм источника — для отображения и разборов.

    🔴 22.08: дашборд показывал ТФ КАЖДОЙ биржевой позиции как «15m», потому что
    фронт брал `tsl_tf || "15m"`, а `tsl_tf` заполняется только при активном трейлинге.
    У impulse_fib (1h) трейлинг выключен по конструкции → у всех его позиций
    печатался чужой ТФ. Источник правды один — реестр.
    """
    if not source:
        return default
    pol = (_policies(cfg).get(source) or {})
    return str(pol.get("entry_tf") or _LEGACY_TF.get(source, default) or default)


def slots(conn, trade_mode: str, *, max_open: int, max_pending: int | None = None,
          table: str = "simulated_trades") -> dict:
    """
    Сколько занято слотов РИСКА и слотов МАРЖИ по источнику.

    🔴 ЭТО ДВА РАЗНЫХ ЛИМИТА, и в одном счётчике их держать нельзя.
    Повод (Егор, 22.08.2026): «неактуальные лимитки не слишком ли долго висят?»
    Оказалось, висят ровно измеренные 12 баров — но занимают не своё место.

        max_open     сколько ПОЗИЦИЙ в рынке        — рыночный риск
        max_pending  сколько ЗАЯВОК ждёт фила       — резерв маржи

    Ожидающая лимитка НЕ в рынке: она не может ни выиграть, ни проиграть,
    рыночного риска не несёт. Расходует она другое — маржу под резерв.
    Считая её слотом риска, мы запрещали вход из-за расхода, которого нет:
    22.08 восемь заявок держали кэп 8/8 при НОЛЕ позиций на бирже, и 1h-луп
    восемь часов писал «скан 250 пар · новых 0».

    Замер (45 символов, 2024+, боевые константы): лимитка наполняется в 20.1%
    случаев. Значит на одну позицию приходится ~5 заявок — при равенстве
    лимитов поток задушен арифметикой, а не гейтами.

    Возвращает {'open','pending','can_place','why'}. `can_place` — можно ли
    выставить ЕЩЁ ОДНУ заявку; `why` объясняет отказ (закон: молчаливых отказов нет).
    """
    n_open = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE signal_type=? AND status='OPEN'",
        (trade_mode,)).fetchone()[0]
    n_pend = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE signal_type=? AND status='PENDING_ENTRY'",
        (trade_mode,)).fetchone()[0]
    if max_pending is None:                 # не объявлен — вдвое от риска
        max_pending = int(max_open) * 2
    why = ""
    if n_open >= int(max_open):
        why = f"позиций {n_open}/{max_open} — рынок полон"
    elif n_pend >= int(max_pending):
        why = f"заявок {n_pend}/{max_pending} — резерв маржи исчерпан"
    return {"open": n_open, "pending": n_pend, "can_place": not why, "why": why}


def describe(cfg=None) -> str:
    """Человекочитаемая карта — для preflight и диагностики."""
    rows = ["источник           тип входа   TTL лимитки"]
    for src, pol in sorted(_policies(cfg).items()):
        typ = str((pol or {}).get("entry_order_type", "MARKET")).upper()
        if typ != "LIMIT":
            continue
        ttl = ttl_for(src, cfg=cfg)
        rows.append(f"  {src:<18} {typ:<11} {ttl/3600:.1f} ч")
    return "\n".join(rows) if len(rows) > 1 else "источников с лимитным входом нет"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    sys.stdout.reconfigure(encoding="utf-8")
    print(describe())
    print("\nSQL-условие:\n ", pending_sql())
