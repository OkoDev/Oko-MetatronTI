---
name: tv_mcp_pine_overwrite_incident
description: "🔴 TradingView MCP: pine_new НЕ создаёт новый скрипт, если в редакторе открыт другой, а pine_smart_compile жмёт «Сохранить» → 26.09 перезаписал OkoTrend (v211). Восстановлен из v210 через pine-facade. Перед set_source проверять заголовок редактора"
metadata:
  node_type: memory
  type: feedback
  originSessionId: ea98197f-5cfa-4b48-ab76-1b2fcebf5d0d
  modified: 2026-09-26T00:08:53.452Z
---

26.09.2026, сверка Pine ↔ Python: `pine_new` вернул success, но в редакторе остался открытый OkoTrend;
`pine_set_source` записал в него тестовый код, `pine_smart_compile` дважды нажал «Pine Save» →
OkoTrend стал версией 211 с чужим кодом. Восстановлено тем же днём: исходник версии 210 взят через
`fetch("https://pine-facade.tradingview.com/pine-facade/get/<USER;id>/<ver>", {credentials:"include"})`
в контексте страницы, вставлен и сохранён → версия 212, совпадение с 210 до символа (хеш). Копия:
`docs/reference/OkoTrend_v210.pine`. Егор разрешал только перезапуск TradingView, не правку своих скриптов.

**Why:** сохранённые скрипты Егора — его рабочие индикаторы; перезапись незаметна (панель просто пустеет).
**How to apply:**
1. Перед `pine_set_source` читать имя скрипта в заголовке редактора (`h2` в правой панели, `x > 1400, y < 110`):
   писать только если там «Новый скрипт». Новый скрипт создавать меню «имя ▾ → Создать новый → Индикатор».
2. `pine_smart_compile` не использовать для тестового кода — он сохраняет. На график без сохранения: Ctrl+Enter.
3. Сверку делать без сохранения; после — снять индикатор, вернуть символ/ТФ, проверить список скриптов.
4. TradingView из Microsoft Store: `tv_launch` его не видит — `Invoke-CommandInDesktopPackage … --remote-debugging-port=9222`.
5. Метки и большие исходники забирать из страницы через CDP из Python (без ручной перепечатки);
   MCP `data_get_pine_labels` округляет цену до 2 знаков.
Связано: [[oko_sm_engine_ported]], [[oko_sm_luxalgo_license_risk]].
