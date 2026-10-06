---
name: bug-gate-lives-in-two-places
description: "🔴 ГЕЙТ ЖИВЁТ В ТРЁХ МЕСТАХ: min_sl_dist per-strategy работал только в роутере — trade_simulator и order_manager читали глобальный 4.0% → impulse_fib (стоп 1.5-3.2%) резался молча, 0 сделок. Третью копию скрыл АНГЛИЙСКИЙ текст ошибки. Тот же баг бил rangefade"
metadata:
  node_type: memory
  type: project
  originSessionId: 696399f2-16be-4ffc-97be-acad52cc3fb5
  modified: 2026-08-20T10:50:04.251Z
---

# 🔴 ГЕЙТ ЖИВЁТ В ДВУХ МЕСТАХ — ПРОВЕРЯТЬ ОБА (20.08.2026)

## Что случилось
`impulse_fib` включён в бой, луп отработал, 8 сигналов залогированы. В БД — **НОЛЬ сделок**.
Ни строки `[TradeRouter]`, ни ошибки. Причина нашлась только по логу симулятора:

```
TradeSimulator: [DEV-157/164] пропуск LONG SOL/USDT — SL слишком близко: 1.9291% < 4.00%
```

Порог `trading.min_sl_dist_per_strategy.impulse_fib: 1.4` был прописан и РАБОТАЛ —
но только в router-гейте `core/trading/gates/min_sl_dist.py`. Вторая копия проверки живёт
в `core/trading/trade_simulator.py` и читала **только глобальный** `min_sl_dist_pct` (4.0).
Сигнал проходил роутер и умирал на последнем шаге.

Самое злое: рядом, в том же файле и в той же функции, RR-фильтр УЖЕ умел per-strategy
(`_per_rr[trade_mode]`). Асимметрия двух соседних проверок и создала слепое пятно.

## Фикс
`trade_simulator.py`: per-strategy override для `min_sl_dist`, по образцу RR-фильтра.
Бэкап `trade_simulator.py.bak.20260820_*`.

## 🔑 Побочно вскрылось: тот же баг бил и другие источники
`rangefade`/`rangefade4h` имеют порог **0.25** в per_strategy — он не действовал в
симуляторе, и их сигналы со стопом <4% резались так же молча. Сколько сделок потеряно —
не считал, но источник числился «не торгует».

## 🔴 КОПИЙ ОКАЗАЛОСЬ ТРИ, И ТРЕТЬЮ СКРЫЛ ЯЗЫК
Починив две, я объявил проблему закрытой — и следующий же скан дал `exch=none`.
Третья копия в `core/exchange/order_manager.py::open_bracket` пишет **по-английски**:
`DEV-164 SL too close`, а я грепал русское «SL слишком близко». Фикс: `OrderRequest.source`
прокинут до `open_bracket` (router → adapter → order_manager), там per-strategy override.

## ЗАКОН
**Порог в конфиге ≠ порог в бою.** Прежде чем включать источник, найти ВСЕ места, где
читается ограничение, и убедиться, что per-strategy применяется в каждом:
```bash
grep -rn "min_sl_dist\|SL too close\|слишком близко" --include=*.py core/ bot/
```
🔑 Грепать по ИМЕНИ КЛЮЧА и КОДУ ошибки (`DEV-164`), а НЕ по тексту сообщения: копии
проверки пишут на разных языках. Признак опасности: у соседней проверки в том же файле
per-strategy есть, а у этой нет.

Третий случай этого класса ([[bug_source_policies_deadpath_router_off]] — router off →
старый путь без гейта; [[bug_rr_gate_killed_tp1r_edge]] — min_rr=2.0 убил rangefade).
Общее: **конфиг говорит одно, активный путь читает другое, отказ не логируется как отказ.**

## Смежная находка того же дня
Кэп позиций в лупе считался по ИССЛЕДОВАТЕЛЬСКОМУ журналу (`impulse_shadow`), а не по
реальным сделкам. 8 записей WAITING, которых на бирже не существовало, держали все слоты →
следующие сканы давали «новых 0». Исправлено: в живом режиме кэп по `simulated_trades`.

Связано: [[impulse_fib_cell_live]], [[bug_rr_gate_killed_tp1r_edge]],
[[bug_source_policies_deadpath_router_off]].
