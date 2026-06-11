<template>
  <div>
    <div v-if="loading && !trades.length" class="note">⏳ Загрузка…</div>
    <div v-else-if="error" class="note red">Ошибка: {{ error }}</div>
    <div v-else-if="!trades.length" class="note">Нет закрытых сделок.</div>

    <table v-if="trades.length">
      <thead>
        <tr>
          <th class="sortable" @click="sortBy('id')" :class="sortClass('id')">#</th>
          <th class="sortable" @click="sortBy('symbol')" :class="sortClass('symbol')">Символ</th>
          <th class="sortable" @click="sortBy('direction')" :class="sortClass('direction')">Напр.</th>
          <th class="sortable" @click="sortBy('signal_type')" :class="sortClass('signal_type')">Сигнал</th>
          <th class="sortable" @click="sortBy('status')" :class="sortClass('status')">Статус</th>
          <th class="sortable" @click="sortBy('entry_price')" :class="sortClass('entry_price')">Вход</th>
          <th class="sortable" @click="sortBy('exit_price')" :class="sortClass('exit_price')">Выход</th>
          <th class="sortable" @click="sortBy('profit_pct')" :class="sortClass('profit_pct')">Δ %</th>
          <th class="sortable" @click="sortBy('R_multiple')" :class="sortClass('R_multiple')">R</th>
          <th class="sortable" @click="sortBy('max_R_possible')" :class="sortClass('max_R_possible')">MFE R</th>
          <th class="sortable" @click="sortBy('captured_R_pct')" :class="sortClass('captured_R_pct')">Capt%</th>
          <th class="sortable" @click="sortBy('strength')" :class="sortClass('strength')">Strength</th>
          <th class="sortable" @click="sortBy('confidence')" :class="sortClass('confidence')">Конф.</th>
          <th class="sortable" @click="sortBy('regime')" :class="sortClass('regime')">Режим</th>
          <th class="sortable" @click="sortBy('duration_minutes')" :class="sortClass('duration_minutes')">Длит.</th>
          <th class="sortable" @click="sortBy('closed_at')" :class="sortClass('closed_at')">Закрыта</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="trade in sortedTrades" :key="trade.id">
          <td>{{ trade.id ?? '—' }}</td>
          <td class="mono">{{ formatSymbol(trade.symbol) }}</td>
          <td :class="directionClass(trade.direction)"><b>{{ trade.direction ?? '—' }}</b></td>
          <td>{{ trade.signal_type ?? '—' }}</td>
          <td v-html="statusBadge(trade.status)"></td>
          <td class="mono">{{ formatNumber(trade.entry_price) }}</td>
          <td class="mono">{{ formatNumber(trade.exit_price) }}</td>
          <td :class="signClass(trade.profit_pct)">{{ formatPct(trade.profit_pct) }}</td>
          <td :class="signClass(trade.R_multiple)">{{ formatR(trade.R_multiple) }}</td>
          <td class="mono">{{ formatR(trade.max_R_possible) }}</td>
          <td>{{ formatCaptured(trade.captured_R_pct) }}</td>
          <td>{{ trade.strength ?? '—' }}</td>
          <td>{{ formatConfidence(trade.confidence) }}</td>
          <td>{{ trade.regime ?? '—' }}</td>
          <td>{{ formatDuration(trade.duration_minutes) }}</td>
          <td>{{ formatDate(trade.closed_at) }}</td>
        </tr>
      </tbody>
    </table>

    <div class="filter-bar" style="justify-content:space-between;margin-top:12px">
      <div>
        <label>На странице:</label>
        <select :value="perPage" @change="$emit('per-page-change', Number($event.target.value))">
          <option :value="25">25</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
        </select>
        <span style="color:#8b949e;font-size:.85em;margin-left:12px">
          Всего: <b style="color:#c9d1d9">{{ total }}</b>
        </span>
      </div>
      <div>
        <button :disabled="page <= 1" @click="$emit('prev')">← Предыдущая</button>
        <span style="margin:0 12px">Стр. {{ page }} / {{ totalPages }}</span>
        <button :disabled="page >= totalPages" @click="$emit('next')">Следующая →</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  trades: { type: Array, default: () => [] },
  page: { type: Number, default: 1 },
  perPage: { type: Number, default: 50 },
  total: { type: Number, default: 0 },
  totalPages: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null }
})

defineEmits(['prev', 'next', 'per-page-change'])

const sort = ref({ key: 'closed_at', dir: 'desc' })

function sortBy(key) {
  if (sort.value.key === key) {
    sort.value.dir = sort.value.dir === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value.key = key
    sort.value.dir = 'desc'
  }
}

function sortClass(col) {
  return {
    'sort-asc': sort.value.key === col && sort.value.dir === 'asc',
    'sort-desc': sort.value.key === col && sort.value.dir === 'desc'
  }
}

function compareValues(a, b, key, dir) {
  const av = a[key]
  const bv = b[key]

  const order = dir === 'asc' ? 1 : -1

  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1

  if (key === 'created_at' || key === 'closed_at') {
    return (new Date(av) - new Date(bv)) * order
  }

  if (typeof av === 'number' && typeof bv === 'number') {
    return (av - bv) * order
  }

  if (typeof av === 'string' && typeof bv === 'string') {
    return av.localeCompare(bv) * order
  }

  return 0
}

const sortedTrades = computed(() => {
  return [...props.trades].sort((a, b) =>
    compareValues(a, b, sort.value.key, sort.value.dir)
  )
})

// ---------- format helpers ----------
function formatSymbol(sym) {
  if (!sym) return '—'
  return sym.replace('-USDT', '/USDT')
}

function formatNumber(val) {
  return val != null ? Number(val).toPrecision(5) : '—'
}

function formatPct(val) {
  if (val == null) return '—'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

function signClass(val) {
  if (val == null) return ''
  return val >= 0 ? 'green' : 'red'
}

function formatR(val) {
  if (val == null) return '—'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}R`
}

function formatCaptured(val) {
  return val != null ? `${Math.round(val)}%` : '—'
}

function formatConfidence(val) {
  return val != null ? `${Math.round(val * 100)}%` : '—'
}

function formatDuration(mins) {
  if (mins == null) return '—'
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}ч ${m}м` : `${m}м`
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleString('ru')
}

function directionClass(dir) {
  return dir === 'LONG' ? 'green' : dir === 'SHORT' ? 'red' : ''
}

function statusBadge(status) {
  const map = {
    TP: '<span class="badge badge-tp">TP</span>',
    SL: '<span class="badge badge-sl">SL</span>',
    TSL: '<span class="badge badge-tsl">TSL</span>',
    EXPIRED: '<span class="badge badge-exp">EXPIRED</span>'
  }
  return map[status] || '—'
}
</script>
