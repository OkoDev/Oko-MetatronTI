<script setup>
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import CriticalAlerts from '@/components/CriticalAlerts.vue'
import HeroGrid from '@/components/HeroGrid.vue'
import EquityCurve from '@/components/EquityCurve.vue'
import StrategyMetrics from '@/components/StrategyMetrics.vue'
import ATRChange from '@/components/ATRChange.vue'
import { useDashboardStore } from '@/stores/dashboardStore'
import { useLiveStore } from '@/stores/liveStore'

const dashboard = useDashboardStore()
const live = useLiveStore()

const { stats, equity, criticalAlertData, confluence, breakeven } = storeToRefs(dashboard)
const { data: liveData } = storeToRefs(live)

onMounted(() => {
  dashboard.connect()
  live.start()
})

// Lazy load для тяжёлых секций — fetch только при первом раскрытии details.
const confluenceFetched = ref(false)
const breakevenFetched = ref(false)
function onConfluenceToggle(e) {
  if (e.target.open && !confluenceFetched.value) {
    dashboard.fetchConfluence()
    confluenceFetched.value = true
  }
}
function onBreakevenToggle(e) {
  if (e.target.open && !breakevenFetched.value) {
    dashboard.fetchBreakeven()
    breakevenFetched.value = true
  }
}

// Удобные computed для confluence breakdown.
const confByDirection = computed(() => confluence.value?.by_direction ?? [])
const confByStrength = computed(() => confluence.value?.by_strength ?? [])
const confByFactorCount = computed(() => confluence.value?.by_factor_count ?? [])
</script>

<template>
  <CriticalAlerts :data="criticalAlertData" />
  <HeroGrid :summary="stats" :live="liveData" />
  <EquityCurve :trades="equity" />
  <StrategyMetrics :summary="stats" />
  <ATRChange />

  <!-- Confluence breakdown — lazy load -->
  <details class="section-collapsible" @toggle="onConfluenceToggle">
    <summary>Confluence breakdown <span style="font-size:.75rem;color:#8b949e;font-weight:400">(только confluence-сделки)</span></summary>

    <div v-if="!confluenceFetched" class="note">Раскройте для загрузки…</div>
    <div v-else-if="!confByDirection.length" class="note">Нет данных confluence.</div>
    <div v-else>
      <h2 style="margin-top:10px">По направлению</h2>
      <table>
        <thead><tr><th>Direction</th><th>Сделок</th><th>Win</th><th>WR%</th><th>Avg R</th></tr></thead>
        <tbody>
          <tr v-for="r in confByDirection" :key="r.direction">
            <td :class="r.direction === 'LONG' ? 'green' : 'red'"><b>{{ r.direction }}</b></td>
            <td>{{ r.total }}</td>
            <td>{{ r.wins }}</td>
            <td :class="r.wr >= 50 ? 'green' : r.wr >= 40 ? 'yellow' : 'red'">{{ r.wr }}%</td>
            <td :class="r.avg_r > 0 ? 'green' : r.avg_r < 0 ? 'red' : ''">{{ r.avg_r > 0 ? '+' : '' }}{{ r.avg_r }}R</td>
          </tr>
        </tbody>
      </table>

      <h2 style="margin-top:18px">По диапазонам Strength</h2>
      <table v-if="confByStrength.length">
        <thead><tr><th>Strength</th><th>Сделок</th><th>WR%</th><th>Avg R</th></tr></thead>
        <tbody>
          <tr v-for="r in confByStrength" :key="r.bucket">
            <td class="mono">{{ r.bucket }}</td>
            <td>{{ r.total }}</td>
            <td :class="r.wr >= 50 ? 'green' : r.wr >= 40 ? 'yellow' : 'red'">{{ r.wr }}%</td>
            <td :class="r.avg_r > 0 ? 'green' : r.avg_r < 0 ? 'red' : ''">{{ r.avg_r > 0 ? '+' : '' }}{{ r.avg_r }}R</td>
          </tr>
        </tbody>
      </table>

      <h2 style="margin-top:18px" v-if="confByFactorCount.length">По числу factors</h2>
      <table v-if="confByFactorCount.length">
        <thead><tr><th>Factor count</th><th>Сделок</th><th>WR%</th><th>Avg R</th></tr></thead>
        <tbody>
          <tr v-for="r in confByFactorCount" :key="r.factor_count">
            <td>{{ r.factor_count }}</td>
            <td>{{ r.total }}</td>
            <td :class="r.wr >= 50 ? 'green' : r.wr >= 40 ? 'yellow' : 'red'">{{ r.wr }}%</td>
            <td :class="r.avg_r > 0 ? 'green' : r.avg_r < 0 ? 'red' : ''">{{ r.avg_r > 0 ? '+' : '' }}{{ r.avg_r }}R</td>
          </tr>
        </tbody>
      </table>
    </div>
  </details>

  <!-- Breakeven (BE+0.5R) — lazy load -->
  <details class="section-collapsible" @toggle="onBreakevenToggle">
    <summary>Безубыток (BE+0.5R) <span style="font-size:.75rem;color:#8b949e;font-weight:400">(сколько TP проходят BE+0.5R до закрытия)</span></summary>

    <div v-if="!breakevenFetched" class="note">Раскройте для загрузки…</div>
    <div v-else-if="!breakeven || Object.keys(breakeven).length === 0" class="note">Нет данных breakeven.</div>
    <div v-else>
      <pre style="background:#0d1117;padding:12px;border-radius:6px;color:#c9d1d9;font-size:.78rem;overflow:auto;max-height:400px">{{ JSON.stringify(breakeven, null, 2) }}</pre>
    </div>
  </details>
</template>
