<template>
  <section>
    <h2>
      Decision Trace
      <span style="font-size:.75rem;color:#8b949e;font-weight:400">
        «Why did the bot do X?»
      </span>
    </h2>

    <div class="filter-bar" style="margin-bottom:16px">
      <label>Trade ID:</label>
      <input v-model.number="manualId" type="number" placeholder="14814" style="width:120px"
             @keyup.enter="load(manualId)" />
      <button @click="load(manualId)">Загрузить</button>
      <span v-if="trade" style="color:#8b949e;font-size:.85em;margin-left:14px">
        ↳ #{{ trade.id }} {{ formatSymbol(trade.symbol) }} {{ trade.direction }}
      </span>
    </div>

    <div v-if="loading" class="note">⏳ Загрузка trace…</div>
    <div v-else-if="error" class="note red">{{ error }}</div>
    <div v-else-if="!trade" class="note">Введите Trade ID для отображения trace.</div>

    <div v-else>
      <!-- Header card -->
      <div class="card" style="margin-bottom:18px">
        <div class="label">Сделка</div>
        <div style="font-size:1.2rem;font-weight:700;margin-bottom:6px">
          #{{ trade.id }} · {{ formatSymbol(trade.symbol) }} ·
          <span :class="dirClass">{{ trade.direction }}</span>
          @ <span v-html="formatStatus(trade.status)"></span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:14px;font-size:.88rem;color:#c9d1d9">
          <span>Сигнал: <code>{{ trade.signal_type }}</code></span>
          <span>Стратегия: <code>{{ trade.strategy_name || '—' }}</code></span>
          <span>Strength: <b>{{ trade.strength ?? '—' }}</b></span>
          <span>Конф.: <b>{{ formatConfidence(trade.confidence) }}</b></span>
          <span>Режим: <code>{{ trade.regime || '—' }}</code></span>
          <span>Создана: {{ formatDate(trade.created_at) }}</span>
        </div>
      </div>

      <!-- Gates -->
      <h2 style="border-bottom:1px solid #21262d;padding-bottom:6px;margin-bottom:12px">Цепочка решений (gates)</h2>
      <div v-if="!gates.length" class="note">decision_trace_json пуст (или сделка была создана до DEV-203).</div>
      <div v-else style="font-family:monospace;font-size:.86rem;line-height:1.7">
        <div v-for="(g, i) in gates" :key="i" :style="{ color: g.passed ? '#3fb950' : '#f85149' }">
          <span style="display:inline-block;width:14px">{{ g.passed ? '✓' : '✗' }}</span>
          <b>GATE: {{ g.name }}</b>
          <span style="color:#8b949e;margin-left:6px">{{ gateSummary(g) }}</span>
        </div>
      </div>

      <!-- Confirmations -->
      <h2 style="border-bottom:1px solid #21262d;padding-bottom:6px;margin:24px 0 12px">Подтверждения (confirmations)</h2>
      <div v-if="!confirmations.length" class="note">Нет confirmations в features_json.</div>
      <table v-else>
        <thead>
          <tr><th>Источник</th><th>Вес</th><th>Конф.</th><th>Evidence</th><th>Время</th></tr>
        </thead>
        <tbody>
          <tr v-for="(c, i) in confirmations" :key="i">
            <td><code>{{ c.source }}</code></td>
            <td>{{ c.weight ?? '—' }}</td>
            <td>{{ formatConfidence(c.confidence) }}</td>
            <td style="max-width:260px;color:#8b949e">{{ formatEvidence(c.evidence) }}</td>
            <td>{{ c.ts ? formatDate(c.ts) : '—' }}</td>
          </tr>
        </tbody>
      </table>

      <!-- Raw features_json -->
      <details class="section-collapsible" style="margin-top:20px">
        <summary>features_json (raw)</summary>
        <pre style="background:#0d1117;padding:12px;border-radius:6px;color:#c9d1d9;font-size:.78rem;overflow:auto;max-height:400px">{{ formattedFeatures }}</pre>
      </details>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const manualId = ref(null)
const loading = ref(false)
const error = ref('')
const trade = ref(null)

function formatSymbol(s) {
  return s?.replace('-USDT', '/USDT') || '—'
}

function formatStatus(s) {
  const map = {
    TP: 'badge-tp',
    SL: 'badge-sl',
    TSL: 'badge-tsl',
    EXPIRED: 'badge-exp',
    OPEN: 'badge-open'
  }
  const cls = map[s] || 'badge-open'
  return `<span class="badge ${cls}">${s ?? '—'}</span>`
}

function formatConfidence(c) {
  return c != null ? Math.round(c * 100) + '%' : '—'
}

function formatDate(d) {
  return d ? new Date(d).toLocaleString('ru') : '—'
}

function gateSummary(g) {
  if (g.value != null && g.threshold != null) {
    return `(${g.value} ${g.passed ? '≥' : '<'} ${g.threshold})`
  }
  if (g.details) return g.details
  return ''
}

function formatEvidence(e) {
  if (e == null) return ''
  let str = typeof e === 'object' ? JSON.stringify(e) : String(e)
  if (str.length > 80) return str.slice(0, 77) + '…'
  return str
}

const dirClass = computed(() => {
  if (trade.value?.direction === 'LONG') return 'green'
  if (trade.value?.direction === 'SHORT') return 'red'
  return ''
})

const gates = computed(() => {
  return trade.value?.decision_trace_json?.gates || []
})

const confirmations = computed(() => {
  const dtConf = trade.value?.decision_trace_json?.confirmations || []
  const ftConf = trade.value?.features_json?.confirmations || []
  return ftConf.length ? ftConf : dtConf
})

const formattedFeatures = computed(() => {
  const f = trade.value?.features_json
  return f ? JSON.stringify(f, null, 2) : '—'
})

async function load(id) {
  if (!id) return
  loading.value = true
  error.value = ''
  trade.value = null
  try {
    const resp = await fetch(`/api/trades/${id}/trace`)
    if (!resp.ok) {
      if (resp.status === 404) throw new Error('Сделка не найдена')
      throw new Error(`Ошибка ${resp.status}`)
    }
    trade.value = await resp.json()
    if (route.params.id !== String(id)) {
      router.replace(`/trades/${id}`)
    }
  } catch (e) {
    error.value = e.message || 'Неизвестная ошибка'
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.id,
  (newId) => {
    if (newId) {
      manualId.value = Number(newId)
      load(newId)
    }
  },
  { immediate: true }
)
</script>
