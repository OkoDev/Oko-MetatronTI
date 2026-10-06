---
name: bug_sl_tp_engine_section_ignored
description: "🔴🔴 КРИТ config-баг — секция sl_tp_engine (26 ключей TSL/SL/breakeven) НЕ читается ботом, код читает trading.X → defaults"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

🔴🔴 **КРИТИЧЕСКИЙ config-баг (найден 14.06.2026 при проверке TSL).** Секция `sl_tp_engine:` (config.yaml стр.293-363, **26 ключей**) содержит ВСЮ exit/risk-логику, НО код читает её из `trading.X` → `config.get("trading.use_tsl")` = None → **defaults**.

**Проверка:** `config.get('trading.tsl_activation_r_per_strategy')` → None; `config.get('sl_tp_engine.tsl_activation_r_per_strategy')` → {ote_nested:4.0,...}. Значения ЛЕЖАТ в sl_tp_engine, код смотрит trading. config_loader НЕ мержит.

**26 игнорируемых ключей:** use_tsl, tsl_hybrid_enabled, tsl_activation_r, tsl_activation_r_per_strategy, tsl_min_move_pct, tsl_activation_r_range, cascade_tsl, cascade_tsl_deescalation_r, cascade_tsl_opts, use_breakeven, breakeven_activation_r, use_be_after_tp1, expired_extend_min_r/hours, expired_management, max_positions_per_direction, min_sl_dist_pct, dual_tp, tp_selector_*, sl_tp.

**Следствия (объясняет многое):**
- **ote_nested TSL = 1.0R (default), НЕ 4.0** — раннеры резались рано. **Вся TSL-сага 14.06 анализировала НЕВЕРНУЮ конфигурацию** (думали act_r=4.0, реально 1.0). Выводы TSL пересмотреть ПОСЛЕ фикса.
- breakeven/cascade/max_positions/tp_selector — на defaults, не из config.
- Правки ote 4.0/999 (Даат 14.06) НЕ читались. min_sl_dist спасал только code-fallback 0.5 (trade_simulator:467, gates/min_sl_dist:24 fallback 0.5 совпал с конфигом).

**Код читает trading.X (проверено):** trade_tracker.py:25 (use_tsl), trade_simulator.py:467/675/2078 (min_sl_dist/tsl_per_strategy), gates/min_sl_dist.py:24, correlation_guard (max_positions_per_direction).

**ФИКС (🔴 #1 приоритет, НЕ наспех):** вернуть sl_tp_engine содержимое в trading (влить блок под `trading:` отступ) ИЛИ код→sl_tp_engine.X. Опасно: разом включит 26 параметров (были defaults) → резкая смена ВСЕЙ exit-логики. Аккуратно: (1) подтвердить все 26 ключей код читает как trading.X (не sl_tp_engine.X нигде); (2) перенести; (3) проверить применение (ote TSL 4.0, breakeven, cascade, max_positions); (4) наблюдать. Бот СЕЙЧАС на defaults = стабилен — не ломать в 3 ночи.

Когда сломалось: блок вынесли в sl_tp_engine секцию (рефакторинг config?), код не обновили. Связано: [[bug_ote_sl_near_entry_r_explosion]] (TSL-сага была на неверном config).

**✅ ФИКС ВКЛЮЧЁН 14.06 (743cc64 config_loader merge sl_tp_engine→trading setdefault). Юзер: «всё 6 сразу, данные к утру».**
**⚠️ Даат дважды ошибся в оценке («2 параметра») — РЕАЛЬНО merge меняет 6 (полный аудит config vs defaults в коде):**
1. `use_breakeven` False→True (BE@0.5R, trade_tracker:27)
2. `use_be_after_tp1` False→True (trade_tracker:29)
3. `ote_nested` TSL 1.0→4.0 (раннеры дышат дольше)
4. `cascade_tsl_opts.no_degrade_above_r` 5.0→8.0 (раннеры >8R не деградируют, cascade_tsl:60)
5. `cascade_tsl_opts.r_gradient_peak_min_r` 3.0→2.5 (cascade_tsl:141)
6. `cascade_tsl_opts.r_gradient_rollback_pct` 0.85→0.4 (cascade_tsl:142 — режет на откате −40% vs −85%, РАНЬШЕ!)
Остальные ~20 ключей: defaults совпадали (use_tsl True, min_sl_dist 0.5, max_positions 0, tsl_activation_r 1.0...) ИЛИ читались из sl_tp_engine.X (tp_selector/tsl_hybrid — работали).
**МОНИТОРИТЬ к утру:** cascade DS-321 (6 параметров) был НЕ тестирован live (default). rollback 0.4 может резать раннеры на откате раньше (противоречит no_degrade 8). breakeven on меняет exit-динамику. Раннеры ote (TSL 4.0): дышат ли до target. УРОК: оценивать config-impact ПОЛНЫМ аудитом (config vs КАЖДЫЙ default в коде), не выборочным списком.
