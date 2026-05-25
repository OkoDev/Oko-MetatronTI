<script setup>
import { onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import CriticalAlerts from '@/components/CriticalAlerts.vue'
import HeroGrid from '@/components/HeroGrid.vue'
import EquityCurve from '@/components/EquityCurve.vue'
import StrategyMetrics from '@/components/StrategyMetrics.vue'
import ATRChange from '@/components/ATRChange.vue'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useLiveStore } from '@/stores/liveStore'

// Stage 3: данные тянутся через стор + SSE (вместо polling).
// dashboardStore — SSE `/api/events?dashboard=1` + lightweight polling `/api/dashboard` (status) 10s.
// liveStore — polling `/api/live` 5s (SSE не покрывает баланс биржи).

const dashboard = useDashboardStore()
const live = useLiveStore()

const { stats, equity, criticalAlertData, isLive, sseError } = storeToRefs(dashboard)
const { data: liveData, error: liveError } = storeToRefs(live)

onMounted(() => {
  dashboard.connect()
  live.start()
})

onUnmounted(() => {
  dashboard.disconnect()
  live.stop()
})
</script>

<template>
  <CriticalAlerts :data="criticalAlertData" />
  <HeroGrid :summary="stats" :live="liveData" />
  <EquityCurve :trades="equity" />
  <StrategyMetrics :summary="stats" />
  <ATRChange />

  <div v-if="sseError || liveError" style="margin-top: 12px; font-size: 0.82rem; color: #8b949e">
    <span v-if="!isLive" class="yellow">⚠ SSE отключён · работаем по polling-fallback</span>
    <span v-if="liveError" class="red" style="margin-left: 12px">live: {{ liveError }}</span>
  </div>
</template>
