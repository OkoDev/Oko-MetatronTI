<script setup>
import { computed } from 'vue'

const props = defineProps({
  patterns: { type: Array, default: () => [] }
})

const cellW = 60
const cellH = 14
const labelW = 100
const headerH = 24
const cols = 4
const viewW = labelW + cols * cellW

// Высота viewBox реактивна: меняется когда патернов больше/меньше.
const viewH = computed(() => headerH + props.patterns.length * cellH)
const viewBox = computed(() => `0 0 ${viewW} ${viewH.value}`)

const rows = computed(() =>
  props.patterns.map((p, i) => ({
    p,
    i,
    y: headerH + i * cellH
  }))
)

function cellColor(p, col) {
  const isActive =
    (col === 0 && p.direction === 'LONG') ||
    (col === 1 && p.direction === 'SHORT')
  if (!isActive) return col >= 2 ? '#1c2128' : '#0d1117'

  const r = p.test_avgR ?? 0
  if (r === 0) return '#1c2128'
  if (r > 0) {
    const op = Math.min(0.85, 0.15 + (r / 1.0) * 0.7)
    return `rgba(63,185,80,${op})`
  }
  const op = Math.min(0.85, 0.15 + (Math.abs(r) / 0.5) * 0.7)
  return `rgba(248,81,73,${op})`
}

function cellStroke(p, col) {
  return col >= 2 ? '#0d1117' : '#21262d'
}

function cellTooltip(p, col) {
  const regNames = ['TREND_UP', 'TREND_DOWN', 'RANGE', 'HIGH_VOL']
  const reg = regNames[col]
  if (col >= 2) {
    return `${p.id} × ${reg}: live данные TBD (нужен pattern_id в features_json)`
  }
  const isActive =
    (col === 0 && p.direction === 'LONG') ||
    (col === 1 && p.direction === 'SHORT')
  if (!isActive) {
    return `${p.id}: ${p.direction} — не применим к ${reg}`
  }
  const r = p.test_avgR != null ? p.test_avgR.toFixed(3) : '—'
  const wr = p.test_WR != null ? p.test_WR.toFixed(1) + '%' : '—'
  const n = p.test_n ?? '—'
  return `${p.id} × ${reg}\navgR=${r}R, WR=${wr}, n=${n}`
}
</script>

<template>
  <div v-if="!patterns.length" class="note">Нет данных паттернов.</div>
  <div v-else style="overflow:auto;max-height:80vh;border:1px solid #30363d;border-radius:6px;background:#161b22">
    <svg :viewBox="viewBox" :width="viewW" :height="viewH" xmlns="http://www.w3.org/2000/svg">
      <text :x="labelW + 30" y="16" text-anchor="middle" font-size="11" fill="#8b949e">TREND_UP</text>
      <text :x="labelW + 90" y="16" text-anchor="middle" font-size="11" fill="#8b949e">TREND_DOWN</text>
      <text :x="labelW + 150" y="16" text-anchor="middle" font-size="11" fill="#8b949e">RANGE</text>
      <text :x="labelW + 210" y="16" text-anchor="middle" font-size="11" fill="#8b949e">HIGH_VOL</text>

      <g v-for="{ p, y } in rows" :key="p.id">
        <text x="6" :y="y + 10" font-family="monospace" font-size="10" fill="#c9d1d9">{{ p.id }}</text>
        <rect
          v-for="col in 4"
          :key="col"
          :x="labelW + (col - 1) * cellW"
          :y="y"
          :width="cellW - 1"
          :height="cellH - 1"
          :fill="cellColor(p, col - 1)"
          :stroke="cellStroke(p, col - 1)"
        >
          <title>{{ cellTooltip(p, col - 1) }}</title>
        </rect>
      </g>
    </svg>
  </div>
</template>
