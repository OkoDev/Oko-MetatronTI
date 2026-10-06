---
name: sim_deprioritize_loop
description: "SIM-DEPRIO — в VST/LIVE 61% бюджета loop тратится на sim_only фантомы; throttle их 60с→300с, приоритет биржевым. Часть SCALABILITY/EXEC-WS вектора"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**⚠️ ПОГЛОЩЁН эпиком [[exec_sim_split_epic]] (14.06): юзер решил радикальнее — sim вообще УХОДИТ из main в strip, а не throttle. SIM-DEPRIO остаётся как запасной быстрый вариант, если split отложат.**

**SIM-DEPRIO (юзер 14.06: «реже SIM, освободить loop, приоритет бирже»).**

**Корень:** `check_open_trades_with_tsl._proc` ([[trade_simulator]] :1816) гоняет ВСЕ открытые сделки — биржевые И sim_only — в одном `Semaphore(15)`. Они конкурируют за единый бюджет REST/loop.

**Данные 14.06 (312 OPEN):** sim_only **189 (61%)** ∥ биржевые 123 ∥ TSL-активных всего **4**. → 61% бюджета loop уходит на фантомы (margin-reject SIM-only — биржа их не взяла, RISK 95%, симулятор всё равно записал). Реально требуют частого внимания единицы: 4 TSL (бот двигает стоп) + биржевые (но у них SL/TP уже НА БИРЖЕ → биржа исполнит сама).

**Решение (throttle, паттерн уже есть — DS-322 `_repair_checked` 3600с, DEV-227 `_force_rest_ts` 150с):**
```python
if not _exchange_managed_trade:  # _exch_id отсутствует или == "SIM"
    if _now_ts - self._sim_checked.get(trade_id, 0) < SIM_CHECK_INTERVAL:  # config 300с
        return (_ops05c, _ops05tsl)
    self._sim_checked[trade_id] = _now_ts
```
За флагом `performance.sim_check_interval_sec`. Эффект: ~38 вместо 189 sim/цикл → бюджет биржевым.

**Нюанс:** sim-закрытие с задержкой ≤5мин (статистика, не деньги — ок). Биржевые (деньги) только выигрывают.

**Статус:** 🟡 спроектировано, код в TASKS:SIM-DEPRIO. Юзер 14.06 выбрал «применить ПОСЛЕ ночного прогона / утром» (не трогать идущий сбор данных на 6 config-параметрах + min_rr ote=3.0). Чек перед коммитом: runtime на копии БД (критичный путь `_proc`, [[feedback_ast_parse_no_scope]]).

**Принцип (две оси, не путать):**
1. *Исполнение SL/TP*: биржевые → биржа+WS ([[exec_ws_vst_userdata_proven]]) event-driven (узнать о срабатывании), sim_only → только polling (биржа не знает).
2. *Приоритет ресурса loop* (эта задача): биржевые (деньги) важнее → им бюджет; sim_only (фантомы) → реже, задержка не жалко.

Полное решение = [[exec_ws_vst_userdata_proven]]: биржевые вообще уходят из polling (executionReport), sim → редкий throttle. Часть EPIC SCALABILITY (нагрузка loop = блокер «+1 юзер»). Чистота данных: 27719 сделок в БД, но sim_only фантомы от margin-reject = «мусорная» подвыборка → помечать через `execution_mode` [[arch_db_v2_terminal]].
