import { createRouter, createWebHistory } from 'vue-router'

// Stage 1: только заглушки. Stage 2-5 наполнят компонентами и реальными данными.
// Имена путей синхронны с текущим SPA-хешем web/static/index.html (showPage('summary' | 'open' | ...)).
const routes = [
  {
    path: '/',
    name: 'summary',
    component: () => import('@/pages/Summary.vue'),
    meta: { title: 'Сводка' },
  },
  {
    path: '/open',
    name: 'open',
    component: () => import('@/pages/OpenPositions.vue'),
    meta: { title: 'Открытые позиции' },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/pages/History.vue'),
    meta: { title: 'История' },
  },
  {
    path: '/analytics',
    name: 'analytics',
    component: () => import('@/pages/Analytics.vue'),
    meta: { title: 'Аналитика' },
  },
  {
    path: '/drops',
    name: 'drops',
    component: () => import('@/pages/Drops.vue'),
    meta: { title: 'Drops' },
  },
  {
    path: '/patterns',
    name: 'patterns',
    component: () => import('@/pages/Patterns.vue'),
    meta: { title: 'Паттерны' },
  },
  {
    path: '/trades/:id?',
    name: 'decision-trace',
    component: () => import('@/pages/DecisionTimeline.vue'),
    meta: { title: 'Decision Trace' },
  },
]

// base — то же значение что и vite.base в prod.
// В dev оставляем '/' для localhost:5173 без префикса.
export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
