<script setup>
import { onMounted, onUnmounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import OpenPositionsTable from '@/components/OpenPositionsTable.vue'
import { useDashboardStore } from '@/stores/dashboardStore'

// open_trades приходят в stats через SSE — отдельный fetch не нужен.
const dashboard = useDashboardStore()
const { stats } = storeToRefs(dashboard)

const openTrades = computed(() => stats.value.open_trades ?? [])

onMounted(() => dashboard.connect())
// disconnect не делаем — стор может быть нужен на других страницах
</script>

<template>
  <section>
    <h2>Открытые позиции <span style="color:#8b949e;font-weight:400">({{ openTrades.length }})</span></h2>
    <OpenPositionsTable :trades="openTrades" />
  </section>
</template>
