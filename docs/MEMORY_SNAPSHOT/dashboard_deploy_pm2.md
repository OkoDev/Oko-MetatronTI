---
name: dashboard_deploy_pm2
description: "Прод-дашборд oko-dashboard управляется pm2 (app 'oko-dash'); промоут изменений = npm run build → pm2 restart oko-dash. НЕ убивать PID (pm2 респавнит)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 03741574-3261-416f-94b1-b4b7c6de6735
---

22.06.2026 — установлено вживую при промоуте Exchange Truth/Oko-ребрендинга на :3000.

**Топология дашборда (oko-dashboard, Next.js 16 Turbopack):**
- **:3000 = ПРОД** — `next start`, управляется **pm2** (app name `oko-dash`, id 0, mode fork, user yogoru). Отдаёт СНИМОК билда `.next`.
- **:3001 = DEV** — `next dev` (hot-reload), читает `.env.local` при старте (в логе «Environments: .env.local»). Если :3000 занят, dev сам падает на :3001.

**🔴 ПРОМОУТ изменений на прод :3000 (правильно):**
```
cd "e:/MTF BOT/CURSOR/oko-dashboard"
npm run build              # пересборка; NEXT_PUBLIC_* ИНЛАЙНЯТСЯ здесь
pm2 restart oko-dash       # поднимает next start на новом .next
```
- `NEXT_PUBLIC_*` (напр. `NEXT_PUBLIC_OLLAMA_MODEL`) фиксируются **в момент `npm run build`** из `.env.local` → менять env ПЕРЕД build. Для прода рантайм-env роли не играет (compile-time inline). Dev (:3001) — наоборот, читает env при старте процесса.

**⚠️ GOTCHA (потратил 3 лишних kill'а):**
- Убивать PID процесса `next start` БЕСПОЛЕЗНО — pm2 мгновенно респавнит (↺ растёт), порт снова занят другим PID. Лечится только `pm2 restart/stop oko-dash`.
- `pm2 jlist 2>$null | ConvertFrom-Json` в PowerShell может молча упасть → ложный вывод «pm2 не установлен». **Проверять `pm2 list` напрямую** (table), а не jlist+парсинг.
- Найти супервизор: родитель `next start` PID → `pm2 Daemon.js`.

**Проверка нового билда (клиентские строки в JS-чанках, НЕ в prerender-HTML):**
`grep -rl "Exchange Truth" .next/static .next/server` (HTML-grep на :3000 НЕ покажет — `"use client"` строки идут в чанки). `.next/BUILD_ID` mtime = свежесть.

Связь: [[dashboard_oper_from_bus_analytics_sql]] (фронт в гите OkoDev/Oko-Dashboard), [[oko_dashboard_v2_status]].
