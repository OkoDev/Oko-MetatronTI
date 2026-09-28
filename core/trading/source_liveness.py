"""ЖИВОСТЬ ИСТОЧНИКОВ: совпадает ли «числится торгующим» с «действительно торгует».

🔴 Повод (Егор 28.09: «конфиг должен быть источником истинности»). За 26–28.09 один класс
сломал пять механизмов, и ни один прибор этого не показал, потому что молчание источника
выглядит как «сигналов не было»:

  · `atr_s2`      — `exchange_enabled: true`, НОЛЬ сделок за всё время: ветка в scan_loop
                    висит на `tf == "4h"`, а entry-ТФ сканера = ['15m'] → путь недостижим;
  · `ds_advisor`  — включён, но все сигналы режет `min_sl_dist` (3 136 отказов за сутки
                    при его среднем стопе 1.9% против глобального порога 4.0%);
  · `ote_nested`  — выключен ключом `ote.vst_trading.enabled`, а в политике остался `true`;
  · гейт радара   — написан, но колонка не выбиралась из БД: 0 срабатываний из 41 924;
  · `impulse_fib` — окно фила в коде, TTL живой заявки в реестре — два разных числа.

Отсюда правило: **ноль сделок при режиме `live` — это тревога, а не тишина.**

Модуль ничего не чинит и никуда не пишет: только сверяет конфиг с фактами БД и отдаёт строки
для отчёта. Вызывается из core/selftest.py (L13) при старте бота.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

SILENT_DAYS = 7          # столько суток без сделок при режиме live = тревога
STALE_DAYS = 3           # последняя сделка старше — предупреждение


@dataclass
class SourceState:
    src: str
    mode: str                      # live | shadow | off
    trades: int = 0                # сделок за окно
    last_trade: str | None = None  # дата последней сделки за всё время
    traces: int = 0                # следов источника в логе (его луп что-то делал)
    needs: str = ""                # требования источника (ТФ/стороны) из политики
    min_sl_dist: float | None = None
    min_rr: float | None = None
    ttl_h: float | None = None
    verdict: str = ""              # ok | МОЛЧИТ | ПУТЬ НЕ НАЙДЕН | —
    note: str = ""


# Тег, которым источник помечает свои строки в логе. Нужен, чтобы отличить ДВА РАЗНЫХ молчания:
#   есть следы, нет сделок → путь живой, режет порог или рынок не даёт сетапов (это норма);
#   НЕТ следов и нет сделок → путь в коде недостижим (так умер atr_s2 — ветка ждала 4h,
#   а сканер давал 15m; за всё время ни одной сделки и ни одной строки от боевой ветки).
LOG_TAGS: dict[str, tuple[str, ...]] = {
    "choch_wavec": ("[CHOCH-C]",),
    "choch_wavec_4h": ("[CHOCH-C4]",),
    "impulse_fib": ("[IMPULSE]",),
    "impulse_fib_15m": ("[IMPULSE15]",),
    "radar": ("[RADAR-ARMED]",),
    "rangefade": ("[RANGEFADE]",),
    "rangefade4h": ("[RANGEFADE]",),
    "bigflush15": ("[RANGEFADE]",),
    "ds_advisor": ("[DS-ADVISOR]",),
    "atr_s2": ("[ATR-S2]",),
    "waves_long": ("[WAVES_LONG]",),
    "ote_nested": ("[OTE-OBS]", "[OTE]"),
}


def _count_traces(src: str, log_path: str | None, tail_lines: int = 60_000) -> int:
    """Сколько строк источник оставил в хвосте лога. 0 при недоступном логе — тогда
    колонка просто не участвует в вердикте (лучше не знать, чем соврать)."""
    tags = LOG_TAGS.get(src)
    if not tags or not log_path:
        return -1
    try:
        from collections import deque
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            tail = deque(f, maxlen=tail_lines)
        return sum(1 for ln in tail if any(t in ln for t in tags))
    except Exception:                                       # noqa: BLE001
        return -1


def _mode_of(cfg, src: str) -> str:
    """Режим источника — ЧЕРЕЗ ЕДИНЫЙ РЕЗОЛВЕР (source_registry.mode_of).

    🔴 Своей копии этой логики здесь быть не должно: прибор, который сам решает, что значит
    «включён», — это ещё один источник истины, то есть ровно та болезнь, которую он измеряет
    ([[principle_reuse_not_duplication]]).
    """
    try:
        from core.trading.source_registry import mode_of
        return mode_of(src, cfg=cfg, warn=False)
    except Exception:                                       # noqa: BLE001
        pol = (cfg.get(f"signal_router.source_policies.{src}", {}) or {})
        return "live" if pol.get("exchange_enabled") else ("off" if pol else "—")


def _names(src: str, cfg) -> list[str]:
    """Имена, под которыми источник пишется в signal_type (у радара их четыре)."""
    try:
        from core.trading.source_registry import subtypes
        subs = subtypes(src, cfg=cfg) or []
    except Exception:                                       # noqa: BLE001
        subs = []
    return sorted({src, *subs})



def _requirements_ok(src: str, pol: dict, cfg) -> tuple[bool, str]:
    """Совместимы ли объявленные требования источника с конфигурацией сканера.

    🔴 Ради этого пункт и делался: `atr_s2` требовал 4h, сканер давал 15m — источник числился
    торгующим и молчал МЕСЯЦАМИ. Теперь несовпадение видно сразу при старте, не дожидаясь,
    пока накопится неделя тишины ([[config_is_single_source_of_truth]]).
    Требование объявляется в политике как `requires_entry_tf`.
    """
    need_tf = str(pol.get("requires_entry_tf") or "").strip()
    if not need_tf:
        return True, ""
    try:
        from core.infra.entry_config import get_entry_timeframes
        tfs = [str(x) for x in (get_entry_timeframes(cfg) or [])]
    except Exception:                                       # noqa: BLE001
        return True, f"нужен {need_tf} (список ТФ сканера не прочитан)"
    if need_tf in tfs:
        return True, f"нужен {need_tf} — есть"
    return False, f"нужен ТФ {need_tf}, а сканер даёт {tfs or '—'}"


def collect(db_path: str, cfg, days: int = SILENT_DAYS, log_path: str | None = None) -> list[SourceState]:
    """Состояние всех источников из политики роутера. Ничего не меняет."""
    pols = (cfg.get("signal_router.source_policies", {}) or {})
    out: list[SourceState] = []
    try:
        conn = sqlite3.connect(db_path, timeout=10)
    except Exception as e:                                  # noqa: BLE001
        logger.warning("[LIVENESS] БД недоступна: %s", e)
        return out
    try:
        for src in sorted(pols):
            st = SourceState(src=src, mode=_mode_of(cfg, src))
            names = _names(src, cfg)
            q = ",".join("?" * len(names))
            try:
                st.trades = conn.execute(
                    f"SELECT COUNT(*) FROM simulated_trades WHERE signal_type IN ({q}) "
                    f"AND created_at >= datetime('now', '-{int(days)} days')", names).fetchone()[0]
                row = conn.execute(
                    f"SELECT MAX(created_at) FROM simulated_trades WHERE signal_type IN ({q})",
                    names).fetchone()
                st.last_trade = (row[0] or "")[:10] or None
            except Exception as e:                          # noqa: BLE001
                st.note = f"БД: {type(e).__name__}"
            try:
                from core.trading.source_registry import min_rr, min_sl_dist_pct, ttl_for
                st.min_sl_dist = min_sl_dist_pct(src, cfg=cfg)
                st.min_rr = min_rr(src, cfg=cfg)
                st.ttl_h = round(ttl_for(src, cfg=cfg) / 3600, 1)
            except Exception:                               # noqa: BLE001
                pass
            st.traces = _count_traces(src, log_path)
            _ok_req, st.needs = _requirements_ok(src, (pols.get(src) or {}), cfg)
            if st.mode == "live" and not _ok_req:
                st.verdict = "ПУТЬ НЕ НАЙДЕН"
                st.note = st.needs
            elif st.mode == "live":
                if st.trades == 0:
                    # ключевое различение: есть следы лупа или нет
                    if st.traces == 0:
                        st.verdict = "ПУТЬ НЕ НАЙДЕН"
                        st.note = "нет ни сделок, ни следов в логе — ветка в коде недостижима?"
                    else:
                        st.verdict = "МОЛЧИТ"
                        st.note = st.note or (f"нет сделок {days} сут"
                                              + (f", последняя {st.last_trade}" if st.last_trade else ", НИ ОДНОЙ за всё время")
                                              + (f"; следов в логе {st.traces} → путь жив, режет порог или нет сетапов"
                                                 if st.traces > 0 else ""))
                else:
                    st.verdict = "ok"
            else:
                st.verdict = "—"
            out.append(st)
    finally:
        conn.close()
    return out


def format_table(rows: list[SourceState], days: int = SILENT_DAYS) -> str:
    """Таблица для лога: источник · режим · сделок · последняя · пороги · вердикт."""
    if not rows:
        return "[LIVENESS] нет данных"
    head = (f"{'источник':<18}{'режим':<8}{f'сделок {days}д':>12}{'последняя':>12}"
            f"{'следов':>8}{'min_sl':>8}{'min_rr':>8}{'TTL ч':>7}  вердикт")
    lines = [head, "-" * len(head)]
    for r in sorted(rows, key=lambda x: (x.mode != "live", x.src)):
        mark = {"МОЛЧИТ": "🟡", "ПУТЬ НЕ НАЙДЕН": "🔴", "ok": "✅"}.get(r.verdict, "  ")
        lines.append(
            f"{r.src:<18}{r.mode:<8}{r.trades:>12}{(r.last_trade or '—'):>12}"
            f"{(r.traces if r.traces >= 0 else '—'):>8}"
            f"{(r.min_sl_dist if r.min_sl_dist is not None else '—'):>8}"
            f"{(r.min_rr if r.min_rr is not None else '—'):>8}"
            f"{(r.ttl_h if r.ttl_h is not None else '—'):>7}  {mark} {r.verdict}"
            + (f" · {r.note}" if r.note else ""))
    dead = [r for r in rows if r.verdict == "ПУТЬ НЕ НАЙДЕН"]
    silent = [r for r in rows if r.verdict == "МОЛЧИТ"]
    lines.append("")
    if dead:
        lines.append(f"🔴 ТРЕВОГА: {len(dead)} источник(ов) числятся торгующими, но НЕ ОСТАВИЛИ СЛЕДОВ: "
                     + ", ".join(r.src for r in dead))
        lines.append("   Это профиль atr_s2: ветка в коде недостижима (ТФ/сторона/вселенная не совпали). "
                     "Проверять код, а не рынок.")
    if silent:
        lines.append(f"🟡 МОЛЧАТ (путь жив, сделок нет): " + ", ".join(r.src for r in silent))
        lines.append("   Смотреть отказы в логе: порог (min_sl_dist/min_rr/TTL) или рынок не даёт сетапов.")
    if not dead and not silent:
        lines.append("✅ все live-источники дают сделки")
    return "\n".join(lines)


if __name__ == "__main__":                                   # ручной прогон между рестартами
    import os
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    logging.disable(logging.CRITICAL)
    from core.infra.config_loader import config as _cfg
    _days = int(_sys.argv[1]) if len(_sys.argv) > 1 else SILENT_DAYS
    _log = os.path.expanduser("~/.pm2/logs/oko-bot-out.log")
    _rows = collect("subscriptions.db", _cfg, days=_days, log_path=_log if os.path.exists(_log) else None)
    print(format_table([r for r in _rows if r.mode != "off"] or _rows, _days))
