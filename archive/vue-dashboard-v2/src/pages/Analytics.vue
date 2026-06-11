<script setup>
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import StatsTable from '@/components/StatsTable.vue'
import { useDashboardStore } from '@/stores/dashboardStore'

const dashboard = useDashboardStore()
const { stats } = storeToRefs(dashboard)

onMounted(() => dashboard.connect())

const bySignalType = computed(() => stats.value?.by_signal_type ?? [])
const byRegime     = computed(() => stats.value?.by_regime ?? [])
const byStrategy   = computed(() => stats.value?.by_strategy ?? [])
const byDirection  = computed(() => stats.value?.by_direction ?? [])
</script>

<template>
  <section>
    <h2>По типу сигнала</h2>
    <StatsTable :rows="bySignalType" key-field="signal_type" key-label="Сигнал" />
  </section>

  <section>
    <h2>По режиму рынка</h2>
    <StatsTable :rows="byRegime" key-field="regime" key-label="Режим" />
  </section>

  <section>
    <h2>По стратегии (Strategy Pattern)</h2>
    <StatsTable :rows="byStrategy" key-field="strategy_name" key-label="Стратегия" />
  </section>

  <section>
    <h2>По направлению</h2>
    <StatsTable :rows="byDirection" key-field="direction" key-label="Direction" />
  </section>
</template>
