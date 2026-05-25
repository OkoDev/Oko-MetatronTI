<template>
  <div class="hero-grid">
    <!-- Card 1: BingX Equity -->
    <div class="hero-card" :style="{ borderColor: card1Border }">
      <div class="hc-label">BingX Equity</div>
      <div
        class="hc-val"
        :class="{ blue: !isSim }"
        :style="isSim ? { color: '#8b949e' } : {}"
      >{{ card1Val }}</div>
      <div class="hc-sub" v-html="card1Sub"></div>
    </div>

    <!-- Card 2: Risk Exposure -->
    <div class="hero-card">
      <div class="hc-label">Risk Exposure</div>
      <div class="hc-val" :style="{ color: riskColor }">
        {{ riskVal }}
      </div>
      <div class="hc-sub">{{ riskSub }}</div>
      <div class="hc-bar">
        <div class="hc-bar-fill" :style="{ width: riskBarWidth, backgroundColor: riskColor }"></div>
      </div>
    </div>

    <!-- Card 3: Позиций открыто / WR -->
    <div class="hero-card">
      <div class="hc-label">Позиций открыто / WR</div>
      <div class="hc-val">
        {{ openCount }} <span style="font-size:1.1rem;color:#8b949e;font-weight:400">/ {{ totalCount }}</span>
      </div>
      <div class="hc-row">
        <div class="hc-mini green">TP {{ tpCount }}</div>
        <div class="hc-mini purple">TSL {{ tslCount }}</div>
        <div class="hc-mini red">SL {{ slCount }}</div>
        <div class="hc-mini" style="margin-left:auto;font-size:.95rem;font-weight:700">
          <span :style="{ color: wrColor }">{{ wrVal }}</span>
          <span style="color:#8b949e;font-size:.7rem;font-weight:400"> WR</span>
        </div>
      </div>
    </div>

    <!-- Card 4: Drops за последний час -->
    <div class="hero-card" :style="{ borderColor: '#d2992233' }">
      <div class="hc-label">Drops за последний час</div>
      <div>
        <div v-if="loading" class="hc-sub">загрузка…</div>
        <div v-else-if="error" class="hc-sub">ошибка загрузки</div>
        <div v-else-if="drops && drops.length === 0" class="hc-sub">нет drops за час</div>
        <template v-else>
          <div v-for="item in drops" :key="item.reason" class="hc-mini">
            • <code>{{ item.reason }}</code>: {{ item.count }}
          </div>
          <div class="hc-sub" style="margin-top:6px">
            <RouterLink to="/drops" style="color:#58a6ff;text-decoration:none">все drops →</RouterLink>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'

const props = defineProps({
  summary: { type: Object, default: () => ({}) },
  live: { type: Object, default: () => ({}) }
})

function fmtUsd(v) {
  return '$' + (v || 0).toLocaleString('ru', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtUsdNoCents(v) {
  return '$' + (v || 0).toLocaleString('ru', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

/* Card 1: BingX Equity */
const isSim = computed(() => props.live.mode === 'SIM' || !props.live.balance)
const card1Border = computed(() => (isSim.value ? '#30363d' : '#58a6ff44'))
const card1Val = computed(() => (isSim.value ? 'SIM' : fmtUsd(props.live.balance?.equity)))
const card1Sub = computed(() => {
  if (isSim.value) {
    return 'режим симуляции — биржа не подключена'
  }
  const bal = props.live.balance
  const free = fmtUsd(bal.available)
  const pnl = bal.unrealized_pnl ?? 0
  const pnlSign = pnl >= 0 ? '+' : '-'
  const pnlColor = pnl >= 0 ? '#3fb950' : '#f85149'
  const pnlHtml = `<span style="color:${pnlColor}">${pnlSign}${fmtUsd(Math.abs(pnl))}</span>`
  const marginPart = bal.used_margin > 0
    ? `&nbsp;&nbsp;Маржа: <span style="color:#8b949e">${fmtUsdNoCents(bal.used_margin)}</span>`
    : ''
  const time = props.live.timestamp ? new Date(props.live.timestamp).toLocaleTimeString('ru') : '—'
  const mode = props.live.mode || '—'
  return `Свободно: <b>${free}</b>&nbsp;&nbsp;P&L: ${pnlHtml}${marginPart}<br><span style="color:#484f58;font-size:.68rem">${mode} · ${time}</span>`
})

/* Card 2: Risk Exposure */
const riskPct = computed(() => props.summary.risk_exposure_pct ?? null)
const riskColor = computed(() => {
  const pct = riskPct.value ?? 0
  if (pct > 10) return '#f85149'
  if (pct > 5) return '#d29922'
  return '#3fb950'
})
const riskVal = computed(() => (riskPct.value != null ? `${riskPct.value.toFixed(1)}%` : '—'))
const riskSub = computed(() => {
  const usdt = props.summary.risk_exposure_usdt
  const dep = props.summary.deposit_usdt
  if (usdt != null && dep != null) {
    return `${fmtUsdNoCents(usdt)} из ${fmtUsdNoCents(dep)}`
  }
  return 'нет данных о депозите'
})
const riskBarWidth = computed(() => `${Math.min(riskPct.value || 0, 100)}%`)

/* Card 3: Позиции / WR — поля живут в props.summary.summary (вложенный объект бэкенда). */
const stats = computed(() => props.summary.summary ?? {})
const openCount = computed(() => stats.value.open_count ?? 0)
const totalCount = computed(() => stats.value.total ?? 0)
const tpCount = computed(() => stats.value.tp_count ?? 0)
const tslCount = computed(() => stats.value.tsl_count ?? 0)
const slCount = computed(() => stats.value.sl_count ?? 0)
const winRate = computed(() => stats.value.win_rate ?? null)
const wrVal = computed(() => (winRate.value != null ? `${winRate.value}%` : '—'))
const wrColor = computed(() => {
  if (winRate.value == null) return '#8b949e'
  return winRate.value >= 50 ? '#3fb950' : '#f85149'
})

/* Card 4: Drops за час (свой fetch, 60s polling) */
const drops = ref(null)
const loading = ref(true)
const error = ref(false)
let intervalId = null

async function loadDrops() {
  try {
    const resp = await fetch('/api/dropped?hours=1&limit=3')
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    drops.value = data.top || []
    error.value = false
  } catch (e) {
    error.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDrops()
  intervalId = setInterval(loadDrops, 60000)
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})
</script>
