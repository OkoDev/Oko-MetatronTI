"""
mechanic_passport.py — паспорта механик: ЧИСЛА обновляются сами, смысл пишется руками.

Зачем (Егор 02.10): «проект растёт и нельзя терять даже мелких деталей». Решение об отключении
механики должно опираться на ДОКУМЕНТ с историей замеров и заранее записанным критерием, а не на
последний прогон. Паспорт живёт в `obsidian/Mechanics/<источник>.md`.

Устройство. Скрипт переписывает ТОЛЬКО блок между маркерами:
    <!-- АВТО:начало --> … <!-- АВТО:конец -->
Всё остальное (карта слоёв L0–L5, критерий отключения, история дефектов, журнал решений) —
рукописное и не затрагивается. Нет файла — создаётся из шаблона.

    python scripts/mechanic_passport.py              # все источники из конфига с историей
    python scripts/mechanic_passport.py radar impulse_fib
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "obsidian" / "Mechanics"
A0, A1 = "<!-- АВТО:начало -->", "<!-- АВТО:конец -->"
CLOSED = ("TP", "SL", "TSL", "EXPIRED")


def _cfg() -> dict:
    c = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    return (c.get("signal_router") or {}).get("source_policies") or {}


def _net(rows: list[tuple]) -> dict | None:
    """Чистый % (ЗАКОН №1): profit_pct − издержки. Медиана и хрупкость — обязательны (§2B)."""
    xs = [p - (c if c is not None else 0.09) for p, c in rows if p is not None]
    if not xs:
        return None
    s = sorted(xs)
    k = max(1, len(xs) // 10)
    return {"n": len(xs), "ср": sum(xs) / len(xs), "мед": s[len(s) // 2],
            "wr": sum(x > 0 for x in xs) / len(xs) * 100, "сумма": sum(xs),
            "безтоп10": sum(s[:-k])}


def auto_block(src: str, pol: dict, db: sqlite3.Connection) -> str:
    q = db.execute
    n_all = q("SELECT COUNT(*) FROM simulated_trades WHERE source_router=?", (src,)).fetchone()[0]
    rows = q("SELECT profit_pct, costs_pct FROM simulated_trades WHERE source_router=? "
             f"AND status IN ({','.join('?' * len(CLOSED))})", (src, *CLOSED)).fetchall()
    st = _net(rows)
    by_st = q("SELECT status, COUNT(*) FROM simulated_trades WHERE source_router=? GROUP BY 1 "
              "ORDER BY 2 DESC", (src,)).fetchall()
    first, last = q("SELECT MIN(created_at), MAX(created_at) FROM simulated_trades "
                    "WHERE source_router=?", (src,)).fetchone()
    by_month = q("SELECT substr(created_at,1,7), COUNT(*), "
                 "ROUND(AVG(profit_pct-COALESCE(costs_pct,0.09)),2) FROM simulated_trades "
                 f"WHERE source_router=? AND status IN ({','.join('?' * len(CLOSED))}) "
                 "GROUP BY 1 ORDER BY 1", (src, *CLOSED)).fetchall()

    L = [A0, f"<!-- обновлено {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
              f"скриптом scripts/mechanic_passport.py — руками не править -->", ""]
    L.append("### Конфигурация (из `config.yaml`, источник истины)")
    L.append("")
    keys = ("mode", "exchange_enabled", "min_strength", "entry_order_type", "entry_ttl_bars",
            "entry_tf", "max_open", "max_pending", "trade_mode", "risk_pct", "leverage")
    L.append("| ключ | значение |")
    L.append("|---|---|")
    for k in keys:
        if k in pol:
            L.append(f"| `{k}` | `{pol[k]}` |")
    L.append("")
    L.append("### Поток и сделки (журнал бота)")
    L.append("")
    L.append(f"- сделок всего: **{n_all}**" + (f" · окно {str(first)[:10]} → {str(last)[:10]}" if first else ""))
    L.append("- по статусам: " + (" · ".join(f"{s} {c}" for s, c in by_st) or "—"))
    if st:
        L.append(f"- закрытых **{st['n']}**: ср **{st['ср']:+.2f}%** · медиана **{st['мед']:+.2f}%** · "
                 f"WR {st['wr']:.0f}% · сумма **{st['сумма']:+.1f}%** · без верхних 10% **{st['безтоп10']:+.1f}%**")
        if st["сумма"] > 0 and st["безтоп10"] < 0:
            L.append("  - 🔴 **плюс держится хвостом**: без верхних 10% сумма отрицательна (§2B протокола)")
    else:
        L.append("- закрытых сделок нет — судить не по чему")
    if by_month:
        L.append("- по месяцам (закрытые, ср чистый %): " +
                 " · ".join(f"{m} n={n} {a:+.2f}%" for m, n, a in by_month))
    L.append("")
    L.append("> Это ФАКТ журнала, а не вердикт: журнал смешивает слои L1–L5 (скилл `research-verdict` §0). "
             "Для вывода о слое нужен его стенд.")
    L.append(A1)
    return "\n".join(L)


TEMPLATE = """---
tags: [mechanic, passport]
type: mechanic-passport
source: {src}
parent: "[[Project-MOC]]"
related: ["[[Mechanics]]"]
---

# Паспорт механики: `{src}`

> Решение о включении/отключении ссылается на ЭТОТ документ, а не на последний прогон.
> Числа в авто-блоке обновляет `scripts/mechanic_passport.py`. Остальное — руками, не перезаписывается.

{auto}

## Карта слоёв (скилл `research-verdict` §0)

| Слой | Конфигурация сейчас | Мерен? | Результат |
|---|---|---|---|
| **L0 поток** | — | ❓ НЕ МЕРЕН | |
| **L1 сигнал** | — | ❓ НЕ МЕРЕН | `python scripts/signal_info.py --source trades:{src}` |
| **L2 геометрия входа** | — | ❓ НЕ МЕРЕН | |
| **L3 управление** | — | ❓ НЕ МЕРЕН | |
| **L4 исполнение** | — | ❓ НЕ МЕРЕН | |
| **L5 портфель** | — | ❓ НЕ МЕРЕН | |

## Критерий отключения (пререгистрирован ДО замеров)

_Записать ЗАРАНЕЕ, иначе решение подгонится под результат._ Например: «отключается, если медиана Δ
форварда L1 накрывает ноль при n ≥ 2000 в двух и более режимах рынка».

**Критерий:** _не записан_

## Покрытие режимов

| Режим | Пройден? |
|---|---|
| флэт BTC + дрейф альтов (2026) | |
| растущий рынок | |
| медвежий рынок | |

## История замеров и дефектов инструмента

| Дата | Слой | Скрипт / отчёт | Результат | Дефект инструмента |
|---|---|---|---|---|

## Журнал решений

| Дата | Статус | Слой-адресат | Основание | Кто решил |
|---|---|---|---|---|
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pol_all = _cfg()
    db = sqlite3.connect(f"file:{ROOT / 'subscriptions.db'}?mode=ro", uri=True, timeout=20)
    names = sys.argv[1:]
    if not names:
        names = [s for s in pol_all
                 if db.execute("SELECT COUNT(*) FROM simulated_trades WHERE source_router=?",
                               (s,)).fetchone()[0] > 0
                 or pol_all[s].get("exchange_enabled")]
    OUT.mkdir(parents=True, exist_ok=True)
    for src in sorted(names):
        block = auto_block(src, pol_all.get(src, {}), db)
        f = OUT / f"{src}.md"
        if f.exists():
            t = f.read_text(encoding="utf-8")
            if A0 in t and A1 in t:
                t = t[:t.index(A0)] + block + t[t.index(A1) + len(A1):]
            else:
                t = t.rstrip() + "\n\n" + block + "\n"
            f.write_text(t, encoding="utf-8")
            print(f"  обновлён: {f.name}")
        else:
            f.write_text(TEMPLATE.format(src=src, auto=block), encoding="utf-8")
            print(f"  создан:   {f.name}")
    print(f"\nпаспортов в {OUT.relative_to(ROOT)}: {len(list(OUT.glob('*.md')))}")


if __name__ == "__main__":
    main()
