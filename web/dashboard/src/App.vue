<script setup>
import { RouterLink, RouterView } from 'vue-router'
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import CommandPalette from '@/components/CommandPalette.vue'
import { useDensity } from '@/composables/useDensity'

const { density, toggle: toggleDensity } = useDensity()

const route = useRoute()
const pageTitle = computed(() => route.meta.title ?? 'Сводка')
const updatedLabel = computed(() => 'Stage 1 placeholder')

// Sidebar nav-группы (структура из web/static/index.html, перенесена 1:1).
const navOverview = [
  { to: '/', icon: '📊', label: 'Сводка' },
  { to: '/open', icon: '📂', label: 'Открытые' },
  { to: '/history', icon: '📋', label: 'История' },
  { to: '/analytics', icon: '📈', label: 'Аналитика' },
  { to: '/drops', icon: '🚫', label: 'Drops' },
  { to: '/patterns', icon: '🧩', label: 'Паттерны' },
  { to: '/trades', icon: '🔬', label: 'Decision Trace' },
]

// Stage 5 добавит /patterns, Stage 6 — Cmd+K палитру.
// Инструменты — внешние страницы старого дашборда (живут на :8000 пока).
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
          <span class="topbar-badge green">● BingX</span>
          <span class="topbar-badge blue">? Скан</span>
          <span class="updated">{{ updatedLabel }}</span>
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
