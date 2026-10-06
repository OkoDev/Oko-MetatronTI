---
name: dashboard-migration-plan
description: "План переезда дашборда — сначала UI, потом реальный API"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9d582948-c9be-42e6-8444-4165a225d1fa
---

Новый дашборд (oko-dashboard, Next.js) сейчас на моковых данных из oko-data.ts.

**План:**
1. ✅ Cube экран — готов
2. Доделать UI всех остальных экранов на моковых данных
3. Создать lib/api.ts — функции fetchStats(), fetchTrades() и т.д. → http://localhost:8000
4. Подключить все экраны к реальному API за один проход

**Why:** сначала дизайн, потом данные — иначе хаос от одновременной борьбы с UI и API.

**Карта API:**
- Overview → /api/stats + /api/equity + /api/live
- Trades → /api/closed_trades + /api/live
- Pairs → /api/live + /api/pair/{symbol}
- Patterns → /api/patterns
- Signals → /api/signal_weights/history + /api/stats/confluence
- Analytics → /api/stats/analytics + /api/equity
- Settings → /api/settings GET/POST
- Cube → /api/cube/stats
