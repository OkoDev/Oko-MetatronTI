<script setup>
import { onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import OpenPositionsTable from '@/components/OpenPositionsTable.vue'
import LivePositionsTable from '@/components/LivePositionsTable.vue'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useLiveStore } from '@/stores/liveStore'

const dashboard = useDashboardStore()
const live = useLiveStore()

const { stats } = storeToRefs(dashboard)
const { data: liveData } = storeToRefs(live)

const openTrades = computed(() => stats.value.open_trades ?? [])
const livePositions = computed(() => liveData.value.positions ?? [])
const liveMode = computed(() => liveData.value.mode ?? 'SIM')

onMounted(() => {
  dashboard.connect()
  live.start()
})
// disconnect не делаем — стор живёт для других страниц
</script>

<template>
  <!-- Реальные VST/LIVE позиции с биржи. В SIM-режиме секция скрыта. -->
  <section v-if="liveMode !== 'SIM'">
    <h2>
      Позиции BingX <span style="color:#8b949e;font-weight:400">({{ livePositions.length }}, режим {{ liveMode }})</span>
    </h2>
    <LivePositionsTable :positions="livePositions" />
  </section>

  <section>
    <h2>
      Симуляция (simulated_trades) <span style="color:#8b949e;font-weight:400">({{ openTrades.length }})</span>
    </h2>
    <OpenPositionsTable :trades="openTrades" />
  </section>
</template>
