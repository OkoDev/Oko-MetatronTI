<template>
  <section>
    <h2>
      Drops — отбракованные сигналы
      <span style="font-size:.75rem;color:#8b949e;font-weight:400">
        (signal_drops table)
      </span>
    </h2>

    <div class="filter-bar" style="margin-bottom:16px;display:flex;align-items:center">
      <label>Окно:</label>
      <select v-model.number="hours" style="margin-left:4px">
        <option :value="1">1ч</option>
        <option :value="6">6ч</option>
        <option :value="24">24ч</option>
        <option :value="72">3д</option>
      </select>
      <button @click="reload" style="margin-left:8px">↻ Обновить</button>
      <span style="color:#8b949e;font-size:.85em;margin-left:auto" v-if="lastFetch">
        обновлено: {{ lastFetch }}
      </span>
    </div>

    <div v-if="loading" class="note">⏳ Загрузка…</div>
    <div v-else-if="error" class="note red">Ошибка: {{ error }}</div>

    <h2 style="margin-top:24px">Топ-{{ drops.length }} причин (за {{ hours }}ч)</h2>
    <div v-if="!drops.length && !loading" class="note">Нет drops за окно.</div>
    <table v-else>
      <thead>
        <tr><th>Gate name</th><th>Drops</th><th>%</th></tr>
      </thead>
      <tbody>
        <tr v-for="d in drops" :key="d.gate_name">
          <td class="mono">{{ d.gate_name }}</td>
          <td><b>{{ d.count }}</b></td>
          <td>
            <span :style="{ color: barColor(d.count, dropTotal) }">{{ pct(d.count, dropTotal) }}%</span>
            <span style="margin-left:8px;display:inline-block;height:6px;background:#21262d;border-radius:3px;width:120px;vertical-align:middle">
              <span :style="{ display:'block', height:'100%', borderRadius:'3px', width: pct(d.count, dropTotal)+'%', background: barColor(d.count, dropTotal) }"></span>
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <h2 style="margin-top:24px">Последние {{ recent.length }} drops</h2>
    <div v-if="!recent.length && !loading" class="note">Нет recent drops.</div>
    <table v-else>
      <thead>
        <tr>
          <th>Время</th>
          <th>Символ</th>
          <th>Gate</th>
          <th>Сигнал</th>
          <th>Напр.</th>
          <th>Причина / детали</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, idx) in recent" :key="idx">
          <td>{{ formatTime(r.ts) }}</td>
          <td class="mono">{{ formatSymbol(r.symbol) }}</td>
          <td class="mono">{{ r.gate_name }}</td>
          <td>{{ r.signal_type ?? '—' }}</td>
          <td :class="dirClass(r.direction)"><b>{{ r.direction ?? '—' }}</b></td>
          <td style="color:#8b949e;font-size:.85em">{{ formatReason(r.reason) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const hours = ref(24)
const drops = ref([])
const recent = ref([])
const loading = ref(false)
const error = ref(null)
const lastFetch = ref(null)

function pct(count, total) {
  return total > 0 ? Math.round(count / total * 100) : 0
}
function barColor(count, total) {
  const p = pct(count, total)
  if (p >= 30) return '#f85149'
  if (p >= 15) return '#d29922'
  return '#58a6ff'
}
const dropTotal = computed(() => drops.value.reduce((s, d) => s + (d.count || 0), 0))

function formatTime(t) {
  return t ? new Date(t).toLocaleString('ru') : '—'
}
function formatSymbol(s) {
  if (!s) return '—'
  return s.replace('-USDT', '/USDT').replace('-', '/')
}
function dirClass(d) {
  return d === 'LONG' ? 'green' : d === 'SHORT' ? 'red' : ''
}
function formatReason(reason) {
  if (!reason) return ''
  if (typeof reason === 'object') {
    try { return JSON.stringify(reason).slice(0, 100) } catch { return '' }
  }
  return String(reason).slice(0, 100)
}

async function fetchWithTimeout(url) {
  const ctrl = new AbortController()
  const timeout = setTimeout(() => ctrl.abort(), 5000)
  try {
    const resp = await fetch(url, { signal: ctrl.signal })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return await resp.json()
  } finally {
    clearTimeout(timeout)
  }
}

async function loadData() {
  loading.value = true
  error.value = null
  const topUrl = `/api/dropped?hours=${hours.value}&limit=20`
  const recentUrl = `/api/dropped?detail=1&hours=${hours.value}&limit=50`
  const [topRes, recentRes] = await Promise.allSettled([
    fetchWithTimeout(topUrl),
    fetchWithTimeout(recentUrl),
  ])

  if (topRes.status === 'fulfilled') {
    drops.value = topRes.value.drops || []
  } else {
    error.value = topRes.reason?.message || 'Ошибка загрузки top drops'
  }

  if (recentRes.status === 'fulfilled') {
    recent.value = recentRes.value.recent || []
  } else if (!error.value) {
    error.value = recentRes.reason?.message || 'Ошибка загрузки recent drops'
  }

  lastFetch.value = new Date().toLocaleTimeString('ru')
  loading.value = false
}

function reload() {
  loadData()
}

watch(hours, loadData)
onMounted(loadData)
</script>
