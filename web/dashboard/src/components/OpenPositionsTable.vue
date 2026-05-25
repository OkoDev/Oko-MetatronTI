<template>
  <div>
    <div v-if="!trades.length" class="note">Нет открытых позиций.</div>
    <table v-else>
      <thead>
        <tr>
          <th class="sortable" :class="sortClass('id')" @click="sortBy('id')">#</th>
          <th class="sortable" :class="sortClass('symbol')" @click="sortBy('symbol')">Символ</th>
          <th class="sortable" :class="sortClass('direction')" @click="sortBy('direction')">Напр.</th>
          <th class="sortable" :class="sortClass('tsl_activated')" @click="sortBy('tsl_activated')">TSL</th>
          <th class="sortable" :class="sortClass('signal_type')" @click="sortBy('signal_type')">Сигнал</th>
          <th class="sortable" :class="sortClass('entry_price')" @click="sortBy('entry_price')">Вход</th>
          <th class="sortable" :class="sortClass('current_price')" @click="sortBy('current_price')">Тек.</th>
          <th class="sortable" :class="sortClass('stop_loss')" @click="sortBy('stop_loss')">SL</th>
          <th class="sortable" :class="sortClass('take_profit')" @click="sortBy('take_profit')">TP</th>
          <th class="sortable" :class="sortClass('unrealized_pct')" @click="sortBy('unrealized_pct')">Δ %</th>
          <th class="sortable" :class="sortClass('unrealized_r')" @click="sortBy('unrealized_r')">R</th>
          <th class="sortable" :class="sortClass('mfe_r')" @click="sortBy('mfe_r')">MFE R</th>
          <th class="sortable" :class="sortClass('strength')" @click="sortBy('strength')">Strength</th>
          <th class="sortable" :class="sortClass('confidence')" @click="sortBy('confidence')">Конф.</th>
          <th class="sortable" :class="sortClass('regime')" @click="sortBy('regime')">Режим</th>
          <th class="sortable" :class="sortClass('created_at')" @click="sortBy('created_at')">Открыта</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in sortedTrades" :key="t.id">
          <td>{{ t.id ?? dash }}</td>
          <td class="mono">{{ formatSymbol(t.symbol) }}</td>
          <td :class="directionClass(t.direction)" style="font-weight: bold;">
            {{ t.direction ?? dash }}
          </td>
          <td>
            <span v-if="t.tsl_activated" class="badge badge-tsl" :title="t.tsl_tf ? `TSL активен на ${t.tsl_tf}` : 'TSL активен'">TSL</span>
            <span v-else style="color:#484f58">—</span>
          </td>
          <td :title="t.signal_type || ''">{{ t.signal_type ?? dash }}</td>
          <td class="mono">{{ formatNumber(t.entry_price) }}</td>
          <td class="mono">{{ formatNumber(t.current_price) }}</td>
          <td class="mono red">{{ formatNumber(t.stop_loss) }}</td>
          <td class="mono green">{{ formatNumber(t.take_profit) }}</td>
          <td :class="signClass(t.unrealized_pct)">{{ formatPct(t.unrealized_pct) }}</td>
          <td :class="signClass(t.unrealized_r)">{{ formatR(t.unrealized_r) }}</td>
          <td :class="signClass(t.mfe_r)">{{ formatR(t.mfe_r) }}</td>
          <td>{{ t.strength ?? dash }}</td>
          <td>{{ formatConfidence(t.confidence) }}</td>
          <td>{{ t.regime ?? dash }}</td>
          <td>{{ formatDate(t.created_at) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  trades: {
    type: Array,
    default: () => []
  }
})

const sort = ref({ key: 'created_at', dir: 'desc' })
const dash = '—'

function sortClass(col) {
  return {
    'sort-asc': sort.value.key === col && sort.value.dir === 'asc',
    'sort-desc': sort.value.key === col && sort.value.dir === 'desc'
  }
}

function sortBy(col) {
  if (sort.value.key === col) {
    sort.value.dir = sort.value.dir === 'asc' ? 'desc' : 'asc'
  } else {
    sort.value.key = col
    sort.value.dir = 'desc'
  }
}

function compareValues(a, b, key) {
  const dir = sort.value.dir === 'asc' ? 1 : -1
  const av = a[key]
  const bv = b[key]

  const aNull = av === null || av === undefined
  const bNull = bv === null || bv === undefined
  if (aNull && bNull) return 0
  if (aNull) return 1
  if (bNull) return -1

  if (key === 'created_at') {
    return (new Date(av) - new Date(bv)) * dir
  }
  if (typeof av === 'number' && typeof bv === 'number') {
    return (av - bv) * dir
  }
  if (typeof av === 'string' && typeof bv === 'string') {
    return av.localeCompare(bv) * dir
  }
  return 0
}

const sortedTrades = computed(() => {
  return [...props.trades].sort((a, b) => compareValues(a, b, sort.value.key))
})

function formatSymbol(sym) {
  if (!sym) return dash
  return sym.replace('-USDT', '/USDT')
}

function directionClass(dir) {
  return dir === 'LONG' ? 'green' : dir === 'SHORT' ? 'red' : ''
}

function signClass(val) {
  if (val == null) return ''
  return val >= 0 ? 'green' : 'red'
}

function formatNumber(val) {
  return val != null ? Number(val).toPrecision(5) : dash
}

function formatPct(val) {
  if (val == null) return dash
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

function formatR(val) {
  if (val == null) return dash
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}R`
}

function formatConfidence(val) {
  if (val == null) return dash
  return `${Math.round(val * 100)}%`
}

function formatDate(val) {
  if (!val) return dash
  return new Date(val).toLocaleString('ru')
}
</script>
