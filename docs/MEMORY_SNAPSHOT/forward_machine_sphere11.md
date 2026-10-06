---
name: forward-machine-sphere11
description: "Форвард-машина — еженедельный судья источников по net%, Сфера 11 (Post-Trade Feedback), REAL-MONEY гейт"
metadata: 
  node_type: memory
  type: project
  originSessionId: 53ad2006-69eb-4389-9eb0-02df4e0d45ab
---

**Что (12.07.2026, желание №2 = последнее ребро Куба):** `scripts/forward_machine.py`, pm2
`forward-machine`, cron вс 08:00. Судит каждый источник по ЧЕСТНОМУ % net (`profit_pct −
costs_pct`, ЗАКОН №1, НЕ R) на data-era ≥ 2026-07-11 (честная линейка: [[bingx_tp_market_new_orderid]]
touch + costs_pct). Разрез по нишам (direction/regime) — ищет «жив в подмножестве» (так выжил
atr_S2). REAL-MONEY гейт: VST clean-сделки к порогу 30 + net>0 → кандидат на реальные деньги.

**Архитектура:** Сфера 11 (Post-Trade Analyser + Feedback Loop) — макро/временна́я рука. Пока
post_trade_analyser реагирует на ОДНУ сделку, форвард-машина агрегирует исходы за недели →
вердикт по источнику. Это тот «feedback loop СЕЙЧАС ОТСУТСТВУЕТ» из энциклопедии. Форма — как
Сфера 12 (диагност: прогон+вердикт+алерт, брат ledger-audit/pivot-sanity). НЕ автовеса —
диагностика для человека (decision-support > автоторговля).

**Первые находки (era 1д, переходные):** radar_build LONG льёт на VST (−1.34%), radar_pump
кандидат (+3.43%, мало данных). ote_nested ВЫЖИЛ на честном sim (+0.75% n=114 — хоронили на
fake-R!), ниша SHORT +1.01%. atr_change подтверждён шреддером (−0.80%). Персист в таблицу
forward_verdicts (тренд по неделям). Крепнет за 2-3 недели. См. [[strategy_truth_state]].
