# Vue Dashboard v2 — АРХИВ (legacy)

> Перемещён в архив **11.06.2026** (юзер: «убрать пока, чтобы не путаться»).

## Почему в архиве
**Актуальный фронтенд = `oko-dashboard` (Next.js, :3000)** — киберпанк-дашборд, все экраны live
через прокси `/api/* → :8000`. Vue v2 (этот) — предыдущее поколение UI бота на `:8000/v2/`.

## Что перемещено / что осталось
- ✅ **`src/`** (Vue-исходники) → сюда, `archive/vue-dashboard-v2/src/`. Чтобы grep/поиск не путал
  два дашборда (раньше Analytics искался в обоих).
- ⚠️ **`web/dashboard/dist/`** — ОСТАВЛЕН на месте: бот `dashboard_server.py:489` (`/v2/` route)
  рендерит готовый `dist/index.html`. Удаление сломало бы `:8000/v2/` (бот graceful → «не собран»,
  но dist живой = UI работает). `oko-dashboard` от Vue НЕ зависит (проксирует только `/api/*`).
- `node_modules/` (43M) — НЕ трогали (в web/dashboard).

## Восстановление (если понадобится)
```
git mv archive/vue-dashboard-v2/src web/dashboard/src
cd web/dashboard && npm run build   # пересобрать dist
```

## Развиваем
`oko-dashboard/` — туда идут все фронт-правки (напр. SIM/VST-переключатель P&L календаря 11.06).
