---
name: oko-dashboard-v2-status
description: "Статус нового киберпанк-дашборда OKO (Next.js) — что live, что мок, как подключено"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

**Проект:** новый дашборд `e:\MTF BOT\CURSOR\oko-dashboard` (Next.js 16 + TS + Tailwind v4 + framer-motion + recharts). Киберпанк/сакральная геометрия, Куб Метатрона. Отдельно от старого aiohttp-дашборда бота (`web/dashboard_server.py` на :8000). **oko-dashboard ВНЕ git** (рабочая директория, не versioned — frontend-правки на диске, hot-reload).

**🔴 Vue v2 → АРХИВ (11.06):** старый Vue-дашборд (`web/dashboard/src`) перемещён в `archive/vue-dashboard-v2/src` (юзер: «убрать, чтобы не путаться» — раньше Analytics искался в обоих). **oko = АКТУАЛЬНЫЙ фронт**, все правки туда. `web/dashboard/dist` ОСТАВЛЕН (бот `dashboard_server:489` рендерит `/v2/`; oko от Vue не зависит — проксирует только `/api/*`). Восстановление: `git mv archive/vue-dashboard-v2/src web/dashboard/src`.

**Связь с ботом (10-11.06.2026):** дашборд читает ЖИВЫЕ данные через прокси, БЕЗ изменений в боте.
- `next.config.mjs` rewrites: `/api/:path*` → `http://localhost:8000/api/:path*` (решает CORS, прокси через Next)
- `lib/api.ts` — фетчеры + мапперы сырого JSON бота в UI-типы. `API_BASE=""` (same-origin → прокси)
- `lib/use-oko-data.ts` — хук `useLive(fetcher, fallback, intervalMs)`: polling + авто-фолбэк на моки если бот офлайн + `source: live|mock`
- Нагрузки на бота нет: эндпоинты уже кешированы (stats TTL=5s) + SQL в executor (`_run_sync`). Equity downsample до 180 точек (22k сделок).

**8 экранов. LIVE подключено:**
- Overview — KPI (Total R, WR, active), equity (`/api/stats`, `/api/equity`)
- Trades — **Sim** (`/api/stats` simulated_trades) ∥ **Exchange** (`/api/live` реальные VST-позиции с плечом/размером/unreal$). Column picker, decision trace.
- **Sync-панель** (`components/oko/sync-panel.tsx`) — сверка Sim↔Exchange по символам: matched/exch-only(zombie)/sim-only. Решает orphan/zombie проблему (часто пользуемся!). Сверху Trades.
- Analytics — equity, by-signal, by-regime, веса
- Signals — адаптивные веса (`/api/signal_weights/history`), performance, **Gate Blocks** (`/api/dropped`)
- Patterns — реальные паттерны (`/api/patterns` отдаёт DS_L001 и т.д., НЕ TODO)
- Cube — метрики шины + Live Bus Feed (`/api/cube/stats`, `/api/cube/events`)
- TopBar — `SYSTEM: LIVE`/`BOT: OFFLINE` по реальному `pingBot()`

**Pairs — ✅ LIVE (11.06, эндпоинт добавлен + проверен на живых данных):**
- `web/dashboard_server.py`: `_handle_pairs` + роут `/api/pairs?limit=60`. Read-only из `pair_context.all_symbols()` + `get_full_state(sym)` (память, без SQL). Фильтр: regime/сигнал/WT. Отдаёт ~200 пар (растёт по мере скана).
- **Реальные формы (проверено):** `wt_verdict`=UNCLEAR/REVERSAL_SETUP/EXHAUSTION/TREND_CONTINUATION (НЕ OB/OS!). `smc_verdict`=WEAK_BULL_ZONE/STRONG_BEAR_ZONE (направление+сила). `wt_confidence`≈0.6. `price`=null (нет tick_price). `last_signal`/`near_pivot` часто null.
- **Маппинг (`fetchPairsLive` в `lib/api.ts`):** WT gauge из `smc_verdict` (bull→−, bear→+, strong/weak±) × wt_confidence. zone=prettySmc(smc) если near_pivot пуст. price/spark/volume/change — fallback на мок-template (шина их не несёт).
- ⚠️ Транзиент: сразу после рестарта бота /api/pairs может дать 500 (состояние ещё пустое) → через ~10с наполняется.

**🎯 Watchlist + OTE LTF проявление (ARCH-128, 11.06) — ✅ РАБОТАЕТ:**
- Новый экран **Watchlist** (`screens/watchlist.tsx`, nav Flame) — heat-score, pin (localStorage), фильтры bull/bear, поиск.
- **Сетап-логика (НЕ проходящие сигналы):** `fetchWatchlist` делит на SETUP-триггеры (пускают в Hot: OTE LTF FIRE+6/ARMED+3, price_in_ote●+4, reversal+3, fired+3, divergence+3) и CONTEXT (только усиливают: strong zone, exhaustion, cascade, OTE armed◌). Зоны/exhaustion больше НЕ засоряют (юзер: «нужны прямо сетапы»).
- **OTE LTF проявление (видение юзера «проявить непроявленное»):** доработка БОТА — `ote_observer` пишет LTF-состояние в `pair_context` (`_publish_ote_ltf_state`, observability, торговля НЕ тронута). PairState +поля `ote_ltf_status` (ARMED/FIRE), `ote_ltf_score/min`, `ote_ltf_entry/sl/tp1/tp/trigger/direction/setup`. get_full_state + /api/pairs отдают. Вотчлист показывает **сигнал ЗАРАНЕЕ** (ARMED N/3 brewing) + **вводные для ручного входа** (Entry/SL/TP при FIRE) — чтобы юзер/клиент мог войти рукой рядом с алгоритмом.
- Файлы бота: `core/context/pair_context.py` (PairState+get_full_state), `bot/loops/ote_observer_loop.py` (_publish), `web/dashboard_server.py` (_handle_pairs). Требует рестарт бота. ote_observer пишет раз в 600с (10мин).
- Проверено: 3 пары ARMED 1/3 с entry/SL. FIRE редки (норма).
- ⚠️ price/tick_price = null у всех пар (бот не пишет tick в pair_context) → watchlist price «—».

**Остальное на МОКАХ (нет эндпоинтов):**
- Analytics: R-distribution, MFE-scatter — нет эндпоинтов
- **PnL-календарь ✅ LIVE (11.06): SIM/VST/ALL переключатель** — `fetchPnlCalendar(mode)` → `/api/stats/analytics?cal_mode=`, backend `pnl_calendar(mode)` фильтрует `exchange_order_id` (SIM=NULL, VST=NOT NULL). SIM avgR**−0.108** vs VST **+0.861** (расходятся сильно: VST=отобранные гейтами, SIM-only=балласт). Backend-фильтр активен после рестарта бота.
- Signals: recent feed (fired/registered/blocked поток) — декоративный мок

**🚀 ЗАПУСК :3000 — PM2 production (11.06):** дашборд = ОТДЕЛЬНЫЙ Next.js процесс, бот (oko_mtf.py :8000) его НЕ поднимает (две независимые технологии). Раньше падал и не автозапускался (ручной `npm run dev`). **Решение (юзер выбрал):** PM2 + production. `npm run build` → `pm2 start node_modules/next/dist/bin/next --name oko-dash --cwd <oko> -- start` → `pm2 save` → `pm2-startup install`. Теперь: автоперезапуск при падении + автостарт при загрузке Windows (registry-entry). Управление: `pm2 list/logs/restart/stop oko-dash`. ⚠️ После правок фронта: `npm run build` + `pm2 restart oko-dash` (production = нет hot-reload). ⚠️ pm2 в PowerShell блокируется execution-policy (`pm2.ps1`) — звать из cmd или `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Ручная запускалка: `oko-dashboard/start_oko_dashboard.bat` (dev-режим, fallback).

**TTS:** голос Pavel + `SetOutputToDefaultAudioDevice()` ([[say-command-tts]]).
**CLAUDE.md правило кириллицы:** в UI дашборда только английский (юзер: «кириллица плохо смотрится»).
