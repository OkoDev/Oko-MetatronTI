---
name: vision_config_reorg
description: "ЭПИК CONFIG-REORG — config хаотичен (настройки по углам), корень CONFIG-SLTP-BUG. Нужна единая структура по доменам + карта + валидатор config↔код"
metadata: 
  node_type: memory
  type: project
  originSessionId: 3743ba62-3271-4099-bf28-5bf1be14a516
---

**⚠️ ЭТО НЕ НОВЫЙ ЭПИК — обоснование DS-325 CONFIG-TYPED** (юзер записал в бэклог ранее, TASKS:196 «типизировать config_loader через pydantic-settings»). pydantic-settings = типизированная схема → решает всё ниже системно (видное место + валидация + orphan-секции невозможны). CONFIG-SLTP-BUG 14.06 = живое доказательство → приоритет DS-325 повышен 🔵→🟠. Рой опрошен по pydantic-settings 14.06 (team_ask q4).

**Проблема (юзер 14.06: «должно лежать на видном месте, все знают где»).**

**Проблема:** config.yaml хаотичен — настройки размазаны по секциям без логики. Поиск «по углам» (trading vs sl_tp_engine). Корень **CONFIG-SLTP-BUG** ([[bug_sl_tp_engine_section_ignored]]): 26 ключей exit/risk уехали в секцию sl_tp_engine, код остался читать trading.X → defaults, **никто не заметил** (нет карты/валидации). Примеры размазки: TSL в sl_tp_engine но код trading.X; min_sl_dist в sl_tp_engine; max_notional_mult/min_rr_per_strategy в trading; tsl_hybrid читается sl_tp_engine.X. Один домен (exit/risk) — в двух секциях, два пути чтения.

**Нужно (эпик):**
1. **Единая структура по доменам** — каждая настройка в ОЧЕВИДНОЙ секции (risk / exit-tsl / signals / gates / market-data / exchange / ...). Один домен = одна секция.
2. **Карта-индекс** в начале config (комментарий): где что лежит. «Видное место».
3. **Один namespace на домен** — код читает консистентно (не trading.X ∥ sl_tp_engine.X для одного).
4. **Валидатор** `scripts/validate_config.py`: config↔код — все читаемые `config.get("X.Y")` ключи существуют в config; нет orphan-секций (как sl_tp_engine), нет потерянных. CI-проверка.
5. **Один источник** ([[principle_reuse_not_duplication]]) — каждая настройка в 1 месте, без дублей.

**Подход (НЕ наспех — рефактор config+код синхронно):** (а) аудит карта ключ→секция→код-читатели; (б) спроектировать домены; (в) валидатор; (г) мигрировать config+код атомарно; (д) документировать. Риск: переместить настройку → обновить чтение → проверить применение (как CONFIG-SLTP-BUG показал — потеря = тихие defaults).

**Связь:** [[bug_sl_tp_engine_section_ignored]] (триггер-баг), [[principle_reuse_not_duplication]], [[gate_sphere_concept]] (централизация гейтов — родственно). Временный фикс CONFIG-SLTP-BUG = merge sl_tp_engine→trading (743cc64), но это костыль — реорг решит системно.
