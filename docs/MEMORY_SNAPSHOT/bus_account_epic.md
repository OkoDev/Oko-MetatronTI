---
name: bus_account_epic
description: BUS-ACCOUNT-EPIC — трёхуровневая шина L1 PairState→L2 AccountState→L3 TraderState (спроектирован роем 14.06)
metadata: 
  node_type: memory
  type: project
  originSessionId: 0218674a-a04f-4556-9b18-087dfa1838c8
---

🏛️ **BUS-ACCOUNT-EPIC** — account/portfolio-измерение Shared Context Bus. Спроектирован 14.06.2026 (2 раунда team-ask 6/7 + видение DS `docs/BUS_SUBSCRIBER_ROADMAP.md` раздел «Уровни куба»). **Дизайн закрыт, эпик в бэклоге (вектор на год). НЕ реализован.**

**Трёхуровневая иерархия над парой:**
- **L1 PairState ×526** — ИСПОЛНЕНИЕ (есть, `core/context/pair_context.py`)
- **L2 AccountState ×2** — ПОРТФЕЛЬ (equity/margin/drawdown/exposure)
- **L3 TraderState** — ДИРИЖЁР (цели +X%/мес, аллокация капитала между стратегиями)

**Консенсус роя:**
1. **L2+L3 в ОДНОЙ шине** — расширить `PairContextBus` (`_accounts` dict, НЕ sentinel, НЕ отдельный PortfolioBus → дубль pub/sub = дрейф, противоречит Центральной Сфере Куба). [[principle_reuse_not_duplication]]
2. Producer: EXEC-WS push (`ACCOUNT_UPDATE` уже приходит) + REST fallback.
3. Доступ потребителей: синглтон-аксессор `get_bus()` (не 30 callsites; DI позже).
4. TraderState = async-подписчик (свой loop) на `ACCOUNT_UPDATED`+`TRADE_CLOSED`+таймер 5мин.
5. Capital Allocator: множитель `strategy_weight` 0.0–2.0 поверх sizing.
6. Correlation Shield: корреляции /15мин → LRU-cache → O(1) hot path, порог 0.75.

**Первый кирпич BUS-L2-BRICK ✅ РЕАЛИЗОВАН 15.06 (6e0d616):** `AccountState` в `PairContextBus` (equity/available/used_margin, L2-измерение параллельно PairState) + `update_account`/`get_account`/`total_equity`. EXEC-WS `ACCOUNT_UPDATE` (`wb`=wallet balance) → `bus.update_account` (push). `trading/status` читает `total_equity()` из шины + fallback БД `balance_snapshots` (cold start). Баланс ЖИВОЙ (push, не REST/10-мин polling), 0 cross-loop вис (был корень dashboard BOT:OFFLINE мигания в threaded). Юзер: «баланс должен слушать шину, не REST». NEXT: position_sizer из шины (живой deposit вместо хардкод 710); на L2 → Risk Monitor/Circuit Breaker/Capital Allocator.

**⚠️ МОЯ ПОЗИЦИЯ ПРОТИВ РОЯ:** Correlation Shield РАНЬШЕ Capital Allocator. Аллокатор по Sharpe, Sharpe на фейк-R (SL≈entry) = усиление ошибки с плечом. Сначала достоверность (DATA-AUDIT-2), потом дирижёр. «Зеркало полноты растёт снизу, от истинного основания, не сверху от красивой абстракции».

**Открытие:** для VST/LIVE deposit УЖЕ живой (`get_available_balance()`→REST). Хардкод 710 бьёт только SIM+fallback+dashboard KPI. Реальные: acc1=395$, acc2=377$.

Связано: [[exec_ws_vst_userdata_proven]] (producer), [[arch_db_v2_terminal]] (account-разметка), [[vision_cube_tesseract_singularity]] (L3=стягивание стратегий в одну волю). TASKS → BUS-ACCOUNT-EPIC / BUS-L2-BRICK.
