---
name: income_ledger_db_overstates_realized
description: "BingX income-леджер 06-19 = ground truth — БД-realized +$121 ВРЁТ, биржа −$202 (overstate ~$323); дневная течь = ЛИКВИДАЦИИ −$87 + завышение DB-exit, НЕ funding (+$0.04)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0b9885d0-84da-4125-92df-2c24b01a41a7
---

**Дёрнул `/openApi/swap/v2/user/income` (06-19 UTC, оба VST-аккаунта) — точная атрибуция дневного −$254 equity, опровергает прежнюю модель.**

Σ оба аккаунта (06-19, n записей):
- **REALIZED_PNL −$202.15** (162) — РЕАЛЬНАЯ realized с биржи
- **INSURANCE_CLEAR −$87.37** (19) — 🔴 **ликвидации** (SL-за-ликвидацией, POPCAT-класс)
- **TRADING_FEE −$38.13** (332) — комиссии
- **FUNDING_FEE +$0.04** (47) — **funding ≈ НОЛЬ**
- TRANSFER +$568 — пополнение юзера 08:29
- **Net trading = −$327.61**

**🔴 ГЛАВНОЕ — БД врёт про стратегию:** моя БД-оценка realized (Σ profit_pct×qty×entry для VST 06-19) = **+$120.90**, биржа = **−$202.15**. Разрыв ~$323 = БД считает realized по ЗАВЫШЕННЫМ exit-ценам (exit-disconnect / fake-R-класс [[bug_phantom_exit_resolve]]). Положительный R (+72.7 sumR, avgR +0.406) и «+$121» = **фикция от кривых exit**. Реальная стратегия В МИНУСЕ.

**Why:** опровергает прежнюю атрибуцию «REST −$435/нед = комиссии −$169 + funding/untracked −$266» (BACKLOG #5, current_state 19.06). На деле: **funding ≈0**, а «untracked» = **завышение DB-realized + ликвидации**, не funding. «Хорошая стратегия / плохое исполнение» — НЕ вся правда: realized реально отрицательна; кажущийся edge — артефакт exit-цен.

**How to apply:**
1. НЕ доверять БД-realized/R для решений о стратегии, пока exit берётся из БД. Истина = `o.rp` (WS) / income-леджер. Это и есть смысл ExecutionLedger ([[exec_sim_split_epic]], [[exec_ws_vst_userdata_proven]]) — сделать метрики честными.
2. Edge ote_nested переоценить на РЕАЛЬНЫХ exit (o.rp), а не R.
3. Ликвидации −$87/день (19 шт) — проверить, режет ли SL-safety-кап (активен). Funding из списка тревог УБРАТЬ.
5. **🔴 ВЕРДИКТ ote_nested (6д, 20.06):** многодневный честный edge (income→signal_type матч, 06-14→06-19, n=817): **NET −$510.80** (realized −$423 + ликвид −$87), БД показывала **+$230** (инверсия знака на $654). **6/6 дней в минус на правде**, БД плюс каждый день. ote_nested как исполняется = отрицательный edge. ОТКРЫТО: мёртвый вход vs SL-churn (61SL/7TP) vs плечо (ликвид=исполнение). Всё на бумаге VST (0 реальных потерь). [[signal_health_map_18jun]] «+0.748 чемпион» = была DB-фикция.

4. Метод: для $-правды дёргать `/user/income` (incomeType REALIZED_PNL/INSURANCE_CLEAR/TRADING_FEE/FUNDING_FEE), не считать из simulated_trades. Read-only, ~1 вызов/аккаунт (IP-бюджет с живым ботом — минимизировать).
