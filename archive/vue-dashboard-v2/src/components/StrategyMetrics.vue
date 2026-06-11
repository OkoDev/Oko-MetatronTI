<script setup>
import { computed } from 'vue'

const props = defineProps({
  summary: {
    type: Object,
    default: () => ({})
  }
})

// Raw fields with defaults
const winRate = computed(() => props.summary?.summary?.win_rate ?? 0)
const avgRWin = computed(() => props.summary?.summary?.avg_r_win ?? 0)
const avgRLoss = computed(() => props.summary?.summary?.avg_r_loss ?? 0)
const closedPerDay = computed(() => props.summary?.summary?.closed_per_day ?? 0)
const daysActiveRaw = computed(() => props.summary?.summary?.days_active ?? 0)
const openPnlR = computed(() => props.summary?.open_pnl_r ?? null)

// Normalized values
const wr = computed(() => (winRate.value ?? 0) / 100)
const rWin = computed(() => avgRWin.value ?? 0)
const rLoss = computed(() => avgRLoss.value ?? 0)

// EV calculations
const ev = computed(() => wr.value * rWin.value + (1 - wr.value) * rLoss.value)
const evRound = computed(() => Math.round(ev.value * 100) / 100)
const evBorder = computed(() => (evRound.value > 0 ? '#3fb95044' : '#f8514944'))
const evDisplay = computed(() => `${evRound.value > 0 ? '+' : ''}${evRound.value.toFixed(2)}R`)
const evVerdict = computed(() => (evRound.value > 0 ? '✅ Система прибыльна' : '❌ Система убыточна'))

// Profit Factor calculations
const pfDenom = computed(() => (1 - wr.value) * Math.abs(rLoss.value))
const pf = computed(() => {
  const denom = pfDenom.value
  return denom > 0 ? Math.round((wr.value * rWin.value) / denom * 100) / 100 : null
})
const pfClass = computed(() => {
  const v = pf.value
  if (v === null) return ''
  if (v >= 1.5) return 'green'
  if (v >= 1) return 'yellow'
  return 'red'
})
const pfDisplay = computed(() => (pf.value !== null ? pf.value.toFixed(2) : '—'))
const pfVerdict = computed(() => {
  const v = pf.value
  if (v === null) return 'нет данных'
  if (v >= 1.5) return '🔥 Отличный'
  if (v >= 1.2) return '👍 Хороший'
  if (v >= 1) return '⚡ Слабый'
  return '❌ < 1'
})

// Avg R card values
const rWinFmt = computed(() => rWin.value.toFixed(2))
const rLossFmt = computed(() => rLoss.value.toFixed(2))
const cpd = computed(() => closedPerDay.value)
const daysActive = computed(() => daysActiveRaw.value)

// Open P&L values
const openPnlColor = computed(() => {
  const v = openPnlR.value
  if (v === null) return '#8b949e'
  return v >= 0 ? '#3fb950' : '#f85149'
})
const openPnlDisplay = computed(() => {
  const v = openPnlR.value
  if (v === null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}R`
})
</script>

<template>
  <section>
    <h2>Метрики стратегии</h2>
    <div class="cards">
      <!-- Card 1: EV / сделку -->
      <div class="card" :style="{ borderColor: evBorder }">
        <div class="label">
          EV / сделку
          <span style="color:#444;font-size:.7rem" title="Expected Value = WR×R_win + (1-WR)×R_loss">ожидаемый R</span>
        </div>
        <div class="value" :class="evRound > 0 ? 'green' : 'red'">
          {{ evDisplay }}
        </div>
        <div class="label" style="margin-top:4px">{{ evVerdict }}</div>
      </div>

      <!-- Card 2: Profit Factor -->
      <div class="card">
        <div class="label">Profit Factor</div>
        <div class="value" :class="pfClass">{{ pfDisplay }}</div>
        <div class="label" style="margin-top:4px">{{ pfVerdict }}</div>
      </div>

      <!-- Card 3: Avg R (Win / Loss) -->
      <div class="card">
        <div class="label">Avg R (Win / Loss)</div>
        <div class="value" style="font-size:1.2rem">
          <span class="green">+{{ rWinFmt }}</span>
          <span style="color:#444;font-weight:400"> / </span>
          <span class="red">{{ rLossFmt }}</span>
        </div>
        <div class="label" style="margin-top:4px">
          Сделок/день: <span style="color:#c9d1d9">{{ cpd }}</span> · {{ daysActive }} дней
        </div>
      </div>

      <!-- Card 4: Open P&L -->
      <div class="card">
        <div class="label">Open P&L</div>
        <div class="value" :style="{ color: openPnlColor }">{{ openPnlDisplay }}</div>
        <div class="label" style="margin-top:4px">нереализованный R</div>
      </div>
    </div>
  </section>
</template>
