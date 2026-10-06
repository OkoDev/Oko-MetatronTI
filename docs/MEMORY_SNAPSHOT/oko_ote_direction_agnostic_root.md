---
name: oko_ote_direction_agnostic_root
description: "КОРЕНЬ контртренд-сделок OKO-OTE — htf_dir \"инфо, не фильтр\"; направление берётся от слома LTF, зона HTF = лишь ценовая полоска"
metadata: 
  node_type: memory
  type: project
  originSessionId: 99e37832-43b2-4ab6-b521-76f0e9977ca5
---

# OKO-OTE торгует против шерсти — корень найден (26.06.2026, по коду)

Егор увидел на чарте: бот шортит RPL в бычьем рынке (свежий импульс 1.215→1.663),
взяв СТАРЫЙ медвежий 4h-импульс (1.48→1.21, CHoCH от 23.06) как основу для SHORT.
Глазами/OKO-SM сетап был LONG (OTE 0.62-0.705 = 1.347-1.385).

**Корень (3 строки в [core/smc/oko_ote.py]):**
- L251 `htf_dir = h["direction"]` → комментарий: «нарратив старшего (инфо; НЕ жёсткий фильтр)»
- L268 без mid_tf: контейнер = `(htf_ote_lo, htf_ote_hi, None)` → `None` = фильтра по направлению НЕТ
- L355 `D = s["direction"]` → направление сделки = слом МЛАДШЕГО, обе стороны
- Бой: наблюдатель зовёт детектор БЕЗ mid_tf → направление HTF не фильтрует ВООБЩЕ

**Перевод:** старший ТФ работает не как bias (бычий/медвежий), а как тонкая ценовая
полоска OTE 0.62-0.79 одного импульса. Логика = «слом LTF любой стороны внутри полоски →
торгуй в сторону слома». Направление OTE (святое в SMC) выкинуто.

**Один корень — два симптома:**
- Контртренд: зона направление-агностична → SHORT в бычьем рынке (RPL-кейс)
- Мало сигналов: узкая полоска одного импульса редко содержит слом LTF + цена-в-зоне-сейчас.
  Измерено: confs≥3 + pit-zone → 0 сделок за первые 10 пар бэктеста.

**Замысел ≠ код:** Егор строит trend-continuation (HTF bias → LTF OTE откат по тренду,
как OKO-SM на TradingView). Код = direction-agnostic confluence-lottery. Разные стратегии.

**Решение (выбор Егора 26.06 = backtest-first):** доказать на истории что
«HTF-bias жёсткий фильтр + LTF OTE continuation» (вариант B, aligned) даёт edge vs
текущий (вариант A, все). Метод: [scripts/oko_ote_runner_test.py] обогащён — несёт
`htf_dir` (из zone_ts) + `aligned` флаг → один прогон даёт A(все)/B(aligned)/counter.
НЕ менять live пока B не доказан плюсом. Прибыльность под вопросом: прошлые OTE-бэктесты
в минусе ([[ote_remine_validated]], [[income_ledger_db_overstates_realized]]).

Связано: [[oko_ote_torn_from_context]] (тот же диагноз раньше, без code-локализации),
[[htf_significant_context_over_local]], [[bug_select_significant_impulse_full_dataset_lookahead]].
