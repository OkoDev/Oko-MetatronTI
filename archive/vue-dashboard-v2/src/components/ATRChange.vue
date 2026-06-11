<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const loading = ref(true)
const error = ref(false)
const data = ref(null)

let intervalId = null

const defaultStat = {
  closed: 0,
  open: 0,
  wr: 0,
  avg_r: 0,
  total_r: 0,
  best_r: null
}

// loading=true только до первой загрузки — на дальнейших тиках polling-flash «Загрузка…» не нужен.
async function loadData() {
  try {
    const resp = await fetch('/api/atr_stats')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    data.value = await resp.json()
    error.value = false
  } catch (e) {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
  intervalId = setInterval(loadData, 30000)
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})

const tfList = ['1h', '4h', '15m']
const tfColors = {
  '1h': '#f8c400',
  '4h': '#2ea043',
  '15m': '#58a6ff'
}

const cards = computed(() => {
  return tfList.map(tf => {
    const s = (data.value?.atr?.[tf]) ?? defaultStat
    const tfColor = tfColors[tf]

    const wrCls = s.wr >= 50 ? 'green' : s.wr >= 40 ? 'yellow' : 'red'
    const arCls = s.avg_r > 0 ? 'green' : s.avg_r < 0 ? 'red' : ''
    const trCls = s.total_r > 0 ? 'green' : s.total_r < 0 ? 'red' : ''

    const arStr = (s.avg_r >= 0 ? '+' : '') + s.avg_r.toFixed(3) + 'R'
    const trStr = (s.total_r >= 0 ? '+' : '') + s.total_r.toFixed(1) + 'R'
    const bestStr = s.best_r != null
      ? (s.best_r >= 0 ? '+' : '') + s.best_r.toFixed(2) + 'R'
      : '—'

    return { tf, tfColor, s, wrCls, arCls, trCls, arStr, trStr, bestStr }
  })
})
</script>

<template>
  <section>
    <h2>
      ATR Change стратегия
      <span style="font-size:.75rem;color:#8b949e;font-weight:400">
        (R8 backtest: 1h_LONG +0.281R, 4h_SHORT +0.287R)
      </span>
    </h2>

    <div v-if="loading" class="cards">
      <div class="card">
        <div class="label">⏳ Загрузка…</div>
      </div>
    </div>

    <div v-else-if="error" class="cards">
      <p class="note red">Ошибка загрузки ATR метрик</p>
    </div>

    <div v-else class="cards" style="grid-template-columns:repeat(3,1fr)">
      <div
        v-for="card in cards"
        :key="card.tf"
        class="card"
        :style="{ borderColor: card.tfColor + '55', borderLeft: '3px solid ' + card.tfColor }"
      >
        <div class="label" style="display:flex;align-items:center;gap:5px">
          <span :style="{ color: card.tfColor, fontSize: '1rem' }">●</span>
          <span :style="{ color: card.tfColor, fontWeight: 700 }">ATR Change {{ card.tf }}</span>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px">
          <div>
            <div class="label">Сделок</div>
            <div style="font-weight:700;color:#c9d1d9">{{ card.s.closed }}</div>
          </div>
          <div>
            <div class="label">Открытых</div>
            <div style="font-weight:700;color:#c9d1d9">{{ card.s.open }}</div>
          </div>

          <div>
            <div class="label">WR</div>
            <div :class="card.wrCls" style="font-weight:700">{{ card.s.wr.toFixed(1) }}%</div>
          </div>
          <div>
            <div class="label">avg R</div>
            <div :class="card.arCls" style="font-weight:700">{{ card.arStr }}</div>
          </div>

          <div>
            <div class="label">Total R</div>
            <div :class="card.trCls" style="font-weight:700">{{ card.trStr }}</div>
          </div>
          <div>
            <div class="label">Best R</div>
            <div class="green" style="font-weight:700">{{ card.bestStr }}</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
