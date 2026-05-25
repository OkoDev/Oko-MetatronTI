# Oko MTF — Vue 3 Dashboard (DEV-144)

Параллельная реализация дашборда на Vue 3 + Vite. Старый `web/static/index.html`
(2981 строка vanilla HTML/JS) продолжает работать, пока миграция идёт по
6 stages × 1 неделя. План:
[`obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md`](../../obsidian/Architecture/DEV-144-Dashboard-Redesign-Plan.md).

## Запуск (dev)

```bash
cd web/dashboard
npm install
npm run dev
```

Dev-сервер: <http://localhost:5173/>
Бэкенд aiohttp (`web/dashboard_server.py`) должен быть запущен отдельно на
порту 8000 — Vite проксирует туда `/api/*` и `/sse/*`.

## Сборка (prod)

```bash
npm run build      # → web/dashboard/dist/
npm run preview    # локально просмотреть собранный bundle
```

## Структура

```
web/dashboard/
├── src/
│   ├── assets/main.css       # глобальные стили (палитра, sidebar, hero-grid)
│   ├── components/           # появятся в Stage 2-5
│   ├── pages/                # Stage 1: пустые заглушки 5 страниц
│   ├── router/index.js       # Vue Router 4
│   ├── stores/               # Pinia (появится в Stage 3)
│   ├── composables/          # useSSE, useFetch (Stage 3)
│   ├── App.vue               # layout: sidebar + topbar + RouterView
│   └── main.js               # createApp + Pinia + router
├── index.html                # HTML entrypoint для Vite
├── package.json
└── vite.config.js
```

## Прогресс stages

- [x] **Stage 1** — Vite + Vue 3 setup, root layout с sidebar, перенос стилей
- [ ] **Stage 2** — компоненты HeroGrid / CriticalAlerts / EquityCurve / StrategyMetrics / ATRChange
- [ ] **Stage 3** — Pinia stores + SSE composable
- [ ] **Stage 4** — таблицы (sortable, filterable)
- [ ] **Stage 5** — новые страницы Patterns + DecisionTimeline
- [ ] **Stage 6** — Cmd+K палитра, sparklines, polish
