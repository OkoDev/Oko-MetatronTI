<template>
  <div v-if="!rows || rows.length === 0" class="note">Нет данных.</div>
  <table v-else>
    <thead>
      <tr>
        <th class="sortable" :class="sortClass(keyField)" @click="sortBy(keyField)">{{ keyLabel }}</th>
        <th class="sortable" :class="sortClass('total')" @click="sortBy('total')">Сделок</th>
        <th class="sortable" :class="sortClass('tp_count')" @click="sortBy('tp_count')">TP</th>
        <th class="sortable" :class="sortClass('tsl_count')" @click="sortBy('tsl_count')">TSL</th>
        <th class="sortable" :class="sortClass('sl_count')" @click="sortBy('sl_count')">SL</th>
        <th class="sortable" :class="sortClass('wr')" @click="sortBy('wr')">WR%</th>
        <th class="sortable" :class="sortClass('avg_r')" @click="sortBy('avg_r')">Avg R</th>
        <th class="sortable" :class="sortClass('total_r')" @click="sortBy('total_r')">Total R</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in sortedRows" :key="row[keyField]">
        <td class="mono">{{ row[keyField] ?? '—' }}</td>
        <td>{{ row.total ?? '—' }}</td>
        <td class="green">{{ row.tp_count ?? '—' }}</td>
        <td class="purple">{{ row.tsl_count ?? '—' }}</td>
        <td class="red">{{ row.sl_count ?? '—' }}</td>
        <td :class="wrClass(row.wr)">{{ row.wr != null ? row.wr.toFixed(1) + '%' : '—' }}</td>
        <td :class="rClass(row.avg_r)">{{ fmtR(row.avg_r, 3) }}</td>
        <td :class="rClass(row.total_r)">{{ fmtR(row.total_r, 1) }}</td>
      </tr>
    </tbody>
  </table>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  keyField: { type: String, required: true },
  keyLabel: { type: String, default: 'Группа' }
})

const sortKey = ref('total_r')
const sortDir = ref('desc')

function sortBy(field) {
  if (sortKey.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = field
    sortDir.value = 'desc'
  }
}

function sortClass(field) {
  if (sortKey.value !== field) return ''
  return sortDir.value === 'asc' ? 'sort-asc' : 'sort-desc'
}

function compareValues(a, b) {
  const aNull = a === null || a === undefined
  const bNull = b === null || b === undefined
  if (aNull && bNull) return 0
  if (aNull) return 1
  if (bNull) return -1
  if (typeof a === 'string' && typeof b === 'string') return a.localeCompare(b)
  if (a < b) return -1
  if (a > b) return 1
  return 0
}

function wrClass(wr) {
  if (wr == null) return ''
  if (wr >= 50) return 'green'
  if (wr >= 40) return 'yellow'
  return 'red'
}
function rClass(r) {
  if (r == null) return ''
  return r > 0 ? 'green' : r < 0 ? 'red' : ''
}
function fmtR(v, digits) {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return sign + v.toFixed(digits) + 'R'
}

const sortedRows = computed(() => {
  const arr = [...props.rows]
  arr.sort((a, b) => {
    const cmp = compareValues(a[sortKey.value], b[sortKey.value])
    return sortDir.value === 'asc' ? cmp : -cmp
  })
  return arr
})
</script>
