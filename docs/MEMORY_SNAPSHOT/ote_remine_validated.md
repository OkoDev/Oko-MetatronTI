---
name: ote_remine_validated
description: "🔴 ПОПРАВКА: синтетический ре-майн OTE (net+0.5R) был ТУГОЙ-SL-АРТЕФАКТ. РЕАЛЬНЫЕ фаеры (5215, conf>=3): net@3R −1.057 WR10%. Выживает ТОЛЬКО 4h_1h_pull SHORT (+0.166, n69)."
metadata:
  node_type: memory
  type: project
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

🔴 **ИТОГ ре-майна OTE 21.06.2026 — ЧЕСТНЫЙ (после самопроверки на реальных данных).**

## ❌ Синтетический бэктест ВРАЛ (ote_remine.py, 89k сделок)
Показывал net@3R +0.37, ≥3R 42%, «4h→5m чемпион». **ЭТО АРТЕФАКТ ТУГОГО SL** — тот самый,
о котором сами предупреждали ([[feedback_backtest_realistic_sl]]): синтетический тугой LTF-SL
(6-бар low) → крошечный 1R → +3R «достигается» легко (42%). R-инфляция. НЕ верить этим числам.

## ✅ РЕАЛЬНЫЕ OTE-фаеры = ИСТИНА (5215 сделок, настоящий вход conf>=3, max_R_possible)
**net@3R = −1.057R, WR@3R = 10%.** OTE-pull на реальном SL + комиссия = net-ОТРИЦАТЕЛЬНА.
| setup×dir | net@3R | WR | n |
|---|---|---|---|
| **4h_1h_pull SHORT** | **+0.166** | 35% | 69 ← ЕДИНСТВЕННЫЙ net+ |
| 4h_1h_pull LONG | −0.178 | 27% | 71 |
| 1h_15m_pull SHORT | −0.627 | 17% | 111 |
| 1h_5m_cont LONG | −1.046 | 9% | 1485 |
| 4h_5m_cont SHORT | −1.876 | 7% | 288 |
conf=3 net−1.18 / conf=4 net−1.00 → **конфлюенция НЕ спасает.**

## 🔑 Три источника СОГЛАСНЫ (синтетика — выброс)
1. Реальные фаеры: ≥3R 10%, net@3R −1.057
2. Пермайн (тоже реальные fires, [[ote_premine]]): baseline ≥3R 11%
3. Income-ledger: OTE реально −$1894 ([[income_ledger_db_overstates_realized]])
→ **edge у OTE-pull почти НЕТ, кроме редкого 4h_1h_pull SHORT.** Это и есть причина убытка.

## Уроки
- **Синтетический бэктест с тугим SL = R-инфляция** (3-й раз за сессию попался). Истина = РЕАЛЬНЫЕ фаеры (max_R_possible) + income-$, НЕ синтетика.
- DS-валидированные триггеры (WR90-100% в config/ote_setups.yaml) теперь ПОД ПОДОЗРЕНИЕМ — вероятно та же backtest-инфляция. Перепроверять на реальных fires.
- Augment (ADX/n_down/elliott) для OTE-pull = маргинален (на реальных не проверял отдельно — пермайн дал слабо).
- Инструменты живут: `scripts/ote_premine.py`, `ote_remine.py`(синт, артефакт), `fetch_binance_vision.py`, `ote_net.py`. Данные Data Vision (87M баров) валидны для будущих честных тестов.

Связь: [[ote_tight_sl_validated]] (тоже могла быть инфляция — перепроверить на fires!), [[ote_nested_mtf_strategy]], [[feedback_backtest_realistic_sl]].
