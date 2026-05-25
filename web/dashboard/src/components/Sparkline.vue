<template>
  <svg v-if="data && data.length > 1"
       :viewBox="`0 0 ${W} ${H}`"
       :width="W"
       :height="H"
       style="display:inline-block;vertical-align:middle"
       :title="title">
    <!-- zero-line dashed (только если 0 в диапазоне) -->
    <line v-if="zeroY !== null"
          :x1="0" :y1="zeroY"
          :x2="W" :y2="zeroY"
          stroke="#484f58" stroke-width="0.5" stroke-dasharray="2 2" />
    <!-- area-под-кривой (полупрозрачная) -->
    <path :d="areaPath" :fill="areaColor" stroke="none" />
    <!-- line -->
    <polyline :points="points"
              :stroke="lineColor"
              stroke-width="1.4"
              fill="none"
              stroke-linejoin="round" />
    <!-- last point dot -->
    <circle :cx="x(data.length - 1)" :cy="y(data[data.length - 1])"
            r="1.6" :fill="lineColor" />
  </svg>
  <span v-else style="color:#484f58;font-size:.7rem">—</span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  width: { type: Number, default: 80 },
  height: { type: Number, default: 22 },
  title: { type: String, default: '' }
})

const W = computed(() => props.width).value
const H = computed(() => props.height).value
const padTop = 2
const padBottom = 2

const yMin = computed(() => Math.min(0, ...props.data))
const yMax = computed(() => Math.max(0, ...props.data))
const yRange = computed(() => yMax.value - yMin.value || 1)

function x(i) {
  const len = Math.max(1, props.data.length - 1)
  return (i / len) * W
}
function y(v) {
  return padTop + (H - padTop - padBottom) - ((v - yMin.value) / yRange.value) * (H - padTop - padBottom)
}

const points = computed(() => props.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' '))

const areaPath = computed(() => {
  if (props.data.length < 2) return ''
  const pts = props.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' L ')
  const baseY = (0 >= yMin.value && 0 <= yMax.value) ? y(0) : y(yMin.value)
  return `M ${x(0).toFixed(1)},${baseY.toFixed(1)} L ${pts} L ${x(props.data.length - 1).toFixed(1)},${baseY.toFixed(1)} Z`
})

const zeroY = computed(() => {
  if (0 >= yMin.value && 0 <= yMax.value) return y(0)
  return null
})

const lineColor = computed(() => {
  const last = props.data[props.data.length - 1] ?? 0
  return last >= 0 ? '#3fb950' : '#f85149'
})

const areaColor = computed(() =>
  lineColor.value === '#3fb950' ? 'rgba(63,185,80,0.12)' : 'rgba(248,81,73,0.12)'
)
</script>
