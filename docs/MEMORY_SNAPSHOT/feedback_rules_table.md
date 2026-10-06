---
name: feedback-rules-table
description: Полная таблица триггер→правило→файл (26 рабочих правил feedback) — вынесена из MEMORY.md для экономии места в хот-индексе
metadata: 
  node_type: memory
  triggers: 
    - правила фидбека
    - как я работаю
    - привычки
    - чек-лист правил
  type: feedback
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

Таблица читается по триггеру: если текущая задача попадает в левую колонку — применить правило, детали в указанном файле.

| Триггер | Правило | File |
|---|---|---|
| вызов `obj.method()` где obj незнаком | grep before claim | `feedback_no_fabricated_apis.md` |
| порядок tuple/поля/return | grep сам `return`, не по памяти | `feedback_grep_return_shape.md` |
| "N% сделок плохие по X" | проверить семантику поля в БД | `feedback_verify_metric_semantics.md` |
| метрика без распределения | avgR+median+Sharpe+гистограмма+data-era | `feedback_metrics_hygiene.md` |
| вывод "edge +X R" из бэктеста | прогнать на ПРОД-SL (0.5%/2%)+комиссия; узкий SL раздувает R = фантом | `feedback_backtest_realistic_sl.md` |
| любой ответ/thinking | на русском, без исключений | `feedback_think_russian.md` |
| завершение задачи | TTS через SAY (Microsoft Irina) | `feedback_say_command.md` |
| закрытие сессии | логи/БД + статус рестарта до TTS | `feedback_session_close_checklist.md` |
| фикс/рефактор/идея | обсудить→проверить данными→действовать | `feedback_discuss_before_act.md` |
| любая правка кода | чек-лист "до/после, что сломает" | `feedback_fix_checklist.md` |
| вывод по паре/стратегии | data-era split (post-15.04, min 10) | `feedback_data_era_first.md` |
| «фикс работает?» | split по моменту активации, НЕ «за Nч» | `feedback_verify_fix_dataera_first.md` |
| SQL по created_at | ISO-cutoff с 'T'; проверять MIN/MAX | `feedback_sqlite_time_compare.md` |
| фильтр БД по времени из лога | лог=МСК(+3), created_at=UTC → −3ч | `feedback_db_query_utc.md` |
| правка register_trade/INSERT | runtime-тест на копии БД (ast не ловит scope) | `feedback_ast_parse_no_scope.md` |
| биржевая задача | сначала BingX docs, потом гипотезы | `feedback_read_bingx_docs.md` |
| блокировка сигнала | НЕ блокировать без крайней нужды | `feedback_no_blocking.md` |
| skill vs code | разделять чат vs торговля | `feedback_skill_vs_code.md` |
| bash команда | выполнять авто (кроме destructive) | `feedback_bash_auto.md` |
| закрытие задачи | сразу обновить TASKS.md | `feedback_close_tasks.md` |
| задание с критериями | якорь в TASKS, детали в DISCUSSION | `feedback_tasks_vs_discussion.md` |
| любая работа | стиль торговли пользователя | `user_trading_style.md` |
| сверка с TradingView | синхронизировать день+символ | `feedback_chart_sync_etalon.md` |
| находка/research | снапшот auto-memory→git; сырьё в data/research/ | `feedback_memory_persistence.md` |
| запись в DISCUSSION/current_state | новые записи СВЕРХУ | `feedback_discussion_newest_top.md` |
| формат TASKS | `\| [ID](#a) \| Ст \| ≤80 \| Роль \|`, детали в DISCUSSION | `feedback_tasks_format.md` |
