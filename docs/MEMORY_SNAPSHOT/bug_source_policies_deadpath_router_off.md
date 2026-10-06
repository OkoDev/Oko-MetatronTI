---
name: bug_source_policies_deadpath_router_off
description: "КРИТ-урок 25.07 — source_policies.exchange_enabled гейтит ТОЛЬКО router-путь; при signal_router.enabled=false весь поток идёт старым путём (open_bracket напрямую, БЕЗ source-гейта). Правка неактивного пути = ложный «локдаун»"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
  modified: 2026-07-24T23:10:57.348Z
---

# source_policies гейтит только router; старый путь ставит VST-ордер без гейта (25.07.2026)

Егор увидел на дашборде «торгует всё что можно» (wt_sideways/confluence/wl_breach/pivot_reversal
на бирже) — ПОСЛЕ моего «локдауна портфеля» через `source_policies.exchange_enabled=false`.

**Корень:** каждый сигнальный хендлер (scan_loop `_execute_sideways_signal`, WL-breach, main) устроен:
```
if signal_router.enabled and bot.trade_router:
    trade_router.submit(source=...)  → source_policies.exchange_enabled гейтит open_bracket → return
# СТАРЫЙ ПУТЬ (signal_router.enabled=false):
register_trade_async(...) ; _oe.open_bracket(...)  # биржевой ордер НАПРЯМУЮ, БЕЗ source-гейта
```
`signal_router.enabled` был **false** → весь живой поток шёл старым путём → `source_policies`
(мой замок) не применялся вообще. Я проверил ЦИФРЫ в конфиге, но не тот путь, и сказал Егору
«портфель зачищен» — **ложно**. `order_executor.open_bracket` вызывается из router (trade_router:233)
И из старого пути (scan_loop:540/1232/1355) — гейт есть только у первого.

**Фикс:** `signal_router.enabled: true` → все хендлеры через router → source_policies гейтит.
`default_policy.exchange_enabled: false` (уже стоял) ловит незалистенные источники. Биржа теперь
только radar/atr_change/atr_s2/ds_advisor. Обратимо (флаг).

**Why:** нарушил собственное правило «grep before claim» в самой опасной форме — проверил
конфиг-значения, но НЕ проверил, активен ли путь, который их читает. Config-значение ≠ поведение.

**How to apply:**
1. Меняешь source_policies/гейт — СНАЧАЛА grep, включён ли `signal_router.enabled` (иначе правишь
   мёртвый путь). Аналогично для любого `if config.enabled: … else: старый_путь`.
2. Торговый «локдаун» верифицировать ЭМПИРИЧЕСКИ (лог реального пути / БД по id), НЕ по конфигу.
   Лог-маркеры: «router … exch=none» (гейт сработал) vs «[VST] bracket» (старый путь льёт).
3. Осторожно с фильтром по времени в БД: `created_at` в БД ≠ таймзоне SQLite `datetime('now')`
   (~2.5ч сдвиг) — фильтровать по id-watermark, не по `-N minutes`.

Связано: [[anchor_dataset_company_no_revenue]] (торговля в +), [[feedback_rules_table]] (grep before claim),
[[exec_sim_split_epic]].
