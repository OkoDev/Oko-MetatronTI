<template>
  <section>
    <h2>Equity curve</h2>
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 8px">
      <div v-if="!trades.length" class="equity-chart" style="padding:40px;text-align:center;color:#8b949e;font-size:.9rem">
        Нет закрытых сделок для построения equity curve
      </div>
      <div v-else class="equity-chart">
        <svg :viewBox="`0 0 ${W} ${H}`" :width="'100%'" :height="H + 'px'" style="display:block">
          <!-- grid lines -->
          <line v-for="(yPos, idx) in gridYPositions" :key="'grid-'+idx"
                :x1="left" :x2="W - right"
                :y1="yPos" :y2="yPos"
                stroke="#21262d" stroke-width="1" opacity="0.6"/>
          <!-- y axis labels -->
          <text v-for="(val, idx) in yLabels" :key="'ylabel-'+idx"
                :x="left - 6" :y="y(val)"
                fill="#8b949e" font-family="monospace" font-size="11"
                text-anchor="end" dominant-baseline="middle">
            {{ formatYLabel(val) }}
          </text>
          <!-- zero line -->
          <line v-if="zeroY !== null"
                :x1="left" :x2="W - right"
                :y1="zeroY" :y2="zeroY"
                stroke="#484f58" stroke-width="1" stroke-dasharray="4 4"/>
          <!-- area -->
          <path :d="areaPath"
                :fill="areaColor"
                stroke="none"/>
          <!-- line -->
          <polyline :points="pointsString"
                    :stroke="lineColor"
                    stroke-width="2"
                    fill="none"
                    stroke-linejoin="round"/>
          <!-- corner labels -->
          <text x="10" y="15" fill="#8b949e" font-family="monospace" font-size="10">Equity</text>
          <text :x="W - right" y="15"
                :fill="lineColor"
                font-family="monospace" font-size="14" text-anchor="end">
            {{ formattedLastVal }}
          </text>
          <text :x="left" :y="H - 5"
                fill="#8b949e" font-family="monospace" font-size="11" text-anchor="start">
            0 / {{ trades.length }} сделок
          </text>
          <text :x="W - right" :y="H - 5"
                fill="#8b949e" font-family="monospace" font-size="10" text-anchor="end">
            min: {{ formatYLabel(minVal) }} · max: {{ formatYLabel(maxVal) }}
          </text>
        </svg>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  trades: {
    type: Array,
    default: () => []
  }
})

const W = 800
const H = 240
const top = 20
const right = 50
const bottom = 30
const left = 60
const cW = W - left - right
const cH = H - top - bottom

const cumR = computed(() => {
  const arr = []
  let sum = 0
  for (const t of props.trades) {
    sum += t.R_multiple
    arr.push(sum)
  }
  return arr
})

const xMax = computed(() => {
  const len = props.trades.length
  return Math.max(1, len - 1)
})

const yMin = computed(() => {
  if (!cumR.value.length) return 0
  const min = Math.min(...cumR.value)
  return Math.min(0, min)
})

const yMax = computed(() => {
  if (!cumR.value.length) return 1
  const max = Math.max(...cumR.value)
  return Math.max(0, max)
})

const yRange = computed(() => {
  const diff = yMax.value - yMin.value
  return diff === 0 ? 1 : diff
})

function x(i) {
  return left + (i / xMax.value) * cW
}
function y(v) {
  return top + cH - ((v - yMin.value) / yRange.value) * cH
}

const pointsString = computed(() => {
  return props.trades.map((_, i) => `${x(i)},${y(cumR.value[i])}`).join(' ')
})

const areaPath = computed(() => {
  if (!props.trades.length) return ''
  const points = props.trades.map((_, i) => `${x(i)},${y(cumR.value[i])}`).join(' L ')
  const baseY = (0 >= yMin.value && 0 <= yMax.value) ? y(0) : y(yMin.value)
  const startX = x(0)
  const endX = x(props.trades.length - 1)
  return `M ${startX},${baseY} L ${points} L ${endX},${baseY} Z`
})

const lineColor = computed(() => {
  const last = cumR.value[cumR.value.length - 1] ?? 0
  return last >= 0 ? '#3fb950' : '#f85149'
})

const areaColor = computed(() => {
  return lineColor.value === '#3fb950' ? 'rgba(63,185,80,0.10)' : 'rgba(248,81,73,0.10)'
})

const zeroY = computed(() => {
  if (0 >= yMin.value && 0 <= yMax.value) {
    return y(0)
  }
  return null
})

const yLabels = computed(() => {
  const vals = []
  const step = (yMax.value - yMin.value) / 4
  for (let i = 0; i <= 4; i++) {
    vals.push(yMin.value + step * i)
  }
  return vals
})

const formattedLastVal = computed(() => {
  const val = cumR.value[cumR.value.length - 1] ?? 0
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}R`
})

const minVal = computed(() => (cumR.value.length ? Math.min(...cumR.value) : 0))
const maxVal = computed(() => (cumR.value.length ? Math.max(...cumR.value) : 0))

function formatYLabel(v) {
  const abs = Math.abs(v)
  if (abs >= 100) {
    return `${v.toFixed(0)}R`
  }
  return `${v.toFixed(1)}R`
}

const gridYPositions = computed(() => {
  const positions = []
  for (let i = 0; i <= 4; i++) {
    positions.push(top + (cH / 4) * i)
  }
  return positions
})
</script>
