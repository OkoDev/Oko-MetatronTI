<script setup>
import { RouterLink, RouterView } from 'vue-router'
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import CommandPalette from '@/components/CommandPalette.vue'
import { useDensity } from '@/composables/useDensity'
import { useDashboardStore } from '@/stores/dashboardStore'

const { density, toggle: toggleDensity } = useDensity()
const route = useRoute()
const pageTitle = computed(() => route.meta.title ?? 'Сводка')

// Live данные из стора для topbar badges.
const dashboard = useDashboardStore()
const { stats, status, lastUpdate, isLive } = storeToRefs(dashboard)

// Подключение к SSE — глобально для всех страниц.
onMounted(() => dashboard.connect())

// ── BTC 4h regime badge ────────────────────────────────────────────────
const btcRegime = computed(() => stats.value.btc_4h_regime || status.value.btc_regime)
const btcBadge = computed(() => {
  const r = btcRegime.value
  if (!r || r === 'N/A') return null
  // Маппинг режима на иконку + цветовой класс
  const map = {
    TREND_UP:   { icon: '↑', cls: 'green', text: 'BTC4h ↑' },
    TREND_DOWN: { icon: '↓', cls: 'red',   text: 'BTC4h ↓' },
    RANGE:      { icon: '↔', cls: 'amber', text: 'BTC4h ↔' },
    HIGH_VOL:   { icon: '⚡', cls: 'amber', text: 'BTC4h ⚡' },
  }
  return map[r] || { icon: '?', cls: '', text: `BTC4h ${r}` }
})

// ── BingX health badge ─────────────────────────────────────────────────
const bingxHealth = computed(() => stats.value.exchange_health || 'HEALTHY')
const bingxLatency = computed(() => stats.value.exchange_latency_ms)
const bingxBadge = computed(() => {
  const h = bingxHealth.value
  const lat = bingxLatency.value
  if (h === 'DOWN') return { cls: 'red',   text: '⛔ BingX DOWN' }
  if (h === 'DEGRADED' || (lat != null && lat > 3000)) {
    return { cls: 'amber', text: `⚠ BingX ${lat ?? '?'}ms` }
  }
  return { cls: 'green', text: `● BingX${lat != null ? ` ${lat}ms` : ''}` }
})

// ── Scan health badge ──────────────────────────────────────────────────
const scanBadge = computed(() => {
  const s = status.value.scan_health || 'unknown'
  const mp = status.value.monitored_pairs ?? 0
  if (s === 'DEAD')    return { cls: 'red',   text: `💀 Скан DEAD (${mp})` }
  if (s === 'delayed') return { cls: 'amber', text: `⏳ Скан delayed (${mp})` }
  if (s === 'ok')      return { cls: 'green', text: `● Скан ${mp} пар` }
  return { cls: '', text: `? Скан ${mp}` }
})

// ── Time of last update ────────────────────────────────────────────────
const updatedLabel = computed(() => {
  if (!lastUpdate.value) return isLive.value ? 'подключено…' : 'нет данных'
  return lastUpdate.value.toLocaleTimeString('ru')
})

const navOverview = [
  { to: '/', icon: '📊', label: 'Сводка' },
  { to: '/open', icon: '📂', label: 'Открытые' },
  { to: '/history', icon: '📋', label: 'История' },
  { to: '/analytics', icon: '📈', label: 'Аналитика' },
  { to: '/drops', icon: '🚫', label: 'Drops' },
  { to: '/patterns', icon: '🧩', label: 'Паттерны' },
  { to: '/trades', icon: '🔬', label: 'Decision Trace' },
]

const navTools = [
  { href: '/trading', icon: '🎯', label: 'Trading Panel' },
  { href: '/settings', icon: '⚙️', label: 'Настройки' },
  { href: '/backtest', icon: '📉', label: 'Бэктест' },
  { href: '/performance', icon: '🏆', label: 'Перформанс' },
]
</script>

<template>
  <div class="app-layout" :class="`density-${density}`">
    <aside class="sidebar">
      <div class="sidebar-logo">
        <h1>📊 Oko MTF</h1>
        <div class="sub">Trade Dashboard</div>
      </div>

      <nav class="nav-group">
        <div class="nav-label">Обзор</div>
        <RouterLink
          v-for="item in navOverview"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          active-class="active"
        >
          <span class="icon">{{ item.icon }}</span>
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <div class="nav-label" style="padding: 10px 14px 5px">Инструменты</div>
        <a
          v-for="tool in navTools"
          :key="tool.href"
          class="nav-item"
          :href="tool.href"
        >
          <span class="icon">{{ tool.icon }}</span>
          {{ tool.label }}
        </a>
      </div>
    </aside>

    <div class="main-area">
      <div class="topbar">
        <span class="topbar-title">{{ pageTitle }}</span>
        <div class="topbar-badges">
          <span class="topbar-badge" style="background:#21262d;color:#8b949e" title="Открыть поиск по дашборду">
            ⌘K / Ctrl+K
          </span>
          <span v-if="btcBadge" class="topbar-badge" :class="btcBadge.cls"
                :title="`BTC 4h режим: ${btcRegime}`">{{ btcBadge.text }}</span>
          <span class="topbar-badge" :class="bingxBadge.cls"
                :title="`exchange_health=${bingxHealth}, latency=${bingxLatency ?? '?'}ms`">
            {{ bingxBadge.text }}
          </span>
          <span class="topbar-badge" :class="scanBadge.cls"
                :title="`scan_health=${status.scan_health}, pairs=${status.monitored_pairs ?? 0}, monitoring=${status.is_monitoring}`">
            {{ scanBadge.text }}
          </span>
          <span class="updated" :title="isLive ? 'SSE подключён' : 'SSE отключён, polling fallback'">
            {{ updatedLabel }}
          </span>
          <button
            class="topbar-badge"
            :title="`Плотность: ${density}. Кликни чтобы переключить.`"
            @click="toggleDensity()"
            style="cursor:pointer;background:none">
            {{ density === 'compact' ? '▣' : '▢' }} {{ density }}
          </button>
          <a class="topbar-badge" href="/trading">SIM</a>
        </div>
      </div>

      <div class="content">
        <RouterView />
      </div>
    </div>

    <CommandPalette />
  </div>
</template>
